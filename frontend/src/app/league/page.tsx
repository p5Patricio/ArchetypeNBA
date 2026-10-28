"use client";

import React, { useEffect, useState, useCallback } from "react";
import { Navbar } from "@/components/Navbar";
import { CommandPalette } from "@/components/CommandPalette";
import { usePreferences } from "@/context/PreferencesContext";
import { getLeague, type LeagueResponse } from "@/lib/api";
import { ChampionCard } from "@/components/league/ChampionCard";
import { ChallengerCard } from "@/components/league/ChallengerCard";
import { RoleHistoryTable } from "@/components/league/RoleHistoryTable";
import { ProposalInfoCard } from "@/components/league/ProposalInfoCard";
import { HowToReadPanel } from "@/components/league/HowToReadPanel";
import {
  Trophy,
  RefreshCw,
  Clock,
  AlertCircle,
  GitCompare,
} from "lucide-react";

export default function ModelLeaguePage() {
  const { language } = usePreferences();
  const isEs = language === "es";

  const [data, setData] = useState<LeagueResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isCommandOpen, setIsCommandOpen] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<string>("");

  const formatUpdateTime = useCallback((date: Date) => {
    return date.toLocaleTimeString(isEs ? "es-MX" : "en-US", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  }, [isEs]);

  const fetchLeagueData = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoading(true);
    setError(null);

    try {
      const res = await getLeague();
      setData(res);
      setLastUpdated(formatUpdateTime(new Date()));
    } catch (err: unknown) {
      console.error("Error fetching model league data:", err);
      setError(
        err instanceof Error
          ? err.message
          : isEs
          ? "No se pudo cargar la información de la Liga de Modelos."
          : "Failed to load Model League data."
      );
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [isEs, formatUpdateTime]);

  useEffect(() => {
    fetchLeagueData();
  }, [fetchLeagueData]);

  // Auto-refresh every 5 minutes while visible
  useEffect(() => {
    let intervalId: NodeJS.Timeout | null = null;

    const tick = () => {
      if (document.visibilityState === "visible") {
        fetchLeagueData(true);
      }
    };

    intervalId = setInterval(tick, 300000); // 5 minutes

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
  }, [fetchLeagueData]);

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
                {/* Pill Badge */}
                <div className="inline-flex items-center gap-2 rounded-full border border-violet-200 bg-violet-50 px-3.5 py-1 text-xs font-black text-violet-800 shadow-2xs">
                  <Trophy className="h-3.5 w-3.5 text-violet-600" />
                  <span>
                    {isEs
                      ? "LIGA CUANTITATIVA DE MODELOS • GOBERNANZA ESTADÍSTICA"
                      : "QUANT MODEL LEAGUE • STATISTICAL GOVERNANCE"}
                  </span>
                </div>

                {/* Headline */}
                <h1 className="text-3xl sm:text-4xl font-black tracking-tight text-slate-900">
                  {isEs ? "Model League: Campeón vs Retadores" : "Model League: Champion vs Challengers"}
                </h1>

                {/* Subtitle */}
                <p className="max-w-3xl text-xs sm:text-sm text-slate-600 font-normal leading-relaxed">
                  {isEs
                    ? "Competencia continua en sombra donde modelos retadores predicen partidos en paralelo. Ningún modelo reemplaza al campeón a menos que supere rigurosas compuertas estadísticas (bootstrap log-loss gain > 0 con 95% de confianza sobre al menos 150 partidos)."
                    : "Continuous shadow competition where candidate models predict upcoming games in parallel. No model replaces the champion unless it clears rigorous statistical gates (bootstrap log-loss gain > 0 at 95% confidence over at least 150 games)."}
                </p>
              </div>

              {/* Action Controls & Update Status */}
              <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3 shrink-0">
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

                <button
                  type="button"
                  onClick={() => fetchLeagueData(true)}
                  disabled={refreshing || loading}
                  aria-label={isEs ? "Actualizar liga de modelos" : "Refresh model league"}
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
                onClick={() => fetchLeagueData(true)}
                className="text-xs font-black text-rose-700 hover:text-rose-900 underline cursor-pointer"
              >
                {isEs ? "Reintentar" : "Retry"}
              </button>
            </div>
          </div>
        )}

        {/* Main Content Body */}
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-8 space-y-8">
          {/* 1. Collapsible Educational Panel */}
          <section aria-labelledby="guide-heading">
            <h2 id="guide-heading" className="sr-only">
              {isEs ? "Guía de Lectura" : "Reading Guide"}
            </h2>
            <HowToReadPanel />
          </section>

          {/* 2. Active Champion Header Card */}
          <section aria-labelledby="champion-heading">
            <h2 id="champion-heading" className="sr-only">
              {isEs ? "Modelo Campeón" : "Champion Model"}
            </h2>
            <ChampionCard champion={data?.champion} loading={loading} />
          </section>

          {/* 3. Shadow Challengers Section */}
          <section aria-labelledby="challengers-heading" className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 id="challengers-heading" className="text-xl sm:text-2xl font-black text-slate-900 tracking-tight">
                  {isEs ? "Retadores en Sombra (Shadow Challengers)" : "Active Shadow Challengers"}
                </h2>
                <p className="text-xs sm:text-sm text-slate-500 mt-0.5">
                  {isEs
                    ? "Modelos evaluados partido a partido en pares idénticos contra el campeón para auditar ventaja predictiva pura."
                    : "Models evaluated game-by-game on paired outcomes against the champion to audit statistical skill."}
                </p>
              </div>
              <span className="text-xs font-mono font-bold bg-slate-100 text-slate-600 px-3 py-1 rounded-xl border border-slate-200">
                {data?.challengers?.length || 0} {isEs ? "retadores" : "challengers"}
              </span>
            </div>

            {loading ? (
              <div className="space-y-4 animate-pulse">
                <div className="h-64 bg-slate-100 rounded-3xl" />
              </div>
            ) : !data?.challengers || data.challengers.length === 0 ? (
              <div className="rounded-3xl border border-dashed border-slate-300 bg-white p-8 text-center">
                <GitCompare className="mx-auto h-8 w-8 text-slate-400 mb-2" />
                <p className="text-sm font-semibold text-slate-700">
                  {isEs ? "No hay retadores en sombra activos" : "No active shadow challengers"}
                </p>
                <p className="text-xs text-slate-500 mt-1 max-w-sm mx-auto">
                  {isEs
                    ? "El laboratorio de candidatos propondrá nuevos modelos automáticamente en la próxima corrida de optimización."
                    : "The candidate lab will automatically propose new models during its weekly search run."}
                </p>
              </div>
            ) : (
              <div className="space-y-6">
                {data.challengers.map((challenger) => (
                  <ChallengerCard key={challenger.model_id} challenger={challenger} />
                ))}
              </div>
            )}
          </section>

          {/* 4. Candidate Proposal Information */}
          <section aria-labelledby="proposal-heading">
            <h2 id="proposal-heading" className="sr-only">
              {isEs ? "Propuestas de Candidatos" : "Candidate Proposals"}
            </h2>
            <ProposalInfoCard
              lastProposal={data?.last_proposal}
              lastProposalSummary={data?.last_proposal_summary}
            />
          </section>

          {/* 5. Promotion & Role Transition History */}
          <section aria-labelledby="history-heading">
            <h2 id="history-heading" className="sr-only">
              {isEs ? "Historial de Cambios de Rol" : "Role Transition History"}
            </h2>
            <RoleHistoryTable changes={data?.changes || []} />
          </section>
        </div>
      </main>
    </div>
  );
}
