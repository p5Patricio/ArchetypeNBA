"use client";

import {
  Chart as ChartJS,
  RadialLinearScale,
  PointElement,
  LineElement,
  Filler,
  Tooltip,
  Legend,
} from "chart.js";
import { Radar } from "react-chartjs-2";
import { usePreferences } from "@/context/PreferencesContext";

ChartJS.register(
  RadialLinearScale,
  PointElement,
  LineElement,
  Filler,
  Tooltip,
  Legend
);

interface RadarChartProps {
  playerStats: {
    pts?: number;
    reb?: number;
    ast?: number;
    stl?: number;
    blk?: number;
    fg3m?: number;
    fg_pct?: number;
  };
  clusterStats?: {
    pts?: number;
    reb?: number;
    ast?: number;
    stl?: number;
    blk?: number;
    fg3m?: number;
    fg_pct?: number;
  };
  playerName?: string;
  clusterName?: string;
  className?: string;
}

export function RadarChart({
  playerStats,
  clusterStats,
  playerName = "Jugador",
  clusterName,
  className = "",
}: RadarChartProps) {
  const { t } = usePreferences();

  // Benchmark scales for NBA per-game metrics
  const maxVals = {
    pts: 35,
    reb: 14,
    ast: 11,
    stl: 2.5,
    blk: 3.0,
    fg3m: 4.5,
    fg_pct: 0.65,
  };

  const normalize = (val?: number, max: number = 100) => {
    if (!val) return 0;
    return Math.min(Math.round((val / max) * 100), 100);
  };

  const playerScores = [
    normalize(playerStats.pts, maxVals.pts),
    normalize(playerStats.reb, maxVals.reb),
    normalize(playerStats.ast, maxVals.ast),
    normalize(playerStats.stl, maxVals.stl),
    normalize(playerStats.blk, maxVals.blk),
    normalize(playerStats.fg3m, maxVals.fg3m),
    normalize(playerStats.fg_pct, maxVals.fg_pct),
  ];

  const clusterScores = clusterStats
    ? [
        normalize(clusterStats.pts, maxVals.pts),
        normalize(clusterStats.reb, maxVals.reb),
        normalize(clusterStats.ast, maxVals.ast),
        normalize(clusterStats.stl, maxVals.stl),
        normalize(clusterStats.blk, maxVals.blk),
        normalize(clusterStats.fg3m, maxVals.fg3m),
        normalize(clusterStats.fg_pct, maxVals.fg_pct),
      ]
    : [50, 50, 50, 50, 50, 50, 50];

  const data = {
    labels: [
      t("radar_pts"),
      t("radar_reb"),
      t("radar_ast"),
      t("radar_stl"),
      t("radar_blk"),
      t("radar_3pm"),
      t("radar_fg_pct"),
    ],
    datasets: [
      {
        label: playerName,
        data: playerScores,
        backgroundColor: "rgba(255, 107, 0, 0.25)", // Naranja Básquetbol
        borderColor: "#EA580C",
        borderWidth: 3,
        pointBackgroundColor: "#EA580C",
        pointBorderColor: "#FFFFFF",
        pointBorderWidth: 2,
        pointHoverBackgroundColor: "#FFFFFF",
        pointHoverBorderColor: "#EA580C",
        pointRadius: 5,
      },
      {
        label: clusterName || t("radar_benchmark"),
        data: clusterScores,
        backgroundColor: "rgba(2, 132, 199, 0.15)", // Azul NBA
        borderColor: "#0284C7",
        borderWidth: 2,
        borderDash: [5, 5],
        pointBackgroundColor: "#0284C7",
        pointBorderColor: "#FFFFFF",
        pointBorderWidth: 2,
        pointRadius: 4,
      },
    ],
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    scales: {
      r: {
        angleLines: {
          color: "#E2E8F0",
        },
        grid: {
          color: "#F1F5F9",
        },
        pointLabels: {
          color: "#1E293B",
          font: {
            size: 11,
            weight: 700 as const,
          },
        },
        ticks: {
          display: false,
          max: 100,
          min: 0,
          stepSize: 20,
        },
      },
    },
    plugins: {
      legend: {
        position: "bottom" as const,
        labels: {
          color: "#0F172A",
          font: {
            size: 12,
            weight: 700 as const,
          },
          padding: 16,
          boxWidth: 12,
        },
      },
      tooltip: {
        backgroundColor: "#0F172A",
        titleColor: "#FFFFFF",
        bodyColor: "#94A3B8",
        borderColor: "#334155",
        borderWidth: 1,
        padding: 10,
        callbacks: {
          label: (context: any) => `${context.dataset.label}: ${context.raw}${t("radar_tooltip_suffix")}`,
        },
      },
    },
  };

  return (
    <div className={`rounded-2xl border border-slate-200 bg-white p-6 shadow-sm ${className}`}>
      <div className="h-72 sm:h-80 w-full">
        <Radar data={data} options={options} />
      </div>
    </div>
  );
}
