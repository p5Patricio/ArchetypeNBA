"""
Weekly view service: on-demand predictions, injuries, and candidate paper bets for the next N days.

Pure read-only service:
- Never writes to model_prediction, simulated_bet, or any other table.
- Computes predictions on demand for champion and active challengers using model_registry.
- Devigs Pinnacle's latest quote pair to get the market fair probability.
- Line shops across stored quotes to find the best available price and its age.
- Evaluates candidate paper bets with analytics.betting_policy.evaluate_candidate.
- Loads injuries from the latest injury report snapshot (flagging stale if older than 36 h).
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import logging
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlmodel import Session

from app.analytics import betting_policy as policy
from app.analytics.props_engine import american_to_decimal, devig_two_way
from app.models import (
    BetSide,
    Game,
    InjuryEntry,
    InjuryReportSnapshot,
    MarketType,
    ModelVersion,
    OddsHistory,
    OddsSnapshotCapture,
    Season,
    Sportsbook,
    Team,
    MODEL_ROLE_CHALLENGER,
)
from app.services import model_registry
from app.services.odds_ingestion import OddsIngestionService
from app.services.prediction_recorder import UNKNOWN_SEASON_ID, _aware_utc, _enum_value

logger = logging.getLogger(__name__)

MEXICO_CITY_TZ = ZoneInfo("America/Mexico_City")
STALE_INJURY_HOURS = 36.0

DAY_NAMES_ES = {
    "Monday": "Lunes",
    "Tuesday": "Martes",
    "Wednesday": "Miércoles",
    "Thursday": "Jueves",
    "Friday": "Viernes",
    "Saturday": "Sábado",
    "Sunday": "Domingo",
}


# -----------------------------------------------------------------------------
# Pydantic Models
# -----------------------------------------------------------------------------

class TeamInjuryEntry(BaseModel):
    player_name: str
    player_id: Optional[int] = None
    status: str
    reason: Optional[str] = None
    availability_prob: Optional[float] = None
    impact: Optional[float] = None


class TeamInjuriesBlock(BaseModel):
    snapshot_timestamp: Optional[datetime] = None
    stale: bool = False
    entries: List[TeamInjuryEntry] = Field(default_factory=list)


class TeamWeekView(BaseModel):
    id: int
    name: str
    abbreviation: str
    city: Optional[str] = None
    injuries: TeamInjuriesBlock


class SideMarketView(BaseModel):
    side: str  # "home" or "away"
    model_prob: Optional[float] = None
    fair_prob: Optional[float] = None
    edge: Optional[float] = None
    best_price: Optional[float] = None
    best_price_american: Optional[int] = None
    best_book: Optional[str] = None
    quote_age_minutes: Optional[float] = None
    would_qualify: bool = False
    reason: str
    ev: Optional[float] = None
    p_blend: Optional[float] = None


class ChampionPredictionView(BaseModel):
    model_id: int
    model_name: str
    model_version: str
    p_home: float
    p_away: float
    projected_margin: float
    sigma: Optional[float] = None


class ChallengerPredictionView(BaseModel):
    model_id: int
    model_name: str
    model_version: str
    p_home: float
    p_away: float
    projected_margin: Optional[float] = None


class WeekGameResponse(BaseModel):
    id: int
    game_id: int
    commence_time: datetime
    commence_time_local: str
    local_date: str
    local_time: str
    day_name: str
    day_name_es: str
    home_team: TeamWeekView
    away_team: TeamWeekView
    champion_prediction: Optional[ChampionPredictionView] = None
    challenger_predictions: List[ChallengerPredictionView] = Field(default_factory=list)
    home_market: SideMarketView
    away_market: SideMarketView
    injury_snapshot_timestamp: Optional[datetime] = None
    injury_snapshot_stale: bool = False


# -----------------------------------------------------------------------------
# Internal Quote Container
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class _StoredQuote:
    id: int
    game_id: int
    book_key: str
    is_sharp: bool
    side: str
    price_decimal: float
    price_american: Optional[int]
    seen_at: datetime
    age_minutes: float


# -----------------------------------------------------------------------------
# Week View Builder
# -----------------------------------------------------------------------------

def build_week_view(
    session: Session,
    days: int = 7,
    now: Optional[datetime] = None,
) -> List[WeekGameResponse]:
    """
    Builds the week view for upcoming scheduled games tipping off within the local day window.
    Pure read-only operation: no writes to DB.
    """
    now = _aware_utc(now) if now is not None else datetime.now(timezone.utc)
    local_now = now.astimezone(MEXICO_CITY_TZ)
    start_date = local_now.date()
    end_date = start_date + timedelta(days=days)

    # 1. Fetch scheduled games
    stmt = (
        select(Game)
        .where(Game.status == "scheduled")
        .order_by(Game.commence_time.asc(), Game.id.asc())
    )
    scheduled = session.execute(stmt).scalars().all()
    games: List[Game] = []
    for g in scheduled:
        commence_utc = _aware_utc(g.commence_time)
        commence_local = commence_utc.astimezone(MEXICO_CITY_TZ)
        if start_date <= commence_local.date() < end_date:
            games.append(g)

    if not games:
        return []

    game_ids = [g.id for g in games]
    team_ids = {g.home_team_id for g in games} | {g.away_team_id for g in games}

    # 2. Teams map
    teams = session.execute(select(Team).where(Team.id.in_(list(team_ids)))).scalars().all()
    teams_by_id: Dict[int, Team] = {t.id: t for t in teams if t.id is not None}

    # 3. Seasons map
    season_ids_by_label = {
        label: season_id
        for season_id, label in session.execute(select(Season.id, Season.season_label))
    }

    # 4. Models: Champion & Challengers (pure load, no insert)
    champion_row = model_registry.get_champion(session)
    champion_family = None
    if champion_row is not None:
        try:
            champion_family = model_registry.load_model(session, champion_row)
        except Exception as exc:
            logger.warning("Could not load champion model: %s", exc)

    challenger_rows = (
        session.execute(
            select(ModelVersion)
            .where(ModelVersion.role == MODEL_ROLE_CHALLENGER)
            .order_by(ModelVersion.id)
        )
        .scalars()
        .all()
    )
    challengers: List[Tuple[ModelVersion, Any]] = []
    for crow in challenger_rows:
        try:
            cfam = model_registry.load_model(session, crow)
            challengers.append((crow, cfam))
        except Exception as exc:
            logger.warning("Could not load challenger model id=%s: %s", crow.id, exc)

    # 5. Quotes & Pinnacle reference
    quotes_by_game = _load_quotes_for_games(session, game_ids, now)

    # 6. Injuries from latest snapshot
    snapshot, entries_by_team = _load_injuries_by_team(session)
    snap_time = _aware_utc(snapshot.report_timestamp) if snapshot is not None else None
    is_stale = (
        (now - snap_time) > timedelta(hours=STALE_INJURY_HOURS)
        if snap_time is not None
        else True
    )

    # 7. Build game view items
    items: List[WeekGameResponse] = []
    for game in games:
        commence_utc = _aware_utc(game.commence_time)
        commence_local = commence_utc.astimezone(MEXICO_CITY_TZ)
        local_date_str = commence_local.strftime("%Y-%m-%d")
        local_time_str = commence_local.strftime("%H:%M")
        day_en = commence_local.strftime("%A")
        day_es = DAY_NAMES_ES.get(day_en, day_en)

        home_team = teams_by_id.get(game.home_team_id)
        away_team = teams_by_id.get(game.away_team_id)

        home_name = home_team.full_name if home_team else f"Team {game.home_team_id}"
        home_abbr = home_team.abbreviation if home_team else "HOM"
        home_city = home_team.city if home_team else None

        away_name = away_team.full_name if away_team else f"Team {game.away_team_id}"
        away_abbr = away_team.abbreviation if away_team else "AWY"
        away_city = away_team.city if away_team else None

        # Resolve season
        season_label = OddsIngestionService.season_label_for(commence_utc.date())
        season_id = season_ids_by_label.get(season_label, UNKNOWN_SEASON_ID)

        # Champion prediction
        champ_pred = None
        if champion_family is not None and home_team is not None and away_team is not None:
            try:
                champ_pred = champion_family.predict(
                    game.home_team_id, game.away_team_id, season_id, commence_utc
                )
            except Exception as exc:
                logger.warning("Champion predict failed for game %s: %s", game.id, exc)

        champ_view: Optional[ChampionPredictionView] = None
        if champ_pred is not None and champion_row is not None:
            champ_view = ChampionPredictionView(
                model_id=champion_row.id,
                model_name=champion_row.name,
                model_version=champion_row.version,
                p_home=round(champ_pred.p_home, 4),
                p_away=round(1.0 - champ_pred.p_home, 4),
                projected_margin=round(champ_pred.mu, 2),
                sigma=round(champ_pred.sigma, 2) if champ_pred.sigma is not None else None,
            )

        # Challenger predictions
        challenger_views: List[ChallengerPredictionView] = []
        for crow, cfam in challengers:
            try:
                cpred = cfam.predict(game.home_team_id, game.away_team_id, season_id, commence_utc)
                if cpred is not None:
                    challenger_views.append(
                        ChallengerPredictionView(
                            model_id=crow.id,
                            model_name=crow.name,
                            model_version=crow.version,
                            p_home=round(cpred.p_home, 4),
                            p_away=round(1.0 - cpred.p_home, 4),
                            projected_margin=round(cpred.mu, 2) if cpred.mu is not None else None,
                        )
                    )
            except Exception as exc:
                logger.debug("Challenger %s predict failed for game %s: %s", crow.id, game.id, exc)

        # Quotes & Markets
        game_quotes = quotes_by_game.get(game.id, [])
        fair_home, fair_away = _sharp_h2h_pair(game_quotes)

        home_quotes = [q for q in game_quotes if q.side == BetSide.home.value]
        away_quotes = [q for q in game_quotes if q.side == BetSide.away.value]

        best_home = min(home_quotes, key=lambda q: (-q.price_decimal, q.book_key), default=None)
        best_away = min(away_quotes, key=lambda q: (-q.price_decimal, q.book_key), default=None)

        home_model_prob = champ_pred.p_home if champ_pred is not None else None
        away_model_prob = (1.0 - champ_pred.p_home) if champ_pred is not None else None

        home_market = _evaluate_side(
            side="home",
            model_prob=home_model_prob,
            fair_prob=fair_home,
            best_quote=best_home,
            commence_time=commence_utc,
            now=now,
        )
        away_market = _evaluate_side(
            side="away",
            model_prob=away_model_prob,
            fair_prob=fair_away,
            best_quote=best_away,
            commence_time=commence_utc,
            now=now,
        )

        # Team injuries
        home_injuries = _match_team_injuries(home_team, entries_by_team)
        away_injuries = _match_team_injuries(away_team, entries_by_team)

        home_team_view = TeamWeekView(
            id=game.home_team_id,
            name=home_name,
            abbreviation=home_abbr,
            city=home_city,
            injuries=TeamInjuriesBlock(
                snapshot_timestamp=snap_time,
                stale=is_stale,
                entries=home_injuries,
            ),
        )
        away_team_view = TeamWeekView(
            id=game.away_team_id,
            name=away_name,
            abbreviation=away_abbr,
            city=away_city,
            injuries=TeamInjuriesBlock(
                snapshot_timestamp=snap_time,
                stale=is_stale,
                entries=away_injuries,
            ),
        )

        items.append(
            WeekGameResponse(
                id=game.id,
                game_id=game.id,
                commence_time=commence_utc,
                commence_time_local=commence_local.isoformat(),
                local_date=local_date_str,
                local_time=local_time_str,
                day_name=day_en,
                day_name_es=day_es,
                home_team=home_team_view,
                away_team=away_team_view,
                champion_prediction=champ_view,
                challenger_predictions=challenger_views,
                home_market=home_market,
                away_market=away_market,
                injury_snapshot_timestamp=snap_time,
                injury_snapshot_stale=is_stale,
            )
        )

    return items


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _load_quotes_for_games(
    session: Session, game_ids: Sequence[int], now: datetime
) -> Dict[int, List[_StoredQuote]]:
    """
    Loads newest stored H2H quotes per (game, book, side) captured <= now.
    Does NOT discard older quotes (future games have older opening quotes).
    """
    stmt = (
        select(
            OddsHistory.id,
            OddsHistory.game_id,
            OddsHistory.sportsbook_id,
            OddsHistory.market,
            OddsHistory.side,
            OddsHistory.price_american,
            OddsHistory.book_last_update,
            OddsHistory.captured_at,
        )
        .where(
            OddsHistory.game_id.in_(list(game_ids)),
            OddsHistory.market == MarketType.h2h,
            OddsHistory.player_id.is_(None),
        )
    )
    rows = [r for r in session.execute(stmt).all() if r[7] is not None]
    rows = [r for r in rows if _aware_utc(r[7]) <= now]

    markers: Dict[int, datetime] = {}
    for gid, cat in session.execute(
        select(OddsSnapshotCapture.game_id, OddsSnapshotCapture.captured_at).where(
            OddsSnapshotCapture.game_id.in_(list(game_ids))
        )
    ):
        cap = _aware_utc(cat)
        if cap <= now and cap > markers.get(gid, datetime.min.replace(tzinfo=timezone.utc)):
            markers[gid] = cap

    books = {
        book_id: (key, bool(sharp))
        for book_id, key, sharp in session.execute(
            select(Sportsbook.id, Sportsbook.key, Sportsbook.is_sharp)
        )
    }

    newest: Dict[Tuple[int, int, str], tuple] = {}
    for r in rows:
        key = (r[1], r[2], _enum_value(r[4]))
        order = (_aware_utc(r[6]), _aware_utc(r[7]), r[0])
        if key not in newest or order > newest[key][0]:
            newest[key] = (order, r)

    quotes_by_game: Dict[int, List[_StoredQuote]] = defaultdict(list)
    for (gid, book_id, side), (_, r) in newest.items():
        if book_id not in books:
            continue
        book_key, is_sharp = books[book_id]
        seen_at = max(_aware_utc(r[7]), markers.get(gid, _aware_utc(r[7])))
        age_minutes = max(0.0, (now - seen_at).total_seconds() / 60.0)
        dec_price = american_to_decimal(r[5])

        quotes_by_game[gid].append(
            _StoredQuote(
                id=r[0],
                game_id=gid,
                book_key=book_key,
                is_sharp=is_sharp,
                side=side,
                price_decimal=dec_price,
                price_american=r[5],
                seen_at=seen_at,
                age_minutes=age_minutes,
            )
        )

    return quotes_by_game


def _sharp_h2h_pair(quotes: Sequence[_StoredQuote]) -> Tuple[Optional[float], Optional[float]]:
    """Pinnacle de-vigged pair (fair_home, fair_away) if two-sided sharp quote exists."""
    by_book: Dict[str, Dict[str, float]] = defaultdict(dict)
    for q in quotes:
        if q.is_sharp:
            by_book[q.book_key][q.side] = q.price_decimal
    for book in sorted(by_book):
        prices = by_book[book]
        if BetSide.home.value in prices and BetSide.away.value in prices:
            fair_home, fair_away = devig_two_way(
                prices[BetSide.home.value], prices[BetSide.away.value]
            )
            return round(fair_home, 4), round(fair_away, 4)
    return None, None


def _evaluate_side(
    side: str,
    model_prob: Optional[float],
    fair_prob: Optional[float],
    best_quote: Optional[_StoredQuote],
    commence_time: datetime,
    now: datetime,
) -> SideMarketView:
    """Evaluates candidate qualification for one side using policy.evaluate_candidate."""
    edge = None
    if model_prob is not None and fair_prob is not None:
        edge = round(model_prob - fair_prob, 4)

    best_price = best_quote.price_decimal if best_quote else None
    best_price_am = best_quote.price_american if best_quote else None
    best_book = best_quote.book_key if best_quote else None
    age_min = round(best_quote.age_minutes, 1) if best_quote else None

    if model_prob is None:
        return SideMarketView(
            side=side,
            model_prob=None,
            fair_prob=fair_prob,
            edge=None,
            best_price=best_price,
            best_price_american=best_price_am,
            best_book=best_book,
            quote_age_minutes=age_min,
            would_qualify=False,
            reason="missing_ratings",
            ev=None,
            p_blend=None,
        )

    if fair_prob is None:
        return SideMarketView(
            side=side,
            model_prob=round(model_prob, 4),
            fair_prob=None,
            edge=None,
            best_price=best_price,
            best_price_american=best_price_am,
            best_book=best_book,
            quote_age_minutes=age_min,
            would_qualify=False,
            reason="no_sharp_reference",
            ev=None,
            p_blend=None,
        )

    if best_quote is None:
        return SideMarketView(
            side=side,
            model_prob=round(model_prob, 4),
            fair_prob=fair_prob,
            edge=edge,
            best_price=None,
            best_price_american=None,
            best_book=None,
            quote_age_minutes=None,
            would_qualify=False,
            reason="no_quotes",
            ev=None,
            p_blend=None,
        )

    if commence_time <= now:
        return SideMarketView(
            side=side,
            model_prob=round(model_prob, 4),
            fair_prob=fair_prob,
            edge=edge,
            best_price=best_price,
            best_price_american=best_price_am,
            best_book=best_book,
            quote_age_minutes=age_min,
            would_qualify=False,
            reason="game_started",
            ev=None,
            p_blend=None,
        )

    decision = policy.evaluate_candidate(
        p_win=model_prob,
        p_push=0.0,
        p_loss=1.0 - model_prob,
        p_fair=fair_prob,
        decimal_price=best_quote.price_decimal,
    )
    return SideMarketView(
        side=side,
        model_prob=round(model_prob, 4),
        fair_prob=fair_prob,
        edge=edge,
        best_price=best_price,
        best_price_american=best_price_am,
        best_book=best_book,
        quote_age_minutes=age_min,
        would_qualify=decision.eligible,
        reason=decision.reason,
        ev=round(decision.ev, 4),
        p_blend=round(decision.p_blend, 4),
    )


def _load_injuries_by_team(
    session: Session,
) -> Tuple[Optional[InjuryReportSnapshot], Dict[str, List[InjuryEntry]]]:
    """Loads latest snapshot and groups non-Available entries by lowercase team key."""
    snapshot = session.execute(
        select(InjuryReportSnapshot).order_by(
            InjuryReportSnapshot.report_timestamp.desc(),
            InjuryReportSnapshot.id.desc(),
        )
    ).scalar_one_or_none()

    if snapshot is None:
        return None, {}

    entries = (
        session.execute(
            select(InjuryEntry).where(
                InjuryEntry.snapshot_id == snapshot.id,
                func.lower(InjuryEntry.status) != "available",
            )
        )
        .scalars()
        .all()
    )

    by_team: Dict[str, List[InjuryEntry]] = defaultdict(list)
    for e in entries:
        if e.team_name:
            by_team[e.team_name.strip().lower()].append(e)

    return snapshot, by_team


def _match_team_injuries(
    team: Optional[Team], entries_by_team: Dict[str, List[InjuryEntry]]
) -> List[TeamInjuryEntry]:
    """Matches injury entries to a team by full name, abbreviation, or city."""
    if team is None or not entries_by_team:
        return []

    candidates: List[InjuryEntry] = []
    keys = [team.full_name.strip().lower(), team.abbreviation.strip().lower()]
    if team.city:
        keys.append(team.city.strip().lower())

    seen_ids: Set[int] = set()
    for k in keys:
        for entry in entries_by_team.get(k, []):
            if entry.id not in seen_ids:
                seen_ids.add(entry.id)  # type: ignore
                candidates.append(entry)

    result: List[TeamInjuryEntry] = []
    for c in candidates:
        prob = float(c.availability_prob) if c.availability_prob is not None else None
        result.append(
            TeamInjuryEntry(
                player_name=c.player_name_raw,
                player_id=c.player_id,
                status=c.status,
                reason=c.reason,
                availability_prob=prob,
                impact=None,  # No impact helper is registered in main
            )
        )
    result.sort(key=lambda item: (item.status, item.player_name))
    return result
