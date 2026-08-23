import math
import random
from typing import Dict, Any, List, Optional, Tuple
from sqlmodel import Session, select
from app.models import Player, PlayerSeasonStats, PlayerAdvancedStats, Season, Team
from app.services.clustering import ROLE_METADATA
from app.schemas import (
    VersusPlayerOption,
    VersusSeasonOption,
    VersusPlayerCard,
    VersusPlayerStats,
    VersusAccolades,
    VersusStatComparisonItem,
    VersusDimensionRating,
    VersusSimulationResult,
    VersusMatchupResponse,
)

# Comprehensive catalog of NBA Accolades for legends and active stars
PLAYER_ACCOLADES_CATALOG: Dict[str, Dict[str, Any]] = {
    "Michael Jordan": {
        "championships": 6, "mvp_count": 5, "finals_mvp_count": 6, "dpoy_count": 1,
        "all_nba_count": 11, "all_star_count": 14, "scoring_titles": 10,
        "olympic_medals": ["🥇 Oro Olímpico (1984)", "🥇 Oro Olímpico Dream Team (1992)"],
        "fiba_accolades": ["🏆 Torneo de las Américas Oro (1992)"], "is_hall_of_fame": True,
    },
    "LeBron James": {
        "championships": 4, "mvp_count": 4, "finals_mvp_count": 4, "dpoy_count": 0,
        "all_nba_count": 20, "all_star_count": 20, "scoring_titles": 1,
        "olympic_medals": ["🥇 Oro Olímpico (2008)", "🥇 Oro Olímpico (2012)", "🥇 Oro Olímpico París (2024)", "🥉 Bronce (2004)"],
        "fiba_accolades": ["🏆 FIBA AmeriCup Oro (2007)"], "is_hall_of_fame": True,
    },
    "Kobe Bryant": {
        "championships": 5, "mvp_count": 1, "finals_mvp_count": 2, "dpoy_count": 0,
        "all_nba_count": 15, "all_star_count": 18, "scoring_titles": 2,
        "olympic_medals": ["🥇 Oro Olímpico Redeem Team (2008)", "🥇 Oro Olímpico (2012)"],
        "fiba_accolades": ["🏆 FIBA AmeriCup Oro (2007)"], "is_hall_of_fame": True,
    },
    "Shaquille O'Neal": {
        "championships": 4, "mvp_count": 1, "finals_mvp_count": 3, "dpoy_count": 0,
        "all_nba_count": 14, "all_star_count": 15, "scoring_titles": 2,
        "olympic_medals": ["🥇 Oro Olímpico (1996)"],
        "fiba_accolades": ["🏆 Campeonato Mundial FIBA Oro (1994)"], "is_hall_of_fame": True,
    },
    "Stephen Curry": {
        "championships": 4, "mvp_count": 2, "finals_mvp_count": 1, "dpoy_count": 0,
        "all_nba_count": 10, "all_star_count": 10, "scoring_titles": 2,
        "olympic_medals": ["🥇 Oro Olímpico París (2024)"],
        "fiba_accolades": ["🏆 2x Mundial FIBA Oro (2010, 2014)"], "is_hall_of_fame": True,
    },
    "Kevin Durant": {
        "championships": 2, "mvp_count": 1, "finals_mvp_count": 2, "dpoy_count": 0,
        "all_nba_count": 11, "all_star_count": 14, "scoring_titles": 4,
        "olympic_medals": ["🥇 4x Oro Olímpico (2012, 2016, 2020, 2024)"],
        "fiba_accolades": ["🏆 Mundial FIBA Oro & MVP (2010)"], "is_hall_of_fame": True,
    },
    "Tim Duncan": {
        "championships": 5, "mvp_count": 2, "finals_mvp_count": 3, "dpoy_count": 0,
        "all_nba_count": 15, "all_star_count": 15, "scoring_titles": 0,
        "olympic_medals": ["🥉 Bronce Olímpico (2004)"],
        "fiba_accolades": ["🏆 2x FIBA AmeriCup Oro (1999, 2003)"], "is_hall_of_fame": True,
    },
    "Magic Johnson": {
        "championships": 5, "mvp_count": 3, "finals_mvp_count": 3, "dpoy_count": 0,
        "all_nba_count": 10, "all_star_count": 12, "scoring_titles": 0,
        "olympic_medals": ["🥇 Oro Olímpico Dream Team (1992)"],
        "fiba_accolades": [], "is_hall_of_fame": True,
    },
    "Larry Bird": {
        "championships": 3, "mvp_count": 3, "finals_mvp_count": 2, "dpoy_count": 0,
        "all_nba_count": 10, "all_star_count": 12, "scoring_titles": 0,
        "olympic_medals": ["🥇 Oro Olímpico Dream Team (1992)"],
        "fiba_accolades": [], "is_hall_of_fame": True,
    },
    "Hakeem Olajuwon": {
        "championships": 2, "mvp_count": 1, "finals_mvp_count": 2, "dpoy_count": 2,
        "all_nba_count": 12, "all_star_count": 12, "scoring_titles": 0,
        "olympic_medals": ["🥇 Oro Olímpico (1996)"],
        "fiba_accolades": [], "is_hall_of_fame": True,
    },
    "Giannis Antetokounmpo": {
        "championships": 1, "mvp_count": 2, "finals_mvp_count": 1, "dpoy_count": 1,
        "all_nba_count": 8, "all_star_count": 8, "scoring_titles": 0,
        "olympic_medals": [], "fiba_accolades": [], "is_hall_of_fame": True,
    },
    "Nikola Jokic": {
        "championships": 1, "mvp_count": 3, "finals_mvp_count": 1, "dpoy_count": 0,
        "all_nba_count": 6, "all_star_count": 6, "scoring_titles": 0,
        "olympic_medals": ["🥈 Plata Olímpica (2016)", "🥉 Bronce Olímpico (2024)"],
        "fiba_accolades": [], "is_hall_of_fame": True,
    },
    "Luka Doncic": {
        "championships": 0, "mvp_count": 0, "finals_mvp_count": 0, "dpoy_count": 0,
        "all_nba_count": 5, "all_star_count": 5, "scoring_titles": 1,
        "olympic_medals": [], "fiba_accolades": ["🏆 Campeón EuroBasket (2017)", "🏆 EuroLeague MVP (2018)"],
        "is_hall_of_fame": False,
    },
    "Dwyane Wade": {
        "championships": 3, "mvp_count": 0, "finals_mvp_count": 1, "dpoy_count": 0,
        "all_nba_count": 8, "all_star_count": 13, "scoring_titles": 1,
        "olympic_medals": ["🥇 Oro Olímpico (2008)", "🥉 Bronce (2004)"],
        "fiba_accolades": [], "is_hall_of_fame": True,
    },
    "Dirk Nowitzki": {
        "championships": 1, "mvp_count": 1, "finals_mvp_count": 1, "dpoy_count": 0,
        "all_nba_count": 12, "all_star_count": 14, "scoring_titles": 0,
        "olympic_medals": [], "fiba_accolades": ["🥉 Mundial FIBA Bronce & MVP (2002)"],
        "is_hall_of_fame": True,
    },
    "Kevin Garnett": {
        "championships": 1, "mvp_count": 1, "finals_mvp_count": 0, "dpoy_count": 1,
        "all_nba_count": 9, "all_star_count": 15, "scoring_titles": 0,
        "olympic_medals": ["🥇 Oro Olímpico (2000)"],
        "fiba_accolades": [], "is_hall_of_fame": True,
    },
    "Allen Iverson": {
        "championships": 0, "mvp_count": 1, "finals_mvp_count": 0, "dpoy_count": 0,
        "all_nba_count": 7, "all_star_count": 11, "scoring_titles": 4,
        "olympic_medals": ["🥉 Bronce Olímpico (2004)"],
        "fiba_accolades": [], "is_hall_of_fame": True,
    },
    "Kawhi Leonard": {
        "championships": 2, "mvp_count": 0, "finals_mvp_count": 2, "dpoy_count": 2,
        "all_nba_count": 6, "all_star_count": 6, "scoring_titles": 0,
        "olympic_medals": [], "fiba_accolades": [], "is_hall_of_fame": True,
    },
    "James Harden": {
        "championships": 0, "mvp_count": 1, "finals_mvp_count": 0, "dpoy_count": 0,
        "all_nba_count": 7, "all_star_count": 10, "scoring_titles": 3,
        "olympic_medals": ["🥇 Oro Olímpico (2012)"],
        "fiba_accolades": ["🏆 Mundial FIBA Oro (2014)"], "is_hall_of_fame": True,
    },
    "Russell Westbrook": {
        "championships": 0, "mvp_count": 1, "finals_mvp_count": 0, "dpoy_count": 0,
        "all_nba_count": 9, "all_star_count": 9, "scoring_titles": 2,
        "olympic_medals": ["🥇 Oro Olímpico (2012)"],
        "fiba_accolades": ["🏆 Mundial FIBA Oro (2010)"], "is_hall_of_fame": True,
    },
    "Chris Paul": {
        "championships": 0, "mvp_count": 0, "finals_mvp_count": 0, "dpoy_count": 0,
        "all_nba_count": 11, "all_star_count": 12, "scoring_titles": 0,
        "olympic_medals": ["🥇 2x Oro Olímpico (2008, 2012)"],
        "fiba_accolades": [], "is_hall_of_fame": True,
    },
    "Manu Ginobili": {
        "championships": 4, "mvp_count": 0, "finals_mvp_count": 0, "dpoy_count": 0,
        "all_nba_count": 2, "all_star_count": 2, "scoring_titles": 0,
        "olympic_medals": ["🥇 Oro Olímpico Atenas (2004)", "🥉 Bronce (2008)"],
        "fiba_accolades": ["🏆 EuroLeague Champion & Finals MVP (2001)"], "is_hall_of_fame": True,
    },
    "Pau Gasol": {
        "championships": 2, "mvp_count": 0, "finals_mvp_count": 0, "dpoy_count": 0,
        "all_nba_count": 4, "all_star_count": 6, "scoring_titles": 0,
        "olympic_medals": ["🥈 2x Plata Olímpica (2008, 2012)", "🥉 Bronce (2016)"],
        "fiba_accolades": ["🏆 Mundial FIBA Oro & MVP (2006)"], "is_hall_of_fame": True,
    },
    "Carmelo Anthony": {
        "championships": 0, "mvp_count": 0, "finals_mvp_count": 0, "dpoy_count": 0,
        "all_nba_count": 6, "all_star_count": 10, "scoring_titles": 1,
        "olympic_medals": ["🥇 3x Oro Olímpico (2008, 2012, 2016)", "🥉 Bronce (2004)"],
        "fiba_accolades": [], "is_hall_of_fame": True,
    },
    "Victor Wembanyama": {
        "championships": 0, "mvp_count": 0, "finals_mvp_count": 0, "dpoy_count": 0,
        "all_nba_count": 0, "all_star_count": 0, "scoring_titles": 0,
        "olympic_medals": ["🥈 Plata Olímpica París (2024 Francia)"],
        "fiba_accolades": ["🌟 NBA Rookie of the Year (2024)", "🌟 All-Defensive 1st Team (2024)"],
        "is_hall_of_fame": False,
    },
    "Anthony Davis": {
        "championships": 1, "mvp_count": 0, "finals_mvp_count": 0, "dpoy_count": 0,
        "all_nba_count": 5, "all_star_count": 9, "scoring_titles": 0,
        "olympic_medals": ["🥇 2x Oro Olímpico (2012, 2024)"],
        "fiba_accolades": ["🏆 Mundial FIBA Oro (2014)"], "is_hall_of_fame": True,
    },
    "Jayson Tatum": {
        "championships": 1, "mvp_count": 0, "finals_mvp_count": 0, "dpoy_count": 0,
        "all_nba_count": 4, "all_star_count": 5, "scoring_titles": 0,
        "olympic_medals": ["🥇 2x Oro Olímpico (2020, 2024)"],
        "fiba_accolades": [], "is_hall_of_fame": False,
    },
    "Joel Embiid": {
        "championships": 0, "mvp_count": 1, "finals_mvp_count": 0, "dpoy_count": 0,
        "all_nba_count": 5, "all_star_count": 7, "scoring_titles": 2,
        "olympic_medals": ["🥇 Oro Olímpico París (2024)"],
        "fiba_accolades": [], "is_hall_of_fame": False,
    },
    "Kyrie Irving": {
        "championships": 1, "mvp_count": 0, "finals_mvp_count": 0, "dpoy_count": 0,
        "all_nba_count": 3, "all_star_count": 8, "scoring_titles": 0,
        "olympic_medals": ["🥇 Oro Olímpico (2016)"],
        "fiba_accolades": ["🏆 Mundial FIBA Oro & MVP (2014)"], "is_hall_of_fame": False,
    },
    "Jimmy Butler": {
        "championships": 0, "mvp_count": 0, "finals_mvp_count": 0, "dpoy_count": 0,
        "all_nba_count": 5, "all_star_count": 6, "scoring_titles": 0,
        "olympic_medals": ["🥇 Oro Olímpico (2016)"],
        "fiba_accolades": [], "is_hall_of_fame": False,
    },
    "Paul George": {
        "championships": 0, "mvp_count": 0, "finals_mvp_count": 0, "dpoy_count": 0,
        "all_nba_count": 6, "all_star_count": 9, "scoring_titles": 0,
        "olympic_medals": ["🥇 Oro Olímpico (2016)"],
        "fiba_accolades": [], "is_hall_of_fame": False,
    },
    "Damian Lillard": {
        "championships": 0, "mvp_count": 0, "finals_mvp_count": 0, "dpoy_count": 0,
        "all_nba_count": 7, "all_star_count": 8, "scoring_titles": 0,
        "olympic_medals": ["🥇 Oro Olímpico (2020)"],
        "fiba_accolades": [], "is_hall_of_fame": False,
    },
}


