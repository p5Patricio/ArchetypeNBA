"use client";

import React from "react";
import { TrendingUp, Send, Zap, RefreshCw, AlertCircle } from "lucide-react";
import { usePreferences } from "@/context/PreferencesContext";
import { DataFreshnessChip } from "./DataFreshnessChip";

interface PropsHeaderProps {
  stale?: boolean;
  age?: string | null;
  date?: string;
  onRefresh: () => void;
  isRefreshing: boolean;
  onRunAnalysis: () => void;
  isAnalyzing: boolean;
  hasProps: boolean;
  sendTelegram: boolean;
  onToggleSendTelegram: (val: boolean) => void;
  className?: string;
}

export function PropsHeader({
  stale,
  age,
  date,
  onRefresh,
  isRefreshing,
  onRunAnalysis,
  isAnalyzing,
  hasProps,
  sendTelegram,
  onToggleSendTelegram,
  className = "",
}: PropsHeaderProps) {
  const { language } = usePreferences();
  const isEs = language === "es";

  return (
    <section
      aria-labelledby="props-page-title"
      className={`relative border-b border-slate-200 bg-gradient-to-b from-orange-50/40 via-white to-white py-10 lg:py-14 shadow-2xs ${className}`}
    >
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 space-y-6">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-6">
          {/* Left: Pill, Title, Subtitle, Disclaimer */}
          <div className="space-y-3 max-w-3xl">
            <div className="flex flex-wrap items-center gap-2">
              {/* Quant Pill Badge */}
              <div className="inline-flex items-center gap-2 rounded-full border border-orange-200 bg-orange-50 px-3.5 py-1 text-xs font-black text-orange-800 shadow-2xs">
                <TrendingUp className="h-3.5 w-3.5 text-orange-600" />
                <span>
                  {isEs
                    ? "MODELO CUANTITATIVO • MONTE CARLO (+EV)"
                    : "QUANT MODEL • MONTE CARLO (+EV)"}
                </span>
              </div>

              {/* Data Freshness Chip */}
              <DataFreshnessChip
                stale={stale}
                age={age}
                date={date}
                onRefresh={onRefresh}
                isRefreshing={isRefreshing}
                disabled={isAnalyzing}
              />
            </div>

            {/* Headline */}
            <h1
              id="props-page-title"
              className="text-3xl sm:text-4xl lg:text-5xl font-black tracking-tight text-slate-900 leading-tight"
            >
              NBA Player Props & Expected Value
            </h1>

            {/* Subtitle */}
            <p className="text-sm sm:text-base text-slate-600 font-normal leading-relaxed">
              {isEs
                ? "Identificá valor matemático frente a las cuotas de las casas de apuestas. Integramos distribución Binomial Negativa (10,000 simulaciones), análisis cualitativo con Gemini AI y cuotas en vivo."
                : "Identify mathematical edges against sportsbook lines using Negative Binomial distributions (10,000 Monte Carlo runs), Gemini AI qualitative injury adjustments, and live odds."}
            </p>

            {/* Visible Paper Analysis Disclaimer */}
            <div className="inline-flex items-center gap-2 rounded-xl bg-slate-100/80 px-3 py-1.5 text-[11px] font-semibold text-slate-600 border border-slate-200">
              <AlertCircle className="h-3.5 w-3.5 text-slate-400 shrink-0" />
              <span>
                {isEs
                  ? "Análisis para simulación (paper trading) únicamente — no constituye asesoramiento financiero ni de apuestas."
                  : "Paper analysis only — not financial or real-money betting advice."}
              </span>
            </div>
          </div>

          {/* Right: Actions */}
          <div className="flex flex-wrap items-center gap-3 shrink-0 self-start lg:self-center">
            {/* Telegram Dispatch Toggle */}
            <label className="flex items-center gap-2 cursor-pointer select-none px-3.5 py-2.5 rounded-2xl bg-white border border-slate-200 text-xs font-semibold text-slate-700 hover:border-slate-300 hover:bg-slate-50 shadow-2xs transition-all focus-within:ring-2 focus-within:ring-sky-500">
              <input
                type="checkbox"
                checked={sendTelegram}
                onChange={(e) => onToggleSendTelegram(e.target.checked)}
                className="rounded border-slate-300 text-sky-600 focus:ring-sky-500 h-4 w-4 cursor-pointer"
              />
              <Send className="h-3.5 w-3.5 text-sky-500" />
              <span>{isEs ? "Despachar a Telegram" : "Send to Telegram"}</span>
            </label>

            {/* Primary Action Button: Run AI Analysis */}
            <button
              type="button"
              onClick={onRunAnalysis}
              disabled={isAnalyzing || isRefreshing}
              className="rounded-2xl bg-gradient-to-r from-orange-600 via-orange-500 to-amber-600 px-5 py-2.5 text-xs font-black text-white shadow-md hover:from-orange-500 hover:to-amber-500 hover:shadow-orange-500/20 active:scale-[0.98] transition-all inline-flex items-center gap-2 disabled:opacity-50 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-500"
            >
              {isAnalyzing ? (
                <RefreshCw className="h-4 w-4 animate-spin text-white" />
              ) : (
                <Zap className="h-4 w-4 text-amber-200 fill-amber-200" />
              )}
              <span>
                {isAnalyzing
                  ? isEs
                    ? "Simulando (10,000 corridas)..."
                    : "Simulating (10k runs)..."
                  : hasProps
                  ? isEs
                    ? "Re-ejecutar Análisis IA"
                    : "Re-run AI Analysis"
                  : isEs
                  ? "Ejecutar Análisis IA"
                  : "Run AI Analysis"}
              </span>
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
