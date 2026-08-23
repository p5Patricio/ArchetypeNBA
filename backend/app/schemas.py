from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class SeasonResponse(BaseModel):
    id: int
    season_label: str
    is_active: bool
    players_count: int = 0


class TeamResponse(BaseModel):
    id: int
    abbreviation: str
    full_name: str
    city: str
    conference: str
    division: str
    players: int


class PlayerSummary(BaseModel):
    id: int
    full_name: str
    team_abbreviation: Optional[str]


class PlayerSeasonSummary(BaseModel):
    player_id: int
    player_name: str
    team_abbreviation: Optional[str] = None
    team_name: Optional[str] = None
    cluster_id: Optional[int] = None
    role_name: Optional[str] = None
    pts: Optional[float] = 0.0
    reb: Optional[float] = 0.0
    ast: Optional[float] = 0.0
    stl: Optional[float] = 0.0
    blk: Optional[float] = 0.0
    fg3m: Optional[float] = 0.0
    fg_pct: Optional[float] = 0.0
    min: Optional[float] = 0.0
    gp: Optional[int] = 0
    headshot_url: Optional[str] = None


class StatDelta(BaseModel):
    stat: str
    player_value: float
    cluster_avg: float
    diff: float
    percent_diff: float


class PlayerAnalysisResponse(BaseModel):
    player_name: str
    team: Optional[str] = None
    cluster_id: Optional[int] = None
    role_name: Optional[str] = None
    role_breakdown: Optional[List[Dict[str, Any]]] = None
    comparison: List[StatDelta] = []
    player_stats: Optional[Dict[str, Any]] = None
    cluster_mean: Optional[Dict[str, Any]] = None


class PlayerRadarsResponse(BaseModel):
    player_name: str
    seasons: List[Dict[str, Any]]


class ClusterInitResponse(BaseModel):
    season_id: int
    k: int
    players: int
    clusters: int
    roles: Dict[int, str]


class PlayerShot(BaseModel):
    x: float
    y: float
    made: bool
    action_type: Optional[str] = None
    shot_zone_basic: Optional[str] = None
    shot_distance: Optional[float] = None


class PlayerShotsResponse(BaseModel):
    season: str
    season_type: str
    attempts: int
    makes: int
    shots: List[PlayerShot]


class PlayerGameLogItem(BaseModel):
    game_id: str
    game_date: Optional[str]
    matchup: Optional[str]
    wl: Optional[str]
    min: int
    pts: int
    reb: int
    ast: int
    stl: int
    blk: int
    plus_minus: int


class PlayerGameLogsResponse(BaseModel):
    player_name: str
    season_id: int
    games: List[PlayerGameLogItem]


class HistoricalPlayerShotsResponse(BaseModel):
    player_name: str
    season_id: int
    attempts: int
    makes: int
    shots: List[PlayerShot]


class PlayerAdvancedStatsResponse(BaseModel):
    player_name: str
    season_id: int
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


class SimilarPlayerItem(BaseModel):
    player_id: int
    player_name: str
    similarity_score: float


class PlayerSimilaritiesResponse(BaseModel):
    player_name: str
    season_id: int
    players: List[SimilarPlayerItem]


class TeamEloItem(BaseModel):
    game_id: Optional[str]
    game_date: Optional[str]
    opponent_team_id: Optional[int]
    rating_before: float
    rating_after: float
    result: Optional[str]
    win_probability: Optional[float]


class TeamEloResponse(BaseModel):
    team_abbreviation: str
    season_id: int
    timeline: List[TeamEloItem]


class PlayerProfileResponse(BaseModel):
    player_id: int
    full_name: str
    team_id: Optional[int]
    team_abbreviation: Optional[str]
    team_name: Optional[str]
    height: Optional[str]
    weight: Optional[str]
    height_cm: Optional[float]
    weight_kg: Optional[float]
    birthdate: Optional[str]
    age: Optional[float]
    headshot_url: Optional[str]


class HealthResponse(BaseModel):
    status: str
    db_connected: bool


class DataUpdateResponse(BaseModel):
    season: str
    file: Optional[str] = None
    rows_processed: int = 0
    players_inserted: int = 0
    players_updated: int = 0
    players_failed: int = 0
    etl_status: str


class DataUpdateRequest(BaseModel):
    season: str
    season_type: str = "Regular Season"
    min_minutes: int = 100
    filepath: Optional[str] = None


# ============================================================================
# Versus & 1v1 Matchup Schemas
# ============================================================================

class VersusSeasonOption(BaseModel):
    season_id: int
    season_label: str
    team_abbreviation: str
    gp: int
    pts_pg: float
    reb_pg: float
    ast_pg: float
    per: Optional[float] = None
    bpm: Optional[float] = None
    ts_pct: Optional[float] = None
    is_best_season: bool = False
    peak_score: float = 0.0


