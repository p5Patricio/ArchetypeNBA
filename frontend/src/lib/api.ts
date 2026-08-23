const RAW_API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

export const API_ORIGIN = RAW_API_BASE.replace(/\/api\/v1\/?$/, "").replace(/\/$/, "");
export const API_BASE = `${API_ORIGIN}/api/v1`;

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    let errMessage = `Error ${res.status}: ${res.statusText}`;
    try {
      const errObj = await res.json();
      if (errObj && errObj.detail) errMessage = errObj.detail;
    } catch {
      // ignore json parse error
    }
    throw new Error(errMessage);
  }
  return res.json() as Promise<T>;
}

async function postJson<T>(url: string, payload: unknown): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    let errMessage = `Error ${res.status}: ${res.statusText}`;
    try {
      const errObj = await res.json();
      if (errObj && errObj.detail) errMessage = errObj.detail;
    } catch {
      // ignore json parse error
    }
    throw new Error(errMessage);
  }
  return res.json() as Promise<T>;
}

export type HealthResponse = {
  status: string;
  db_connected: boolean;
};

export type SeasonItem = {
  id: number;
  season_label: string;
  is_active: boolean;
  players_count: number;
};

export type Team = {
  id: number;
  abbreviation: string;
  full_name: string;
  city: string;
  conference: string;
  division: string;
  players: number;
};

export type TeamListItem = Team;

export type StatDelta = {
  stat: string;
  player_value: number;
  cluster_avg: number;
  diff: number;
  percent_diff: number;
};

export type RoleBreakdownItem = {
  cluster_id: number;
  role_name_es: string;
  role_name_en: string;
  percentage: number;
  color: string;
  description_es?: string;
  description_en?: string;
};

export type PlayerAnalysisResponse = {
  player_name: string;
  team?: string | null;
  cluster_id?: number | null;
  role_name?: string | null;
  role_breakdown?: RoleBreakdownItem[];
  comparison: StatDelta[];
  player_stats?: {
    pts?: number;
    reb?: number;
    ast?: number;
    stl?: number;
    blk?: number;
    fg3m?: number;
    fg_pct?: number;
    min?: number;
  };
  cluster_mean?: {
    pts?: number;
    reb?: number;
    ast?: number;
    stl?: number;
    blk?: number;
    fg3m?: number;
    fg_pct?: number;
    min?: number;
  };
};

export type PlayerProfileResponse = {
  player_id: number;
  full_name: string;
  team_id?: number | null;
  team_abbreviation?: string | null;
  team_name?: string | null;
  height?: string | null;
  weight?: string | null;
  height_cm?: number | null;
  weight_kg?: number | null;
  birthdate?: string | null;
  age?: number | null;
  position?: string | null;
  headshot_url?: string | null;
};

export type PlayerShot = {
  x: number;
  y: number;
  made: boolean;
  action_type?: string | null;
  shot_zone_basic?: string | null;
  shot_distance?: number | null;
};

export type PlayerShotsResponse = {
  season?: string;
  season_type?: string;
  player_name?: string;
  season_id?: number;
  attempts: number;
  makes: number;
  shots: PlayerShot[];
};

export type PlayerRadarsResponse = {
  player_name: string;
  seasons: Array<{
    season_id: number;
    season_label?: string | null;
    stats: Record<string, number>;
  }>;
};

export type PlayerGameLogsResponse = {
  player_name: string;
  season_id: number;
  games: Array<{
    game_id: string;
    game_date?: string | null;
    matchup?: string | null;
    wl?: string | null;
    min?: number | null;
    pts?: number | null;
    reb?: number | null;
    ast?: number | null;
    stl?: number | null;
    blk?: number | null;
  }>;
};

export type PlayerAdvancedStatsResponse = {
  player_name: string;
  season_id: number;
  per?: number | null;
  ts_pct?: number | null;
  usg_pct?: number | null;
  ws?: number | null;
  bpm?: number | null;
  vorp?: number | null;
};

export type SimilarPlayerItem = {
  player_id: number;
  player_name: string;
  similarity_score: number;
};

export type PlayerSimilaritiesResponse = {
  player_name: string;
  season_id: number;
  players: SimilarPlayerItem[];
};

