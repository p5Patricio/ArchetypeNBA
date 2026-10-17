import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np
from scipy.stats import nbinom
from pydantic import BaseModel

logger = logging.getLogger(__name__)


def normalize_player_key(name: str) -> str:
    """
    Matching key for player names across systems: no diacritics, lower case, no punctuation,
    single spaces ("Luka Dončić" -> "luka doncic", "P.J. Washington Jr." -> "pj washington jr").
    """
    stripped = "".join(c for c in unicodedata.normalize("NFKD", name or "") if not unicodedata.combining(c))
    cleaned = re.sub(r"[^a-z0-9\s]", "", stripped.lower().replace("-", " "))
    return " ".join(cleaned.split())


def index_props_by_player(props_map: Dict[str, Dict[str, "PropBetLine"]]) -> Dict[str, Dict[str, "PropBetLine"]]:
    """Re-keys a {player name: {stat: line}} map by normalize_player_key so lookups ignore accents."""
    indexed: Dict[str, Dict[str, "PropBetLine"]] = {}
    for name, stats in props_map.items():
        indexed.setdefault(normalize_player_key(name), {}).update(stats)
    return indexed


def american_to_decimal(american_odds: int) -> float:
    """Converts American odds (-110, +130) to decimal odds (1.909, 2.30)."""
    if american_odds > 0:
        return round((american_odds / 100.0) + 1.0, 3)
    elif american_odds < 0:
        return round((100.0 / abs(american_odds)) + 1.0, 3)
    return 1.0


def decimal_to_implied_prob(decimal_odds: float) -> float:
    """Calculates implied probability from decimal odds."""
    if decimal_odds <= 0:
        return 0.0
    return round(1.0 / decimal_odds, 4)


def devig_two_way(over_decimal: float, under_decimal: float) -> tuple[float, float]:
    """
    Removes the bookmaker margin from a two-way market (proportional / multiplicative method).
    p_i = (1 / d_i) / sum(1 / d). Returns (fair_over_prob, fair_under_prob), which sum to 1.
    """
    inv_over = 1.0 / over_decimal
    inv_under = 1.0 / under_decimal
    total = inv_over + inv_under
    return inv_over / total, inv_under / total


@dataclass
class PlayerBaseline:
    player_id: int
    name: str
    team: str
    avg_minutes: float
    pts_per_min: float
    reb_per_min: float
    ast_per_min: float
    overdispersion_alpha: float = 0.12  # Overdispersion parameter for Negative Binomial


class PropBetLine(BaseModel):
    stat_type: str  # 'PTS', 'REB', 'AST', 'PRA'
    line: float
    over_odds: int  # always an actual quoted price; no default is ever assumed
    under_odds: Optional[int] = None  # None = no under price was quoted; never assume one
    bookmaker: Optional[str] = None  # key of the book that offered this quote, when known


class PropSimulationResult(BaseModel):
    player_name: str
    team: str
    stat_type: str
    sportsbook_line: float
    over_odds: int
    projected_mean: float
    projected_median: float
    projected_p10: float
    projected_p90: float
    prob_over: float
    prob_under: float
    book_implied_prob: float  # for the evaluated `side`: no-vig fair prob when devigged, else vigged implied
    edge_pct: float  # model prob minus book_implied_prob for `side`
    expected_value_pct: float  # EV of `side` at that side's actual price
    kelly_stake_pct: float  # quarter Kelly for `side`
    recommendation: str  # 'STRONG OVER', 'LEAN OVER', 'PASS', 'LEAN UNDER', 'STRONG UNDER'
    risk_level: str
    reasoning: str
    # Added fields (defaults keep existing consumers working)
    side: str = "over"  # side the edge/EV/Kelly fields refer to: 'over' or 'under'
    under_odds: Optional[int] = None
    fair_prob: Optional[float] = None  # no-vig probability of `side`; None when only one side was quoted
    devigged: bool = False  # True when both sides were quoted and the margin was removed
    bookmaker: Optional[str] = None
    prob_push: float = 0.0  # P(stat == line) on integer lines (stake refunded); 0 on half-point lines


