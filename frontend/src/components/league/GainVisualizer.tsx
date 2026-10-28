"use client";

import React from "react";
import { type GainResponse } from "@/lib/api";
import { usePreferences } from "@/context/PreferencesContext";
import { CheckCircle2, AlertTriangle, XCircle, Info } from "lucide-react";

interface GainVisualizerProps {
  gain?: GainResponse | null;
  metricName?: string;
}

export function GainVisualizer({
  gain,
  metricName = "Log-Loss Gain",
}: GainVisualizerProps) {
  const { language } = usePreferences();
  const isEs = language === "es";

  if (!gain) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-center">
        <span className="text-xs text-slate-500 font-medium">
          {isEs ? "Evaluación bootstrap aún no disponible" : "Bootstrap evaluation not available yet"}
        </span>
      </div>
    );
  }

  const { mean, ci_low, ci_high } = gain;
  const hasCI = ci_low != null && ci_high != null;

  // Determine CI bounds relative to 0
  const crossesZero = hasCI && ci_low! <= 0 && ci_high! >= 0;
  const strictlyPositive = hasCI && ci_low! > 0;
  const strictlyNegative = hasCI && ci_high! < 0;

  // Calculate SVG positioning
  // Default range from -0.04 to +0.04 or dynamic
  const minVal = hasCI ? Math.min(-0.03, ci_low! * 1.3) : Math.min(-0.03, mean * 1.3);
  const maxVal = hasCI ? Math.max(0.03, ci_high! * 1.3) : Math.max(0.03, mean * 1.3);
  const span = maxVal - minVal || 0.06;

  const toPercent = (val: number) => {
    const clamped = Math.max(minVal, Math.min(maxVal, val));
    return ((clamped - minVal) / span) * 100;
  };

  const zeroPos = toPercent(0);
  const meanPos = toPercent(mean);
  const ciLowPos = hasCI ? toPercent(ci_low!) : meanPos;
  const ciHighPos = hasCI ? toPercent(ci_high!) : meanPos;

  // Visual cues
  const statusColor = strictlyPositive
    ? "text-emerald-700 bg-emerald-50 border-emerald-200"
    : crossesZero
    ? "text-amber-800 bg-amber-50 border-amber-200"
    : strictlyNegative
    ? "text-rose-800 bg-rose-50 border-rose-200"
    : "text-slate-700 bg-slate-50 border-slate-200";

  const barColor = strictlyPositive
    ? "#059669" // emerald
    : crossesZero
    ? "#d97706" // amber
    : "#e11d48"; // rose

  return (
    <div className="space-y-3">
      {/* Metrics Header */}
      <div className="flex items-baseline justify-between">
        <div>
          <span className="text-xs font-bold text-slate-600 block">{metricName}</span>
          <div className="flex items-baseline gap-2 mt-0.5">
            <span
              className={`text-xl sm:text-2xl font-black tabular-nums font-mono ${
                mean > 0 ? "text-emerald-600" : mean < 0 ? "text-rose-600" : "text-slate-800"
              }`}
            >
              {mean > 0 ? `+${mean.toFixed(4)}` : mean.toFixed(4)}
            </span>
            <span className="text-xs text-slate-400 font-medium font-mono">
              (95% CI: [{ci_low != null ? ci_low.toFixed(4) : "—"}, {ci_high != null ? ci_high.toFixed(4) : "—"}])
            </span>
          </div>
        </div>

        {/* Visual Badge */}
        <div className={`px-2.5 py-1 rounded-full border text-[11px] font-bold flex items-center gap-1.5 ${statusColor}`}>
          {strictlyPositive && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600 shrink-0" />}
          {crossesZero && <AlertTriangle className="h-3.5 w-3.5 text-amber-600 shrink-0" />}
          {strictlyNegative && <XCircle className="h-3.5 w-3.5 text-rose-600 shrink-0" />}
          {!hasCI && <Info className="h-3.5 w-3.5 text-slate-500 shrink-0" />}
          <span>
            {strictlyPositive
              ? isEs
                ? "Ventaja Comprobada (CI > 0)"
                : "Proven Edge (CI > 0)"
              : crossesZero
              ? isEs
                ? "CI Cruza Cero (No Probado)"
                : "CI Crosses Zero (Unproven)"
              : strictlyNegative
              ? isEs
                ? "Inferior al Campeón"
                : "Underperforming"
              : isEs
              ? "Estimación Puntual"
              : "Point Estimate"}
          </span>
        </div>
      </div>

      {/* SVG Axis Visualization */}
      <div
        className="relative py-2 select-none"
        role="img"
        aria-label={`${metricName}: mean ${mean.toFixed(4)}, CI [${ci_low ?? "—"}, ${ci_high ?? "—"}]`}
      >
        <svg className="w-full h-12 overflow-visible" aria-hidden="true">
          {/* Background baseline */}
          <line
            x1="0%"
            y1="50%"
            x2="100%"
            y2="50%"
            stroke="#cbd5e1"
            strokeWidth="1.5"
            strokeDasharray="3 3"
          />

          {/* Zero reference vertical line */}
          <line
            x1={`${zeroPos}%`}
            y1="10%"
            x2={`${zeroPos}%`}
            y2="90%"
            stroke="#64748b"
            strokeWidth="2"
          />
          <text
            x={`${zeroPos}%`}
            y="98%"
            textAnchor="middle"
            className="text-[9px] font-mono fill-slate-500 font-bold"
          >
            0.0
          </text>

          {/* CI Whisker / Bar */}
          {hasCI && (
            <>
              {/* Range horizontal line */}
              <line
                x1={`${ciLowPos}%`}
                y1="50%"
                x2={`${ciHighPos}%`}
                y2="50%"
                stroke={barColor}
                strokeWidth="4"
                strokeLinecap="round"
              />
              {/* Left whisker cap */}
              <line
                x1={`${ciLowPos}%`}
                y1="35%"
                x2={`${ciLowPos}%`}
                y2="65%"
                stroke={barColor}
                strokeWidth="2.5"
              />
              {/* Right whisker cap */}
              <line
                x1={`${ciHighPos}%`}
                y1="35%"
                x2={`${ciHighPos}%`}
                y2="65%"
                stroke={barColor}
                strokeWidth="2.5"
              />
            </>
          )}

          {/* Mean point marker */}
          <circle
            cx={`${meanPos}%`}
            cy="50%"
            r="5"
            fill={barColor}
            stroke="#ffffff"
            strokeWidth="2"
          />
        </svg>

        {/* Legend labels under axis */}
        <div className="flex justify-between text-[10px] text-slate-400 font-mono mt-1">
          <span>{minVal.toFixed(3)}</span>
          <span className="text-slate-600 font-semibold">
            {isEs ? "← Peor | Mejor →" : "← Worse | Better →"}
          </span>
          <span>{maxVal.toFixed(3)}</span>
        </div>
      </div>

      {/* Helper explanation */}
      <div className="text-[11px] leading-relaxed text-slate-500 bg-slate-50 p-2.5 rounded-xl border border-slate-100">
        <span className="font-semibold text-slate-700 mr-1">
          {isEs ? "Criterio de Promoción:" : "Promotion Criterion:"}
        </span>
        {isEs
          ? "Para autorizar una promoción, el extremo inferior del intervalo (CI low) debe permanecer estrictamente superior a cero sobre un mínimo de 150 partidos."
          : "For promotion, the lower bound of the 95% bootstrap CI must remain strictly above zero over at least 150 paired games."}
      </div>
    </div>
  );
}
