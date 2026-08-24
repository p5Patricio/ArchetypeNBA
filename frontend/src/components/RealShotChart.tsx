"use client";

import React, { useState } from "react";
import { usePreferences } from "@/context/PreferencesContext";


export interface ShotCoordinate {
  id: number;
  loc_x: number;
  loc_y: number;
  shot_made: boolean;
  shot_type: string;
  shot_distance_ft: number;
  action_type?: string;
}

export interface ZoneEfficiency {
  zone_key: string;
  zone_name_es: string;
  zone_name_en: string;
  fgm: number;
  fga: number;
  fg_pct: number;
  league_avg_pct: number;
  efficiency_diff: number;
  rating_tier: string;
}

export interface RealShotChartData {
  player_id: number;
  player_name: string;
  season_label?: string;
  total_shots_plotted: number;
  total_made: number;
  total_missed: number;
  overall_fg_pct: number;
  shots: ShotCoordinate[];
  zone_efficiencies: ZoneEfficiency[];
}

interface RealShotChartProps {
  data: RealShotChartData;
}

export const RealShotChart: React.FC<RealShotChartProps> = ({ data }) => {
  const { language } = usePreferences();
  const [filterMode, setFilterMode] = useState<"all" | "makes" | "misses" | "zones">("all");

  const [hoveredShot, setHoveredShot] = useState<ShotCoordinate | null>(null);
  const [hoveredZone, setHoveredZone] = useState<ZoneEfficiency | null>(null);

  // NBA coordinates: loc_x is -250 to 250 (tenths of feet), loc_y is -50 to 420 (tenths of feet).
  // SVG court mapping:
  // SVG viewBox: 0 0 500 470
  // svg_x = loc_x + 250
  // svg_y = loc_y + 50
  const mapCoords = (loc_x: number, loc_y: number) => {
    const svg_x = loc_x + 250;
    const svg_y = loc_y + 50;
    return { x: svg_x, y: svg_y };
  };

  const filteredShots = data.shots.filter((s) => {
    if (filterMode === "makes") return s.shot_made;
    if (filterMode === "misses") return !s.shot_made;
    return true;
  });

  const getTierColor = (tier: string) => {
    switch (tier) {
      case "elite":
        return "#10B981"; // Emerald
      case "above_average":
        return "#3B82F6"; // Blue
      case "average":
        return "#F59E0B"; // Amber
      default:
        return "#EF4444"; // Red
    }
  };

  return (
    <div className="bg-[#111827]/90 border border-white/10 rounded-2xl p-6 backdrop-blur-xl shadow-2xl relative overflow-hidden">
      {/* Background Neon Brand Glow */}
      <div className="absolute -top-24 -left-24 w-72 h-72 bg-blue-600/10 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute -bottom-24 -right-24 w-72 h-72 bg-emerald-600/10 rounded-full blur-3xl pointer-events-none" />

      {/* Header & Filter Controls */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between pb-6 border-b border-white/10 gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <span className="px-2.5 py-1 text-xs font-semibold uppercase tracking-wider rounded-md bg-blue-500/20 text-blue-400 border border-blue-500/30">
              NBA Official Spatial Coordinates
            </span>
            <span className="text-xs text-gray-400">
              {data.total_shots_plotted} {language === "es" ? "tiros analizados" : "shots plotted"}
            </span>
          </div>
          <h2 className="text-2xl font-bold text-white tracking-wide mt-1.5 flex items-center gap-2">
            <span>{data.player_name}</span>
            <span className="text-sm font-normal text-gray-400">({data.season_label || "Active"})</span>
          </h2>
        </div>

        {/* Filter Buttons */}
        <div className="flex items-center gap-1.5 bg-black/40 p-1.5 rounded-xl border border-white/10">
          <button
            onClick={() => setFilterMode("all")}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              filterMode === "all" ? "bg-white/20 text-white shadow-sm" : "text-gray-400 hover:text-white"
            }`}
          >
            {language === "es" ? "Todos" : "All"} ({data.total_shots_plotted})
          </button>
          <button
            onClick={() => setFilterMode("makes")}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              filterMode === "makes" ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40" : "text-emerald-500/70 hover:text-emerald-400"
            }`}
          >
            ● {language === "es" ? "Aciertos" : "Makes"} ({data.total_made})
          </button>
          <button
            onClick={() => setFilterMode("misses")}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              filterMode === "misses" ? "bg-rose-500/20 text-rose-300 border border-rose-500/40" : "text-rose-500/70 hover:text-rose-400"
            }`}
          >
            ✕ {language === "es" ? "Fallos" : "Misses"} ({data.total_missed})
          </button>
          <button
            onClick={() => setFilterMode("zones")}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              filterMode === "zones" ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/40" : "text-indigo-400/70 hover:text-indigo-300"
            }`}
          >
            {language === "es" ? "Zonas" : "Zones"}
          </button>
        </div>
      </div>

      {/* Main Grid: Half Court Diagram + Zone Efficiency Badges */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start mt-6">
        {/* Half Court SVG Visualization (7 cols) */}
        <div className="lg:col-span-7 flex flex-col items-center justify-center relative">
          <div className="w-full max-w-[460px] bg-slate-950/80 rounded-2xl p-4 border border-white/10 shadow-2xl relative">
            <svg viewBox="0 0 500 470" className="w-full h-auto drop-shadow-lg select-none">
              {/* Outer Court Boundary */}
              <rect x="0" y="0" width="500" height="470" fill="#0B0F19" stroke="#374151" strokeWidth="2" rx="8" />

              {/* Paint Key Box (160 wide, 190 deep) */}
              <rect x="170" y="0" width="160" height="190" fill="#111827" stroke="#4B5563" strokeWidth="2" />
              <rect x="190" y="0" width="120" height="190" fill="none" stroke="#374151" strokeWidth="1" strokeDasharray="4 4" />

              {/* Free Throw Circle (radius 60 from center (250, 190)) */}
              <circle cx="250" cy="190" r="60" fill="none" stroke="#4B5563" strokeWidth="2" />
              <circle cx="250" cy="190" r="60" fill="none" stroke="#374151" strokeWidth="1" strokeDasharray="4 4" />

              {/* Restricted Area Arc (radius 40 from hoop (250, 52.5)) */}
              <path d="M 210 52.5 A 40 40 0 0 0 290 52.5" fill="none" stroke="#4B5563" strokeWidth="2" />

              {/* Backboard & Hoop */}
              <line x1="220" y1="40" x2="280" y2="40" stroke="#F3F4F6" strokeWidth="3" />
              <circle cx="250" cy="52.5" r="7.5" fill="none" stroke="#F97316" strokeWidth="2.5" />
              <line x1="250" y1="40" x2="250" y2="45" stroke="#F3F4F6" strokeWidth="2" />

              {/* Corner 3 Straight Lines (x=30 and x=470 from y=0 to y=140) */}
              <line x1="30" y1="0" x2="30" y2="140" stroke="#4B5563" strokeWidth="2" />
              <line x1="470" y1="0" x2="470" y2="140" stroke="#4B5563" strokeWidth="2" />

              {/* 3-Point Arc (radius 237.5 from hoop at (250, 52.5)) */}
              <path
                d="M 30 140 A 237.5 237.5 0 0 0 470 140"
                fill="none"
                stroke="#4B5563"
                strokeWidth="2"
              />

              {/* Center Court Circle Top Arc */}
              <path d="M 190 470 A 60 60 0 0 1 310 470" fill="none" stroke="#374151" strokeWidth="2" />

              {/* Zone Heatmap Overlay (when filterMode === 'zones') */}
              {filterMode === "zones" && (
                <g opacity="0.65">
                  {/* Restricted Area */}
                  <circle
                    cx="250"
                    cy="52.5"
                    r="40"
                    fill={getTierColor(data.zone_efficiencies.find((z) => z.zone_key === "restricted_area")?.rating_tier || "average")}
                    opacity="0.4"
                  />
                  {/* Paint Non-RA */}
                  <rect
                    x="170"
                    y="52.5"
                    width="160"
                    height="137.5"
                    fill={getTierColor(data.zone_efficiencies.find((z) => z.zone_key === "in_paint_non_ra")?.rating_tier || "average")}
                    opacity="0.3"
                  />
                  {/* Mid-Range */}
                  <path
                    d="M 30 140 A 237.5 237.5 0 0 0 470 140 L 330 0 L 170 0 Z"
                    fill={getTierColor(data.zone_efficiencies.find((z) => z.zone_key === "mid_range")?.rating_tier || "average")}
                    opacity="0.2"
                  />
                </g>
              )}

              {/* Individual Shot Points */}
              {filterMode !== "zones" &&
                filteredShots.map((shot) => {
                  const { x, y } = mapCoords(shot.loc_x, shot.loc_y);
                  const isHovered = hoveredShot?.id === shot.id;

                  if (shot.shot_made) {
                    return (
                      <circle
                        key={shot.id}
                        cx={x}
                        cy={y}
                        r={isHovered ? 6 : 3.5}
                        fill="#10B981"
                        fillOpacity={isHovered ? 1.0 : 0.85}
                        stroke="#064E3B"
                        strokeWidth={1}
                        onMouseEnter={() => setHoveredShot(shot)}
                        onMouseLeave={() => setHoveredShot(null)}
                        className="cursor-pointer transition-all hover:scale-125"
                      />
                    );
                  } else {
                    return (
                      <g
                        key={shot.id}
                        onMouseEnter={() => setHoveredShot(shot)}
                        onMouseLeave={() => setHoveredShot(null)}
                        className="cursor-pointer"
                      >
                        <line
                          x1={x - (isHovered ? 4 : 2.5)}
                          y1={y - (isHovered ? 4 : 2.5)}
                          x2={x + (isHovered ? 4 : 2.5)}
                          y2={y + (isHovered ? 4 : 2.5)}
                          stroke="#EF4444"
                          strokeWidth={isHovered ? 2.5 : 1.5}
                          strokeOpacity={isHovered ? 1.0 : 0.75}
                        />
                        <line
                          x1={x - (isHovered ? 4 : 2.5)}
                          y1={y + (isHovered ? 4 : 2.5)}
                          x2={x + (isHovered ? 4 : 2.5)}
                          y2={y - (isHovered ? 4 : 2.5)}
                          stroke="#EF4444"
                          strokeWidth={isHovered ? 2.5 : 1.5}
                          strokeOpacity={isHovered ? 1.0 : 0.75}
                        />
                      </g>
                    );
                  }
                })}
            </svg>

            {/* Hover Floating Tooltip */}
            {hoveredShot ? (
              <div className="absolute bottom-6 left-1/2 -translate-x-1/2 bg-gray-900/95 border border-white/15 px-4 py-2 rounded-xl backdrop-blur-md shadow-2xl text-center z-10">
                <div className="text-xs font-bold text-white flex items-center justify-center gap-2">
                  <span className={hoveredShot.shot_made ? "text-emerald-400" : "text-rose-400"}>
                    {hoveredShot.shot_made ? "● MADE" : "✕ MISSED"}
                  </span>
                  <span>{hoveredShot.shot_type}</span>
                </div>
                <div className="text-[11px] text-gray-400 mt-0.5">
                  {hoveredShot.shot_distance_ft} ft • {hoveredShot.action_type || "Jump Shot"}
                </div>
              </div>
            ) : (
              <div className="mt-2 text-center text-xs text-gray-500">
                {language === "es" ? "● Verde = Anotado | ✕ Rojo = Fallado" : "● Green = Made | ✕ Red = Missed"}
              </div>
            )}
          </div>
        </div>

        {/* 6 Zone Efficiencies Breakdown (5 cols) */}
        <div className="lg:col-span-5 space-y-3">
          <div className="flex items-center justify-between pb-2 border-b border-white/10">
            <h3 className="text-sm font-bold uppercase tracking-wider text-gray-300">
              {language === "es" ? "Eficiencia por Zonas vs Promedio NBA" : "Zone Efficiency vs League Avg"}
            </h3>
            <span className="text-xs font-bold text-emerald-400 font-mono">
              FG% {data.overall_fg_pct.toFixed(1)}%
            </span>
          </div>

          <div className="space-y-2.5">
            {data.zone_efficiencies.map((zone) => {
              const diffSign = zone.efficiency_diff >= 0 ? "+" : "";
              const tierColor = getTierColor(zone.rating_tier);

              return (
                <div
                  key={zone.zone_key}
                  onMouseEnter={() => setHoveredZone(zone)}
                  onMouseLeave={() => setHoveredZone(null)}
                  className="bg-black/30 border border-white/5 rounded-xl p-3 hover:border-white/15 transition-all"
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-xs font-bold text-gray-200">
                        {language === "es" ? zone.zone_name_es : zone.zone_name_en}
                      </div>
                      <div className="text-[11px] text-gray-400 font-mono mt-0.5">
                        {zone.fgm} / {zone.fga} FGA ({zone.fg_pct.toFixed(1)}%)
                      </div>
                    </div>

                    <div className="text-right">
                      <span
                        className="text-xs font-bold font-mono px-2 py-0.5 rounded-full"
                        style={{
                          backgroundColor: `${tierColor}25`,
                          color: tierColor,
                          border: `1px solid ${tierColor}40`,
                        }}
                      >
                        {diffSign}
                        {zone.efficiency_diff.toFixed(1)}%
                      </span>
                      <div className="text-[10px] text-gray-500 mt-1">
                        {language === "es" ? "Media:" : "Avg:"} {zone.league_avg_pct.toFixed(1)}%
                      </div>
                    </div>
                  </div>

                  {/* Visual Progress Comparison Bar */}
                  <div className="w-full bg-gray-800 h-1.5 rounded-full overflow-hidden mt-2.5 relative">
                    <div
                      className="h-full rounded-full transition-all duration-500"
                      style={{
                        width: `${Math.min(zone.fg_pct, 100)}%`,
                        backgroundColor: tierColor,
                      }}
                    />
                    {/* League Average Marker */}
                    <div
                      className="absolute top-0 bottom-0 w-0.5 bg-white opacity-80"
                      style={{ left: `${zone.league_avg_pct}%` }}
                      title={`League Avg: ${zone.league_avg_pct}%`}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};
