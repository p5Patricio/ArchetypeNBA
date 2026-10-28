import os
import tempfile
from typing import Optional, List, Dict, Any
import pandas as pd
import numpy as np
from sqlmodel import Session
from fastapi import HTTPException

from app.models import Player, PlayerSeasonStats
from app.repositories.player import PlayerRepository
from app.repositories.stats import StatsRepository

# Matplotlib backend for headless environments
import matplotlib
matplotlib.use("Agg")

from app.services.scouting_report import (
    generate_player_report_pdf,
    STAT_NAMES_MAP,
    radar_stats_categories,
    assign_cluster_roles,
)


STAT_FIELD_MAP = {
    "gp": "GP", "gs": "GS", "min": "MIN", "fgm": "FGM", "fga": "FGA",
    "fg_pct": "FG_PCT", "fg3m": "FG3M", "fg3a": "FG3A", "fg3_pct": "FG3_PCT",
    "ftm": "FTM", "fta": "FTA", "ft_pct": "FT_PCT", "oreb": "OREB",
    "dreb": "DREB", "reb": "REB", "ast": "AST", "stl": "STL",
    "blk": "BLK", "tov": "TOV", "pf": "PF", "pts": "PTS",
}


class ReportService:
    def __init__(self, session: Session):
        self.session = session
        self.player_repo = PlayerRepository(session)
        self.stats_repo = StatsRepository(session)

    def generate_report(self, player_name: str, season_id: Optional[int] = None) -> str:
        player = self.player_repo.get_by_name(player_name)
        if not player:
            raise HTTPException(status_code=404, detail=f"Player '{player_name}' not found")

        stats_list = [s for s in player.season_stats if (not season_id or s.season_id == season_id)]
        if not stats_list:
            raise HTTPException(status_code=404, detail="No stats found for player")

        player_stats = stats_list[-1]

        if player_stats.cluster_id is None:
            raise HTTPException(status_code=400, detail="Clustering not initialized for this season")

        all_season_stats = self.stats_repo.find_by_season(player_stats.season_id)
        cluster_stats = [s for s in all_season_stats if s.cluster_id == player_stats.cluster_id]
        if not cluster_stats:
            raise HTTPException(status_code=404, detail="No cluster stats found")

        # Build cluster means DataFrame (legacy format: uppercase columns)
        cluster_data = []
        for s in cluster_stats:
            row = {STAT_FIELD_MAP.get(k, k): getattr(s, k, 0) for k in STAT_FIELD_MAP}
            cluster_data.append(row)

        cluster_df = pd.DataFrame(cluster_data)
        cluster_means_series = cluster_df.mean().fillna(0)

        # assign_cluster_roles expects DataFrame with cluster_id index
        cluster_means_df = pd.DataFrame([cluster_means_series.values], columns=cluster_means_series.index)
        cluster_means_df.index = [player_stats.cluster_id]
        cluster_roles = assign_cluster_roles(cluster_means_df)

        # Player stats in legacy uppercase format
        player_stats_raw = pd.Series(
            {STAT_FIELD_MAP.get(k, k): getattr(player_stats, k, 0) for k in STAT_FIELD_MAP}
        )

        # Compute weak areas and projections (matching legacy logic)
        weak_areas: List[str] = []
        projected_stats = player_stats_raw.copy()

        for field_lower, field_upper in STAT_FIELD_MAP.items():
            p_val = player_stats_raw.get(field_upper, 0)
            c_val = cluster_means_series.get(field_upper, 0)

            if field_upper.endswith("_PCT"):
                gp = player_stats_raw.get("GP", 0)
                if gp > 10 and (c_val - p_val) > 0.05:
                    weak_areas.append(
                        f"{field_upper}: {p_val:.3f} (Promedio Clúster: {c_val:.3f}) - [Necesita mejorar puntería/eficiencia]"
                    )
                    projected_stats[field_upper] = min(p_val + 0.03, c_val + 0.01)
            elif field_upper in ["TOV", "PF"]:
                if c_val > 0 and p_val > (c_val * 1.20):
                    weak_areas.append(
                        f"{field_upper}: {p_val:.2f} (Promedio Clúster: {c_val:.2f}) - [Reducir {field_upper}]"
                    )
                    projected_stats[field_upper] = max(p_val * 0.90, c_val * 0.95)
            else:
                if c_val > 0 and p_val < (c_val * 0.75):
                    weak_areas.append(
                        f"{field_upper}: {p_val:.2f} (Promedio Clúster: {c_val:.2f}) - [Necesita mejorar {field_upper}]"
                    )
                    projected_stats[field_upper] = min(p_val * 1.15, c_val * 0.95)

        # Comparison DataFrame
        comparison_rows = []
        for field_lower, field_upper in STAT_FIELD_MAP.items():
            p_val = player_stats_raw.get(field_upper, 0)
            c_val = cluster_means_series.get(field_upper, 0)
            diff = p_val - c_val
            percent = (diff / c_val * 100.0) if c_val else 0.0
            comparison_rows.append({
                "stat": field_upper,
                "Player Stats": p_val,
                "Cluster Average": c_val,
                "Difference": diff,
                "Percentage Difference": percent,
            })
        comparison_df = pd.DataFrame(comparison_rows).set_index("stat")

        # Drills HTML
        detailed_drills_html = "<h3>Sugerencias de Entrenamiento</h3><ul>"
        for w in weak_areas:
            detailed_drills_html += f"<li>{w}</li>"
        detailed_drills_html += "</ul>"

        # Legacy player_row DataFrame
        season_label = player_stats.season.season_label if player_stats.season else ""
        team_abbr = player_stats.team.abbreviation if player_stats.team else ""
        player_row = pd.DataFrame([{
            "SEASON_ID": season_label,
            "TEAM_ABBREVIATION": team_abbr,
            "PLAYER_AGE": 25,
        }])

        all_stats_columns = list(STAT_FIELD_MAP.values())

        # Run PDF generation in a temp directory
        cwd = os.getcwd()
        tmpdir = tempfile.mkdtemp()
        os.chdir(tmpdir)
        try:
            generate_player_report_pdf(
                player_name=player_name,
                player_row=player_row,
                player_cluster=player_stats.cluster_id,
                cluster_roles=cluster_roles,
                player_stats_raw=player_stats_raw,
                cluster_avg_stats_raw=cluster_means_series,
                projected_stats_raw=projected_stats,
                comparison_df=comparison_df,
                weak_areas_list=weak_areas,
                detailed_drills_html=detailed_drills_html,
                all_stats_columns=all_stats_columns,
                radar_categories=radar_stats_categories,
            )
        finally:
            os.chdir(cwd)

        pdf_path = os.path.join(tmpdir, f"Reporte_{player_name.replace(' ', '_')}.pdf")
        if not os.path.exists(pdf_path):
            raise HTTPException(status_code=500, detail="PDF generation failed")

        return pdf_path