class PropsEngine:
    """
    Mathematical modeling engine for NBA player props.
    Combines Negative Binomial count distributions with Monte Carlo simulations (10,000 runs).
    """

    def __init__(self, simulation_runs: int = 10000):
        self.simulation_runs = simulation_runs

    def evaluate_prop(
        self,
        player: PlayerBaseline,
        prop: PropBetLine,
        minute_multiplier: float = 1.0,
        usage_multiplier: float = 1.0,
        defense_multiplier: float = 1.0,
        risk_level: str = "LOW",
        tactical_summary: str = "",
    ) -> PropSimulationResult:
        """
        Calculates exact mathematical probabilities and simulates outcomes for a player prop.
        """
        # 1. Project adjusted minutes
        projected_minutes = max(0.0, player.avg_minutes * minute_multiplier)

        # 2. Project per-minute rate based on stat type
        if prop.stat_type == "PTS":
            base_rate = player.pts_per_min
        elif prop.stat_type == "REB":
            base_rate = player.reb_per_min
        elif prop.stat_type == "AST":
            base_rate = player.ast_per_min
        elif prop.stat_type == "PRA":
            base_rate = player.pts_per_min + player.reb_per_min + player.ast_per_min
        else:
            base_rate = player.pts_per_min

        # Adjusted rate incorporating usage boost and opponent defense
        adjusted_rate = base_rate * usage_multiplier * defense_multiplier
        projected_mean = projected_minutes * adjusted_rate

        # If projected mean is practically zero (e.g. OUT)
        if projected_mean <= 0.1:
            return PropSimulationResult(
                player_name=player.name,
                team=player.team,
                stat_type=prop.stat_type,
                sportsbook_line=prop.line,
                over_odds=prop.over_odds,
                projected_mean=0.0,
                projected_median=0.0,
                projected_p10=0.0,
                projected_p90=0.0,
                prob_over=0.0,
                prob_under=1.0,
                book_implied_prob=decimal_to_implied_prob(american_to_decimal(prop.over_odds)),
                edge_pct=-1.0,
                expected_value_pct=-1.0,
                kelly_stake_pct=0.0,
                recommendation="PASS (INACTIVE / 0 MIN)",
                risk_level="EXTREME",
                reasoning=tactical_summary or "Player confirmed OUT or zero minutes projected.",
                under_odds=prop.under_odds,
                bookmaker=prop.bookmaker,
            )

        # 3. Parameterize Negative Binomial distribution
        # Variance = mean + alpha * mean^2
        # r (number of failures) = 1 / alpha
        # p (success probability) = 1 / (1 + alpha * mean)
        alpha = max(0.02, player.overdispersion_alpha)
        r_param = 1.0 / alpha
        p_param = 1.0 / (1.0 + alpha * projected_mean)

        # Exact CDF calculation: P(X > line) = 1 - CDF(floor(line)).
        # On an integer line, X == line is a push (stake refunded): it is neither an over nor an under win.
        # Half-point lines cannot push, so p_push is 0 and the numbers are unchanged.
        k = int(np.floor(prop.line))
        cdf_k = float(nbinom.cdf(k, r_param, p_param))
        p_push = float(nbinom.pmf(k, r_param, p_param)) if prop.line == k else 0.0
        prob_over_exact = round(1.0 - cdf_k, 4)
        prob_under_exact = round(cdf_k - p_push, 4)
        prob_push = round(p_push, 4)

        # 4. Monte Carlo Simulation for robust empirical percentiles
        simulated_samples = nbinom.rvs(r_param, p_param, size=self.simulation_runs)
        sim_median = float(np.median(simulated_samples))
        sim_p10 = float(np.percentile(simulated_samples, 10))
        sim_p90 = float(np.percentile(simulated_samples, 90))

        # 5. Financial & Edge Analysis
        dec_over = american_to_decimal(prop.over_odds)
        devigged = prop.under_odds is not None

        if devigged:
            dec_under = american_to_decimal(prop.under_odds)
            fair_over, fair_under = devig_two_way(dec_over, dec_under)
            # Edge is measured against the no-vig probability; EV uses each side's actual price.
            evaluated = {
                "over": (prob_over_exact, dec_over, fair_over),
                "under": (prob_under_exact, dec_under, fair_under),
            }
        else:
            # Only the over was quoted: compare against the vigged implied probability (conservative).
            evaluated = {"over": (prob_over_exact, dec_over, decimal_to_implied_prob(dec_over))}

        def side_metrics(side: str) -> tuple[float, float]:
            p_win, dec, book_prob = evaluated[side]
            # Book prices (and their no-vig probabilities) describe a win conditional on no push, so the
            # model's win probability is conditioned the same way before comparing. No-op when p_push == 0.
            p_win_given_no_push = p_win / (1.0 - p_push) if p_push < 1.0 else p_win
            # EV = p_win*(d-1) - p_lose, with p_lose = 1 - p_win - p_push (a push refunds the stake).
            # Equivalent to p_win*d - 1 + p_push, which is the pre-push formula when p_push == 0.
            ev_side = (p_win * dec) - 1.0 + p_push
            return round(p_win_given_no_push - book_prob, 4), round(ev_side, 4)

        # Choose the side with the higher EV; ties go to the over (deterministic).
        side = max(evaluated, key=lambda sd: (side_metrics(sd)[1], sd == "over"))
        p_model, dec_side, book_prob = evaluated[side]
        edge, ev = side_metrics(side)

        # Fractional Kelly Criterion (Quarter-Kelly for bankroll preservation), sized for the chosen side.
        # f* = (b*p_win - p_lose) / b with p_lose = 1 - p_win - p_push. Pushes are not renormalized away:
        # the exact log-growth maximizer divides this by (1 - p_push), so skipping that is slightly more
        # conservative, which suits quarter-Kelly. It equals the usual formula when p_push == 0.
        b = dec_side - 1.0
        p_lose = 1.0 - p_model - p_push
        full_kelly = max(0.0, (b * p_model - p_lose) / b) if b > 0 else 0.0
        quarter_kelly = round(full_kelly * 0.25, 4)

        # Recommendation categorization (symmetric for both sides)
        if edge >= 0.07 and ev > 0.08:
            recommendation = f"STRONG {side.upper()}"
        elif edge >= 0.03 and ev > 0.03:
            recommendation = f"LEAN {side.upper()}"
        else:
            recommendation = "PASS"

        return PropSimulationResult(
            player_name=player.name,
            team=player.team,
            stat_type=prop.stat_type,
            sportsbook_line=prop.line,
            over_odds=prop.over_odds,
            projected_mean=round(projected_mean, 1),
            projected_median=round(sim_median, 1),
            projected_p10=round(sim_p10, 1),
            projected_p90=round(sim_p90, 1),
            prob_over=prob_over_exact,
            prob_under=prob_under_exact,
            book_implied_prob=round(book_prob, 4),
            edge_pct=round(edge * 100.0, 1),
            expected_value_pct=round(ev * 100.0, 1),
            kelly_stake_pct=round(quarter_kelly * 100.0, 1),
            recommendation=recommendation,
            risk_level=risk_level,
            reasoning=tactical_summary,
            side=side,
            under_odds=prop.under_odds,
            fair_prob=round(book_prob, 4) if devigged else None,
            devigged=devigged,
            bookmaker=prop.bookmaker,
            prob_push=prob_push,
        )

    def get_standard_star_baselines(self) -> List[PlayerBaseline]:
        """Provides verified baseline profiles for key active NBA players."""
        return [
            PlayerBaseline(
                player_id=1629029,
                name="Luka Doncic",
                team="Dallas Mavericks",
                avg_minutes=36.2,
                pts_per_min=0.94,
                reb_per_min=0.25,
                ast_per_min=0.27,
                overdispersion_alpha=0.10,
            ),
            PlayerBaseline(
                player_id=203999,
                name="Nikola Jokic",
                team="Denver Nuggets",
                avg_minutes=34.6,
                pts_per_min=0.76,
                reb_per_min=0.36,
                ast_per_min=0.26,
                overdispersion_alpha=0.08,
            ),
            PlayerBaseline(
                player_id=203507,
                name="Giannis Antetokounmpo",
                team="Milwaukee Bucks",
                avg_minutes=35.1,
                pts_per_min=0.87,
                reb_per_min=0.33,
                ast_per_min=0.18,
                overdispersion_alpha=0.11,
            ),
            PlayerBaseline(
                player_id=2544,
                name="LeBron James",
                team="Los Angeles Lakers",
                avg_minutes=35.0,
                pts_per_min=0.73,
                reb_per_min=0.21,
                ast_per_min=0.24,
                overdispersion_alpha=0.09,
            ),
            PlayerBaseline(
                player_id=203076,
                name="Anthony Davis",
                team="Los Angeles Lakers",
                avg_minutes=35.5,
                pts_per_min=0.69,
                reb_per_min=0.35,
                ast_per_min=0.10,
                overdispersion_alpha=0.12,
            ),
            PlayerBaseline(
                player_id=202681,
                name="Kyrie Irving",
                team="Dallas Mavericks",
                avg_minutes=35.0,
                pts_per_min=0.72,
                reb_per_min=0.14,
                ast_per_min=0.15,
                overdispersion_alpha=0.13,
            ),
            PlayerBaseline(
                player_id=201939,
                name="Stephen Curry",
                team="Golden State Warriors",
                avg_minutes=32.7,
                pts_per_min=0.81,
                reb_per_min=0.14,
                ast_per_min=0.16,
                overdispersion_alpha=0.14,
            ),
            PlayerBaseline(
                player_id=1628369,
                name="Jayson Tatum",
                team="Boston Celtics",
                avg_minutes=35.8,
                pts_per_min=0.75,
                reb_per_min=0.23,
                ast_per_min=0.14,
                overdispersion_alpha=0.10,
            ),
        ]

    @staticmethod
    def normalize_name(name: str) -> str:
        """Removes diacritics / accents for seamless cross-system matching (e.g. Dončić -> Doncic)."""
        import unicodedata
        return "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))

    def load_baselines_from_db(
        self,
        db_path=None,
        min_minutes: float = 200.0,
        season_weights: Optional[Dict[int, float]] = None,
    ) -> List[PlayerBaseline]:
        """
        Dynamically loads player baselines from SQLite multi-season data.
        1. Identifies the player's CURRENT team from their latest recorded season.
        2. Computes recency-weighted multi-season production rates (PTS/min, REB/min, AST/min).
        """
        import sqlite3
        from pathlib import Path

        if db_path is None:
            db_path = Path(__file__).resolve().parent.parent.parent / "nba_platform.db"
        else:
            db_path = Path(db_path)

        if not db_path.exists():
            logger.warning(f"PropsEngine: Database {db_path} not found. Falling back to static stars.")
            return self.get_standard_star_baselines()

        if season_weights is None:
            # 50% for 2025-26 (id=3), 30% for 2024-25 (id=2), 20% for 2023-24 (id=1)
            season_weights = {3: 0.50, 2: 0.30, 1: 0.20}

        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()

            query = """
            SELECT ps.player_id, p.full_name, t.full_name, t.abbreviation,
                   ps.season_id, ps.gp, ps.min, ps.pts, ps.reb, ps.ast
            FROM player_season_stats ps
            JOIN player p ON ps.player_id = p.id
            JOIN team t ON ps.team_id = t.id
            WHERE t.abbreviation != 'TOT'
            ORDER BY ps.player_id, ps.season_id ASC
            """
            rows = cur.execute(query).fetchall()
            conn.close()

            player_records: Dict[int, Dict] = {}
            for r in rows:
                p_id, full_name, team_full, team_abbr, s_id, gp, minutes, pts, reb, ast = r
                norm_name = self.normalize_name(full_name)

                if p_id not in player_records:
                    player_records[p_id] = {
                        "name": norm_name,
                        "latest_season": s_id,
                        "current_team": team_full,
                        "current_team_abbr": team_abbr,
                        "seasons": [],
                    }

                if s_id >= player_records[p_id]["latest_season"]:
                    player_records[p_id]["latest_season"] = s_id
                    player_records[p_id]["current_team"] = team_full
                    player_records[p_id]["current_team_abbr"] = team_abbr

                player_records[p_id]["seasons"].append({
                    "season_id": s_id,
                    "gp": gp or 0,
                    "min": minutes or 0.0,
                    "pts": pts or 0.0,
                    "reb": reb or 0.0,
                    "ast": ast or 0.0,
                })

            baselines: List[PlayerBaseline] = []
            for p_id, data in player_records.items():
                total_weighted_mins = 0.0
                total_weighted_pts = 0.0
                total_weighted_reb = 0.0
                total_weighted_ast = 0.0
                total_raw_mins = 0.0
                total_raw_gp = 0

                for s in data["seasons"]:
                    w = season_weights.get(s["season_id"], 0.20)
                    m = s["min"]
                    total_raw_mins += m
                    total_raw_gp += s["gp"]
                    total_weighted_mins += m * w
                    total_weighted_pts += s["pts"] * w
                    total_weighted_reb += s["reb"] * w
                    total_weighted_ast += s["ast"] * w

                if total_raw_mins < min_minutes or total_weighted_mins <= 0:
                    continue

                avg_min = total_raw_mins / max(1, total_raw_gp)
                pts_pm = total_weighted_pts / total_weighted_mins
                reb_pm = total_weighted_reb / total_weighted_mins
                ast_pm = total_weighted_ast / total_weighted_mins

                baselines.append(
                    PlayerBaseline(
                        player_id=p_id,
                        name=data["name"],
                        team=data["current_team"],
                        avg_minutes=round(avg_min, 1),
                        pts_per_min=round(pts_pm, 3),
                        reb_per_min=round(reb_pm, 3),
                        ast_per_min=round(ast_pm, 3),
                        overdispersion_alpha=0.10,
                    )
                )

            logger.info(f"PropsEngine: Loaded {len(baselines)} multi-season player baselines from DB.")
            return baselines

        except Exception as e:
            logger.error(f"PropsEngine: Error loading from database: {e}. Falling back to default stars.")
            return self.get_standard_star_baselines()
