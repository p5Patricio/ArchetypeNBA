"""
Records Elo predictions and paper bets at decision time.

For every scheduled game that tips off within the horizon the recorder stores the model's probabilities in
``model_prediction`` and, when the betting policy (``app.analytics.betting_policy``) finds an edge over the
sharp book, a flat and a fractional-Kelly paper bet in ``simulated_bet``. Predictions that were not saved
before tip-off cannot be reconstructed later, which is why this runs on every tick and is idempotent.

Design notes
- Ratings: ``EloRatingService.current_ratings`` with the season of the game derived from its tip-off date (not
  from ``game.season_id``, which was wrong for rows created before the season existed), so the 25% carryover
  is applied on opening night. A season with no row yet is represented by a sentinel id that no team has
  played in, which triggers the same carryover.
- Stale-ratings guard: a game is skipped while either team has an earlier game that has not been settled
  (status scheduled/live and tipped off less than 24 h ago or still ahead); its rating would be out of date.
- Quotes: for every (sportsbook, market, side) the newest row by (book_last_update, captured_at) captured at
  or before ``now`` is that book's current quote (a moved line supersedes the old one). A quote is fresh when
  the newest capture of its game (the row itself or an ``odds_snapshot_capture`` marker, because an
  unchanged price inserts no new odds row) is at most ``max_quote_age_minutes`` old.
- Fair probability: the sharp book's de-vigged two-sided pair at one line. Without a pair the predictions are
  still recorded and no bet is placed. Candidates are priced at the best quote of the same line.
- A bet is placed at most once per (strategy, game, market, side) across all runs, never at or after tip-off.
  ``placed_at`` is the injected ``now``.
- ``dry_run`` computes everything and issues no INSERT at all.
"""
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy import func, or_, select
from sqlmodel import Session

from app.analytics import betting_policy as policy
from app.analytics import elo
from app.analytics.props_engine import american_to_decimal, devig_two_way
from app.models import (
    BetSide,
    BetStatus,
    Game,
    MarketType,
    ModelPrediction,
    ModelVersion,
    OddsHistory,
    OddsSnapshotCapture,
    Season,
    SimulatedBet,
    Sportsbook,
    StakingStrategy,
)
from app.services.elo_service import MODEL_NAME, MODEL_VERSION, EloRatingService
from app.services.odds_ingestion import OddsIngestionService

logger = logging.getLogger(__name__)

DEFAULT_HORIZON_HOURS = 20.0
DEFAULT_MAX_QUOTE_AGE_MINUTES = 360.0
STALE_GAME_WINDOW = timedelta(hours=24)
UNKNOWN_SEASON_ID = -1  # no team has ever played in it, so every rating gets the season carryover

_RECORDED_MARKETS = (MarketType.h2h, MarketType.spreads)
_STRATEGIES = (StakingStrategy.flat, StakingStrategy.kelly_fractional)
_SETTLED = (BetStatus.won, BetStatus.lost, BetStatus.push)


class RecorderError(RuntimeError):
    """The recorder cannot run (for example the model_version is not registered)."""


@dataclass(frozen=True)
class CandidateRecord:
    game_id: int
    market: str
    side: str
    line: Optional[float]
    book: str
    price: float
    p_cond: float
    p_fair: float
    raw_edge: float
    ev: float
    eligible: bool
    reason: str


@dataclass
class RecorderSummary:
    now: datetime
    dry_run: bool = False
    games_considered: int = 0  # scheduled games inside the horizon window
    games_processed: int = 0  # ... that passed the rating guards
    predictions_written: int = 0  # would-be writes on a dry run
    predictions_existing: int = 0
    bets_placed: Counter = field(default_factory=Counter)  # strategy -> bets (would-be on a dry run)
    skipped: Counter = field(default_factory=Counter)  # reason -> count
    candidates: List[CandidateRecord] = field(default_factory=list)


@dataclass(frozen=True)
class _Quote:
    id: int
    book_key: str
    is_sharp: bool
    market: str
    side: str
    line: Optional[Decimal]
    price: float  # decimal odds


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _line(value) -> Optional[Decimal]:
    return None if value is None else Decimal(str(value)).quantize(Decimal("0.1"))


def _prob(value: float) -> Decimal:
    return Decimal(f"{min(max(value, 1e-5), 1.0 - 1e-5):.5f}")


def _local_day(moment: datetime) -> date:
    return _aware_utc(moment).astimezone().date()


