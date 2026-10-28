"""
Market audit: closing-total error on settled games and player-prop closing quotes vig.
Read-only analysis of stored closing market data.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import math
import statistics
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlmodel import Session

from app.analytics.props_engine import american_to_decimal
from app.models import (
    CAPTURE_CLOSING,
    CAPTURE_CLOSING_PROPS,
    BetSide,
    Game,
    MarketType,
    OddsHistory,
    OddsSnapshotCapture,
    Sportsbook,
)


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _dec(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _line(value) -> Optional[Decimal]:
    return None if value is None else _dec(value).quantize(Decimal("0.1"))


def _recency(quote: OddsHistory) -> Tuple[datetime, datetime, int]:
    return (_aware_utc(quote.captured_at), _aware_utc(quote.book_last_update), quote.id)


@dataclass
class TotalErrorAudit:
    n_games: int = 0
    mean_error: Optional[float] = None
    std_dev: Optional[float] = None


@dataclass
class PropVigAudit:
    n_pairs: int = 0
    mean_vig: Optional[float] = None
    median_vig: Optional[float] = None


@dataclass
class MarketAuditResult:
    totals: TotalErrorAudit = field(default_factory=TotalErrorAudit)
    props: PropVigAudit = field(default_factory=PropVigAudit)


def audit_closing_totals(session: Session) -> TotalErrorAudit:
    """
    Computes error of (final total points - closing total line) on settled games
    that have a closing marker.
    """
    # 1. Settled games with closing marker
    closing_marker_ids = set(
        session.execute(
            select(OddsSnapshotCapture.game_id).where(OddsSnapshotCapture.kind == CAPTURE_CLOSING)
        ).scalars()
    )
    if not closing_marker_ids:
        return TotalErrorAudit()

    finals = session.execute(
        select(Game.id, Game.home_score, Game.away_score, Game.commence_time).where(
            Game.id.in_(list(closing_marker_ids)),
            Game.status == "final",
            Game.home_score.is_not(None),
            Game.away_score.is_not(None),
        )
    ).all()

    if not finals:
        return TotalErrorAudit()

    game_scores = {g_id: (h_score + a_score, commence) for g_id, h_score, a_score, commence in finals}
    game_ids = list(game_scores.keys())

    # 2. Closing totals quotes for these games
    quotes = session.execute(
        select(OddsHistory)
        .join(Sportsbook, Sportsbook.id == OddsHistory.sportsbook_id)
        .where(
            OddsHistory.game_id.in_(game_ids),
            OddsHistory.market == MarketType.totals,
            OddsHistory.player_id.is_(None),
            OddsHistory.line.is_not(None),
        )
        .order_by(Sportsbook.is_sharp.desc(), OddsHistory.captured_at.asc(), OddsHistory.id.asc())
    ).scalars().all()

    # Find latest quote at or before tip-off for each game (prioritizing sharp books)
    best_quote_by_game: Dict[int, OddsHistory] = {}
    for q in quotes:
        if q.captured_at is None:
            continue
        commence = game_scores[q.game_id][1]
        if _aware_utc(q.captured_at) > _aware_utc(commence):
            continue
        g_id = q.game_id
        if g_id not in best_quote_by_game:
            best_quote_by_game[g_id] = q
        else:
            prev = best_quote_by_game[g_id]
            # Replace if current is sharper or more recent among same sharpness
            if _recency(q) > _recency(prev):
                best_quote_by_game[g_id] = q

    errors: List[float] = []
    for g_id, q in best_quote_by_game.items():
        actual_total = game_scores[g_id][0]
        closing_line = float(q.line)
        errors.append(actual_total - closing_line)

    n = len(errors)
    if n == 0:
        return TotalErrorAudit()

    mean_err = sum(errors) / n
    sd_err = math.sqrt(sum((e - mean_err) ** 2 for e in errors) / (n - 1)) if n >= 2 else None

    return TotalErrorAudit(n_games=n, mean_error=mean_err, std_dev=sd_err)


def audit_prop_vig(session: Session) -> PropVigAudit:
    """
    Computes typical vig of stored player-prop closing quotes (over/under pairs).
    """
    # Quotes on games with a closing_props marker, or player prop quotes at/before tip-off
    closing_prop_games = set(
        session.execute(
            select(OddsSnapshotCapture.game_id).where(OddsSnapshotCapture.kind == CAPTURE_CLOSING_PROPS)
        ).scalars()
    )

    query = (
        select(OddsHistory, Game.commence_time)
        .join(Game, Game.id == OddsHistory.game_id)
        .where(
            OddsHistory.player_id.is_not(None),
            OddsHistory.side.in_([BetSide.over, BetSide.under, BetSide.over.value, BetSide.under.value]),
            OddsHistory.line.is_not(None),
        )
    )
    if closing_prop_games:
        query = query.where(OddsHistory.game_id.in_(list(closing_prop_games)))

    rows = session.execute(query).all()
    if not rows:
        return PropVigAudit()

    # Group by (game_id, sportsbook_id, market, player_id, line) -> side -> latest quote
    grouped: Dict[tuple, Dict[str, OddsHistory]] = defaultdict(dict)
    for q, commence in rows:
        if q.captured_at is None or _aware_utc(q.captured_at) > _aware_utc(commence):
            continue
        key = (q.game_id, q.sportsbook_id, _enum_value(q.market), q.player_id, _line(q.line))
        side_str = _enum_value(q.side)
        if side_str not in grouped[key] or _recency(q) > _recency(grouped[key][side_str]):
            grouped[key][side_str] = q

    vigs: List[float] = []
    for sides in grouped.values():
        if BetSide.over.value in sides and BetSide.under.value in sides:
            q_over = sides[BetSide.over.value]
            q_under = sides[BetSide.under.value]
            d_over = american_to_decimal(q_over.price_american)
            d_under = american_to_decimal(q_under.price_american)
            if d_over > 0 and d_under > 0:
                # Vig = sum of implied probabilities - 1.0
                vig = (1.0 / d_over + 1.0 / d_under) - 1.0
                vigs.append(vig)

    if not vigs:
        return PropVigAudit()

    return PropVigAudit(
        n_pairs=len(vigs),
        mean_vig=statistics.mean(vigs),
        median_vig=statistics.median(vigs),
    )


def run_market_audit(session: Session) -> MarketAuditResult:
    return MarketAuditResult(
        totals=audit_closing_totals(session),
        props=audit_prop_vig(session),
    )


def format_market_audit(result: MarketAuditResult) -> str:
    lines = ["Market Audit Report", ""]

    # (a) Closing totals error
    lines.append("1. Closing-total error on settled games (actual - closing line):")
    if result.totals.n_games > 0:
        sd_str = f"{result.totals.std_dev:.2f} pts" if result.totals.std_dev is not None else "n/a"
        lines.append(
            f"   n = {result.totals.n_games} games | "
            f"mean error = {result.totals.mean_error:+.2f} pts | "
            f"sd = {sd_str}"
        )
    else:
        lines.append("   no data (no settled games with closing totals quotes)")

    lines.append("")

    # (b) Player props vig
    lines.append("2. Player-prop closing quotes typical vig (over/under pairs):")
    if result.props.n_pairs > 0:
        lines.append(
            f"   n = {result.props.n_pairs} pairs | "
            f"mean vig = {result.props.mean_vig * 100:.2f}% | "
            f"median vig = {result.props.median_vig * 100:.2f}%"
        )
    else:
        lines.append("   no data (no over/under closing prop pairs)")

    return "\n".join(lines)
