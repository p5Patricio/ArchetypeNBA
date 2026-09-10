from typing import Optional, List, Dict, Any, Tuple
from collections import defaultdict
from sqlmodel import Session, select
from app.models import Player, Season, PlayerMatchupStats
from app.schemas import (
    MatchupBaseline,
    DefenderMatchupItem,
    PlayerMatchupAnalysisResponse,
)


def _format_headshot(player_id: int, custom_url: Optional[str] = None) -> str:
    if custom_url:
        return custom_url
    return f"https://cdn.nba.com/headshots/nba/latest/260x190/{player_id}.png"


class MatchupService:
    def __init__(self, session: Session):
        self.session = session

    def analyze_player_matchups(
        self,
        player_id: int,
        seasons: Optional[List[str]] = None,
        min_possessions: float = 10.0,
    ) -> PlayerMatchupAnalysisResponse:
        player = self.session.get(Player, player_id)
        if not player:
            raise ValueError(f"Player with ID {player_id} not found")

        # Query all matchup records for this offensive player
        stmt = (
            select(PlayerMatchupStats, Season, Player)
            .join(Season, PlayerMatchupStats.season_id == Season.id)
            .join(Player, PlayerMatchupStats.def_player_id == Player.id)
            .where(PlayerMatchupStats.off_player_id == player_id)
        )

        if seasons:
            stmt = stmt.where(Season.season_label.in_(seasons))

        results = self.session.exec(stmt).all()
        if not results:
            # Check if player exists under a different ID in player table (canonical matching)
            alt_player = self.session.exec(
                select(Player).where(Player.full_name == player.full_name, Player.id != player_id)
            ).first()
            if alt_player:
                stmt = (
                    select(PlayerMatchupStats, Season, Player)
                    .join(Season, PlayerMatchupStats.season_id == Season.id)
                    .join(Player, PlayerMatchupStats.def_player_id == Player.id)
                    .where(PlayerMatchupStats.off_player_id == alt_player.id)
                )
                if seasons:
                    stmt = stmt.where(Season.season_label.in_(seasons))
                results = self.session.exec(stmt).all()

        if not results:
            # Auto-ingest multi-season matchups on demand from NBA API
            print(f"Auto-ingesting matchups for player '{player.full_name}' (ID: {player_id})...")
            self._auto_ingest_player_matchups(player.id, seasons)
            results = self.session.exec(stmt).all()

        if not results:
            raise ValueError(f"No matchup tracking data found for player '{player.full_name}'")

        # 1. Calculate Offensive Player Baseline across the queried matchups
        total_poss = sum(m.partial_poss for m, s, d in results)
        total_pts = sum(m.player_pts for m, s, d in results)
        total_ast = sum(m.matchup_ast for m, s, d in results)
        total_tov = sum(m.matchup_tov for m, s, d in results)
        total_fga = sum(m.matchup_fga for m, s, d in results)
        total_fta = sum(m.matchup_fta for m, s, d in results)

        denom_ts_base = 2.0 * (total_fga + 0.44 * total_fta)
        base_ts_pct = (total_pts / denom_ts_base * 100.0) if denom_ts_base > 0 else 0.0
        base_pts_75 = (total_pts / total_poss * 75.0) if total_poss > 0 else 0.0
        base_ast_75 = (total_ast / total_poss * 75.0) if total_poss > 0 else 0.0
        base_tov_75 = (total_tov / total_poss * 75.0) if total_poss > 0 else 0.0

        distinct_seasons = sorted(list(set(s.season_label for m, s, d in results)))

        baseline = MatchupBaseline(
            pts_per_75=round(base_pts_75, 1),
            ast_per_75=round(base_ast_75, 1),
            tov_per_75=round(base_tov_75, 1),
            ts_pct=round(base_ts_pct, 1),
            total_possessions=round(total_poss, 1),
            seasons=distinct_seasons,
        )

        # 2. Aggregate Matchups by Defender
        defender_aggregates: Dict[int, Dict[str, Any]] = defaultdict(lambda: {
            "defender_id": 0,
            "defender_name": "",
            "defender_headshot_url": None,
            "seasons": set(),
            "partial_poss": 0.0,
            "matchup_min": 0.0,
            "player_pts": 0.0,
            "matchup_ast": 0.0,
            "matchup_tov": 0.0,
            "matchup_fgm": 0.0,
            "matchup_fga": 0.0,
            "matchup_fg3m": 0.0,
            "matchup_fg3a": 0.0,
            "matchup_ftm": 0.0,
            "matchup_fta": 0.0,
        })

        for m, s, d in results:
            item = defender_aggregates[d.id]
            item["defender_id"] = d.id
            item["defender_name"] = d.full_name
            item["defender_headshot_url"] = _format_headshot(d.id, d.headshot_url)
            item["seasons"].add(s.season_label)
            item["partial_poss"] += m.partial_poss
            item["matchup_min"] += m.matchup_min
            item["player_pts"] += m.player_pts
            item["matchup_ast"] += m.matchup_ast
            item["matchup_tov"] += m.matchup_tov
            item["matchup_fgm"] += m.matchup_fgm
            item["matchup_fga"] += m.matchup_fga
            item["matchup_fg3m"] += m.matchup_fg3m
            item["matchup_fg3a"] += m.matchup_fg3a
            item["matchup_ftm"] += m.matchup_ftm
            item["matchup_fta"] += m.matchup_fta

        # 3. Calculate per-75, TS%, Deltas, and Classify
        all_items: List[DefenderMatchupItem] = []

        for def_id, data in defender_aggregates.items():
            poss = data["partial_poss"]
            if poss < min_possessions:
                continue

            pts = data["player_pts"]
            ast = data["matchup_ast"]
            tov = data["matchup_tov"]
            fga = data["matchup_fga"]
            fgm = data["matchup_fgm"]
            fg3a = data["matchup_fg3a"]
            fg3m = data["matchup_fg3m"]
            fta = data["matchup_fta"]
            ftm = data["matchup_ftm"]

            denom_ts = 2.0 * (fga + 0.44 * fta)
            ts_pct = (pts / denom_ts * 100.0) if denom_ts > 0 else 0.0
            pts_75 = (pts / poss * 75.0) if poss > 0 else 0.0
            ast_75 = (ast / poss * 75.0) if poss > 0 else 0.0
            tov_75 = (tov / poss * 75.0) if poss > 0 else 0.0

            delta_pts = pts_75 - base_pts_75
            delta_ast = ast_75 - base_ast_75
            delta_tov = tov_75 - base_tov_75
            delta_ts = ts_pct - base_ts_pct

            # Heuristics for Classification
            if (delta_ts <= -5.0 and delta_pts <= -3.0) or delta_pts <= -8.0 or delta_ts <= -10.0:
                classification = "kryptonite"
                classification_label = "Kryptonita / Bloqueador de Élite"
            elif delta_pts >= 8.0 or delta_ts >= 6.0:
                classification = "mismatch_exploited"
                classification_label = "Mismatch / Switch Explotado"
            elif delta_ast >= 3.0:
                classification = "playmaker_trigger"
                classification_label = "Generador de Juego Forzado"
            else:
                classification = "neutral"
                classification_label = "Matchup Neutro"

            matchup_item = DefenderMatchupItem(
                defender_id=def_id,
                defender_name=data["defender_name"],
                defender_headshot_url=data["defender_headshot_url"],
                seasons=sorted(list(data["seasons"])),
                partial_poss=round(poss, 1),
                matchup_min=round(data["matchup_min"], 1),
                player_pts=round(pts, 1),
                matchup_ast=round(ast, 1),
                matchup_tov=round(tov, 1),
                matchup_fgm=round(fgm, 1),
                matchup_fga=round(fga, 1),
                matchup_fg_pct=round((fgm / fga * 100.0) if fga > 0 else 0.0, 1),
                matchup_fg3m=round(fg3m, 1),
                matchup_fg3a=round(fg3a, 1),
                matchup_fg3_pct=round((fg3m / fg3a * 100.0) if fg3a > 0 else 0.0, 1),
                matchup_ftm=round(ftm, 1),
                matchup_fta=round(fta, 1),
                pts_per_75=round(pts_75, 1),
                ast_per_75=round(ast_75, 1),
                tov_per_75=round(tov_75, 1),
                ts_pct=round(ts_pct, 1),
                delta_pts=round(delta_pts, 1),
                delta_ast=round(delta_ast, 1),
                delta_tov=round(delta_tov, 1),
                delta_ts_pct=round(delta_ts, 1),
                classification=classification,
                classification_label=classification_label,
            )
            all_items.append(matchup_item)

        # 4. Top Stoppers and Top Targets
        stoppers = [i for i in all_items if i.classification == "kryptonite"]
        stoppers.sort(key=lambda x: (x.delta_ts_pct, x.delta_pts))
        top_stoppers = stoppers[:5]

        targets = [i for i in all_items if i.classification == "mismatch_exploited"]
        targets.sort(key=lambda x: (x.delta_pts, x.delta_ts_pct), reverse=True)
        top_targets = targets[:5]

        # Sort all matchups by volume of possessions descending
        all_items.sort(key=lambda x: x.partial_poss, reverse=True)

        return PlayerMatchupAnalysisResponse(
            player_id=player.id,
            player_name=player.full_name,
            player_headshot_url=_format_headshot(player.id, player.headshot_url),
            seasons=distinct_seasons,
            min_possessions=min_possessions,
            baseline=baseline,
            top_stoppers=top_stoppers,
            top_targets=top_targets,
            matchups=all_items,
        )

    def _auto_ingest_player_matchups(self, player_id: int, seasons: Optional[List[str]] = None) -> None:
        target_seasons = seasons if seasons else ["2023-24", "2022-23", "2021-22"]
        from app.etl.matchups import fetch_matchups_data, ingest_matchups_dataframe, _get_or_create_season
        for season_label in target_seasons:
            try:
                df = fetch_matchups_data(season=season_label, player_id=player_id)
                if df is not None and not df.empty:
                    season = _get_or_create_season(self.session, season_label)
                    ingest_matchups_dataframe(self.session, df, season)
            except Exception as e:
                print(f"Error auto-ingesting matchups for player {player_id} in season {season_label}: {e}")

