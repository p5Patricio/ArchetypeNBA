import os
import json
import time
import numpy as np
import pandas as pd
from typing import Dict, Any, List
from nba_api.stats.endpoints import leaguedashplayershotlocations, leaguedashplayerstats

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(DATA_DIR, exist_ok=True)

def generate_season_data(season: str = "2023-24") -> Dict[str, Any]:
    print(f"[{season}] Fetching league shot locations and player stats from NBA API...")
    try:
        shot_data = leaguedashplayershotlocations.LeagueDashPlayerShotLocations(
            season=season,
            season_type_all_star="Regular Season",
            timeout=30
        ).get_data_frames()[0]
    except Exception as e:
        print(f"[{season}] Error fetching shot locations: {e}")
        return {}

    time.sleep(1)

    try:
        player_data = leaguedashplayerstats.LeagueDashPlayerStats(
            season=season,
            season_type_all_star="Regular Season",
            timeout=30
        ).get_data_frames()[0]
    except Exception as e:
        print(f"[{season}] Error fetching player stats: {e}")
        return {}

    # Flatten MultiIndex shot columns
    shot_cols = []
    for c in shot_data.columns:
        if c[0] == '':
            shot_cols.append(c[1])
        else:
            shot_cols.append(f"{c[0]}_{c[1]}")
    shot_data.columns = shot_cols

    # Top 300 players by minutes played
    top_300 = player_data.sort_values("MIN", ascending=False).head(300).copy()

    cols_to_keep = [
        c for c in [
            "PLAYER_ID", "PLAYER_NAME", "TEAM_ID", "TEAM_ABBREVIATION", "AGE",
            "GP", "MIN", "FGM", "FGA", "FG_PCT", "FG3M", "FG3A", "FG3_PCT",
            "FTM", "FTA", "FT_PCT", "PTS"
        ] if c in top_300.columns
    ]

    merged = pd.merge(
        top_300[cols_to_keep],
        shot_data,
        on=["PLAYER_ID", "PLAYER_NAME"],
        how="inner"
    )

    # 1. Pintura (Paint = Restricted Area + In The Paint Non-RA)
    ra_fgm = merged.get("Restricted Area_FGM", 0.0)
    ra_fga = merged.get("Restricted Area_FGA", 0.0)
    paint_non_ra_fgm = merged.get("In The Paint (Non-RA)_FGM", 0.0)
    paint_non_ra_fga = merged.get("In The Paint (Non-RA)_FGA", 0.0)

    merged["paint_fgm"] = (ra_fgm + paint_non_ra_fgm).round(0)
    merged["paint_fga"] = (ra_fga + paint_non_ra_fga).round(0)
    merged["paint_pct"] = np.where(merged["paint_fga"] > 0, merged["paint_fgm"] / merged["paint_fga"], 0.0)

    # 2. Media Distancia (Mid-Range)
    merged["mid_fgm"] = merged.get("Mid-Range_FGM", 0.0).round(0)
    merged["mid_fga"] = merged.get("Mid-Range_FGA", 0.0).round(0)
    merged["mid_pct"] = merged.get("Mid-Range_FG_PCT", 0.0)

    # 3. Tiro Libre (Free Throw)
    merged["ft_fgm"] = merged["FTM"].astype(float)
    merged["ft_fga"] = merged["FTA"].astype(float)
    merged["ft_pct"] = merged["FT_PCT"].astype(float)

    # 4. Triple (3-Point)
    merged["three_fgm"] = merged["FG3M"].astype(float)
    merged["three_fga"] = merged["FG3A"].astype(float)
    merged["three_pct"] = merged["FG3_PCT"].astype(float)

    # Calculate Volume x Efficiency Impact Scores (matches visual rankings in broadcast video)
    merged["paint_score"] = merged["paint_fgm"] * merged["paint_pct"]
    merged["mid_score"] = merged["mid_fgm"] * merged["mid_pct"]
    merged["ft_score"] = merged["ft_fgm"] * merged["ft_pct"]
    merged["three_score"] = merged["three_fgm"] * merged["three_pct"]

    # Calculate Ranks & Percentiles (1 = best, 300 = lowest; percentiles 100 = best, 0 = lowest)
    n_players = len(merged)

    # Impact Score Ranks (1 is highest score)
    merged["rank_score_paint"] = merged["paint_score"].rank(ascending=False, method="min").astype(int)
    merged["rank_score_mid"] = merged["mid_score"].rank(ascending=False, method="min").astype(int)
    merged["rank_score_ft"] = merged["ft_score"].rank(ascending=False, method="min").astype(int)
    merged["rank_score_three"] = merged["three_score"].rank(ascending=False, method="min").astype(int)

    # Pure PCT Ranks (1 is highest %)
    merged["rank_pct_paint"] = merged["paint_pct"].rank(ascending=False, method="min").astype(int)
    merged["rank_pct_mid"] = merged["mid_pct"].rank(ascending=False, method="min").astype(int)
    merged["rank_pct_ft"] = merged["ft_pct"].rank(ascending=False, method="min").astype(int)
    merged["rank_pct_three"] = merged["three_pct"].rank(ascending=False, method="min").astype(int)

    # Percentiles (0 to 100)
    merged["pctile_score_paint"] = ((n_players - merged["rank_score_paint"]) / (n_players - 1) * 100).round(1)
    merged["pctile_score_mid"] = ((n_players - merged["rank_score_mid"]) / (n_players - 1) * 100).round(1)
    merged["pctile_score_ft"] = ((n_players - merged["rank_score_ft"]) / (n_players - 1) * 100).round(1)
    merged["pctile_score_three"] = ((n_players - merged["rank_score_three"]) / (n_players - 1) * 100).round(1)

    merged["pctile_pct_paint"] = ((n_players - merged["rank_pct_paint"]) / (n_players - 1) * 100).round(1)
    merged["pctile_pct_mid"] = ((n_players - merged["rank_pct_mid"]) / (n_players - 1) * 100).round(1)
    merged["pctile_pct_ft"] = ((n_players - merged["rank_pct_ft"]) / (n_players - 1) * 100).round(1)
    merged["pctile_pct_three"] = ((n_players - merged["rank_pct_three"]) / (n_players - 1) * 100).round(1)

    # League Averages
    league_averages = {
        "paint": {
            "avg_pct": round(float(merged["paint_fgm"].sum() / max(merged["paint_fga"].sum(), 1) * 100), 1),
            "median_pct": round(float(merged["paint_pct"].median() * 100), 1),
            "avg_fgm": round(float(merged["paint_fgm"].mean()), 1),
            "avg_fga": round(float(merged["paint_fga"].mean()), 1),
        },
        "mid": {
            "avg_pct": round(float(merged["mid_fgm"].sum() / max(merged["mid_fga"].sum(), 1) * 100), 1),
            "median_pct": round(float(merged["mid_pct"].median() * 100), 1),
            "avg_fgm": round(float(merged["mid_fgm"].mean()), 1),
            "avg_fga": round(float(merged["mid_fga"].mean()), 1),
        },
        "ft": {
            "avg_pct": round(float(merged["ft_fgm"].sum() / max(merged["ft_fga"].sum(), 1) * 100), 1),
            "median_pct": round(float(merged["ft_pct"].median() * 100), 1),
            "avg_fgm": round(float(merged["ft_fgm"].mean()), 1),
            "avg_fga": round(float(merged["ft_fga"].mean()), 1),
        },
        "three": {
            "avg_pct": round(float(merged["three_fgm"].sum() / max(merged["three_fga"].sum(), 1) * 100), 1),
            "median_pct": round(float(merged["three_pct"].median() * 100), 1),
            "avg_fgm": round(float(merged["three_fgm"].mean()), 1),
            "avg_fga": round(float(merged["three_fga"].mean()), 1),
        },
    }

    # Format players list
    players_list: List[Dict[str, Any]] = []
    for _, r in merged.iterrows():
        pid = int(r["PLAYER_ID"])
        team_abbr = str(r.get("TEAM_ABBREVIATION_x", r.get("TEAM_ABBREVIATION", "NBA")))
        p_obj = {
            "id": pid,
            "name": str(r["PLAYER_NAME"]),
            "team": team_abbr,
            "headshot_url": f"https://cdn.nba.com/headshots/nba/latest/1040x760/{pid}.png",
            "minutes": float(r["MIN"]),
            "gp": int(r["GP"]),
            "pts": float(r["PTS"]),
            "zones": {
                "paint": {
                    "fgm": float(r["paint_fgm"]),
                    "fga": float(r["paint_fga"]),
                    "pct": round(float(r["paint_pct"]) * 100, 1),
                    "score": round(float(r["paint_score"]), 1),
                    "rank_score": int(r["rank_score_paint"]),
                    "rank_pct": int(r["rank_pct_paint"]),
                    "pctile_score": float(r["pctile_score_paint"]),
                    "pctile_pct": float(r["pctile_pct_paint"]),
                },
                "mid": {
                    "fgm": float(r["mid_fgm"]),
                    "fga": float(r["mid_fga"]),
                    "pct": round(float(r["mid_pct"]) * 100, 1),
                    "score": round(float(r["mid_score"]), 1),
                    "rank_score": int(r["rank_score_mid"]),
                    "rank_pct": int(r["rank_pct_mid"]),
                    "pctile_score": float(r["pctile_score_mid"]),
                    "pctile_pct": float(r["pctile_pct_mid"]),
                },
                "ft": {
                    "fgm": float(r["ft_fgm"]),
                    "fga": float(r["ft_fga"]),
                    "pct": round(float(r["ft_pct"]) * 100, 1),
                    "score": round(float(r["ft_score"]), 1),
                    "rank_score": int(r["rank_score_ft"]),
                    "rank_pct": int(r["rank_pct_ft"]),
                    "pctile_score": float(r["pctile_score_ft"]),
                    "pctile_pct": float(r["pctile_pct_ft"]),
                },
                "three": {
                    "fgm": float(r["three_fgm"]),
                    "fga": float(r["three_fga"]),
                    "pct": round(float(r["three_pct"]) * 100, 1),
                    "score": round(float(r["three_score"]), 1),
                    "rank_score": int(r["rank_score_three"]),
                    "rank_pct": int(r["rank_pct_three"]),
                    "pctile_score": float(r["pctile_score_three"]),
                    "pctile_pct": float(r["pctile_pct_three"]),
                },
            }
        }
        players_list.append(p_obj)

    dataset = {
        "season": season,
        "total_players": len(players_list),
        "league_averages": league_averages,
        "players": players_list,
    }

    out_file = os.path.join(DATA_DIR, f"parallel_shot_zones_{season.replace('-', '_')}.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)

    print(f"[{season}] Saved {len(players_list)} players to {out_file}")
    return dataset

if __name__ == "__main__":
    for s in ["2023-24", "2024-25"]:
        generate_season_data(s)