class VersusPlayerOption(BaseModel):
    player_id: int
    player_name: str
    team_abbreviation: str
    position: Optional[str] = None
    height: Optional[str] = None
    weight: Optional[str] = None
    headshot_url: str
    best_season_id: int
    best_season_label: str
    seasons: List[VersusSeasonOption]


class VersusAccolades(BaseModel):
    championships: int = 0
    mvp_count: int = 0
    finals_mvp_count: int = 0
    dpoy_count: int = 0
    all_nba_count: int = 0
    all_star_count: int = 0
    scoring_titles: int = 0
    olympic_medals: List[str] = []
    fiba_accolades: List[str] = []
    is_hall_of_fame: bool = False


class VersusPlayerStats(BaseModel):
    # Per-game traditional
    gp: int = 0
    min_pg: float = 0.0
    pts_pg: float = 0.0
    reb_pg: float = 0.0
    ast_pg: float = 0.0
    stl_pg: float = 0.0
    blk_pg: float = 0.0
    fg3m_pg: float = 0.0
    fg_pct: float = 0.0
    fg3_pct: float = 0.0
    ft_pct: float = 0.0
    oreb_pg: float = 0.0
    dreb_pg: float = 0.0
    tov_pg: float = 0.0
    pf_pg: float = 0.0
    # Advanced
    ts_pct: Optional[float] = None
    usg_pct: Optional[float] = None
    per: Optional[float] = None
    bpm: Optional[float] = None
    obpm: Optional[float] = None
    dbpm: Optional[float] = None
    vorp: Optional[float] = None
    ws: Optional[float] = None
    ws_per_48: Optional[float] = None


class VersusPlayerCard(BaseModel):
    player_id: int
    player_name: str
    team_abbreviation: str
    team_name: Optional[str] = None
    position: Optional[str] = None
    height: Optional[str] = None
    height_cm: Optional[float] = None
    weight: Optional[str] = None
    weight_kg: Optional[float] = None
    headshot_url: str
    archetype_id: int = 3
    archetype_es: str
    archetype_en: str
    archetype_color: str
    selected_season_id: int
    selected_season_label: str
    is_best_season: bool = False
    stats: VersusPlayerStats
    accolades: VersusAccolades
    available_seasons: List[VersusSeasonOption]


class VersusStatComparisonItem(BaseModel):
    category_key: str
    label_es: str
    label_en: str
    p1_value: float
    p2_value: float
    format_type: str  # "float1", "percent", "integer", "float3"
    higher_is_better: bool = True
    leader: int  # 1 for p1, 2 for p2, 0 for tie
    diff: float


class VersusDimensionRating(BaseModel):
    key: str
    name_es: str
    name_en: str
    description_es: str
    description_en: str
    p1_score: float  # 0 to 100
    p2_score: float  # 0 to 100
    advantage_player: int  # 1 or 2


class VersusSimulationResult(BaseModel):
    p1_win_prob: float  # e.g. 58.4 (58.4%)
    p2_win_prob: float  # e.g. 41.6
    projected_score_p1: int  # e.g. 21
    projected_score_p2: int  # e.g. 17
    predicted_winner_id: int
    predicted_winner_name: str
    dimensions: List[VersusDimensionRating]
    tactical_summary_es: str
    tactical_summary_en: str
    key_advantages_p1: List[str]
    key_advantages_p2: List[str]
    series_best_of_7_winner: str
    series_score: str  # e.g. "4 - 2"


class VersusMatchupResponse(BaseModel):
    player1: VersusPlayerCard
    player2: VersusPlayerCard
    stat_comparisons: List[VersusStatComparisonItem]
    accolades_comparisons: List[VersusStatComparisonItem]
    simulation: VersusSimulationResult


# ============================================================================
# 5 vs 5 Fantasy Lineup Builder Schemas
# ============================================================================

class LineupSlotRequest(BaseModel):
    position: str  # "PG", "SG", "SF", "PF", "C"
    player_id: int
    season_id: Optional[int] = None


class LineupTeamRequest(BaseModel):
    team_name: str = "Mi Equipo Fantasía"
    slots: List[LineupSlotRequest]


class LineupSlotDetail(BaseModel):
    position: str  # "PG", "SG", "SF", "PF", "C"
    player_id: int
    player_name: str
    headshot_url: str
    position_raw: str
    height_cm: Optional[int] = None
    weight_kg: Optional[int] = None
    team_abbreviation: str
    season_id: int
    season_label: str
    is_best_season: bool = False
    archetype_id: int
    archetype_name_es: str
    archetype_name_en: str
    archetype_color: str
    ppg: float
    rpg: float
    apg: float
    spg: float
    bpg: float
    fg_pct: float
    fg3_pct: float
    ft_pct: float
    ts_pct: float
    per: Optional[float] = None
    bpm: Optional[float] = None
    available_seasons: List[VersusSeasonOption] = []


