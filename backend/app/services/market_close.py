"""
The sharp book's de-vigged closing probability, shared by the paper report and the model evaluation.

For a final game with a ``closing`` capture marker, the closing line is the newest two-sided h2h pair of a sharp
book (``Sportsbook.is_sharp``) captured at or before tip-off; its proportional de-vig (``devig_two_way``) gives
the market's fair home probability. Several sharp books are tried in alphabetical key order and the first one
with both sides wins, so the choice never depends on row order.
"""
from datetime import datetime, timezone
from typing import Dict, Iterable, Mapping, Optional, Set

from sqlalchemy import select
from sqlmodel import Session

from app.analytics.props_engine import american_to_decimal, devig_two_way
from app.models import CAPTURE_CLOSING, BetSide, MarketType, OddsHistory, OddsSnapshotCapture, Sportsbook


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def sharp_books(session: Session) -> Dict[int, str]:
    """sportsbook id -> key of every sharp book."""
    rows = session.execute(select(Sportsbook.id, Sportsbook.key).where(Sportsbook.is_sharp.is_(True))).all()
    return {book_id: key for book_id, key in rows}


def closing_marker_game_ids(session: Session) -> Set[int]:
    """Games that have a ``closing`` capture marker (the closing line was captured for them)."""
    return set(
        session.execute(select(OddsSnapshotCapture.game_id).where(OddsSnapshotCapture.kind == CAPTURE_CLOSING)).scalars()
    )


def sharp_closing_home_probs(
    session: Session,
    commence_by_game: Mapping[int, datetime],
    game_ids: Iterable[int],
    books: Optional[Mapping[int, str]] = None,
) -> Dict[int, float]:
    """
    game id -> de-vigged sharp closing probability of the home side, for the ``game_ids`` that have a two-sided
    quote captured at or before their tip-off (``commence_by_game``). Games without one are left out.
    """
    book_keys = dict(sharp_books(session) if books is None else books)
    game_ids = list(game_ids)
    if not game_ids or not book_keys:
        return {}

    latest: Dict[tuple, tuple] = {}  # (game, book, side) -> (recency, price_american)
    for row in session.execute(
        select(OddsHistory).where(
            OddsHistory.game_id.in_(game_ids),
            OddsHistory.sportsbook_id.in_(list(book_keys)),
            OddsHistory.market == MarketType.h2h,
            OddsHistory.player_id.is_(None),
        )
    ).scalars():
        if row.captured_at is None or _aware_utc(row.captured_at) > _aware_utc(commence_by_game[row.game_id]):
            continue
        recency = (_aware_utc(row.captured_at), _aware_utc(row.book_last_update), row.id)
        key = (row.game_id, row.sportsbook_id, _enum_value(row.side))
        if key not in latest or recency > latest[key][0]:
            latest[key] = (recency, row.price_american)

    fair: Dict[int, float] = {}
    for game_id in game_ids:
        for book_id in sorted(book_keys, key=lambda b: book_keys[b]):
            home = latest.get((game_id, book_id, BetSide.home.value))
            away = latest.get((game_id, book_id, BetSide.away.value))
            if home is not None and away is not None:
                fair[game_id] = devig_two_way(american_to_decimal(home[1]), american_to_decimal(away[1]))[0]
                break
    return fair
