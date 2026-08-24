from typing import Optional, List, Dict, Any
from datetime import date
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint, Index
from sqlalchemy import Column, JSON


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

