import enum
from decimal import Decimal
from typing import Optional, List, Dict, Any
from datetime import date, datetime
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint, Index
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    SmallInteger,
    Text,
    false as sa_false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB


class Season(SQLModel, table=True):
    __tablename__ = "season"

    id: Optional[int] = Field(default=None, primary_key=True)
    season_label: str = Field(unique=True, index=True)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_active: bool = False

    player_stats: List["PlayerSeasonStats"] = Relationship(back_populates="season")
    team_stats: List["TeamSeasonStats"] = Relationship(back_populates="season")
    game_logs: List["PlayerGameLog"] = Relationship(back_populates="season")
    shots: List["PlayerShot"] = Relationship(back_populates="season")
    advanced_stats: List["PlayerAdvancedStats"] = Relationship(back_populates="season")
    elo_ratings: List["TeamEloRating"] = Relationship(back_populates="season")
    similarities: List["PlayerSimilarity"] = Relationship(back_populates="season")
    matchup_stats: List["PlayerMatchupStats"] = Relationship(back_populates="season")


class Team(SQLModel, table=True):
    __tablename__ = "team"

    id: Optional[int] = Field(default=None, primary_key=True)
    abbreviation: str = Field(unique=True, index=True)
    full_name: str
    city: str
    conference: str
    division: str

    player_stats: List["PlayerSeasonStats"] = Relationship(back_populates="team")
    season_stats: List["TeamSeasonStats"] = Relationship(back_populates="team")
    elo_ratings: List["TeamEloRating"] = Relationship(back_populates="team")


class Player(SQLModel, table=True):
    __tablename__ = "player"

    id: Optional[int] = Field(default=None, primary_key=True)
    full_name: str = Field(index=True)
    birthdate: Optional[date] = None
    height_cm: Optional[int] = None
    weight_kg: Optional[int] = None
    position: Optional[str] = None
    headshot_url: Optional[str] = None

    season_stats: List["PlayerSeasonStats"] = Relationship(back_populates="player")
    game_logs: List["PlayerGameLog"] = Relationship(back_populates="player")
    shots: List["PlayerShot"] = Relationship(back_populates="player")
    advanced_stats: List["PlayerAdvancedStats"] = Relationship(back_populates="player")
    similarities: List["PlayerSimilarity"] = Relationship(back_populates="player", sa_relationship_kwargs={"foreign_keys": "PlayerSimilarity.player_id"})
    offensive_matchups: List["PlayerMatchupStats"] = Relationship(sa_relationship_kwargs={"foreign_keys": "PlayerMatchupStats.off_player_id"})
    defensive_matchups: List["PlayerMatchupStats"] = Relationship(sa_relationship_kwargs={"foreign_keys": "PlayerMatchupStats.def_player_id"})


