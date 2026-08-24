import math
import random
from typing import List, Dict, Any, Optional
import numpy as np
from sqlmodel import Session, select

from app.models import Player, Team, Season, PlayerSeasonStats, PlayerAdvancedStats
from app.schemas import (
    LineupSlotRequest,
    LineupTeamRequest,
    LineupSlotDetail,
    LineupTeamMetrics,
    LineupTeamEvaluationResponse,
    LineupPlayerBoxScore,
    Lineup5v5SimulationResponse,
    ClassicPresetLineup,
    VersusSeasonOption,
)
from app.services.versus import VersusService, ROLE_METADATA


class LineupService:
    def __init__(self, session: Session):
        self.session = session
        self.versus_service = VersusService(session)

    def get_slot_detail(self, slot: LineupSlotRequest) -> LineupSlotDetail:
        """
        Builds a rich slot detail with biometric, archetype, per-game, and advanced stats.
        """
        card = self.versus_service.get_player_card(slot.player_id, slot.season_id)
        
        # Calculate raw 3pt rate & per-game metrics
        stats = card.stats
        return LineupSlotDetail(
            position=slot.position.upper(),
            player_id=card.player_id,
            player_name=card.player_name,
            headshot_url=card.headshot_url,
            position_raw=card.position,
            height_cm=card.height_cm,
            weight_kg=card.weight_kg,
            team_abbreviation=card.team_abbreviation,
            season_id=card.selected_season_id,
            season_label=card.selected_season_label,
            is_best_season=card.is_best_season,
            archetype_id=card.archetype_id,
            archetype_name_es=card.archetype_es,
            archetype_name_en=card.archetype_en,
            archetype_color=card.archetype_color,
            ppg=stats.pts_pg,
            rpg=stats.reb_pg,
            apg=stats.ast_pg,
            spg=stats.stl_pg,
            bpg=stats.blk_pg,
            fg_pct=stats.fg_pct,
            fg3_pct=stats.fg3_pct,
            ft_pct=stats.ft_pct,
            ts_pct=stats.ts_pct,
            per=stats.per,
            bpm=stats.bpm,
            available_seasons=card.available_seasons,
        )

    def evaluate_lineup(self, team_name: str, slots_req: List[LineupSlotRequest]) -> LineupTeamEvaluationResponse:
        """
        Computes composite offensive, defensive, spacing, playmaking, and synergy ratings.
        """
        slots: List[LineupSlotDetail] = []
        for s in slots_req:
            try:
                detail = self.get_slot_detail(s)
                slots.append(detail)
            except Exception as e:
                continue

        if not slots:
            # Fallback empty metrics
            empty_metrics = LineupTeamMetrics(
                ortg=100.0,
                drtg=110.0,
                net_rating=-10.0,
                pace=98.0,
                spacing_score=50.0,
                playmaking_score=50.0,
                rebounding_score=50.0,
                perimeter_defense_score=50.0,
                rim_protection_score=50.0,
                chemistry_score=50.0,
                total_ppg=0.0,
                total_rpg=0.0,
                total_apg=0.0,
                total_rings=0,
                total_mvps=0,
                total_all_nba=0,
                synergy_strengths_es=["Quinteto sin jugadores asignados"],
                synergy_strengths_en=["No players assigned to lineup"],
                synergy_weaknesses_es=["Debe seleccionar jugadores para evaluar"],
                synergy_weaknesses_en=["Must select players to evaluate"],
            )
            return LineupTeamEvaluationResponse(team_name=team_name, slots=[], metrics=empty_metrics)

        # Totals
        total_ppg = sum(p.ppg for p in slots)
        total_rpg = sum(p.rpg for p in slots)
        total_apg = sum(p.apg for p in slots)

        # Accolades across players
        total_rings = 0
        total_mvps = 0
        total_all_nba = 0
        for p in slots:
            card = self.versus_service.get_player_card(p.player_id, p.season_id)
            total_rings += card.accolades.championships
            total_mvps += card.accolades.mvp_count
            total_all_nba += card.accolades.all_nba_count

        # 1. Spacing Score (0 - 100)
        # Based on average 3P% and 3PM
        good_shooters = sum(1 for p in slots if p.fg3_pct >= 0.35 or p.archetype_id in [4, 5, 6])
        avg_3p_pct = sum(p.fg3_pct for p in slots) / max(len(slots), 1)
        spacing_score = min(100.0, max(20.0, (avg_3p_pct * 140.0) + (good_shooters * 8.0) + 15.0))

        # 2. Playmaking Score (0 - 100)
        has_pg = any(p.position == "PG" or p.archetype_id in [6, 4] for p in slots)
        avg_apg = total_apg / max(len(slots), 1)
        playmaking_score = min(100.0, max(25.0, (avg_apg * 9.0) + (15.0 if has_pg else -10.0) + 30.0))

        # 3. Rebounding & Interior Physicality (0 - 100)
        avg_rpg = total_rpg / max(len(slots), 1)
        bigs_count = sum(1 for p in slots if p.position in ["PF", "C"] or p.archetype_id in [0, 2])
        rebounding_score = min(100.0, max(30.0, (avg_rpg * 7.5) + (bigs_count * 7.0) + 20.0))

        # 4. Perimeter Defense (0 - 100)
        poa_stoppers = sum(1 for p in slots if p.archetype_id in [1, 5])
        avg_spg = sum(p.spg for p in slots) / max(len(slots), 1)
        perimeter_def_score = min(100.0, max(30.0, (avg_spg * 25.0) + (poa_stoppers * 10.0) + 35.0))

        # 5. Rim Protection (0 - 100)
        rim_protectors = sum(1 for p in slots if p.archetype_id in [2, 0] or p.position == "C")
        avg_bpg = sum(p.bpg for p in slots) / max(len(slots), 1)
        rim_prot_score = min(100.0, max(25.0, (avg_bpg * 28.0) + (rim_protectors * 12.0) + 25.0))

        # 6. Chemistry & Archetype Synergy (0 - 100)
        chemistry = 75.0
        strengths_es: List[str] = []
        strengths_en: List[str] = []
        weaknesses_es: List[str] = []
        weaknesses_en: List[str] = []

        # Check for 5 standard positions
        assigned_positions = set(p.position for p in slots)
        if len(assigned_positions) == 5:
            chemistry += 10.0
            strengths_es.append("Estructura posicional perfecta (PG-SG-SF-PF-C)")
            strengths_en.append("Flawless positional balance (PG-SG-SF-PF-C)")
        elif len(assigned_positions) < 4:
            chemistry -= 12.0
            weaknesses_es.append("Desbalance posicional: múltiples jugadores compitiendo por el mismo espacio")
            weaknesses_en.append("Positional imbalance: multiple players overlapping role zones")

        # Heliocentric balance (too many ball dominant players)
        heliocentrics = sum(1 for p in slots if p.archetype_id == 4)
        if heliocentrics > 2:
            chemistry -= 15.0
            weaknesses_es.append(f"Exceso de anotadores heliocéntricos ({heliocentrics}): conflicto por el uso del balón")
            weaknesses_en.append(f"Too many heliocentric scorers ({heliocentrics}): ball-dominance redundancy")
        elif heliocentrics == 1 or (heliocentrics == 2 and has_pg):
            chemistry += 8.0
            strengths_es.append("Generación heliocéntrica balanceada con roles de apoyo definidos")
            strengths_en.append("Balanced heliocentric engine with defined secondary scoring roles")

        # 3&D & Floor Spacing
        snipers_3d = sum(1 for p in slots if p.archetype_id == 5)
        if snipers_3d >= 2:
            chemistry += 8.0
            strengths_es.append(f"Excelente amenaza perimetral con {snipers_3d} francotiradores 3&D")
            strengths_en.append(f"Lethal spacing with {snipers_3d} 3&D snipers punishing double teams")

        if rim_protectors >= 1:
            strengths_es.append("Ancla defensiva sólida protegiendo el aro y cerrando el rebote defensivo")
            strengths_en.append("Solid rim protector anchoring the interior and defensive glass")
        else:
            chemistry -= 10.0
            weaknesses_es.append("Falta de un pívot protector del aro élite en la pintura")
            weaknesses_en.append("Lack of an elite rim protector in the paint")

        if spacing_score < 45.0:
            weaknesses_es.append("Espaciado deficiente: la defensa rival puede colapsar la pintura fácilmente")
            weaknesses_en.append("Poor floor spacing: opposing defenses can pack the lane")

        chemistry_score = min(100.0, max(20.0, chemistry))

        # 7. Projected Offensive & Defensive Ratings
        avg_bpm = sum((p.bpm or 0.0) for p in slots) / max(len(slots), 1)
        avg_ts = sum(p.ts_pct for p in slots) / max(len(slots), 1)

        ortg = round(105.0 + (avg_ts - 0.53) * 60.0 + (spacing_score - 50.0) * 0.15 + (playmaking_score - 50.0) * 0.12 + (chemistry_score - 70.0) * 0.1, 1)
        drtg = round(114.0 - (perimeter_def_score - 50.0) * 0.12 - (rim_prot_score - 50.0) * 0.14 - (rebounding_score - 50.0) * 0.06 - avg_bpm * 0.5, 1)
        net_rating = round(ortg - drtg, 1)
        pace = round(96.0 + (playmaking_score * 0.08) + (perimeter_def_score * 0.04), 1)

        metrics = LineupTeamMetrics(
            ortg=ortg,
            drtg=drtg,
            net_rating=net_rating,
            pace=pace,
            spacing_score=round(spacing_score, 1),
            playmaking_score=round(playmaking_score, 1),
            rebounding_score=round(rebounding_score, 1),
            perimeter_defense_score=round(perimeter_def_score, 1),
            rim_protection_score=round(rim_prot_score, 1),
            chemistry_score=round(chemistry_score, 1),
            total_ppg=round(total_ppg, 1),
            total_rpg=round(total_rpg, 1),
            total_apg=round(total_apg, 1),
            total_rings=total_rings,
            total_mvps=total_mvps,
            total_all_nba=total_all_nba,
            synergy_strengths_es=strengths_es or ["Quinteto balanceado"],
            synergy_strengths_en=strengths_en or ["Balanced tactical lineup"],
            synergy_weaknesses_es=weaknesses_es or ["Sin debilidades críticas evidentes"],
            synergy_weaknesses_en=weaknesses_en or ["No critical structural weaknesses"],
        )

        return LineupTeamEvaluationResponse(
            team_name=team_name,
            slots=slots,
            metrics=metrics,
        )

    def simulate_5v5_game(
        self, team1_req: LineupTeamRequest, team2_req: LineupTeamRequest
    ) -> Lineup5v5SimulationResponse:
        """
        Full 48-minute 5 vs 5 game simulation with possession model, Box Score, and quarter-by-quarter scoring.
        """
        t1_eval = self.evaluate_lineup(team1_req.team_name, team1_req.slots)
        t2_eval = self.evaluate_lineup(team2_req.team_name, team2_req.slots)

        m1 = t1_eval.metrics
        m2 = t2_eval.metrics

        # Pace & Possessions
        game_pace = (m1.pace + m2.pace) / 2.0
        possessions = int(round(game_pace))

        # Expected offensive efficiency per 100 possessions
        t1_eff = (m1.ortg + (115.0 - m2.drtg) * 0.8) / 100.0
        t2_eff = (m2.ortg + (115.0 - m1.drtg) * 0.8) / 100.0

        # Win probability with logistic sigmoid
        net_diff = (m1.net_rating - m2.net_rating) + (m1.chemistry_score - m2.chemistry_score) * 0.25
        t1_prob = 1.0 / (1.0 + math.exp(-net_diff * 0.12))
        t1_prob_pct = round(t1_prob * 100.0, 1)
        t2_prob_pct = round((1.0 - t1_prob) * 100.0, 1)

        # Baseline point projection
        t1_total_pts = int(round(possessions * t1_eff))
        t2_total_pts = int(round(possessions * t2_eff))

        # Prevent ties in simulation
        if t1_total_pts == t2_total_pts:
            if t1_prob_pct >= 50.0:
                t1_total_pts += random.choice([2, 3])
            else:
                t2_total_pts += random.choice([2, 3])

        # Distribute into 4 quarters
        def distribute_quarters(total: int) -> List[int]:
            base = total // 4
            rem = total % 4
            q = [base, base, base, base]
            # Add remaining points randomly
            for _ in range(rem):
                idx = random.randint(0, 3)
                q[idx] += 1
            # Add small natural variance (+/- 1-3 pts per quarter)
            v1 = random.randint(-2, 2)
            v2 = random.randint(-2, 2)
            q[0] += v1
            q[1] -= v1
            q[2] += v2
            q[3] -= v2
            return q

        q_t1 = distribute_quarters(t1_total_pts)
        q_t2 = distribute_quarters(t2_total_pts)

        # Build Box Scores for Team 1
        def build_boxscore(slots: List[LineupSlotDetail], total_pts: int, opp_pts: int) -> List[LineupPlayerBoxScore]:
            box: List[LineupPlayerBoxScore] = []
            if not slots:
                return box

            # Total player points weight
            total_ppg_sum = sum(p.ppg for p in slots) or 1.0
            total_rpg_sum = sum(p.rpg for p in slots) or 1.0
            total_apg_sum = sum(p.apg for p in slots) or 1.0

            # Target team totals
            target_reb = int(round(44.0 + (m1.rebounding_score - 50.0) * 0.15))
            target_ast = int(round(26.0 + (m1.playmaking_score - 50.0) * 0.15))
            target_stl = int(round(7.5 + (m1.perimeter_defense_score - 50.0) * 0.08))
            target_blk = int(round(5.0 + (m1.rim_protection_score - 50.0) * 0.08))

            for p in slots:
                # Minutes: starters play 32-38 mins
                mins = random.randint(33, 38)
                share_pts = p.ppg / total_ppg_sum
                share_reb = p.rpg / total_rpg_sum
                share_ast = p.apg / total_apg_sum

                pts = max(4, int(round(total_pts * share_pts)))
                reb = max(1, int(round(target_reb * share_reb)))
                ast = max(0, int(round(target_ast * share_ast)))
                stl = max(0, int(round(target_stl * (p.spg / (sum(x.spg for x in slots) or 1.0)))))
                blk = max(0, int(round(target_blk * (p.bpg / (sum(x.bpg for x in slots) or 1.0)))))

                # Shot distribution
                fg3m = int(round(pts * (p.fg3_pct * 0.6) / 3.0)) if p.fg3_pct > 0.25 else 0
                fg3a = int(round(fg3m / max(p.fg3_pct, 0.30))) if fg3m > 0 else random.randint(0, 1)
                
                remaining_pts = pts - (fg3m * 3)
                ftm = int(round(remaining_pts * 0.25))
                fta = int(round(ftm / max(p.ft_pct, 0.70))) if ftm > 0 else 0
                
                fg2m = max(0, (remaining_pts - ftm) // 2)
                fgm = fg2m + fg3m
                fga = max(fgm, int(round(fgm / max(p.fg_pct, 0.45))))
                actual_fg_pct = round(fgm / max(fga, 1), 3)

                plus_minus = total_pts - opp_pts

                box.append(
                    LineupPlayerBoxScore(
                        player_id=p.player_id,
                        player_name=p.player_name,
                        position=p.position,
                        season_label=p.season_label,
                        minutes=mins,
                        pts=pts,
                        reb=reb,
                        ast=ast,
                        stl=stl,
                        blk=blk,
                        fgm=fgm,
                        fga=fga,
                        fg_pct=actual_fg_pct,
                        fg3m=fg3m,
                        fg3a=fg3a,
                        ftm=ftm,
                        fta=fta,
                        plus_minus=plus_minus,
                    )
                )
            return box

        box1 = build_boxscore(t1_eval.slots, t1_total_pts, t2_total_pts)
        box2 = build_boxscore(t2_eval.slots, t2_total_pts, t1_total_pts)

        # Determine MVP from winning team
        winning_box = box1 if t1_total_pts > t2_total_pts else box2
        if winning_box:
            mvp_candidate = max(
                winning_box,
                key=lambda b: (b.pts * 1.0) + (b.reb * 1.2) + (b.ast * 1.5) + (b.stl * 2.0) + (b.blk * 2.0),
            )
            mvp_name = mvp_candidate.player_name
            mvp_stats = f"{mvp_candidate.pts} PTS, {mvp_candidate.reb} REB, {mvp_candidate.ast} AST, {mvp_candidate.stl} STL"
        else:
            mvp_name = "N/A"
            mvp_stats = ""

        # Tactical narrative
        winner_name = team1_req.team_name if t1_total_pts > t2_total_pts else team2_req.team_name
        diff_pts = abs(t1_total_pts - t2_total_pts)

        summary_es = (
            f"{winner_name} se lleva la victoria {max(t1_total_pts, t2_total_pts)}-{min(t1_total_pts, t2_total_pts)} "
            f"en un duelo electrizante de {possessions} posesiones. La clave estuvo en "
            f"{'el dominante espaciado y fluidez ofensiva' if m1.spacing_score > m2.spacing_score else 'el control del rebote y la contención defensiva en la pintura'}. "
            f"{mvp_name} se coronó como la gran figura del encuentro con {mvp_stats}."
        )
        summary_en = (
            f"{winner_name} claims the victory {max(t1_total_pts, t2_total_pts)}-{min(t1_total_pts, t2_total_pts)} "
            f"in a high-octane battle of {possessions} possessions. The decisive factor was "
            f"{'superior floor spacing and ball movement' if m1.spacing_score > m2.spacing_score else 'interior dominance on the glass and lockdown rim protection'}. "
            f"{mvp_name} earned Game MVP honors with {mvp_stats}."
        )

        matchups_es = [
            f"Duelo en el Perímetro: {t1_eval.slots[0].player_name if t1_eval.slots else 'PG1'} vs {t2_eval.slots[0].player_name if t2_eval.slots else 'PG2'}",
            f"Batalla en la Pintura: {t1_eval.slots[-1].player_name if t1_eval.slots else 'C1'} vs {t2_eval.slots[-1].player_name if t2_eval.slots else 'C2'}",
        ]
        matchups_en = [
            f"Perimeter Showdown: {t1_eval.slots[0].player_name if t1_eval.slots else 'PG1'} vs {t2_eval.slots[0].player_name if t2_eval.slots else 'PG2'}",
            f"Battle in the Paint: {t1_eval.slots[-1].player_name if t1_eval.slots else 'C1'} vs {t2_eval.slots[-1].player_name if t2_eval.slots else 'C2'}",
        ]

        # Build 48-minute tactical match momentum flow
        from app.schemas import MatchMomentumPoint, MatchMomentumTimeline
        momentum_points: List[MatchMomentumPoint] = []
        largest_lead_t1 = 0
        largest_lead_t2 = 0
        lead_changes = 0
        last_leader = 0
        rng_m = random.Random(t1_total_pts * 1000 + t2_total_pts)
        q_minutes = [12, 24, 36, 48]

        for minute_idx in range(1, 49):
            q = 1 if minute_idx <= 12 else (2 if minute_idx <= 24 else (3 if minute_idx <= 36 else 4))
            q_start = 0 if q == 1 else q_minutes[q - 2]
            q_fraction = (minute_idx - q_start) / 12.0

            target_q_t1 = q_t1[q - 1]
            target_q_t2 = q_t2[q - 1]

            prev_q_sum_t1 = sum(q_t1[:q - 1])
            prev_q_sum_t2 = sum(q_t2[:q - 1])

            cur_t1 = prev_q_sum_t1 + int(target_q_t1 * q_fraction) + rng_m.randint(-1, 1)
            cur_t2 = prev_q_sum_t2 + int(target_q_t2 * q_fraction) + rng_m.randint(-1, 1)

            if minute_idx == 48:
                cur_t1 = t1_total_pts
                cur_t2 = t2_total_pts

            diff = cur_t1 - cur_t2
            if diff > largest_lead_t1:
                largest_lead_t1 = diff
            if -diff > largest_lead_t2:
                largest_lead_t2 = -diff

            current_leader = 1 if diff > 0 else (2 if diff < 0 else 0)
            if current_leader != 0 and last_leader != 0 and current_leader != last_leader:
                lead_changes += 1
            if current_leader != 0:
                last_leader = current_leader

            mom_val = float(np.clip(diff * 4.5 + rng_m.uniform(-8, 8), -100.0, 100.0))

            highlight_es = None
            highlight_en = None
            if minute_idx in [12, 24, 36]:
                highlight_es = f"Final del Q{q}: {cur_t1} - {cur_t2}"
                highlight_en = f"End of Q{q}: {cur_t1} - {cur_t2}"
            elif minute_idx == 44 and abs(diff) <= 6:
                highlight_es = "Momento Clutch: Duelo decisivo en el cierre del partido"
                highlight_en = "Clutch Time: Decisive showdown in closing minutes"

            momentum_points.append(
                MatchMomentumPoint(
                    minute=float(minute_idx),
                    quarter=q,
                    score_differential=diff,
                    possession_momentum=round(mom_val, 1),
                    lead_team=current_leader,
                    event_highlight_es=highlight_es,
                    event_highlight_en=highlight_en,
                )
            )

        momentum_timeline = MatchMomentumTimeline(
            team1_name=team1_req.team_name,
            team2_name=team2_req.team_name,
            points=momentum_points,
            largest_lead_team1=max(largest_lead_t1, 0),
            largest_lead_team2=max(largest_lead_t2, 0),
            lead_changes=max(lead_changes, 1),
            clutch_swing_minute=44.0 if abs(t1_total_pts - t2_total_pts) <= 6 else 34.0,
        )

        return Lineup5v5SimulationResponse(
            team1_name=team1_req.team_name,
            team2_name=team2_req.team_name,
            team1_slots=t1_eval.slots,
            team2_slots=t2_eval.slots,
            team1_metrics=m1,
            team2_metrics=m2,
            team1_score=t1_total_pts,
            team2_score=t2_total_pts,
            team1_win_prob=t1_prob_pct,
            team2_win_prob=t2_prob_pct,
            quarter_scores_t1=q_t1,
            quarter_scores_t2=q_t2,
            game_mvp_name=mvp_name,
            game_mvp_stats=mvp_stats,
            team1_boxscore=box1,
            team2_boxscore=box2,
            tactical_summary_es=summary_es,
            tactical_summary_en=summary_en,
            momentum_timeline=momentum_timeline,
        )

    def get_classic_presets(self) -> List[ClassicPresetLineup]:
        """
        Returns pre-packaged legendary quintets ready to load into the court.
        """
        def find_p_id(name: str) -> int:
            from app.api.v1.versus import _resolve_player_id
            pid = _resolve_player_id(self.session, name)
            return pid or 2544  # Fallback to LeBron if not found

        seasons_all = self.session.exec(select(Season)).all()
        s_map = {s.season_label: s.id for s in seasons_all}

        s96 = s_map.get("1995-96")
        s17 = s_map.get("2016-17")
        s14 = s_map.get("2013-14")
        s13 = s_map.get("2012-13")
        s24 = s_map.get("2023-24")

        # 1. 1995-96 Chicago Bulls (72-10 Championship)
        bulls_slots = [
            LineupSlotRequest(position="PG", player_id=find_p_id("Ron Harper"), season_id=s96),
            LineupSlotRequest(position="SG", player_id=find_p_id("Michael Jordan"), season_id=s96),
            LineupSlotRequest(position="SF", player_id=find_p_id("Scottie Pippen"), season_id=s96),
            LineupSlotRequest(position="PF", player_id=find_p_id("Dennis Rodman"), season_id=s96),
            LineupSlotRequest(position="C", player_id=find_p_id("Luc Longley"), season_id=s96),
        ]

        # 2. 2016-17 Golden State Warriors (Death Lineup 16-1 Playoffs)
        warriors_slots = [
            LineupSlotRequest(position="PG", player_id=find_p_id("Stephen Curry"), season_id=s17),
            LineupSlotRequest(position="SG", player_id=find_p_id("Klay Thompson"), season_id=s17),
            LineupSlotRequest(position="SF", player_id=find_p_id("Kevin Durant"), season_id=s17),
            LineupSlotRequest(position="PF", player_id=find_p_id("Draymond Green"), season_id=s17),
            LineupSlotRequest(position="C", player_id=find_p_id("Zaza Pachulia"), season_id=s17),
        ]

        # 3. 2000-01 Los Angeles Lakers (15-1 Playoffs & Three-Peat)
        lakers_slots = [
            LineupSlotRequest(position="PG", player_id=find_p_id("Derek Fisher")),
            LineupSlotRequest(position="SG", player_id=find_p_id("Kobe Bryant")),
            LineupSlotRequest(position="SF", player_id=find_p_id("Rick Fox")),
            LineupSlotRequest(position="PF", player_id=find_p_id("Horace Grant")),
            LineupSlotRequest(position="C", player_id=find_p_id("Shaquille O'Neal")),
        ]

        # 4. 2013-14 San Antonio Spurs (The Beautiful Game)
        spurs_slots = [
            LineupSlotRequest(position="PG", player_id=find_p_id("Tony Parker"), season_id=s14),
            LineupSlotRequest(position="SG", player_id=find_p_id("Danny Green"), season_id=s14),
            LineupSlotRequest(position="SF", player_id=find_p_id("Kawhi Leonard"), season_id=s14),
            LineupSlotRequest(position="PF", player_id=find_p_id("Tim Duncan"), season_id=s14),
            LineupSlotRequest(position="C", player_id=find_p_id("Tiago Splitter"), season_id=s14),
        ]

        # 5. 2012-13 Miami Heat (Big 3 & 27 Game Win Streak)
        heat_slots = [
            LineupSlotRequest(position="PG", player_id=find_p_id("Mario Chalmers"), season_id=s13),
            LineupSlotRequest(position="SG", player_id=find_p_id("Dwyane Wade"), season_id=s13),
            LineupSlotRequest(position="SF", player_id=find_p_id("LeBron James"), season_id=s13),
            LineupSlotRequest(position="PF", player_id=find_p_id("Shane Battier"), season_id=s13),
            LineupSlotRequest(position="C", player_id=find_p_id("Chris Bosh"), season_id=s13),
        ]

        # 6. 2023-24 Boston Celtics (Modern 5-Out Champions)
        celtics_slots = [
            LineupSlotRequest(position="PG", player_id=find_p_id("Jrue Holiday"), season_id=s24),
            LineupSlotRequest(position="SG", player_id=find_p_id("Derrick White"), season_id=s24),
            LineupSlotRequest(position="SF", player_id=find_p_id("Jaylen Brown"), season_id=s24),
            LineupSlotRequest(position="PF", player_id=find_p_id("Jayson Tatum"), season_id=s24),
            LineupSlotRequest(position="C", player_id=find_p_id("Kristaps Porzingis"), season_id=s24),
        ]

        # 7. All-Time USA Dream Team
        usa_slots = [
            LineupSlotRequest(position="PG", player_id=find_p_id("Stephen Curry")),
            LineupSlotRequest(position="SG", player_id=find_p_id("Michael Jordan")),
            LineupSlotRequest(position="SF", player_id=find_p_id("Kobe Bryant")),
            LineupSlotRequest(position="PF", player_id=find_p_id("LeBron James")),
            LineupSlotRequest(position="C", player_id=find_p_id("Shaquille O'Neal")),
        ]

        # 8. All-Time International Dream Team
        world_slots = [
            LineupSlotRequest(position="PG", player_id=find_p_id("Luka Doncic")),
            LineupSlotRequest(position="SG", player_id=find_p_id("Manu Ginobili")),
            LineupSlotRequest(position="SF", player_id=find_p_id("Giannis Antetokounmpo")),
            LineupSlotRequest(position="PF", player_id=find_p_id("Dirk Nowitzki")),
            LineupSlotRequest(position="C", player_id=find_p_id("Nikola Jokic")),
        ]

        return [
            ClassicPresetLineup(
                id="bulls_1996",
                name="Chicago Bulls 1995-96",
                year="1995-96",
                era="Era 90s Clásica",
                description_es="El mítico equipo del 72-10 liderado por Michael Jordan, Scottie Pippen y Dennis Rodman.",
                description_en="The iconic 72-10 championship team led by Jordan, Pippen, and Rodman.",
                slots=bulls_slots,
            ),
            ClassicPresetLineup(
                id="warriors_2017",
                name="Golden State Warriors 2016-17",
                year="2016-17",
                era="Era del Triple & Spacing",
                description_es="El Death Lineup con Curry, Klay, KD y Draymond: 16-1 en playoffs y espaciado letal.",
                description_en="The unstoppable Death Lineup featuring Curry, Thompson, Durant, and Green.",
                slots=warriors_slots,
            ),
            ClassicPresetLineup(
                id="lakers_2001",
                name="Los Angeles Lakers 2000-01",
                year="2000-01",
                era="Era del Three-Peat",
                description_es="La fuerza bruta de Shaquille O'Neal en su prime combinado con la magia anotadora de Kobe Bryant.",
                description_en="Peak Shaq interior dominance paired with young Kobe Bryant scoring mastery.",
                slots=lakers_slots,
            ),
            ClassicPresetLineup(
                id="spurs_2014",
                name="San Antonio Spurs 2013-14",
                year="2013-14",
                era="Era del Pase & Fundamentos",
                description_es="'The Beautiful Game': la cumbre del juego colectivo con Duncan, Parker, Ginóbili y Kawhi.",
                description_en="'The Beautiful Game': the pinnacle of passing and fundamentals with Duncan and Kawhi.",
                slots=spurs_slots,
            ),
            ClassicPresetLineup(
                id="heat_2013",
                name="Miami Heat 2012-13",
                year="2012-13",
                era="Era del Big 3",
                description_es="LeBron James en su pico físico y táctico junto a Wade y Bosh, logrando 27 victorias consecutivas.",
                description_en="Peak LeBron James alongside Dwyane Wade and Chris Bosh on a 27-game streak.",
                slots=heat_slots,
            ),
            ClassicPresetLineup(
                id="celtics_2024",
                name="Boston Celtics 2023-24",
                year="2023-24",
                era="Era Moderna 5-Out",
                description_es="Alineación moderna de 5 tiradores perimetrales y defensa de cambios múltiples con Tatum y Brown.",
                description_en="Modern 5-out spacing powerhouse anchored by Tatum, Brown, Holiday, and Porzingis.",
                slots=celtics_slots,
            ),
            ClassicPresetLineup(
                id="all_time_usa",
                name="USA All-Time Dream Team",
                year="All-Time",
                era="Selección Histórica USA",
                description_es="El quinteto definitivo del baloncesto estadounidense con Jordan, LeBron, Kobe, Curry y Shaq.",
                description_en="The ultimate USA dream team lineup featuring Jordan, LeBron, Kobe, Curry, and Shaq.",
                slots=usa_slots,
            ),
            ClassicPresetLineup(
                id="all_time_world",
                name="World All-Time Legends",
                year="All-Time",
                era="Selección Internacional",
                description_es="Las leyendas internacionales más dominantes: Dončić, Ginóbili, Antetokounmpo, Nowitzki y Jokić.",
                description_en="The all-time international squad featuring Dončić, Ginóbili, Giannis, Dirk, and Jokić.",
                slots=world_slots,
            ),
        ]