class PredictionRecorder:
    def __init__(
        self,
        session: Session,
        now: Optional[datetime] = None,
        horizon_hours: float = DEFAULT_HORIZON_HOURS,
        max_quote_age_minutes: float = DEFAULT_MAX_QUOTE_AGE_MINUTES,
    ):
        self.session = session
        self.now = _aware_utc(now) if now is not None else datetime.now(timezone.utc)
        self.horizon = timedelta(hours=horizon_hours)
        self.max_quote_age = timedelta(minutes=max_quote_age_minutes)

    # ------------------------------------------------------------------ entry point

    def run(self, dry_run: bool = False) -> RecorderSummary:
        summary = RecorderSummary(now=self.now, dry_run=dry_run)
        model_version = self._model_version()
        sigma = float((model_version.params or {}).get("sigma") or 0.0)
        if sigma <= 0:
            raise RecorderError(f"model_version {MODEL_NAME} {MODEL_VERSION} has no sigma in its params")

        games = self._window_games()
        summary.games_considered = len(games)
        if not games:
            return summary

        self._dry_run = dry_run
        self._model_version_id = model_version.id
        self._sigma = sigma
        self._elo = EloRatingService(self.session, sigma=sigma)
        self._ratings: Dict[int, Dict[int, float]] = {}
        self._load_ledger(games)

        game_ids = [g.id for g in games]
        quotes = self._load_quotes(game_ids)
        blocked = self._blocked_games(games)
        season_ids = self._season_ids_by_label()

        try:
            for game in games:
                reason = blocked.get(game.id)
                if reason is not None:
                    summary.skipped[reason] += 1
                    continue
                ratings = self._ratings_for(self._season_id_for(game, season_ids))
                if game.home_team_id not in ratings or game.away_team_id not in ratings:
                    summary.skipped["missing_ratings"] += 1
                    continue
                summary.games_processed += 1
                self._record_game(game, ratings, quotes.get(game.id, []), summary)
            if not dry_run:
                self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return summary

    # ------------------------------------------------------------------ inputs

    def _model_version(self) -> ModelVersion:
        row = self.session.execute(
            select(ModelVersion).where(ModelVersion.name == MODEL_NAME, ModelVersion.version == MODEL_VERSION)
        ).scalar_one_or_none()
        if row is None:
            raise RecorderError(
                f"model_version {MODEL_NAME} {MODEL_VERSION} is not registered; "
                "run scripts/backfill_elo.py --evaluate --register first"
            )
        return row

    def _window_games(self) -> List[Game]:
        """Scheduled games that tip off after ``now`` and within the horizon, soonest first."""
        stmt = (
            select(Game)
            .where(
                Game.status == "scheduled",
                Game.commence_time > self.now,
                Game.commence_time <= self.now + self.horizon,
            )
            .order_by(Game.commence_time, Game.id)
        )
        games = self.session.execute(stmt).scalars().all()
        # SQLite hands back naive datetimes: re-check in Python so the tip-off guard never depends on the driver.
        return [g for g in games if self.now < _aware_utc(g.commence_time) <= self.now + self.horizon]

    def _blocked_games(self, games: Sequence[Game]) -> Dict[int, str]:
        """game id -> skip reason for games whose teams still have an earlier unsettled game."""
        horizon_end = self.now + self.horizon
        stmt = select(Game).where(
            Game.status.in_(("scheduled", "live")),
            Game.commence_time > self.now - STALE_GAME_WINDOW,
            Game.commence_time <= horizon_end,
        )
        open_games = [
            (g.id, _aware_utc(g.commence_time), g.home_team_id, g.away_team_id)
            for g in self.session.execute(stmt).scalars().all()
        ]
        blocked: Dict[int, str] = {}
        for game in games:
            commence = _aware_utc(game.commence_time)
            teams = {game.home_team_id, game.away_team_id}
            for other_id, other_commence, home_id, away_id in open_games:
                if other_id != game.id and other_commence < commence and teams & {home_id, away_id}:
                    blocked[game.id] = "stale_ratings_earlier_game"
                    break
        return blocked

    def _season_ids_by_label(self) -> Dict[str, int]:
        return {label: season_id for season_id, label in self.session.execute(select(Season.id, Season.season_label))}

    @staticmethod
    def _season_id_for(game: Game, season_ids: Dict[str, int]) -> int:
        label = OddsIngestionService.season_label_for(_aware_utc(game.commence_time).date())
        return season_ids.get(label, UNKNOWN_SEASON_ID)

    def _ratings_for(self, season_id: int) -> Dict[int, float]:
        if season_id not in self._ratings:
            self._ratings[season_id] = self._elo.current_ratings(for_season_id=season_id)
        return self._ratings[season_id]

    def _load_quotes(self, game_ids: Sequence[int]) -> Dict[int, List[_Quote]]:
        """The fresh current quote of every (book, market, side) for each game."""
        stmt = (
            select(
                OddsHistory.id,
                OddsHistory.game_id,
                OddsHistory.sportsbook_id,
                OddsHistory.market,
                OddsHistory.side,
                OddsHistory.line,
                OddsHistory.price_american,
                OddsHistory.book_last_update,
                OddsHistory.captured_at,
            )
            .where(
                OddsHistory.game_id.in_(list(game_ids)),
                OddsHistory.market.in_(_RECORDED_MARKETS),
                OddsHistory.player_id.is_(None),
            )
        )
        rows = [row for row in self.session.execute(stmt).all() if row[8] is not None]
        rows = [row for row in rows if _aware_utc(row[8]) <= self.now]

        markers: Dict[int, datetime] = {}
        for game_id, captured_at in self.session.execute(
            select(OddsSnapshotCapture.game_id, OddsSnapshotCapture.captured_at).where(
                OddsSnapshotCapture.game_id.in_(list(game_ids))
            )
        ):
            captured = _aware_utc(captured_at)
            if captured <= self.now and captured > markers.get(game_id, datetime.min.replace(tzinfo=timezone.utc)):
                markers[game_id] = captured

        books = {
            book_id: (key, bool(sharp))
            for book_id, key, sharp in self.session.execute(select(Sportsbook.id, Sportsbook.key, Sportsbook.is_sharp))
        }

        newest: Dict[Tuple[int, int, str, str], tuple] = {}
        for row in rows:
            key = (row[1], row[2], _enum_value(row[3]), _enum_value(row[4]))
            order = (_aware_utc(row[7]), _aware_utc(row[8]), row[0])
            if key not in newest or order > newest[key][0]:
                newest[key] = (order, row)

        quotes: Dict[int, List[_Quote]] = defaultdict(list)
        for (game_id, book_id, market, side), (_, row) in newest.items():
            seen_at = max(_aware_utc(row[8]), markers.get(game_id, _aware_utc(row[8])))
            if self.now - seen_at > self.max_quote_age or book_id not in books:
                continue
            book_key, is_sharp = books[book_id]
            quotes[game_id].append(
                _Quote(row[0], book_key, is_sharp, market, side, _line(row[5]), american_to_decimal(row[6]))
            )
        for game_quotes in quotes.values():
            game_quotes.sort(key=lambda q: (q.market, q.side, q.book_key))
        return quotes

    def _load_ledger(self, games: Sequence[Game]) -> None:
        """Existing predictions, placed bets and the bankroll of each strategy."""
        game_ids = [g.id for g in games]
        window = set(game_ids)
        self._predictions: Dict[Tuple[int, str, str, Optional[Decimal]], int] = {}
        for pred_id, game_id, market, side, line in self.session.execute(
            select(
                ModelPrediction.id,
                ModelPrediction.game_id,
                ModelPrediction.market,
                ModelPrediction.side,
                ModelPrediction.line,
            ).where(
                ModelPrediction.model_version_id == self._model_version_id,
                ModelPrediction.game_id.in_(game_ids),
                ModelPrediction.player_id.is_(None),
            )
        ):
            self._predictions[(game_id, _enum_value(market), _enum_value(side), _line(line))] = pred_id

        self._placed: Set[Tuple[str, int, str, str]] = set()
        self._game_stake: Dict[str, Dict[int, float]] = {s.value: defaultdict(float) for s in _STRATEGIES}
        self._day_stake: Dict[str, Dict[date, float]] = {s.value: defaultdict(float) for s in _STRATEGIES}
        recent = self.now - timedelta(days=2)
        for strategy, game_id, market, side, stake, placed_at in self.session.execute(
            select(
                SimulatedBet.strategy,
                ModelPrediction.game_id,
                ModelPrediction.market,
                ModelPrediction.side,
                SimulatedBet.stake_units,
                SimulatedBet.placed_at,
            )
            .join(ModelPrediction, ModelPrediction.id == SimulatedBet.prediction_id)
            .where(or_(ModelPrediction.game_id.in_(game_ids), SimulatedBet.placed_at >= recent))
        ):
            name = _enum_value(strategy)
            amount = float(stake)
            if game_id in window:
                self._placed.add((name, game_id, _enum_value(market), _enum_value(side)))
                self._game_stake[name][game_id] += amount
            if placed_at is not None:
                self._day_stake[name][_local_day(placed_at)] += amount

        self._bankroll: Dict[str, float] = {s.value: policy.START_BANKROLL for s in _STRATEGIES}
        for strategy, profit in self.session.execute(
            select(SimulatedBet.strategy, func.sum(SimulatedBet.profit_units))
            .where(SimulatedBet.status.in_(_SETTLED))
            .group_by(SimulatedBet.strategy)
        ):
            self._bankroll[_enum_value(strategy)] += float(profit or 0.0)

    # ------------------------------------------------------------------ per game

    def _record_game(self, game: Game, ratings: Dict[int, float], quotes: List[_Quote], summary: RecorderSummary) -> None:
        prediction = self._elo.predict(game.home_team_id, game.away_team_id, ratings)
        mu, sigma = prediction.expected_margin, prediction.sigma
        projection = Decimal(f"{mu:.2f}")

        # h2h: always recorded, odds or not.
        h2h_ids = {
            BetSide.home.value: self._store_prediction(game, MarketType.h2h, BetSide.home, None, prediction.p_home, projection, summary),
            BetSide.away.value: self._store_prediction(game, MarketType.h2h, BetSide.away, None, 1.0 - prediction.p_home, projection, summary),
        }

        # spreads: one prediction pair per distinct home line quoted by any fresh book.
        spread_quotes = [q for q in quotes if q.market == MarketType.spreads.value and q.line is not None]
        spread_ids: Dict[Decimal, Dict[str, Optional[int]]] = {}
        spread_probs: Dict[Decimal, Tuple[float, float, float]] = {}
        for home_line in sorted({q.line if q.side == BetSide.home.value else -q.line for q in spread_quotes}):
            p_home_win, p_push, p_away_win = elo.spread_probabilities(mu, sigma, float(home_line))
            spread_probs[home_line] = (p_home_win, p_push, p_away_win)
            spread_ids[home_line] = {
                BetSide.home.value: self._store_prediction(game, MarketType.spreads, BetSide.home, home_line, p_home_win, projection, summary),
                BetSide.away.value: self._store_prediction(game, MarketType.spreads, BetSide.away, -home_line, p_away_win, projection, summary),
            }

        if not quotes:
            summary.skipped["no_fresh_quotes"] += 2  # h2h and spreads
            return

        # h2h candidates
        h2h = [q for q in quotes if q.market == MarketType.h2h.value]
        pair = self._sharp_h2h_pair(h2h)
        if pair is None:
            summary.skipped["no_sharp_reference" if h2h else "no_fresh_quotes"] += 1
        else:
            fair_home, fair_away = devig_two_way(pair[0], pair[1])
            p_home = prediction.p_home
            for side, p_win, p_loss, p_fair in (
                (BetSide.home, p_home, 1.0 - p_home, fair_home),
                (BetSide.away, 1.0 - p_home, p_home, fair_away),
            ):
                best = self._best_quote([q for q in h2h if q.side == side.value])
                self._consider(game, MarketType.h2h, side, None, h2h_ids[side.value], best, p_win, 0.0, p_loss, p_fair, summary)

        # spread candidates, one per sharp pair line
        spreads = [q for q in quotes if q.market == MarketType.spreads.value]
        pairs = self._sharp_spread_pairs(spreads)
        if not spreads:
            summary.skipped["no_fresh_quotes"] += 1
        elif not pairs:
            summary.skipped["no_sharp_reference"] += 1
        for home_line, (price_home, price_away) in pairs.items():
            fair_home, fair_away = devig_two_way(price_home, price_away)
            p_home_win, p_push, p_away_win = spread_probs[home_line]
            for side, line, p_win, p_loss, p_fair in (
                (BetSide.home, home_line, p_home_win, p_away_win, fair_home),
                (BetSide.away, -home_line, p_away_win, p_home_win, fair_away),
            ):
                same_line = [q for q in spreads if q.side == side.value and q.line == line]
                best = self._best_quote(same_line)
                self._consider(
                    game, MarketType.spreads, side, line, spread_ids[home_line][side.value], best,
                    p_win, p_push, p_loss, p_fair, summary,
                )

    @staticmethod
    def _best_quote(quotes: Sequence[_Quote]) -> Optional[_Quote]:
        # Highest price wins; ties go to the alphabetically first book so reruns pick the same row.
        return min(quotes, key=lambda q: (-q.price, q.book_key), default=None)

    @staticmethod
    def _sharp_h2h_pair(h2h: Sequence[_Quote]) -> Optional[Tuple[float, float]]:
        by_book: Dict[str, Dict[str, float]] = defaultdict(dict)
        for q in h2h:
            if q.is_sharp:
                by_book[q.book_key][q.side] = q.price
        for book in sorted(by_book):
            prices = by_book[book]
            if BetSide.home.value in prices and BetSide.away.value in prices:
                return prices[BetSide.home.value], prices[BetSide.away.value]
        return None

    @staticmethod
    def _sharp_spread_pairs(spreads: Sequence[_Quote]) -> Dict[Decimal, Tuple[float, float]]:
        """home line -> (sharp home price, sharp away price) where the away line is the exact opposite."""
        by_book: Dict[str, Dict[str, _Quote]] = defaultdict(dict)
        for q in spreads:
            if q.is_sharp:
                by_book[q.book_key][q.side] = q
        pairs: Dict[Decimal, Tuple[float, float]] = {}
        for book in sorted(by_book):
            home, away = by_book[book].get(BetSide.home.value), by_book[book].get(BetSide.away.value)
            if home is not None and away is not None and home.line == -away.line:
                pairs.setdefault(home.line, (home.price, away.price))
        return pairs

    # ------------------------------------------------------------------ writes

    def _store_prediction(
        self,
        game: Game,
        market: MarketType,
        side: BetSide,
        line: Optional[Decimal],
        p_win: float,
        projection: Decimal,
        summary: RecorderSummary,
    ) -> Optional[int]:
        """Id of the prediction for this target, creating it when new (None for a new one on a dry run)."""
        key = (game.id, market.value, side.value, _line(line))
        if key in self._predictions:
            summary.predictions_existing += 1
            return self._predictions[key]
        summary.predictions_written += 1
        if self._dry_run:
            return None
        row = ModelPrediction(
            model_version_id=self._model_version_id,
            game_id=game.id,
            market=market,
            side=side,
            line=_line(line),
            model_prob=_prob(p_win),
            projection=projection,
            predicted_at=self.now,
        )
        self.session.add(row)
        self.session.flush()
        self._predictions[key] = row.id
        return row.id

    def _consider(
        self,
        game: Game,
        market: MarketType,
        side: BetSide,
        line: Optional[Decimal],
        prediction_id: Optional[int],
        quote: Optional[_Quote],
        p_win: float,
        p_push: float,
        p_loss: float,
        p_fair: float,
        summary: RecorderSummary,
    ) -> None:
        if quote is None:
            summary.skipped["no_price_at_sharp_line"] += 1
            return
        decision = policy.evaluate_candidate(p_win, p_push, p_loss, p_fair, quote.price)
        summary.candidates.append(
            CandidateRecord(
                game.id, market.value, side.value, None if line is None else float(line), quote.book_key,
                quote.price, decision.p_cond, p_fair, decision.raw_edge, decision.ev, decision.eligible, decision.reason,
            )
        )
        if not decision.eligible:
            summary.skipped[decision.reason] += 1
            return
        if _aware_utc(game.commence_time) <= self.now:  # hard guard: nothing at or after tip-off
            summary.skipped["game_started"] += 1
            return

        today = _local_day(self.now)
        for strategy in _STRATEGIES:
            name = strategy.value
            if (name, game.id, market.value, side.value) in self._placed:
                summary.skipped["already_bet"] += 1
                continue
            bankroll = self._bankroll[name]
            day_room = policy.daily_room(bankroll, self._day_stake[name][today])
            game_room = policy.game_room(bankroll, self._game_stake[name][game.id])
            if strategy == StakingStrategy.flat:
                stake = policy.cap_stake(policy.flat_stake(), bankroll, daily_room=day_room, game_room=game_room)
                multiplier = None
            else:
                stake = policy.kelly_stake(bankroll, decision.f_star, daily_room=day_room, game_room=game_room)
                multiplier = Decimal(f"{policy.KELLY_MULTIPLIER:.3f}")
            if stake <= 0:
                summary.skipped["stake_below_min"] += 1
                continue

            summary.bets_placed[name] += 1
            self._placed.add((name, game.id, market.value, side.value))
            self._game_stake[name][game.id] += stake
            self._day_stake[name][today] += stake
            if self._dry_run:
                continue
            self.session.add(
                SimulatedBet(
                    prediction_id=prediction_id,
                    odds_taken_id=quote.id,
                    price_taken=Decimal(f"{quote.price:.4f}"),
                    line_taken=_line(quote.line),
                    fair_prob_at_bet=_prob(p_fair),
                    ev_per_unit=Decimal(f"{decision.ev:.5f}"),
                    strategy=strategy,
                    kelly_multiplier=multiplier,
                    stake_units=Decimal(f"{stake:.3f}"),
                    bankroll_before=Decimal(f"{bankroll:.3f}"),
                    status=BetStatus.pending,
                    placed_at=self.now,
                )
            )