class PlayerSeasonStats(SQLModel, table=True):
    __tablename__ = "player_season_stats"

    __table_args__ = (
        UniqueConstraint("player_id", "season_id", "team_id", name="uq_player_season_team"),
        Index("ix_season_cluster", "season_id", "cluster_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(foreign_key="player.id")
    team_id: int = Field(foreign_key="team.id")
    season_id: int = Field(foreign_key="season.id")

    gp: int = 0
    gs: int = 0
    min: float = 0.0

    fgm: float = 0.0
    fga: float = 0.0
    fg_pct: float = 0.0
    fg3m: float = 0.0
    fg3a: float = 0.0
    fg3_pct: float = 0.0
    ftm: float = 0.0
    fta: float = 0.0
    ft_pct: float = 0.0

    oreb: float = 0.0
    dreb: float = 0.0
    reb: float = 0.0

    ast: float = 0.0
    stl: float = 0.0
    blk: float = 0.0
    tov: float = 0.0
    pf: float = 0.0
    pts: float = 0.0

    cluster_id: Optional[int] = None

    player: "Player" = Relationship(back_populates="season_stats")
    team: "Team" = Relationship(back_populates="player_stats")
    season: "Season" = Relationship(back_populates="player_stats")


class TeamSeasonStats(SQLModel, table=True):
    __tablename__ = "team_season_stats"

    __table_args__ = (
        UniqueConstraint("team_id", "season_id", name="uq_team_season"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    team_id: int = Field(foreign_key="team.id")
    season_id: int = Field(foreign_key="season.id")

    wins: int = 0
    losses: int = 0
    win_pct: float = 0.0
    pts_avg: float = 0.0
    reb_avg: float = 0.0
    ast_avg: float = 0.0

    extra_stats: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    team: "Team" = Relationship(back_populates="season_stats")
    season: "Season" = Relationship(back_populates="team_stats")


# ============================================================================
# Phase 2: Data Engine Models
# ============================================================================

class PlayerGameLog(SQLModel, table=True):
    __tablename__ = "player_game_log"

    __table_args__ = (
        UniqueConstraint("player_id", "game_id", name="uq_player_game"),
        Index("ix_game_season", "season_id", "game_date"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(foreign_key="player.id")
    team_id: int = Field(foreign_key="team.id")
    season_id: int = Field(foreign_key="season.id")

    game_id: str = Field(index=True)
    game_date: Optional[date] = None
    matchup: Optional[str] = None
    wl: Optional[str] = None  # W or L
    min: int = 0

    fgm: int = 0
    fga: int = 0
    fg_pct: float = 0.0
    fg3m: int = 0
    fg3a: int = 0
    fg3_pct: float = 0.0
    ftm: int = 0
    fta: int = 0
    ft_pct: float = 0.0

    oreb: int = 0
    dreb: int = 0
    reb: int = 0
    ast: int = 0
    stl: int = 0
    blk: int = 0
    tov: int = 0
    pf: int = 0
    pts: int = 0
    plus_minus: int = 0

    player: "Player" = Relationship(back_populates="game_logs")
    season: "Season" = Relationship(back_populates="game_logs")


class PlayerShot(SQLModel, table=True):
    __tablename__ = "player_shot"

    __table_args__ = (
        Index("ix_shot_player_season", "player_id", "season_id"),
        Index("ix_shot_game", "game_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(foreign_key="player.id")
    season_id: int = Field(foreign_key="season.id")

    game_id: Optional[str] = None
    game_event_id: Optional[int] = None
    period: int = 1
    minutes_remaining: int = 0
    seconds_remaining: int = 0
    event_type: Optional[str] = None
    action_type: Optional[str] = None
    shot_type: Optional[str] = None
    shot_zone_basic: Optional[str] = None
    shot_zone_area: Optional[str] = None
    shot_zone_range: Optional[str] = None
    shot_distance: float = 0.0
    loc_x: float = 0.0
    loc_y: float = 0.0
    shot_attempted_flag: bool = False
    shot_made_flag: bool = False
    game_date: Optional[date] = None

    player: "Player" = Relationship(back_populates="shots")
    season: "Season" = Relationship(back_populates="shots")


class PlayerAdvancedStats(SQLModel, table=True):
    __tablename__ = "player_advanced_stats"

    __table_args__ = (
        UniqueConstraint("player_id", "season_id", name="uq_player_season_advanced"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(foreign_key="player.id")
    season_id: int = Field(foreign_key="season.id")

    per: Optional[float] = None
    ts_pct: Optional[float] = None
    ftr: Optional[float] = None
    orb_pct: Optional[float] = None
    drb_pct: Optional[float] = None
    trb_pct: Optional[float] = None
    ast_pct: Optional[float] = None
    stl_pct: Optional[float] = None
    blk_pct: Optional[float] = None
    tov_pct: Optional[float] = None
    usg_pct: Optional[float] = None
    ows: Optional[float] = None
    dws: Optional[float] = None
    ws: Optional[float] = None
    ws_per_48: Optional[float] = None
    obpm: Optional[float] = None
    dbpm: Optional[float] = None
    bpm: Optional[float] = None
    vorp: Optional[float] = None

    player: "Player" = Relationship(back_populates="advanced_stats")
    season: "Season" = Relationship(back_populates="advanced_stats")


class TeamEloRating(SQLModel, table=True):
    __tablename__ = "team_elo_rating"

    __table_args__ = (
        UniqueConstraint("team_id", "season_id", "game_id", name="uq_team_season_game_elo"),
        Index("ix_elo_season", "season_id", "rating_after"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    team_id: int = Field(foreign_key="team.id")
    season_id: int = Field(foreign_key="season.id")

    game_id: Optional[str] = None
    game_date: Optional[date] = None
    opponent_team_id: Optional[int] = None
    rating_before: float = 1500.0
    rating_after: float = 1500.0
    k_factor: float = 20.0
    result: Optional[str] = None  # W or L
    win_probability: Optional[float] = None

    team: "Team" = Relationship(back_populates="elo_ratings")
    season: "Season" = Relationship(back_populates="elo_ratings")


class PlayerSimilarity(SQLModel, table=True):
    __tablename__ = "player_similarity"

    __table_args__ = (
        UniqueConstraint("player_id", "season_id", "similar_player_id", name="uq_similarity"),
        Index("ix_similarity_score", "season_id", "similarity_score"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(foreign_key="player.id")
    season_id: int = Field(foreign_key="season.id")
    similar_player_id: int = Field(foreign_key="player.id")
    similarity_score: float = 0.0

    player: "Player" = Relationship(back_populates="similarities", sa_relationship_kwargs={"foreign_keys": "PlayerSimilarity.player_id"})
    season: "Season" = Relationship(back_populates="similarities")


class PlayerContract(SQLModel, table=True):
    __tablename__ = "player_contract"

    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(foreign_key="player.id", index=True)
    team_id: Optional[int] = Field(default=None, foreign_key="team.id")
    season_id: Optional[int] = Field(default=None, foreign_key="season.id")

    annual_salary: float = 0.0  # in USD, e.g. 51915615.0
    cap_hit_pct: float = 0.0    # e.g. 35.0 (%)
    contract_type: str = "Standard"  # Supermax, Max, Veteran Minimum, Rookie Scale, Mid-Level
    years_remaining: int = 1
    free_agency_year: int = 2026
    is_guaranteed: bool = True


# ============================================================================
# Phase 3: 1v1 Matchup Tracking Data
# ============================================================================

class PlayerMatchupStats(SQLModel, table=True):
    __tablename__ = "player_matchup_stats"

    __table_args__ = (
        UniqueConstraint("season_id", "off_player_id", "def_player_id", name="uq_matchup_season_off_def"),
        Index("ix_matchup_off_poss", "off_player_id", "partial_poss"),
        Index("ix_matchup_def_poss", "def_player_id", "partial_poss"),
        Index("ix_matchup_season_off", "season_id", "off_player_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    season_id: int = Field(foreign_key="season.id")
    off_player_id: int = Field(foreign_key="player.id")
    def_player_id: int = Field(foreign_key="player.id")

    gp: int = 0
    matchup_min: float = 0.0
    partial_poss: float = 0.0
    player_pts: float = 0.0
    team_pts: float = 0.0
    matchup_ast: float = 0.0
    matchup_tov: float = 0.0
    matchup_blk: float = 0.0
    matchup_fgm: float = 0.0
    matchup_fga: float = 0.0
    matchup_fg_pct: float = 0.0
    matchup_fg3m: float = 0.0
    matchup_fg3a: float = 0.0
    matchup_fg3_pct: float = 0.0
    help_blk: float = 0.0
    help_fgm: float = 0.0
    help_fga: float = 0.0
    help_fg_perc: float = 0.0
    matchup_ftm: float = 0.0
    matchup_fta: float = 0.0
    sfl: float = 0.0
    matchup_time_sec: float = 0.0

    # Normalized metrics (per 75 possessions and True Shooting %)
    ts_pct: float = 0.0
    pts_per_75: float = 0.0
    ast_per_75: float = 0.0
    tov_per_75: float = 0.0

    season: "Season" = Relationship(back_populates="matchup_stats")
    off_player: "Player" = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "PlayerMatchupStats.off_player_id",
            "overlaps": "offensive_matchups",
        }
    )
    def_player: "Player" = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "PlayerMatchupStats.def_player_id",
            "overlaps": "defensive_matchups",
        }
    )


# ============================================================================
# Phase 4: Quant Paper Trading
# ============================================================================
# Persistence layer for odds history, model predictions and simulated bets.
# Target DB is PostgreSQL 15 (native enums, GENERATED columns, NULLS NOT
# DISTINCT unique constraints, BRIN index). Tests run on SQLite through
# SQLModel.metadata.create_all, so every dialect-specific feature is expressed
# through a variant/kwarg that SQLite ignores. The Alembic migration
# `add_quant_paper_trading` is hand written and must be kept in sync.
# The views v_closing_odds / v_paper_performance exist only in the migration.


class MarketType(str, enum.Enum):
    h2h = "h2h"
    spreads = "spreads"
    totals = "totals"
    player_points = "player_points"
    player_rebounds = "player_rebounds"
    player_assists = "player_assists"
    player_pra = "player_pra"


class BetSide(str, enum.Enum):
    home = "home"
    away = "away"
    over = "over"
    under = "under"


class BetStatus(str, enum.Enum):
    pending = "pending"
    won = "won"
    lost = "lost"
    push = "push"
    void = "void"


class StakingStrategy(str, enum.Enum):
    flat = "flat"
    kelly_fractional = "kelly_fractional"


def _pg_enum(py_enum: type[enum.Enum], name: str) -> SAEnum:
    """Named enum: native PG enum type, VARCHAR + CHECK on SQLite."""
    return SAEnum(
        py_enum,
        name=name,
        values_callable=lambda e: [member.value for member in e],
        create_constraint=True,
    )


_MARKET_TYPE = _pg_enum(MarketType, "market_type")
_BET_SIDE = _pg_enum(BetSide, "bet_side")
_BET_STATUS = _pg_enum(BetStatus, "bet_status")
_STAKING_STRATEGY = _pg_enum(StakingStrategy, "staking_strategy")

# SQLite only auto-increments a plain INTEGER primary key.
_BIG_ID = BigInteger().with_variant(Integer(), "sqlite")
_SMALL_ID = SmallInteger().with_variant(Integer(), "sqlite")
_JSON = JSON().with_variant(JSONB(), "postgresql")


def _timestamptz(**kwargs: Any) -> Column:
    return Column(DateTime(timezone=True), **kwargs)


class Sportsbook(SQLModel, table=True):
    __tablename__ = "sportsbook"

    __table_args__ = (UniqueConstraint("key", name="uq_sportsbook_key"),)

    id: Optional[int] = Field(
        default=None, sa_column=Column(_SMALL_ID, primary_key=True, autoincrement=True)
    )
    key: str = Field(sa_column=Column(Text, nullable=False))  # provider key, e.g. "pinnacle"
    name: str = Field(sa_column=Column(Text, nullable=False))
    region: str = Field(sa_column=Column(Text, nullable=False))
    is_sharp: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default=sa_false())
    )


class Game(SQLModel, table=True):
    __tablename__ = "game"

    __table_args__ = (
        UniqueConstraint("nba_game_id", name="uq_game_nba_game_id"),
        UniqueConstraint("provider_event_id", name="uq_game_provider_event_id"),
        CheckConstraint("home_team_id <> away_team_id", name="ck_game_distinct_teams"),
        CheckConstraint(
            "status IN ('scheduled', 'live', 'final', 'postponed')", name="ck_game_status"
        ),
        Index("ix_game_commence_time", "commence_time"),
    )

    id: Optional[int] = Field(
        default=None, sa_column=Column(_BIG_ID, primary_key=True, autoincrement=True)
    )
    # Joins player_game_log.game_id
    nba_game_id: Optional[str] = Field(default=None, sa_column=Column(Text))
    provider_event_id: Optional[str] = Field(default=None, sa_column=Column(Text))
    season_id: int = Field(sa_column=Column(Integer, ForeignKey("season.id"), nullable=False))
    home_team_id: int = Field(sa_column=Column(Integer, ForeignKey("team.id"), nullable=False))
    away_team_id: int = Field(sa_column=Column(Integer, ForeignKey("team.id"), nullable=False))
    commence_time: datetime = Field(sa_column=_timestamptz(nullable=False))
    status: str = Field(
        default="scheduled",
        sa_column=Column(Text, nullable=False, server_default=text("'scheduled'")),
    )
    home_score: Optional[int] = Field(default=None, sa_column=Column(SmallInteger))
    away_score: Optional[int] = Field(default=None, sa_column=Column(SmallInteger))


class OddsHistory(SQLModel, table=True):
    """Append-only odds snapshots, one row per (book, market, side, line, book update)."""

    __tablename__ = "odds_history"

    __table_args__ = (
        CheckConstraint(
            "price_american <= -100 OR price_american >= 100", name="ck_odds_price_american"
        ),
        # NULLS NOT DISTINCT (PostgreSQL 15+): player_id/line are NULL for game markets.
        UniqueConstraint(
            "game_id",
            "sportsbook_id",
            "market",
            "player_id",
            "side",
            "line",
            "book_last_update",
            name="uq_odds_history_quote",
            postgresql_nulls_not_distinct=True,
        ),
        Index(
            "ix_odds_history_lookup",
            "game_id",
            "market",
            "player_id",
            "side",
            "sportsbook_id",
            text("captured_at DESC"),
        ),
        Index("ix_odds_history_captured_brin", "captured_at", postgresql_using="brin"),
    )

    id: Optional[int] = Field(
        default=None, sa_column=Column(_BIG_ID, primary_key=True, autoincrement=True)
    )
    game_id: int = Field(
        sa_column=Column(_BIG_ID, ForeignKey("game.id", ondelete="CASCADE"), nullable=False)
    )
    sportsbook_id: int = Field(
        sa_column=Column(_SMALL_ID, ForeignKey("sportsbook.id"), nullable=False)
    )
    market: MarketType = Field(sa_column=Column(_MARKET_TYPE, nullable=False))
    player_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, ForeignKey("player.id"))
    )  # NULL for game markets
    side: BetSide = Field(sa_column=Column(_BET_SIDE, nullable=False))
    line: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(5, 1)))
    price_american: int = Field(sa_column=Column(Integer, nullable=False))
    price_decimal: Optional[Decimal] = Field(
        default=None,
        sa_column=Column(
            Numeric(8, 4),
            Computed(
                "CASE WHEN price_american > 0 THEN 1 + price_american / 100.0 "
                "ELSE 1 + 100.0 / ABS(price_american) END",
                persisted=True,
            ),
        ),
    )
    book_last_update: datetime = Field(sa_column=_timestamptz(nullable=False))
    captured_at: Optional[datetime] = Field(
        default=None, sa_column=_timestamptz(nullable=False, server_default=func.now())
    )


class ModelVersion(SQLModel, table=True):
    __tablename__ = "model_version"

    __table_args__ = (UniqueConstraint("name", "version", name="uq_model_version_name_version"),)

    id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, primary_key=True, autoincrement=True)
    )
    name: str = Field(sa_column=Column(Text, nullable=False))
    version: str = Field(sa_column=Column(Text, nullable=False))
    params: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(_JSON, nullable=False, server_default=text("'{}'")),
    )
    brier_oos: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(6, 5)))
    trained_at: Optional[datetime] = Field(
        default=None, sa_column=_timestamptz(server_default=func.now())
    )


class ModelPrediction(SQLModel, table=True):
    __tablename__ = "model_prediction"

    __table_args__ = (
        CheckConstraint("model_prob > 0 AND model_prob < 1", name="ck_prediction_prob_range"),
        UniqueConstraint(
            "model_version_id",
            "game_id",
            "market",
            "player_id",
            "side",
            "line",
            name="uq_model_prediction_target",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Optional[int] = Field(
        default=None, sa_column=Column(_BIG_ID, primary_key=True, autoincrement=True)
    )
    model_version_id: int = Field(
        sa_column=Column(Integer, ForeignKey("model_version.id"), nullable=False)
    )
    game_id: int = Field(
        sa_column=Column(_BIG_ID, ForeignKey("game.id", ondelete="CASCADE"), nullable=False)
    )
    market: MarketType = Field(sa_column=Column(_MARKET_TYPE, nullable=False))
    player_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, ForeignKey("player.id"))
    )
    side: BetSide = Field(sa_column=Column(_BET_SIDE, nullable=False))
    line: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(5, 1)))
    model_prob: Decimal = Field(sa_column=Column(Numeric(6, 5), nullable=False))
    fair_decimal: Optional[Decimal] = Field(
        default=None,
        sa_column=Column(Numeric(8, 4), Computed("1 / model_prob", persisted=True)),
    )
    projection: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(6, 2)))
    predicted_at: Optional[datetime] = Field(
        default=None, sa_column=_timestamptz(server_default=func.now())
    )