class VersusService:
    def __init__(self, session: Session):
        self.session = session

    def get_all_players_with_seasons(self) -> List[VersusPlayerOption]:
        """
        Retrieves all players who have at least one season recorded,
        calculates peak score for each season, flags their best season, and returns options.
        """
        players = self.session.exec(select(Player)).all()
        teams = self.session.exec(select(Team)).all()
        team_map = {t.id: t.abbreviation for t in teams}
        seasons = self.session.exec(select(Season)).all()
        season_map = {s.id: s.season_label for s in seasons}

        stats_all = self.session.exec(select(PlayerSeasonStats)).all()
        adv_all = self.session.exec(select(PlayerAdvancedStats)).all()

        adv_map: Dict[Tuple[int, int], PlayerAdvancedStats] = {
            (a.player_id, a.season_id): a for a in adv_all
        }

        # Group stats by player_id
        player_stats_map: Dict[int, List[PlayerSeasonStats]] = {}
        for s in stats_all:
            player_stats_map.setdefault(s.player_id, []).append(s)

        results: List[VersusPlayerOption] = []

        for p in players:
            p_stats = player_stats_map.get(p.id, [])
            if not p_stats:
                continue

            # Deduplicate by season_id (keep the one with most minutes if traded)
            dedup_season: Dict[int, PlayerSeasonStats] = {}
            for s in p_stats:
                if s.season_id not in dedup_season or (s.min or 0) > (dedup_season[s.season_id].min or 0):
                    dedup_season[s.season_id] = s

            season_options: List[VersusSeasonOption] = []
            best_season_id = None
            best_score = -999.0
            best_label = ""

            for season_id, s in dedup_season.items():
                s_label = season_map.get(season_id, f"Season {season_id}")
                t_abbr = team_map.get(s.team_id, "NBA")
                gp = max(s.gp or 0, 1)
                pts_pg = round((s.pts or 0.0) / gp, 1)
                reb_pg = round((s.reb or 0.0) / gp, 1)
                ast_pg = round((s.ast or 0.0) / gp, 1)

                adv = adv_map.get((p.id, season_id))
                per = adv.per if adv and adv.per is not None else None
                bpm = adv.bpm if adv and adv.bpm is not None else None
                ts_pct = adv.ts_pct if adv and adv.ts_pct is not None else None

                # Calculate composite peak score
                # Base formula: PER * 0.35 + BPM * 0.25 + PPG * 0.25 + (TS% * 100) * 0.15
                base_per = per if per is not None else (pts_pg * 0.7 + reb_pg * 0.4 + ast_pg * 0.5)
                base_bpm = bpm if bpm is not None else ((pts_pg - 15.0) * 0.2)
                base_ts = (ts_pct * 100) if ts_pct is not None else (s.fg_pct * 100 if s.fg_pct else 50.0)

                peak_score = round(base_per * 0.35 + base_bpm * 0.25 + pts_pg * 0.25 + base_ts * 0.15, 2)

                if peak_score > best_score:
                    best_score = peak_score
                    best_season_id = season_id
                    best_label = s_label

                season_options.append(
                    VersusSeasonOption(
                        season_id=season_id,
                        season_label=s_label,
                        team_abbreviation=t_abbr,
                        gp=s.gp or 0,
                        pts_pg=pts_pg,
                        reb_pg=reb_pg,
                        ast_pg=ast_pg,
                        per=per,
                        bpm=bpm,
                        ts_pct=ts_pct,
                        is_best_season=False,
                        peak_score=peak_score,
                    )
                )

            # Sort seasons descending by season_label or ID
            season_options.sort(key=lambda x: x.season_label, reverse=True)

            # Mark best season
            for opt in season_options:
                if opt.season_id == best_season_id:
                    opt.is_best_season = True

            headshot = p.headshot_url or f"https://cdn.nba.com/headshots/nba/latest/1040x760/{p.id}.png"
            primary_team = season_options[0].team_abbreviation if season_options else "NBA"

            results.append(
                VersusPlayerOption(
                    player_id=p.id,
                    player_name=p.full_name,
                    team_abbreviation=primary_team,
                    position=p.position,
                    height=f"{p.height_cm} cm" if p.height_cm else None,
                    weight=f"{p.weight_kg} kg" if p.weight_kg else None,
                    headshot_url=headshot,
                    best_season_id=best_season_id or (season_options[0].season_id if season_options else 1),
                    best_season_label=best_label or (season_options[0].season_label if season_options else "2023-24"),
                    seasons=season_options,
                )
            )

        # Sort players alphabetically by full_name
        results.sort(key=lambda x: x.player_name)
        return results

    def get_player_card(self, player_id: int, season_id: Optional[int] = None) -> VersusPlayerCard:
        player = self.session.exec(select(Player).where(Player.id == player_id)).first()
        if not player:
            raise ValueError(f"Player ID {player_id} not found")

        teams = self.session.exec(select(Team)).all()
        team_map = {t.id: t for t in teams}
        seasons = self.session.exec(select(Season)).all()
        season_map = {s.id: s.season_label for s in seasons}

        stats_list = self.session.exec(
            select(PlayerSeasonStats).where(PlayerSeasonStats.player_id == player.id)
        ).all()

        adv_list = self.session.exec(
            select(PlayerAdvancedStats).where(PlayerAdvancedStats.player_id == player.id)
        ).all()
        adv_map = {a.season_id: a for a in adv_list}

        # Deduplicate stats per season
        dedup_stats: Dict[int, PlayerSeasonStats] = {}
        for s in stats_list:
            if s.season_id not in dedup_stats or (s.min or 0) > (dedup_stats[s.season_id].min or 0):
                dedup_stats[s.season_id] = s

        if not dedup_stats:
            raise ValueError(f"No statistical records found for {player.full_name}")

        # Compute available seasons with peak score
        available_seasons: List[VersusSeasonOption] = []
        best_season_id = None
        best_score = -999.0

        for sid, s in dedup_stats.items():
            gp = max(s.gp or 0, 1)
            pts_pg = round((s.pts or 0.0) / gp, 1)
            reb_pg = round((s.reb or 0.0) / gp, 1)
            ast_pg = round((s.ast or 0.0) / gp, 1)
            t_abbr = team_map[s.team_id].abbreviation if s.team_id in team_map else "NBA"

            adv = adv_map.get(sid)
            per = adv.per if adv and adv.per is not None else None
            bpm = adv.bpm if adv and adv.bpm is not None else None
            ts_pct = adv.ts_pct if adv and adv.ts_pct is not None else None

            base_per = per if per is not None else (pts_pg * 0.7 + reb_pg * 0.4 + ast_pg * 0.5)
            base_bpm = bpm if bpm is not None else ((pts_pg - 15.0) * 0.2)
            base_ts = (ts_pct * 100) if ts_pct is not None else (s.fg_pct * 100 if s.fg_pct else 50.0)
            score = round(base_per * 0.35 + base_bpm * 0.25 + pts_pg * 0.25 + base_ts * 0.15, 2)

            if score > best_score:
                best_score = score
                best_season_id = sid

            available_seasons.append(
                VersusSeasonOption(
                    season_id=sid,
                    season_label=season_map.get(sid, f"Season {sid}"),
                    team_abbreviation=t_abbr,
                    gp=s.gp or 0,
                    pts_pg=pts_pg,
                    reb_pg=reb_pg,
                    ast_pg=ast_pg,
                    per=per,
                    bpm=bpm,
                    ts_pct=ts_pct,
                    is_best_season=False,
                    peak_score=score,
                )
            )

        available_seasons.sort(key=lambda x: x.season_label, reverse=True)
        for opt in available_seasons:
            if opt.season_id == best_season_id:
                opt.is_best_season = True

        # Selected Season
        sel_season_id = season_id if (season_id and season_id in dedup_stats) else best_season_id
        sel_stat = dedup_stats[sel_season_id]
        sel_adv = adv_map.get(sel_season_id)
        sel_label = season_map.get(sel_season_id, "2023-24")

        gp = max(sel_stat.gp or 0, 1)
        team_obj = team_map.get(sel_stat.team_id)
        team_abbr = team_obj.abbreviation if team_obj else "NBA"
        team_name = team_obj.full_name if team_obj else "NBA Team"

        stats_obj = VersusPlayerStats(
            gp=sel_stat.gp or 0,
            min_pg=round((sel_stat.min or 0.0) / gp, 1),
            pts_pg=round((sel_stat.pts or 0.0) / gp, 1),
            reb_pg=round((sel_stat.reb or 0.0) / gp, 1),
            ast_pg=round((sel_stat.ast or 0.0) / gp, 1),
            stl_pg=round((sel_stat.stl or 0.0) / gp, 1),
            blk_pg=round((sel_stat.blk or 0.0) / gp, 1),
            fg3m_pg=round((sel_stat.fg3m or 0.0) / gp, 1),
            fg_pct=round(sel_stat.fg_pct or 0.0, 3),
            fg3_pct=round(sel_stat.fg3_pct or 0.0, 3),
            ft_pct=round(sel_stat.ft_pct or 0.0, 3),
            oreb_pg=round((sel_stat.oreb or 0.0) / gp, 1),
            dreb_pg=round((sel_stat.dreb or 0.0) / gp, 1),
            tov_pg=round((sel_stat.tov or 0.0) / gp, 1),
            pf_pg=round((sel_stat.pf or 0.0) / gp, 1),
            ts_pct=sel_adv.ts_pct if sel_adv else None,
            usg_pct=sel_adv.usg_pct if sel_adv else None,
            per=sel_adv.per if sel_adv else None,
            bpm=sel_adv.bpm if sel_adv else None,
            obpm=sel_adv.obpm if sel_adv else None,
            dbpm=sel_adv.dbpm if sel_adv else None,
            vorp=sel_adv.vorp if sel_adv else None,
            ws=sel_adv.ws if sel_adv else None,
            ws_per_48=sel_adv.ws_per_48 if sel_adv else None,
        )

        # Archetype resolution
        cluster_id = sel_stat.cluster_id if sel_stat.cluster_id is not None else 0
        archetype_meta = ROLE_METADATA.get(cluster_id, {
            "name_es": "Creador y Anotador Principal",
            "name_en": "Primary Ball Handler & Creator",
            "color": "#F97316"
        })

        # Accolades resolution
        acc_data = PLAYER_ACCOLADES_CATALOG.get(player.full_name, {})
        accolades = VersusAccolades(
            championships=acc_data.get("championships", 0),
            mvp_count=acc_data.get("mvp_count", 0),
            finals_mvp_count=acc_data.get("finals_mvp_count", 0),
            dpoy_count=acc_data.get("dpoy_count", 0),
            all_nba_count=acc_data.get("all_nba_count", 0),
            all_star_count=acc_data.get("all_star_count", 0),
            scoring_titles=acc_data.get("scoring_titles", 0),
            olympic_medals=acc_data.get("olympic_medals", []),
            fiba_accolades=acc_data.get("fiba_accolades", []),
            is_hall_of_fame=acc_data.get("is_hall_of_fame", False),
        )

        # Height & Weight format
        height_cm = player.height_cm or 198.0
        weight_kg = player.weight_kg or 98.0
        height_feet = f"{int(height_cm / 30.48)}' {int((height_cm % 30.48) / 2.54)}\""

        headshot = player.headshot_url or f"https://cdn.nba.com/headshots/nba/latest/1040x760/{player.id}.png"

        return VersusPlayerCard(
            player_id=player.id,
            player_name=player.full_name,
            team_abbreviation=team_abbr,
            team_name=team_name,
            position=player.position or "G/F",
            height=height_feet,
            height_cm=height_cm,
            weight=f"{int(weight_kg * 2.20462)} lbs",
            weight_kg=weight_kg,
            headshot_url=headshot,
            archetype_id=cluster_id,
            archetype_es=archetype_meta.get("name_es", "Anotador Principal"),
            archetype_en=archetype_meta.get("name_en", "Primary Scorer"),
            archetype_color=archetype_meta.get("color", "#F97316"),
            selected_season_id=sel_season_id,
            selected_season_label=sel_label,
            is_best_season=(sel_season_id == best_season_id),
            stats=stats_obj,
            accolades=accolades,
            available_seasons=available_seasons,
        )

    def calculate_matchup(
        self,
        player1_id: int,
        season1_id: Optional[int],
        player2_id: int,
        season2_id: Optional[int],
    ) -> VersusMatchupResponse:
        p1 = self.get_player_card(player1_id, season1_id)
        p2 = self.get_player_card(player2_id, season2_id)

        # 1. Direct Stats Comparisons
        stat_comparisons = self._build_stat_comparisons(p1, p2)

        # 2. Accolades Comparisons
        accolades_comparisons = self._build_accolades_comparisons(p1, p2)

        # 3. 7 Dimensions and 1v1 Simulation
        simulation = self._simulate_1v1_duel(p1, p2)

        return VersusMatchupResponse(
            player1=p1,
            player2=p2,
            stat_comparisons=stat_comparisons,
            accolades_comparisons=accolades_comparisons,
            simulation=simulation,
        )

    def _build_stat_comparisons(
        self, p1: VersusPlayerCard, p2: VersusPlayerCard
    ) -> List[VersusStatComparisonItem]:
        s1 = p1.stats
        s2 = p2.stats

        defs = [
            ("pts_pg", "Puntos por Partido (PPG)", "Points Per Game (PPG)", s1.pts_pg, s2.pts_pg, "float1", True),
            ("reb_pg", "Rebotes por Partido (RPG)", "Rebounds Per Game (RPG)", s1.reb_pg, s2.reb_pg, "float1", True),
            ("ast_pg", "Asistencias por Partido (APG)", "Assists Per Game (APG)", s1.ast_pg, s2.ast_pg, "float1", True),
            ("stl_pg", "Robos por Partido (SPG)", "Steals Per Game (SPG)", s1.stl_pg, s2.stl_pg, "float1", True),
            ("blk_pg", "Tapones por Partido (BPG)", "Blocks Per Game (BPG)", s1.blk_pg, s2.blk_pg, "float1", True),
            ("fg_pct", "% Tiro de Campo (FG%)", "Field Goal % (FG%)", s1.fg_pct * 100, s2.fg_pct * 100, "percent", True),
            ("fg3_pct", "% Triple (3P%)", "3-Point % (3P%)", s1.fg3_pct * 100, s2.fg3_pct * 100, "percent", True),
            ("fg3m_pg", "Triples Anotados (3PM)", "3-Pointers Made (3PM)", s1.fg3m_pg, s2.fg3m_pg, "float1", True),
            ("ft_pct", "% Tiros Libres (FT%)", "Free Throw % (FT%)", s1.ft_pct * 100, s2.ft_pct * 100, "percent", True),
            ("ts_pct", "% Tiro Verdadero (TS%)", "True Shooting % (TS%)", (s1.ts_pct or 0.5) * 100, (s2.ts_pct or 0.5) * 100, "percent", True),
            ("usg_pct", "% Uso de Posesión (USG%)", "Usage Rate % (USG%)", (s1.usg_pct or 0.25) * 100, (s2.usg_pct or 0.25) * 100, "percent", True),
            ("per", "Eficiencia de Jugador (PER)", "Player Efficiency (PER)", s1.per or 15.0, s2.per or 15.0, "float1", True),
            ("bpm", "Box Plus-Minus (BPM)", "Box Plus-Minus (BPM)", s1.bpm or 0.0, s2.bpm or 0.0, "float1", True),
            ("dbpm", "BPM Defensivo (DBPM)", "Defensive BPM (DBPM)", s1.dbpm or 0.0, s2.dbpm or 0.0, "float1", True),
            ("tov_pg", "Pérdidas por Partido (TOV)", "Turnovers Per Game (TOV)", s1.tov_pg, s2.tov_pg, "float1", False),
        ]

        results = []
        for key, l_es, l_en, v1, v2, ftype, higher_better in defs:
            diff = round(v1 - v2, 2)
            if abs(diff) < 0.001:
                leader = 0
            elif higher_better:
                leader = 1 if v1 > v2 else 2
            else:
                leader = 1 if v1 < v2 else 2

            results.append(
                VersusStatComparisonItem(
                    category_key=key,
                    label_es=l_es,
                    label_en=l_en,
                    p1_value=round(v1, 2),
                    p2_value=round(v2, 2),
                    format_type=ftype,
                    higher_is_better=higher_better,
                    leader=leader,
                    diff=diff,
                )
            )
        return results

    def _build_accolades_comparisons(
        self, p1: VersusPlayerCard, p2: VersusPlayerCard
    ) -> List[VersusStatComparisonItem]:
        a1 = p1.accolades
        a2 = p2.accolades

        defs = [
            ("championships", "Anillos NBA (Campeonatos)", "NBA Championships", a1.championships, a2.championships),
            ("mvp_count", "MVP de Temporada Regular", "Regular Season MVPs", a1.mvp_count, a2.mvp_count),
            ("finals_mvp_count", "MVP de las Finales NBA", "Finals MVPs", a1.finals_mvp_count, a2.finals_mvp_count),
            ("dpoy_count", "Jugador Defensivo del Año (DPOY)", "Defensive Player of the Year", a1.dpoy_count, a2.dpoy_count),
            ("scoring_titles", "Títulos de Máximo Anotador", "Scoring Titles", a1.scoring_titles, a2.scoring_titles),
            ("all_nba_count", "Selecciones All-NBA", "All-NBA Teams", a1.all_nba_count, a2.all_nba_count),
            ("all_star_count", "Apariciones All-Star", "All-Star Appearances", a1.all_star_count, a2.all_star_count),
            ("olympic_medals", "Medallas Olímpicas", "Olympic Medals", len(a1.olympic_medals), len(a2.olympic_medals)),
        ]

        results = []
        for key, l_es, l_en, v1, v2 in defs:
            diff = v1 - v2
            leader = 0 if diff == 0 else (1 if diff > 0 else 2)
            results.append(
                VersusStatComparisonItem(
                    category_key=key,
                    label_es=l_es,
                    label_en=l_en,
                    p1_value=float(v1),
                    p2_value=float(v2),
                    format_type="integer",
                    higher_is_better=True,
                    leader=leader,
                    diff=float(diff),
                )
            )
        return results

    def _simulate_1v1_duel(
        self, p1: VersusPlayerCard, p2: VersusPlayerCard
    ) -> VersusSimulationResult:
        s1, s2 = p1.stats, p2.stats
        h1, h2 = p1.height_cm or 198.0, p2.height_cm or 198.0
        w1, w2 = p1.weight_kg or 98.0, p2.weight_kg or 98.0

        # Dimension 1: Anotación y Aislamiento (ISO Scoring)
        def calc_iso(s: VersusPlayerStats) -> float:
            score = (s.pts_pg * 2.2) + ((s.ts_pct or 0.55) * 40) + ((s.usg_pct or 0.28) * 50) + (s.fg_pct * 25)
            return max(50.0, min(99.0, score))

        iso1, iso2 = calc_iso(s1), calc_iso(s2)

        # Dimension 2: Tiro Exterior y Rango (Perimeter Shooting)
        def calc_shooting(s: VersusPlayerStats) -> float:
            score = (s.fg3m_pg * 12.0) + (s.fg3_pct * 70.0) + (s.ft_pct * 25.0) + 20.0
            return max(40.0, min(99.0, score))

        shoot1, shoot2 = calc_shooting(s1), calc_shooting(s2)

        # Dimension 3: Manejo y Cambio de Ritmo (Handles & Creation)
        def calc_handles(s: VersusPlayerStats, h: float) -> float:
            height_bonus = max(0.0, (215.0 - h) * 0.2)
            score = (s.ast_pg * 4.5) + ((s.usg_pct or 0.25) * 45.0) - (s.tov_pg * 2.0) + height_bonus + 30.0
            return max(45.0, min(99.0, score))

        handle1, handle2 = calc_handles(s1, h1), calc_handles(s2, h2)

        # Dimension 4: Defensa Perimetral y Manos Rápidas (Perimeter Defense)
        def calc_perim_def(s: VersusPlayerStats, h: float, acc: VersusAccolades) -> float:
            dpoy_boost = acc.dpoy_count * 4.0
            score = (s.stl_pg * 20.0) + ((s.dbpm or 0.0) * 4.5) + dpoy_boost + 55.0
            return max(45.0, min(99.0, score))

        pdef1, pdef2 = calc_perim_def(s1, h1, p1.accolades), calc_perim_def(s2, h2, p2.accolades)

        # Dimension 5: Defensa Interior y Protección de Aro (Rim Protection)
        def calc_rim_def(s: VersusPlayerStats, h: float, w: float, acc: VersusAccolades) -> float:
            height_factor = max(0.0, (h - 190.0) * 0.8)
            weight_factor = max(0.0, (w - 85.0) * 0.3)
            score = (s.blk_pg * 22.0) + height_factor + weight_factor + ((s.dbpm or 0.0) * 3.0) + (acc.dpoy_count * 5.0) + 35.0
            return max(40.0, min(99.0, score))

        rdef1, rdef2 = calc_rim_def(s1, h1, w1, p1.accolades), calc_rim_def(s2, h2, w2, p2.accolades)

        # Dimension 6: Físico, Potencia y Contacto (Physicality & Size)
        def calc_phys(h: float, w: float, s: VersusPlayerStats) -> float:
            score = ((h - 180.0) * 0.7) + ((w - 75.0) * 0.6) + (s.reb_pg * 2.0) + 30.0
            return max(45.0, min(99.0, score))

        phys1, phys2 = calc_phys(h1, w1, s1), calc_phys(h2, w2, s2)

        # Dimension 7: Rebote y Segundas Oportunidades (Rebounding)
        def calc_reb(s: VersusPlayerStats, h: float) -> float:
            score = (s.reb_pg * 4.5) + (s.oreb_pg * 6.0) + ((h - 190.0) * 0.4) + 30.0
            return max(40.0, min(99.0, score))

        reb1, reb2 = calc_reb(s1, h1), calc_reb(s2, h2)

        dimensions: List[VersusDimensionRating] = [
            VersusDimensionRating(
                key="iso_scoring",
                name_es="Anotación 1v1 & Aislamiento",
                name_en="1v1 ISO Scoring & Creation",
                description_es="Capacidad para generar tiro propio y castigar en situaciones de uno contra uno.",
                description_en="Ability to self-create scoring opportunities in one-on-one isolations.",
                p1_score=round(iso1, 1),
                p2_score=round(iso2, 1),
                advantage_player=1 if iso1 >= iso2 else 2,
            ),
            VersusDimensionRating(
                key="perimeter_shooting",
                name_es="Tiro Exterior & Rango",
                name_en="Perimeter & 3PT Shooting",
                description_es="Eficacia desde el triple y amenaza de tiro con espacio o sobre punteos.",
                description_en="Shooting gravity, 3-point conversion rate, and contested jumper accuracy.",
                p1_score=round(shoot1, 1),
                p2_score=round(shoot2, 1),
                advantage_player=1 if shoot1 >= shoot2 else 2,
            ),
            VersusDimensionRating(
                key="handles_creation",
                name_es="Manejo & Cambio de Ritmo",
                name_en="Handles & Change of Pace",
                description_es="Bote protegiendo el balón, cambio de dirección y primer paso explosivo.",
                description_en="Ball handling dexterity, hesitation moves, and first-step burst.",
                p1_score=round(handle1, 1),
                p2_score=round(handle2, 1),
                advantage_player=1 if handle1 >= handle2 else 2,
            ),
            VersusDimensionRating(
                key="perimeter_defense",
                name_es="Defensa Perimetral & Robo",
                name_en="Perimeter Lock & Steals",
                description_es="Presión al balón, desplazamiento lateral y anticipación en líneas de pase.",
                description_en="On-ball containment, lateral foot speed, and hand speed for poke-aways.",
                p1_score=round(pdef1, 1),
                p2_score=round(pdef2, 1),
                advantage_player=1 if pdef1 >= pdef2 else 2,
            ),
            VersusDimensionRating(
                key="rim_protection",
                name_es="Protección de Pintura & Tapón",
                name_en="Rim Protection & Paint Deterrence",
                description_es="Intimidación cerca del aro, verticalidad y tapones en bandejas o volcadas.",
                description_en="Rim deterrence, vertical contest height, and shot-blocking recovery.",
                p1_score=round(rdef1, 1),
                p2_score=round(rdef2, 1),
                advantage_player=1 if rdef1 >= rdef2 else 2,
            ),
            VersusDimensionRating(
                key="physicality",
                name_es="Físico, Envergadura & Peso",
                name_en="Physicality & Body Dominance",
                description_es="Masa muscular para aguantar contactos en el poste y juego de espaldas.",
                description_en="Body mass, frame leverage, and shoulder-to-shoulder contact endurance.",
                p1_score=round(phys1, 1),
                p2_score=round(phys2, 1),
                advantage_player=1 if phys1 >= phys2 else 2,
            ),
            VersusDimensionRating(
                key="rebounding",
                name_es="Rebote & Posesión Extra",
                name_en="Rebounding & Extra Possessions",
                description_es="Control de tableros para cortar posesiones o generar segundas oportunidades.",
                description_en="Board control to secure defensive stops and generate put-backs.",
                p1_score=round(reb1, 1),
                p2_score=round(reb2, 1),
                advantage_player=1 if reb1 >= reb2 else 2,
            ),
        ]

        weights = [0.30, 0.15, 0.05, 0.15, 0.10, 0.15, 0.10]
        p1_dim_scores = [iso1, shoot1, handle1, pdef1, rdef1, phys1, reb1]
        p2_dim_scores = [iso2, shoot2, handle2, pdef2, rdef2, phys2, reb2]

        total_r1 = sum(w * s for w, s in zip(weights, p1_dim_scores))
        total_r2 = sum(w * s for w, s in zip(weights, p2_dim_scores))

        h_diff = h1 - h2
        if abs(h_diff) >= 8:
            if h_diff > 0:
                post_edge = (h_diff / 10.0) * 1.5
                total_r1 += post_edge
                if shoot2 > 85:
                    total_r2 += (shoot2 - 80) * 0.2
            else:
                post_edge = (abs(h_diff) / 10.0) * 1.5
                total_r2 += post_edge
                if shoot1 > 85:
                    total_r1 += (shoot1 - 80) * 0.2

        diff_r = total_r1 - total_r2
        prob_p1 = 1.0 / (1.0 + math.exp(-diff_r / 6.5))
        prob_p1_pct = round(prob_p1 * 100.0, 1)
        prob_p2_pct = round(100.0 - prob_p1_pct, 1)

        if prob_p1_pct >= 50.0:
            score_p1 = 21
            ratio = prob_p2_pct / max(prob_p1_pct, 1.0)
            score_p2 = max(11, min(20, int(round(21.0 * ratio))))
            winner_id = p1.player_id
            winner_name = p1.player_name
        else:
            score_p2 = 21
            ratio = prob_p1_pct / max(prob_p2_pct, 1.0)
            score_p1 = max(11, min(20, int(round(21.0 * ratio))))
            winner_id = p2.player_id
            winner_name = p2.player_name

        adv_p1: List[str] = []
        adv_p2: List[str] = []

        if iso1 > iso2 + 3:
            adv_p1.append(f"Mayor capacidad de anotación individual y desequilibrio ({s1.pts_pg} PPG vs {s2.pts_pg} PPG)")
        elif iso2 > iso1 + 3:
            adv_p2.append(f"Mayor capacidad de anotación individual y desequilibrio ({s2.pts_pg} PPG vs {s1.pts_pg} PPG)")

        if shoot1 > shoot2 + 5:
            adv_p1.append(f"Superioridad letal en tiro perimetral ({s1.fg3m_pg} triples con {round(s1.fg3_pct*100,1)}%)")
        elif shoot2 > shoot1 + 5:
            adv_p2.append(f"Superioridad letal en tiro perimetral ({s2.fg3m_pg} triples con {round(s2.fg3_pct*100,1)}%)")

        if pdef1 > pdef2 + 4:
            adv_p1.append(f"Manos rápidas y presión asfixiante al bote ({s1.stl_pg} SPG)")
        elif pdef2 > pdef1 + 4:
            adv_p2.append(f"Manos rápidas y presión asfixiante al bote ({s2.stl_pg} SPG)")

        if rdef1 > rdef2 + 5:
            adv_p1.append(f"Intimidación y bloqueo en la pintura ({s1.blk_pg} BPG)")
        elif rdef2 > rdef1 + 5:
            adv_p2.append(f"Intimidación y bloqueo en la pintura ({s2.blk_pg} BPG)")

        if phys1 > phys2 + 5:
            adv_p1.append(f"Ventaja de tonelaje y fortaleza de contacto ({p1.weight_kg} kg vs {p2.weight_kg} kg)")
        elif phys2 > phys1 + 5:
            adv_p2.append(f"Ventaja de tonelaje y fortaleza de contacto ({p2.weight_kg} kg vs {p1.weight_kg} kg)")

        if reb1 > reb2 + 4:
            adv_p1.append(f"Dominio de segundas oportunidades en el rebote ({s1.reb_pg} RPG)")
        elif reb2 > reb1 + 4:
            adv_p2.append(f"Dominio de segundas oportunidades en el rebote ({s2.reb_pg} RPG)")

        if not adv_p1:
            adv_p1.append("Equilibrio táctico y versatilidad bidireccional")
        if not adv_p2:
            adv_p2.append("Equilibrio táctico y versatilidad bidireccional")

        series_winner = winner_name
        if abs(prob_p1_pct - 50.0) < 5.0:
            series_score = "4 - 3"
        elif abs(prob_p1_pct - 50.0) < 15.0:
            series_score = "4 - 2"
        elif abs(prob_p1_pct - 50.0) < 25.0:
            series_score = "4 - 1"
        else:
            series_score = "4 - 0"

        if prob_p1_pct >= 50.0:
            fav, dog = p1, p2
            fav_prob = prob_p1_pct
        else:
            fav, dog = p2, p1
            fav_prob = prob_p2_pct

        summary_es = (
            f"En este enfrentamiento 1 vs 1, el modelo proyecta una victoria para {fav.player_name} ({fav.selected_season_label}) "
            f"con un {fav_prob}% de probabilidad estimada ({score_p1} - {score_p2}). "
            f"La clave radica en su balance ofensivo ({fav.stats.pts_pg} PPG) y su capacidad para imponer condiciones en {fav.archetype_es}. "
            f"{dog.player_name} ({dog.selected_season_label}) ofrece resistencia táctica de élite pero cede terreno en áreas decisivas de posesión y contención individual."
        )

        summary_en = (
            f"In this direct 1v1 matchup, the model projects a victory for {fav.player_name} ({fav.selected_season_label}) "
            f"with an estimated {fav_prob}% win probability ({score_p1} - {score_p2}). "
            f"The deciding edge comes from offensive efficiency ({fav.stats.pts_pg} PPG) and isolation control. "
            f"{dog.player_name} ({dog.selected_season_label}) provides world-class resistance but struggles with positional mismatch and possession retention."
        )

        return VersusSimulationResult(
            p1_win_prob=prob_p1_pct,
            p2_win_prob=prob_p2_pct,
            projected_score_p1=score_p1,
            projected_score_p2=score_p2,
            predicted_winner_id=winner_id,
            predicted_winner_name=winner_name,
            dimensions=dimensions,
            tactical_summary_es=summary_es,
            tactical_summary_en=summary_en,
            key_advantages_p1=adv_p1,
            key_advantages_p2=adv_p2,
            series_best_of_7_winner=series_winner,
            series_score=series_score,
        )
