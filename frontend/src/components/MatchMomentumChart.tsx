"use client";

import React, { useState } from "react";
import { usePreferences } from "@/context/PreferencesContext";
import { Activity } from "lucide-react";

export interface MatchMomentumPoint {
  minute: number;
  quarter: number;
  score_differential: number;
  possession_momentum: number;
  lead_team: number;
  event_highlight_es?: string;
  event_highlight_en?: string;
}

export interface MatchMomentumTimelineData {
  team1_name: string;
  team2_name: string;
  points: MatchMomentumPoint[];
  largest_lead_team1: number;
  largest_lead_team2: number;
  lead_changes: number;
  clutch_swing_minute: number;
}

interface MatchMomentumChartProps {
  timeline: MatchMomentumTimelineData;
}

export const MatchMomentumChart: React.FC<MatchMomentumChartProps> = ({ timeline }) => {
  const { language } = usePreferences();
  const [hoveredPoint, setHoveredPoint] = useState<MatchMomentumPoint | null>(null);

  // SVG Dimension Constants
  const width = 600;
  const height = 200;
  const paddingX = 40;
  const paddingY = 25;
  const graphWidth = width - 2 * paddingX;
  const graphHeight = height - 2 * paddingY;
  const centerY = paddingY + graphHeight / 2;

  // Max momentum range is -100 to +100
  const maxRange = 100;

  const getX = (min: number) => paddingX + (min / 48.0) * graphWidth;
  const getY = (mom: number) => centerY - (mom / maxRange) * (graphHeight / 2);

  // Build SVG Path points
  const pointsString = (timeline.points || [])
    .map((p) => `${getX(p.minute)},${getY(p.possession_momentum)}`)
    .join(" ");

  // Build Area Path for Team 1 (upper half) and Team 2 (lower half)
  const areaPointsT1 = [
    `${getX(1)},${centerY}`,
    ...(timeline.points || []).map((p) => `${getX(p.minute)},${Math.min(getY(p.possession_momentum), centerY)}`),
    `${getX(48)},${centerY}`,
  ].join(" ");

  const areaPointsT2 = [
    `${getX(1)},${centerY}`,
    ...(timeline.points || []).map((p) => `${getX(p.minute)},${Math.max(getY(p.possession_momentum), centerY)}`),
    `${getX(48)},${centerY}`,
  ].join(" ");

  return (
    <div className="rounded-3xl border border-slate-200 bg-white p-6 sm:p-7 shadow-xs">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between pb-4 border-b border-slate-100 gap-2">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-orange-50 text-orange-600 border border-orange-200">
            <Activity className="h-4 w-4" />
          </div>
          <div>
            <h3 className="text-sm font-extrabold uppercase tracking-wider text-slate-900">
              {language === "es" ? "Flujo de Momentum Táctico (48 Minutos)" : "48-Minute Match Momentum Curve"}
            </h3>
          </div>
        </div>

        {/* Tactical Key Insights */}
        <div className="flex flex-wrap items-center gap-4 text-xs font-mono text-slate-500">
          <div>
            <span className="text-slate-400">{language === "es" ? "Cambios Liderato:" : "Lead Swings:"}</span>{" "}
            <strong className="text-slate-800">{timeline.lead_changes}</strong>
          </div>
          <div>
            <span className="text-slate-400">{timeline.team1_name}:</span>{" "}
            <strong className="text-orange-600">+{timeline.largest_lead_team1}</strong>
          </div>
          <div>
            <span className="text-slate-400">{timeline.team2_name}:</span>{" "}
            <strong className="text-blue-600">+{timeline.largest_lead_team2}</strong>
          </div>
        </div>
      </div>

      {/* Team Labels */}
      <div className="flex justify-between items-center text-xs font-bold mt-3 px-2">
        <div className="flex items-center gap-1.5 text-orange-600 font-mono">
          <span className="w-2.5 h-2.5 rounded-full bg-orange-500 shadow-xs" />
          <span>▲ {timeline.team1_name} (+ Momentum)</span>
        </div>
        <div className="flex items-center gap-1.5 text-blue-600 font-mono">
          <span>▼ {timeline.team2_name} (- Momentum)</span>
          <span className="w-2.5 h-2.5 rounded-full bg-blue-600 shadow-xs" />
        </div>
      </div>

      {/* SVG Chart Area */}
      <div className="relative mt-2 w-full">
        <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-auto select-none">
          <defs>
            {/* Team 1 Gradient */}
            <linearGradient id="gradT1" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#EA580C" stopOpacity="0.25" />
              <stop offset="100%" stopColor="#EA580C" stopOpacity="0.02" />
            </linearGradient>

            {/* Team 2 Gradient */}
            <linearGradient id="gradT2" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#2563EB" stopOpacity="0.02" />
              <stop offset="100%" stopColor="#2563EB" stopOpacity="0.25" />
            </linearGradient>
          </defs>

          {/* Quarter Divider Vertical Lines */}
          {[12, 24, 36, 48].map((qMin, idx) => (
            <g key={`q-${qMin}`}>
              <line
                x1={getX(qMin)}
                y1={paddingY}
                x2={getX(qMin)}
                y2={height - paddingY}
                stroke="#E2E8F0"
                strokeWidth="1.2"
                strokeDasharray="4 4"
              />
              <text
                x={getX(qMin) - 16}
                y={height - paddingY + 14}
                fill="#94A3B8"
                fontSize="9"
                fontFamily="monospace"
                fontWeight="700"
              >
                Q{idx + 1}
              </text>
            </g>
          ))}

          {/* Center Zero Line */}
          <line
            x1={paddingX}
            y1={centerY}
            x2={width - paddingX}
            y2={centerY}
            stroke="#CBD5E1"
            strokeWidth="1.5"
          />

          {/* Area Fills */}
          <polygon points={areaPointsT1} fill="url(#gradT1)" />
          <polygon points={areaPointsT2} fill="url(#gradT2)" />

          {/* Main Polyline Curve */}
          <polyline
            fill="none"
            stroke="#0F172A"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            points={pointsString}
          />

          {/* Interactive Data Points */}
          {(timeline.points || []).map((p) => {
            const isHovered = hoveredPoint?.minute === p.minute;
            const dotColor = p.possession_momentum >= 0 ? "#EA580C" : "#2563EB";

            return (
              <circle
                key={p.minute}
                cx={getX(p.minute)}
                cy={getY(p.possession_momentum)}
                r={isHovered ? 6 : 3}
                fill={dotColor}
                stroke="#FFFFFF"
                strokeWidth={isHovered ? 2 : 1}
                className="cursor-pointer transition-all duration-150"
                onMouseEnter={() => setHoveredPoint(p)}
                onMouseLeave={() => setHoveredPoint(null)}
              />
            );
          })}
        </svg>

        {/* Hover Highlight Tooltip */}
        {hoveredPoint && (
          <div
            className="absolute top-2 left-1/2 -translate-x-1/2 bg-slate-900 text-white border border-slate-700 rounded-2xl p-3 shadow-xl text-xs max-w-sm pointer-events-none animate-in fade-in"
          >
            <div className="flex items-center justify-between gap-4 font-mono pb-1 border-b border-slate-700">
              <span className="font-bold text-amber-400">Minuto {hoveredPoint.minute}&apos; (Q{hoveredPoint.quarter})</span>
              <span className="font-bold">
                {hoveredPoint.score_differential >= 0 ? `+${hoveredPoint.score_differential}` : hoveredPoint.score_differential} Dif.
              </span>
            </div>
            <div className="mt-1.5 text-[11px] text-slate-300 leading-tight">
              {language === "es"
                ? hoveredPoint.event_highlight_es || "Posesiones clave y rotación táctica en cancha."
                : hoveredPoint.event_highlight_en || "Key possession and tactical transition."}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
