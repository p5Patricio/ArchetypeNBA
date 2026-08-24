"use client";

import React, { useState } from "react";
import { usePreferences } from "@/context/PreferencesContext";
import { Target } from "lucide-react";

export interface ShotCoordinate {
  id: number;
  loc_x: number;
  loc_y: number;
  shot_made?: boolean;
  shot_made_flag?: boolean;
  shot_type?: string;
  shot_distance_ft?: number;
  action_type?: string;
  period?: number;
}

export interface ZoneEfficiency {
  zone_key: string;
  zone_name_es: string;
  zone_name_en: string;
  fgm: number;
  fga: number;
  fg_pct: number;
  league_avg_pct: number;
  diff_pct?: number;
  efficiency_diff?: number;
  status?: string;
  rating_tier?: string;
}

export interface RealShotChartData {
  player_id: number;
  player_name: string;
  season_label?: string;
  total_fga?: number;
  total_fgm?: number;
  total_shots_plotted?: number;
  total_made?: number;
  total_missed?: number;
  overall_fg_pct?: number;
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

  const shotsList = data.shots || [];
  const zonesList = data.zone_efficiencies || [];

  const totalShots = data.total_shots_plotted ?? data.total_fga ?? shotsList.length;
  const totalMade = data.total_made ?? data.total_fgm ?? shotsList.filter((s) => s.shot_made || s.shot_made_flag).length;
  const totalMissed = data.total_missed ?? (totalShots - totalMade);
  const overallFgPct = data.overall_fg_pct ?? (totalShots > 0 ? (totalMade / totalShots) * 100 : 0);

  // NBA coordinates: loc_x is -250 to 250 (tenths of feet), loc_y is -50 to 420 (tenths of feet).
  const mapCoords = (loc_x: number, loc_y: number) => {
    const svg_x = loc_x + 250;
    const svg_y = loc_y + 50;
    return { x: svg_x, y: svg_y };
  };

  const isShotMade = (s: ShotCoordinate) => Boolean(s.shot_made ?? s.shot_made_flag);

  const filteredShots = shotsList.filter((s) => {
    const made = isShotMade(s);
    if (filterMode === "makes") return made;
    if (filterMode === "misses") return !made;
    return true;
  });

  const getTierColor = (tierOrStatus?: string) => {
    switch (tierOrStatus) {
      case "elite":
      case "hot":
        return "#10B981"; // Emerald
      case "above_average":
        return "#3B82F6"; // Blue
      case "average":
        return "#F59E0B"; // Amber
      default:
        return "#EF4444"; // Red / Cold
    }
  };

