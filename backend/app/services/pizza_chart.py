import math
import unicodedata
from typing import Optional, List, Dict, Any, Tuple
import numpy as np
from sqlmodel import Session, select
from app.models import Player, PlayerSeasonStats, Season, PlayerAdvancedStats
from app.schemas import (
    PizzaChartResponse,
    PizzaQuadrant,
    PizzaMetricItem,
)
from app.services.training import _normalize_str, PLAYER_POSITION_MASTER_CATALOG


def _calc_percentile(val: float, cohort: List[float], higher_is_better: bool = True) -> float:
    if not cohort or len(cohort) == 0:
        return 50.0
    arr = np.array(cohort)
    if higher_is_better:
        pct = (np.sum(arr < val) + 0.5 * np.sum(arr == val)) / len(arr) * 100.0
    else:
        pct = (np.sum(arr > val) + 0.5 * np.sum(arr == val)) / len(arr) * 100.0
    return round(float(np.clip(pct, 1.0, 99.0)), 1)


class PizzaChartService:
    def __init__(self, session: Session):
        self.session = session

    def get_player_pizza_chart(
        self,
        player_id_or_name: str,
        season_id: Optional[int] = None,
    ) -> PizzaChartResponse:
        # 1. Resolve player
        player = None
        if str(player_id_or_name).isdigit():
            player = self.session.get(Player, int(player_id_or_name))
        
        if not player:
            clean_target = _normalize_str(str(player_id_or_name))
            all_players = self.session.exec(select(Player)).all()
            for p in all_players:
                if _normalize_str(p.full_name) == clean_target:
                    player = p
                    break
            if not player:
                for p in all_players:
                    if clean_target in _normalize_str(p.full_name) or _normalize_str(p.full_name) in clean_target:
                        player = p
                        break

        if not player:
            raise ValueError(f"Player '{player_id_or_name}' not found")

        # 2. Resolve Season
        if season_id:
            season = self.session.get(Season, season_id)
        else:
            # Pick season with most games or active
            p_stats = self.session.exec(
                select(PlayerSeasonStats).where(PlayerSeasonStats.player_id == player.id)
            ).all()
            if not p_stats:
                raise ValueError(f"No stats found for {player.full_name}")
            best_stat = max(p_stats, key=lambda s: s.pts or 0)
            season = self.session.get(Season, best_stat.season_id)

        if not season:
            raise ValueError(f"Season not found for {player.full_name}")

        # 3. Get Target Player Stat
        target_stat = self.session.exec(
            select(PlayerSeasonStats).where(
                PlayerSeasonStats.player_id == player.id,
                PlayerSeasonStats.season_id == season.id,
            )
        ).first()
        if not target_stat:
            # Fallback to any stat
            target_stat = self.session.exec(
                select(PlayerSeasonStats).where(PlayerSeasonStats.player_id == player.id)
            ).first()

        target_adv = self.session.exec(
            select(PlayerAdvancedStats).where(
                PlayerAdvancedStats.player_id == player.id,
                PlayerAdvancedStats.season_id == season.id,
            )
        ).first()

        # 4. Infer Position Group
        pos_str = player.position or "G"
        pos_grp = "Guard"
        if "C" in pos_str.upper():
            pos_grp = "Center"
        elif "F" in pos_str.upper():
            pos_grp = "Forward"
        
        # Check master catalog
        for cat_name, pos_t in PLAYER_POSITION_MASTER_CATALOG.items():
            if _normalize_str(cat_name) == _normalize_str(player.full_name):
                pos_str, pos_grp = pos_t
                break

        # 5. Build Cohort (All players in same season and same position group with GP >= 10)
        all_season_stats = self.session.exec(
            select(PlayerSeasonStats).where(
                PlayerSeasonStats.season_id == season.id,
                PlayerSeasonStats.gp >= 10,
            )
        ).all()

        cohort_data: List[Dict[str, float]] = []
        for s in all_season_stats:
            p_item = self.session.get(Player, s.player_id)
            if not p_item:
                continue
            item_pos_grp = "Guard"
            p_item_pos = p_item.position or ""
            if "C" in p_item_pos.upper():
                item_pos_grp = "Center"
            elif "F" in p_item_pos.upper():
                item_pos_grp = "Forward"

            for c_name, c_t in PLAYER_POSITION_MASTER_CATALOG.items():
                if _normalize_str(c_name) == _normalize_str(p_item.full_name):
                    item_pos_grp = c_t[1]
                    break

            if item_pos_grp == pos_grp:
                gp = max(s.gp or 1, 1)
                fga = max(s.fga or 1.0, 1.0)
                pts = s.pts or 0.0
                fta = s.fta or 0.0
                fg3a = s.fg3a or 0.0
                ast = s.ast or 0.0
                tov = max(s.tov or 0.5, 0.5)

                ts = pts / (2.0 * (fga + 0.44 * fta)) if (fga + 0.44 * fta) > 0 else 0.50
                fg3_rate = (fg3a / fga) * 100.0
                ft_rate = (fta / fga) * 100.0
                ast_tov = ast / tov

                cohort_data.append({
                    "pts_pg": pts / gp,
                    "ts_pct": ts * 100.0,
                    "fg3_rate": fg3_rate,
                    "ft_rate": ft_rate,
                    "ast_pg": ast / gp,
                    "ast_tov": ast_tov,
                    "stl_pg": (s.stl or 0.0) / gp,
                    "blk_pg": (s.blk or 0.0) / gp,
                    "reb_pg": (s.reb or 0.0) / gp,
                    "oreb_pg": (s.oreb or 0.0) / gp,
                    "dreb_pg": (s.dreb or 0.0) / gp,
                    "def_activity": ((s.stl or 0.0) + (s.blk or 0.0) + 0.5 * (s.dreb or 0.0)) / gp,
                    "pass_pts": (ast / gp) * 2.3,
                })

        if len(cohort_data) < 15:
            # Relax filter to include all season players
            for s in all_season_stats:
                gp = max(s.gp or 1, 1)
                fga = max(s.fga or 1.0, 1.0)
                pts = s.pts or 0.0
                fta = s.fta or 0.0
                fg3a = s.fg3a or 0.0
                ast = s.ast or 0.0
                tov = max(s.tov or 0.5, 0.5)
                ts = pts / (2.0 * (fga + 0.44 * fta)) if (fga + 0.44 * fta) > 0 else 0.50
                cohort_data.append({
                    "pts_pg": pts / gp,
                    "ts_pct": ts * 100.0,
                    "fg3_rate": (fg3a / fga) * 100.0,
                    "ft_rate": (fta / fga) * 100.0,
                    "ast_pg": ast / gp,
                    "ast_tov": ast / tov,
                    "stl_pg": (s.stl or 0.0) / gp,
                    "blk_pg": (s.blk or 0.0) / gp,
                    "reb_pg": (s.reb or 0.0) / gp,
                    "oreb_pg": (s.oreb or 0.0) / gp,
                    "dreb_pg": (s.dreb or 0.0) / gp,
                    "def_activity": ((s.stl or 0.0) + (s.blk or 0.0) + 0.5 * (s.dreb or 0.0)) / gp,
                    "pass_pts": (ast / gp) * 2.3,
                })

        # 6. Extract Target Player Raw Metrics
        t_gp = max(target_stat.gp or 1, 1)
        t_fga = max(target_stat.fga or 1.0, 1.0)
        t_pts = target_stat.pts or 0.0
        t_fta = target_stat.fta or 0.0
        t_fg3a = target_stat.fg3a or 0.0
        t_ast = target_stat.ast or 0.0
        t_tov = max(target_stat.tov or 0.5, 0.5)

        t_pts_pg = round(t_pts / t_gp, 1)
        t_ts_pct = round((t_pts / (2.0 * (t_fga + 0.44 * t_fta))) * 100.0, 1) if (t_fga + 0.44 * t_fta) > 0 else 53.0
        t_fg3_rate = round((t_fg3a / t_fga) * 100.0, 1)
        t_ft_rate = round((t_fta / t_fga) * 100.0, 1)
        t_usg_pct = round(target_adv.usg_pct if target_adv and target_adv.usg_pct else 22.5, 1)

        t_ast_pg = round(t_ast / t_gp, 1)
        t_ast_tov = round(t_ast / t_tov, 2)
        t_ast_pct = round(target_adv.ast_pct if target_adv and target_adv.ast_pct else (t_ast_pg * 3.5), 1)
        t_pass_pts = round(t_ast_pg * 2.3, 1)

        t_stl_pg = round((target_stat.stl or 0.0) / t_gp, 1)
        t_blk_pg = round((target_stat.blk or 0.0) / t_gp, 1)
        t_dreb_pg = round((target_stat.dreb or 0.0) / t_gp, 1)
        t_def_activity = round(t_stl_pg + t_blk_pg + 0.5 * t_dreb_pg, 2)

        t_reb_pg = round((target_stat.reb or 0.0) / t_gp, 1)
        t_oreb_pg = round((target_stat.oreb or 0.0) / t_gp, 1)
        t_oreb_pct = round(target_adv.orb_pct if target_adv and target_adv.orb_pct else (t_oreb_pg * 2.8), 1)
        t_dreb_pct = round(target_adv.drb_pct if target_adv and target_adv.drb_pct else (t_dreb_pg * 3.2), 1)

        # 7. Compute Percentiles for the 16 Metrics
        c_pts = [c["pts_pg"] for c in cohort_data]
        c_ts = [c["ts_pct"] for c in cohort_data]
        c_fg3r = [c["fg3_rate"] for c in cohort_data]
        c_ftr = [c["ft_rate"] for c in cohort_data]
        c_ast = [c["ast_pg"] for c in cohort_data]
        c_ast_tov = [c["ast_tov"] for c in cohort_data]
        c_pass_pts = [c["pass_pts"] for c in cohort_data]
        c_stl = [c["stl_pg"] for c in cohort_data]
        c_blk = [c["blk_pg"] for c in cohort_data]
        c_def_act = [c["def_activity"] for c in cohort_data]
        c_reb = [c["reb_pg"] for c in cohort_data]
        c_oreb = [c["oreb_pg"] for c in cohort_data]
        c_dreb = [c["dreb_pg"] for c in cohort_data]

        pct_pts = _calc_percentile(t_pts_pg, c_pts)
        pct_ts = _calc_percentile(t_ts_pct, c_ts)
        pct_fg3r = _calc_percentile(t_fg3_rate, c_fg3r)
        pct_ftr = _calc_percentile(t_ft_rate, c_ftr)

        pct_ast = _calc_percentile(t_ast_pg, c_ast)
        pct_ast_tov = _calc_percentile(t_ast_tov, c_ast_tov)
        pct_ast_pct = min(99.0, max(5.0, round(pct_ast * 0.95 + 5.0, 1)))
        pct_pass_pts = _calc_percentile(t_pass_pts, c_pass_pts)

        pct_stl = _calc_percentile(t_stl_pg, c_stl)
        pct_blk = _calc_percentile(t_blk_pg, c_blk)
        pct_def_act = _calc_percentile(t_def_activity, c_def_act)
        pct_d_impact = min(99.0, max(5.0, round(0.4 * pct_stl + 0.4 * pct_blk + 0.2 * pct_def_act, 1)))

        pct_reb = _calc_percentile(t_reb_pg, c_reb)
        pct_oreb = _calc_percentile(t_oreb_pg, c_oreb)
        pct_dreb = _calc_percentile(t_dreb_pg, c_dreb)
        pct_physical = min(99.0, max(5.0, round(0.5 * pct_reb + 0.3 * pct_ftr + 0.2 * pct_pts, 1)))

        # 8. Assemble Quadrants (4 metrics each)
        quad_scoring = PizzaQuadrant(
            quadrant_key="scoring",
            title_es="Anotación & Eficiencia",
            title_en="Scoring & Efficiency",
            color="#EF4444",  # Red / Rose
            metrics=[
                PizzaMetricItem(
                    key="pts_pg",
                    label_es="Puntos por Partido",
                    label_en="Points Per Game",
                    quadrant="scoring",
                    raw_value=t_pts_pg,
                    formatted_value=f"{t_pts_pg} PTS",
                    percentile=pct_pts,
                    color="#EF4444",
                ),
                PizzaMetricItem(
                    key="ts_pct",
                    label_es="True Shooting (TS%)",
                    label_en="True Shooting (TS%)",
                    quadrant="scoring",
                    raw_value=t_ts_pct,
                    formatted_value=f"{t_ts_pct}%",
                    percentile=pct_ts,
                    color="#F87171",
                ),
                PizzaMetricItem(
                    key="fg3_rate",
                    label_es="Volumen Triples (3P Rate)",
                    label_en="3P Attempt Rate",
                    quadrant="scoring",
                    raw_value=t_fg3_rate,
                    formatted_value=f"{t_fg3_rate}%",
                    percentile=pct_fg3r,
                    color="#FB923C",
                ),
                PizzaMetricItem(
                    key="ft_rate",
                    label_es="Frecuencia TL (FT Rate)",
                    label_en="Free Throw Rate",
                    quadrant="scoring",
                    raw_value=t_ft_rate,
                    formatted_value=f"{t_ft_rate}%",
                    percentile=pct_ftr,
                    color="#F59E0B",
                ),
            ],
        )

        quad_playmaking = PizzaQuadrant(
            quadrant_key="playmaking",
            title_es="Creación & Playmaking",
            title_en="Creation & Playmaking",
            color="#3B82F6",  # Blue
            metrics=[
                PizzaMetricItem(
                    key="ast_pg",
                    label_es="Asistencias por Partido",
                    label_en="Assists Per Game",
                    quadrant="playmaking",
                    raw_value=t_ast_pg,
                    formatted_value=f"{t_ast_pg} AST",
                    percentile=pct_ast,
                    color="#3B82F6",
                ),
                PizzaMetricItem(
                    key="ast_tov",
                    label_es="Ratio Asist/Pérdidas",
                    label_en="Assist-to-TOV Ratio",
                    quadrant="playmaking",
                    raw_value=t_ast_tov,
                    formatted_value=f"{t_ast_tov} A/T",
                    percentile=pct_ast_tov,
                    color="#60A5FA",
                ),
                PizzaMetricItem(
                    key="ast_pct",
                    label_es="% Asistencias (AST%)",
                    label_en="Assist Rate (AST%)",
                    quadrant="playmaking",
                    raw_value=t_ast_pct,
                    formatted_value=f"{t_ast_pct}%",
                    percentile=pct_ast_pct,
                    color="#38BDF8",
                ),
                PizzaMetricItem(
                    key="pass_pts",
                    label_es="Puntos Creados por Pase",
                    label_en="Points Created from Passes",
                    quadrant="playmaking",
                    raw_value=t_pass_pts,
                    formatted_value=f"{t_pass_pts} PTS",
                    percentile=pct_pass_pts,
                    color="#0284C7",
                ),
            ],
        )

        quad_defense = PizzaQuadrant(
            quadrant_key="defense",
            title_es="Defensa & Disrupción",
            title_en="Defense & Disruption",
            color="#10B981",  # Emerald Green
            metrics=[
                PizzaMetricItem(
                    key="stl_pg",
                    label_es="Robos por Partido",
                    label_en="Steals Per Game",
                    quadrant="defense",
                    raw_value=t_stl_pg,
                    formatted_value=f"{t_stl_pg} STL",
                    percentile=pct_stl,
                    color="#10B981",
                ),
                PizzaMetricItem(
                    key="blk_pg",
                    label_es="Tapones por Partido",
                    label_en="Blocks Per Game",
                    quadrant="defense",
                    raw_value=t_blk_pg,
                    formatted_value=f"{t_blk_pg} BLK",
                    percentile=pct_blk,
                    color="#34D399",
                ),
                PizzaMetricItem(
                    key="def_activity",
                    label_es="Índice Actividad Defensiva",
                    label_en="Defensive Activity Index",
                    quadrant="defense",
                    raw_value=t_def_activity,
                    formatted_value=f"{t_def_activity}",
                    percentile=pct_def_act,
                    color="#059669",
                ),
                PizzaMetricItem(
                    key="def_impact",
                    label_es="Impacto Defensivo Global",
                    label_en="Overall Defensive Impact",
                    quadrant="defense",
                    raw_value=round(pct_d_impact / 10.0, 1),
                    formatted_value=f"{pct_d_impact} Pctl",
                    percentile=pct_d_impact,
                    color="#047857",
                ),
            ],
        )

        quad_physical = PizzaQuadrant(
            quadrant_key="physical",
            title_es="Rebote & Presencia Física",
            title_en="Rebounding & Physicality",
            color="#8B5CF6",  # Purple
            metrics=[
                PizzaMetricItem(
                    key="reb_pg",
                    label_es="Rebotes por Partido",
                    label_en="Rebounds Per Game",
                    quadrant="physical",
                    raw_value=t_reb_pg,
                    formatted_value=f"{t_reb_pg} REB",
                    percentile=pct_reb,
                    color="#8B5CF6",
                ),
                PizzaMetricItem(
                    key="oreb_pg",
                    label_es="Rebote Ofensivo (ORB/G)",
                    label_en="Offensive Rebounds/G",
                    quadrant="physical",
                    raw_value=t_oreb_pg,
                    formatted_value=f"{t_oreb_pg} ORB",
                    percentile=pct_oreb,
                    color="#A78BFA",
                ),
                PizzaMetricItem(
                    key="dreb_pg",
                    label_es="Rebote Defensivo (DRB/G)",
                    label_en="Defensive Rebounds/G",
                    quadrant="physical",
                    raw_value=t_dreb_pg,
                    formatted_value=f"{t_dreb_pg} DRB",
                    percentile=pct_dreb,
                    color="#7C3AED",
                ),
                PizzaMetricItem(
                    key="physical_score",
                    label_es="Dominio Físico Interior",
                    label_en="Physical Interior Dominance",
                    quadrant="physical",
                    raw_value=round(pct_physical / 10.0, 1),
                    formatted_value=f"{pct_physical} Pctl",
                    percentile=pct_physical,
                    color="#6D28D9",
                ),
            ],
        )

        all_pcts = [
            pct_pts, pct_ts, pct_fg3r, pct_ftr,
            pct_ast, pct_ast_tov, pct_ast_pct, pct_pass_pts,
            pct_stl, pct_blk, pct_def_act, pct_d_impact,
            pct_reb, pct_oreb, pct_dreb, pct_physical,
        ]
        overall_score = round(float(np.mean(all_pcts)), 1)

        return PizzaChartResponse(
            player_id=player.id,
            player_name=player.full_name,
            season_id=season.id,
            season_label=season.season_label,
            position=pos_str,
            position_group=pos_grp,
            total_peers=len(cohort_data),
            overall_percentile=overall_score,
            quadrants=[quad_scoring, quad_playmaking, quad_defense, quad_physical],
        )
