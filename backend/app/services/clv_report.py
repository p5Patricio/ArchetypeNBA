"""
Pinnacle-referenced closing-line value (CLV) report.

For every paper bet on a game with a `closing` capture marker, evaluates CLV against
Pinnacle's two-way de-vigged closing price:
  - h2h: Pinnacle's de-vigged closing price of the same side.
  - spreads: only when Pinnacle's closing line equals the bet's line_taken (otherwise
    excluded as line moved).
  - totals: only when Pinnacle's closing line equals the bet's line_taken (otherwise
    excluded as line moved).

Games are the independent sampling unit: multiple bets on the same game (e.g. flat and Kelly)
are averaged first.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import math
from typing import Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import select
from sqlmodel import Session

from app.analytics.clv_stats import BetClvRecord, ClvStats, compute_clv_stats
from app.analytics.props_engine import american_to_decimal, devig_two_way
from app.models import (
    CAPTURE_CLOSING,
    BetSide,
    Game,
    MarketType,
    ModelPrediction,
    OddsHistory,
    OddsSnapshotCapture,
    SimulatedBet,
    Sportsbook,
)
from app.services import market_close

_LINE = Decimal("0.1")


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _dec(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _line(value) -> Optional[Decimal]:
    return None if value is None else _dec(value).quantize(_LINE)


def _recency(quote: OddsHistory) -> Tuple[datetime, datetime, int]:
    return (_aware_utc(quote.captured_at), _aware_utc(quote.book_last_update), quote.id)


@dataclass
class GamePinnacleClvRow:
    game_id: int
    commence_time: datetime
    bets_count: int
    mean_price_taken: float
    fair_closing_price: float
    fair_closing_prob: float
    log_clv: float


@dataclass
class PinnacleClvExclusions:
    no_closing_marker: int = 0
    no_pinnacle_quote: int = 0
    line_moved: int = 0
    one_sided_quote: int = 0
    closing_before_bet: int = 0
    unsupported_market: int = 0

    @property
    def total(self) -> int:
        return (
            self.no_closing_marker
            + self.no_pinnacle_quote
            + self.line_moved
            + self.one_sided_quote
            + self.closing_before_bet
            + self.unsupported_market
        )


@dataclass
class PinnacleClvReport:
    total_bets: int = 0
    games_count: int = 0
    stats: ClvStats = field(default_factory=lambda: ClvStats(n_games=0))
    exclusions: PinnacleClvExclusions = field(default_factory=PinnacleClvExclusions)
    same_book_avg_clv: Optional[float] = None
    same_book_clv_bets: int = 0
    game_rows: List[GamePinnacleClvRow] = field(default_factory=list)


def build_pinnacle_clv_report(
    session: Session, now: Optional[datetime] = None
) -> PinnacleClvReport:
    """
    Builds the Pinnacle-referenced CLV report for all paper bets.
    Reuses existing sharp book lookup and devigging helpers.
    """
    now = _aware_utc(now) if now is not None else datetime.now(timezone.utc)
    report = PinnacleClvReport()

    # Sharp books (Pinnacle)
    book_keys = market_close.sharp_books(session)
    if not book_keys:
        pinnacle_rows = session.execute(
            select(Sportsbook.id, Sportsbook.key).where(Sportsbook.key == "pinnacle")
        ).all()
        book_keys = {bid: k for bid, k in pinnacle_rows}

    # Games with closing capture marker
    markers: Dict[int, datetime] = {}
    for game_id, captured_at in session.execute(
        select(OddsSnapshotCapture.game_id, OddsSnapshotCapture.captured_at).where(
            OddsSnapshotCapture.kind == CAPTURE_CLOSING
        )
    ).all():
        if captured_at is not None:
            markers[game_id] = _aware_utc(captured_at)

    # Load all simulated bets with predictions and game info
    rows = session.execute(
        select(
            SimulatedBet,
            ModelPrediction.game_id,
            ModelPrediction.market,
            ModelPrediction.side,
            ModelPrediction.player_id,
            Game.commence_time,
        )
        .join(ModelPrediction, ModelPrediction.id == SimulatedBet.prediction_id)
        .join(Game, Game.id == ModelPrediction.game_id)
        .order_by(SimulatedBet.id)
    ).all()

    report.total_bets = len(rows)
    if not rows:
        return report

    # Same-book CLV comparison
    same_book_clvs = [float(b.clv_pct) for b, *_ in rows if b.clv_pct is not None]
    if same_book_clvs:
        report.same_book_clv_bets = len(same_book_clvs)
        report.same_book_avg_clv = sum(same_book_clvs) / len(same_book_clvs)

    # Load sharp quotes for relevant games
    game_ids = list({row[1] for row in rows})
    quotes_by_game = _load_pinnacle_quotes(session, game_ids, list(book_keys.keys()))

    valid_records: List[BetClvRecord] = []
    # For per-game rows tracking: game_id -> list of (price_taken, fair_price, fair_prob, log_clv, commence)
    game_bet_details: Dict[int, List[Tuple[float, float, float, float, datetime]]] = defaultdict(list)

    for bet, game_id, market, side, player_id, commence_time in rows:
        # Check closing marker
        closed_at = markers.get(game_id)
        if closed_at is None:
            report.exclusions.no_closing_marker += 1
            continue

        # Check market support (h2h, spreads and totals)
        m_str = _enum_value(market)
        if m_str not in (MarketType.h2h.value, MarketType.spreads.value, MarketType.totals.value):
            report.exclusions.unsupported_market += 1
            continue

        # Check placed_at vs closed_at
        if bet.placed_at is None or closed_at <= _aware_utc(bet.placed_at):
            report.exclusions.closing_before_bet += 1
            continue

        commence = _aware_utc(commence_time)
        game_quotes = quotes_by_game.get(game_id, [])
        # Only quotes captured at or before tip-off
        pre_tipoff = [q for q in game_quotes if _aware_utc(q.captured_at) <= commence]

        if not pre_tipoff:
            report.exclusions.no_pinnacle_quote += 1
            continue

        if m_str == MarketType.h2h.value:
            fair_result = _devig_h2h(pre_tipoff, side)
            if fair_result is None:
                # Distinguish no quote vs one sided
                has_side = any(_enum_value(q.side) == _enum_value(side) for q in pre_tipoff)
                if has_side:
                    report.exclusions.one_sided_quote += 1
                else:
                    report.exclusions.no_pinnacle_quote += 1
                continue
            fair_prob, fair_price = fair_result
            rec = BetClvRecord(game_id=game_id, price_taken=float(bet.price_taken), fair_closing_price=fair_price)
            valid_records.append(rec)
            game_bet_details[game_id].append(
                (float(bet.price_taken), fair_price, fair_prob, rec.log_clv, commence)
            )

        elif m_str == MarketType.spreads.value:
            taken_line = _line(bet.line_taken)
            fair_result, reason = _devig_spread(pre_tipoff, side, taken_line)
            if fair_result is None:
                if reason == "line_moved":
                    report.exclusions.line_moved += 1
                elif reason == "one_sided":
                    report.exclusions.one_sided_quote += 1
                else:
                    report.exclusions.no_pinnacle_quote += 1
                continue
            fair_prob, fair_price = fair_result
            rec = BetClvRecord(game_id=game_id, price_taken=float(bet.price_taken), fair_closing_price=fair_price)
            valid_records.append(rec)
            game_bet_details[game_id].append(
                (float(bet.price_taken), fair_price, fair_prob, rec.log_clv, commence)
            )

        elif m_str == MarketType.totals.value:
            taken_line = _line(bet.line_taken)
            fair_result, reason = _devig_totals(pre_tipoff, side, taken_line)
            if fair_result is None:
                if reason == "line_moved":
                    report.exclusions.line_moved += 1
                elif reason == "one_sided":
                    report.exclusions.one_sided_quote += 1
                else:
                    report.exclusions.no_pinnacle_quote += 1
                continue
            fair_prob, fair_price = fair_result
            rec = BetClvRecord(game_id=game_id, price_taken=float(bet.price_taken), fair_closing_price=fair_price)
            valid_records.append(rec)
            game_bet_details[game_id].append(
                (float(bet.price_taken), fair_price, fair_prob, rec.log_clv, commence)
            )

    report.stats = compute_clv_stats(valid_records)
    report.games_count = report.stats.n_games

    # Per-game rows
    for g_id, details in sorted(game_bet_details.items(), key=lambda item: item[1][0][4]):
        b_count = len(details)
        mean_pt = sum(d[0] for d in details) / b_count
        f_price = details[0][1]
        f_prob = details[0][2]
        mean_log_clv = sum(d[3] for d in details) / b_count
        report.game_rows.append(
            GamePinnacleClvRow(
                game_id=g_id,
                commence_time=details[0][4],
                bets_count=b_count,
                mean_price_taken=mean_pt,
                fair_closing_price=f_price,
                fair_closing_prob=f_prob,
                log_clv=mean_log_clv,
            )
        )

    return report


def _load_pinnacle_quotes(
    session: Session, game_ids: List[int], sharp_book_ids: List[int]
) -> Dict[int, List[OddsHistory]]:
    if not game_ids or not sharp_book_ids:
        return {}
    grouped: Dict[int, List[OddsHistory]] = defaultdict(list)
    chunk = 500
    for start in range(0, len(game_ids), chunk):
        batch = game_ids[start : start + chunk]
        stmt = (
            select(OddsHistory)
            .where(
                OddsHistory.game_id.in_(batch),
                OddsHistory.sportsbook_id.in_(sharp_book_ids),
                OddsHistory.player_id.is_(None),
            )
            .order_by(OddsHistory.captured_at.asc(), OddsHistory.id.asc())
        )
        for row in session.execute(stmt).scalars():
            if row.captured_at is not None:
                grouped[row.game_id].append(row)
    return grouped


def _devig_h2h(quotes: List[OddsHistory], bet_side) -> Optional[Tuple[float, float]]:
    """
    Finds latest h2h home and away quotes and devigs them.
    Returns (fair_prob_of_bet_side, fair_closing_price_of_bet_side).
    """
    h2h_quotes = [q for q in quotes if _enum_value(q.market) == MarketType.h2h.value]
    if not h2h_quotes:
        return None

    home_quotes = [q for q in h2h_quotes if _enum_value(q.side) == BetSide.home.value]
    away_quotes = [q for q in h2h_quotes if _enum_value(q.side) == BetSide.away.value]
    if not home_quotes or not away_quotes:
        return None

    latest_home = max(home_quotes, key=_recency)
    latest_away = max(away_quotes, key=_recency)

    d_home = american_to_decimal(latest_home.price_american)
    d_away = american_to_decimal(latest_away.price_american)
    p_home, p_away = devig_two_way(d_home, d_away)

    is_home = _enum_value(bet_side) == BetSide.home.value
    fair_prob = p_home if is_home else p_away
    fair_price = 1.0 / fair_prob
    return fair_prob, fair_price


def _devig_spread(
    quotes: List[OddsHistory], bet_side, taken_line: Optional[Decimal]
) -> Tuple[Optional[Tuple[float, float]], str]:
    """
    Finds latest spread quote for bet_side.
    Only proceeds if Pinnacle's closing line == taken_line.
    Returns ((fair_prob, fair_price), status_reason).
    """
    if taken_line is None:
        return None, "invalid_line"

    spread_quotes = [q for q in quotes if _enum_value(q.market) == MarketType.spreads.value]
    if not spread_quotes:
        return None, "no_quote"

    own_quotes = [q for q in spread_quotes if _enum_value(q.side) == _enum_value(bet_side)]
    if not own_quotes:
        return None, "no_quote"

    latest_own = max(own_quotes, key=_recency)
    pinnacle_closing_line = _line(latest_own.line)
    if pinnacle_closing_line != taken_line:
        return None, "line_moved"

    # Opponent side at opposing line (-taken_line)
    opp_side = BetSide.away.value if _enum_value(bet_side) == BetSide.home.value else BetSide.home.value
    opp_line = -taken_line
    matching_opp = [
        q for q in spread_quotes if _enum_value(q.side) == opp_side and _line(q.line) == opp_line
    ]
    if not matching_opp:
        return None, "one_sided"

    latest_opp = max(matching_opp, key=_recency)
    d_own = american_to_decimal(latest_own.price_american)
    d_opp = american_to_decimal(latest_opp.price_american)
    p_own, _ = devig_two_way(d_own, d_opp)

    fair_price = 1.0 / p_own
    return (p_own, fair_price), "ok"


def _devig_totals(
    quotes: List[OddsHistory], bet_side, taken_line: Optional[Decimal]
) -> Tuple[Optional[Tuple[float, float]], str]:
    """
    Finds latest total quote for bet_side.
    Only proceeds if Pinnacle's closing line == taken_line.
    Returns ((fair_prob, fair_price), status_reason).
    """
    if taken_line is None:
        return None, "invalid_line"

    totals_quotes = [q for q in quotes if _enum_value(q.market) == MarketType.totals.value]
    if not totals_quotes:
        return None, "no_quote"

    own_quotes = [q for q in totals_quotes if _enum_value(q.side) == _enum_value(bet_side)]
    if not own_quotes:
        return None, "no_quote"

    latest_own = max(own_quotes, key=_recency)
    pinnacle_closing_line = _line(latest_own.line)
    if pinnacle_closing_line != taken_line:
        return None, "line_moved"

    # Opponent side at the SAME line
    opp_side = BetSide.under.value if _enum_value(bet_side) == BetSide.over.value else BetSide.over.value
    matching_opp = [
        q for q in totals_quotes if _enum_value(q.side) == opp_side and _line(q.line) == taken_line
    ]
    if not matching_opp:
        return None, "one_sided"

    latest_opp = max(matching_opp, key=_recency)
    d_own = american_to_decimal(latest_own.price_american)
    d_opp = american_to_decimal(latest_opp.price_american)
    p_own, _ = devig_two_way(d_own, d_opp)

    fair_price = 1.0 / p_own
    return (p_own, fair_price), "ok"