class SimulatedBet(SQLModel, table=True):
    __tablename__ = "simulated_bet"

    __table_args__ = (
        CheckConstraint("stake_units > 0", name="ck_simulated_bet_stake_positive"),
        CheckConstraint(
            "closing_price IS NULL OR closing_price > 0", name="ck_simulated_bet_closing_price"
        ),
        CheckConstraint(
            "status = 'pending' OR settled_at IS NOT NULL", name="ck_simulated_bet_settled_at"
        ),
        Index(
            "ix_simulated_bet_pending",
            "status",
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
        Index("ix_simulated_bet_strategy_placed", "strategy", "placed_at"),
    )

    id: Optional[int] = Field(
        default=None, sa_column=Column(_BIG_ID, primary_key=True, autoincrement=True)
    )
    prediction_id: int = Field(
        sa_column=Column(_BIG_ID, ForeignKey("model_prediction.id"), nullable=False)
    )
    odds_taken_id: int = Field(
        sa_column=Column(_BIG_ID, ForeignKey("odds_history.id"), nullable=False)
    )
    price_taken: Decimal = Field(sa_column=Column(Numeric(8, 4), nullable=False))
    line_taken: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(5, 1)))
    fair_prob_at_bet: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(6, 5)))
    ev_per_unit: Decimal = Field(sa_column=Column(Numeric(7, 5), nullable=False))
    strategy: StakingStrategy = Field(sa_column=Column(_STAKING_STRATEGY, nullable=False))
    kelly_multiplier: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(4, 3)))
    stake_units: Decimal = Field(sa_column=Column(Numeric(8, 3), nullable=False))
    bankroll_before: Decimal = Field(sa_column=Column(Numeric(12, 3), nullable=False))
    closing_odds_id: Optional[int] = Field(
        default=None, sa_column=Column(_BIG_ID, ForeignKey("odds_history.id"))
    )
    closing_price: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(8, 4)))
    closing_line: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(5, 1)))
    clv_pct: Optional[Decimal] = Field(
        default=None,
        sa_column=Column(Numeric(7, 5), Computed("price_taken / closing_price - 1", persisted=True)),
    )
    status: BetStatus = Field(
        default=BetStatus.pending,
        sa_column=Column(_BET_STATUS, nullable=False, server_default=text("'pending'")),
    )
    profit_units: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(10, 3)))
    placed_at: Optional[datetime] = Field(
        default=None, sa_column=_timestamptz(server_default=func.now())
    )
    settled_at: Optional[datetime] = Field(default=None, sa_column=_timestamptz())
