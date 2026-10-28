"use client";

import React, { useEffect, useState, useCallback } from "react";
import { Navbar } from "@/components/Navbar";
import { CommandPalette } from "@/components/CommandPalette";
import { usePreferences } from "@/context/PreferencesContext";
import {
  getPaperSummary,
  getPaperBets,
  getPaperBankroll,
  type PaperSummaryResponse,
  type PaperBetsListResponse,
  type PaperBankrollResponse,
} from "@/lib/api";
import { StrategyKpis } from "@/components/paper/StrategyKpis";
import { EvidenceCard } from "@/components/paper/EvidenceCard";
import { BankrollChart } from "@/components/paper/BankrollChart";
import { BetsTable } from "@/components/paper/BetsTable";
import {
  Banknote,
  ShieldAlert,
  RefreshCw,
  Clock,
  AlertCircle,
} from "lucide-react";

export default function PaperTradingPage() {
  const { language } = usePreferences();
  const isEs = language === "es";

  // Data states
  const [summary, setSummary] = useState<PaperSummaryResponse | null>(null);
  const [bankroll, setBankroll] = useState<PaperBankrollResponse | null>(null);
  const [betsData, setBetsData] = useState<PaperBetsListResponse | null>(null);

  // Loading & error states
  const [loadingSummary, setLoadingSummary] = useState(true);
  const [loadingBankroll, setLoadingBankroll] = useState(true);
  const [loadingBets, setLoadingBets] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [betsError, setBetsError] = useState<string | null>(null);

  // Command palette state
  const [isCommandOpen, setIsCommandOpen] = useState(false);

  // Pagination & Filters
  const [page, setPage] = useState(1);
  const [strategyFilter, setStrategyFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const pageSize = 50;

  // Last updated timestamp
  const [lastUpdated, setLastUpdated] = useState<string>("");

  const formatUpdateTime = useCallback((date: Date) => {
    return date.toLocaleTimeString(isEs ? "es-MX" : "en-US", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  }, [isEs]);

  const fetchSummaryAndBankroll = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else {
      setLoadingSummary(true);
      setLoadingBankroll(true);
    }
    setError(null);

    try {
      const [sumRes, bkrRes] = await Promise.all([
        getPaperSummary(),
        getPaperBankroll(),
      ]);
      setSummary(sumRes);
      setBankroll(bkrRes);
      setLastUpdated(formatUpdateTime(new Date()));
    } catch (err: unknown) {
      console.error("Error fetching paper trading summary:", err);
      setError(
        err instanceof Error
          ? err.message
          : isEs
          ? "No se pudo cargar el resumen de paper trading."
          : "Failed to load paper trading summary."
      );
    } finally {
      setLoadingSummary(false);
      setLoadingBankroll(false);
      setRefreshing(false);
    }
  }, [isEs, formatUpdateTime]);

  const fetchBets = useCallback(async () => {
    setLoadingBets(true);
    setBetsError(null);

    try {
      const offset = (page - 1) * pageSize;
      const res = await getPaperBets({
        strategy: strategyFilter !== "all" ? strategyFilter : undefined,
        status: statusFilter !== "all" ? statusFilter : undefined,
        limit: pageSize,
        offset,
      });
      setBetsData(res);
    } catch (err: unknown) {
      console.error("Error fetching paper bets:", err);
      setBetsError(
        err instanceof Error
          ? err.message
          : isEs
          ? "No se pudo obtener el historial de apuestas."
          : "Failed to load paper bets list."
      );
    } finally {
      setLoadingBets(false);
    }
  }, [page, strategyFilter, statusFilter, isEs]);

  // Initial load
  useEffect(() => {
    fetchSummaryAndBankroll();
  }, [fetchSummaryAndBankroll]);

  // Re-fetch bets when filter or page changes
  useEffect(() => {
    fetchBets();
  }, [fetchBets]);

  // Auto-refresh every 2 minutes while tab is visible
  useEffect(() => {
    let intervalId: NodeJS.Timeout | null = null;

    const tick = () => {
      if (document.visibilityState === "visible") {
        fetchSummaryAndBankroll(true);
        fetchBets();
      }
    };

    intervalId = setInterval(tick, 120000); // 2 minutes

    const handleVisibility = () => {
      if (document.visibilityState === "visible") {
        tick();
      }
    };

    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      if (intervalId) clearInterval(intervalId);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [fetchSummaryAndBankroll, fetchBets]);

  const handleManualRefresh = () => {
    fetchSummaryAndBankroll(true);
    fetchBets();
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
        <section className="relative border-b border-slate-200 bg-gradient-to-b from-orange-50/40 via-white to-white py-10 lg:py-14 shadow-2xs">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
              <div className="space-y-3">
                {/* STRICT PAPER TRADING BADGE */}
                <div className="flex flex-wrap items-center gap-2">
                  <div className="inline-flex items-center gap-2 rounded-full border border-emerald-300 bg-emerald-50 px-3.5 py-1 text-xs font-black text-emerald-800 shadow-2xs">
                    <Banknote className="h-3.5 w-3.5 text-emerald-600" />
                    <span>
                      {isEs
                        ? "SIMULACIÓN PAPER TRADING • CAPITAL FICTICIO"
                        : "SIMULATED PAPER TRADING • VIRTUAL FUNDS"}
                    </span>
                  </div>

                  <div className="inline-flex items-center gap-1.5 rounded-full border border-amber-300 bg-amber-50 px-3 py-1 text-xs font-bold text-amber-900 shadow-2xs">
                    <ShieldAlert className="h-3.5 w-3.5 text-amber-600" />
                    <span>
                      {isEs
                        ? "Sin dinero real • Fines de investigación cuantitativa"
                        : "Simulated money — no real bets, research only"}
                    </span>
                  </div>
                </div>

                {/* Headline */}
                <h1 className="text-3xl sm:text-4xl font-black tracking-tight text-slate-900">
                  {isEs ? "Paper Trading & Validación de Estrategias" : "Paper Trading & Strategy Validation"}
                </h1>

                {/* Subtitle */}
                <p className="max-w-3xl text-xs sm:text-sm text-slate-600 font-normal leading-relaxed">
                  {isEs
                    ? "Seguimiento en tiempo real de apuestas simuladas generadas por el modelo campeón. Comparamos ejecución con cuotas de apertura frente al cierre de Pinnacle para medir valor de línea de cierre (CLV) y descartar varianza de corto plazo."
                    : "Real-time tracking of simulated paper bets executed by the champion model. We benchmark opening quotes against Pinnacle's sharp closing price to measure Closing Line Value (CLV) and isolate statistical skill from sample noise."}
                </p>
              </div>

              {/* Action Controls & Update Status */}
              <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3 shrink-0">
                {/* Updated timestamp */}
                {lastUpdated && (
                  <div
                    className="flex items-center gap-1.5 text-xs text-slate-500 bg-white border border-slate-200 px-3 py-2 rounded-2xl shadow-2xs font-mono"
                    aria-live="polite"
                  >
                    <Clock className="h-3.5 w-3.5 text-slate-400" />
                    <span>
                      {isEs ? "Actualizado:" : "Updated:"} {lastUpdated}
                    </span>
                  </div>
                )}

                {/* Refresh button */}
                <button
                  type="button"
                  onClick={handleManualRefresh}
                  disabled={refreshing || loadingSummary}
                  aria-label={isEs ? "Actualizar datos de paper trading" : "Refresh paper trading data"}
                  className="rounded-2xl border border-slate-200 bg-white px-4 py-2 text-xs font-bold text-slate-700 shadow-2xs hover:border-orange-300 hover:bg-orange-50/40 transition-all inline-flex items-center gap-2 disabled:opacity-50 cursor-pointer focus-visible:ring-2 focus-visible:ring-orange-500 outline-none"
                >
                  <RefreshCw
                    className={`h-3.5 w-3.5 text-slate-600 ${refreshing ? "animate-spin text-orange-600" : ""}`}
                  />
                  <span>
                    {refreshing
                      ? isEs
                        ? "Actualizando..."
                        : "Refreshing..."
                      : isEs
                      ? "Actualizar"
                      : "Refresh"}
                  </span>
                </button>
              </div>
            </div>
          </div>
        </section>

        {/* Global Error Banner */}
        {error && (
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 pt-6">
            <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4 shadow-sm flex items-center justify-between gap-3">
              <div className="flex items-center gap-3 text-xs sm:text-sm font-bold text-rose-950">
                <AlertCircle className="h-5 w-5 text-rose-600 shrink-0" />
                <span>{error}</span>
              </div>
              <button
                type="button"
                onClick={handleManualRefresh}
                className="text-xs font-black text-rose-700 hover:text-rose-900 underline cursor-pointer"
              >
                {isEs ? "Reintentar" : "Retry"}
              </button>
            </div>
          </div>
        )}

        {/* Content Body */}
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-8 space-y-8">
          {/* 1. Strategy KPI Cards */}
          <section aria-labelledby="kpis-heading">
            <h2 id="kpis-heading" className="sr-only">
              {isEs ? "Métricas de Estrategias" : "Strategy Metrics"}
            </h2>
            <StrategyKpis
              strategies={summary?.strategies || []}
              loading={loadingSummary}
            />
          </section>

          {/* 2. Pinnacle-referenced CLV Evidence Card */}
          <section aria-labelledby="evidence-heading">
            <h2 id="evidence-heading" className="sr-only">
              {isEs ? "Evidencia de Ventaja y CLV" : "Edge Evidence and CLV"}
            </h2>
            <EvidenceCard
              pinnacleClv={summary?.pinnacle_clv}
              brier={summary?.brier}
              loading={loadingSummary}
            />
          </section>

          {/* 3. Bankroll Trajectory Chart */}
          <section aria-labelledby="chart-heading">
            <h2 id="chart-heading" className="sr-only">
              {isEs ? "Gráfico de Bankroll" : "Bankroll Chart"}
            </h2>
            <BankrollChart data={bankroll} loading={loadingBankroll} />
          </section>

          {/* 4. Bets Table & Ledger */}
          <section aria-labelledby="bets-heading">
            <h2 id="bets-heading" className="sr-only">
              {isEs ? "Listado de Apuestas" : "Bets List"}
            </h2>
            <BetsTable
              bets={betsData?.bets || []}
              total={betsData?.total || 0}
              loading={loadingBets}
              error={betsError}
              onRetry={fetchBets}
              strategyFilter={strategyFilter}
              onStrategyFilterChange={setStrategyFilter}
              statusFilter={statusFilter}
              onStatusFilterChange={setStatusFilter}
              page={page}
              onPageChange={setPage}
              pageSize={pageSize}
            />
          </section>
        </div>
      </main>
    </div>
  );
}
