"""
Paper-trading report: how the strategies are doing and whether the model has any skill against the market.

* Performance per staking strategy: same definitions as the ``v_paper_performance`` view (PostgreSQL only, so the
  numbers are computed here to run on any database): settled bets, win rate (won / (won + lost)), P/L in units,
  ROI on settled stake, average CLV and the share of bets that beat the close (both over bets that have a CLV).
* CLV coverage: bets with a CLV over bets whose game has tipped off, and the closing captures that were missed
  (games that tipped off without a ``closing`` marker, so their closing line is lost for good).
* Model skill: Brier score of the champion's h2h home probability against the Brier score of the sharp book's
  de-vigged closing home probability, on the SAME final games. Only games with a ``closing`` marker, a recorded
  h2h home prediction and a two-sided closing quote from the sharp book take part. Lower is better; a model that
  does not beat the close has no edge to bet.
* Active models: the champion and every challenger with the predictions each has recorded (challengers only
  predict, they never bet) and how many final games those predictions cover.
* Model league: each challenger's live paired evaluation against the champion, its promotion gate in words and the
  promotion/retirement history (``app.services.league_report``).
* Bankroll per strategy: ``START_BANKROLL`` plus settled P/L.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy import func, select
from sqlmodel import Session

from app.analytics.betting_policy import START_BANKROLL
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
    StakingStrategy,
)
from app.services import market_close, model_registry
from app.services.clv_report import PinnacleClvReport, build_pinnacle_clv_report
from app.services.league_report import League, build_league, format_league

_SETTLED = (BetStatus.won, BetStatus.lost, BetStatus.push)


def _line(value) -> Optional[Decimal]:
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.1"))



def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


@dataclass
class StrategyPerformance:
    strategy: str
    bets: int = 0
    settled: int = 0
    pending: int = 0
    win_rate: Optional[float] = None
    pnl_units: float = 0.0
    roi: Optional[float] = None
    clv_bets: int = 0
    avg_clv: Optional[float] = None
    beat_close_rate: Optional[float] = None
    bankroll: float = START_BANKROLL


@dataclass
class MarketPerformance:
    market: str
    bets: int = 0
    settled: int = 0
    roi: Optional[float] = None
    avg_clv: Optional[float] = None


@dataclass
class ClvCoverage:
    bets_tipped_off: int = 0
    bets_with_clv: int = 0
    bets_line_moved: int = 0  # the book closed at another line: no comparable closing price
    bets_absent_at_close: int = 0  # quote absent from closing capture payload (market dropped)
    games_tipped_off: int = 0
    closings_missed: int = 0  # tipped-off games (not postponed) without a closing marker

    @property
    def coverage(self) -> Optional[float]:
        return self.bets_with_clv / self.bets_tipped_off if self.bets_tipped_off else None


@dataclass
class ModelSkill:
    model: Optional[str] = None  # the champion the numbers belong to, e.g. "elo_538 1.1"
    sharp_book: Optional[str] = None
    final_games: int = 0
    final_games_with_closing: int = 0
    games_compared: int = 0  # final + closing marker + h2h prediction + two-sided sharp close
    brier_model: Optional[float] = None
    brier_market: Optional[float] = None

    @property
    def difference(self) -> Optional[float]:
        """model - market: negative means the model scored better than the de-vigged close."""
        if self.brier_model is None or self.brier_market is None:
            return None
        return self.brier_model - self.brier_market


@dataclass
class ActiveModel:
    name: str
    version: str
    role: str
    predictions: int = 0  # model_prediction rows recorded (all markets)
    final_games: int = 0  # distinct final games those predictions cover


@dataclass
class PaperReport:
    now: datetime
    strategies: List[StrategyPerformance] = field(default_factory=list)
    markets: List[MarketPerformance] = field(default_factory=list)
    clv: ClvCoverage = field(default_factory=ClvCoverage)
    pinnacle_clv: Optional[PinnacleClvReport] = None
    skill: ModelSkill = field(default_factory=ModelSkill)
    models: List[ActiveModel] = field(default_factory=list)
    league: Optional[League] = None


def build_report(session: Session, now: Optional[datetime] = None) -> PaperReport:
    now = _aware_utc(now) if now is not None else datetime.now(timezone.utc)
    return PaperReport(
        now=now,
        strategies=_performance(session),
        markets=_market_breakdown(session),
        clv=_clv_coverage(session, now),
        pinnacle_clv=build_pinnacle_clv_report(session, now),
        skill=_model_skill(session),
        models=_active_models(session),
        league=build_league(session, now),
    )


# ------------------------------------------------------------------------------------------ performance

def _performance(session: Session) -> List[StrategyPerformance]:
    by_strategy: Dict[str, StrategyPerformance] = {s.value: StrategyPerformance(s.value) for s in StakingStrategy}
    rows = session.execute(
        select(
            SimulatedBet.strategy,
            SimulatedBet.status,
            SimulatedBet.stake_units,
            SimulatedBet.profit_units,
            SimulatedBet.clv_pct,
        )
    ).all()
    stakes: Dict[str, float] = defaultdict(float)
    won: Dict[str, int] = defaultdict(int)
    lost: Dict[str, int] = defaultdict(int)
    clv: Dict[str, List[float]] = defaultdict(list)
    for strategy, status, stake, profit, clv_pct in rows:
        name = _enum_value(strategy)
        perf = by_strategy.setdefault(name, StrategyPerformance(name))
        perf.bets += 1
        if status in _SETTLED:
            perf.settled += 1
            perf.pnl_units += float(profit or 0)
            stakes[name] += float(stake)
            if status == BetStatus.won:
                won[name] += 1
            elif status == BetStatus.lost:
                lost[name] += 1
        elif status == BetStatus.pending:
            perf.pending += 1
        if clv_pct is not None:
            clv[name].append(float(clv_pct))
    for name, perf in by_strategy.items():
        if won[name] + lost[name]:
            perf.win_rate = won[name] / (won[name] + lost[name])
        if stakes[name]:
            perf.roi = perf.pnl_units / stakes[name]
        if clv[name]:
            perf.clv_bets = len(clv[name])
            perf.avg_clv = sum(clv[name]) / len(clv[name])
            perf.beat_close_rate = sum(1 for value in clv[name] if value > 0) / len(clv[name])
        perf.bankroll = START_BANKROLL + perf.pnl_units
    return sorted(by_strategy.values(), key=lambda p: p.strategy)


def _market_breakdown(session: Session) -> List[MarketPerformance]:
    by_market = {m: MarketPerformance(m) for m in ("h2h", "spreads", "totals")}
    rows = session.execute(
        select(
            ModelPrediction.market,
            SimulatedBet.status,
            SimulatedBet.stake_units,
            SimulatedBet.profit_units,
            SimulatedBet.clv_pct,
        )
        .join(ModelPrediction, ModelPrediction.id == SimulatedBet.prediction_id)
    ).all()
    stakes: Dict[str, float] = defaultdict(float)
    pnl: Dict[str, float] = defaultdict(float)
    clv: Dict[str, List[float]] = defaultdict(list)
    for market, status, stake, profit, clv_pct in rows:
        m_str = _enum_value(market)
        perf = by_market.setdefault(m_str, MarketPerformance(m_str))
        perf.bets += 1
        if status in _SETTLED:
            perf.settled += 1
            pnl[m_str] += float(profit or 0)
            stakes[m_str] += float(stake)
        if clv_pct is not None:
            clv[m_str].append(float(clv_pct))
    for m_str, perf in by_market.items():
        if stakes[m_str]:
            perf.roi = pnl[m_str] / stakes[m_str]
        if clv[m_str]:
            perf.avg_clv = sum(clv[m_str]) / len(clv[m_str])
    return [by_market[m] for m in ("h2h", "spreads", "totals")]


# ------------------------------------------------------------------------------------------------- CLV

def _clv_coverage(session: Session, now: datetime) -> ClvCoverage:
    coverage = ClvCoverage()
    bet_rows = session.execute(
        select(
            SimulatedBet.closing_price,
            SimulatedBet.closing_line,
            Game.commence_time,
            Game.id,
            ModelPrediction.market,
            ModelPrediction.side,
            SimulatedBet.line_taken,
            OddsHistory.sportsbook_id,
            SimulatedBet.placed_at,
        )
        .join(ModelPrediction, ModelPrediction.id == SimulatedBet.prediction_id)
        .join(Game, Game.id == ModelPrediction.game_id)
        .join(OddsHistory, OddsHistory.id == SimulatedBet.odds_taken_id)
    ).all()

    # Games with closing capture marker
    markers: Dict[int, Tuple[int, datetime]] = {}  # game_id -> (capture_id, captured_at)
    for cap_id, game_id, captured_at in session.execute(
        select(OddsSnapshotCapture.id, OddsSnapshotCapture.game_id, OddsSnapshotCapture.captured_at).where(
            OddsSnapshotCapture.kind == CAPTURE_CLOSING
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

    for closing_price, closing_line, commence, game_id, market, side, line_taken, book_id, placed_at in bet_rows:
        if _aware_utc(commence) > now:
            continue
        coverage.bets_tipped_off += 1
        if closing_price is not None:
            coverage.bets_with_clv += 1
        elif closing_line is not None:
            coverage.bets_line_moved += 1
        else:
            marker_info = markers.get(game_id)
            if marker_info is not None:
                cap_id, closed_at = marker_info
                if placed_at is None or closed_at > _aware_utc(placed_at):
                    if cap_id in presence_by_capture:
                        m_str = market.value if hasattr(market, "value") else str(market)
                        s_str = side.value if hasattr(side, "value") else str(side)
                        l_val = _line(line_taken)
                        if (book_id, m_str, s_str, l_val) not in presence_by_capture[cap_id]:
                            coverage.bets_absent_at_close += 1

    with_closing = set(markers.keys())
    for game_id, commence, status in session.execute(select(Game.id, Game.commence_time, Game.status)).all():
        if status == "postponed" or _aware_utc(commence) > now:
            continue
        coverage.games_tipped_off += 1
        if game_id not in with_closing:
            coverage.closings_missed += 1
    return coverage


# -------------------------------------------------------------------------------------------------- skill

def _active_models(session: Session) -> List[ActiveModel]:
    champion = model_registry.get_champion(session)
    models: List[ActiveModel] = []
    for row in model_registry.list_active(session):
        role = "champion" if champion is not None and row.id == champion.id else row.role
        active = ActiveModel(row.name, row.version, role)
        active.predictions = int(
            session.execute(
                select(func.count(ModelPrediction.id)).where(
                    ModelPrediction.model_version_id == row.id, ModelPrediction.player_id.is_(None)
                )
            ).scalar_one()
        )
        active.final_games = int(
            session.execute(
                select(func.count(func.distinct(ModelPrediction.game_id)))
                .join(Game, Game.id == ModelPrediction.game_id)
                .where(
                    ModelPrediction.model_version_id == row.id,
                    ModelPrediction.player_id.is_(None),
                    Game.status == "final",
                )
            ).scalar_one()
        )
        models.append(active)
    return models


def _model_skill(session: Session) -> ModelSkill:
    skill = ModelSkill()
    champion = model_registry.get_champion(session)
    if champion is not None:
        skill.model = f"{champion.name} {champion.version}"
    finals = {
        game_id: (commence, home_score > away_score)
        for game_id, commence, home_score, away_score in session.execute(
            select(Game.id, Game.commence_time, Game.home_score, Game.away_score).where(
                Game.status == "final", Game.home_score.is_not(None), Game.away_score.is_not(None)
            )
        ).all()
    }
    skill.final_games = len(finals)
    if not finals:
        return skill

    with_closing = market_close.closing_marker_game_ids(session)
    closing_games = [game_id for game_id in finals if game_id in with_closing]
    skill.final_games_with_closing = len(closing_games)

    model_probs: Dict[int, float] = {}
    for game_id, prob in session.execute(
        select(ModelPrediction.game_id, ModelPrediction.model_prob).where(
            ModelPrediction.model_version_id == (champion.id if champion is not None else -1),
            ModelPrediction.market == MarketType.h2h,
            ModelPrediction.side == BetSide.home,
            ModelPrediction.player_id.is_(None),
        )
    ).all():
        model_probs[game_id] = float(prob)

    book_keys = market_close.sharp_books(session)
    if book_keys:
        skill.sharp_book = ", ".join(sorted(book_keys.values()))
    fair_home_by_game = market_close.sharp_closing_home_probs(
        session, {game_id: finals[game_id][0] for game_id in closing_games}, closing_games, book_keys
    )

    squared_model = squared_market = 0.0
    for game_id in closing_games:
        fair_home = fair_home_by_game.get(game_id)
        if game_id not in model_probs or fair_home is None:
            continue
        outcome = 1.0 if finals[game_id][1] else 0.0
        squared_model += (model_probs[game_id] - outcome) ** 2
        squared_market += (fair_home - outcome) ** 2
        skill.games_compared += 1
    if skill.games_compared:
        skill.brier_model = squared_model / skill.games_compared
        skill.brier_market = squared_market / skill.games_compared
    return skill


# --------------------------------------------------------------------------------------------------- text

def _pct(value: Optional[float], digits: int = 1) -> str:
    return "n/a" if value is None else f"{value * 100:.{digits}f}%"


def format_report(report: PaperReport) -> str:
    lines = [f"Paper trading report ({report.now.isoformat()})", ""]

    lines.append("Strategy performance (settled bets)")
    if not any(p.bets for p in report.strategies):
        lines.append("  No paper bets recorded yet.")
    for perf in report.strategies:
        lines.append(
            f"  {perf.strategy:<18} bets {perf.bets} (settled {perf.settled}, pending {perf.pending}) | "
            f"win rate {_pct(perf.win_rate)} | P/L {perf.pnl_units:+.2f}u | ROI {_pct(perf.roi)} | "
            f"avg CLV {_pct(perf.avg_clv, 2)} | beat close {_pct(perf.beat_close_rate)} (over {perf.clv_bets} bets with CLV)"
        )
    lines.append("")

    lines.append("Market breakdown (h2h / spreads / totals)")
    for m in report.markets:
        lines.append(
            f"  {m.market:<18} bets {m.bets} (settled {m.settled}) | "
            f"ROI {_pct(m.roi)} | avg CLV {_pct(m.avg_clv, 2)}"
        )
    lines.append("")

    clv = report.clv
    lines.append("CLV coverage")
    if clv.bets_tipped_off:
        lines.append(
            f"  {clv.bets_with_clv} of {clv.bets_tipped_off} bets on tipped-off games have a CLV ({_pct(clv.coverage)}); "
            f"{clv.bets_line_moved} closed at another line (no comparable price)."
        )
    else:
        lines.append("  No bets on tipped-off games yet.")
    lines.append(
        f"  Quotes absent at close: {clv.bets_absent_at_close} bet(s) dropped before tip-off."
    )
    lines.append(
        f"  Closing captures missed: {clv.closings_missed} of {clv.games_tipped_off} tipped-off games "
        "(those closing lines cannot be recovered)."
    )
    lines.append("")

    pclv = report.pinnacle_clv
    if pclv is not None:
        lines.append("CLV vs Pinnacle close (per game)")
        if pclv.games_count:
            mean_str = _pct(pclv.stats.mean_clv, 2)
            se_str = _pct(pclv.stats.std_err, 2)
            t_str = f"{pclv.stats.t_stat:.2f}" if pclv.stats.t_stat is not None else "n/a"
            sd_str = _pct(pclv.stats.std_dev, 2)
            needed = pclv.stats.bets_needed_for(0.01)
            needed_str = f"{needed:.0f}" if needed is not None else "n/a"
            lines.append(
                f"  games {pclv.games_count} | mean CLV {mean_str} | SE {se_str} | t {t_str} | "
                f"sd {sd_str} | bets needed for +1% {needed_str}"
            )
        else:
            lines.append("  No independent games with Pinnacle closing data yet.")
        exc = pclv.exclusions
        lines.append(
            f"  Exclusions: {exc.total} bets (no closing marker {exc.no_closing_marker}, "
            f"no Pinnacle quote {exc.no_pinnacle_quote}, line moved {exc.line_moved}, "
            f"one-sided {exc.one_sided_quote}, closing before bet {exc.closing_before_bet}, "
            f"absent at close {exc.absent_at_close})"
        )
        lines.append("")

    skill = report.skill
    title = f"Model skill of the champion ({skill.model})" if skill.model else "Model skill (no champion registered)"
    lines.append(f"{title} vs the de-vigged closing line (same final games, Brier: lower is better)")
    lines.append(
        f"  final games {skill.final_games}, with a closing capture {skill.final_games_with_closing}, "
        f"compared {skill.games_compared}" + (f" (sharp book: {skill.sharp_book})" if skill.sharp_book else "")
    )
    if skill.games_compared:
        verdict = "model better" if skill.difference < 0 else "market better" if skill.difference > 0 else "tie"
        lines.append(
            f"  Brier model {skill.brier_model:.4f} | Brier market {skill.brier_market:.4f} | "
            f"difference {skill.difference:+.4f} ({verdict})"
        )
    else:
        lines.append("  Cannot be computed yet: no final game has a closing capture, a model prediction and a sharp close.")
    lines.append("")

    lines.append("Active models (only the champion bets)")
    if report.models:
        lines.append(f"  {'model':<22}{'role':<12}{'predictions':>12}{'final games':>13}")
        for active in report.models:
            lines.append(
                f"  {active.name + ' ' + active.version:<22}{active.role:<12}{active.predictions:>12}{active.final_games:>13}"
            )
    else:
        lines.append("  No model registered.")
    lines.append("")

    if report.league is not None:
        lines.append(format_league(report.league))
        lines.append("")

    lines.append("Bankroll (start + settled P/L)")
    for perf in report.strategies:
        lines.append(f"  {perf.strategy:<18} {perf.bankroll:.2f}u")
    return "\n".join(lines)
