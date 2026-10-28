"""
Read-only paper-trading API endpoints:
  - GET /api/v1/paper/summary
  - GET /api/v1/paper/bets
  - GET /api/v1/paper/bankroll
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func
from sqlmodel import Session, select

from app.analytics.betting_policy import START_BANKROLL
from app.deps import get_db_session
from app.models import (
    BetSide,
    BetStatus,
    Game,
    MarketType,
    ModelPrediction,
    OddsHistory,
    SimulatedBet,
    Sportsbook,
    StakingStrategy,
    Team,
)
from app.services.paper_report import build_report

router = APIRouter(prefix="/paper", tags=["paper"])

_SETTLED_STATUSES = (BetStatus.won, BetStatus.lost, BetStatus.push)


# ---------------------------------------------------------------------------------- Pydantic schemas

class StrategySummary(BaseModel):
    strategy: str
    bets: int
    settled: int
    pending: int
    win_rate: Optional[float] = None
    pnl_units: float
    roi: Optional[float] = None
    bankroll: float
    avg_clv: Optional[float] = None
    beat_close_rate: Optional[float] = None
    clv_bets: int


class PinnacleClvExclusionsResponse(BaseModel):
    total: int
    no_closing_marker: int
    no_pinnacle_quote: int
    line_moved: int
    one_sided_quote: int
    closing_before_bet: int
    unsupported_market: int


class PinnacleClvSummaryResponse(BaseModel):
    games: int
    mean_clv: Optional[float] = None
    std_err: Optional[float] = None
    t_stat: Optional[float] = None
    std_dev: Optional[float] = None
    bets_needed_1pct: Optional[float] = None
    exclusions: PinnacleClvExclusionsResponse
    same_book_avg_clv: Optional[float] = None
    same_book_clv_bets: int = 0


class ChampionSkillResponse(BaseModel):
    model: Optional[str] = None
    sharp_book: Optional[str] = None
    games_compared: int
    brier_model: Optional[float] = None
    brier_market: Optional[float] = None
    difference: Optional[float] = None


class PaperSummaryResponse(BaseModel):
    strategies: List[StrategySummary]
    pinnacle_clv: PinnacleClvSummaryResponse
    champion_model: Optional[str] = None
    brier: ChampionSkillResponse


class BetGameInfo(BaseModel):
    id: int
    home_team: str
    away_team: str
    commence_time: datetime


class PaperBetItem(BaseModel):
    id: int
    game: BetGameInfo
    market: str
    side: str
    line: Optional[float] = None
    price_taken: float
    stake_units: float
    status: str
    profit_units: Optional[float] = None
    clv_pct: Optional[float] = None
    book: Optional[str] = None
    placed_at: Optional[datetime] = None
    strategy: str


class PaperBetsListResponse(BaseModel):
    total: int
    bets: List[PaperBetItem]


class BankrollPoint(BaseModel):
    settled_at: datetime
    cumulative_profit_units: float
    bankroll: float


class PaperBankrollResponse(BaseModel):
    series: Dict[str, List[BankrollPoint]]


# ---------------------------------------------------------------------------------- Endpoints

@router.get("/summary", response_model=PaperSummaryResponse)
def get_paper_summary(session: Session = Depends(get_db_session)) -> PaperSummaryResponse:
    report = build_report(session, datetime.now(timezone.utc))

    strategies_resp = [
        StrategySummary(
            strategy=s.strategy,
            bets=s.bets,
            settled=s.settled,
            pending=s.pending,
            win_rate=s.win_rate,
            pnl_units=s.pnl_units,
            roi=s.roi,
            bankroll=s.bankroll,
            avg_clv=s.avg_clv,
            beat_close_rate=s.beat_close_rate,
            clv_bets=s.clv_bets,
        )
        for s in report.strategies
    ]

    pclv = report.pinnacle_clv
    if pclv is not None:
        pinnacle_resp = PinnacleClvSummaryResponse(
            games=pclv.games_count,
            mean_clv=pclv.stats.mean_clv,
            std_err=pclv.stats.std_err,
            t_stat=pclv.stats.t_stat,
            std_dev=pclv.stats.std_dev,
            bets_needed_1pct=pclv.stats.bets_needed_for(0.01),
            exclusions=PinnacleClvExclusionsResponse(
                total=pclv.exclusions.total,
                no_closing_marker=pclv.exclusions.no_closing_marker,
                no_pinnacle_quote=pclv.exclusions.no_pinnacle_quote,
                line_moved=pclv.exclusions.line_moved,
                one_sided_quote=pclv.exclusions.one_sided_quote,
                closing_before_bet=pclv.exclusions.closing_before_bet,
                unsupported_market=pclv.exclusions.unsupported_market,
            ),
            same_book_avg_clv=pclv.same_book_avg_clv,
            same_book_clv_bets=pclv.same_book_clv_bets,
        )
    else:
        pinnacle_resp = PinnacleClvSummaryResponse(
            games=0,
            exclusions=PinnacleClvExclusionsResponse(
                total=0,
                no_closing_marker=0,
                no_pinnacle_quote=0,
                line_moved=0,
                one_sided_quote=0,
                closing_before_bet=0,
                unsupported_market=0,
            ),
        )

    brier_resp = ChampionSkillResponse(
        model=report.skill.model,
        sharp_book=report.skill.sharp_book,
        games_compared=report.skill.games_compared,
        brier_model=report.skill.brier_model,
        brier_market=report.skill.brier_market,
        difference=report.skill.difference,
    )

    return PaperSummaryResponse(
        strategies=strategies_resp,
        pinnacle_clv=pinnacle_resp,
        champion_model=report.skill.model,
        brier=brier_resp,
    )


@router.get("/bets", response_model=PaperBetsListResponse)
def get_paper_bets(
    strategy: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_db_session),
) -> PaperBetsListResponse:
    query = (
        select(
            SimulatedBet,
            ModelPrediction.market,
            ModelPrediction.side,
            Game.id.label("game_id"),
            Game.commence_time,
            Game.home_team_id,
            Game.away_team_id,
            OddsHistory.sportsbook_id,
        )
        .join(ModelPrediction, ModelPrediction.id == SimulatedBet.prediction_id)
        .join(Game, Game.id == ModelPrediction.game_id)
        .join(OddsHistory, OddsHistory.id == SimulatedBet.odds_taken_id)
    )

    if strategy:
        query = query.where(SimulatedBet.strategy == strategy)
    if status:
        query = query.where(SimulatedBet.status == status)

    # Count total
    total_query = select(func.count(SimulatedBet.id))
    if strategy:
        total_query = total_query.where(SimulatedBet.strategy == strategy)
    if status:
        total_query = total_query.where(SimulatedBet.status == status)
    total = session.execute(total_query).scalar_one()

    # Fetch page ordered newest first
    query = query.order_by(SimulatedBet.placed_at.desc(), SimulatedBet.id.desc()).offset(offset).limit(limit)
    rows = session.execute(query).all()

    if not rows:
        return PaperBetsListResponse(total=total, bets=[])

    # Preload teams and sportsbooks
    team_ids = {r[5] for r in rows} | {r[6] for r in rows}
    sportsbook_ids = {r[7] for r in rows if r[7] is not None}

    teams = {t.id: (t.abbreviation or t.full_name) for t in session.execute(select(Team).where(Team.id.in_(team_ids))).scalars()}
    sportsbooks = {s.id: s.name for s in session.execute(select(Sportsbook).where(Sportsbook.id.in_(sportsbook_ids))).scalars()}

    bet_items: List[PaperBetItem] = []
    for bet, market, side, game_id, commence, home_id, away_id, book_id in rows:
        home_name = teams.get(home_id, str(home_id))
        away_name = teams.get(away_id, str(away_id))
        book_name = sportsbooks.get(book_id)

        m_str = market.value if hasattr(market, "value") else str(market)
        s_str = side.value if hasattr(side, "value") else str(side)
        strat_str = bet.strategy.value if hasattr(bet.strategy, "value") else str(bet.strategy)
        status_str = bet.status.value if hasattr(bet.status, "value") else str(bet.status)

        bet_items.append(
            PaperBetItem(
                id=bet.id,
                game=BetGameInfo(
                    id=game_id,
                    home_team=home_name,
                    away_team=away_name,
                    commence_time=commence,
                ),
                market=m_str,
                side=s_str,
                line=float(bet.line_taken) if bet.line_taken is not None else None,
                price_taken=float(bet.price_taken),
                stake_units=float(bet.stake_units),
                status=status_str,
                profit_units=float(bet.profit_units) if bet.profit_units is not None else None,
                clv_pct=float(bet.clv_pct) if bet.clv_pct is not None else None,
                book=book_name,
                placed_at=bet.placed_at,
                strategy=strat_str,
            )
        )

    return PaperBetsListResponse(total=total, bets=bet_items)


@router.get("/bankroll", response_model=PaperBankrollResponse)
def get_paper_bankroll(session: Session = Depends(get_db_session)) -> PaperBankrollResponse:
    # Initialize series dictionary for all known strategies
    series: Dict[str, List[BankrollPoint]] = {s.value: [] for s in StakingStrategy}

    # Query all settled bets ordered chronologically
    settled_rows = session.execute(
        select(SimulatedBet)
        .where(
            SimulatedBet.status.in_(_SETTLED_STATUSES),
            SimulatedBet.settled_at.is_not(None),
        )
        .order_by(SimulatedBet.settled_at.asc(), SimulatedBet.id.asc())
    ).scalars().all()

    running_profit: Dict[str, float] = {s.value: 0.0 for s in StakingStrategy}
    for bet in settled_rows:
        strat = bet.strategy.value if hasattr(bet.strategy, "value") else str(bet.strategy)
        if strat not in series:
            series[strat] = []
            running_profit[strat] = 0.0

        pnl = float(bet.profit_units or 0.0)
        running_profit[strat] += pnl
        current_bankroll = START_BANKROLL + running_profit[strat]

        series[strat].append(
            BankrollPoint(
                settled_at=bet.settled_at,
                cumulative_profit_units=round(running_profit[strat], 4),
                bankroll=round(current_bankroll, 4),
            )
        )

    return PaperBankrollResponse(series=series)
