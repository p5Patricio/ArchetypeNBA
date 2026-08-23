from typing import Optional, Dict, Any, List
from fastapi import HTTPException
import numpy as np
from app.models import Player
from app.repositories.player import PlayerRepository
from app.repositories.stats import StatsRepository
from app.services.clustering import ROLE_METADATA, ClusteringService


class PlayerService:
    def __init__(self, player_repo: PlayerRepository, stats_repo: StatsRepository):
        self.player_repo = player_repo
        self.stats_repo = stats_repo

    def get_analysis(self, player_name: str, season_id: Optional[int] = None) -> Dict[str, Any]:
        player = self.player_repo.get_by_name(player_name)
        if not player:
            raise HTTPException(status_code=404, detail=f"Player '{player_name}' not found")

        if season_id:
            player_stats = next((s for s in player.season_stats if s.season_id == season_id), None)
        else:
            player_stats = player.season_stats[0] if player.season_stats else None

        if not player_stats:
            raise HTTPException(status_code=404, detail=f"No stats found for player '{player_name}' in season {season_id or 'default'}")

        all_season_stats = self.stats_repo.find_by_season(player_stats.season_id)
        cluster_stats = [s for s in all_season_stats if s.cluster_id == player_stats.cluster_id and s.player_id != player.id]

        comparison = []
        stat_fields = [
            "gp", "gs", "min", "fgm", "fga", "fg_pct", "fg3m", "fg3a", "fg3_pct",
            "ftm", "fta", "ft_pct", "oreb", "dreb", "reb", "ast", "stl", "blk", "tov", "pf", "pts",
        ]

        for field in stat_fields:
            p_val = getattr(player_stats, field, 0) or 0
            c_vals = [getattr(s, field, 0) or 0 for s in cluster_stats if getattr(s, field, 0) is not None]
            c_avg = sum(c_vals) / len(c_vals) if c_vals else 0
            diff = p_val - c_avg
            percent = (diff / c_avg * 100) if c_avg else 0
            comparison.append({
                "stat": field,
                "player_value": p_val,
                "cluster_avg": round(c_avg, 2),
                "diff": round(diff, 2),
                "percent_diff": round(percent, 2),
            })

        p_gp = max(player_stats.gp or 1, 1)
        player_per_game = {
            "pts": round(player_stats.pts / p_gp, 1) if player_stats.pts else 0.0,
            "reb": round(player_stats.reb / p_gp, 1) if player_stats.reb else 0.0,
            "ast": round(player_stats.ast / p_gp, 1) if player_stats.ast else 0.0,
            "stl": round(player_stats.stl / p_gp, 1) if player_stats.stl else 0.0,
            "blk": round(player_stats.blk / p_gp, 1) if player_stats.blk else 0.0,
            "fg3m": round(player_stats.fg3m / p_gp, 1) if player_stats.fg3m else 0.0,
            "fg_pct": round(player_stats.fg_pct, 3) if player_stats.fg_pct else 0.0,
            "min": round(player_stats.min / p_gp, 1) if player_stats.min else 0.0,
            "gp": player_stats.gp or 0,
        }

        # Compute cluster averages per game
        cluster_pg_pts = [s.pts / max(s.gp or 1, 1) for s in cluster_stats if s.pts]
        cluster_pg_reb = [s.reb / max(s.gp or 1, 1) for s in cluster_stats if s.reb]
        cluster_pg_ast = [s.ast / max(s.gp or 1, 1) for s in cluster_stats if s.ast]
        cluster_pg_stl = [s.stl / max(s.gp or 1, 1) for s in cluster_stats if s.stl]
        cluster_pg_blk = [s.blk / max(s.gp or 1, 1) for s in cluster_stats if s.blk]
        cluster_pg_fg3m = [s.fg3m / max(s.gp or 1, 1) for s in cluster_stats if s.fg3m]
        cluster_fg_pct = [s.fg_pct for s in cluster_stats if s.fg_pct]

        cluster_mean_pg = {
            "pts": round(sum(cluster_pg_pts) / len(cluster_pg_pts), 1) if cluster_pg_pts else 12.0,
            "reb": round(sum(cluster_pg_reb) / len(cluster_pg_reb), 1) if cluster_pg_reb else 4.0,
            "ast": round(sum(cluster_pg_ast) / len(cluster_pg_ast), 1) if cluster_pg_ast else 2.5,
            "stl": round(sum(cluster_pg_stl) / len(cluster_pg_stl), 1) if cluster_pg_stl else 0.8,
            "blk": round(sum(cluster_pg_blk) / len(cluster_pg_blk), 1) if cluster_pg_blk else 0.5,
            "fg3m": round(sum(cluster_pg_fg3m) / len(cluster_pg_fg3m), 1) if cluster_pg_fg3m else 1.2,
            "fg_pct": round(sum(cluster_fg_pct) / len(cluster_fg_pct), 3) if cluster_fg_pct else 0.45,
            "min": 24.0,
        }

        # Calculate dynamic soft clustering probabilities across all 7 archetypes
        mpg = max((player_stats.min or 0) / p_gp, 4.0)
        scale_36 = 36.0 / mpg
        p_vec = [
            ((player_stats.pts or 0.0) / p_gp) * scale_36,
            ((player_stats.reb or 0.0) / p_gp) * scale_36,
            ((player_stats.ast or 0.0) / p_gp) * scale_36,
            ((player_stats.stl or 0.0) / p_gp) * scale_36,
            ((player_stats.blk or 0.0) / p_gp) * scale_36,
            ((player_stats.fg3m or 0.0) / p_gp) * scale_36,
            player_stats.fg_pct or 0.45,
            (player_stats.fg3a or 0.0) / max(player_stats.fga or 1.0, 1.0),
        ]

        # Standard cluster benchmarks for the 7 archetypes
        archetype_benchmarks = np.array([
            [17.0, 9.2, 4.2, 1.1, 1.1, 1.3, 0.52, 0.23],  # 0: Playmaking Hub & Unicorn Big
            [12.1, 5.8, 3.9, 1.9, 0.6, 1.6, 0.43, 0.46],  # 1: POA Lockdown Stopper
            [14.3, 11.3, 2.3, 0.9, 1.9, 0.3, 0.60, 0.07], # 2: Traditional Rim Protector & Roll Big
            [12.3, 5.6, 2.5, 1.0, 0.6, 1.9, 0.43, 0.50],  # 3: Versatile Connecting Wing
            [23.4, 5.5, 5.3, 1.1, 0.5, 2.5, 0.47, 0.38],  # 4: Heliocentric Primary Scorer
            [16.1, 4.7, 2.8, 1.0, 0.4, 3.2, 0.43, 0.66],  # 5: Pure 3&D & Perimeter Sniper
            [14.0, 4.2, 6.7, 1.2, 0.3, 1.8, 0.43, 0.43],  # 6: Floor General & Pure Playmaker
        ])

        role_breakdown = ClusteringService.calculate_soft_probabilities(p_vec, archetype_benchmarks)
        primary_role = role_breakdown[0]["role_name_en"] if role_breakdown else "NBA Tactical Player"
        primary_cid = role_breakdown[0]["cluster_id"] if role_breakdown else (player_stats.cluster_id or 0)

        return {
            "player_name": player.full_name,
            "team": player_stats.team.abbreviation if player_stats.team else None,
            "cluster_id": primary_cid,
            "role_name": primary_role,
            "role_breakdown": role_breakdown,
            "comparison": comparison,
            "player_stats": player_per_game,
            "cluster_mean": cluster_mean_pg,
        }

    def get_radars(self, player_name: str) -> Dict[str, Any]:
        player = self.player_repo.get_by_name(player_name)
        if not player:
            raise HTTPException(status_code=404, detail=f"Player '{player_name}' not found")

        stats = player.season_stats
        return {
            "player_name": player.full_name,
            "seasons": [
                {
                    "season_id": s.season_id,
                    "season_label": s.season.season_label if s.season else None,
                    "stats": {
                        "pts": s.pts, "ast": s.ast, "reb": s.reb,
                        "stl": s.stl, "blk": s.blk, "tov": s.tov,
                        "fg_pct": s.fg_pct, "fg3_pct": s.fg3_pct, "ft_pct": s.ft_pct,
                    },
                }
                for s in stats
            ],
        }

    def get_season_players(self, season_id: int, team: Optional[str] = None) -> List[Dict[str, Any]]:
        stats = self.stats_repo.find_by_season(season_id, team_abbreviation=team)
        
        # Deduplicate multi-stint player records (keep stint with most minutes)
        deduped = {}
        for s in stats:
            if not s.player:
                continue
            pid = s.player.id
            if pid not in deduped or (s.min or 0) > (deduped[pid].min or 0):
                deduped[pid] = s

        results = []
        for s in deduped.values():
            gp = max(s.gp or 1, 1)
            ppg = round((s.pts or 0.0) / gp, 1)
            rpg = round((s.reb or 0.0) / gp, 1)
            apg = round((s.ast or 0.0) / gp, 1)
            spg = round((s.stl or 0.0) / gp, 1)
            bpg = round((s.blk or 0.0) / gp, 1)
            fg3m_pg = round((s.fg3m or 0.0) / gp, 1)
            mpg = round((s.min or 0.0) / gp, 1)

            meta = ROLE_METADATA.get(s.cluster_id if s.cluster_id is not None else 3, {})
            role_title = meta.get("name_en", "Versatile Connecting Wing")

            results.append({
                "player_id": s.player.id,
                "player_name": s.player.full_name,
                "team_abbreviation": s.team.abbreviation if s.team else "",
                "team_name": s.team.full_name if s.team else (s.team.abbreviation if s.team else "NBA"),
                "cluster_id": s.cluster_id or 0,
                "role_name": role_title,
                "pts": ppg,
                "reb": rpg,
                "ast": apg,
                "stl": spg,
                "blk": bpg,
                "fg3m": fg3m_pg,
                "fg_pct": round(s.fg_pct, 3) if s.fg_pct else 0.0,
                "min": mpg,
                "gp": s.gp or 0,
                "headshot_url": s.player.headshot_url or f"https://cdn.nba.com/headshots/nba/latest/1040x760/{s.player.id}.png",
            })
        return sorted(results, key=lambda x: x["pts"] or 0, reverse=True)
