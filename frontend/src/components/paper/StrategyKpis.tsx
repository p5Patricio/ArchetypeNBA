"use client";

import React from "react";
import { type StrategySummary } from "@/lib/api";
import { usePreferences } from "@/context/PreferencesContext";
import {
  ArrowUpRight,
  ArrowDownRight,
  Minus,
  Coins,
  Percent,
  CheckCircle2,
} from "lucide-react";

interface StrategyKpisProps {
  strategies: StrategySummary[];
  loading?: boolean;
}

export function StrategyKpis({ strategies, loading }: StrategyKpisProps) {
  const { language } = usePreferences();
  const isEs = language === "es";

  const getStrategyMeta = (key: string) => {
    switch (key.toLowerCase()) {
      case "flat":
        return {
          title: isEs ? "Flat (1 Unidad)" : "Flat (1 Unit)",
          desc: isEs
            ? "Apuesta plana de 1 unidad fija. Instrumento de referencia sin sesgo de tamaño para validar si el modelo tiene ventaja matemática pura."
            : "Flat 1-unit stake. Unbiased baseline instrument to validate whether the predictive model has raw edge without sizing bias.",
          badge: isEs ? "Referencia" : "Baseline",
          badgeColor: "bg-slate-100 text-slate-700 border-slate-200",
        };
      case "kelly_fractional":
        return {
          title: isEs ? "Kelly 1/4 (Fraccional)" : "Quarter-Kelly (Fractional)",
          desc: isEs
            ? "Criterio Kelly a un cuarto (topes: 2% pick, 4% partido, 10% día). Optimiza el crecimiento de capital asumiendo probabilidades exactas."
            : "Fixed quarter-Kelly sizing (caps: 2% bet, 4% game, 10% day). Maximizes wealth growth assuming calibrated probabilities.",
          badge: isEs ? "Crecimiento" : "Growth",
          badgeColor: "bg-blue-100 text-blue-700 border-blue-200",
        };
      case "kelly_shrunk":
        return {
          title: isEs ? "Kelly Contraído (Shrunk)" : "Shrunk Kelly (Uncertainty)",
          desc: isEs
            ? "Kelly con contracción por incertidumbre del modelo (Baker & McHale). Reduce la exposición ante muestras reducidas o fuerte desacuerdo con Pinnacle."
            : "Kelly shrunk for model parameter uncertainty (Baker & McHale). Reduces exposure with smaller samples or large market disagreement.",
          badge: isEs ? "Robusto" : "Robust",
          badgeColor: "bg-amber-100 text-amber-700 border-amber-200",
        };
      case "market_edge":
        return {
          title: isEs ? "Benchmark de Mercado" : "Market-Only Benchmark",
          desc: isEs
            ? "Benchmark puro sin modelo predictivo. Apuesta sólo cuando la mejor cuota comercial supera la probabilidad de cierre fair de Pinnacle."
            : "Pure market benchmark with no model. Bets strictly when the best book quote beats Pinnacle's de-vigged fair close.",
          badge: isEs ? "Sin Modelo" : "No Model",
          badgeColor: "bg-purple-100 text-purple-700 border-purple-200",
        };
      default:
        return {
          title: key.replace(/_/g, " ").toUpperCase(),
          desc: isEs
            ? "Estrategia cuantitativa de asignación y gestión de bankroll."
            : "Quantitative staking and bankroll management strategy.",
          badge: isEs ? "Estrategia" : "Strategy",
          badgeColor: "bg-emerald-100 text-emerald-700 border-emerald-200",
        };
    }
  };

  if (loading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4" aria-busy="true">
        {[1, 2, 3, 4].map((i) => (
          <div
            key={i}
            className="rounded-3xl border border-slate-200 bg-white p-6 shadow-xs animate-pulse space-y-4"
          >
            <div className="flex items-center justify-between">
              <div className="h-5 w-28 bg-slate-200 rounded-lg" />
              <div className="h-5 w-16 bg-slate-100 rounded-full" />
            </div>
            <div className="h-8 w-32 bg-slate-200 rounded-lg" />
            <div className="space-y-2 pt-2">
              <div className="h-4 w-full bg-slate-100 rounded-md" />
              <div className="h-4 w-3/4 bg-slate-100 rounded-md" />
            </div>
            <div className="pt-3 border-t border-slate-100 grid grid-cols-2 gap-2">
              <div className="h-4 bg-slate-100 rounded-md" />
              <div className="h-4 bg-slate-100 rounded-md" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (!strategies || strategies.length === 0) {
    return (
      <div className="rounded-3xl border border-dashed border-slate-300 bg-white p-8 text-center">
        <Coins className="mx-auto h-8 w-8 text-slate-400 mb-2" />
        <p className="text-sm font-semibold text-slate-700">
          {isEs ? "No hay estrategias registradas todavía" : "No registered strategies yet"}
        </p>
        <p className="text-xs text-slate-500 mt-1">
          {isEs
            ? "Las apuestas simuladas se registrarán automáticamente en el próximo tick."
            : "Simulated paper bets will populate on the next pipeline tick."}
        </p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      {strategies.map((s) => {
        const meta = getStrategyMeta(s.strategy);
        const pnl = s.pnl_units ?? 0;
        const roi = s.roi != null ? s.roi : null;
        const winRate = s.win_rate != null ? s.win_rate * 100 : null;
        const isProfit = pnl > 0.0001;
        const isLoss = pnl < -0.0001;

        return (
          <div
            key={s.strategy}
            className="flex flex-col justify-between rounded-3xl border border-slate-200 bg-white p-6 shadow-xs hover:border-slate-300 hover:shadow-md transition-all duration-200"
          >
            <div>
              {/* Header: Name + Badge */}
              <div className="flex items-center justify-between gap-2 mb-3">
                <h3 className="font-bold text-sm text-slate-900 tracking-tight flex items-center gap-1.5">
                  <Coins className="h-4 w-4 text-orange-500 shrink-0" />
                  <span>{meta.title}</span>
                </h3>
                <span
                  className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[10px] font-extrabold border ${meta.badgeColor}`}
                >
                  {meta.badge}
                </span>
              </div>

              {/* Main Bankroll */}
              <div className="mb-4">
                <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 mb-0.5">
                  {isEs ? "Bankroll Actual" : "Current Bankroll"}
                </div>
                <div className="flex items-baseline gap-2">
                  <span className="text-2xl sm:text-3xl font-black text-slate-900 tabular-nums">
                    {s.bankroll.toFixed(2)}
                  </span>
                  <span className="text-xs font-bold text-slate-500">
                    u <span className="font-normal text-[11px] text-slate-400">({isEs ? "inicial 100.00" : "init 100.00"})</span>
                  </span>
                </div>
              </div>

              {/* P/L & ROI Row */}
              <div className="grid grid-cols-2 gap-3 p-3 rounded-2xl bg-slate-50 border border-slate-100 mb-4">
                <div>
                  <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-1 flex items-center gap-1">
                    <span>P/L</span>
                  </div>
                  <div
                    className={`flex items-center gap-1 text-sm font-black tabular-nums ${
                      isProfit
                        ? "text-emerald-600"
                        : isLoss
                        ? "text-rose-600"
                        : "text-slate-600"
                    }`}
                  >
                    {isProfit ? (
                      <ArrowUpRight className="h-4 w-4 shrink-0 text-emerald-600" />
                    ) : isLoss ? (
                      <ArrowDownRight className="h-4 w-4 shrink-0 text-rose-600" />
                    ) : (
                      <Minus className="h-3.5 w-3.5 shrink-0 text-slate-400" />
                    )}
                    <span>
                      {pnl > 0 ? `+${pnl.toFixed(2)}` : pnl.toFixed(2)} u
                    </span>
                  </div>
                </div>

                <div>
                  <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-1">
                    <span>ROI</span>
                  </div>
                  <div
                    className={`text-sm font-black tabular-nums ${
                      roi != null && roi > 0
                        ? "text-emerald-600"
                        : roi != null && roi < 0
                        ? "text-rose-600"
                        : "text-slate-600"
                    }`}
                  >
                    {roi != null
                      ? `${roi > 0 ? "+" : ""}${(roi * 100).toFixed(1)}%`
                      : "—"}
                  </div>
                </div>
              </div>

              {/* Bets & Win Rate stats */}
              <div className="space-y-1.5 text-xs text-slate-600 border-t border-slate-100 pt-3 mb-4">
                <div className="flex items-center justify-between">
                  <span className="text-slate-500 flex items-center gap-1">
                    <CheckCircle2 className="h-3.5 w-3.5 text-slate-400" />
                    {isEs ? "Cerradas / Pendientes:" : "Settled / Pending:"}
                  </span>
                  <span className="font-bold text-slate-800 tabular-nums">
                    {s.settled}{" "}
                    <span className="font-normal text-slate-400">/</span>{" "}
                    {s.pending}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-500 flex items-center gap-1">
                    <Percent className="h-3.5 w-3.5 text-slate-400" />
                    {isEs ? "Tasa de Acierto (Win):" : "Win Rate:"}
                  </span>
                  <span className="font-bold text-slate-800 tabular-nums">
                    {winRate != null ? `${winRate.toFixed(1)}%` : "—"}
                  </span>
                </div>
              </div>
            </div>

            {/* Plain language caption */}
            <div className="text-[11px] leading-relaxed text-slate-500 bg-slate-50/70 p-2.5 rounded-xl border border-slate-100 mt-2">
              <span className="font-semibold text-slate-700 block mb-0.5">
                {isEs ? "Qué representa:" : "What this is:"}
              </span>
              {meta.desc}
            </div>
          </div>
        );
      })}
    </div>
  );
}
