"""
Closing-line value (CLV) statistics against a sharp reference (Pinnacle de-vigged close).

Evaluates log-odds CLV:
    ln(price_taken / fair_closing_price)

Games are the independent sampling unit: multiple bets on the same game (e.g. flat and Kelly)
are averaged first so a single game is never counted multiple times.
"""
from collections import defaultdict
from dataclasses import dataclass
import math
from typing import Any, Iterable, List, Optional, Union

# Normal distribution critical values:
# z_alpha = 1.645 for one-sided alpha = 0.05
# z_beta = 0.8416 for power = 0.80 (type II error beta = 0.20)
Z_ALPHA_05 = 1.645
Z_BETA_80 = 0.8416


def log_odds_clv(price_taken: float, fair_closing_price: float) -> float:
    """
    Log-odds CLV: ln(price_taken / fair_closing_price).
    Strictly positive prices required.
    """
    if price_taken <= 0 or fair_closing_price <= 0:
        raise ValueError("Prices must be strictly positive")
    return math.log(price_taken / fair_closing_price)


def bets_needed_for(sd: Optional[float], delta: float) -> Optional[float]:
    """
    Sample size of independent games needed to detect a true mean CLV of delta
    with one-sided alpha=0.05 and power=0.80:
        n = ((z_alpha + z_beta) * sd / delta) ^ 2
    Returns None if sd is missing, delta <= 0, or calculation cannot be performed.
    """
    if sd is None or delta <= 0 or math.isnan(sd):
        return None
    return float(((Z_ALPHA_05 + Z_BETA_80) * sd / delta) ** 2)


@dataclass
class BetClvRecord:
    game_id: Union[int, str]
    price_taken: float
    fair_closing_price: float

    @property
    def log_clv(self) -> float:
        return log_odds_clv(self.price_taken, self.fair_closing_price)


@dataclass
class ClvStats:
    n_games: int
    mean_clv: Optional[float] = None
    std_dev: Optional[float] = None
    std_err: Optional[float] = None
    t_stat: Optional[float] = None

    def bets_needed_for(self, delta: float) -> Optional[float]:
        return bets_needed_for(self.std_dev, delta)


def compute_clv_stats(records: Iterable[Any]) -> ClvStats:
    """
    Compute CLV statistics clustered by game.
    Averages duplicate bets on the same game first.
    Accepts BetClvRecord instances or objects with game_id, price_taken, fair_closing_price.
    Gracefully handles n < 2 (returns None values, never NaN or exceptions).
    """
    by_game: defaultdict[Union[int, str], List[float]] = defaultdict(list)
    for r in records:
        game_id = getattr(r, "game_id", None) if not isinstance(r, dict) else r.get("game_id")
        price = getattr(r, "price_taken", None) if not isinstance(r, dict) else r.get("price_taken")
        fair = getattr(r, "fair_closing_price", None) if not isinstance(r, dict) else r.get("fair_closing_price")
        if game_id is None or price is None or fair is None:
            continue
        try:
            val = log_odds_clv(float(price), float(fair))
            by_game[game_id].append(val)
        except (ValueError, TypeError, ZeroDivisionError):
            continue

    if not by_game:
        return ClvStats(n_games=0)

    # Average duplicate bets of the same game
    game_clvs = [sum(clvs) / len(clvs) for clvs in by_game.values()]
    n = len(game_clvs)

    mean_val = sum(game_clvs) / n
    if n < 2:
        return ClvStats(n_games=n, mean_clv=mean_val)

    variance = sum((x - mean_val) ** 2 for x in game_clvs) / (n - 1)
    sd_val = math.sqrt(variance)
    se_val = sd_val / math.sqrt(n)
    t_val = (mean_val / se_val) if se_val > 0 else None

    return ClvStats(
        n_games=n,
        mean_clv=mean_val,
        std_dev=sd_val,
        std_err=se_val,
        t_stat=t_val,
    )