class LineupTeamMetrics(BaseModel):
    ortg: float  # Projected Offensive Rating
    drtg: float  # Projected Defensive Rating
    net_rating: float
    pace: float
    spacing_score: float  # 0 to 100
    playmaking_score: float  # 0 to 100
    rebounding_score: float  # 0 to 100
    perimeter_defense_score: float  # 0 to 100
    rim_protection_score: float  # 0 to 100
    chemistry_score: float  # 0 to 100
    total_ppg: float
    total_rpg: float
    total_apg: float
    total_rings: int
    total_mvps: int
    total_all_nba: int
    synergy_strengths_es: List[str]
    synergy_strengths_en: List[str]
    synergy_weaknesses_es: List[str]
    synergy_weaknesses_en: List[str]


class LineupTeamEvaluationResponse(BaseModel):
    team_name: str
    slots: List[LineupSlotDetail]
    metrics: LineupTeamMetrics


class LineupPlayerBoxScore(BaseModel):
    player_id: int
    player_name: str
    position: str
    season_label: str
    minutes: int
    pts: int
    reb: int
    ast: int
    stl: int
    blk: int
    fgm: int
    fga: int
    fg_pct: float
    fg3m: int
    fg3a: int
    ftm: int
    fta: int
    plus_minus: int


class Lineup5v5SimulationRequest(BaseModel):
    team1: LineupTeamRequest
    team2: LineupTeamRequest


class Lineup5v5SimulationResponse(BaseModel):
    team1_name: str
    team2_name: str
    team1_slots: List[LineupSlotDetail]
    team2_slots: List[LineupSlotDetail]
    team1_metrics: LineupTeamMetrics
    team2_metrics: LineupTeamMetrics
    team1_score: int
    team2_score: int
    team1_win_prob: float
    team2_win_prob: float
    quarter_scores_t1: List[int]
    quarter_scores_t2: List[int]
    game_mvp_name: str
    game_mvp_stats: str
    team1_boxscore: List[LineupPlayerBoxScore]
    team2_boxscore: List[LineupPlayerBoxScore]
    tactical_summary_es: str
    tactical_summary_en: str
class ClassicPresetLineup(BaseModel):
    id: str
    name: str
    year: str
    era: str
    description_es: str
    description_en: str
    slots: List[LineupSlotRequest]


# ============================================================================
# Phase 3: Positional Analysis & Training Camp Models
# ============================================================================

class DrillRecommendation(BaseModel):
    id: str
    name_es: str
    name_en: str
    category: str  # shooting, playmaking, defense, rebounding, conditioning
    stat_target: str
    intensity: str  # standard, high, elite
    sets_and_reps: str
    description_es: str
    description_en: str
    projected_impact_es: str
    projected_impact_en: str


class StatGapItem(BaseModel):
    stat_key: str
    label_es: str
    label_en: str
    player_value: float
    position_avg: float
    position_median: float
    position_p75: float
    diff: float
    pct_diff: float
    status: str  # elite, strength, average, weakness, critical_deficit
    needs_training: bool


class RoleFulfillment(BaseModel):
    overall_score: float  # 0 to 100
    letter_grade: str  # A+, A, B+, B, C+, C, D
    grade_label_es: str
    grade_label_en: str
    verdict_es: str
    verdict_en: str
    key_strengths_es: List[str]
    key_strengths_en: List[str]
    primary_deficits_es: List[str]
    primary_deficits_en: List[str]
    projected_score: float
    projected_grade: str


class TrainingRegimePlan(BaseModel):
    regime_id: str  # balanced, shooting_focus, defensive_lockdown, playmaking_mastery, athletic_rebounding
    title_es: str
    title_en: str
    description_es: str
    description_en: str
    weekly_frequency: str
    target_focus_es: str
    target_focus_en: str
    drills: List[DrillRecommendation]


class TrainingAnalysisResponse(BaseModel):
    player_id: int
    player_name: str
    team_abbreviation: str
    team_name: str
    headshot_url: str
    position: str
    position_group: str  # Guard, Forward, Center
    archetype_id: int
    archetype_name_es: str
    archetype_name_en: str
    archetype_color: str
    season_id: int
    season_label: str
    total_position_peers: int
    current_stats: Dict[str, float]
    positional_benchmark: Dict[str, float]
    projected_stats: Dict[str, float]
    stat_gaps: List[StatGapItem]
    role_fulfillment: RoleFulfillment
    recommended_drills: List[DrillRecommendation]
    training_regimes: List[TrainingRegimePlan]
    radar_labels: List[str]
    radar_player_values: List[float]
    radar_benchmark_values: List[float]
    radar_projected_values: List[float]



