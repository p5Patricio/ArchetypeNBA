"use client";

import React from "react";
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

interface TrainingTriRadarProps {
  labels: string[];
  playerValues: number[];
  benchmarkValues: number[];
  projectedValues: number[];
  playerName?: string;
  positionLabel?: string;
  className?: string;
}

export function TrainingTriRadar({
  labels,
  playerValues,
  benchmarkValues,
  projectedValues,
  playerName = "Jugador",
  positionLabel = "Posición",
  className = "",
}: TrainingTriRadarProps) {
  const { t } = usePreferences();

  // Normalize values (0 to 100)
  const normPlayer = playerValues.map((v) => Math.round(v * 100));
  const normBench = benchmarkValues.map((v) => Math.round(v * 100));
  const normProj = projectedValues.map((v) => Math.round(v * 100));

  const data = {
    labels: labels && labels.length > 0 ? labels : [
      "Anotación", "Rebotes", "Creación", "Tiro Exterior", "Defensa", "Eficiencia"
    ],
    datasets: [
      {
        label: `${playerName} (${t("training_radar_player") || "Actual"})`,
        data: normPlayer,
        backgroundColor: "rgba(234, 88, 12, 0.22)", // Orange
        borderColor: "#EA580C",
        borderWidth: 2.5,
        pointBackgroundColor: "#EA580C",
        pointBorderColor: "#FFFFFF",
        pointBorderWidth: 2,
        pointRadius: 4,
      },
      {
        label: `${t("training_radar_benchmark") || "Media Posicional"} (${positionLabel})`,
        data: normBench,
        backgroundColor: "rgba(100, 116, 139, 0.12)", // Slate
        borderColor: "#64748B",
        borderWidth: 2,
        borderDash: [5, 5],
        pointBackgroundColor: "#64748B",
        pointBorderColor: "#FFFFFF",
        pointBorderWidth: 1.5,
        pointRadius: 3,
      },
      {
        label: `${t("training_radar_projected") || "Proyectado Post-Drills"} ⚡`,
        data: normProj,
        backgroundColor: "rgba(6, 182, 212, 0.20)", // Cyan / Electric Blue
        borderColor: "#0891B2",
        borderWidth: 2.5,
        pointBackgroundColor: "#0891B2",
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
          color: "#0F172A",
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
          color: "#1E293B",
          font: {
            size: 11,
            weight: 700 as const,
          },
          padding: 14,
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
          label: (context: any) => `${context.dataset.label}: ${context.raw}% del tope NBA`,
        },
      },
    },
  };

  return (
    <div className={`relative h-72 sm:h-84 w-full ${className}`}>
      <Radar data={data} options={options} />
    </div>
  );
}
