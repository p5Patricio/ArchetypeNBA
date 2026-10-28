"use client";

import React, { useMemo } from "react";
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler,
  type ChartOptions,
  type ChartData,
} from "chart.js";
import { Line } from "react-chartjs-2";
import { type PaperBankrollResponse } from "@/lib/api";
import { usePreferences } from "@/context/PreferencesContext";
import { LineChart, ArrowUpRight, ArrowDownRight, Layers } from "lucide-react";

// Register ChartJS modules
ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
);

interface BankrollChartProps {
  data?: PaperBankrollResponse | null;
  loading?: boolean;
}

interface StrategyStyle {
  color: string;
  borderColor: string;
  backgroundColor: string;
  pointStyle: "circle" | "rect" | "triangle" | "rectRot" | "star";
  borderDash: number[];
  labelEs: string;
  labelEn: string;
  patternEs: string;
  patternEn: string;
}

const STRATEGY_STYLES: Record<string, StrategyStyle> = {
  flat: {
    color: "#059669",
    borderColor: "#059669",
    backgroundColor: "rgba(5, 150, 105, 0.08)",
    pointStyle: "circle",
    borderDash: [],
    labelEs: "Flat (1 u)",
    labelEn: "Flat (1 u)",
    patternEs: "● Círculo, línea continua",
    patternEn: "● Circle, solid line",
  },
  kelly_fractional: {
    color: "#2563eb",
    borderColor: "#2563eb",
    backgroundColor: "rgba(37, 99, 235, 0.08)",
    pointStyle: "rect",
    borderDash: [6, 4],
    labelEs: "Kelly 1/4 (Fraccional)",
    labelEn: "Quarter-Kelly (Fractional)",
    patternEs: "■ Cuadrado, línea a trazos",
    patternEn: "■ Square, dashed line",
  },
  kelly_shrunk: {
    color: "#d97706",
    borderColor: "#d97706",
    backgroundColor: "rgba(217, 119, 6, 0.08)",
    pointStyle: "triangle",
    borderDash: [2, 3],
    labelEs: "Kelly Shrunk (Incertidumbre)",
    labelEn: "Shrunk Kelly (Uncertainty)",
    patternEs: "▲ Triángulo, línea punteada",
    patternEn: "▲ Triangle, dotted line",
  },
  market_edge: {
    color: "#7c3aed",
    borderColor: "#7c3aed",
    backgroundColor: "rgba(124, 58, 237, 0.08)",
    pointStyle: "rectRot",
    borderDash: [8, 4, 2, 4],
    labelEs: "Market Benchmark (Sin Modelo)",
    labelEn: "Market Benchmark (No Model)",
    patternEs: "◆ Rombo, raya y punto",
    patternEn: "◆ Diamond, dash-dot line",
  },
};

const DEFAULT_STYLE: StrategyStyle = {
  color: "#64748b",
  borderColor: "#64748b",
  backgroundColor: "rgba(100, 116, 139, 0.08)",
  pointStyle: "star",
  borderDash: [4, 4],
  labelEs: "Estrategia",
  labelEn: "Strategy",
  patternEs: "★ Estrella, trazos",
  patternEn: "★ Star, dashes",
};

