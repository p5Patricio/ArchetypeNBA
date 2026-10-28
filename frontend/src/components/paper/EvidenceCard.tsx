"use client";

import React from "react";
import {
  type PinnacleClvSummaryResponse,
  type ChampionSkillResponse,
  type PropsShadowSummaryResponse,
} from "@/lib/api";
import { usePreferences } from "@/context/PreferencesContext";
import {
  ShieldCheck,
  Scale,
  AlertTriangle,
  Info,
  TrendingUp,
  Activity,
  CheckCircle2,
  XCircle,
} from "lucide-react";

interface EvidenceCardProps {
  pinnacleClv?: PinnacleClvSummaryResponse | null;
  brier?: ChampionSkillResponse | null;
  propsShadow?: PropsShadowSummaryResponse | null;
  loading?: boolean;
}

export function EvidenceCard({
  pinnacleClv,
  brier,
  propsShadow,
  loading,
}: EvidenceCardProps) {
  const { language } = usePreferences();
  const isEs = language === "es";

  if (loading) {
    return (
      <div
        className="rounded-3xl border border-slate-200 bg-white p-6 shadow-xs animate-pulse space-y-4"
        aria-busy="true"
      >
        <div className="h-6 w-48 bg-slate-200 rounded-lg" />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 pt-2">
          <div className="h-32 bg-slate-100 rounded-2xl" />
          <div className="h-32 bg-slate-100 rounded-2xl" />
          <div className="h-32 bg-slate-100 rounded-2xl" />
        </div>
      </div>
    );
  }

  // Verdict calculation according to quant rules
  const games = pinnacleClv?.games ?? 0;
  const tStat = pinnacleClv?.t_stat ?? null;
  const meanClv = pinnacleClv?.mean_clv ?? null;
  const stdErr = pinnacleClv?.std_err ?? null;
  const betsNeeded1pct = pinnacleClv?.bets_needed_1pct ?? null;

  let verdictText = "";
  let verdictStatus: "neutral" | "warning" | "positive" | "negative" = "neutral";

  if (games < 20) {
    verdictText = isEs ? "Muy temprano para evaluar" : "Too early to tell";
    verdictStatus = "neutral";
  } else if (tStat != null && Math.abs(tStat) < 2) {
    verdictText = isEs
      ? "Sin ventaja medible vs el cierre sharp aún"
      : "No measurable edge vs the sharp close yet";
    verdictStatus = "warning";
  } else if (tStat != null && tStat >= 2) {
    verdictText = isEs
      ? "Positivo y estadísticamente notable - seguir validando"
      : "Positive and statistically notable - keep validating";
    verdictStatus = "positive";
  } else if (tStat != null && tStat <= -2) {
    verdictText = isEs
      ? "Peor que el cierre sharp"
      : "Worse than the sharp close";
    verdictStatus = "negative";
  } else {
    verdictText = isEs ? "Muestra insuficiente" : "Insufficient sample";
    verdictStatus = "neutral";
  }

  const verdictBadgeStyles = {
    neutral: "bg-slate-100 text-slate-800 border-slate-300",
    warning: "bg-amber-50 text-amber-900 border-amber-300",
    positive: "bg-emerald-50 text-emerald-900 border-emerald-300",
    negative: "bg-rose-50 text-rose-900 border-rose-300",
  }[verdictStatus];

  const sameBookAvgClv = pinnacleClv?.same_book_avg_clv ?? null;
  const sameBookBets = pinnacleClv?.same_book_clv_bets ?? 0;

  return (
    <div className="rounded-3xl border border-slate-200 bg-white p-6 sm:p-8 shadow-xs">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-100 pb-5 mb-6">
        <div>
          <div className="inline-flex items-center gap-1.5 rounded-full border border-orange-200 bg-orange-50 px-3 py-0.5 text-[11px] font-black text-orange-800 mb-2">
            <Scale className="h-3 w-3 text-orange-600" />
            <span>{isEs ? "EVIDENCIA ESTADÍSTICA • NO ROI" : "STATISTICAL EVIDENCE • NOT ROI"}</span>
          </div>
          <h2 className="text-xl sm:text-2xl font-black text-slate-900 tracking-tight">
            {isEs ? "Evaluación de Habilidad: CLV & Brier vs Mercado Sharp" : "Skill Evaluation: CLV & Brier vs Sharp Close"}
          </h2>
          <p className="text-xs sm:text-sm text-slate-500 mt-1 max-w-3xl">
            {isEs
              ? "El ROI requiere miles de apuestas para converger y no mide habilidad pura. El CLV frente a Pinnacle (de-vigged) y el Brier score contra el cierre sharp detectan si el sistema tiene una ventaja predictiva real en muestras pequeñas."
              : "ROI requires thousands of bets to converge and reflects luck. CLV against de-vigged Pinnacle and Brier score against the sharp close detect genuine predictive edge in much smaller samples."}
          </p>
        </div>

        {/* Verdict Badge */}
        <div className="shrink-0">
          <div className={`rounded-2xl border px-4 py-2 text-center ${verdictBadgeStyles}`}>
            <span className="text-[10px] uppercase font-bold tracking-wider block opacity-75">
              {isEs ? "Veredicto Matemático" : "Statistical Verdict"}
            </span>
            <span className="text-xs sm:text-sm font-black flex items-center justify-center gap-1.5 mt-0.5">
              {verdictStatus === "positive" && <CheckCircle2 className="h-4 w-4 text-emerald-600" />}
              {verdictStatus === "warning" && <AlertTriangle className="h-4 w-4 text-amber-600" />}
              {verdictStatus === "negative" && <XCircle className="h-4 w-4 text-rose-600" />}
              {verdictStatus === "neutral" && <Info className="h-4 w-4 text-slate-500" />}
              <span>{verdictText}</span>
            </span>
          </div>
        </div>
      </div>

      {/* 3 Pillars Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Pillar 1: Pinnacle CLV */}
        <div className="rounded-2xl border border-slate-200 bg-slate-50/60 p-5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-black uppercase tracking-wider text-slate-700 flex items-center gap-1.5">
                <ShieldCheck className="h-4 w-4 text-sky-600" />
                <span>{isEs ? "CLV vs Cierre Pinnacle" : "CLV vs Pinnacle Close"}</span>
              </span>
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-sky-100 text-sky-800 border border-sky-200">
                {isEs ? "Referencia Sharp" : "Sharp Reference"}
              </span>
            </div>

            <div className="mb-4">
              <div className="text-2xl sm:text-3xl font-black text-slate-900 tabular-nums">
                {meanClv != null
                  ? `${meanClv > 0 ? "+" : ""}${(meanClv * 100).toFixed(2)}%`
                  : "—"}
              </div>
              <div className="text-[11px] text-slate-500 mt-0.5">
                {isEs ? "Media ponderada agrupada por partido" : "Game-clustered mean CLV in log-odds"}
              </div>
            </div>

            <div className="space-y-2 text-xs border-t border-slate-200/70 pt-3">
              <div className="flex justify-between items-center">
                <span className="text-slate-500">{isEs ? "Error Estándar (SE):" : "Standard Error (SE):"}</span>
                <span className="font-bold text-slate-800 tabular-nums">
                  {stdErr != null ? `±${(stdErr * 100).toFixed(2)}%` : "—"}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-500">{isEs ? "Estadístico t:" : "t statistic:"}</span>
                <span
                  className={`font-black tabular-nums ${
                    tStat != null && Math.abs(tStat) >= 2
                      ? tStat > 0
                        ? "text-emerald-600"
                        : "text-rose-600"
                      : "text-slate-700"
                  }`}
                >
                  {tStat != null ? tStat.toFixed(2) : "—"}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-500">{isEs ? "Partidos independientes:" : "Independent games:"}</span>
                <span className="font-bold text-slate-800 tabular-nums">{games}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-500">{isEs ? "Muestra para detectar +1%:" : "Bets to detect +1%:"}</span>
                <span className="font-bold text-slate-800 tabular-nums">
                  {betsNeeded1pct != null ? `~${Math.round(betsNeeded1pct)}` : "—"}
                </span>
              </div>
            </div>
          </div>

          <div className="text-[11px] leading-relaxed text-slate-500 bg-white p-3 rounded-xl border border-slate-200 mt-4">
            <span className="font-bold text-slate-700 block mb-0.5">
              {isEs ? "Por qué agrupar por partido:" : "Why cluster by game:"}
            </span>
            {isEs
              ? "Flat y Kelly suelen apostar la misma selección. Contar cada apuesta como independiente sobreestima la significancia t."
              : "Flat and Kelly duplicate picks. Clustering by game prevents inflating t-statistics with correlated bets."}
          </div>
        </div>

        {/* Pillar 2: Same-Book CLV */}
        <div className="rounded-2xl border border-slate-200 bg-slate-50/60 p-5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-black uppercase tracking-wider text-slate-700 flex items-center gap-1.5">
                <TrendingUp className="h-4 w-4 text-amber-600" />
                <span>{isEs ? "CLV Same-Book (Misma Casa)" : "Same-Book CLV"}</span>
              </span>
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 border border-amber-200">
                {isEs ? "Sesgo Optimista" : "Optimistic Bias"}
              </span>
            </div>

            <div className="mb-4">
              <div className="text-2xl sm:text-3xl font-black text-slate-900 tabular-nums">
                {sameBookAvgClv != null
                  ? `${sameBookAvgClv > 0 ? "+" : ""}${(sameBookAvgClv * 100).toFixed(2)}%`
                  : "—"}
              </div>
              <div className="text-[11px] text-slate-500 mt-0.5">
                {isEs
                  ? `Sobre ${sameBookBets} apuestas con cierre capturado`
                  : `Over ${sameBookBets} bets with closing quote`}
              </div>
            </div>

            <div className="space-y-2 text-xs border-t border-slate-200/70 pt-3">
              <div className="flex justify-between items-center">
                <span className="text-slate-500">{isEs ? "Apuestas comparables:" : "Comparable bets:"}</span>
                <span className="font-bold text-slate-800 tabular-nums">{sameBookBets}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-500">{isEs ? "Exclusiones de línea:" : "Excluded line moves:"}</span>
                <span className="font-bold text-slate-800 tabular-nums">
                  {pinnacleClv?.exclusions?.line_moved ?? 0}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-500">{isEs ? "Total no comparables:" : "Total non-comparable:"}</span>
                <span className="font-bold text-slate-800 tabular-nums">
                  {pinnacleClv?.exclusions?.total ?? 0}
                </span>
              </div>
            </div>
          </div>

          <div className="text-[11px] leading-relaxed text-slate-500 bg-white p-3 rounded-xl border border-slate-200 mt-4">
            <span className="font-bold text-amber-800 block mb-0.5">
              {isEs ? "Advertencia de sesgo:" : "Bias warning:"}
            </span>
            {isEs
              ? "El CLV de la misma casa suele ser optimista: casas recreacionales mueven líneas tarde, las apuestas descartadas por cambio de línea generan sesgo de supervivencia y se duplican selecciones."
              : "Same-book CLV is optimistic: soft books adjust lines late, bets where line moved are dropped (survivorship), and flat/Kelly duplicate selections."}
          </div>
        </div>

        {/* Pillar 3: Brier vs Market */}
        <div className="rounded-2xl border border-slate-200 bg-slate-50/60 p-5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-black uppercase tracking-wider text-slate-700 flex items-center gap-1.5">
                <Activity className="h-4 w-4 text-purple-600" />
                <span>{isEs ? "Brier Score vs Mercado" : "Brier Score vs Market"}</span>
              </span>
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-purple-100 text-purple-800 border border-purple-200">
                {isEs ? "Menor = Mejor" : "Lower = Better"}
              </span>
            </div>

            <div className="mb-4">
              <div className="flex items-baseline gap-2">
                <span className="text-2xl sm:text-3xl font-black text-slate-900 tabular-nums">
                  {brier?.brier_model != null ? brier.brier_model.toFixed(4) : "—"}
                </span>
                <span className="text-xs text-slate-400 font-normal">
                  vs {brier?.brier_market != null ? brier.brier_market.toFixed(4) : "—"} (Mkt)
                </span>
              </div>
              <div className="text-[11px] text-slate-500 mt-0.5">
                {isEs ? "Puntuación de calibración probabilística" : "Probabilistic calibration score"}
              </div>
            </div>

            <div className="space-y-2 text-xs border-t border-slate-200/70 pt-3">
              <div className="flex justify-between items-center">
                <span className="text-slate-500">{isEs ? "Modelo Campeón:" : "Champion Model:"}</span>
                <span className="font-bold text-slate-800">{brier?.model || "elo_538"}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-500">{isEs ? "Referencia Sharp:" : "Sharp Reference:"}</span>
                <span className="font-bold text-slate-800 capitalize">{brier?.sharp_book || "Pinnacle"}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-500">{isEs ? "Partidos comparados:" : "Compared games:"}</span>
                <span className="font-bold text-slate-800 tabular-nums">{brier?.games_compared ?? 0}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-500">{isEs ? "Brecha vs Mercado:" : "Gap vs Market:"}</span>
                <span
                  className={`font-black tabular-nums ${
                    brier?.difference != null
                      ? brier.difference > 0
                        ? "text-rose-600"
                        : "text-emerald-600"
                      : "text-slate-700"
                  }`}
                >
                  {brier?.difference != null
                    ? `${brier.difference > 0 ? "+" : ""}${brier.difference.toFixed(4)}`
                    : "—"}
                </span>
              </div>
            </div>
          </div>

          <div className="text-[11px] leading-relaxed text-slate-500 bg-white p-3 rounded-xl border border-slate-200 mt-4">
            <span className="font-bold text-slate-700 block mb-0.5">
              {isEs ? "Interpretación Brier:" : "Brier Interpretation:"}
            </span>
            {isEs
              ? "0.00 es perfección. El cierre de Pinnacle ronda ~0.201. Un modelo básico de caja pública ronda ~0.249. La ventaja sólo se alcanzará con señales privadas (alineaciones, lesiones)."
              : "0.00 is perfect accuracy. Pinnacle's close averages ~0.201. A public box-score model sits at ~0.249. Edge requires real information signals (lineups, injuries)."}
          </div>
        </div>
      </div>

      {/* Optional: Props Shadow Model vs Book Close */}
      {propsShadow && (propsShadow.n > 0 || propsShadow.void_count > 0 || propsShadow.unmatched_name_count > 0) && (
        <div className="mt-6 pt-6 border-t border-slate-100">
          <div className="rounded-2xl border border-slate-200 bg-slate-50/60 p-5">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-3">
              <span className="text-xs font-black uppercase tracking-wider text-slate-700 flex items-center gap-1.5">
                <Activity className="h-4 w-4 text-indigo-600" />
                <span>{isEs ? "Modelo Shadow Props (props_nb) vs Cierre de Casas" : "Props Shadow Model (props_nb) vs Book Close"}</span>
              </span>
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-800 border border-indigo-200">
                {propsShadow.n < 30 ? (isEs ? "Muestra insuficiente (n < 30)" : "Insufficient data (n < 30)") : `${propsShadow.n} ${isEs ? "predicciones" : "predictions"}`}
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4 mt-4">
              <div>
                <span className="text-slate-500 text-xs block">{isEs ? "Predicciones evaluadas:" : "Evaluated predictions:"}</span>
                <span className="text-lg font-black text-slate-900 tabular-nums">{propsShadow.n}</span>
              </div>
              <div>
                <span className="text-slate-500 text-xs block">{isEs ? "Brier (Modelo vs Casa):" : "Brier (Model vs Book):"}</span>
                <span className="text-sm font-bold text-slate-900 tabular-nums">
                  {propsShadow.brier_model != null && propsShadow.brier_book != null
                    ? `${propsShadow.brier_model.toFixed(4)} vs ${propsShadow.brier_book.toFixed(4)}`
                    : "—"}
                </span>
                {propsShadow.brier_diff != null && (
                  <span className={`text-xs font-bold block ${propsShadow.brier_diff > 0 ? "text-rose-600" : "text-emerald-600"}`}>
                    diff {propsShadow.brier_diff > 0 ? "+" : ""}{propsShadow.brier_diff.toFixed(4)}
                  </span>
                )}
              </div>
              <div>
                <span className="text-slate-500 text-xs block">{isEs ? "Log Loss (Modelo vs Casa):" : "Log Loss (Model vs Book):"}</span>
                <span className="text-sm font-bold text-slate-900 tabular-nums">
                  {propsShadow.log_loss_model != null && propsShadow.log_loss_book != null
                    ? `${propsShadow.log_loss_model.toFixed(4)} vs ${propsShadow.log_loss_book.toFixed(4)}`
                    : "—"}
                </span>
                {propsShadow.log_loss_diff != null && (
                  <span className={`text-xs font-bold block ${propsShadow.log_loss_diff > 0 ? "text-rose-600" : "text-emerald-600"}`}>
                    diff {propsShadow.log_loss_diff > 0 ? "+" : ""}{propsShadow.log_loss_diff.toFixed(4)}
                  </span>
                )}
              </div>
              <div>
                <span className="text-slate-500 text-xs block">{isEs ? "Voids / Nombres no asignados:" : "Voids / Unmatched names:"}</span>
                <span className="text-sm font-bold text-slate-800 tabular-nums">
                  {propsShadow.void_count} voids | {propsShadow.unmatched_name_count} unmatched
                </span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