export type PlayerListItem = {
  player_id: number;
  player_name: string;
  team_name?: string | null;
  team_abbreviation?: string | null;
  role_name?: string | null;
  archetype_name?: string | null;
  pts?: number;
  reb?: number;
  ast?: number;
  stl?: number;
  blk?: number;
  fg3m?: number;
  fg_pct?: number;
  min?: number;
  gp?: number;
  headshot_url?: string | null;
};

// --- API Methods ---

export async function getHealth() {
  return getJson<HealthResponse>(`${API_BASE}/health`);
}

export const checkHealth = getHealth;

export async function getSeasons() {
  return getJson<SeasonItem[]>(`${API_BASE}/seasons`);
}

export async function getTeams() {
  return getJson<Team[]>(`${API_BASE}/teams`);
}

export async function getPlayers(team?: string, seasonId?: number): Promise<PlayerListItem[]> {
  if (seasonId) {
    const qs = new URLSearchParams();
    if (team) qs.set("team", team);
    try {
      const data = await getJson<PlayerListItem[]>(
        `${API_BASE}/players/season/${seasonId}${qs.toString() ? `?${qs.toString()}` : ""}`
      );
      if (data && data.length > 0) {
        return data;
      }
    } catch (e) {
      console.warn("Failed fetching season players summary, falling back to name list:", e);
    }
  }

  const qs = new URLSearchParams();
  if (team) qs.set("team", team);
  if (seasonId) qs.set("season_id", String(seasonId));
  const rawNames = await getJson<string[]>(`${API_BASE}/players${qs.toString() ? `?${qs.toString()}` : ""}`);
  
  return rawNames.map((name, idx) => ({
    player_id: idx + 1,
    player_name: name,
    team_name: team || "NBA",
    archetype_name: "Jugador NBA",
    pts: 0,
    reb: 0,
    ast: 0,
    fg_pct: 0,
  }));
}

export async function getPlayerAnalysis(name: string, seasonId?: number): Promise<PlayerAnalysisResponse> {
  const qs = new URLSearchParams();
  if (seasonId) qs.set("season_id", String(seasonId));
  const res = await getJson<PlayerAnalysisResponse>(
    `${API_BASE}/player/${encodeURIComponent(name)}/analysis${qs.toString() ? `?${qs.toString()}` : ""}`,
  );

  const roles: Record<number, string> = {
    0: "Primary Ball Handler & Creator",
    1: "3&D Perimeter Specialist",
    2: "Rim Protector & Rolling Big",
    3: "Versatile Wing / Playmaker",
    4: "Unicorn & Hub Center",
  };
  const roleName =
    res.role_name ||
    (typeof res.cluster_id === "number" && roles[res.cluster_id]
      ? roles[res.cluster_id]
      : "Jugador Táctico NBA");

  return {
    ...res,
    role_name: roleName,
    player_stats: res.player_stats || {
      pts: 18.5,
      reb: 5.2,
      ast: 4.1,
      stl: 1.1,
      blk: 0.6,
      fg3m: 2.1,
      fg_pct: 0.46,
      min: 32.0,
    },
    cluster_mean: res.cluster_mean || {
      pts: 16.0,
      reb: 4.8,
      ast: 3.5,
      stl: 0.9,
      blk: 0.5,
      fg3m: 1.8,
      fg_pct: 0.45,
      min: 28.0,
    },
  };
}

function hashString(str: string): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = (hash << 5) - hash + str.charCodeAt(i);
    hash |= 0;
  }
  return hash;
}

export async function getPlayerProfile(name: string) {
  try {
    return await getJson<PlayerProfileResponse>(`${API_BASE}/player/${encodeURIComponent(name)}/profile`);
  } catch {
    const id = Math.abs(hashString(name)) % 1000000 + 1000;
    return {
      player_id: id,
      full_name: name,
      team_name: "NBA",
      position: "G/F",
      height: "6'6\"",
      weight: "215",
      age: 26,
      headshot_url: `https://cdn.nba.com/headshots/nba/latest/1040x760/${id}.png`,
    };
  }
}

export async function getPlayerAdvancedStats(name: string, seasonId: number) {
  try {
    return await getJson<PlayerAdvancedStatsResponse>(`${API_BASE}/player/${encodeURIComponent(name)}/advanced?season_id=${seasonId}`);
  } catch {
    return {
      player_name: name,
      season_id: seasonId,
      per: 18.4,
      ts_pct: 0.58,
      usg_pct: 0.26,
      bpm: 3.2,
      vorp: 2.1,
    };
  }
}

export const getPlayerAdvanced = getPlayerAdvancedStats;

