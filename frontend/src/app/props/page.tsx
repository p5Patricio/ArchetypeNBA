"use client";

import React, { useEffect, useState, useMemo, useCallback, useRef, Suspense } from "react";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { Navbar } from "@/components/Navbar";
import { CommandPalette } from "@/components/CommandPalette";
import { usePreferences } from "@/context/PreferencesContext";
import {
  getTodayProps,
  runPropsAnalysis,
  type TodayPropsResponse,
} from "@/lib/api";
import {
  RefreshCw,
  AlertCircle,
  CheckCircle2,
  Zap,
  Clock,
  Cpu,
  Layers,
  Flame,
} from "lucide-react";

import { PropsHeader } from "@/components/props/PropsHeader";
import {
  PropsFilterBar,
  type StatCategory,
  type SortOption,
  type ViewMode,
} from "@/components/props/PropsFilterBar";
import { PropCard } from "@/components/props/PropCard";
import { PropTableRow } from "@/components/props/PropTableRow";
import { PropsSkeleton } from "@/components/props/PropsSkeleton";
import { PropsEmptyState } from "@/components/props/PropsEmptyState";
import { InjuryNoticeBanner } from "@/components/props/InjuryNoticeBanner";
import { PropsQuotaAlert } from "@/components/props/PropsQuotaAlert";

const VALID_CATEGORIES: StatCategory[] = ["ALL", "POINTS", "REBOUNDS", "ASSISTS", "PRA"];
const VALID_SORTS: SortOption[] = ["EV_DESC", "EDGE_DESC", "KELLY_DESC", "LINE_DESC"];

