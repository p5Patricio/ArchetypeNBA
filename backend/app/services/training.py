import math
import unicodedata
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
from sqlmodel import Session, select
from app.models import Player, PlayerSeasonStats, Season, Team, PlayerAdvancedStats
from app.services.clustering import ROLE_METADATA
from app.schemas import (
    TrainingAnalysisResponse,
    DrillRecommendation,
    StatGapItem,
    RoleFulfillment,
    TrainingRegimePlan,
)


def _normalize_str(s: str) -> str:
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    return (
        "".join(c for c in nfkd if not unicodedata.combining(c))
        .lower()
        .replace("'", "")
        .replace("’", "")
        .replace("-", "")
        .replace(".", "")
        .replace(" ", "")
        .strip()
    )


# Comprehensive NBA Professional Drills Catalog
DRILLS_CATALOG: Dict[str, List[Dict[str, Any]]] = {
    "FG3_PCT": [
        {
            "id": "drill_spotup_3pt",
            "name_es": "Maestría en Triples Catch & Shoot (5 Puntos)",
            "name_en": "5-Spot Catch & Shoot 3PT Mastery",
            "category": "shooting",
            "stat_target": "FG3_PCT",
            "intensity": "high",
            "sets_and_reps": "5 series x 20 tiros (100 totales) desde esquinas, alas y tope",
            "description_es": "Lanzamientos a máxima velocidad de recepción con pase en movimiento. Foco en colocación de pies ('hop' o '1-2'), arco de 45° y alineación de codo.",
            "description_en": "High-tempo catch-and-shoot release from game-speed passes. Focus on footwork rhythm, 45-degree arc, and elbow alignment.",
            "projected_impact_es": "+2.5% a +4.0% de efectividad en triples exteriores",
            "projected_impact_en": "+2.5% to +4.0% 3PT shooting efficiency",
        },
        {
            "id": "drill_relocation_3pt",
            "name_es": "Reubicación y Tiro en Transición Rápida",
            "name_en": "Relocation & Quick-Trigger Flare 3s",
            "category": "shooting",
            "stat_target": "FG3_PCT",
            "intensity": "high",
            "sets_and_reps": "6 series x 10 repeticiones con sprint a la esquina",
            "description_es": "Sprint desde pintura hacia el perímetro simulando descarga del base o pick-and-pop, cuadrando el cuerpo en menos de 0.7 segundos.",
            "description_en": "Sprint from paint to perimeter simulating kick-out or pick-and-pop, squaring shoulders in under 0.7 seconds.",
            "projected_impact_es": "Mayor consistencia en tiros con poco espacio y ritmo acelerado",
            "projected_impact_en": "Higher consistency on contested, high-pace perimeter shots",
        },
    ],
    "FG_PCT": [
        {
            "id": "drill_rim_finishing",
            "name_es": "Finalizaciones en Tráfico con Contacto",
            "name_en": "Contested Rim & Traffic Finishing",
            "category": "shooting",
            "stat_target": "FG_PCT",
            "intensity": "elite",
            "sets_and_reps": "4 series x 15 finalizaciones (flotadoras, bandejas pasadas, extensiones)",
            "description_es": "Ataques verticales a la pintura con defensor usando almohadilla de impacto. Absorber contacto y finalizar con ambas manos.",
            "description_en": "Vertical drives into the paint with contact pad resistance. Absorbing impact and converting with soft touch on both hands.",
            "projected_impact_es": "+3.0% en porcentaje de tiro en la zona restringida",
            "projected_impact_en": "+3.0% conversion rate inside the restricted area",
        },
        {
            "id": "drill_midrange_pullup",
            "name_es": "Pull-Up de Media Distancia tras Separación",
            "name_en": "Mid-Range Deceleration & Pull-Up",
            "category": "shooting",
            "stat_target": "FG_PCT",
            "intensity": "standard",
            "sets_and_reps": "5 series x 12 tiros desde codos de zona",
            "description_es": "Drible en penetración, parada en un tiempo (jump-stop) con elevación limpia sobre la marca.",
            "description_en": "Drive, sudden hard deceleration into a 1-count jump-stop with balanced vertical elevation.",
            "projected_impact_es": "+2.0% en tiros de 2 puntos disputados",
            "projected_impact_en": "+2.0% on contested 2-point pull-ups",
        },
    ],
    "FT_PCT": [
        {
            "id": "drill_pressure_ft",
            "name_es": "Tiros Libres Bajo Fatiga Cardiovascular",
            "name_en": "High-Heart-Rate Clutch Free Throws",
            "category": "shooting",
            "stat_target": "FT_PCT",
            "intensity": "high",
            "sets_and_reps": "10 series x 2 tiros libres tras suicidio de cancha completa (100% exigencia)",
            "description_es": "Rutina fija de 3 botes y respiración diafragmática para mantener el pulso bajo control con pulsaciones sobre 170 bpm. Penalización por fallo.",
            "description_en": "Fixed 3-dribble routine and diaphragmatic breathing to stabilize mechanics with heart rate above 170 bpm. Sprint penalty on misses.",
            "projected_impact_es": "+4.0% a +6.5% de acierto en la línea de libres",
            "projected_impact_en": "+4.0% to +6.5% free-throw accuracy in clutch situations",
        },
    ],
    "TOV": [
        {
            "id": "drill_twoball_handling",
            "name_es": "Manejo de Dos Balones contra Presión Asfixiante",
            "name_en": "Dual-Ball Full-Court Pressure Control",
            "category": "playmaking",
            "stat_target": "TOV",
            "intensity": "elite",
            "sets_and_reps": "4 bloques x 4 minutos de dribleo continuo con cambios de ritmo",
            "description_es": "Dribleo simultáneo y alternado a diferentes alturas con resistencia elástica y estímulos visuales para forzar la visión periférica.",
            "description_en": "Simultaneous and alternating dribbling at varying heights with resistance bands and visual reaction cues.",
            "projected_impact_es": "Reducción de 12% a 18% en pérdidas por mal manejo de balón",
            "projected_impact_en": "12% to 18% reduction in unforced ball-handling turnovers",
        },
        {
            "id": "drill_pnr_read",
            "name_es": "Lectura de Coberturas de Pick & Roll en < 1.2 Segundos",
            "name_en": "Rapid Pick-and-Roll Coverage Blitz Simulator",
            "category": "playmaking",
            "stat_target": "TOV",
            "intensity": "high",
            "sets_and_reps": "25 posesiones de P&R contra defensas Drop, Hedge, Blitz y Trap",
            "description_es": "Toma de decisiones instantánea para identificar el pase de bolsillo (pocket pass), el pase a la esquina opuesta (skip pass) o el tiro.",
            "description_en": "Split-second decision making against varied pick-and-roll defensive schemes (Drop, Blitz, Switch).",
            "projected_impact_es": "Mayor ratio de Asistencias/Pérdidas y menor riesgo en pases forzados",
            "projected_impact_en": "Improved AST/TOV ratio and safer high-leverage passing reads",
        },
    ],
    "AST": [
        {
            "id": "drill_drive_kick",
            "name_es": "Penetración, Atracción Defensiva y Pase de Descarga",
            "name_en": "Drive, Collapse & Precision Kick-Outs",
            "category": "playmaking",
            "stat_target": "AST",
            "intensity": "standard",
            "sets_and_reps": "5 series x 10 repeticiones con defensores rotando",
            "description_es": "Atacar la pintura para provocar la ayuda del lado débil y enviar un pase con una mano directo al pecho del tirador abierto.",
            "description_en": "Collapse the interior defense and deliver live-dribble one-hand bullet passes to open weakside shooters.",
            "projected_impact_es": "+1.2 a +2.0 asistencias por partido",
            "projected_impact_en": "+1.2 to +2.0 assists per game",
        },
    ],
    "REB": [
        {
            "id": "drill_boxout_anchor",
            "name_es": "Bloqueo de Rebote Físico y Palanca de Cadera",
            "name_en": "Hip-Leverage Defensive Box-Out & Seal",
            "category": "rebounding",
            "stat_target": "REB",
            "intensity": "high",
            "sets_and_reps": "5 series x 10 batallas de rebote 1v1 y 2v2",
            "description_es": "Contacto inicial con el antebrazo, rotación de cadera para sellar al rival y captura del rebote en el punto más alto con dos manos.",
            "description_en": "Forearm check, hip torque to establish low-center seal, and two-handed secure grab at maximum vertical reach.",
            "projected_impact_es": "+1.5 a +2.8 rebotes totales por juego",
            "projected_impact_en": "+1.5 to +2.8 total rebounds per game",
        },
        {
            "id": "drill_second_jump",
            "name_es": "Segundo Salto Explosivo y Rebote Ofensivo",
            "name_en": "Quick Second-Jump Offensive Rebounding",
            "category": "rebounding",
            "stat_target": "REB",
            "intensity": "elite",
            "sets_and_reps": "4 series x 12 saltos reactivos sobre el aro",
            "description_es": "Cargar el rebote ofensivo en cuanto el balón toca el aro y realizar un segundo salto inmediato sin fase de frenado.",
            "description_en": "Crash offensive glass with immediate plyometric second-jump reaction off missed shots.",
            "projected_impact_es": "+0.8 a +1.4 rebotes ofensivos que generan segundas oportunidades",
            "projected_impact_en": "+0.8 to +1.4 offensive boards generating second-chance points",
        },
    ],
    "STL": [
        {
            "id": "drill_deflection_lanes",
            "name_es": "Anticipación en Líneas de Pase y Desvío de Balón",
            "name_en": "Passing Lane Anticipation & Deflections",
            "category": "defense",
            "stat_target": "STL",
            "intensity": "high",
            "sets_and_reps": "6 series x 8 rotaciones de lado débil en situaciones 3v3",
            "description_es": "Lectura visual de la postura del pasador rival y arranque explosivo en primera zancada para cortar la trayectoria sin descolocarse.",
            "description_en": "Reading passer cues and launching first-step explosion to deflect passes without giving up back-door cuts.",
            "projected_impact_es": "+0.4 a +0.7 robos y mayor número de deflexiones defensivas",
            "projected_impact_en": "+0.4 to +0.7 steals and increased total defensive deflections",
        },
    ],
    "BLK": [
        {
            "id": "drill_verticality_wall",
            "name_es": "Verticalidad y Protección de Aro sin Falta",
            "name_en": "Rule of Verticality & Rim Deterrence",
            "category": "defense",
            "stat_target": "BLK",
            "intensity": "elite",
            "sets_and_reps": "5 series x 10 defensas de penetración directa al semicírculo",
            "description_es": "Saltar estrictamente vertical con los brazos extendidos a 90° sin inclinarse hacia adelante. Intimidar el tiro y proteger el aro sin cometer falta personal.",
            "description_en": "Straight vertical elevation inside the charge circle, arms perpendicular to the floor, contesting shots without fouling.",
            "projected_impact_es": "+0.5 a +1.0 tapones y reducción del porcentaje de tiro rival en el aro",
            "projected_impact_en": "+0.5 to +1.0 blocks and reduced opponent field goal % at the rim",
        },
    ],
    "PF": [
        {
            "id": "drill_discipline_closeout",
            "name_es": "Closeout Disciplinado sin Picar en el Amague",
            "name_en": "Controlled Closeout & Pump-Fake Discipline",
            "category": "defense",
            "stat_target": "PF",
            "intensity": "standard",
            "sets_and_reps": "6 series x 10 recuperaciones defensivas",
            "description_es": "Pasos cortos de frenado (choppy steps), una mano arriba para contestar el tiro y mantener el centro de gravedad bajo para no saltar en el amague.",
            "description_en": "Choppy deceleration steps, high hand contest, keeping base wide and feet grounded on ball fakes.",
            "projected_impact_es": "Reducción de 0.6 a 1.0 faltas personales por partido",
            "projected_impact_en": "Reduction of 0.6 to 1.0 personal fouls per game",
        },
    ],
    "MIN": [
        {
            "id": "drill_game_conditioning",
            "name_es": "Acondicionamiento Físico Intervalado de Alta Intensidad",
            "name_en": "High-Intensity NBA Match-Pace Conditioning",
            "category": "conditioning",
            "stat_target": "MIN",
            "intensity": "elite",
            "sets_and_reps": "6 bloques x 3 minutos de circuito táctico continuo",
            "description_es": "Combinación de sprints de transición, retroceso defensivo, flexiones y tiro en fatiga extrema.",
            "description_en": "Combined transition sprints, back-pedal defensive slides, and fatigue shooting circuits.",
            "projected_impact_es": "Mayor resistencia física para mantener 30+ minutos de impacto constante",
            "projected_impact_en": "Enhanced stamina to maintain peak two-way production across 30+ MPG",
        },
    ],
}


