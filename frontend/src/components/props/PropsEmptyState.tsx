"use client";

import React from "react";
import {
  Database,
  Search,
  Zap,
  AlertCircle,
  RotateCcw,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";
import { usePreferences } from "@/context/PreferencesContext";

export type EmptyStateType =
  | "NO_BASELINES"
  | "NO_LIVE_LINES"
  | "STANDBY_QUOTA"
  | "FILTER_EMPTY";

interface PropsEmptyStateProps {
  type: EmptyStateType;
  slateSummary?: string;
  onRunAnalysis?: () => void;
  isAnalyzing?: boolean;
  onClearFilters?: () => void;
  activeFiltersDesc?: {
    category?: string;
    onlyValue?: boolean;
    searchQuery?: string;
  };
  className?: string;
}

export function PropsEmptyState({
  type,
  slateSummary,
  onRunAnalysis,
  isAnalyzing = false,
  onClearFilters,
  activeFiltersDesc,
  className = "",
}: PropsEmptyStateProps) {
  const { language } = usePreferences();
  const isEs = language === "es";

  // 1. Baselines Unavailable (strict data honesty - never fabricate synthetic player stats)
  if (type === "NO_BASELINES") {
    return (
      <div
        className={`rounded-3xl border border-slate-200 bg-white p-8 sm:p-12 text-center max-w-2xl mx-auto space-y-5 shadow-xs ${className}`}
      >
        <div className="h-16 w-16 rounded-2xl bg-amber-50 text-amber-600 border border-amber-200 flex items-center justify-center mx-auto shadow-2xs">
          <Database className="h-8 w-8" />
        </div>
        <div className="space-y-2">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-slate-100 text-slate-700 text-[11px] font-bold">
            <ShieldAlert className="h-3.5 w-3.5 text-amber-600" />
            <span>{isEs ? "Regla de Honestidad de Datos" : "Data Honesty Rule"}</span>
          </div>
          <h3 className="text-xl sm:text-2xl font-black text-slate-900">
            {isEs
              ? "Sin líneas base de jugadores en la base de datos"
              : "No player baselines found in database"}
          </h3>
          <p className="text-xs sm:text-sm text-slate-600 leading-relaxed max-w-lg mx-auto font-medium">
            {isEs
              ? "Para no fabricar datos estadísticos ficticios, el motor cuantitativo de props requiere registros históricos reales de jugadores en PostgreSQL para calcular las distribuciones Binomial Negativa. No se generan jugadores simulados."
              : "To prevent fabricating synthetic stats, the quantitative props engine requires verified historical player game logs in PostgreSQL to compute Negative Binomial distributions. No synthetic players are simulated."}
          </p>
        </div>

        <div className="rounded-2xl bg-slate-50 border border-slate-200 p-4 max-w-md mx-auto text-left text-xs space-y-1.5 text-slate-600">
          <span className="font-bold text-slate-800">
            {isEs ? "Pasos para habilitar proyecciones:" : "Steps to populate baselines:"}
          </span>
          <ol className="list-decimal list-inside space-y-1 text-[11px]">
            <li>{isEs ? "Ejecutar la ingesta de estadísticas de jugadores (ETL)." : "Run player stats ingestion pipeline (ETL)."}</li>
            <li>{isEs ? "Comprobar que la base de datos PostgreSQL contenga la temporada activa." : "Verify PostgreSQL contains historical game logs for the active season."}</li>
            <li>{isEs ? "Reintentar el análisis cuantitativo de props." : "Rerun props simulation analysis."}</li>
          </ol>
        </div>

        {onRunAnalysis && (
          <button
            type="button"
            onClick={onRunAnalysis}
            disabled={isAnalyzing}
            className="rounded-2xl border border-slate-300 bg-white px-5 py-2.5 text-xs font-bold text-slate-700 shadow-2xs hover:bg-slate-50 transition-all inline-flex items-center gap-2 cursor-pointer disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-500"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${isAnalyzing ? "animate-spin text-orange-600" : ""}`} />
            <span>{isEs ? "Comprobar de nuevo" : "Check again"}</span>
          </button>
        )}
      </div>
    );
  }

  // 2. No Live Lines from Sportsbooks
  if (type === "NO_LIVE_LINES") {
    return (
      <div
        className={`rounded-3xl border border-slate-200 bg-white p-8 sm:p-12 text-center max-w-2xl mx-auto space-y-5 shadow-xs ${className}`}
      >
        <div className="h-16 w-16 rounded-2xl bg-slate-100 text-slate-500 flex items-center justify-center mx-auto">
          <AlertCircle className="h-8 w-8" />
        </div>
        <div className="space-y-2">
          <h3 className="text-xl sm:text-2xl font-black text-slate-900">
            {isEs ? "Sin líneas de props en vivo" : "No live prop lines posted"}
          </h3>
          <p className="text-xs sm:text-sm text-slate-600 leading-relaxed max-w-lg mx-auto">
            {isEs
              ? "Ninguna casa de apuestas ha publicado cuotas de jugadores para los partidos de hoy (o la jornada aún no tiene mercados abiertos). No se muestran recomendaciones porque no existen precios reales contra los cuales comparar."
              : "No sportsbook has published player prop quotes for today's slate yet (or markets are not open). No picks are evaluated because there are no real market quotes to evaluate against."}
          </p>
        </div>

        {onRunAnalysis && (
          <button
            type="button"
            onClick={onRunAnalysis}
            disabled={isAnalyzing}
            className="rounded-2xl border border-slate-200 bg-white px-5 py-2.5 text-xs font-bold text-slate-700 shadow-2xs hover:border-orange-300 hover:bg-orange-50/40 transition-all inline-flex items-center gap-2 cursor-pointer disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-500"
          >
            <RefreshCw className={`h-3.5 w-3.5 text-slate-500 ${isAnalyzing ? "animate-spin text-orange-600" : ""}`} />
            <span>{isEs ? "Reintentar consulta de cuotas" : "Retry fetching odds"}</span>
          </button>
        )}
      </div>
    );
  }

  // 3. Standby Quota-Saving Initial State
  if (type === "STANDBY_QUOTA") {
    return (
      <div
        className={`rounded-3xl border-2 border-dashed border-orange-200 bg-gradient-to-b from-orange-50/40 via-white to-white p-8 sm:p-12 text-center max-w-2xl mx-auto space-y-6 shadow-xs ${className}`}
      >
        <div className="h-16 w-16 rounded-2xl bg-orange-100 text-orange-600 flex items-center justify-center mx-auto shadow-inner">
          <Zap className="h-8 w-8 text-orange-600" />
        </div>

        <div className="space-y-2">
          <h3 className="text-xl sm:text-2xl font-black text-slate-900">
            {isEs ? "Análisis en Pausa (Ahorro de Cuota Activo)" : "Analysis on Standby (Quota Protection Active)"}
          </h3>
          <p className="text-xs sm:text-sm text-slate-600 leading-relaxed max-w-lg mx-auto font-medium">
            {slateSummary ||
              (isEs
                ? "Las predicciones y simulaciones Monte Carlo no se ejecutan automáticamente para no consumir tu cuota gratuita mensual de The Odds API y Gemini AI."
                : "Monte Carlo simulations and live odds fetches do not run automatically to preserve your monthly API credits.")}
          </p>
        </div>

        {onRunAnalysis && (
          <div className="pt-2 flex flex-col sm:flex-row items-center justify-center gap-4">
            <button
              type="button"
              onClick={onRunAnalysis}
              disabled={isAnalyzing}
              className="w-full sm:w-auto rounded-2xl bg-gradient-to-r from-orange-600 via-orange-500 to-amber-600 px-6 py-3.5 text-sm font-black text-white shadow-md hover:from-orange-500 hover:to-amber-500 hover:shadow-orange-500/25 active:scale-[0.98] transition-all inline-flex items-center justify-center gap-2.5 cursor-pointer disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-500"
            >
              {isAnalyzing ? (
                <RefreshCw className="h-4 w-4 animate-spin text-white" />
              ) : (
                <Zap className="h-4 w-4 text-amber-200 fill-amber-200" />
              )}
              <span>
                {isAnalyzing
                  ? isEs
                    ? "Ejecutando 10,000 simulaciones..."
                    : "Running 10k simulations..."
                  : isEs
                  ? "⚡ Iniciar Análisis de Props Ahora"
                  : "⚡ Launch Props Analysis Now"}
              </span>
            </button>
          </div>
        )}

        <div className="text-[11px] text-slate-400 font-medium pt-3 border-t border-slate-100">
          {isEs
            ? "💡 Simulación cuantitativa (paper trading) con 10,000 corridas Binomial Negativa por jugador y gestión Quarter-Kelly."
            : "💡 Quantitative paper trading simulation using 10,000 Negative Binomial runs per player and Quarter-Kelly sizing."}
        </div>
      </div>
    );
  }

  // 4. Filter Empty State (Props available but filtered out by user query/toggles)
  const filtersList: string[] = [];
  if (activeFiltersDesc?.category && activeFiltersDesc.category !== "ALL") {
    filtersList.push(
      isEs
        ? `Categoría: ${activeFiltersDesc.category}`
        : `Category: ${activeFiltersDesc.category}`
    );
  }
  if (activeFiltersDesc?.onlyValue) {
    filtersList.push(isEs ? "Solo picks con +EV" : "Only +EV value picks");
  }
  if (activeFiltersDesc?.searchQuery) {
    filtersList.push(
      isEs
        ? `Búsqueda: "${activeFiltersDesc.searchQuery}"`
        : `Search: "${activeFiltersDesc.searchQuery}"`
    );
  }

  return (
    <div
      className={`rounded-3xl border border-slate-200 bg-white p-8 sm:p-12 text-center max-w-md mx-auto space-y-5 shadow-xs ${className}`}
    >
      <div className="h-14 w-14 rounded-2xl bg-slate-100 text-slate-400 flex items-center justify-center mx-auto">
        <Search className="h-7 w-7" />
      </div>

      <div className="space-y-2">
        <h4 className="text-lg font-black text-slate-900">
          {isEs ? "No se encontraron props con los filtros activos" : "No props match your active filters"}
        </h4>
        <p className="text-xs text-slate-500 leading-relaxed">
          {isEs
            ? "Los siguientes filtros combinados están ocultando todos los resultados disponibles:"
            : "The following combination of filters is hiding all available picks:"}
        </p>

        {filtersList.length > 0 && (
          <div className="flex flex-wrap items-center justify-center gap-1.5 pt-1">
            {filtersList.map((f, i) => (
              <span
                key={i}
                className="inline-block rounded-lg bg-orange-50 border border-orange-200 px-2 py-0.5 text-[11px] font-semibold text-orange-800"
              >
                {f}
              </span>
            ))}
          </div>
        )}
      </div>

      {onClearFilters && (
        <button
          type="button"
          onClick={onClearFilters}
          className="rounded-2xl bg-slate-900 hover:bg-slate-800 text-white px-5 py-2.5 text-xs font-bold transition-all shadow-xs inline-flex items-center gap-2 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-500"
        >
          <RotateCcw className="h-3.5 w-3.5" />
          <span>{isEs ? "Restablecer todos los filtros" : "Clear all filters"}</span>
        </button>
      )}
    </div>
  );
}
