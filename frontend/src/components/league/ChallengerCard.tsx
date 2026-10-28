"use client";

import React from "react";
import { type ChallengerResponse } from "@/lib/api";
import { GainVisualizer } from "./GainVisualizer";
import { usePreferences } from "@/context/PreferencesContext";
import {
  GitCompare,
  Clock,
  CheckCircle2,
  XCircle,
  Target,
  Activity,
  Lock,
} from "lucide-react";

interface ChallengerCardProps {
  challenger: ChallengerResponse;
}

export function ChallengerCard({ challenger }: ChallengerCardProps) {
  const { language } = usePreferences();
  const isEs = language === "es";

  const targetN = challenger.target_n || 150;
  const pairedN = challenger.paired_n || 0;
  const progressPct = Math.min(100, Math.round((pairedN / targetN) * 100));

  const getDecisionBadge = (decision: string) => {
    switch (decision.toLowerCase()) {
      case "promoted":
        return {
          label: isEs ? "Promovido a Campeón" : "Promoted to Champion",
          styles: "bg-emerald-100 text-emerald-900 border-emerald-300",
          icon: CheckCircle2,
        };
      case "retired":
        return {
          label: isEs ? "Retirado / Descartado" : "Retired / Discarded",
          styles: "bg-rose-100 text-rose-900 border-rose-300",
          icon: XCircle,
        };
      case "keep_shadow":
        return {
          label: isEs ? "Mantener en Shadow" : "Keep in Shadow",
          styles: "bg-blue-100 text-blue-900 border-blue-300",
          icon: Activity,
        };
      case "insufficient_data":
      default:
        return {
          label: isEs ? "Datos Insuficientes" : "Insufficient Data",
          styles: "bg-slate-100 text-slate-800 border-slate-300",
          icon: Clock,
        };
    }
  };

  const decisionBadge = getDecisionBadge(challenger.decision || challenger.last_decision || "insufficient_data");
  const DecisionIcon = decisionBadge.icon;

  const marginNllMean = challenger.margin_nll_gain?.mean ?? null;
  const marketBrierGap = challenger.market_brier_gap ?? null;

  return (
    <div className="rounded-3xl border border-slate-200 bg-white p-6 sm:p-8 shadow-xs hover:border-slate-300 transition-all duration-200 space-y-6">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-100 pb-5">
        <div>
          <div className="flex items-center gap-2 mb-1.5">
            <span className="text-[11px] font-black uppercase tracking-wider text-slate-400">
              {isEs ? "RETADOR EN SOMBRA" : "SHADOW CHALLENGER"}
            </span>
            <span className="font-mono text-xs font-bold text-slate-500 bg-slate-100 px-2 py-0.5 rounded-lg border border-slate-200">
              ID #{challenger.model_id}
            </span>
          </div>
          <h3 className="text-xl sm:text-2xl font-black text-slate-900 tracking-tight flex items-center gap-2">
            <GitCompare className="h-5 w-5 text-orange-500" />
            <span>{challenger.label}</span>
          </h3>
        </div>

        {/* Audit Decision Badge */}
        <div className="shrink-0">
          <div
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-2xl border text-xs font-black shadow-2xs ${decisionBadge.styles}`}
          >
            <DecisionIcon className="h-4 w-4 shrink-0" />
            <span>{decisionBadge.label}</span>
          </div>
        </div>
      </div>

      {/* Progress Bar: Paired Games vs Target */}
      <div className="rounded-2xl bg-slate-50 border border-slate-200/80 p-5 space-y-2">
        <div className="flex items-center justify-between text-xs">
          <span className="font-bold text-slate-700 flex items-center gap-1.5">
            <Target className="h-4 w-4 text-orange-600" />
            <span>{isEs ? "Muestra Evaluada en Pares:" : "Paired Games Evaluated:"}</span>
          </span>
          <span className="font-mono font-black text-slate-900">
            {pairedN} <span className="font-normal text-slate-400">/</span> {targetN}{" "}
            <span className="text-orange-600 font-extrabold">({progressPct}%)</span>
          </span>
        </div>

        {/* Progress Bar Track */}
        <div className="w-full bg-slate-200 rounded-full h-3 overflow-hidden p-0.5">
          <div
            className="bg-gradient-to-r from-orange-500 to-amber-500 h-2 rounded-full transition-all duration-500"
            style={{ width: `${progressPct}%` }}
            role="progressbar"
            aria-valuenow={pairedN}
            aria-valuemin={0}
            aria-valuemax={targetN}
          />
        </div>

        <div className="flex justify-between text-[11px] text-slate-500 pt-1">
          <span>
            {isEs
              ? `${Math.max(0, targetN - pairedN)} partidos faltantes para el umbral mínimo de 150`
              : `${Math.max(0, targetN - pairedN)} games remaining for the 150 paired threshold`}
          </span>
          <span className="font-mono">
            {challenger.days_live != null
              ? `${Math.round(challenger.days_live)} ${isEs ? "días activo" : "days live"}`
              : ""}
          </span>
        </div>
      </div>

      {/* Primary Signal: Log-Loss Gain Visualizer */}
      <div className="rounded-2xl border border-slate-200/80 p-5 bg-white space-y-2">
        <GainVisualizer
          gain={challenger.log_loss_gain}
          metricName={
            isEs
              ? "Ganancia de Log-Loss vs Campeón (Métrica Primaria)"
              : "Log-Loss Gain vs Champion (Primary Metric)"
          }
        />
      </div>

      {/* Secondary Metrics Grid: Margin-NLL & Brier Gap vs Market */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {/* Margin NLL Gain */}
        <div className="rounded-2xl bg-slate-50 border border-slate-200/80 p-4">
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-1">
            {isEs ? "Ganancia de NLL de Margen" : "Margin NLL Gain"}
          </div>
          <div className="flex items-baseline gap-2">
            <span
              className={`text-lg sm:text-xl font-black font-mono tabular-nums ${
                marginNllMean != null && marginNllMean > 0
                  ? "text-emerald-600"
                  : marginNllMean != null && marginNllMean < 0
                  ? "text-rose-600"
                  : "text-slate-800"
              }`}
            >
              {marginNllMean != null
                ? `${marginNllMean > 0 ? "+" : ""}${marginNllMean.toFixed(4)}`
                : "—"}
            </span>
            {challenger.margin_nll_gain?.ci_low != null && (
              <span className="text-[11px] text-slate-400 font-mono">
                [{challenger.margin_nll_gain.ci_low.toFixed(3)},{" "}
                {challenger.margin_nll_gain.ci_high?.toFixed(3) ?? "—"}]
              </span>
            )}
          </div>
          <p className="text-[11px] text-slate-500 mt-1">
            {isEs
              ? "Calidad de predicción del margen de puntos. No debe empeorar significativamente."
              : "Point margin spread accuracy. Must not be significantly worse."}
          </p>
        </div>

        {/* Brier Gap vs Market */}
        <div className="rounded-2xl bg-slate-50 border border-slate-200/80 p-4">
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-1">
            {isEs ? "Brecha Brier vs Mercado Sharp" : "Brier Gap vs Sharp Market"}
          </div>
          <div className="flex items-baseline gap-2">
            <span
              className={`text-lg sm:text-xl font-black font-mono tabular-nums ${
                marketBrierGap != null && marketBrierGap <= 0.005
                  ? "text-slate-800"
                  : "text-amber-600"
              }`}
            >
              {marketBrierGap != null
                ? `${marketBrierGap > 0 ? "+" : ""}${marketBrierGap.toFixed(4)}`
                : "—"}
            </span>
            <span className="text-[11px] text-slate-400">
              {isEs ? "(tolerancia ≤ 0.005)" : "(max tolerance ≤ 0.005)"}
            </span>
          </div>
          <p className="text-[11px] text-slate-500 mt-1">
            {isEs
              ? "Distancia frente a la calibración del cierre sharp de Pinnacle."
              : "Distance compared to Pinnacle's de-vigged closing calibration."}
          </p>
        </div>
      </div>

      {/* Promotion Gate Status in Plain Words */}
      <div className="rounded-2xl bg-slate-50/80 border border-slate-200 p-4 text-xs space-y-1.5">
        <div className="flex items-center gap-2 font-bold text-slate-800">
          <Lock className="h-4 w-4 text-orange-600 shrink-0" />
          <span>{isEs ? "Estado de las Compuertas de Promoción:" : "Promotion Gate Evaluation:"}</span>
        </div>
        <p className="text-slate-600 leading-relaxed font-mono text-[11px] bg-white p-3 rounded-xl border border-slate-200">
          {challenger.gate_text ||
            (isEs
              ? "Muestra insuficiente para abrir auditoría de compuertas (mínimo 150 partidos en pares y 14 días)."
              : "Insufficient sample to trigger audit gates (minimum 150 paired games and 14 days).")}
        </p>
        {challenger.last_reason && (
          <div className="text-[11px] text-slate-500 pt-1">
            <span className="font-semibold text-slate-700">{isEs ? "Última razón:" : "Last audit log:"}</span>{" "}
            {challenger.last_reason}
          </div>
        )}
      </div>
    </div>
  );
}