class TrainingService:
    def __init__(self, session: Session):
        self.session = session

    def _infer_position_group(self, position: Optional[str], height_cm: Optional[int], archetype_id: Optional[int]) -> Tuple[str, str]:
        """
        Infers exact position label (PG, SG, SF, PF, C) and general group (Guard, Forward, Center).
        """
        pos = (position or "").strip().upper()

        if pos in ["PG", "POINT GUARD", "BASE"]:
            return "PG", "Guard"
        if pos in ["SG", "SHOOTING GUARD", "ESCOLTA"]:
            return "SG", "Guard"
        if pos in ["SF", "SMALL FORWARD", "ALERO"]:
            return "SF", "Forward"
        if pos in ["PF", "POWER FORWARD", "ALA-PIVOT"]:
            return "PF", "Forward"
        if pos in ["C", "CENTER", "PIVOT"]:
            return "C", "Center"

        if "G" in pos and "F" not in pos:
            return "PG", "Guard"
        if "C" in pos:
            return "C", "Center"
        if "F" in pos:
            return "SF", "Forward"

        # Fallback using archetype or height
        if archetype_id in [0, 2]:
            return "C", "Center"
        elif archetype_id in [1, 6]:
            return "PG", "Guard"
        elif archetype_id in [4, 5]:
            return "SG", "Guard"
        elif archetype_id == 3:
            return "SF", "Forward"

        if height_cm:
            if height_cm >= 208:
                return "C", "Center"
            elif height_cm >= 198:
                return "SF", "Forward"
            else:
                return "PG", "Guard"

        return "SF", "Forward"

    def get_training_analysis(
        self,
        player_name: str,
        season_id: Optional[int] = None,
        intensity: str = "standard",
    ) -> TrainingAnalysisResponse:
        # Find player using robust exact and normalized match
        player = self.session.exec(select(Player).where(Player.full_name == player_name)).first()
        if not player:
            clean_target = _normalize_str(player_name)
            all_players = self.session.exec(select(Player)).all()
            candidates = []
            for p in all_players:
                clean_p = _normalize_str(p.full_name)
                if clean_p == clean_target:
                    candidates.append((p, 3))
                elif clean_p.startswith(clean_target) or clean_target.startswith(clean_p):
                    candidates.append((p, 2))
                elif clean_target in clean_p or clean_p in clean_target:
                    candidates.append((p, 1))

            if candidates:
                stats_map = {}
                for p, _ in candidates:
                    st_count = len(
                        self.session.exec(
                            select(PlayerSeasonStats).where(PlayerSeasonStats.player_id == p.id)
                        ).all()
                    )
                    stats_map[p.id] = st_count

                candidates.sort(key=lambda x: (x[1], stats_map.get(x[0].id, 0)), reverse=True)
                player = candidates[0][0]

        if not player:
            raise ValueError(f"Player '{player_name}' not found")


        # Find player stats for the season
        stats_all = self.session.exec(
            select(PlayerSeasonStats).where(PlayerSeasonStats.player_id == player.id)
        ).all()
        if not stats_all:
            raise ValueError(f"No stats found for player '{player.full_name}'")

        if season_id:
            player_stat = next((s for s in stats_all if s.season_id == season_id), None)
        else:
            player_stat = stats_all[0]

        if not player_stat:
            player_stat = stats_all[0]

        eff_season_id = player_stat.season_id
        season_obj = self.session.get(Season, eff_season_id)
        season_label = season_obj.season_label if season_obj else f"Season {eff_season_id}"
        team_obj = self.session.get(Team, player_stat.team_id) if player_stat.team_id else None
        team_abbr = team_obj.abbreviation if team_obj else "NBA"
        team_full = team_obj.full_name if team_obj else "NBA"

        # Determine Archetype and Position
        arch_id = player_stat.cluster_id if player_stat.cluster_id is not None else 3
        arch_meta = ROLE_METADATA.get(arch_id, ROLE_METADATA[3])
        arch_name_es = arch_meta["name_es"]
        arch_name_en = arch_meta["name_en"]
        arch_color = arch_meta["color"]

        pos_specific, pos_group = self._infer_position_group(
            player.position, player.height_cm, arch_id
        )

        # Player Per-Game metrics
        gp = max(player_stat.gp or 1, 1)
        p_pts = round((player_stat.pts or 0.0) / gp, 1)
        p_reb = round((player_stat.reb or 0.0) / gp, 1)
        p_oreb = round((player_stat.oreb or 0.0) / gp, 1)
        p_dreb = round((player_stat.dreb or 0.0) / gp, 1)
        p_ast = round((player_stat.ast or 0.0) / gp, 1)
        p_stl = round((player_stat.stl or 0.0) / gp, 1)
        p_blk = round((player_stat.blk or 0.0) / gp, 1)
        p_tov = round((player_stat.tov or 0.0) / gp, 1)
        p_pf = round((player_stat.pf or 0.0) / gp, 1)
        p_fg3m = round((player_stat.fg3m or 0.0) / gp, 1)
        p_min = round((player_stat.min or 0.0) / gp, 1)
        p_fg_pct = round(player_stat.fg_pct or 0.44, 3)
        p_fg3_pct = round(player_stat.fg3_pct or 0.32, 3)
        p_ft_pct = round(player_stat.ft_pct or 0.75, 3)

        player_metrics = {
            "pts": p_pts,
            "reb": p_reb,
            "oreb": p_oreb,
            "dreb": p_dreb,
            "ast": p_ast,
            "stl": p_stl,
            "blk": p_blk,
            "tov": p_tov,
            "pf": p_pf,
            "fg3m": p_fg3m,
            "min": p_min,
            "fg_pct": p_fg_pct,
            "fg3_pct": p_fg3_pct,
            "ft_pct": p_ft_pct,
        }

        # Fetch Positional Cohort
        season_stats_all = self.session.exec(
            select(PlayerSeasonStats).where(PlayerSeasonStats.season_id == eff_season_id)
        ).all()

        cohort_stats: List[PlayerSeasonStats] = []
        for s in season_stats_all:
            if s.player_id == player.id:
                continue
            if not s.player:
                p_item = self.session.get(Player, s.player_id)
            else:
                p_item = s.player
            if not p_item:
                continue

            item_pos_spec, item_pos_grp = self._infer_position_group(
                p_item.position, p_item.height_cm, s.cluster_id
            )
            # Match by specific position or group
            if item_pos_grp == pos_group or s.cluster_id == arch_id:
                cohort_stats.append(s)

        # Fallback if cohort is too small (expand across seasons)
        if len(cohort_stats) < 5:
            all_historical_stats = self.session.exec(select(PlayerSeasonStats)).all()
            for s in all_historical_stats:
                if s.player_id == player.id:
                    continue
                p_item = self.session.get(Player, s.player_id)
                if not p_item:
                    continue
                _, item_grp = self._infer_position_group(p_item.position, p_item.height_cm, s.cluster_id)
                if item_grp == pos_group:
                    cohort_stats.append(s)
                if len(cohort_stats) >= 50:
                    break

        total_peers = len(cohort_stats)

        # Compute Positional Benchmarks (Mean, Median, P75)
        def _get_pg_list(field: str, is_pct: bool = False) -> List[float]:
            vals = []
            for s in cohort_stats:
                c_gp = max(s.gp or 1, 1)
                if is_pct:
                    v = getattr(s, field, 0.0)
                    if v is not None and v > 0.0:
                        vals.append(float(v))
                else:
                    raw = getattr(s, field, 0.0) or 0.0
                    vals.append(round(raw / c_gp, 2))
            return vals or [1.0]

        cohort_pts = _get_pg_list("pts")
        cohort_reb = _get_pg_list("reb")
        cohort_oreb = _get_pg_list("oreb")
        cohort_dreb = _get_pg_list("dreb")
        cohort_ast = _get_pg_list("ast")
        cohort_stl = _get_pg_list("stl")
        cohort_blk = _get_pg_list("blk")
        cohort_tov = _get_pg_list("tov")
        cohort_pf = _get_pg_list("pf")
        cohort_fg3m = _get_pg_list("fg3m")
        cohort_min = _get_pg_list("min")
        cohort_fg_pct = _get_pg_list("fg_pct", is_pct=True)
        cohort_fg3_pct = _get_pg_list("fg3_pct", is_pct=True)
        cohort_ft_pct = _get_pg_list("ft_pct", is_pct=True)

        benchmark_dict = {
            "pts": round(float(np.mean(cohort_pts)), 1),
            "reb": round(float(np.mean(cohort_reb)), 1),
            "oreb": round(float(np.mean(cohort_oreb)), 1),
            "dreb": round(float(np.mean(cohort_dreb)), 1),
            "ast": round(float(np.mean(cohort_ast)), 1),
            "stl": round(float(np.mean(cohort_stl)), 1),
            "blk": round(float(np.mean(cohort_blk)), 1),
            "tov": round(float(np.mean(cohort_tov)), 1),
            "pf": round(float(np.mean(cohort_pf)), 1),
            "fg3m": round(float(np.mean(cohort_fg3m)), 1),
            "min": round(float(np.mean(cohort_min)), 1),
            "fg_pct": round(float(np.mean(cohort_fg_pct)), 3),
            "fg3_pct": round(float(np.mean(cohort_fg3_pct)), 3),
            "ft_pct": round(float(np.mean(cohort_ft_pct)), 3),
        }

        # Analyze Stat Gaps
        stat_configs = [
            ("pts", "Puntos por Partido", "Points Per Game", cohort_pts, False),
            ("reb", "Rebotes Totales", "Total Rebounds", cohort_reb, False),
            ("ast", "Asistencias", "Assists", cohort_ast, False),
            ("stl", "Robos de Balón", "Steals", cohort_stl, False),
            ("blk", "Bloqueos / Tapones", "Blocks", cohort_blk, False),
            ("fg3m", "Triples Anotados", "3-Pointers Made", cohort_fg3m, False),
            ("fg_pct", "% Tiro de Campo", "Field Goal %", cohort_fg_pct, True),
            ("fg3_pct", "% Triples", "3-Point %", cohort_fg3_pct, True),
            ("ft_pct", "% Tiros Libres", "Free Throw %", cohort_ft_pct, True),
            ("tov", "Pérdidas de Balón", "Turnovers", cohort_tov, False),
            ("pf", "Faltas Personales", "Personal Fouls", cohort_pf, False),
        ]

        stat_gaps: List[StatGapItem] = []
        weak_spot_keys: List[str] = []
        strength_keys: List[str] = []

        for key, lbl_es, lbl_en, cohort_vals, is_pct in stat_configs:
            p_val = player_metrics.get(key, 0.0)
            c_avg = benchmark_dict.get(key, 1.0)
            c_med = round(float(np.median(cohort_vals)), 3 if is_pct else 1)
            c_p75 = round(float(np.percentile(cohort_vals, 75)), 3 if is_pct else 1)

            diff = round(p_val - c_avg, 3 if is_pct else 1)
            pct_diff = round(((p_val - c_avg) / c_avg * 100) if c_avg != 0 else 0.0, 1)

            # Determine status
            if key in ["tov", "pf"]:
                # Lower is better
                if p_val < c_avg * 0.75:
                    status = "elite"
                    needs_tr = False
                    strength_keys.append(key)
                elif p_val <= c_avg:
                    status = "strength"
                    needs_tr = False
                elif p_val > c_avg * 1.25:
                    status = "critical_deficit"
                    needs_tr = True
                    weak_spot_keys.append(key)
                elif p_val > c_avg * 1.10:
                    status = "weakness"
                    needs_tr = True
                    weak_spot_keys.append(key)
                else:
                    status = "average"
                    needs_tr = False
            else:
                # Higher is better
                if is_pct:
                    if (p_val - c_avg) >= 0.06:
                        status = "elite"
                        strength_keys.append(key)
                        needs_tr = False
                    elif (p_val - c_avg) >= 0.02:
                        status = "strength"
                        strength_keys.append(key)
                        needs_tr = False
                    elif (c_avg - p_val) >= 0.06:
                        status = "critical_deficit"
                        weak_spot_keys.append(key)
                        needs_tr = True
                    elif (c_avg - p_val) >= 0.03:
                        status = "weakness"
                        weak_spot_keys.append(key)
                        needs_tr = True
                    else:
                        status = "average"
                        needs_tr = False
                else:
                    if p_val >= c_avg * 1.40:
                        status = "elite"
                        strength_keys.append(key)
                        needs_tr = False
                    elif p_val >= c_avg * 1.15:
                        status = "strength"
                        strength_keys.append(key)
                        needs_tr = False
                    elif p_val <= c_avg * 0.65:
                        status = "critical_deficit"
                        weak_spot_keys.append(key)
                        needs_tr = True
                    elif p_val <= c_avg * 0.85:
                        status = "weakness"
                        weak_spot_keys.append(key)
                        needs_tr = True
                    else:
                        status = "average"
                        needs_tr = False

            stat_gaps.append(
                StatGapItem(
                    stat_key=key,
                    label_es=lbl_es,
                    label_en=lbl_en,
                    player_value=p_val,
                    position_avg=c_avg,
                    position_median=c_med,
                    position_p75=c_p75,
                    diff=diff,
                    pct_diff=pct_diff,
                    status=status,
                    needs_training=needs_tr,
                )
            )

        # Role Fulfillment Scoring (0 - 100)
        if pos_group == "Guard":
            w_pts, w_ast, w_3pt, w_eff, w_stl, w_tov, w_reb = 0.22, 0.25, 0.18, 0.15, 0.10, 0.05, 0.05
        elif pos_group == "Forward":
            w_pts, w_reb, w_eff, w_3pt, w_stl, w_blk, w_ast = 0.25, 0.22, 0.18, 0.12, 0.08, 0.08, 0.07
            w_tov = 0.0
        else:  # Center
            w_pts, w_reb, w_blk, w_eff, w_tov, w_ast, w_stl = 0.20, 0.30, 0.20, 0.20, 0.05, 0.03, 0.02
            w_3pt = 0.0

        def _calc_sub_score(val: float, avg: float, reverse: bool = False) -> float:
            if avg == 0:
                return 75.0
            if reverse:
                ratio = avg / max(val, 0.1)
            else:
                ratio = val / avg
            score = 75.0 + (ratio - 1.0) * 45.0
            return float(np.clip(score, 30.0, 99.0))

        if pos_group == "Guard":
            sub_scores = [
                _calc_sub_score(p_pts, benchmark_dict["pts"]) * w_pts,
                _calc_sub_score(p_ast, benchmark_dict["ast"]) * w_ast,
                _calc_sub_score(p_fg3_pct, benchmark_dict["fg3_pct"]) * w_3pt,
                _calc_sub_score(p_fg_pct, benchmark_dict["fg_pct"]) * w_eff,
                _calc_sub_score(p_stl, benchmark_dict["stl"]) * w_stl,
                _calc_sub_score(p_tov, benchmark_dict["tov"], reverse=True) * w_tov,
                _calc_sub_score(p_reb, benchmark_dict["reb"]) * w_reb,
            ]
        elif pos_group == "Forward":
            sub_scores = [
                _calc_sub_score(p_pts, benchmark_dict["pts"]) * w_pts,
                _calc_sub_score(p_reb, benchmark_dict["reb"]) * w_reb,
                _calc_sub_score(p_fg_pct, benchmark_dict["fg_pct"]) * w_eff,
                _calc_sub_score(p_fg3_pct, benchmark_dict["fg3_pct"]) * w_3pt,
                _calc_sub_score(p_stl, benchmark_dict["stl"]) * w_stl,
                _calc_sub_score(p_blk, benchmark_dict["blk"]) * w_blk,
                _calc_sub_score(p_ast, benchmark_dict["ast"]) * w_ast,
            ]
        else:
            sub_scores = [
                _calc_sub_score(p_pts, benchmark_dict["pts"]) * w_pts,
                _calc_sub_score(p_reb, benchmark_dict["reb"]) * w_reb,
                _calc_sub_score(p_blk, benchmark_dict["blk"]) * w_blk,
                _calc_sub_score(p_fg_pct, benchmark_dict["fg_pct"]) * w_eff,
                _calc_sub_score(p_tov, benchmark_dict["tov"], reverse=True) * w_tov,
                _calc_sub_score(p_ast, benchmark_dict["ast"]) * w_ast,
                _calc_sub_score(p_stl, benchmark_dict["stl"]) * w_stl,
            ]

        raw_score = float(sum(sub_scores))
        overall_score = round(float(np.clip(raw_score, 40.0, 99.5)), 1)

        def _grade(sc: float) -> Tuple[str, str, str]:
            if sc >= 92.0:
                return "A+", "Dominio de Élite Posicional", "Elite Positional Dominance"
            elif sc >= 85.0:
                return "A", "Titular Destacado / Sobresaliente", "Outstanding Starter"
            elif sc >= 78.0:
                return "B+", "Sólido Cumplimiento Posicional", "Solid Role Execution"
            elif sc >= 70.0:
                return "B", "Rendimiento Medio en la Posición", "Average Positional Standard"
            elif sc >= 62.0:
                return "C+", "Cumplimiento Parcial / Áreas por Mejorar", "Partial Execution / Deficits Present"
            elif sc >= 52.0:
                return "C", "Por Debajo del Estándar Posicional", "Below Positional Benchmark"
            else:
                return "D", "Déficit Crítico de Rendimiento", "Critical Performance Deficit"

        letter_grade, gr_label_es, gr_label_en = _grade(overall_score)

        # Verdict text
        key_strengths_es = []
        key_strengths_en = []
        for sk in strength_keys[:3]:
            cfg = next((c for c in stat_configs if c[0] == sk), None)
            if cfg:
                key_strengths_es.append(f"Supera la media posicional en {cfg[1]}")
                key_strengths_en.append(f"Exceeds positional average in {cfg[2]}")

        primary_deficits_es = []
        primary_deficits_en = []
        for wk in weak_spot_keys[:3]:
            cfg = next((c for c in stat_configs if c[0] == wk), None)
            if cfg:
                primary_deficits_es.append(f"Déficit en {cfg[1]} frente a sus pares de posición")
                primary_deficits_en.append(f"Deficit in {cfg[2]} compared to positional peers")

        if not primary_deficits_es:
            primary_deficits_es.append("No muestra déficits estadísticos severos frente a su cohorte")
            primary_deficits_en.append("No critical statistical deficits compared to positional cohort")

        if overall_score >= 85.0:
            verdict_es = f"Cumple con creces las demandas de su posición ({pos_specific}). Es un pilar de élite en su cohorte posicional."
            verdict_en = f"Thoroughly fulfills the tactical demands of his position ({pos_specific}). An elite pillar in his positional cohort."
        elif overall_score >= 70.0:
            verdict_es = f"Cumple adecuadamente el rol de {pos_specific}, con margen de crecimiento claro en áreas específicas para alcanzar el escalón All-Star."
            verdict_en = f"Adequately executes the {pos_specific} role, with clear developmental upside in targeted facets to reach All-Star caliber."
        else:
            verdict_es = f"Presenta desventajas estadísticas marcadas frente a la media de {pos_specific}. Requiere una intervención de entrenamiento focalizada."
            verdict_en = f"Shows marked statistical deficiencies compared to the {pos_specific} positional benchmark. Requires targeted training intervention."

        # Compute Projected Stats
        projected_metrics = dict(player_metrics)
        if "fg3_pct" in weak_spot_keys or "FG3_PCT" in weak_spot_keys:
            projected_metrics["fg3_pct"] = round(min(p_fg3_pct + 0.035, benchmark_dict["fg3_pct"] + 0.015), 3)
            projected_metrics["fg3m"] = round(p_fg3m * 1.18, 1)
        elif p_fg3_pct > 0.0:
            projected_metrics["fg3_pct"] = round(min(p_fg3_pct + 0.015, 0.44), 3)

        if "fg_pct" in weak_spot_keys or "FG_PCT" in weak_spot_keys:
            projected_metrics["fg_pct"] = round(min(p_fg_pct + 0.032, benchmark_dict["fg_pct"] + 0.010), 3)

        if "ft_pct" in weak_spot_keys or "FT_PCT" in weak_spot_keys:
            projected_metrics["ft_pct"] = round(min(p_ft_pct + 0.055, 0.88), 3)

        if "tov" in weak_spot_keys or "TOV" in weak_spot_keys:
            projected_metrics["tov"] = round(max(p_tov * 0.82, benchmark_dict["tov"] * 0.95), 1)

        if "pf" in weak_spot_keys or "PF" in weak_spot_keys:
            projected_metrics["pf"] = round(max(p_pf * 0.85, benchmark_dict["pf"] * 0.95), 1)

        if "reb" in weak_spot_keys or "REB" in weak_spot_keys:
            projected_metrics["reb"] = round(min(p_reb * 1.20, benchmark_dict["reb"] * 1.10), 1)

        if "ast" in weak_spot_keys or "AST" in weak_spot_keys:
            projected_metrics["ast"] = round(min(p_ast * 1.22, benchmark_dict["ast"] * 1.10), 1)

        if "stl" in weak_spot_keys or "STL" in weak_spot_keys:
            projected_metrics["stl"] = round(min(p_stl * 1.25, benchmark_dict["stl"] * 1.15), 1)

        if "blk" in weak_spot_keys or "BLK" in weak_spot_keys:
            projected_metrics["blk"] = round(min(p_blk * 1.25, benchmark_dict["blk"] * 1.15), 1)

        if "pts" in weak_spot_keys or "PTS" in weak_spot_keys:
            projected_metrics["pts"] = round(p_pts * 1.12, 1)

        # Projected score
        projected_score = round(min(overall_score + 9.5, 99.0), 1)
        projected_grade, _, _ = _grade(projected_score)

        role_fulfillment = RoleFulfillment(
            overall_score=overall_score,
            letter_grade=letter_grade,
            grade_label_es=gr_label_es,
            grade_label_en=gr_label_en,
            verdict_es=verdict_es,
            verdict_en=verdict_en,
            key_strengths_es=key_strengths_es,
            key_strengths_en=key_strengths_en,
            primary_deficits_es=primary_deficits_es,
            primary_deficits_en=primary_deficits_en,
            projected_score=projected_score,
            projected_grade=projected_grade,
        )

        # Assemble Recommended Drills
        recommended_drills: List[DrillRecommendation] = []
        target_keys = weak_spot_keys if weak_spot_keys else ["FG3_PCT", "FG_PCT", "TOV"]

        for wk in target_keys:
            mapped_key = wk.upper()
            if mapped_key not in DRILLS_CATALOG:
                for cat_k in DRILLS_CATALOG:
                    if cat_k.lower() == wk.lower() or cat_k.replace("_PCT", "").lower() == wk.lower():
                        mapped_key = cat_k
                        break

            drills_for_target = DRILLS_CATALOG.get(mapped_key, [])
            for d in drills_for_target:
                recommended_drills.append(
                    DrillRecommendation(
                        id=d["id"],
                        name_es=d["name_es"],
                        name_en=d["name_en"],
                        category=d["category"],
                        stat_target=d["stat_target"],
                        intensity=d["intensity"],
                        sets_and_reps=d["sets_and_reps"],
                        description_es=d["description_es"],
                        description_en=d["description_en"],
                        projected_impact_es=d["projected_impact_es"],
                        projected_impact_en=d["projected_impact_en"],
                    )
                )

        if not recommended_drills:
            for d in DRILLS_CATALOG["FG3_PCT"] + DRILLS_CATALOG["TOV"]:
                recommended_drills.append(DrillRecommendation(**d))

        # Build 4 Distinct Training Regimes
        regimes: List[TrainingRegimePlan] = [
            TrainingRegimePlan(
                regime_id="balanced",
                title_es="Plan de Compensación Integral",
                title_en="Comprehensive Positional Upgrade",
                description_es="Régimen balanceado diseñado específicamente para subsanar los déficits estadísticos del jugador frente a su cohorte.",
                description_en="Balanced program engineered to systematically eliminate the player's statistical deficits compared to position peers.",
                weekly_frequency="5 sesiones por semana (90 min/sesión)",
                target_focus_es="Eliminación de puntos débiles y optimización de virtudes posicionales",
                target_focus_en="Weak spot eradication and positional strength leverage",
                drills=recommended_drills[:4],
            ),
            TrainingRegimePlan(
                regime_id="shooting_focus",
                title_es="Especialización en Tiro y Eficiencia Ofensiva",
                title_en="Shooting Mastery & Offensive Efficiency",
                description_es="Enfoque de máxima repetición en tiro perimetral catch-and-shoot, tiro tras drible y tiros libres clutch.",
                description_en="High-repetition protocol for catch-and-shoot 3s, pull-up jumpers, and pressure free throws.",
                weekly_frequency="6 sesiones por semana (60 min/sesión)",
                target_focus_es="+3.5% en Triples y +5.0% en Tiros Libres",
                target_focus_en="+3.5% 3PT% and +5.0% FT%",
                drills=[DrillRecommendation(**d) for d in (DRILLS_CATALOG["FG3_PCT"] + DRILLS_CATALOG["FT_PCT"] + DRILLS_CATALOG["FG_PCT"])[:4]],
            ),
            TrainingRegimePlan(
                regime_id="defensive_lockdown",
                title_es="Fortaleza Defensiva y Protección de Cancha",
                title_en="Defensive Lockdown & Rim Deterrence",
                description_es="Trabajo intenso en contención perimetral, recuperación en closeouts, verticalidad de aro y robos en línea de pase.",
                description_en="Intense focus on point-of-attack slides, closeout control, rim verticality, and deflection reads.",
                weekly_frequency="4 sesiones por semana (75 min/sesión)",
                target_focus_es="Reducción de faltas, +0.6 robos y mayor solidez interior",
                target_focus_en="Foul reduction, +0.6 steals, and improved defensive deterrence",
                drills=[DrillRecommendation(**d) for d in (DRILLS_CATALOG["PF"] + DRILLS_CATALOG["STL"] + DRILLS_CATALOG["BLK"])[:4]],
            ),
            TrainingRegimePlan(
                regime_id="playmaking_mastery",
                title_es="Maestría en Creación y Control de Posesión",
                title_en="Playmaking Mastery & Ball Security",
                description_es="Drills de manejo bajo presión con 2 balones y simulador táctico de pick-and-roll para maximizar asistencias y recortar pérdidas.",
                description_en="Dual-ball pressure handling and pick-and-roll coverage reads to maximize assists and minimize turnovers.",
                weekly_frequency="4 sesiones por semana (60 min/sesión)",
                target_focus_es="Ratio AST/TOV > 2.8 y mayor generación ofensiva",
                target_focus_en="AST/TOV ratio > 2.8 and elevated offensive creation",
                drills=[DrillRecommendation(**d) for d in (DRILLS_CATALOG["TOV"] + DRILLS_CATALOG["AST"])[:4]],
            ),
        ]

        radar_labels = [
            "Anotación (PTS)",
            "Rebotes (REB)",
            "Creación (AST)",
            "Tiro Exterior (3PT)",
            "Defensa (STL+BLK)",
            "Eficiencia (FG%/FT%)",
        ]

        max_pts = 35.0
        max_reb = 15.0
        max_ast = 12.0
        max_3pt = 4.5
        max_def = 4.0
        max_eff = 1.0

        p_radar = [
            min(p_pts / max_pts, 1.0),
            min(p_reb / max_reb, 1.0),
            min(p_ast / max_ast, 1.0),
            min((p_fg3m + (p_fg3_pct * 3.0)) / max_3pt, 1.0),
            min((p_stl + p_blk) / max_def, 1.0),
            min(((p_fg_pct * 0.5) + (p_ft_pct * 0.5)) / max_eff, 1.0),
        ]

        b_pts = benchmark_dict["pts"]
        b_reb = benchmark_dict["reb"]
        b_ast = benchmark_dict["ast"]
        b_fg3m = benchmark_dict["fg3m"]
        b_fg3_pct = benchmark_dict["fg3_pct"]
        b_stl = benchmark_dict["stl"]
        b_blk = benchmark_dict["blk"]
        b_fg_pct = benchmark_dict["fg_pct"]
        b_ft_pct = benchmark_dict["ft_pct"]

        b_radar = [
            min(b_pts / max_pts, 1.0),
            min(b_reb / max_reb, 1.0),
            min(b_ast / max_ast, 1.0),
            min((b_fg3m + (b_fg3_pct * 3.0)) / max_3pt, 1.0),
            min((b_stl + b_blk) / max_def, 1.0),
            min(((b_fg_pct * 0.5) + (b_ft_pct * 0.5)) / max_eff, 1.0),
        ]

        pr_pts = projected_metrics["pts"]
        pr_reb = projected_metrics["reb"]
        pr_ast = projected_metrics["ast"]
        pr_fg3m = projected_metrics["fg3m"]
        pr_fg3_pct = projected_metrics["fg3_pct"]
        pr_stl = projected_metrics["stl"]
        pr_blk = projected_metrics["blk"]
        pr_fg_pct = projected_metrics["fg_pct"]
        pr_ft_pct = projected_metrics["ft_pct"]

        pr_radar = [
            min(pr_pts / max_pts, 1.0),
            min(pr_reb / max_reb, 1.0),
            min(pr_ast / max_ast, 1.0),
            min((pr_fg3m + (pr_fg3_pct * 3.0)) / max_3pt, 1.0),
            min((pr_stl + pr_blk) / max_def, 1.0),
            min(((pr_fg_pct * 0.5) + (pr_ft_pct * 0.5)) / max_eff, 1.0),
        ]

        headshot = player.headshot_url or f"https://cdn.nba.com/headshots/nba/latest/1040x760/{player.id}.png"

        return TrainingAnalysisResponse(
            player_id=player.id,
            player_name=player.full_name,
            team_abbreviation=team_abbr,
            team_name=team_full,
            headshot_url=headshot,
            position=pos_specific,
            position_group=pos_group,
            archetype_id=arch_id,
            archetype_name_es=arch_name_es,
            archetype_name_en=arch_name_en,
            archetype_color=arch_color,
            season_id=eff_season_id,
            season_label=season_label,
            total_position_peers=total_peers,
            current_stats=player_metrics,
            positional_benchmark=benchmark_dict,
            projected_stats=projected_metrics,
            stat_gaps=stat_gaps,
            role_fulfillment=role_fulfillment,
            recommended_drills=recommended_drills,
            training_regimes=regimes,
            radar_labels=radar_labels,
            radar_player_values=[round(v, 3) for v in p_radar],
            radar_benchmark_values=[round(v, 3) for v in b_radar],
            radar_projected_values=[round(v, 3) for v in pr_radar],
        )
