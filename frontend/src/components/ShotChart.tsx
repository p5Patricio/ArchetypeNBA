"use client";

import React, { useState } from "react";
import { type PlayerShot } from "@/lib/api";
import { usePreferences } from "@/context/PreferencesContext";
import { Target, CheckCircle2, XCircle, Crosshair } from "lucide-react";

interface ShotChartProps {
  shots: PlayerShot[];
  playerName?: string;
  seasonLabel?: string;
  className?: string;
}

export function ShotChart({
  shots = [],
  playerName = "Jugador",
  seasonLabel = "2023-24",
  className = "",
}: ShotChartProps) {
  const { language } = usePreferences();
  const [filter, setFilter] = useState<"all" | "makes" | "misses">("all");
  const [hoveredShot, setHoveredShot] = useState<PlayerShot | null>(null);

  const filteredShots = shots.filter((s) => {
    if (filter === "makes") return s.made;
    if (filter === "misses") return !s.made;
    return true;
  });

  const totalAttempts = shots.length;
  const totalMakes = shots.filter((s) => s.made).length;
  const fgPct = totalAttempts > 0 ? ((totalMakes / totalAttempts) * 100).toFixed(1) : "0.0";

  const threeShots = shots.filter((s) => (s.shot_distance || 0) >= 22.0);
  const threeMakes = threeShots.filter((s) => s.made).length;
  const threePct = threeShots.length > 0 ? ((threeMakes / threeShots.length) * 100).toFixed(1) : "0.0";

  const rimShots = shots.filter((s) => (s.shot_distance || 0) <= 5.0);
  const rimMakes = rimShots.filter((s) => s.made).length;
  const rimPct = rimShots.length > 0 ? ((rimMakes / rimShots.length) * 100).toFixed(1) : "0.0";

  // Coordinate transformation:
  // NBA coords: x in [-250, 250], y in [-50, 420]
  // SVG viewBox: width=500, height=470
  // Basket center at (250, 52.5) in SVG
  const mapX = (x: number) => 250 + x;
  const mapY = (y: number) => 52.5 + y;

  return (
    <div className={`rounded-3xl border border-slate-200 bg-white p-6 shadow-xs space-y-5 ${className}`}>
      
      {/* Header with Metrics */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-100 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="p-1.5 rounded-xl bg-orange-50 border border-orange-200 text-orange-600">
              <Target className="h-4 w-4" />
            </span>
            <h3 className="text-base font-extrabold tracking-tight text-slate-900">
              {language === "es" ? "Mapa de Tiro Espacial (Shot Chart)" : "Spatial Shot Chart (Shot Quality)"}
            </h3>
          </div>
          <p className="text-xs font-medium text-slate-500 mt-1">
            {language === "es"
              ? `Distribución de ${totalAttempts} tiros de campo en la temporada ${seasonLabel}`
              : `Distribution of ${totalAttempts} field goal attempts in season ${seasonLabel}`}
          </p>
        </div>

        {/* Filter Switcher */}
        <div className="flex items-center rounded-xl border border-slate-200 bg-slate-50 p-1 self-start sm:self-auto text-xs font-bold">
          <button
            onClick={() => setFilter("all")}
            className={`rounded-lg px-3 py-1 transition ${
              filter === "all"
                ? "bg-white text-slate-900 shadow-xs border border-slate-200"
                : "text-slate-500 hover:text-slate-900"
            }`}
          >
            {language === "es" ? "Todos" : "All"} ({shots.length})
          </button>
          <button
            onClick={() => setFilter("makes")}
            className={`flex items-center gap-1 rounded-lg px-3 py-1 transition ${
              filter === "makes"
                ? "bg-emerald-500 text-white shadow-xs"
                : "text-slate-500 hover:text-slate-900"
            }`}
          >
            <CheckCircle2 className="h-3 w-3" />
            {language === "es" ? "Anotados" : "Makes"} ({totalMakes})
          </button>
          <button
            onClick={() => setFilter("misses")}
            className={`flex items-center gap-1 rounded-lg px-3 py-1 transition ${
              filter === "misses"
                ? "bg-slate-800 text-white shadow-xs"
                : "text-slate-500 hover:text-slate-900"
            }`}
          >
            <XCircle className="h-3 w-3" />
            {language === "es" ? "Fallados" : "Misses"} ({totalAttempts - totalMakes})
          </button>
        </div>
      </div>

      {/* Summary KPI Badges */}
      <div className="grid grid-cols-3 gap-3 text-center text-xs">
        <div className="rounded-2xl border border-slate-100 bg-slate-50/70 p-3">
          <span className="text-[10px] uppercase font-bold text-slate-400">
            {language === "es" ? "Efectividad Global" : "Overall FG%"}
          </span>
          <div className="font-mono text-xl font-black text-slate-900 mt-0.5">{fgPct}%</div>
          <span className="text-[11px] font-semibold text-slate-500">{totalMakes}/{totalAttempts} FGM</span>
        </div>

        <div className="rounded-2xl border border-slate-100 bg-slate-50/70 p-3">
          <span className="text-[10px] uppercase font-bold text-slate-400">
            {language === "es" ? "Tiro de 3 Puntos" : "3-Point FG%"}
          </span>
          <div className="font-mono text-xl font-black text-orange-600 mt-0.5">{threePct}%</div>
          <span className="text-[11px] font-semibold text-slate-500">{threeMakes}/{threeShots.length} 3PM</span>
        </div>

        <div className="rounded-2xl border border-slate-100 bg-slate-50/70 p-3">
          <span className="text-[10px] uppercase font-bold text-slate-400">
            {language === "es" ? "Efectividad en el Aro" : "Rim Finish FG%"}
          </span>
          <div className="font-mono text-xl font-black text-sky-700 mt-0.5">{rimPct}%</div>
          <span className="text-[11px] font-semibold text-slate-500">{rimMakes}/{rimShots.length} RIM</span>
        </div>
      </div>

      {/* NBA Court SVG Representation with Stable Invisible Hitboxes */}
      <div className="relative mx-auto max-w-lg overflow-hidden rounded-2xl border border-slate-200 bg-[#FDFEFE] p-3 shadow-inner">
        <svg
          viewBox="0 0 500 470"
          className="w-full h-auto select-none"
        >
          {/* Court Outline & Background */}
          <rect x="0" y="0" width="500" height="470" fill="#F8FAFC" stroke="#CBD5E1" strokeWidth="2" />

          {/* Half-Court Outer Border */}
          <rect x="10" y="10" width="480" height="450" fill="none" stroke="#94A3B8" strokeWidth="2" />

          {/* Center Court Circle at top */}
          <path d="M 190 460 A 60 60 0 0 1 310 460" fill="none" stroke="#94A3B8" strokeWidth="2" />

          {/* The Paint / Key (16ft wide = 160 units) */}
          <rect x="170" y="10" width="160" height="190" fill="#F1F5F9" stroke="#94A3B8" strokeWidth="2" />

          {/* Free Throw Circle */}
          <circle cx="250" cy="200" r="60" fill="none" stroke="#94A3B8" strokeWidth="2" strokeDasharray="6,6" />
          <path d="M 190 200 A 60 60 0 0 0 310 200" fill="none" stroke="#94A3B8" strokeWidth="2" />

          {/* Restricted Area Arc (4ft = 40 units) */}
          <path d="M 210 52.5 A 40 40 0 0 0 290 52.5" fill="none" stroke="#94A3B8" strokeWidth="1.5" />

          {/* Backboard & Hoop */}
          <line x1="220" y1="40" x2="280" y2="40" stroke="#0F172A" strokeWidth="3" />
          <circle cx="250" cy="52.5" r="9" fill="none" stroke="#EA580C" strokeWidth="2.5" />
          <line x1="250" y1="40" x2="250" y2="43.5" stroke="#EA580C" strokeWidth="2" />

          {/* 3-Point Line (Corners: 22ft = 220 units; Arc: 23.75ft = 237.5 units) */}
          <line x1="30" y1="10" x2="30" y2="150" stroke="#94A3B8" strokeWidth="2" />
          <line x1="470" y1="10" x2="470" y2="150" stroke="#94A3B8" strokeWidth="2" />
          <path
            d="M 30 150 A 237.5 237.5 0 0 0 470 150"
            fill="none"
            stroke="#94A3B8"
            strokeWidth="2"
          />

          {/* Render Shot Points with Rock-Solid Stable Hitbox Group */}
          {filteredShots.map((shot, idx) => {
            const cx = mapX(shot.x);
            const cy = mapY(shot.y);
            const isHovered = hoveredShot === shot;

            return (
              <g
                key={idx}
                className="cursor-pointer"
                onMouseEnter={() => setHoveredShot(shot)}
                onMouseLeave={() => {
                  if (hoveredShot === shot) {
                    setHoveredShot(null);
                  }
                }}
              >
                {/* Large Invisible Hitbox (8px radius) prevents flicker completely */}
                <circle
                  cx={cx}
                  cy={cy}
                  r={8}
                  fill="transparent"
                  pointerEvents="all"
                />

                {/* Visible Shot Marker */}
                {shot.made ? (
                  <circle
                    cx={cx}
                    cy={cy}
                    r={isHovered ? 5.5 : 3.5}
                    fill={isHovered ? "#059669" : "#10B981"}
                    stroke="#FFFFFF"
                    strokeWidth={isHovered ? 2 : 1.2}
                    pointerEvents="none"
                  />
                ) : (
                  <g pointerEvents="none">
                    <line
                      x1={cx - (isHovered ? 4 : 3)}
                      y1={cy - (isHovered ? 4 : 3)}
                      x2={cx + (isHovered ? 4 : 3)}
                      y2={cy + (isHovered ? 4 : 3)}
                      stroke={isHovered ? "#DC2626" : "#EF4444"}
                      strokeWidth={isHovered ? 2.5 : 1.6}
                    />
                    <line
                      x1={cx + (isHovered ? 4 : 3)}
                      y1={cy - (isHovered ? 4 : 3)}
                      x2={cx - (isHovered ? 4 : 3)}
                      y2={cy + (isHovered ? 4 : 3)}
                      stroke={isHovered ? "#DC2626" : "#EF4444"}
                      strokeWidth={isHovered ? 2.5 : 1.6}
                    />
                  </g>
                )}
              </g>
            );
          })}
        </svg>

        {/* Persistent Floating Tooltip with pointer-events-none (NEVER steals mouse focus or flickers) */}
        <div
          className={`pointer-events-none absolute bottom-4 left-4 right-4 rounded-xl border border-slate-200/50 bg-slate-900/90 backdrop-blur-md px-3.5 py-2 text-white shadow-xl text-xs flex items-center justify-between transition-all duration-200 ${
            hoveredShot ? "opacity-100 translate-y-0" : "opacity-0 translate-y-2"
          }`}
        >
          <div className="flex items-center gap-2">
            <span
              className={`h-2.5 w-2.5 rounded-full ${
                hoveredShot?.made ? "bg-emerald-400" : "bg-red-400"
              }`}
            />
            <span className="font-bold">
              {hoveredShot?.made
                ? language === "es"
                  ? "Anotado"
                  : "Made"
                : language === "es"
                ? "Fallado"
                : "Missed"}
            </span>
            <span className="text-slate-400">•</span>
            <span className="text-slate-200 font-medium">
              {hoveredShot?.shot_zone_basic || hoveredShot?.action_type || "Tiro de campo"}
            </span>
          </div>
          <div className="flex items-center gap-1 font-mono font-bold text-orange-400">
            <Crosshair className="h-3.5 w-3.5 text-orange-400" />
            <span>{hoveredShot?.shot_distance ? `${hoveredShot.shot_distance} ft` : "—"}</span>
          </div>
        </div>
      </div>

      {/* Legend Footer */}
      <div className="flex items-center justify-center gap-6 text-xs font-semibold text-slate-600 border-t border-slate-100 pt-3">
        <div className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-full bg-emerald-500 border border-white shadow-xs" />
          <span>{language === "es" ? "Tiro Anotado (Made)" : "Field Goal Made"}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="font-bold text-red-500 font-mono text-sm">✕</span>
          <span>{language === "es" ? "Tiro Fallado (Missed)" : "Field Goal Missed"}</span>
        </div>
      </div>

    </div>
  );
}
