"use client";

import React, { useEffect, useState, useCallback, useMemo } from "react";
import { Navbar } from "@/components/Navbar";
import { CommandPalette } from "@/components/CommandPalette";
import { TeamLogo } from "@/components/TeamLogo";
import { usePreferences } from "@/context/PreferencesContext";
import {
  getWeek,
  type WeekGameItem,
  type SideMarketView,
  type TeamInjuryEntry,
} from "@/lib/api";
import {
  Calendar,
  CalendarDays,
  Clock,
  AlertCircle,
  AlertTriangle,
  RefreshCw,
  Search,
  CheckCircle2,
  XCircle,
  Activity,
  ChevronDown,
  ChevronUp,
  Info,
  ShieldAlert,
  Percent,
  Sparkles,
} from "lucide-react";

export default function WeekViewPage() {
  const { language } = usePreferences();
  const isEs = language === "es";

  // Data states
  const [games, setGames] = useState<WeekGameItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string>("");

  // Filters
  const [days, setDays] = useState<number>(7);
  const [selectedDay, setSelectedDay] = useState<string>("all");
  const [teamSearch, setTeamSearch] = useState<string>("");
  const [onlyCandidates, setOnlyCandidates] = useState<boolean>(false);

  // Command palette state
  const [isCommandOpen, setIsCommandOpen] = useState(false);

  // Expanded drawers per game (gameId -> { home: boolean, away: boolean, challengers: boolean })
  const [expandedState, setExpandedState] = useState<
    Record<number, { home?: boolean; away?: boolean; challengers?: boolean }>
  >({});

  const formatUpdateTime = useCallback(
    (date: Date) => {
      return date.toLocaleTimeString(isEs ? "es-MX" : "en-US", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
    },
    [isEs]
  );

  const fetchWeekData = useCallback(
    async (isRefresh = false) => {
      if (isRefresh) setRefreshing(true);
      else setLoading(true);
      setError(null);

      try {
        const data = await getWeek(days);
        setGames(data);
        setLastUpdated(formatUpdateTime(new Date()));
      } catch (err: unknown) {
        console.error("Error fetching week data:", err);
        setError(
          err instanceof Error
            ? err.message
            : isEs
            ? "No se pudo cargar la vista semanal."
            : "Failed to load week view."
        );
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [days, isEs, formatUpdateTime]
  );

  useEffect(() => {
    fetchWeekData();
  }, [fetchWeekData]);

  // Toggle drawer helpers
  const toggleDrawer = (gameId: number, type: "home" | "away" | "challengers") => {
    setExpandedState((prev) => {
      const current = prev[gameId] || {};
      return {
        ...prev,
        [gameId]: {
          ...current,
          [type]: !current[type],
        },
      };
    });
  };

  // Extract injury metadata from the first game that has it
  const injuryMeta = useMemo(() => {
    if (games.length === 0) return null;
    const firstWithMeta = games.find((g) => g.injury_snapshot_timestamp != null);
    if (!firstWithMeta) {
      return {
        timestamp: games[0].home_team.injuries.snapshot_timestamp,
        isStale: games[0].home_team.injuries.stale,
      };
    }
    return {
      timestamp: firstWithMeta.injury_snapshot_timestamp,
      isStale: firstWithMeta.injury_snapshot_stale,
    };
  }, [games]);

  // Unique days list
  const availableDays = useMemo(() => {
    const map = new Map<string, { en: string; es: string; date: string }>();
    for (const g of games) {
      if (!map.has(g.local_date)) {
        map.set(g.local_date, {
          date: g.local_date,
          en: g.day_name,
          es: g.day_name_es,
        });
      }
    }
    return Array.from(map.values()).sort((a, b) => a.date.localeCompare(b.date));
  }, [games]);

  // Filtered games
  const filteredGames = useMemo(() => {
    return games.filter((g) => {
      // Day filter
      if (selectedDay !== "all" && g.local_date !== selectedDay) {
        return false;
      }

      // Team filter
      if (teamSearch.trim()) {
        const query = teamSearch.toLowerCase().trim();
        const homeMatch =
          g.home_team.name.toLowerCase().includes(query) ||
          g.home_team.abbreviation.toLowerCase().includes(query);
        const awayMatch =
          g.away_team.name.toLowerCase().includes(query) ||
          g.away_team.abbreviation.toLowerCase().includes(query);
        if (!homeMatch && !awayMatch) {
          return false;
        }
      }

      // Candidate-only filter
      if (onlyCandidates) {
        const hasCandidate =
          g.home_market.would_qualify || g.away_market.would_qualify;
        if (!hasCandidate) {
          return false;
        }
      }

      return true;
    });
  }, [games, selectedDay, teamSearch, onlyCandidates]);

  // Group filtered games by day
  const groupedByDay = useMemo(() => {
    const groups: Record<string, WeekGameItem[]> = {};
    for (const g of filteredGames) {
      if (!groups[g.local_date]) {
        groups[g.local_date] = [];
      }
      groups[g.local_date].push(g);
    }
    return groups;
  }, [filteredGames]);

  // Format plain language reasons
  const formatReason = (reason: string): string => {
    switch (reason) {
      case "ok":
        return isEs ? "Candidato elegible (+EV)" : "Candidate eligible (+EV)";
      case "edge_below_min":
        return isEs ? "Ventaja del modelo < 2 pp" : "Model edge < 2 pp";
      case "ev_below_min":
        return isEs ? "Valor esperado < 2%" : "Expected value < 2%";
      case "no_sharp_reference":
        return isEs ? "Sin línea Pinnacle de referencia" : "No Pinnacle sharp line";
      case "no_quotes":
        return isEs ? "Sin cuotas disponibles" : "No quotes available";
      case "game_started":
        return isEs ? "Partido ya iniciado" : "Game already tipped off";
      case "missing_ratings":
        return isEs ? "Faltan ratings de equipo" : "Missing team ratings";
      case "invalid_input":
        return isEs ? "Parámetros inválidos" : "Invalid parameters";
      default:
        return reason;
    }
  };

  // Format quote age
  const formatQuoteAge = (minutes: number | null | undefined): string => {
    if (minutes == null) return "";
    if (minutes < 60) return `${Math.round(minutes)}m`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `${hours}h`;
    const days = Math.round(hours / 24);
    return `${days}d`;
  };

  return (
    <div className="min-h-screen bg-[#F8FAFC] text-slate-900 selection:bg-orange-100 selection:text-orange-900">
      <Navbar onOpenSearch={() => setIsCommandOpen(true)} />
      <CommandPalette isOpen={isCommandOpen} onClose={() => setIsCommandOpen(false)} />

      {/* Main Container offset for desktop sidebar */}
      <main className="md:pl-64">
        {/* ========================================================================= */}
        {/* HERO SECTION */}
        {/* ========================================================================= */}
        <section className="relative border-b border-slate-200 bg-gradient-to-b from-blue-50/40 via-white to-white py-8 lg:py-12 shadow-2xs">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
              <div className="space-y-3">
                {/* Pill Badge */}
                <div className="inline-flex items-center gap-2 rounded-full border border-blue-200 bg-blue-50 px-3.5 py-1 text-xs font-black text-blue-800 shadow-2xs">
                  <CalendarDays className="h-3.5 w-3.5 text-blue-600" />
                  <span>
                    {isEs
                      ? "VISTA SEMANAL • PREDICCIONES & PAPER TRADING"
                      : "WEEKLY VIEW • PREDICTIONS & PAPER TRADING"}
                  </span>
                </div>

                {/* Headline */}
                <h1 className="text-3xl sm:text-4xl font-black tracking-tight text-slate-900">
                  {isEs ? "Semana NBA: Predicciones & Bajas" : "NBA Week: Predictions & Injuries"}
                </h1>
                <p className="max-w-2xl text-sm sm:text-base text-slate-600">
                  {isEs
                    ? "Proyecciones bajo demanda del campeón Elo y retadores, cuotas de mercado de Pinnacle, line shopping y reporte oficial de lesiones para los próximos 7 a 14 días."
                    : "On-demand Elo champion and challenger projections, Pinnacle market fair lines, line shopping, and official injury reports for the next 7 to 14 days."}
                </p>
              </div>

              {/* Actions & Refresh */}
              <div className="flex flex-wrap items-center gap-3">
                {lastUpdated && (
                  <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-500">
                    <Clock className="h-3.5 w-3.5" />
                    <span>{lastUpdated}</span>
                  </div>
                )}
                <button
                  type="button"
                  onClick={() => fetchWeekData(true)}
                  disabled={refreshing || loading}
                  aria-label={isEs ? "Actualizar datos semanales" : "Refresh week data"}
                  className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-2 text-xs font-bold text-slate-700 shadow-2xs transition hover:bg-slate-50 hover:text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
                >
                  <RefreshCw
                    className={`h-3.5 w-3.5 text-slate-500 ${refreshing ? "animate-spin" : ""}`}
                  />
                  <span>{refreshing ? (isEs ? "Cargando..." : "Refreshing...") : isEs ? "Actualizar" : "Refresh"}</span>
                </button>
              </div>
            </div>

            {/* Injury Report Status & Age Warning Banner */}
            <div className="mt-6 flex flex-wrap items-center gap-3">
              {injuryMeta?.timestamp ? (
                <div
                  className={`inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs font-semibold shadow-2xs ${
                    injuryMeta.isStale
                      ? "border-amber-300 bg-amber-50 text-amber-900"
                      : "border-emerald-200 bg-emerald-50 text-emerald-900"
                  }`}
                >
                  {injuryMeta.isStale ? (
                    <AlertTriangle className="h-4 w-4 text-amber-600" />
                  ) : (
                    <Activity className="h-4 w-4 text-emerald-600" />
                  )}
                  <span>
                    {isEs ? "Reporte de Lesiones: " : "Injury Report: "}
                    {new Date(injuryMeta.timestamp).toLocaleString(isEs ? "es-MX" : "en-US", {
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                    {injuryMeta.isStale && (
                      <span className="ml-1 font-bold text-amber-700">
                        {isEs ? "(Desactualizado > 36h)" : "(Stale > 36h)"}
                      </span>
                    )}
                  </span>
                </div>
              ) : (
                <div className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-600">
                  <AlertCircle className="h-4 w-4 text-slate-400" />
                  <span>{isEs ? "Sin reporte de lesiones cargado" : "No injury report available"}</span>
                </div>
              )}

              {/* Informative Note Badge */}
              <div className="inline-flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50/70 px-3 py-1.5 text-xs text-blue-950 shadow-2xs">
                <Info className="h-4 w-4 text-blue-600 shrink-0" />
                <span>
                  {isEs
                    ? "Análisis paper trading: Las cuotas de juegos a días futuros son capturas de apertura y se moverán al acercarse el partido."
                    : "Paper trading analysis: Odds for games days away reflect earlier captures and will move as tip-off approaches."}
                </span>
              </div>
            </div>
          </div>
        </section>

        {/* ========================================================================= */}
        {/* CONTROLS & FILTER BAR */}
        {/* ========================================================================= */}
        <div className="border-b border-slate-200 bg-white">
          <div className="mx-auto max-w-7xl px-4 py-4 sm:px-6 lg:px-8 space-y-4">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
              {/* Left: Days selector & Candidate Toggle */}
              <div className="flex flex-wrap items-center gap-3">
                {/* Window Range Selector */}
                <div className="inline-flex rounded-xl border border-slate-200 bg-slate-50 p-1">
                  {[7, 10, 14].map((d) => (
                    <button
                      key={d}
                      type="button"
                      onClick={() => setDays(d)}
                      className={`rounded-lg px-3 py-1 text-xs font-bold transition ${
                        days === d
                          ? "bg-white text-blue-700 shadow-2xs"
                          : "text-slate-600 hover:text-slate-900"
                      }`}
                    >
                      {d} {isEs ? "días" : "days"}
                    </button>
                  ))}
                </div>

                {/* Candidate Only Checkbox Button */}
                <button
                  type="button"
                  onClick={() => setOnlyCandidates(!onlyCandidates)}
                  aria-pressed={onlyCandidates}
                  className={`inline-flex items-center gap-2 rounded-xl border px-3 py-1.5 text-xs font-bold transition ${
                    onlyCandidates
                      ? "border-emerald-300 bg-emerald-50 text-emerald-800"
                      : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                  }`}
                >
                  <Sparkles
                    className={`h-3.5 w-3.5 ${
                      onlyCandidates ? "text-emerald-600" : "text-slate-400"
                    }`}
                  />
                  <span>
                    {isEs ? "Solo Candidatos Paper Bet" : "Candidate Paper Bets Only"}
                  </span>
                </button>
              </div>

              {/* Right: Team search input */}
              <div className="relative w-full md:w-64">
                <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
                <input
                  type="text"
                  value={teamSearch}
                  onChange={(e) => setTeamSearch(e.target.value)}
                  placeholder={isEs ? "Filtrar por equipo..." : "Filter by team..."}
                  aria-label={isEs ? "Buscar equipo" : "Search team"}
                  className="w-full rounded-xl border border-slate-200 bg-white py-1.5 pl-9 pr-3 text-xs text-slate-900 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
            </div>

            {/* Day Filter Chips */}
            {availableDays.length > 0 && (
              <div className="flex items-center gap-1.5 overflow-x-auto pb-1 scrollbar-none">
                <button
                  type="button"
                  onClick={() => setSelectedDay("all")}
                  className={`shrink-0 rounded-lg px-3 py-1 text-xs font-semibold transition ${
                    selectedDay === "all"
                      ? "bg-slate-900 text-white"
                      : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                  }`}
                >
                  {isEs ? "Todos los días" : "All days"}
                </button>
                {availableDays.map((d) => (
                  <button
                    key={d.date}
                    type="button"
                    onClick={() => setSelectedDay(d.date)}
                    className={`shrink-0 rounded-lg px-3 py-1 text-xs font-semibold transition ${
                      selectedDay === d.date
                        ? "bg-blue-600 text-white"
                        : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                    }`}
                  >
                    <span>{isEs ? d.es : d.en}</span>
                    <span className="ml-1 opacity-70">
                      {d.date.substring(5)}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ========================================================================= */}
        {/* MAIN CONTENT AREA */}
        {/* ========================================================================= */}
        <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
          {/* Error State */}
          {error && (
            <div className="rounded-2xl border border-rose-200 bg-rose-50 p-6 text-center space-y-3">
              <AlertCircle className="mx-auto h-8 w-8 text-rose-500" />
              <p className="text-sm font-bold text-rose-800">{error}</p>
              <button
                type="button"
                onClick={() => fetchWeekData()}
                className="rounded-xl bg-rose-600 px-4 py-2 text-xs font-bold text-white shadow-2xs hover:bg-rose-700"
              >
                {isEs ? "Reintentar" : "Retry"}
              </button>
            </div>
          )}

          {/* Loading Skeletons */}
          {loading && !error && (
            <div className="space-y-8 animate-pulse">
              {[1, 2].map((s) => (
                <div key={s} className="space-y-4">
                  <div className="h-6 w-48 bg-slate-200 rounded-md" />
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    {[1, 2].map((c) => (
                      <div
                        key={c}
                        className="h-80 bg-slate-100 border border-slate-200 rounded-2xl p-6"
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Empty State */}
          {!loading && !error && Object.keys(groupedByDay).length === 0 && (
            <div className="rounded-2xl border border-slate-200 bg-white p-12 text-center shadow-2xs space-y-4">
              <Calendar className="mx-auto h-12 w-12 text-slate-300" />
              <h3 className="text-lg font-bold text-slate-800">
                {isEs ? "No se encontraron partidos" : "No scheduled games found"}
              </h3>
              <p className="max-w-md mx-auto text-xs text-slate-500">
                {isEs
                  ? "No hay juegos programados que coincidan con los filtros seleccionados para este período."
                  : "There are no scheduled games matching the selected filters for this time window."}
              </p>
              {(teamSearch || selectedDay !== "all" || onlyCandidates) && (
                <button
                  type="button"
                  onClick={() => {
                    setTeamSearch("");
                    setSelectedDay("all");
                    setOnlyCandidates(false);
                  }}
                  className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-xs font-bold text-slate-700 hover:bg-slate-50"
                >
                  {isEs ? "Limpiar filtros" : "Clear filters"}
                </button>
              )}
            </div>
          )}

          {/* Render Days as Sections */}
          {!loading &&
            !error &&
            Object.entries(groupedByDay).map(([dayDate, dayGames]) => {
              const dayNameEn = dayGames[0]?.day_name || "";
              const dayNameEs = dayGames[0]?.day_name_es || "";

              return (
                <section key={dayDate} className="mb-10 space-y-4">
                  {/* Day Header */}
                  <div className="flex items-center justify-between border-b border-slate-200 pb-3">
                    <div className="flex items-center gap-3">
                      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-100 text-blue-700 font-bold">
                        <Calendar className="h-4 w-4" />
                      </div>
                      <div>
                        <h2 className="text-base sm:text-lg font-black text-slate-900">
                          {isEs ? dayNameEs : dayNameEn} • {dayDate}
                        </h2>
                      </div>
                    </div>
                    <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-bold text-slate-600">
                      {dayGames.length} {dayGames.length === 1 ? (isEs ? "partido" : "game") : isEs ? "partidos" : "games"}
                    </span>
                  </div>

                  {/* Grid of Game Cards */}
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    {dayGames.map((game) => (
                      <GameCard
                        key={game.game_id}
                        game={game}
                        isEs={isEs}
                        expanded={expandedState[game.game_id] || {}}
                        onToggleDrawer={(type) => toggleDrawer(game.game_id, type)}
                        formatReason={formatReason}
                        formatQuoteAge={formatQuoteAge}
                      />
                    ))}
                  </div>
                </section>
              );
            })}
        </div>
      </main>
    </div>
  );
}

// -----------------------------------------------------------------------------
// Sub-components: GameCard
// -----------------------------------------------------------------------------

interface GameCardProps {
  game: WeekGameItem;
  isEs: boolean;
  expanded: { home?: boolean; away?: boolean; challengers?: boolean };
  onToggleDrawer: (type: "home" | "away" | "challengers") => void;
  formatReason: (reason: string) => string;
  formatQuoteAge: (min: number | null | undefined) => string;
}

function GameCard({
  game,
  isEs,
  expanded,
  onToggleDrawer,
  formatReason,
  formatQuoteAge,
}: GameCardProps) {
  const { home_team, away_team, champion_prediction, challenger_predictions, home_market, away_market } = game;

  // Determine overall candidate badge
  const hasHomeCandidate = home_market.would_qualify;
  const hasAwayCandidate = away_market.would_qualify;
  const isCandidate = hasHomeCandidate || hasAwayCandidate;

  // Top-line candidate message
  let badgeLabel = isEs ? "Sin apuesta" : "No bet";
  let badgeClass = "bg-slate-100 text-slate-600 border-slate-200";
  let candidateDetail = "";

  if (hasHomeCandidate) {
    badgeLabel = isEs
      ? `Candidato: ${home_team.abbreviation}`
      : `Candidate: ${home_team.abbreviation}`;
    badgeClass = "bg-emerald-50 text-emerald-800 border-emerald-300";
    candidateDetail = `EV: +${((home_market.ev || 0) * 100).toFixed(1)}% • ${home_market.best_book?.toUpperCase()}`;
  } else if (hasAwayCandidate) {
    badgeLabel = isEs
      ? `Candidato: ${away_team.abbreviation}`
      : `Candidate: ${away_team.abbreviation}`;
    badgeClass = "bg-emerald-50 text-emerald-800 border-emerald-300";
    candidateDetail = `EV: +${((away_market.ev || 0) * 100).toFixed(1)}% • ${away_market.best_book?.toUpperCase()}`;
  } else {
    candidateDetail = formatReason(home_market.reason);
  }

  // Probabilities for bars
  const pHomeModel = champion_prediction ? champion_prediction.p_home : null;
  const pAwayModel = champion_prediction ? champion_prediction.p_away : null;
  const pHomeFair = home_market.fair_prob;
  const pAwayFair = away_market.fair_prob;

  return (
    <div className="flex flex-col rounded-2xl border border-slate-200 bg-white p-5 shadow-2xs transition hover:border-slate-300">
      {/* Top Header: Tip-off + Badges */}
      <div className="flex items-center justify-between border-b border-slate-100 pb-3 gap-2">
        <div className="flex items-center gap-2 text-xs font-bold text-slate-500">
          <Clock className="h-3.5 w-3.5 text-slate-400" />
          <span>{game.local_time} CST</span>
          {champion_prediction && (
            <span className="rounded-md bg-blue-50 px-2 py-0.5 text-[11px] font-extrabold text-blue-700">
              {champion_prediction.projected_margin >= 0
                ? `${home_team.abbreviation} +${champion_prediction.projected_margin.toFixed(1)} pts`
                : `${away_team.abbreviation} +${Math.abs(champion_prediction.projected_margin).toFixed(1)} pts`}
            </span>
          )}
        </div>

        {/* Candidate / No Bet Badge */}
        <div className="flex items-center gap-1.5">
          <span
            title={candidateDetail}
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-black shadow-2xs ${badgeClass}`}
          >
            {isCandidate ? (
              <CheckCircle2 className="h-3 w-3 text-emerald-600" />
            ) : (
              <XCircle className="h-3 w-3 text-slate-400" />
            )}
            <span>{badgeLabel}</span>
          </span>
        </div>
      </div>

      {/* Matchup Header: Teams & Projections */}
      <div className="grid grid-cols-2 gap-4 py-4 border-b border-slate-100">
        {/* Away Team */}
        <div className="flex items-center gap-3">
          <TeamLogo
            teamId={away_team.id}
            abbreviation={away_team.abbreviation}
            teamName={away_team.name}
            size={42}
          />
          <div>
            <div className="flex items-center gap-1.5">
              <span className="text-base font-black text-slate-900">
                {away_team.abbreviation}
              </span>
              <span className="text-[10px] uppercase font-bold text-slate-400">
                {isEs ? "Visita" : "Away"}
              </span>
            </div>
            <p className="text-xs text-slate-500 truncate max-w-[120px] sm:max-w-[160px]">
              {away_team.name}
            </p>
          </div>
        </div>

        {/* Home Team */}
        <div className="flex items-center justify-end gap-3 text-right">
          <div>
            <div className="flex items-center justify-end gap-1.5">
              <span className="text-[10px] uppercase font-bold text-slate-400">
                {isEs ? "Local" : "Home"}
              </span>
              <span className="text-base font-black text-slate-900">
                {home_team.abbreviation}
              </span>
            </div>
            <p className="text-xs text-slate-500 truncate max-w-[120px] sm:max-w-[160px]">
              {home_team.name}
            </p>
          </div>
          <TeamLogo
            teamId={home_team.id}
            abbreviation={home_team.abbreviation}
            teamName={home_team.name}
            size={42}
          />
        </div>
      </div>

      {/* Probability Comparison: Model vs Market */}
      <div className="py-4 space-y-3 border-b border-slate-100">
        {/* Model Bar */}
        <div className="space-y-1">
          <div className="flex justify-between text-xs font-bold text-slate-600">
            <span>
              {away_team.abbreviation} {pAwayModel != null ? `${(pAwayModel * 100).toFixed(1)}%` : "-"}
            </span>
            <span className="text-[11px] font-extrabold text-blue-700">
              {isEs ? "Modelo Campeón (Elo)" : "Champion Model (Elo)"}
            </span>
            <span>
              {pHomeModel != null ? `${(pHomeModel * 100).toFixed(1)}%` : "-"} {home_team.abbreviation}
            </span>
          </div>
          <div className="h-2 w-full rounded-full bg-slate-100 overflow-hidden flex">
            <div
              className="bg-blue-400 transition-all duration-300"
              style={{ width: `${(pAwayModel || 0.5) * 100}%` }}
              title={`Away Model: ${((pAwayModel || 0) * 100).toFixed(1)}%`}
            />
            <div
              className="bg-blue-600 transition-all duration-300"
              style={{ width: `${(pHomeModel || 0.5) * 100}%` }}
              title={`Home Model: ${((pHomeModel || 0) * 100).toFixed(1)}%`}
            />
          </div>
        </div>

        {/* Pinnacle Market Close Bar */}
        <div className="space-y-1">
          <div className="flex justify-between text-xs font-semibold text-slate-500">
            <span>
              {away_team.abbreviation} {pAwayFair != null ? `${(pAwayFair * 100).toFixed(1)}%` : "-"}
            </span>
            <span className="text-[10px] font-bold text-slate-400">
              {isEs ? "Mercado Sharp (Pinnacle devig)" : "Sharp Market (Pinnacle devig)"}
            </span>
            <span>
              {pHomeFair != null ? `${(pHomeFair * 100).toFixed(1)}%` : "-"} {home_team.abbreviation}
            </span>
          </div>
          <div className="h-1.5 w-full rounded-full bg-slate-100 overflow-hidden flex">
            {pAwayFair != null && pHomeFair != null ? (
              <>
                <div
                  className="bg-slate-300 transition-all duration-300"
                  style={{ width: `${pAwayFair * 100}%` }}
                />
                <div
                  className="bg-slate-400 transition-all duration-300"
                  style={{ width: `${pHomeFair * 100}%` }}
                />
              </>
            ) : (
              <div className="w-full bg-slate-200" />
            )}
          </div>
        </div>
      </div>

      {/* Side Markets: Best Quotes, Edge, and Badges */}
      <div className="grid grid-cols-2 gap-3 py-3 border-b border-slate-100">
        {/* Away Market */}
        <SideMarketCard
          teamAbbr={away_team.abbreviation}
          market={away_market}
          isEs={isEs}
          formatQuoteAge={formatQuoteAge}
          formatReason={formatReason}
        />

        {/* Home Market */}
        <SideMarketCard
          teamAbbr={home_team.abbreviation}
          market={home_market}
          isEs={isEs}
          formatQuoteAge={formatQuoteAge}
          formatReason={formatReason}
        />
      </div>

      {/* Accordions: Injuries Drawer & Challengers */}
      <div className="pt-3 space-y-2">
        <div className="flex items-center justify-between gap-2">
          {/* Away Injuries Toggle */}
          <button
            type="button"
            onClick={() => onToggleDrawer("away")}
            aria-expanded={expanded.away}
            className="flex-1 inline-flex items-center justify-between rounded-xl border border-slate-200 bg-slate-50/70 px-3 py-1.5 text-[11px] font-bold text-slate-700 hover:bg-slate-100 transition"
          >
            <div className="flex items-center gap-1.5 truncate">
              <ShieldAlert className="h-3.5 w-3.5 text-rose-500 shrink-0" />
              <span className="truncate">
                {away_team.abbreviation}: {away_team.injuries.entries.length}{" "}
                {isEs ? "bajas" : "out"}
              </span>
            </div>
            {expanded.away ? (
              <ChevronUp className="h-3.5 w-3.5 text-slate-400" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
            )}
          </button>

          {/* Home Injuries Toggle */}
          <button
            type="button"
            onClick={() => onToggleDrawer("home")}
            aria-expanded={expanded.home}
            className="flex-1 inline-flex items-center justify-between rounded-xl border border-slate-200 bg-slate-50/70 px-3 py-1.5 text-[11px] font-bold text-slate-700 hover:bg-slate-100 transition"
          >
            <div className="flex items-center gap-1.5 truncate">
              <ShieldAlert className="h-3.5 w-3.5 text-rose-500 shrink-0" />
              <span className="truncate">
                {home_team.abbreviation}: {home_team.injuries.entries.length}{" "}
                {isEs ? "bajas" : "out"}
              </span>
            </div>
            {expanded.home ? (
              <ChevronUp className="h-3.5 w-3.5 text-slate-400" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
            )}
          </button>
        </div>

        {/* Challengers Toggle (if present) */}
        {challenger_predictions.length > 0 && (
          <button
            type="button"
            onClick={() => onToggleDrawer("challengers")}
            aria-expanded={expanded.challengers}
            className="w-full inline-flex items-center justify-between rounded-xl border border-violet-200 bg-violet-50/50 px-3 py-1 text-[11px] font-bold text-violet-800 hover:bg-violet-100/50 transition"
          >
            <span className="flex items-center gap-1.5">
              <Percent className="h-3.5 w-3.5 text-violet-600" />
              <span>
                {isEs ? "Modelos Retadores en Shadow" : "Shadow Challenger Models"} (
                {challenger_predictions.length})
              </span>
            </span>
            {expanded.challengers ? (
              <ChevronUp className="h-3.5 w-3.5 text-violet-400" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5 text-violet-400" />
            )}
          </button>
        )}

        {/* Drawer Content: Away Injuries */}
        {expanded.away && (
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 space-y-2 animate-in fade-in duration-200">
            <h4 className="text-xs font-black text-slate-800">
              {away_team.name} ({away_team.abbreviation}) - {isEs ? "Bajas Reportadas" : "Injuries"}
            </h4>
            <InjuryEntriesList
              entries={away_team.injuries.entries}
              isEs={isEs}
            />
          </div>
        )}

        {/* Drawer Content: Home Injuries */}
        {expanded.home && (
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 space-y-2 animate-in fade-in duration-200">
            <h4 className="text-xs font-black text-slate-800">
              {home_team.name} ({home_team.abbreviation}) - {isEs ? "Bajas Reportadas" : "Injuries"}
            </h4>
            <InjuryEntriesList
              entries={home_team.injuries.entries}
              isEs={isEs}
            />
          </div>
        )}

        {/* Drawer Content: Challengers */}
        {expanded.challengers && (
          <div className="rounded-xl border border-violet-200 bg-violet-50/40 p-3 space-y-2 animate-in fade-in duration-200">
            <h4 className="text-xs font-black text-violet-900">
              {isEs ? "Predicciones de Retadores" : "Challenger Model Predictions"}
            </h4>
            <div className="space-y-1.5">
              {challenger_predictions.map((cp) => (
                <div
                  key={cp.model_id}
                  className="flex items-center justify-between rounded-lg bg-white p-2 text-xs border border-violet-100 shadow-2xs"
                >
                  <div>
                    <span className="font-extrabold text-slate-800">
                      {cp.model_name}
                    </span>
                    <span className="text-[10px] text-slate-400 ml-1">
                      v{cp.model_version}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 font-semibold text-slate-700">
                    <span>
                      {away_team.abbreviation} {(cp.p_away * 100).toFixed(1)}%
                    </span>
                    <span className="text-slate-300">•</span>
                    <span>
                      {home_team.abbreviation} {(cp.p_home * 100).toFixed(1)}%
                    </span>
                    {cp.projected_margin != null && (
                      <span className="text-[10px] bg-violet-100 text-violet-800 px-1.5 py-0.5 rounded font-mono font-bold">
                        {cp.projected_margin >= 0 ? `+${cp.projected_margin}` : cp.projected_margin}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// -----------------------------------------------------------------------------
// Sub-components: SideMarketCard
// -----------------------------------------------------------------------------

interface SideMarketCardProps {
  teamAbbr: string;
  market: SideMarketView;
  isEs: boolean;
  formatQuoteAge: (min: number | null | undefined) => string;
  formatReason: (reason: string) => string;
}

function SideMarketCard({
  teamAbbr,
  market,
  isEs,
  formatQuoteAge,
  formatReason,
}: SideMarketCardProps) {
  const isCandidate = market.would_qualify;
  const edgePp = market.edge != null ? market.edge * 100 : null;

  return (
    <div
      className={`rounded-xl border p-3 flex flex-col justify-between space-y-2 ${
        isCandidate
          ? "border-emerald-300 bg-emerald-50/50"
          : "border-slate-100 bg-slate-50/50"
      }`}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-black text-slate-800">
          {teamAbbr} {isEs ? "Moneyline" : "Moneyline"}
        </span>
        {isCandidate ? (
          <span className="rounded-md bg-emerald-100 px-1.5 py-0.5 text-[10px] font-black text-emerald-800">
            +EV
          </span>
        ) : (
          <span className="text-[10px] font-bold text-slate-400">
            {market.reason === "ok" ? "OK" : formatReason(market.reason)}
          </span>
        )}
      </div>

      {/* Best Price & Bookmaker */}
      <div>
        <div className="flex items-baseline gap-1.5">
          <span className="text-base font-black text-slate-900">
            {market.best_price ? market.best_price.toFixed(2) : "-"}
          </span>
          {market.best_price_american != null && (
            <span className="text-[11px] font-mono text-slate-500">
              ({market.best_price_american > 0 ? `+${market.best_price_american}` : market.best_price_american})
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5 text-[10px] text-slate-500">
          <span className="font-extrabold uppercase text-slate-700">
            {market.best_book || (isEs ? "Sin cuota" : "No quote")}
          </span>
          {market.quote_age_minutes != null && (
            <span
              className={`font-medium ${
                market.quote_age_minutes > 360 ? "text-amber-700 font-bold" : "text-slate-400"
              }`}
            >
              • {formatQuoteAge(market.quote_age_minutes)}
            </span>
          )}
        </div>
      </div>

      {/* Edge & EV */}
      <div className="pt-1 border-t border-slate-200/60 flex items-center justify-between text-[11px]">
        <span className="text-slate-500">{isEs ? "Ventaja:" : "Edge:"}</span>
        <span
          className={`font-black ${
            edgePp != null && edgePp >= 2.0
              ? "text-emerald-700"
              : edgePp != null && edgePp > 0
              ? "text-slate-700"
              : "text-slate-400"
          }`}
        >
          {edgePp != null ? `${edgePp >= 0 ? "+" : ""}${edgePp.toFixed(1)} pp` : "-"}
        </span>
      </div>
    </div>
  );
}

// -----------------------------------------------------------------------------
// Sub-components: InjuryEntriesList
// -----------------------------------------------------------------------------

function InjuryEntriesList({
  entries,
  isEs,
}: {
  entries: TeamInjuryEntry[];
  isEs: boolean;
}) {
  if (entries.length === 0) {
    return (
      <p className="text-xs text-slate-500 italic">
        {isEs ? "Sin jugadores no disponibles reportados." : "No unavailable players reported."}
      </p>
    );
  }

  return (
    <div className="space-y-1.5">
      {entries.map((ent, idx) => {
        const isOut = ent.status.toLowerCase().includes("out");
        const isDoubtful = ent.status.toLowerCase().includes("doubt");

        const badgeClass = isOut
          ? "bg-rose-100 text-rose-800 border-rose-200"
          : isDoubtful
          ? "bg-amber-100 text-amber-800 border-amber-200"
          : "bg-yellow-100 text-yellow-800 border-yellow-200";

        return (
          <div
            key={`${ent.player_name}-${idx}`}
            className="flex items-start justify-between rounded-lg bg-white p-2 text-xs border border-slate-200 shadow-2xs gap-2"
          >
            <div className="space-y-0.5">
              <p className="font-bold text-slate-900">{ent.player_name}</p>
              {ent.reason && (
                <p className="text-[11px] text-slate-500 leading-tight">
                  {ent.reason}
                </p>
              )}
            </div>
            <div className="text-right shrink-0">
              <span
                className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-black border ${badgeClass}`}
              >
                {ent.status}
              </span>
              {ent.availability_prob != null && (
                <p className="text-[10px] font-mono text-slate-400 mt-0.5">
                  {Math.round(ent.availability_prob * 100)}% prob
                </p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
