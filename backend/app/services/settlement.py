"""
Settlement of paper bets and closing-line value (CLV).

``settle_bets``: pending ``simulated_bet`` rows whose game is ``final`` (with both scores) become won / lost /
push. Profit in units: won = ``stake * (price_taken - 1)``, lost = ``-stake``, push = 0. Bets of games that are not
final (postponed, still scheduled) stay pending; a final game without scores is never settled. Idempotent: a
settled bet is never touched again.

* h2h: the bet side against the winner.
* spreads: ``line_taken`` is the line of the bet's own side (a home bet at -3.5, an away bet at +3.5). The bet's
  margin is ``home - away`` for a home bet and ``away - home`` for an away bet; ``margin + line_taken`` > 0 wins,
  == 0 pushes (integer lines), < 0 loses.

``fill_clv``: for bets whose game has tipped off it stores the closing price of the same sportsbook, market, side
and exact line (``closing_odds_id``, ``closing_price``, ``closing_line``); ``clv_pct`` is a generated column.

* Only games with an ``odds_snapshot_capture`` marker of kind ``closing`` count. Without the marker the latest quote
  is merely the opening snapshot, which would turn "no information" into a fake zero CLV.
* The closing capture must be later than the bet (``captured_at`` of the marker > ``placed_at``).
* The closing quote is the book's latest quote of that side at or before tip-off. If it quotes the bet's line, its
  price is the closing price (an unchanged price is a legitimate 0 CLV: the odds feed stores a new row only when
  the book's own update stamp changes, so the row the bet was placed on is still the live quote). If the book has
  moved to another line, ``closing_price`` stays NULL (a price at a different line is not comparable) and
  ``closing_line`` records where the book closed, for information; ``clv_pct`` then stays NULL.
* The price uses ``american_to_decimal`` exactly like ``price_taken`` does, so an unchanged price is exactly 0.
"""
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlmodel import Session

from app.analytics.props_engine import american_to_decimal
from app.models import (
    CAPTURE_CLOSING,
    BetSide,
    BetStatus,
    Game,
    MarketType,
    ModelPrediction,
    OddsCapturePresence,
    OddsHistory,
    OddsSnapshotCapture,
    SimulatedBet,
)

logger = logging.getLogger(__name__)

