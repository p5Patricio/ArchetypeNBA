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