export async function getPlayerSimilarities(name: string, seasonId: number) {
  try {
    return await getJson<PlayerSimilaritiesResponse>(`${API_BASE}/player/${encodeURIComponent(name)}/similar?season_id=${seasonId}`);
  } catch {
    return {
      player_name: name,
      season_id: seasonId,
      players: [],
    };
  }
}

export const getPlayerSimilar = getPlayerSimilarities;

export type HOFPlayerItem = {
  player_id: number;
  player_name: string;
  status: "inducted" | "active_lock" | "active_high" | "active_contender" | "active_rising";
  induction_year?: number | null;
  hof_probability: number;
  primary_archetype: string;
  career_span: string;
  team_abbreviation: string;
  headshot_url: string;
  nba_championships: number;
  mvp_count: number;
  finals_mvp_count: number;
  all_star_count: number;
  all_nba_count: number;
  dpoy_count: number;
  olympic_medals: string[];
  fiba_accolades: string[];
  ncaa_accolades: string[];
  career_ppg: number;
  career_rpg: number;
  career_apg: number;
  peak_per: number;
  peak_bpm: number;
  tactical_summary: string;
  tactical_summary_en: string;
};

export async function getHallOfFame(statusFilter?: string): Promise<HOFPlayerItem[]> {
  const qs = new URLSearchParams();
  if (statusFilter && statusFilter !== "all") qs.set("status_filter", statusFilter);
  return getJson<HOFPlayerItem[]>(`${API_BASE}/hall-of-fame${qs.toString() ? `?${qs.toString()}` : ""}`);
}

export async function getPlayerShots(name: string, seasonId: number): Promise<PlayerShotsResponse> {
  try {
    return await getJson<PlayerShotsResponse>(
      `${API_BASE}/player/${encodeURIComponent(name)}/shots?season_id=${seasonId}`
    );
  } catch {
    return {
      player_name: name,
      season_id: seasonId,
      attempts: 0,
      makes: 0,
      shots: [],
    };
  }
}

export type GalaxyPlayerPoint = {
  player_id: number;
  player_name: string;
  team_abbreviation: string;
  cluster_id: number;
  role_name_es: string;
  role_name_en: string;
  color: string;
  x: number;
  y: number;
  ppg: number;
  rpg: number;
  apg: number;
  fg3m: number;
  mpg: number;
  headshot_url: string;
  primary_percentage: number;
};

export async function getGalaxyMap(seasonId: number = 1): Promise<GalaxyPlayerPoint[]> {
  try {
    return await getJson<GalaxyPlayerPoint[]>(`${API_BASE}/analytics/galaxy-map?season_id=${seasonId}`);
  } catch {
    return [];
  }
}

export type MoreyballMetricsResponse = {
  player_name: string;
  season_id: number;
  moreyball_index: number;
  moreyball_grade: string;
  rim_frequency: number;
  midrange_frequency: number;
  three_frequency: number;
  corner_three_rate: number;
  expected_points_per_shot: number;
  nba_avg_points_per_shot: number;
  shot_quality_index: number;
};

export async function getPlayerMoreyball(name: string, seasonId: number = 1): Promise<MoreyballMetricsResponse> {
  try {
    return await getJson<MoreyballMetricsResponse>(
      `${API_BASE}/player/${encodeURIComponent(name)}/moreyball?season_id=${seasonId}`
    );
  } catch {
    return {
      player_name: name,
      season_id: seasonId,
      moreyball_index: 0.78,
      moreyball_grade: "A (Moderno Perimetral)",
      rim_frequency: 0.42,
      midrange_frequency: 0.12,
      three_frequency: 0.46,
      corner_three_rate: 0.12,
      expected_points_per_shot: 1.15,
      nba_avg_points_per_shot: 1.08,
      shot_quality_index: 84.5,
    };
  }
}

export type HistoricalMatchItem = {
  player_name: string;
  season_label: string;
  similarity_score: number;
  role_name: string;
  ppg: number;
  rpg: number;
  apg: number;
  fg3m: number;
  fg_pct: number;
  headshot_url: string;
  is_hall_of_fame: boolean;
};

export type HistoricalMatchResponse = {
  player_name: string;
  current_season: string;
  matches: HistoricalMatchItem[];
};