_MONEY = Decimal("0.001")
_LINE = Decimal("0.1")
_PRICE = Decimal("0.0001")


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _dec(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _line(value) -> Optional[Decimal]:
    return None if value is None else _dec(value).quantize(_LINE)


# ------------------------------------------------------------------------------------------------ grading

def grade_bet(
    market: str, side: str, line: Optional[Decimal], home_score: int, away_score: int
) -> Optional[BetStatus]:
    """won / lost / push for a game-line bet, or None when the market is not settled by this module."""
    home_margin = home_score - away_score
    if market == MarketType.h2h.value:
        if side not in (BetSide.home.value, BetSide.away.value):
            return None
        if home_margin == 0:  # cannot happen in the NBA; never guess a winner
            return BetStatus.push
        home_won = home_margin > 0
        return BetStatus.won if home_won == (side == BetSide.home.value) else BetStatus.lost
    if market == MarketType.spreads.value:
        if side not in (BetSide.home.value, BetSide.away.value) or line is None:
            return None
        own_margin = home_margin if side == BetSide.home.value else -home_margin
        adjusted = Decimal(own_margin) + _dec(line)
        if adjusted > 0:
            return BetStatus.won
        if adjusted < 0:
            return BetStatus.lost
        return BetStatus.push
    return None


def profit_for(status: BetStatus, stake: Decimal, price: Decimal) -> Decimal:
    if status == BetStatus.won:
        return (_dec(stake) * (_dec(price) - 1)).quantize(_MONEY, rounding=ROUND_HALF_UP)
    if status == BetStatus.lost:
        return (-_dec(stake)).quantize(_MONEY, rounding=ROUND_HALF_UP)
    return Decimal(0).quantize(_MONEY)


@dataclass
class SettlementSummary:
    now: datetime
    dry_run: bool = False
    settled: Counter = field(default_factory=Counter)  # status value -> bets (would-be on a dry run)
    profit_units: Decimal = Decimal(0)
    skipped_unsupported: int = 0  # markets this module does not settle (totals, props)
    skipped_no_score: int = 0  # final game without both scores

    @property
    def total_settled(self) -> int:
        return sum(self.settled.values())


def settle_bets(session: Session, now: datetime, *, dry_run: bool = False) -> SettlementSummary:
    now = _aware_utc(now)
    summary = SettlementSummary(now=now, dry_run=dry_run)
    rows = session.execute(
        select(SimulatedBet, ModelPrediction.market, ModelPrediction.side, Game.home_score, Game.away_score)
        .join(ModelPrediction, ModelPrediction.id == SimulatedBet.prediction_id)
        .join(Game, Game.id == ModelPrediction.game_id)
        .where(SimulatedBet.status == BetStatus.pending, Game.status == "final")
        .order_by(SimulatedBet.id)
    ).all()
    for bet, market, side, home_score, away_score in rows:
        if home_score is None or away_score is None:
            summary.skipped_no_score += 1
            continue
        status = grade_bet(_enum_value(market), _enum_value(side), bet.line_taken, home_score, away_score)
        if status is None:
            summary.skipped_unsupported += 1
            continue
        profit = profit_for(status, bet.stake_units, bet.price_taken)
        summary.settled[status.value] += 1
        summary.profit_units += profit
        if dry_run:
            continue
        bet.status = status
        bet.profit_units = profit
        bet.settled_at = now
        session.add(bet)
    if not dry_run:
        session.commit()
    return summary


# ------------------------------------------------------------------------------------------------------ CLV

@dataclass
class ClvSummary:
    now: datetime
    dry_run: bool = False
    candidates: int = 0  # bets without a closing price whose game has tipped off
    filled: int = 0  # closing price stored (would-be on a dry run)
    line_moved: int = 0  # the book closed at another line: closing_line recorded, price NULL
    no_closing_marker: int = 0
    closing_before_bet: int = 0
    no_quote: int = 0  # the book had no quote of that side at tip-off
    absent_at_close: int = 0  # capture has presence rows, but the quote was absent


def fill_clv(session: Session, now: Optional[datetime] = None, *, dry_run: bool = False) -> ClvSummary:
    now = _aware_utc(now) if now is not None else datetime.now(timezone.utc)
    summary = ClvSummary(now=now, dry_run=dry_run)
    rows = session.execute(
        select(
            SimulatedBet,
            ModelPrediction.game_id,
            ModelPrediction.market,
            ModelPrediction.side,
            ModelPrediction.player_id,
            Game.commence_time,
            OddsHistory.sportsbook_id,
        )
        .join(ModelPrediction, ModelPrediction.id == SimulatedBet.prediction_id)
        .join(Game, Game.id == ModelPrediction.game_id)
        .join(OddsHistory, OddsHistory.id == SimulatedBet.odds_taken_id)
        .where(
            SimulatedBet.closing_price.is_(None),
            SimulatedBet.closing_line.is_(None),
            SimulatedBet.closing_odds_id.is_(None),
        )
        .order_by(SimulatedBet.id)
    ).all()
    # SQLite hands back naive datetimes: compare in Python so the tip-off guard never depends on the driver.
    due = [row for row in rows if _aware_utc(row[5]) <= now]
    summary.candidates = len(due)
    if not due:
        return summary

    game_ids = sorted({row[1] for row in due})
    markers: Dict[int, Tuple[int, datetime]] = {}  # game_id -> (capture_id, captured_at)
    for cap_id, game_id, captured_at in session.execute(
        select(OddsSnapshotCapture.id, OddsSnapshotCapture.game_id, OddsSnapshotCapture.captured_at).where(
            OddsSnapshotCapture.game_id.in_(game_ids), OddsSnapshotCapture.kind == CAPTURE_CLOSING
        )
    ).all():
        if captured_at is not None:
            markers[game_id] = (cap_id, _aware_utc(captured_at))

    capture_ids = [cap_id for cap_id, _ in markers.values()]
    presence_by_capture: Dict[int, Set[Tuple[int, str, str, Optional[Decimal]]]] = {}
    if capture_ids:
        for cap_id, book_id, market, side, line in session.execute(
            select(
                OddsCapturePresence.capture_id,
                OddsCapturePresence.sportsbook_id,
                OddsCapturePresence.market,
                OddsCapturePresence.side,
                OddsCapturePresence.line,
            ).where(OddsCapturePresence.capture_id.in_(capture_ids))
        ).all():
            m_val = market.value if hasattr(market, "value") else str(market)
            s_val = side.value if hasattr(side, "value") else str(side)
            l_val = _line(line)
            presence_by_capture.setdefault(cap_id, set()).add((book_id, m_val, s_val, l_val))

    quotes = _load_quotes(session, game_ids)
    for bet, game_id, market, side, player_id, commence_time, book_id in due:
        marker_info = markers.get(game_id)
        if marker_info is None:
            summary.no_closing_marker += 1
            continue
        capture_id, closed_at = marker_info
        if bet.placed_at is None or closed_at <= _aware_utc(bet.placed_at):
            summary.closing_before_bet += 1
            continue

        commence = _aware_utc(commence_time)
        m_str = _enum_value(market)
        s_str = _enum_value(side)
        key = (game_id, book_id, m_str, player_id, s_str)
        history = [q for q in quotes.get(key, []) if _aware_utc(q.captured_at) <= commence]
        if not history:
            summary.no_quote += 1
            continue
        taken_line = _line(bet.line_taken)
        latest = max(history, key=_recency)
        same_line = [q for q in history if _line(q.line) == taken_line]
        closing = max(same_line, key=_recency) if same_line else None
        if closing is not None and _aware_utc(closing.captured_at) >= _aware_utc(latest.captured_at):
            # Backward compatibility: if capture has NO presence rows at all (captures made before
            # this change), keep old behaviour. If it has presence rows, the closing quote is valid
            # ONLY if it was present in the closing capture payload.
            has_presence = capture_id in presence_by_capture
            if has_presence and (book_id, m_str, s_str, taken_line) not in presence_by_capture[capture_id]:
                # Stale quote: the book dropped the market/quote before closing.
                summary.absent_at_close += 1
                continue

            summary.filled += 1
            if not dry_run:
                bet.closing_odds_id = closing.id
                bet.closing_price = Decimal(f"{american_to_decimal(closing.price_american):.4f}")
                bet.closing_line = taken_line
                session.add(bet)
        else:  # the book closed at another line: not comparable, keep the line for information
            summary.line_moved += 1
            if not dry_run and latest.line is not None:
                bet.closing_line = _line(latest.line)
                session.add(bet)
    if not dry_run:
        session.commit()
    return summary


def _recency(quote) -> Tuple[datetime, datetime, int]:
    return (_aware_utc(quote.captured_at), _aware_utc(quote.book_last_update), quote.id)


def _load_quotes(session: Session, game_ids: List[int]) -> Dict[tuple, List[OddsHistory]]:
    """All odds rows of the games, grouped by (game, book, market, player, side)."""
    grouped: Dict[tuple, List[OddsHistory]] = {}
    chunk = 500
    for start in range(0, len(game_ids), chunk):
        stmt = select(OddsHistory).where(OddsHistory.game_id.in_(game_ids[start : start + chunk]))
        for row in session.execute(stmt).scalars():
            if row.captured_at is None:
                continue
            key = (row.game_id, row.sportsbook_id, _enum_value(row.market), row.player_id, _enum_value(row.side))
            grouped.setdefault(key, []).append(row)
    return grouped
