"""A synthetic NBA-like league for model tests: teams with known strengths, a home edge and noise."""
import random
from datetime import date, timedelta
from typing import Dict, List, Optional

from app.services.elo_service import HistoricalGame


def make_league(
    n_seasons: int = 8,
    n_teams: int = 10,
    seed: int = 0,
    home_edge: float = 3.0,
    noise: float = 11.0,
    strength_sd: float = 4.0,
    rounds: Optional[int] = None,
    first_year: int = 2000,
) -> List[HistoricalGame]:
    """
    Chronological games of ``n_seasons`` seasons (season ids 1..n). Each round every team plays once (random
    pairing, first of a pair at home); a day passes between rounds, sometimes two. Margin = strength gap + home
    edge + noise, so the true win probability is known and a good model can approach it.
    """
    rng = random.Random(seed)
    rounds = rounds if rounds is not None else 4 * (n_teams - 1)
    strength: Dict[int, float] = {team: rng.gauss(0.0, strength_sd) for team in range(1, n_teams + 1)}
    games: List[HistoricalGame] = []
    for season in range(1, n_seasons + 1):
        day = date(first_year + season, 10, 20)
        for team in strength:
            strength[team] = 0.8 * strength[team] + rng.gauss(0.0, 0.6 * strength_sd)
        sequence = 0
        for _ in range(rounds):
            order = list(strength)
            rng.shuffle(order)
            for home, away in zip(order[0::2], order[1::2]):
                margin = round(strength[home] - strength[away] + home_edge + rng.gauss(0.0, noise))
                margin = margin or 1
                home_pts = 100 + max(margin, 0) + rng.randint(0, 8)
                away_pts = home_pts - margin
                sequence += 1
                games.append(
                    HistoricalGame(
                        game_id=f"002{season:02d}{sequence:05d}",
                        game_date=day,
                        season_id=season,
                        home_team_id=home,
                        away_team_id=away,
                        home_pts=home_pts,
                        away_pts=away_pts,
                    )
                )
            day += timedelta(days=rng.choice((1, 1, 2)))
    games.sort(key=lambda g: g.sort_key)
    return games


def insert_league(session, games: List[HistoricalGame]) -> List[HistoricalGame]:
    """
    Store a synthetic league as player_game_log rows (2 players per team, points split between them) with real
    team abbreviations, and return the games re-keyed to the database ids (what ``load_games`` will yield).
    """
    from dataclasses import replace

    from app.models import Player, PlayerGameLog, Season, Team
    from app.services.elo_service import CURRENT_TEAMS

    team_ids = sorted({g.home_team_id for g in games} | {g.away_team_id for g in games})
    abbreviations = sorted(CURRENT_TEAMS)[: len(team_ids)]
    teams: Dict[int, Team] = {}
    players: Dict[int, List[Player]] = {}
    for team_id, abbr in zip(team_ids, abbreviations):
        teams[team_id] = Team(abbreviation=abbr, full_name=abbr, city=abbr, conference="E", division="X")
        session.add(teams[team_id])
        players[team_id] = [Player(full_name=f"{abbr} player {n}") for n in (1, 2)]
        session.add_all(players[team_id])
    seasons: Dict[int, Season] = {}
    for season_id in sorted({g.season_id for g in games}):
        seasons[season_id] = Season(season_label=f"{2000 + season_id}-{str(season_id + 1).zfill(2)[-2:]}")
        session.add(seasons[season_id])
    session.flush()

    rekeyed = []
    for game in games:
        home, away = teams[game.home_team_id], teams[game.away_team_id]
        season = seasons[game.season_id]
        for team, opponent, pts, matchup in (
            (home, away, game.home_pts, f"{home.abbreviation} vs. {away.abbreviation}"),
            (away, home, game.away_pts, f"{away.abbreviation} @ {home.abbreviation}"),
        ):
            for n, share in ((0, pts // 2), (1, pts - pts // 2)):
                session.add(
                    PlayerGameLog(
                        player_id=players[game.home_team_id if team is home else game.away_team_id][n].id,
                        team_id=team.id,
                        season_id=season.id,
                        game_id=game.game_id,
                        game_date=game.game_date,
                        matchup=matchup,
                        pts=share,
                    )
                )
        rekeyed.append(replace(game, season_id=season.id, home_team_id=home.id, away_team_id=away.id))
    session.commit()
    return rekeyed