  return (
    <div className="rounded-3xl border border-slate-200 bg-white p-6 sm:p-7 shadow-xs">
      {/* Header & Filter Controls */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between pb-6 border-b border-slate-100 gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <span className="px-2.5 py-1 text-[10px] font-black uppercase tracking-wider rounded-lg bg-cyan-50 text-cyan-800 border border-cyan-200">
              NBA Official Spatial Coordinates
            </span>
            <span className="text-xs font-semibold text-slate-500">
              {totalShots} {language === "es" ? "tiros registrados" : "shots plotted"}
            </span>
          </div>
          <h2 className="text-2xl font-black text-slate-900 tracking-tight mt-1.5 flex items-center gap-2">
            <span>{data.player_name}</span>
            <span className="text-sm font-semibold text-slate-400">({data.season_label || "2023-24"})</span>
          </h2>
        </div>

        {/* Filter Buttons */}
        <div className="flex items-center gap-1.5 bg-slate-100 p-1 rounded-2xl border border-slate-200/80">
          <button
            onClick={() => setFilterMode("all")}
            className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all ${
              filterMode === "all" ? "bg-white text-slate-900 shadow-2xs" : "text-slate-500 hover:text-slate-800"
            }`}
          >
            {language === "es" ? "Todos" : "All"} ({totalShots})
          </button>
          <button
            onClick={() => setFilterMode("makes")}
            className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all ${
              filterMode === "makes" ? "bg-emerald-600 text-white shadow-xs" : "text-emerald-700 hover:text-emerald-800"
            }`}
          >
            ● {language === "es" ? "Aciertos" : "Makes"} ({totalMade})
          </button>
          <button
            onClick={() => setFilterMode("misses")}
            className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all ${
              filterMode === "misses" ? "bg-rose-600 text-white shadow-xs" : "text-rose-700 hover:text-rose-800"
            }`}
          >
            ✕ {language === "es" ? "Fallos" : "Misses"} ({totalMissed})
          </button>
          <button
            onClick={() => setFilterMode("zones")}
            className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all ${
              filterMode === "zones" ? "bg-indigo-600 text-white shadow-xs" : "text-indigo-700 hover:text-indigo-800"
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
          <div className="w-full max-w-[460px] bg-white rounded-3xl p-4 border border-slate-200 shadow-xs relative">
            <svg viewBox="0 0 500 470" className="w-full h-auto select-none">
              <defs>
                <pattern id="halfCourtGrid" width="30" height="30" patternUnits="userSpaceOnUse">
                  <path d="M 30 0 L 0 0 0 30" fill="none" stroke="#F1F5F9" strokeWidth="0.8" />
                </pattern>
              </defs>

              {/* Court Floor with subtle grid */}
              <rect x="0" y="0" width="500" height="470" fill="#FAFAFA" rx="16" />
              <rect x="0" y="0" width="500" height="470" fill="url(#halfCourtGrid)" rx="16" />
              <rect x="0" y="0" width="500" height="470" fill="none" stroke="#CBD5E1" strokeWidth="2" rx="16" />

              {/* Paint Key Box */}
              <rect x="170" y="0" width="160" height="190" fill="#FFF7ED" stroke="#F97316" strokeWidth="1.8" />
              <rect x="190" y="0" width="120" height="190" fill="none" stroke="#FDBA74" strokeWidth="1" strokeDasharray="4 4" />

              {/* Free Throw Circle */}
              <circle cx="250" cy="190" r="60" fill="none" stroke="#EA580C" strokeWidth="1.8" />
              <circle cx="250" cy="190" r="60" fill="none" stroke="#FDBA74" strokeWidth="1" strokeDasharray="4 4" />

              {/* Restricted Area Arc */}
              <path d="M 210 52.5 A 40 40 0 0 0 290 52.5" fill="none" stroke="#EA580C" strokeWidth="1.8" />

              {/* Backboard & Hoop */}
              <line x1="220" y1="40" x2="280" y2="40" stroke="#1E293B" strokeWidth="3.5" strokeLinecap="round" />
              <circle cx="250" cy="52.5" r="8" fill="#FFEDD5" stroke="#EA580C" strokeWidth="2.5" />
              <line x1="250" y1="40" x2="250" y2="44.5" stroke="#1E293B" strokeWidth="2.5" />

              {/* Corner 3 Straight Lines */}
              <line x1="30" y1="0" x2="30" y2="140" stroke="#475569" strokeWidth="2" />
              <line x1="470" y1="0" x2="470" y2="140" stroke="#475569" strokeWidth="2" />

              {/* 3-Point Arc */}
              <path
                d="M 30 140 A 237.5 237.5 0 0 0 470 140"
                fill="none"
                stroke="#475569"
                strokeWidth="2"
              />

              {/* Center Court Circle Top Arc */}
              <path d="M 190 470 A 60 60 0 0 1 310 470" fill="none" stroke="#64748B" strokeWidth="2" />

              {/* Individual Shot Points */}
              {filterMode !== "zones" &&
                filteredShots.map((shot) => {
                  const { x, y } = mapCoords(shot.loc_x, shot.loc_y);
                  const isHovered = hoveredShot?.id === shot.id;
                  const made = isShotMade(shot);

                  if (made) {
                    return (
                      <circle
                        key={shot.id}
                        cx={x}
                        cy={y}
                        r={isHovered ? 7 : 4}
                        fill="#10B981"
                        stroke="#064E3B"
                        strokeWidth={1.5}
                        className="cursor-pointer transition-all duration-150"
                        opacity={hoveredShot && !isHovered ? 0.35 : 0.9}
                        onMouseEnter={() => setHoveredShot(shot)}
                        onMouseLeave={() => setHoveredShot(null)}
                      />
                    );
                  } else {
                    return (
                      <g
                        key={shot.id}
                        className="cursor-pointer transition-all duration-150"
                        opacity={hoveredShot && !isHovered ? 0.35 : 0.8}
                        onMouseEnter={() => setHoveredShot(shot)}
                        onMouseLeave={() => setHoveredShot(null)}
                      >
                        <line
                          x1={x - (isHovered ? 5 : 3.5)}
                          y1={y - (isHovered ? 5 : 3.5)}
                          x2={x + (isHovered ? 5 : 3.5)}
                          y2={y + (isHovered ? 5 : 3.5)}
                          stroke="#EF4444"
                          strokeWidth={isHovered ? 2.5 : 1.8}
                        />
                        <line
                          x1={x + (isHovered ? 5 : 3.5)}
                          y1={y - (isHovered ? 5 : 3.5)}
                          x2={x - (isHovered ? 5 : 3.5)}
                          y2={y + (isHovered ? 5 : 3.5)}
                          stroke="#EF4444"
                          strokeWidth={isHovered ? 2.5 : 1.8}
                        />
                      </g>
                    );
                  }
                })}
            </svg>

            {/* Hover Tooltip Overlay */}
            {hoveredShot && (
              <div className="absolute top-6 left-6 bg-slate-900 text-white rounded-xl p-3 shadow-xl text-xs max-w-[220px] pointer-events-none animate-in fade-in">
                <div className="flex items-center gap-2">
                  <span
                    className={`w-2.5 h-2.5 rounded-full ${
                      isShotMade(hoveredShot) ? "bg-emerald-400" : "bg-rose-400"
                    }`}
                  />
                  <span className="font-bold">
                    {isShotMade(hoveredShot)
                      ? language === "es" ? "Acierto" : "Made"
                      : language === "es" ? "Fallo" : "Missed"}
                  </span>
                </div>
                <div className="text-slate-300 font-mono text-[11px] mt-1">
                  {hoveredShot.action_type || "Tiro de Campo"}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* 6 Zone Efficiency Breakdown List (5 cols) */}
        <div className="lg:col-span-5 space-y-4">
          <div className="flex items-center justify-between pb-2 border-b border-slate-100">
            <h3 className="text-xs font-extrabold text-slate-700 uppercase tracking-wider">
              {language === "es" ? "Eficiencia por Zonas vs Promedio NBA" : "Zone Efficiency vs League Avg"}
            </h3>
            <span className="text-xs font-black text-emerald-700 font-mono">
              FG% {overallFgPct.toFixed(1)}%
            </span>
          </div>

          <div className="space-y-2.5">
            {zonesList.map((zone) => {
              const diffVal = zone.diff_pct ?? zone.efficiency_diff ?? 0;
              const diffSign = diffVal >= 0 ? "+" : "";
              const tierColor = getTierColor(zone.status || zone.rating_tier);
              const fgPct = zone.fg_pct ?? 0;
              const leagueAvg = zone.league_avg_pct ?? 0;

              return (
                <div
                  key={zone.zone_key}
                  onMouseEnter={() => setHoveredZone(zone)}
                  onMouseLeave={() => setHoveredZone(null)}
                  className="bg-slate-50/80 border border-slate-200/90 rounded-2xl p-3 hover:border-slate-300 hover:bg-slate-50 transition-all"
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-xs font-bold text-slate-900">
                        {language === "es" ? zone.zone_name_es : zone.zone_name_en}
                      </div>
                      <div className="text-[11px] text-slate-500 font-mono mt-0.5">
                        {zone.fgm} / {zone.fga} FGA ({fgPct.toFixed(1)}%)
                      </div>
                    </div>

                    <div className="text-right">
                      <span
                        className="text-xs font-black font-mono px-2 py-0.5 rounded-full"
                        style={{
                          backgroundColor: `${tierColor}18`,
                          color: tierColor,
                          border: `1px solid ${tierColor}35`,
                        }}
                      >
                        {diffSign}
                        {diffVal.toFixed(1)}%
                      </span>
                      <div className="text-[10px] text-slate-400 mt-0.5 font-medium">
                        {language === "es" ? "Media:" : "Avg:"} {leagueAvg.toFixed(1)}%
                      </div>
                    </div>
                  </div>

                  {/* Visual Progress Comparison Bar */}
                  <div className="w-full bg-slate-200 h-1.5 rounded-full overflow-hidden mt-2.5 relative">
                    <div
                      className="h-full rounded-full transition-all duration-500"
                      style={{
                        width: `${Math.min(fgPct, 100)}%`,
                        backgroundColor: tierColor,
                      }}
                    />
                    {/* League Average Marker */}
                    <div
                      className="absolute top-0 bottom-0 w-1 bg-slate-700 opacity-90 rounded-full"
                      style={{ left: `${Math.min(leagueAvg, 100)}%` }}
                      title={`League Avg: ${leagueAvg}%`}
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