export function BankrollChart({ data, loading }: BankrollChartProps) {
  const { language } = usePreferences();
  const isEs = language === "es";

  // Build unified chronological timeline
  const { chartData, summaries, hasData } = useMemo(() => {
    if (!data || !data.series || Object.keys(data.series).length === 0) {
      return { chartData: null, summaries: [], hasData: false };
    }

    const strategies = Object.keys(data.series);
    let totalPoints = 0;
    strategies.forEach((st) => {
      totalPoints += data.series[st]?.length || 0;
    });

    if (totalPoints === 0) {
      return { chartData: null, summaries: [], hasData: false };
    }

    // Collect all unique settlement events sorted by time
    interface TimelineEvent {
      time: number;
      dateStr: string;
      strategy: string;
      bankroll: number;
      profit: number;
    }

    const events: TimelineEvent[] = [];
    strategies.forEach((strategy) => {
      const points = data.series[strategy] || [];
      points.forEach((pt) => {
        const time = new Date(pt.settled_at).getTime();
        events.push({
          time,
          dateStr: pt.settled_at,
          strategy,
          bankroll: pt.bankroll,
          profit: pt.cumulative_profit_units,
        });
      });
    });

    events.sort((a, b) => a.time - b.time);

    // Initial label
    const labels: string[] = [isEs ? "Inicio (100 u)" : "Start (100 u)"];
    const currentBankrolls: Record<string, number> = {};
    strategies.forEach((st) => {
      currentBankrolls[st] = 100.0;
    });

    // Per-strategy values along timeline
    const seriesValues: Record<string, number[]> = {};
    strategies.forEach((st) => {
      seriesValues[st] = [100.0];
    });

    // Step through each event
    events.forEach((ev) => {
      currentBankrolls[ev.strategy] = ev.bankroll;

      const dateObj = new Date(ev.dateStr);
      const label = dateObj.toLocaleDateString(isEs ? "es-MX" : "en-US", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
      labels.push(label);

      // Record state for every strategy
      strategies.forEach((st) => {
        seriesValues[st].push(Number(currentBankrolls[st].toFixed(2)));
      });
    });

    // Build ChartJS datasets
    const datasets = strategies.map((strategy) => {
      const style = STRATEGY_STYLES[strategy] || {
        ...DEFAULT_STYLE,
        labelEs: strategy.replace(/_/g, " "),
        labelEn: strategy.replace(/_/g, " "),
      };

      return {
        label: isEs ? style.labelEs : style.labelEn,
        data: seriesValues[strategy],
        borderColor: style.borderColor,
        backgroundColor: style.backgroundColor,
        pointStyle: style.pointStyle,
        borderDash: style.borderDash,
        borderWidth: 2.5,
        pointRadius: seriesValues[strategy].length > 30 ? 3 : 4,
        pointHoverRadius: 6,
        tension: 0.15,
        fill: false,
      };
    });

    // Compute accessible summaries
    const summs = strategies.map((strategy) => {
      const values = seriesValues[strategy] || [100.0];
      const start = 100.0;
      const current = values[values.length - 1];
      const peak = Math.max(...values);
      const trough = Math.min(...values);
      const pnl = current - start;
      const roi = (pnl / start) * 100;
      const style = STRATEGY_STYLES[strategy] || DEFAULT_STYLE;

      return {
        strategy,
        name: isEs ? style.labelEs : style.labelEn,
        pattern: isEs ? style.patternEs : style.patternEn,
        color: style.color,
        pointStyle: style.pointStyle,
        current,
        peak,
        trough,
        pnl,
        roi,
        pointsCount: (data.series[strategy] || []).length,
      };
    });

    const cData: ChartData<"line"> = {
      labels,
      datasets,
    };

    return { chartData: cData, summaries: summs, hasData: true };
  }, [data, isEs]);

  const chartOptions: ChartOptions<"line"> = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: {
      mode: "index",
      intersect: false,
    },
    plugins: {
      legend: {
        position: "top",
        labels: {
          usePointStyle: true,
          boxWidth: 10,
          boxHeight: 10,
          padding: 16,
          font: {
            family: "inherit",
            weight: "bold",
            size: 12,
          },
        },
      },
      tooltip: {
        backgroundColor: "rgba(15, 23, 42, 0.95)",
        titleFont: { weight: "bold", size: 12 },
        bodyFont: { size: 12 },
        padding: 12,
        cornerRadius: 12,
        callbacks: {
          label: (context) => {
            const val = context.parsed.y ?? 100.0;
            const diff = val - 100.0;
            const sign = diff >= 0 ? "+" : "";
            return ` ${context.dataset.label}: ${val.toFixed(2)} u (${sign}${diff.toFixed(2)} u)`;
          },
        },
      },
    },
    scales: {
      x: {
        grid: { display: false },
        ticks: {
          maxTicksLimit: 8,
          font: { size: 11 },
          color: "#64748b",
        },
      },
      y: {
        grid: {
          color: "rgba(226, 232, 240, 0.8)",
        },
        ticks: {
          font: { size: 11 },
          color: "#64748b",
          callback: (value) => `${Number(value).toFixed(0)} u`,
        },
      },
    },
  };

  if (loading) {
    return (
      <div className="rounded-3xl border border-slate-200 bg-white p-6 sm:p-8 shadow-xs animate-pulse space-y-4">
        <div className="h-6 w-56 bg-slate-200 rounded-lg" />
        <div className="h-72 w-full bg-slate-100 rounded-2xl" />
        <div className="h-16 w-full bg-slate-50 rounded-xl" />
      </div>
    );
  }

  return (
    <div className="rounded-3xl border border-slate-200 bg-white p-6 sm:p-8 shadow-xs">
      {/* Title & Legend descriptor */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
        <div>
          <div className="inline-flex items-center gap-1.5 rounded-full border border-orange-200 bg-orange-50 px-3 py-0.5 text-[11px] font-black text-orange-800 mb-2">
            <LineChart className="h-3 w-3 text-orange-600" />
            <span>{isEs ? "TRAYECTORIA DE CAPITAL" : "CAPITAL TRAJECTORY"}</span>
          </div>
          <h2 className="text-xl sm:text-2xl font-black text-slate-900 tracking-tight">
            {isEs ? "Curva de Bankroll por Estrategia" : "Bankroll Trajectory by Strategy"}
          </h2>
          <p className="text-xs sm:text-sm text-slate-500 mt-0.5">
            {isEs
              ? "Evolución cronológica del balance simulado (partiendo de 100.00 u). Los patrones y figuras distinguen cada estrategia sin depender únicamente del color."
              : "Chronological progression of simulated paper balance (initial 100.00 u). Line patterns and point shapes identify strategies without relying on color alone."}
          </p>
        </div>
      </div>

      {/* Chart Canvas Area */}
      {!hasData || !chartData ? (
        <div className="flex flex-col items-center justify-center h-64 rounded-2xl border border-dashed border-slate-300 bg-slate-50/50 p-6 text-center">
          <Layers className="h-8 w-8 text-slate-400 mb-2" />
          <p className="text-sm font-semibold text-slate-700">
            {isEs ? "Aún no hay apuestas finalizadas para graficar" : "No settled bets to chart yet"}
          </p>
          <p className="text-xs text-slate-500 mt-1 max-w-sm">
            {isEs
              ? "La curva comenzará a formarse a medida que los partidos concluyan y se liquiden los resultados en el tick."
              : "Trajectory points will generate automatically once scheduled games finish and resolve."}
          </p>
        </div>
      ) : (
        <div>
          <div className="h-72 sm:h-80 w-full">
            <Line data={chartData} options={chartOptions} />
          </div>

          {/* Accessible Text Summary / Pattern Legend Table */}
          <div className="mt-8 border-t border-slate-100 pt-6">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">
              {isEs ? "Resumen de Curvas & Leyenda Accesible" : "Series Summary & Accessible Legend"}
            </h3>

            {/* Desktop Table View */}
            <div className="overflow-x-auto">
              <table
                className="w-full text-left text-xs text-slate-700"
                aria-label={
                  isEs
                    ? "Tabla de resumen de rendimiento de bankroll por estrategia"
                    : "Bankroll performance summary by strategy"
                }
              >
                <thead className="border-b border-slate-200 bg-slate-50 text-[11px] font-black uppercase tracking-wider text-slate-600">
                  <tr>
                    <th scope="col" className="px-3 py-2 rounded-l-xl">
                      {isEs ? "Estrategia & Trazo" : "Strategy & Pattern"}
                    </th>
                    <th scope="col" className="px-3 py-2 text-right">
                      {isEs ? "Apuestas" : "Bets"}
                    </th>
                    <th scope="col" className="px-3 py-2 text-right">
                      {isEs ? "Pico Máx" : "Peak"}
                    </th>
                    <th scope="col" className="px-3 py-2 text-right">
                      {isEs ? "Mínimo" : "Trough"}
                    </th>
                    <th scope="col" className="px-3 py-2 text-right">
                      {isEs ? "Actual" : "Current"}
                    </th>
                    <th scope="col" className="px-3 py-2 text-right rounded-r-xl">
                      {isEs ? "P/L Neto" : "Net P/L"}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {summaries.map((s) => {
                    const isUp = s.pnl > 0.0001;
                    const isDown = s.pnl < -0.0001;
                    return (
                      <tr key={s.strategy} className="hover:bg-slate-50/70 transition">
                        <td className="px-3 py-2.5 font-bold text-slate-900 flex items-center gap-2">
                          <span
                            className="inline-block h-3 w-3 rounded-full shrink-0"
                            style={{ backgroundColor: s.color }}
                            aria-hidden="true"
                          />
                          <div>
                            <div>{s.name}</div>
                            <div className="text-[10px] font-normal text-slate-500">{s.pattern}</div>
                          </div>
                        </td>
                        <td className="px-3 py-2.5 text-right font-mono tabular-nums">{s.pointsCount}</td>
                        <td className="px-3 py-2.5 text-right font-mono tabular-nums text-slate-600">
                          {s.peak.toFixed(2)} u
                        </td>
                        <td className="px-3 py-2.5 text-right font-mono tabular-nums text-slate-600">
                          {s.trough.toFixed(2)} u
                        </td>
                        <td className="px-3 py-2.5 text-right font-mono tabular-nums font-bold text-slate-900">
                          {s.current.toFixed(2)} u
                        </td>
                        <td className="px-3 py-2.5 text-right font-mono tabular-nums font-black">
                          <span
                            className={`inline-flex items-center gap-0.5 ${
                              isUp ? "text-emerald-600" : isDown ? "text-rose-600" : "text-slate-600"
                            }`}
                          >
                            {isUp && <ArrowUpRight className="h-3.5 w-3.5" />}
                            {isDown && <ArrowDownRight className="h-3.5 w-3.5" />}
                            <span>
                              {s.pnl > 0 ? `+${s.pnl.toFixed(2)}` : s.pnl.toFixed(2)} u ({s.roi > 0 ? "+" : ""}
                              {s.roi.toFixed(1)}%)
                            </span>
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
