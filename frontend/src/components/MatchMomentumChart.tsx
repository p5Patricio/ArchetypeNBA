"use client";

import React, { useState } from "react";
import { usePreferences } from "@/context/PreferencesContext";


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
  const pointsString = timeline.points
    .map((p) => `${getX(p.minute)},${getY(p.possession_momentum)}`)
    .join(" ");

  // Build Area Path for Team 1 (upper half) and Team 2 (lower half)
  const areaPointsT1 = [
    `${getX(1)},${centerY}`,
    ...timeline.points.map((p) => `${getX(p.minute)},${Math.min(getY(p.possession_momentum), centerY)}`),
    `${getX(48)},${centerY}`,
  ].join(" ");

  const areaPointsT2 = [
    `${getX(1)},${centerY}`,
    ...timeline.points.map((p) => `${getX(p.minute)},${Math.max(getY(p.possession_momentum), centerY)}`),
    `${getX(48)},${centerY}`,
  ].join(" ");

  return (
    <div className="bg-[#111827]/90 border border-white/10 rounded-2xl p-6 backdrop-blur-xl shadow-2xl relative overflow-hidden">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between pb-4 border-b border-white/10 gap-2">
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full bg-cyan-400 animate-pulse" />
          <h3 className="text-sm font-bold uppercase tracking-wider text-gray-200">
            {language === "es" ? "Flujo de Momentum Táctico (48 Min)" : "Match Momentum Flow (48 Min)"}
          </h3>
        </div>

        {/* Tactical Key Insights */}
        <div className="flex items-center gap-4 text-xs font-mono text-gray-400">
          <div>
            <span className="text-gray-500">{language === "es" ? "Cambios de Liderato:" : "Lead Changes:"}</span>{" "}
            <span className="font-bold text-amber-400">{timeline.lead_changes}</span>
          </div>
          <div>
            <span className="text-gray-500">{language === "es" ? "Máx Ventaja T1:" : "Max Lead T1:"}</span>{" "}
            <span className="font-bold text-orange-400">+{timeline.largest_lead_team1}</span>
          </div>
          <div>
            <span className="text-gray-500">{language === "es" ? "Máx Ventaja T2:" : "Max Lead T2:"}</span>{" "}
            <span className="font-bold text-blue-400">+{timeline.largest_lead_team2}</span>
          </div>
        </div>
      </div>

      {/* Team Labels */}
      <div className="flex justify-between items-center text-xs font-bold text-gray-400 mt-2 px-2">
        <div className="flex items-center gap-1.5 text-orange-400">
          <span className="w-2 h-2 rounded-full bg-orange-500" />
          <span>{timeline.team1_name} (Dominance ▲)</span>
        </div>
        <div className="flex items-center gap-1.5 text-blue-400">
          <span>{timeline.team2_name} (Dominance ▼)</span>
          <span className="w-2 h-2 rounded-full bg-blue-500" />
        </div>
      </div>

      {/* SVG Momentum Flow Graph */}
      <div className="relative mt-2">
        <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-auto drop-shadow-md select-none">
          <defs>
            <linearGradient id="gradT1" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#F97316" stopOpacity="0.45" />
              <stop offset="100%" stopColor="#F97316" stopOpacity="0.0" />
            </linearGradient>
            <linearGradient id="gradT2" x1="0" y1="1" x2="0" y2="0">
              <stop offset="0%" stopColor="#3B82F6" stopOpacity="0.45" />
              <stop offset="100%" stopColor="#3B82F6" stopOpacity="0.0" />
            </linearGradient>
          </defs>

          {/* Quarter Vertical Demarcations */}
          {[12, 24, 36].map((qMin, idx) => (
            <g key={`q-line-${qMin}`}>
              <line
                x1={getX(qMin)}
                y1={paddingY}
                x2={getX(qMin)}
                y2={height - paddingY}
                stroke="#374151"
                strokeWidth="1"
                strokeDasharray="4 4"
              />
              <text
                x={getX(qMin)}
                y={paddingY - 8}
                fill="#9CA3AF"
                fontSize="10"
                textAnchor="middle"
                fontWeight="600"
              >
                {idx === 1 ? (language === "es" ? "DESCANSO" : "HALF") : `Q${idx + 1}`}
              </text>
            </g>
          ))}

          {/* Center Zero-Line (Equality) */}
          <line
            x1={paddingX}
            y1={centerY}
            x2={width - paddingX}
            y2={centerY}
            stroke="#4B5563"
            strokeWidth="1.5"
          />

          {/* Area Fills */}
          <polygon points={areaPointsT1} fill="url(#gradT1)" />
          <polygon points={areaPointsT2} fill="url(#gradT2)" />

          {/* Main Momentum Curve Line */}
          <polyline
            fill="none"
            stroke="#E5E7EB"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            points={pointsString}
          />

          {/* Interactive Hover Dots */}
          {timeline.points.map((p) => (
            <circle
              key={p.minute}
              cx={getX(p.minute)}
              cy={getY(p.possession_momentum)}
              r={hoveredPoint?.minute === p.minute ? 5 : 2.5}
              fill={p.score_differential >= 0 ? "#F97316" : "#3B82F6"}
              stroke="#FFFFFF"
              strokeWidth={hoveredPoint?.minute === p.minute ? 1.5 : 0}
              className="cursor-pointer transition-all"
              onMouseEnter={() => setHoveredPoint(p)}
              onMouseLeave={() => setHoveredPoint(null)}
            />
          ))}
        </svg>

        {/* Dynamic Tooltip */}
        {hoveredPoint ? (
          <div className="absolute top-2 left-1/2 -translate-x-1/2 bg-gray-900/95 border border-white/20 px-4 py-2 rounded-xl backdrop-blur-md shadow-2xl text-center z-10">
            <div className="text-xs font-bold text-white">
              Min {hoveredPoint.minute}&apos; (Q{hoveredPoint.quarter})
            </div>
            <div className="text-[11px] font-mono text-gray-300 mt-0.5">
              {language === "es" ? "Diferencia:" : "Lead:"}{" "}
              <span className={hoveredPoint.score_differential >= 0 ? "text-orange-400 font-bold" : "text-blue-400 font-bold"}>
                {hoveredPoint.score_differential > 0
                  ? `${timeline.team1_name} +${hoveredPoint.score_differential}`
                  : hoveredPoint.score_differential < 0
                  ? `${timeline.team2_name} +${-hoveredPoint.score_differential}`
                  : "Empate (Tied)"}
              </span>
            </div>
            {hoveredPoint.event_highlight_es && (
              <div className="text-[10px] text-amber-300 font-medium mt-1">
                ⚡ {language === "es" ? hoveredPoint.event_highlight_es : hoveredPoint.event_highlight_en}
              </div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
};