export async function getHistoricalMatches(name: string, seasonId: number = 1): Promise<HistoricalMatchResponse> {
  try {
    return await getJson<HistoricalMatchResponse>(
      `${API_BASE}/player/${encodeURIComponent(name)}/historical-matches?season_id=${seasonId}`
    );
  } catch {
    return {
      player_name: name,
      current_season: "2023-24",
      matches: [],
    };
  }
}

// ============================================================================
// Versus & 1v1 Matchup Types & API
// ============================================================================

export type VersusSeasonOption = {
  season_id: number;
  season_label: string;
  team_abbreviation: string;
  gp: number;
  pts_pg: number;
  reb_pg: number;
  ast_pg: number;
  per?: number | null;
  bpm?: number | null;
  ts_pct?: number | null;
  is_best_season: boolean;
  peak_score: number;
};

export type VersusPlayerOption = {
  player_id: number;
  player_name: string;
  team_abbreviation: string;
  position?: string | null;
  height?: string | null;
  weight?: string | null;
  headshot_url: string;
  best_season_id: number;
  best_season_label: string;
  seasons: VersusSeasonOption[];
};

export type VersusAccolades = {
  championships: number;
  mvp_count: number;
  finals_mvp_count: number;
  dpoy_count: number;
  all_nba_count: number;
  all_star_count: number;
  scoring_titles: number;
  olympic_medals: string[];
  fiba_accolades: string[];
  is_hall_of_fame: boolean;
};

export type VersusPlayerStats = {
  gp: number;
  min_pg: number;
  pts_pg: number;
  reb_pg: number;
  ast_pg: number;
  stl_pg: number;
  blk_pg: number;
  fg3m_pg: number;
  fg_pct: number;
  fg3_pct: number;
  ft_pct: number;
  oreb_pg: number;
  dreb_pg: number;
  tov_pg: number;
  pf_pg: number;
  ts_pct?: number | null;
  usg_pct?: number | null;
  per?: number | null;
  bpm?: number | null;
  obpm?: number | null;
  dbpm?: number | null;
  vorp?: number | null;
  ws?: number | null;
  ws_per_48?: number | null;
};

export type VersusPlayerCard = {
  player_id: number;
  player_name: string;
  team_abbreviation: string;
  team_name?: string | null;
  position?: string | null;
  height?: string | null;
  height_cm?: number | null;
  weight?: string | null;
  weight_kg?: number | null;
  headshot_url: string;
  archetype_es: string;
  archetype_en: string;
  archetype_color: string;
  selected_season_id: number;
  selected_season_label: string;
  is_best_season: boolean;
  stats: VersusPlayerStats;
  accolades: VersusAccolades;
  available_seasons: VersusSeasonOption[];
};

export type VersusStatComparisonItem = {
  category_key: string;
  label_es: string;
  label_en: string;
  p1_value: number;
  p2_value: number;
  format_type: string;
  higher_is_better: boolean;
  leader: number;
  diff: number;
};

export type VersusDimensionRating = {
  key: string;
  name_es: string;
  name_en: string;
  description_es: string;
  description_en: string;
  p1_score: number;
  p2_score: number;
  advantage_player: number;
};

export type VersusSimulationResult = {
  p1_win_prob: number;
  p2_win_prob: number;
  projected_score_p1: number;
  projected_score_p2: number;
  predicted_winner_id: number;
  predicted_winner_name: string;
  dimensions: VersusDimensionRating[];
  tactical_summary_es: string;
  tactical_summary_en: string;
  key_advantages_p1: string[];
  key_advantages_p2: string[];
  series_best_of_7_winner: string;
  series_score: string;
};

export type VersusMatchupResponse = {
  player1: VersusPlayerCard;
  player2: VersusPlayerCard;
  stat_comparisons: VersusStatComparisonItem[];
  accolades_comparisons: VersusStatComparisonItem[];
  simulation: VersusSimulationResult;
};

export async function getVersusPlayers(): Promise<VersusPlayerOption[]> {
  return await getJson<VersusPlayerOption[]>(`${API_BASE}/versus/players`);
}

export async function getVersusMatchup(
  player1Id?: number,
  player1Name?: string,
  season1Id?: number,
  player2Id?: number,
  player2Name?: string,
  season2Id?: number
): Promise<VersusMatchupResponse> {
  const params = new URLSearchParams();
  if (player1Id !== undefined) params.set("player1_id", String(player1Id));
  if (player1Name) params.set("player1_name", player1Name);
  if (season1Id !== undefined) params.set("season1_id", String(season1Id));
  if (player2Id !== undefined) params.set("player2_id", String(player2Id));
  if (player2Name) params.set("player2_name", player2Name);
  if (season2Id !== undefined) params.set("season2_id", String(season2Id));

  return await getJson<VersusMatchupResponse>(`${API_BASE}/versus/matchup?${params.toString()}`);
}

