import math
import unicodedata
from typing import Optional, List, Dict, Any, Tuple
import numpy as np
from sqlmodel import Session, select
from app.models import Player, Season, PlayerSeasonStats, PlayerAdvancedStats
from app.schemas import (
    DoppelgangerResponse,
    DoppelgangerMatchItem,
)
from app.services.clustering import ROLE_METADATA
from app.services.training import _normalize_str, PLAYER_POSITION_MASTER_CATALOG


def _cosine_similarity(v1: np.ndarray, v2: np.ndarray) -> float:
    dot = np.dot(v1, v2)
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return float(dot / (norm1 * norm2))


class DoppelgangerService:
    def __init__(self, session: Session):
        self.session = session

    def find_doppelgangers(
        self,
        player_id_or_name: str,
        season_id: Optional[int] = None,
        top_k: int = 5,
    ) -> DoppelgangerResponse:
        # 1. Resolve target player
        target_player = None
        if str(player_id_or_name).isdigit():
            target_player = self.session.get(Player, int(player_id_or_name))
        
        if not target_player:
            clean_target = _normalize_str(str(player_id_or_name))
            all_players = self.session.exec(select(Player)).all()
            for p in all_players:
                if _normalize_str(p.full_name) == clean_target:
                    target_player = p
                    break
            if not target_player:
                for p in all_players:
                    if clean_target in _normalize_str(p.full_name) or _normalize_str(p.full_name) in clean_target:
                        target_player = p
                        break

        if not target_player:
            raise ValueError(f"Player '{player_id_or_name}' not found")

        # 2. Resolve Season
        if season_id:
            target_season = self.session.get(Season, season_id)
        else:
            p_stats = self.session.exec(
                select(PlayerSeasonStats).where(PlayerSeasonStats.player_id == target_player.id)
            ).all()
            if not p_stats:
                raise ValueError(f"No stats found for {target_player.full_name}")
            best_stat = max(p_stats, key=lambda s: s.pts or 0)
            target_season = self.session.get(Season, best_stat.season_id)

        target_stat = self.session.exec(
            select(PlayerSeasonStats).where(
                PlayerSeasonStats.player_id == target_player.id,
                PlayerSeasonStats.season_id == target_season.id,
            )
        ).first()
        if not target_stat:
            target_stat = self.session.exec(
                select(PlayerSeasonStats).where(PlayerSeasonStats.player_id == target_player.id)
            ).first()

        # Build target vector
        t_vec, t_stats_dict = self._extract_feature_vector(target_player, target_stat)

        # 3. Scan all player seasons in database (excluding target player himself)
        all_stats = self.session.exec(
            select(PlayerSeasonStats).where(
                PlayerSeasonStats.player_id != target_player.id,
                PlayerSeasonStats.gp >= 25,
                PlayerSeasonStats.pts >= 250,
            )
        ).all()

        candidates: List[Tuple[float, Player, Season, PlayerSeasonStats, Dict[str, float]]] = []

        for s_item in all_stats:
            p_item = self.session.get(Player, s_item.player_id)
            season_item = self.session.get(Season, s_item.season_id)
            if not p_item or not season_item:
                continue

            c_vec, c_stats_dict = self._extract_feature_vector(p_item, s_item)
            sim_score = _cosine_similarity(t_vec, c_vec)

            # Positional compatibility bonus/penalty
            t_pos = target_player.position or "G"
            c_pos = p_item.position or "G"
            pos_bonus = 0.04 if t_pos == c_pos else (0.02 if (t_pos in ["PG", "SG"] and c_pos in ["PG", "SG"]) or (t_pos in ["SF", "PF"] and c_pos in ["SF", "PF"]) else -0.05)

            final_similarity = float(np.clip(sim_score + pos_bonus, 0.50, 0.985)) * 100.0

            candidates.append((final_similarity, p_item, season_item, s_item, c_stats_dict))

        # Sort by similarity descending
        candidates.sort(key=lambda x: x[0], reverse=True)

        # Pick top unique players
        matches: List[DoppelgangerMatchItem] = []
        seen_player_ids = set()

        for sim_pct, p_item, season_item, s_item, c_stats_dict in candidates:
            if p_item.id in seen_player_ids:
                continue
            seen_player_ids.add(p_item.id)

            arch_id = s_item.cluster_id if s_item.cluster_id is not None else 1
            arch_meta = ROLE_METADATA.get(arch_id, ROLE_METADATA[1])

            # Compute shared traits
            shared_es, shared_en = self._determine_shared_traits(t_stats_dict, c_stats_dict)

            # Comparison dictionary
            comp_dict = {
                "ppg": {"target": t_stats_dict["ppg"], "comp": c_stats_dict["ppg"]},
                "rpg": {"target": t_stats_dict["rpg"], "comp": c_stats_dict["rpg"]},
                "apg": {"target": t_stats_dict["apg"], "comp": c_stats_dict["apg"]},
                "ts_pct": {"target": t_stats_dict["ts_pct"], "comp": c_stats_dict["ts_pct"]},
                "fg3_rate": {"target": t_stats_dict["fg3_rate"], "comp": c_stats_dict["fg3_rate"]},
                "usg_proxy": {"target": t_stats_dict["usg_proxy"], "comp": c_stats_dict["usg_proxy"]},
            }

            matches.append(
                DoppelgangerMatchItem(
                    similar_player_id=p_item.id,
                    player_name=p_item.full_name,
                    headshot_url=p_item.headshot_url or f"https://cdn.nba.com/headshots/nba/latest/1040x760/{p_item.id}.png",
                    season_label=season_item.season_label,
                    similarity_pct=round(sim_pct, 1),
                    archetype_name_es=arch_meta["name_es"],
                    archetype_name_en=arch_meta["name_en"],
                    archetype_color=arch_meta["color"],
                    shared_traits_es=shared_es,
                    shared_traits_en=shared_en,
                    key_comparison_stats=comp_dict,
                )
            )

            if len(matches) >= top_k:
                break

        # Scouting Takeaway Summary
        best_match = matches[0] if matches else None
        if best_match:
            takeaway_es = f"El perfil estadístico de {target_player.full_name} ({target_season.season_label}) presenta un índice de coincidencia del {best_match.similarity_pct}% con {best_match.player_name} en la temporada {best_match.season_label}. Ambos comparten una huella táctica enfocada en '{best_match.archetype_name_es}'."
            takeaway_en = f"{target_player.full_name}'s statistical profile ({target_season.season_label}) exhibits a {best_match.similarity_pct}% similarity index with {best_match.player_name} ({best_match.season_label}), sharing strong tactical convergence in '{best_match.archetype_name_en}'."
        else:
            takeaway_es = "Perfil con rasgos únicos en el ecosistema histórico de la NBA."
            takeaway_en = "Unique profile with distinct statistical characteristics across NBA history."

        return DoppelgangerResponse(
            target_player_id=target_player.id,
            target_player_name=target_player.full_name,
            target_season_label=target_season.season_label,
            target_position=target_player.position or "G/F",
            matches=matches,
            scouting_takeaway_es=takeaway_es,
            scouting_takeaway_en=takeaway_en,
        )

    def _extract_feature_vector(self, player: Player, stat: PlayerSeasonStats) -> Tuple[np.ndarray, Dict[str, float]]:
        gp = max(stat.gp or 1, 1)
        fga = max(stat.fga or 1.0, 1.0)
        pts = stat.pts or 0.0
        fta = stat.fta or 0.0
        fg3a = stat.fg3a or 0.0
        ast = stat.ast or 0.0
        reb = stat.reb or 0.0
        stl = stat.stl or 0.0
        blk = stat.blk or 0.0
        tov = max(stat.tov or 0.5, 0.5)

        ppg = pts / gp
        rpg = reb / gp
        apg = ast / gp
        spg = stl / gp
        bpg = blk / gp
        ts = (pts / (2.0 * (fga + 0.44 * fta))) * 100.0 if (fga + 0.44 * fta) > 0 else 53.0
        fg3_rate = (fg3a / fga) * 100.0
        ft_rate = (fta / fga) * 100.0
        ast_tov = ast / tov
        usg_proxy = ((fga + 0.44 * fta + tov) / gp) * 2.0
        h_cm = player.height_cm or 200

        vec = np.array([
            ppg / 35.0,
            rpg / 15.0,
            apg / 12.0,
            spg / 2.5,
            bpg / 3.0,
            ts / 70.0,
            fg3_rate / 60.0,
            ft_rate / 60.0,
            min(ast_tov, 4.0) / 4.0,
            usg_proxy / 35.0,
            (h_cm - 180.0) / 40.0,
        ], dtype=float)

        stats_dict = {
            "ppg": round(ppg, 1),
            "rpg": round(rpg, 1),
            "apg": round(apg, 1),
            "spg": round(spg, 1),
            "bpg": round(bpg, 1),
            "ts_pct": round(ts, 1),
            "fg3_rate": round(fg3_rate, 1),
            "usg_proxy": round(usg_proxy, 1),
        }

        return vec, stats_dict

    def _determine_shared_traits(self, t_dict: Dict[str, float], c_dict: Dict[str, float]) -> Tuple[List[str], List[str]]:
        traits_es: List[str] = []
        traits_en: List[str] = []

        if abs(t_dict["ppg"] - c_dict["ppg"]) <= 3.5 and t_dict["ppg"] >= 20.0:
            traits_es.append("Volumen anotador de élite (+20 PPG)")
            traits_en.append("Elite scoring volume (+20 PPG)")
        elif t_dict["ppg"] >= 15.0:
            traits_es.append("Anotación consistente en media y larga distancia")
            traits_en.append("Consistent multi-level scoring")

        if t_dict["apg"] >= 5.0 and c_dict["apg"] >= 5.0:
            traits_es.append("Generación primaria y visión de pase")
            traits_en.append("Primary playmaking & court vision")
        
        if t_dict["fg3_rate"] >= 35.0 and c_dict["fg3_rate"] >= 35.0:
            traits_es.append("Espaciado perimetral y amenaza de 3 puntos")
            traits_en.append("Perimeter spacing & 3PT gravity")

        if t_dict["rpg"] >= 8.0 and c_dict["rpg"] >= 8.0:
            traits_es.append("Dominio del rebote y presencia física en pintura")
            traits_en.append("Rebounding dominance & paint presence")

        if abs(t_dict["ts_pct"] - c_dict["ts_pct"]) <= 4.0:
            traits_es.append("Curva de eficiencia y True Shooting similar")
            traits_en.append("Similar True Shooting efficiency curve")

        if not traits_es:
            traits_es.append("Similitud en ritmo de posesión y uso ofensivo")
            traits_en.append("Similar possession pace and offensive usage")

        return traits_es[:3], traits_en[:3]
