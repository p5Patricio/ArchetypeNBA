"use client";

import React, { useEffect, useState, useMemo } from "react";
import { Navbar } from "@/components/Navbar";
import { CommandPalette } from "@/components/CommandPalette";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { TeamLogo } from "@/components/TeamLogo";
import { usePreferences } from "@/context/PreferencesContext";
import {
  getTodayProps,
  runPropsAnalysis,
  type TodayPropsResponse,
  type PropItem,
} from "@/lib/api";
import {
  TrendingUp,
  Sparkles,
  Zap,
  ShieldCheck,
  AlertCircle,
  RefreshCw,
  Search,
  Percent,
  SlidersHorizontal,
  Flame,
  ArrowUpRight,
  ArrowDownRight,
  Clock,
  Layers,
  BarChart3,
  Cpu,
  CheckCircle2,
  Send,
} from "lucide-react";

type StatCategory = "ALL" | "POINTS" | "REBOUNDS" | "ASSISTS" | "PRA";
type SortOption = "EV_DESC" | "EDGE_DESC" | "KELLY_DESC" | "LINE_DESC";

export default function PropsPage() {
  const { language } = usePreferences();
  const [data, setData] = useState<TodayPropsResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [isCommandOpen, setIsCommandOpen] = useState<boolean>(false);

  // Filters & State
  const [selectedCategory, setSelectedCategory] = useState<StatCategory>("ALL");
  const [onlyValuePicks, setOnlyValuePicks] = useState<boolean>(false);
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [sortBy, setSortBy] = useState<SortOption>("EV_DESC");

  // On-demand AI Analysis & Telegram dispatch state
  const [analyzing, setAnalyzing] = useState<boolean>(false);
  const [sendTelegram, setSendTelegram] = useState<boolean>(true);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const loadPropsData = async (forceRefresh: boolean = false) => {
    if (forceRefresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);

    try {
      const res = await getTodayProps({ refresh: forceRefresh });
      setData(res);
    } catch (err: unknown) {
      console.error("Error loading NBA props:", err);
      setError(
        err instanceof Error
          ? err.message
          : language === "es"
          ? "No se pudieron cargar las proyecciones de props."
          : "Failed to load player props projections."
      );
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const handleRunAnalysis = async () => {
    setAnalyzing(true);
    setError(null);

    try {
      const res = await runPropsAnalysis({ send_telegram: sendTelegram });
      setData(res);
      setToastMessage(
        language === "es"
          ? `¡Análisis completado! Se generaron ${res.total_props} props (${res.value_picks_count} picks con +EV).${sendTelegram ? " Reporte despachado a Telegram." : ""}`
          : `Analysis complete! Generated ${res.total_props} props (${res.value_picks_count} value picks).${sendTelegram ? " Dispatched to Telegram." : ""}`
      );
      setTimeout(() => setToastMessage(null), 7000);
    } catch (err: unknown) {
      console.error("Error running props analysis:", err);
      setError(
        err instanceof Error
          ? err.message
          : language === "es"
          ? "No se pudo completar el análisis con Gemini AI."
          : "Failed to run AI props analysis."
      );
    } finally {
      setAnalyzing(false);
    }
  };

  useEffect(() => {
    loadPropsData();
  }, []);

  // Filter and sort items
  const filteredItems = useMemo(() => {
    if (!data || !data.items) return [];

    return data.items
      .filter((item) => {
        // Category filter
        if (selectedCategory !== "ALL") {
          const st = item.stat_type.toLowerCase();
          if (selectedCategory === "POINTS" && !st.includes("point")) return false;
          if (selectedCategory === "REBOUNDS" && !st.includes("rebound")) return false;
          if (selectedCategory === "ASSISTS" && !st.includes("assist")) return false;
          if (
            selectedCategory === "PRA" &&
            !st.includes("points_rebounds_assists") &&
            !st.includes("pra")
          ) {
            return false;
          }
        }

        // Value picks only
        if (onlyValuePicks && item.expected_value_pct <= 0) {
          return false;
        }

        // Search query
        if (searchQuery.trim()) {
          const q = searchQuery.toLowerCase().trim();
          const matchPlayer = item.player_name.toLowerCase().includes(q);
          const matchTeam = item.team.toLowerCase().includes(q);
          if (!matchPlayer && !matchTeam) return false;
        }

        return true;
      })
      .sort((a, b) => {
        if (sortBy === "EV_DESC") {
          return b.expected_value_pct - a.expected_value_pct;
        }
        if (sortBy === "EDGE_DESC") {
          return b.edge_pct - a.edge_pct;
        }
        if (sortBy === "KELLY_DESC") {
          return b.kelly_stake_pct - a.kelly_stake_pct;
        }
        if (sortBy === "LINE_DESC") {
          return b.line - a.line;
        }
        return 0;
      });
  }, [data, selectedCategory, onlyValuePicks, searchQuery, sortBy]);

  const statCategoryLabels: Record<StatCategory, { es: string; en: string }> = {
    ALL: { es: "Todas las Categorías", en: "All Categories" },
    POINTS: { es: "Puntos (PTS)", en: "Points (PTS)" },
    REBOUNDS: { es: "Rebotes (REB)", en: "Rebounds (REB)" },
    ASSISTS: { es: "Asistencias (AST)", en: "Assists (AST)" },
    PRA: { es: "PTS + REB + AST", en: "PTS + REB + AST" },
  };

  const getStatTypeBadge = (statType: string) => {
    const st = statType.toLowerCase();
    if (st.includes("point") && !st.includes("rebound")) {
      return { label: "Puntos", color: "bg-orange-50 border-orange-200 text-orange-700" };
    }
    if (st.includes("rebound") && !st.includes("point")) {
      return { label: "Rebotes", color: "bg-blue-50 border-blue-200 text-blue-700" };
    }
    if (st.includes("assist") && !st.includes("point")) {
      return { label: "Asistencias", color: "bg-emerald-50 border-emerald-200 text-emerald-700" };
    }
    return { label: "PTS+REB+AST", color: "bg-purple-50 border-purple-200 text-purple-700" };
  };

  const getRecommendationStyle = (rec: string) => {
    const r = rec.toUpperCase();
    if (r === "OVER") {
      return {
        bg: "bg-emerald-50 border border-emerald-200 text-emerald-800",
        text: "OVER (ALTA)",
        icon: ArrowUpRight,
      };
    }
    if (r === "UNDER") {
      return {
        bg: "bg-rose-50 border border-rose-200 text-rose-800",
        text: "UNDER (BAJA)",
        icon: ArrowDownRight,
      };
    }
    return {
      bg: "bg-slate-100 border border-slate-200 text-slate-600",
      text: "PASS (NEUTRAL)",
      icon: ShieldCheck,
    };
  };

  const formatOdds = (odds: number) => {
    if (odds > 0) return `+${odds}`;
    return `${odds}`;
  };

  const isEs = language === "es";

  return (
    <div className="min-h-screen bg-[#F8FAFC] text-slate-900 selection:bg-orange-100 selection:text-orange-900">
      <Navbar onOpenSearch={() => setIsCommandOpen(true)} />
      <CommandPalette isOpen={isCommandOpen} onClose={() => setIsCommandOpen(false)} />

      {/* Desktop sidebar offset wrapper */}
      <div className="md:pl-64">
        {/* ========================================================================= */}
        {/* HERO SECTION (Clean White / Warm Gradient consistent with ArchetypeNBA) */}
        {/* ========================================================================= */}
        <section className="relative border-b border-slate-200 bg-gradient-to-b from-orange-50/40 via-white to-white py-12 lg:py-16 shadow-xs">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
              <div className="space-y-3">
                {/* Pill Badge */}
                <div className="inline-flex items-center gap-2 rounded-full border border-orange-200 bg-orange-50 px-4 py-1 text-xs font-black text-orange-800 shadow-2xs">
                  <TrendingUp className="h-3.5 w-3.5 text-orange-600" />
                  <span>
                    {isEs
                      ? "MODELO CUANTITATIVO • PROYECCIONES MONTE CARLO (+EV)"
                      : "QUANT MODEL • MONTE CARLO SIMULATIONS (+EV)"}
                  </span>
                </div>

                {/* Headline */}
                <h1 className="text-3xl sm:text-4xl lg:text-5xl font-black tracking-tight text-slate-900 leading-tight">
                  NBA Player Props & Expected Value
                </h1>

                {/* Subtitle */}
                <p className="max-w-2xl text-sm sm:text-base text-slate-600 font-normal leading-relaxed">
                  {isEs
                    ? "Identificá valor matemático frente a las cuotas de las casas de apuestas. Integramos distribución Binomial Negativa (10,000 simulaciones), análisis cualitativo con Gemini AI y cuotas en vivo."
                    : "Identify mathematical edges against sportsbook lines using Negative Binomial distributions (10,000 Monte Carlo runs), Gemini AI qualitative injury adjustments, and live odds."}
                </p>
              </div>

              {/* Hero Action Controls */}
              <div className="flex flex-wrap items-center gap-3 shrink-0">
                {/* Telegram Dispatch Toggle */}
                <label className="flex items-center gap-2 cursor-pointer select-none px-3.5 py-2.5 rounded-2xl bg-white border border-slate-200 text-xs font-semibold text-slate-700 hover:border-slate-300 hover:bg-slate-50 shadow-2xs transition-all">
                  <input
                    type="checkbox"
                    checked={sendTelegram}
                    onChange={(e) => setSendTelegram(e.target.checked)}
                    className="rounded border-slate-300 text-orange-600 focus:ring-orange-500 h-4 w-4 cursor-pointer"
                  />
                  <Send className="h-3.5 w-3.5 text-sky-500" />
                  <span>{isEs ? "Despachar a Telegram" : "Send to Telegram"}</span>
                </label>

                {/* Primary Trigger: On-Demand AI Analysis */}
                <button
                  onClick={handleRunAnalysis}
                  disabled={analyzing || loading}
                  className="rounded-2xl bg-gradient-to-r from-orange-600 via-orange-500 to-amber-600 px-5 py-2.5 text-xs font-black text-white shadow-md hover:from-orange-500 hover:to-amber-500 hover:shadow-orange-500/20 active:scale-[0.98] transition-all inline-flex items-center gap-2 disabled:opacity-50 cursor-pointer"
                >
                  {analyzing ? (
                    <RefreshCw className="h-4 w-4 animate-spin text-white" />
                  ) : (
                    <Zap className="h-4 w-4 text-amber-200 fill-amber-200" />
                  )}
                  <span>
                    {analyzing
                      ? isEs
                        ? "Simulando (10,000 corridas)..."
                        : "Simulating (10k runs)..."
                      : data && data.total_props > 0
                      ? isEs
                        ? "Re-ejecutar Análisis IA"
                        : "Re-run AI Analysis"
                      : isEs
                      ? "Ejecutar Análisis IA"
                      : "Run AI Analysis"}
                  </span>
                </button>

                {/* Fast Cache Reload */}
                <button
                  onClick={() => loadPropsData(false)}
                  disabled={refreshing || loading || analyzing}
                  title={isEs ? "Recargar datos desde caché" : "Reload from cache"}
                  className="rounded-2xl border border-slate-200 bg-white px-3.5 py-2.5 text-xs font-bold text-slate-700 shadow-2xs hover:border-orange-300 hover:bg-orange-50/40 transition-all inline-flex items-center gap-1.5 disabled:opacity-50 cursor-pointer"
                >
                  <RefreshCw
                    className={`h-3.5 w-3.5 text-slate-500 ${refreshing ? "animate-spin text-orange-600" : ""}`}
                  />
                  <span className="hidden sm:inline">
                    {refreshing
                      ? isEs
                        ? "Leyendo..."
                        : "Reading..."
                      : isEs
                      ? "Recargar"
                      : "Reload"}
                  </span>
                </button>
              </div>
            </div>
          </div>
        </section>

        {/* Toast Alert Banner */}
        {toastMessage && (
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 pt-6">
            <div className="rounded-2xl border border-emerald-200 bg-emerald-50/90 p-4 shadow-sm flex items-center justify-between gap-3 animate-in fade-in slide-in-from-top-2">
              <div className="flex items-center gap-3 text-xs sm:text-sm font-bold text-emerald-950">
                <CheckCircle2 className="h-5 w-5 text-emerald-600 shrink-0" />
                <span>{toastMessage}</span>
              </div>
              <button
                onClick={() => setToastMessage(null)}
                className="text-emerald-700 hover:text-emerald-900 text-xs font-bold px-2 py-1 rounded-lg hover:bg-emerald-100 transition-colors cursor-pointer"
              >
                ✕
              </button>
            </div>
          </div>
        )}

        {/* Active Simulation Progress Banner */}
        {analyzing && (
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 pt-6">
            <div className="rounded-3xl border border-orange-200 bg-gradient-to-r from-orange-50 via-amber-50 to-orange-50 p-6 shadow-sm flex flex-col sm:flex-row items-center justify-between gap-4">
              <div className="flex items-center gap-4">
                <div className="h-12 w-12 rounded-2xl bg-orange-600 text-white flex items-center justify-center shadow-md shadow-orange-600/20 shrink-0 animate-pulse">
                  <Zap className="h-6 w-6 text-amber-200 fill-amber-200" />
                </div>
                <div className="space-y-1">
                  <div className="text-sm sm:text-base font-black text-slate-900 flex items-center gap-2">
                    <span>
                      {isEs
                        ? "Simulaciones Monte Carlo & Análisis Gemini en Ejecución"
                        : "Monte Carlo Simulations & Gemini Analysis Running"}
                    </span>
                  </div>
                  <p className="text-xs text-slate-600 font-medium">
                    {isEs
                      ? "Consultando The Odds API en vivo, simulando 10,000 corridas por jugador y evaluando Expected Value (+EV)..."
                      : "Querying The Odds API live, computing 10,000 iterations per player, and evaluating +EV edges..."}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2.5 px-4 py-2 rounded-2xl bg-white/80 border border-orange-200 text-xs font-bold text-orange-800 shrink-0 shadow-2xs">
                <RefreshCw className="h-4 w-4 animate-spin text-orange-600" />
                <span>{isEs ? "Calculando distribuciones..." : "Computing distributions..."}</span>
              </div>
            </div>
          </div>
        )}

        {/* ========================================================================= */}
        {/* MAIN CONTENT AREA */}
        {/* ========================================================================= */}
        <main className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-10 space-y-8">
          {/* Intelligence Meta Metrics Cards */}
          {data && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-xs">
                <div className="flex items-center gap-2 text-xs font-semibold text-slate-400 mb-1">
                  <Clock className="h-3.5 w-3.5 text-slate-400" />
                  <span>{isEs ? "Fecha del Slate" : "Slate Date"}</span>
                </div>
                <div className="text-base font-black text-slate-900">{data.date}</div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-xs">
                <div className="flex items-center gap-2 text-xs font-semibold text-slate-400 mb-1">
                  <Cpu className="h-3.5 w-3.5 text-orange-500" />
                  <span>{isEs ? "Motor de Simulación" : "Simulation Engine"}</span>
                </div>
                <div className="text-sm font-black text-orange-700 truncate">
                  {data.ai_engine}
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-xs">
                <div className="flex items-center gap-2 text-xs font-semibold text-slate-400 mb-1">
                  <Layers className="h-3.5 w-3.5 text-blue-500" />
                  <span>{isEs ? "Props Analizados" : "Analyzed Props"}</span>
                </div>
                <div className="text-base font-black text-slate-900">{data.total_props}</div>
              </div>

              <div className="rounded-2xl border border-emerald-200 bg-emerald-50/40 p-4 shadow-xs">
                <div className="flex items-center gap-2 text-xs font-semibold text-emerald-700 mb-1">
                  <Flame className="h-3.5 w-3.5 text-emerald-600" />
                  <span>{isEs ? "Oportunidades +EV" : "+EV Value Picks"}</span>
                </div>
                <div className="text-base font-black text-emerald-700 flex items-center gap-1.5">
                  <span>{data.value_picks_count}</span>
                  <span className="text-xs font-medium text-emerald-600">
                    {isEs ? "picks con valor" : "value picks"}
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Filter Controls Bar */}
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs space-y-4">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
              {/* Category Pills */}
              <div className="flex flex-wrap items-center gap-2">
                {(["ALL", "POINTS", "REBOUNDS", "ASSISTS", "PRA"] as StatCategory[]).map(
                  (cat) => (
                    <button
                      key={cat}
                      onClick={() => setSelectedCategory(cat)}
                      className={`px-3.5 py-1.5 rounded-xl text-xs font-bold transition-all border ${
                        selectedCategory === cat
                          ? "bg-slate-900 text-white border-slate-900 shadow-xs font-black"
                          : "border-slate-200 bg-slate-50 text-slate-700 hover:bg-slate-100 hover:text-slate-900"
                      }`}
                    >
                      {statCategoryLabels[cat][isEs ? "es" : "en"]}
                    </button>
                  )
                )}
              </div>

              {/* Toggle Value Picks Only */}
              <div className="flex items-center gap-2">
                <label className="relative inline-flex items-center cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={onlyValuePicks}
                    onChange={(e) => setOnlyValuePicks(e.target.checked)}
                    className="sr-only peer"
                  />
                  <div className="w-10 h-5 bg-slate-200 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-emerald-500"></div>
                  <span className="ml-2.5 text-xs font-bold text-slate-800 flex items-center gap-1.5">
                    <Flame className="h-3.5 w-3.5 text-emerald-600" />
                    {isEs ? "Solo picks con valor (+EV)" : "Only +EV Picks"}
                  </span>
                </label>
              </div>
            </div>

            <div className="flex flex-col sm:flex-row items-center justify-between gap-3 pt-3 border-t border-slate-100">
              {/* Search Bar */}
              <div className="relative w-full sm:w-80">
                <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder={
                    isEs
                      ? "Buscar jugador o equipo (ej. Luka, LAL)..."
                      : "Search player or team..."
                  }
                  className="w-full pl-10 pr-4 py-1.5 rounded-xl border border-slate-200 bg-slate-50/80 text-xs font-medium text-slate-900 placeholder:text-slate-400 focus:border-orange-500 focus:bg-white focus:ring-2 focus:ring-orange-500/10 transition-all outline-none"
                />
              </div>

              {/* Sort Selector */}
              <div className="flex items-center gap-2 w-full sm:w-auto justify-end">
                <SlidersHorizontal className="h-3.5 w-3.5 text-slate-400 shrink-0" />
                <span className="text-xs font-semibold text-slate-500 shrink-0">
                  {isEs ? "Ordenar por:" : "Sort by:"}
                </span>
                <select
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value as SortOption)}
                  className="px-3 py-1.5 rounded-xl border border-slate-200 bg-slate-50 text-xs font-bold text-slate-800 outline-none cursor-pointer"
                >
                  <option value="EV_DESC">
                    {isEs ? "Mayor Expected Value (+EV %)" : "Highest +EV %"}
                  </option>
                  <option value="EDGE_DESC">
                    {isEs ? "Mayor Ventaja Modelo (Edge %)" : "Highest Edge %"}
                  </option>
                  <option value="KELLY_DESC">
                    {isEs ? "Mayor Stake Kelly %" : "Highest Kelly Stake"}
                  </option>
                  <option value="LINE_DESC">
                    {isEs ? "Línea más alta" : "Highest Line"}
                  </option>
                </select>
              </div>
            </div>
          </div>

          {/* Loading Indicator */}
          {loading && (
            <div className="flex flex-col items-center justify-center py-24 space-y-4">
              <RefreshCw className="h-10 w-10 text-orange-500 animate-spin" />
              <p className="text-sm font-bold text-slate-500">
                {isEs
                  ? "Simulando 10,000 iteraciones Monte Carlo y consultando cuotas en vivo..."
                  : "Running 10,000 Monte Carlo simulations and fetching live odds..."}
              </p>
            </div>
          )}

          {/* Error Message */}
          {error && !loading && (
            <div className="rounded-2xl border border-rose-200 bg-rose-50/70 p-6 text-center space-y-3">
              <AlertCircle className="h-8 w-8 text-rose-500 mx-auto" />
              <div className="text-base font-bold text-rose-900">
                {isEs ? "Error al cargar props" : "Error loading props"}
              </div>
              <p className="text-xs text-rose-700 max-w-md mx-auto">{error}</p>
              <button
                onClick={() => loadPropsData(true)}
                className="px-4 py-2 rounded-xl bg-rose-600 text-white text-xs font-bold hover:bg-rose-700 transition-colors inline-flex items-center gap-1.5"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                {isEs ? "Reintentar" : "Retry"}
              </button>
            </div>
          )}

          {/* Props Grid */}
          {!loading && !error && filteredItems.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
              {filteredItems.map((prop, idx) => {
                const badge = getStatTypeBadge(prop.stat_type);
                const rec = getRecommendationStyle(prop.recommendation);
                const RecIcon = rec.icon;
                const hasPositiveEV = prop.expected_value_pct > 0;

                return (
                  <div
                    key={`${prop.player_name}-${prop.stat_type}-${idx}`}
                    className={`relative rounded-2xl border bg-white p-5 shadow-xs transition-all duration-300 hover:shadow-md hover:border-slate-300 flex flex-col justify-between overflow-hidden space-y-4 ${
                      hasPositiveEV
                        ? "border-emerald-200"
                        : "border-slate-200"
                    }`}
                  >
                    {/* Top edge green stripe for value picks */}
                    {hasPositiveEV && (
                      <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-emerald-400 to-teal-500" />
                    )}

                    <div className="space-y-4">
                      {/* Player Info & Recommendation Badge */}
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-center gap-3">
                          <PlayerAvatar
                            playerName={prop.player_name}
                            size={44}
                            className="rounded-xl ring-1 ring-slate-200 shrink-0"
                          />
                          <div>
                            <h3 className="text-sm font-black text-slate-900 leading-tight">
                              {prop.player_name}
                            </h3>
                            <div className="flex items-center gap-1.5 mt-1">
                              <div className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-slate-100 text-[10px] font-bold text-slate-700">
                                <TeamLogo abbreviation={prop.team} size={12} />
                                <span>{prop.team}</span>
                              </div>
                              <span className="text-slate-300 text-xs">•</span>
                              <div
                                className={`px-2 py-0.5 rounded-md border text-[10px] font-extrabold uppercase ${badge.color}`}
                              >
                                {badge.label}
                              </div>
                            </div>
                          </div>
                        </div>

                        {/* Recommendation Pill */}
                        <div
                          className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-xl text-xs font-black tracking-wide shrink-0 ${rec.bg}`}
                        >
                          <RecIcon className="h-3 w-3" />
                          <span>{rec.text}</span>
                        </div>
                      </div>

                      {/* Sportsbook vs Model Matrix Box */}
                      <div className="rounded-xl bg-slate-50 border border-slate-100 p-3.5 space-y-3">
                        <div className="flex items-center justify-between border-b border-slate-200/60 pb-2">
                          <div>
                            <span className="text-[10px] font-bold uppercase text-slate-400 tracking-wider">
                              {isEs ? "Línea Casa de Apuestas" : "Sportsbook Line"}
                            </span>
                            <div className="text-sm font-black text-slate-900 flex items-baseline gap-1.5">
                              <span>Over {prop.line}</span>
                              <span className="text-xs font-mono font-bold text-orange-600">
                                ({formatOdds(prop.over_odds)})
                              </span>
                            </div>
                          </div>

                          <div className="text-right">
                            <span className="text-[10px] font-bold uppercase text-slate-400 tracking-wider">
                              {isEs ? "Prob. Implícita Casa" : "Book Implied"}
                            </span>
                            <div className="text-sm font-mono font-black text-slate-700">
                              {prop.book_implied_prob.toFixed(1)}%
                            </div>
                          </div>
                        </div>

                        {/* Model Projected Stats */}
                        <div className="grid grid-cols-3 gap-2 text-center pt-1">
                          <div>
                            <span className="text-[10px] font-bold text-slate-400 uppercase">
                              {isEs ? "Media Proy." : "Proj. Mean"}
                            </span>
                            <div className="text-xs font-mono font-black text-slate-900">
                              {prop.projected_mean.toFixed(1)}
                            </div>
                          </div>
                          <div>
                            <span className="text-[10px] font-bold text-slate-400 uppercase">
                              {isEs ? "Mediana" : "Median"}
                            </span>
                            <div className="text-xs font-mono font-black text-slate-900">
                              {prop.projected_median.toFixed(1)}
                            </div>
                          </div>
                          <div>
                            <span className="text-[10px] font-bold text-slate-400 uppercase">
                              {isEs ? "Prob. Modelo" : "Model Prob"}
                            </span>
                            <div className="text-xs font-mono font-black text-emerald-700">
                              {prop.prob_over.toFixed(1)}%
                            </div>
                          </div>
                        </div>

                        {/* Probability Bar */}
                        <div className="space-y-1 pt-1">
                          <div className="flex justify-between text-[10px] font-bold text-slate-400">
                            <span>Vegas: {prop.book_implied_prob.toFixed(1)}%</span>
                            <span className="text-emerald-700 font-extrabold">
                              Modelo: {prop.prob_over.toFixed(1)}%
                            </span>
                          </div>
                          <div className="relative w-full h-2 rounded-full bg-slate-200 overflow-hidden">
                            <div
                              className="absolute top-0 bottom-0 left-0 bg-slate-400"
                              style={{
                                width: `${Math.min(100, Math.max(0, prop.book_implied_prob))}%`,
                              }}
                            />
                            <div
                              className={`absolute top-0 bottom-0 left-0 transition-all ${
                                prop.prob_over >= prop.book_implied_prob
                                  ? "bg-emerald-500"
                                  : "bg-rose-500"
                              }`}
                              style={{
                                width: `${Math.min(100, Math.max(0, prop.prob_over))}%`,
                                opacity: 0.85,
                              }}
                            />
                          </div>
                        </div>
                      </div>

                      {/* Edge & Expected Value Pills */}
                      <div className="grid grid-cols-2 gap-2.5">
                        <div
                          className={`p-2.5 rounded-xl border flex flex-col justify-center ${
                            prop.edge_pct > 0
                              ? "bg-emerald-50 border-emerald-200 text-emerald-800"
                              : "bg-slate-50 border-slate-200 text-slate-700"
                          }`}
                        >
                          <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wide">
                            {isEs ? "Ventaja (Edge)" : "Model Edge"}
                          </span>
                          <span className="text-sm font-mono font-black mt-0.5">
                            {prop.edge_pct > 0
                              ? `+${prop.edge_pct.toFixed(1)}%`
                              : `${prop.edge_pct.toFixed(1)}%`}
                          </span>
                        </div>

                        <div
                          className={`p-2.5 rounded-xl border flex flex-col justify-center ${
                            prop.expected_value_pct > 0
                              ? "bg-emerald-50 border-emerald-200 text-emerald-800"
                              : "bg-slate-50 border-slate-200 text-slate-700"
                          }`}
                        >
                          <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wide">
                            Expected Value (+EV)
                          </span>
                          <span className="text-sm font-mono font-black mt-0.5">
                            {prop.expected_value_pct > 0
                              ? `+${prop.expected_value_pct.toFixed(1)}% EV`
                              : `${prop.expected_value_pct.toFixed(1)}% EV`}
                          </span>
                        </div>
                      </div>

                      {/* Quarter Kelly Bankroll */}
                      <div className="flex items-center justify-between px-3 py-2 rounded-xl bg-slate-50 border border-slate-100 text-xs">
                        <span className="font-semibold text-slate-500 flex items-center gap-1">
                          <Percent className="h-3 w-3 text-orange-500" />
                          <span>{isEs ? "Stake Kelly Sugerido:" : "Kelly Stake:"}</span>
                        </span>
                        <span className="font-mono font-black text-slate-900">
                          {prop.kelly_stake_pct > 0
                            ? `${(prop.kelly_stake_pct * 100).toFixed(1)}% bankroll`
                            : "0.0% (No bet)"}
                        </span>
                      </div>

                      {/* Monte Carlo Range */}
                      <div className="text-[11px] text-slate-500 flex items-center justify-between font-medium">
                        <span>Rango Monte Carlo (P10 - P90):</span>
                        <span className="font-mono font-bold text-slate-700">
                          [{prop.projected_p10.toFixed(1)} — {prop.projected_p90.toFixed(1)}]
                        </span>
                      </div>

                      {/* Gemini AI Contextual Reasoning */}
                      <div className="pt-2 border-t border-slate-100">
                        <div className="rounded-xl bg-orange-50/50 border border-orange-100 p-3 space-y-1">
                          <div className="flex items-center justify-between">
                            <span className="text-[11px] font-black text-orange-800 inline-flex items-center gap-1.5">
                              <Sparkles className="h-3 w-3 text-orange-600" />
                              <span>Gemini AI Context</span>
                            </span>
                            <span
                              className={`text-[9px] font-bold px-1.5 py-0.2 rounded-md ${
                                prop.risk_level === "LOW"
                                  ? "bg-emerald-100 text-emerald-800"
                                  : prop.risk_level === "MEDIUM"
                                  ? "bg-amber-100 text-amber-800"
                                  : "bg-rose-100 text-rose-800"
                              }`}
                            >
                              Riesgo: {prop.risk_level}
                            </span>
                          </div>
                          <p className="text-[11px] text-slate-600 leading-relaxed">
                            {prop.reasoning}
                          </p>
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Quota-Saving On-Demand Empty State */}
          {!loading && !error && data && data.total_props === 0 && !analyzing && (
            <div className="rounded-3xl border-2 border-dashed border-orange-200 bg-gradient-to-b from-orange-50/40 via-white to-white p-8 sm:p-12 text-center max-w-2xl mx-auto space-y-6 shadow-xs">
              <div className="h-16 w-16 rounded-2xl bg-orange-100 text-orange-600 flex items-center justify-center mx-auto shadow-inner">
                <Zap className="h-8 w-8 text-orange-600" />
              </div>
              <div className="space-y-2">
                <h3 className="text-xl sm:text-2xl font-black text-slate-900">
                  {isEs ? "Análisis en Pausa (Ahorro de Cuota Activo)" : "Analysis on Standby (Quota-Saving Active)"}
                </h3>
                <p className="text-xs sm:text-sm text-slate-600 leading-relaxed max-w-lg mx-auto">
                  {data.slate_summary ||
                    (isEs
                      ? "Las predicciones y simulaciones Monte Carlo no se ejecutan automáticamente al iniciar Windows para no consumir cuotas de Gemini AI ni The Odds API innecesariamente."
                      : "Monte Carlo simulations and Gemini reasoning do not run on system startup to preserve API quota.")}
                </p>
              </div>

              <div className="pt-2 flex flex-col sm:flex-row items-center justify-center gap-4">
                <button
                  onClick={handleRunAnalysis}
                  disabled={analyzing}
                  className="w-full sm:w-auto rounded-2xl bg-gradient-to-r from-orange-600 via-orange-500 to-amber-600 px-6 py-3.5 text-sm font-black text-white shadow-md hover:from-orange-500 hover:to-amber-500 hover:shadow-orange-500/25 active:scale-[0.98] transition-all inline-flex items-center justify-center gap-2.5 cursor-pointer"
                >
                  <Zap className="h-4 w-4 text-amber-200 fill-amber-200" />
                  <span>{isEs ? "⚡ Iniciar Análisis de Props Ahora" : "⚡ Launch Props Analysis Now"}</span>
                </button>
              </div>

              <div className="text-[11px] text-slate-400 font-medium pt-2 border-t border-slate-100">
                {isEs
                  ? "💡 Cada ejecución corre 10,000 simulaciones Binomial Negativa por jugador, extrae líneas de The Odds API y puede despachar el reporte a Telegram."
                  : "💡 Each run computes 10,000 Negative Binomial simulations per player, fetches live sportsbook odds, and can dispatch executive alerts to Telegram."}
              </div>
            </div>
          )}

          {/* Filter Empty State (Props available but filtered out) */}
          {!loading && !error && data && data.total_props > 0 && filteredItems.length === 0 && !analyzing && (
            <div className="rounded-3xl border border-slate-200 bg-white p-12 text-center max-w-md mx-auto space-y-4 shadow-xs">
              <div className="h-12 w-12 rounded-2xl bg-slate-100 text-slate-400 flex items-center justify-center mx-auto">
                <Search className="h-6 w-6" />
              </div>
              <div className="space-y-1">
                <h4 className="text-base font-black text-slate-900">
                  {isEs ? "No se encontraron props" : "No props found"}
                </h4>
                <p className="text-xs text-slate-500">
                  {isEs
                    ? "Probá cambiando la categoría, desactivando el filtro de solo valor (+EV) o limpiando la búsqueda."
                    : "Try selecting a different stat category, disabling the value-only filter, or clearing search."}
                </p>
              </div>
              <button
                onClick={() => {
                  setSelectedCategory("ALL");
                  setOnlyValuePicks(false);
                  setSearchQuery("");
                }}
                className="px-4 py-2 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-800 text-xs font-bold transition-colors cursor-pointer"
              >
                {isEs ? "Restablecer Filtros" : "Reset Filters"}
              </button>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