function PropsPageContent() {
  const { language } = usePreferences();
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const [data, setData] = useState<TodayPropsResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [quotaError, setQuotaError] = useState<string | null>(null);
  const [isCommandOpen, setIsCommandOpen] = useState<boolean>(false);

  // Screen reader aria-live announcements
  const [liveAnnouncement, setLiveAnnouncement] = useState<string>("");

  // URL-synchronized Filter State
  const initialCat = (searchParams.get("cat")?.toUpperCase() as StatCategory) || "ALL";
  const [selectedCategory, setSelectedCategory] = useState<StatCategory>(
    VALID_CATEGORIES.includes(initialCat) ? initialCat : "ALL"
  );

  const initialVal = searchParams.get("val");
  const [onlyValuePicks, setOnlyValuePicks] = useState<boolean>(
    initialVal === "1" || initialVal === "true"
  );

  const [searchQuery, setSearchQuery] = useState<string>(
    searchParams.get("q") || ""
  );

  const initialSort = (searchParams.get("sort") as SortOption) || "EV_DESC";
  const [sortBy, setSortBy] = useState<SortOption>(
    VALID_SORTS.includes(initialSort) ? initialSort : "EV_DESC"
  );

  const initialView = searchParams.get("view");
  const [viewMode, setViewMode] = useState<ViewMode>(
    initialView === "table" ? "table" : "cards"
  );

  // On-demand AI Analysis & Telegram dispatch state
  const [analyzing, setAnalyzing] = useState<boolean>(false);
  const [sendTelegram, setSendTelegram] = useState<boolean>(true);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const isEs = language === "es";

  // Debounced URL state updater
  const debounceTimerRef = useRef<NodeJS.Timeout | null>(null);

  const syncStateToUrl = useCallback(
    (updates: {
      cat?: StatCategory;
      val?: boolean;
      q?: string;
      sort?: SortOption;
      view?: ViewMode;
    }) => {
      const currentCat = updates.cat !== undefined ? updates.cat : selectedCategory;
      const currentVal = updates.val !== undefined ? updates.val : onlyValuePicks;
      const currentQ = updates.q !== undefined ? updates.q : searchQuery;
      const currentSort = updates.sort !== undefined ? updates.sort : sortBy;
      const currentView = updates.view !== undefined ? updates.view : viewMode;

      const params = new URLSearchParams();
      if (currentCat !== "ALL") params.set("cat", currentCat);
      if (currentVal) params.set("val", "1");
      if (currentQ.trim()) params.set("q", currentQ.trim());
      if (currentSort !== "EV_DESC") params.set("sort", currentSort);
      if (currentView !== "cards") params.set("view", currentView);

      const qs = params.toString();
      const target = qs ? `${pathname}?${qs}` : pathname;
      router.replace(target, { scroll: false });
    },
    [selectedCategory, onlyValuePicks, searchQuery, sortBy, viewMode, pathname, router]
  );

  // Synchronize state when browser back/forward buttons are pressed
  useEffect(() => {
    const cat = (searchParams.get("cat")?.toUpperCase() as StatCategory) || "ALL";
    if (VALID_CATEGORIES.includes(cat) && cat !== selectedCategory) {
      setSelectedCategory(cat);
    }

    const val = searchParams.get("val") === "1" || searchParams.get("val") === "true";
    if (val !== onlyValuePicks) {
      setOnlyValuePicks(val);
    }

    const q = searchParams.get("q") || "";
    if (q !== searchQuery) {
      setSearchQuery(q);
    }

    const sort = (searchParams.get("sort") as SortOption) || "EV_DESC";
    if (VALID_SORTS.includes(sort) && sort !== sortBy) {
      setSortBy(sort);
    }

    const view = searchParams.get("view") === "table" ? "table" : "cards";
    if (view !== viewMode) {
      setViewMode(view);
    }
  }, [searchParams, selectedCategory, onlyValuePicks, searchQuery, sortBy, viewMode]);

  // Handlers for filter bar with immediate state update and URL sync
  const handleCategoryChange = (cat: StatCategory) => {
    setSelectedCategory(cat);
    syncStateToUrl({ cat });
  };

  const handleOnlyValueToggle = (val: boolean) => {
    setOnlyValuePicks(val);
    syncStateToUrl({ val });
  };

  const handleSearchChange = (q: string) => {
    setSearchQuery(q);
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    debounceTimerRef.current = setTimeout(() => {
      syncStateToUrl({ q });
    }, 300);
  };

  const handleSortChange = (sort: SortOption) => {
    setSortBy(sort);
    syncStateToUrl({ sort });
  };

  const handleViewModeChange = (view: ViewMode) => {
    setViewMode(view);
    syncStateToUrl({ view });
  };

  const handleResetFilters = () => {
    setSelectedCategory("ALL");
    setOnlyValuePicks(false);
    setSearchQuery("");
    setSortBy("EV_DESC");
    syncStateToUrl({ cat: "ALL", val: false, q: "", sort: "EV_DESC" });
  };

  // Data fetching logic
  const loadPropsData = useCallback(async (forceRefresh: boolean = false) => {
    if (forceRefresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);
    setQuotaError(null);

    try {
      const res = await getTodayProps({ refresh: forceRefresh });
      setData(res);
      setLiveAnnouncement(
        isEs
          ? `Proyecciones cargadas: ${res.total_props} props disponibles, ${res.value_picks_count} oportunidades con valor.`
          : `Projections loaded: ${res.total_props} props available, ${res.value_picks_count} value picks.`
      );
    } catch (err: unknown) {
      console.error("Error loading NBA props:", err);
      const msg = err instanceof Error ? err.message : String(err);
      if (
        msg.includes("429") ||
        msg.toLowerCase().includes("quota") ||
        msg.toLowerCase().includes("credit guard") ||
        msg.toLowerCase().includes("insufficient")
      ) {
        setQuotaError(msg);
        setLiveAnnouncement(
          isEs
            ? "Actualización pausada por límite de seguridad de créditos."
            : "Refresh paused by API credit guard."
        );
      } else {
        setError(
          err instanceof Error
            ? err.message
            : isEs
            ? "No se pudieron cargar las proyecciones de props."
            : "Failed to load player props projections."
        );
        setLiveAnnouncement(
          isEs ? "Error al cargar props." : "Error loading props."
        );
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [isEs]);

  const handleRunAnalysis = async () => {
    setAnalyzing(true);
    setError(null);
    setQuotaError(null);

    try {
      const res = await runPropsAnalysis({ send_telegram: sendTelegram });
      setData(res);
      const successMsg =
        res.total_props === 0
          ? isEs
            ? "Análisis completado, pero no hay líneas en vivo publicadas: no se generaron props."
            : "Analysis complete, but no live lines are posted: no props were generated."
          : isEs
          ? `¡Análisis completado! Se generaron ${res.total_props} props (${res.value_picks_count} picks con +EV).${sendTelegram ? " Reporte despachado a Telegram." : ""}`
          : `Analysis complete! Generated ${res.total_props} props (${res.value_picks_count} value picks).${sendTelegram ? " Dispatched to Telegram." : ""}`;

      setToastMessage(successMsg);
      setLiveAnnouncement(successMsg);
      setTimeout(() => setToastMessage(null), 7000);
    } catch (err: unknown) {
      console.error("Error running props analysis:", err);
      const msg = err instanceof Error ? err.message : String(err);
      if (
        msg.includes("429") ||
        msg.toLowerCase().includes("quota") ||
        msg.toLowerCase().includes("credit guard") ||
        msg.toLowerCase().includes("insufficient")
      ) {
        setQuotaError(msg);
        setLiveAnnouncement(
          isEs
            ? "Análisis pausado para proteger los créditos mensuales de The Odds API."
            : "Analysis paused to protect monthly Odds API credits."
        );
      } else {
        setError(
          err instanceof Error
            ? err.message
            : isEs
            ? "No se pudo completar el análisis con Gemini AI."
            : "Failed to run AI props analysis."
        );
        setLiveAnnouncement(
          isEs ? "Error al ejecutar análisis IA." : "Failed to run AI analysis."
        );
      }
    } finally {
      setAnalyzing(false);
    }
  };

  useEffect(() => {
    loadPropsData();
  }, [loadPropsData]);

  // Filter and sort props items
  const filteredItems = useMemo(() => {
    if (!data || !data.items) return [];

    return data.items
      .filter((item) => {
        // Category filter
        if (selectedCategory !== "ALL") {
          const st = item.stat_type.toUpperCase();
          if (selectedCategory === "POINTS" && st !== "PTS") return false;
          if (selectedCategory === "REBOUNDS" && st !== "REB") return false;
          if (selectedCategory === "ASSISTS" && st !== "AST") return false;
          if (selectedCategory === "PRA" && st !== "PRA") return false;
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

  // Determine empty states
  const hasNoLiveLines =
    !!data && data.total_props === 0 && data.odds_source.toLowerCase().includes("sin líneas en vivo");

  const hasBaselinesUnavailable =
    !!data && data.baselines_available === false;

  const isStandbyQuota =
    !!data && data.total_props === 0 && !hasNoLiveLines && !hasBaselinesUnavailable;

  const isFilterEmpty =
    !!data && data.total_props > 0 && filteredItems.length === 0;

  return (
    <div className="min-h-screen bg-[#F8FAFC] text-slate-900 selection:bg-orange-100 selection:text-orange-900">
      {/* Screen reader live region */}
      <div role="status" aria-live="polite" className="sr-only">
        {liveAnnouncement}
      </div>

      <Navbar onOpenSearch={() => setIsCommandOpen(true)} />
      <CommandPalette isOpen={isCommandOpen} onClose={() => setIsCommandOpen(false)} />

      {/* Main Container offset for desktop sidebar */}
      <div className="md:pl-64 flex flex-col min-h-screen">
        {/* ========================================================================= */}
        {/* HERO HEADER SECTION */}
        {/* ========================================================================= */}
        <PropsHeader
          stale={data?.stale}
          age={data?.age}
          date={data?.date}
          onRefresh={() => loadPropsData(true)}
          isRefreshing={refreshing}
          onRunAnalysis={handleRunAnalysis}
          isAnalyzing={analyzing}
          hasProps={Boolean(data && data.total_props > 0)}
          sendTelegram={sendTelegram}
          onToggleSendTelegram={setSendTelegram}
        />

        {/* ========================================================================= */}
        {/* ALERT & NOTIFICATION BANNERS */}
        {/* ========================================================================= */}
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 pt-6 space-y-4 w-full">
          {/* Toast Message */}
          {toastMessage && (
            <div
              role="alert"
              className="rounded-2xl border border-emerald-200 bg-emerald-50/95 p-4 shadow-xs flex items-center justify-between gap-3 animate-in fade-in slide-in-from-top-2"
            >
              <div className="flex items-center gap-3 text-xs sm:text-sm font-bold text-emerald-950">
                <CheckCircle2 className="h-5 w-5 text-emerald-600 shrink-0" />
                <span>{toastMessage}</span>
              </div>
              <button
                type="button"
                onClick={() => setToastMessage(null)}
                aria-label={isEs ? "Cerrar notificación" : "Close notification"}
                className="text-emerald-700 hover:text-emerald-900 text-xs font-bold px-2 py-1 rounded-lg hover:bg-emerald-100 transition-colors cursor-pointer"
              >
                ✕
              </button>
            </div>
          )}

          {/* HTTP 429 Quota Guard Alert */}
          {quotaError && (
            <PropsQuotaAlert
              message={quotaError}
              onRetry={() => loadPropsData(true)}
              onDismiss={() => setQuotaError(null)}
            />
          )}

          {/* Injury Information Honest State Banner */}
          {data?.injury_report && (
            <InjuryNoticeBanner injuryReport={data.injury_report} />
          )}

          {/* Active Simulation Progress Banner */}
          {analyzing && (
            <div
              role="status"
              className="rounded-3xl border border-orange-200 bg-gradient-to-r from-orange-50 via-amber-50 to-orange-50 p-6 shadow-xs flex flex-col sm:flex-row items-center justify-between gap-4 animate-in fade-in"
            >
              <div className="flex items-center gap-4">
                <div className="h-12 w-12 rounded-2xl bg-orange-600 text-white flex items-center justify-center shadow-md shadow-orange-600/20 shrink-0 animate-pulse">
                  <Zap className="h-6 w-6 text-amber-200 fill-amber-200" />
                </div>
                <div className="space-y-1">
                  <h3 className="text-sm sm:text-base font-black text-slate-900">
                    {isEs
                      ? "Simulaciones Monte Carlo & Análisis Gemini en Ejecución"
                      : "Monte Carlo Simulations & Gemini Analysis Running"}
                  </h3>
                  <p className="text-xs text-slate-600 font-medium">
                    {isEs
                      ? "Consultando The Odds API en vivo, computando 10,000 iteraciones Binomial Negativa por jugador y evaluando Expected Value (+EV)..."
                      : "Querying The Odds API live, computing 10,000 iterations per player, and evaluating +EV edges..."}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2.5 px-4 py-2 rounded-2xl bg-white/90 border border-orange-200 text-xs font-bold text-orange-800 shrink-0 shadow-2xs">
                <RefreshCw className="h-4 w-4 animate-spin text-orange-600" />
                <span>{isEs ? "Calculando distribuciones..." : "Computing distributions..."}</span>
              </div>
            </div>
          )}
        </div>

        {/* ========================================================================= */}
        {/* MAIN BODY AREA */}
        {/* ========================================================================= */}
        <main className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-8 space-y-8 w-full flex-1">
          {/* Intelligence Meta Metrics Cards */}
          {data && (
            <section
              aria-label={isEs ? "Métricas generales del slate" : "Slate summary metrics"}
              className="grid grid-cols-2 sm:grid-cols-4 gap-4"
            >
              <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-xs">
                <div className="flex items-center gap-2 text-xs font-semibold text-slate-400 mb-1">
                  <Clock className="h-3.5 w-3.5 text-slate-400" />
                  <span>{isEs ? "Fecha del Slate" : "Slate Date"}</span>
                </div>
                <div className="text-base font-black text-slate-900 tabular-nums">
                  {data.date}
                </div>
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
                <div className="text-base font-black text-slate-900 tabular-nums">
                  {data.total_props}
                </div>
              </div>

              <div className="rounded-2xl border border-emerald-200 bg-emerald-50/40 p-4 shadow-xs">
                <div className="flex items-center gap-2 text-xs font-semibold text-emerald-700 mb-1">
                  <Flame className="h-3.5 w-3.5 text-emerald-600" />
                  <span>{isEs ? "Oportunidades +EV" : "+EV Value Picks"}</span>
                </div>
                <div className="text-base font-black text-emerald-700 flex items-center gap-1.5 tabular-nums">
                  <span>{data.value_picks_count}</span>
                  <span className="text-xs font-medium text-emerald-600">
                    {isEs ? "picks con valor" : "value picks"}
                  </span>
                </div>
              </div>
            </section>
          )}

          {/* Filter Bar */}
          <PropsFilterBar
            selectedCategory={selectedCategory}
            onSelectCategory={handleCategoryChange}
            onlyValuePicks={onlyValuePicks}
            onToggleOnlyValue={handleOnlyValueToggle}
            searchQuery={searchQuery}
            onSearchChange={handleSearchChange}
            sortBy={sortBy}
            onSortChange={handleSortChange}
            viewMode={viewMode}
            onViewModeChange={handleViewModeChange}
            totalFilteredCount={filteredItems.length}
          />

          {/* Loading Skeleton */}
          {loading && <PropsSkeleton />}

          {/* Error State with Retry Button */}
          {error && !loading && !quotaError && (
            <div
              role="alert"
              className="rounded-3xl border border-rose-200 bg-rose-50/80 p-8 text-center space-y-4 max-w-lg mx-auto shadow-xs"
            >
              <div className="h-14 w-14 rounded-2xl bg-rose-100 text-rose-600 flex items-center justify-center mx-auto">
                <AlertCircle className="h-7 w-7" />
              </div>
              <div className="space-y-1.5">
                <h3 className="text-base sm:text-lg font-black text-rose-950">
                  {isEs ? "Error al cargar props" : "Error loading props"}
                </h3>
                <p className="text-xs text-rose-700 leading-relaxed">{error}</p>
              </div>
              <button
                type="button"
                onClick={() => loadPropsData(true)}
                className="px-5 py-2.5 rounded-2xl bg-rose-600 text-white text-xs font-bold hover:bg-rose-700 transition-colors inline-flex items-center gap-2 shadow-xs cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-500"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                <span>{isEs ? "Reintentar carga" : "Retry load"}</span>
              </button>
            </div>
          )}

          {/* ========================================================================= */}
          {/* EMPTY STATES */}
          {/* ========================================================================= */}
          {!loading && !error && !quotaError && !analyzing && (
            <>
              {/* 1. Baselines Unavailable (Data Honesty) */}
              {hasBaselinesUnavailable && (
                <PropsEmptyState
                  type="NO_BASELINES"
                  onRunAnalysis={handleRunAnalysis}
                  isAnalyzing={analyzing}
                />
              )}

              {/* 2. No Live Lines Posted */}
              {!hasBaselinesUnavailable && hasNoLiveLines && (
                <PropsEmptyState
                  type="NO_LIVE_LINES"
                  onRunAnalysis={handleRunAnalysis}
                  isAnalyzing={analyzing}
                />
              )}

              {/* 3. Standby Quota Protection Mode */}
              {!hasBaselinesUnavailable && !hasNoLiveLines && isStandbyQuota && (
                <PropsEmptyState
                  type="STANDBY_QUOTA"
                  slateSummary={data?.slate_summary}
                  onRunAnalysis={handleRunAnalysis}
                  isAnalyzing={analyzing}
                />
              )}

              {/* 4. Filter Empty State */}
              {!hasBaselinesUnavailable && !hasNoLiveLines && !isStandbyQuota && isFilterEmpty && (
                <PropsEmptyState
                  type="FILTER_EMPTY"
                  onClearFilters={handleResetFilters}
                  activeFiltersDesc={{
                    category: selectedCategory,
                    onlyValue: onlyValuePicks,
                    searchQuery: searchQuery,
                  }}
                />
              )}
            </>
          )}

          {/* ========================================================================= */}
          {/* RESULTS DISPLAY: CARDS GRID OR TABLE */}
          {/* ========================================================================= */}
          {!loading && !error && !quotaError && filteredItems.length > 0 && (
            <section
              aria-label={isEs ? "Listado de props evaluados" : "Evaluated props list"}
              className="space-y-4"
            >
              {viewMode === "cards" ? (
                /* Card Grid View (Responsive from 360px to 4K) */
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
                  {filteredItems.map((prop, idx) => (
                    <PropCard
                      key={`${prop.player_name}-${prop.stat_type}-${prop.line}-${idx}`}
                      prop={prop}
                    />
                  ))}
                </div>
              ) : (
                /* Accessible Table View (Wide Screens / Tabular Mode) */
                <div className="rounded-3xl border border-slate-200 bg-white shadow-xs overflow-hidden">
                  <div className="overflow-x-auto">
                    <table className="w-full text-left border-collapse">
                      <caption className="sr-only">
                        {isEs
                          ? "Tabla de recomendaciones de props de jugadores NBA"
                          : "NBA player props recommendation table"}
                      </caption>
                      <thead>
                        <tr className="bg-slate-50 border-b border-slate-200 text-[10px] font-extrabold uppercase tracking-wider text-slate-400">
                          <th scope="col" className="py-3 px-4">
                            {isEs ? "Jugador / Equipo" : "Player / Team"}
                          </th>
                          <th scope="col" className="py-3 px-3">
                            {isEs ? "Línea / Cuota" : "Line / Odds"}
                          </th>
                          <th scope="col" className="py-3 px-3 text-center">
                            {isEs ? "Modelo vs Casa" : "Model vs Book"}
                          </th>
                          <th scope="col" className="py-3 px-3 text-center">
                            {isEs ? "Ventaja (Edge)" : "Model Edge"}
                          </th>
                          <th scope="col" className="py-3 px-3 text-center">
                            Expected Value
                          </th>
                          <th scope="col" className="py-3 px-3 text-center">
                            Kelly %
                          </th>
                          <th scope="col" className="py-3 px-3 text-center">
                            {isEs ? "Dictamen" : "Recommendation"}
                          </th>
                          <th scope="col" className="py-3 px-3 text-right">
                            {isEs ? "Detalles" : "Details"}
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {filteredItems.map((prop, idx) => (
                          <PropTableRow
                            key={`table-${prop.player_name}-${prop.stat_type}-${prop.line}-${idx}`}
                            prop={prop}
                          />
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </section>
          )}
        </main>
      </div>
    </div>
  );
}

export default function PropsPage() {
  return (
    <Suspense fallback={<PropsSkeleton />}>
      <PropsPageContent />
    </Suspense>
  );
}