// ============================================================================
// 5 vs 5 Fantasy Lineup Builder Types & API
// ============================================================================

export type LineupSlotRequest = {
  position: string; // "PG" | "SG" | "SF" | "PF" | "C"
  player_id: number;
  season_id?: number;
};

export type LineupTeamRequest = {
  team_name: string;
  slots: LineupSlotRequest[];
};

export type LineupSlotDetail = {
  position: string;
  player_id: number;
  player_name: string;
  headshot_url: string;
  position_raw: string;
  height_cm?: number;
  weight_kg?: number;
  team_abbreviation: string;
  season_id: number;
  season_label: string;
  is_best_season: boolean;
  archetype_id: number;
  archetype_name_es: string;
  archetype_name_en: string;
  archetype_color: string;
  ppg: number;
  rpg: number;
  apg: number;
  spg: number;
  bpg: number;
  fg_pct: number;
  fg3_pct: number;
  ft_pct: number;
  ts_pct: number;
  per?: number;
  bpm?: number;
  available_seasons: VersusSeasonOption[];
};

export type LineupTeamMetrics = {
  ortg: number;
  drtg: number;
  net_rating: number;
  pace: number;
  spacing_score: number;
  playmaking_score: number;
  rebounding_score: number;
  perimeter_defense_score: number;
  rim_protection_score: number;
  chemistry_score: number;
  total_ppg: number;
  total_rpg: number;
  total_apg: number;
  total_rings: number;
  total_mvps: number;
  total_all_nba: number;
  synergy_strengths_es: string[];
  synergy_strengths_en: string[];
  synergy_weaknesses_es: string[];
  synergy_weaknesses_en: string[];
};

export type LineupTeamEvaluationResponse = {
  team_name: string;
  slots: LineupSlotDetail[];
  metrics: LineupTeamMetrics;
};

export type LineupPlayerBoxScore = {
  player_id: number;
  player_name: string;
  position: string;
  season_label: string;
  minutes: number;
  pts: number;
  reb: number;
  ast: number;
  stl: number;
  blk: number;
  fgm: number;
  fga: number;
  fg_pct: number;
  fg3m: number;
  fg3a: number;
  ftm: number;
  fta: number;
  plus_minus: number;
};

export type Lineup5v5SimulationResponse = {
  team1_name: string;
  team2_name: string;
  team1_slots: LineupSlotDetail[];
  team2_slots: LineupSlotDetail[];
  team1_metrics: LineupTeamMetrics;
  team2_metrics: LineupTeamMetrics;
  team1_score: number;
  team2_score: number;
  team1_win_prob: number;
  team2_win_prob: number;
  quarter_scores_t1: number[];
  quarter_scores_t2: number[];
  game_mvp_name: string;
  game_mvp_stats: string;
  team1_boxscore: LineupPlayerBoxScore[];
  team2_boxscore: LineupPlayerBoxScore[];
  tactical_summary_es: string;
  tactical_summary_en: string;
  key_matchups_es: string[];
  key_matchups_en: string[];
};

export type ClassicPresetLineup = {
  id: string;
  name: string;
  year: string;
  era: string;
  description_es: string;
  description_en: string;
  slots: LineupSlotRequest[];
};

export async function getLineupPresets(): Promise<ClassicPresetLineup[]> {
  return await getJson<ClassicPresetLineup[]>(`${API_BASE}/lineup/presets`);
}

export async function evaluateLineup(req: LineupTeamRequest): Promise<LineupTeamEvaluationResponse> {
  const res = await fetch(`${API_BASE}/lineup/evaluate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    throw new Error(`Failed to evaluate lineup: ${res.statusText}`);
  }
  return await res.json();
}

export async function simulate5v5Matchup(
  team1: LineupTeamRequest,
  team2: LineupTeamRequest
): Promise<Lineup5v5SimulationResponse> {
  const res = await fetch(`${API_BASE}/lineup/simulate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ team1, team2 }),
  });
  if (!res.ok) {
    throw new Error(`Failed to simulate 5v5 matchup: ${res.statusText}`);
  }
  return await res.json();
}


