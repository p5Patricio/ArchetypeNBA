"use client";

import React, { useState, useMemo } from "react";
import Image from "next/image";
import {
  type ParallelPlayerItem,
  type LeagueAveragesMap,
  type ShotZonePreset,
} from "@/lib/api";
import {
  Search,
  X,
  SlidersHorizontal,
  Info,
  Layers,
  Flame,
  Award,
  BarChart3,
  Target,
  Sparkles,
} from "lucide-react";

interface ParallelShotZonesChartProps {
  players: ParallelPlayerItem[];
  leagueAverages: LeagueAveragesMap;
  presets: ShotZonePreset[];
  currentSeason: string;
  onSeasonChange?: (season: string) => void;
}

const PLAYER_COLORS = [
  { name: "Electric Blue", stroke: "#2563eb", bg: "bg-blue-500", text: "text-blue-700", ring: "ring-blue-400", border: "border-blue-200", fill: "rgba(37, 99, 235, 0.08)" },
  { name: "Emerald Green", stroke: "#059669", bg: "bg-emerald-500", text: "text-emerald-700", ring: "ring-emerald-400", border: "border-emerald-200", fill: "rgba(5, 150, 105, 0.08)" },
  { name: "Rose Crimson", stroke: "#e11d48", bg: "bg-rose-500", text: "text-rose-700", ring: "ring-rose-400", border: "border-rose-200", fill: "rgba(225, 29, 72, 0.08)" },
  { name: "Royal Violet", stroke: "#7c3aed", bg: "bg-purple-500", text: "text-purple-700", ring: "ring-purple-400", border: "border-purple-200", fill: "rgba(124, 58, 237, 0.08)" },
  { name: "Flame Orange", stroke: "#ea580c", bg: "bg-orange-500", text: "text-orange-700", ring: "ring-orange-400", border: "border-orange-200", fill: "rgba(234, 88, 12, 0.08)" },
  { name: "Amber Gold", stroke: "#d97706", bg: "bg-amber-500", text: "text-amber-700", ring: "ring-amber-400", border: "border-amber-200", fill: "rgba(217, 119, 6, 0.08)" },
  { name: "Cyber Teal", stroke: "#0891b2", bg: "bg-cyan-500", text: "text-cyan-700", ring: "ring-cyan-400", border: "border-cyan-200", fill: "rgba(8, 145, 178, 0.08)" },
  { name: "Indigo Slate", stroke: "#4f46e5", bg: "bg-indigo-500", text: "text-indigo-700", ring: "ring-indigo-400", border: "border-indigo-200", fill: "rgba(79, 70, 229, 0.08)" },
];

const ZONE_KEYS = [
  { key: "paint", label: "Pintura", sub: "Restricted Area & Paint" },
  { key: "mid", label: "Media", sub: "Mid-Range (10-22 ft)" },
  { key: "ft", label: "Tiro Libre", sub: "Línea de Personal" },
  { key: "three", label: "Triple", sub: "Tiro Exterior 3PT" },
] as const;

export function ParallelShotZonesChart({
  players = [],
  leagueAverages,
  presets = [],
  currentSeason = "2023-24",
  onSeasonChange,
}: ParallelShotZonesChartProps) {
  // Mode: "score" (Impact Score = Made * % like video) or "pct" (Pure %)
  const [metricMode, setMetricMode] = useState<"score" | "pct">("score");
  const [showCohort, setShowCohort] = useState<boolean>(true);
  const [showAverageLine, setShowAverageLine] = useState<boolean>(true);
  const [hoveredPlayerId, setHoveredPlayerId] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [isSearchOpen, setIsSearchOpen] = useState<boolean>(false);

  // Default selected: Curry (201939) & Giannis (203507)
  const [selectedPlayerIds, setSelectedPlayerIds] = useState<number[]>(() => {
    const defaultIds = [201939, 203507];
    const present = defaultIds.filter((id) => players.some((p) => p.id === id));
    if (present.length > 0) return present;
    return players.slice(0, 2).map((p) => p.id);
  });

  // SVG dimensions
  const svgWidth = 920;
  const svgHeight = 540;
  const margin = { top: 60, right: 65, bottom: 45, left: 65 };
  const innerWidth = svgWidth - margin.left - margin.right;
  const innerHeight = svgHeight - margin.top - margin.bottom;

  // X coordinate for each zone axis
  const axisXPositions = useMemo(() => {
    return [0, 1, 2, 3].map((i) => margin.left + (innerWidth / 3) * i);
  }, [innerWidth, margin.left]);

  // Selected player objects with color assigned
  const selectedPlayersWithColor = useMemo(() => {
    return selectedPlayerIds
      .map((id, index) => {
        const player = players.find((p) => p.id === id);
        if (!player) return null;
        const color = PLAYER_COLORS[index % PLAYER_COLORS.length];
        return { ...player, color };
      })
      .filter((p): p is ParallelPlayerItem & { color: (typeof PLAYER_COLORS)[0] } => p !== null);
  }, [selectedPlayerIds, players]);

  // Search filtered players
  const filteredSearchList = useMemo(() => {
    if (!searchQuery.trim()) return [];
    const q = searchQuery.toLowerCase().trim();
    return players
      .filter(
        (p) =>
          !selectedPlayerIds.includes(p.id) &&
          (p.name.toLowerCase().includes(q) || p.team.toLowerCase().includes(q))
      )
      .slice(0, 10);
  }, [searchQuery, players, selectedPlayerIds]);

  // Function to get Y coordinate
  const getYForZone = (player: ParallelPlayerItem, zoneKey: (typeof ZONE_KEYS)[number]["key"]) => {
    const zone = player.zones[zoneKey];
    const pctile = metricMode === "score" ? zone.pctile_score : zone.pctile_pct;
    const clamped = Math.max(0, Math.min(100, pctile));
    return margin.top + innerHeight * (1 - clamped / 100);
  };

  // Generate smooth cubic Bézier curve
  const generateSmoothPath = (player: ParallelPlayerItem) => {
    const points = [
      { x: axisXPositions[0], y: getYForZone(player, "paint") },
      { x: axisXPositions[1], y: getYForZone(player, "mid") },
      { x: axisXPositions[2], y: getYForZone(player, "ft") },
      { x: axisXPositions[3], y: getYForZone(player, "three") },
    ];

    let path = `M ${points[0].x} ${points[0].y}`;
    for (let i = 0; i < points.length - 1; i++) {
      const p0 = points[i];
      const p1 = points[i + 1];
      const dx = p1.x - p0.x;
      const cp1x = p0.x + dx * 0.45;
      const cp1y = p0.y;
      const cp2x = p1.x - dx * 0.45;
      const cp2y = p1.y;
      path += ` C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${p1.x} ${p1.y}`;
    }
    return path;
  };

  // Precompute cohort background paths
  const cohortPaths = useMemo(() => {
    if (!showCohort) return [];
    return players.map((player) => ({
      id: player.id,
      name: player.name,
      d: generateSmoothPath(player),
    }));
  }, [players, showCohort, metricMode, axisXPositions]);

  // Add/remove player
  const addPlayer = (id: number) => {
    if (!selectedPlayerIds.includes(id)) {
      if (selectedPlayerIds.length >= 8) {
        setSelectedPlayerIds((prev) => [...prev.slice(1), id]);
      } else {
        setSelectedPlayerIds((prev) => [...prev, id]);
      }
    }
    setSearchQuery("");
    setIsSearchOpen(false);
  };

  const removePlayer = (id: number) => {
    setSelectedPlayerIds((prev) => prev.filter((pId) => pId !== id));
  };

  const applyPreset = (preset: ShotZonePreset) => {
    const valid = preset.player_ids.filter((id) => players.some((p) => p.id === id));
    if (valid.length > 0) {
      setSelectedPlayerIds(valid);
    }
  };

  const leagueAvgY = margin.top + innerHeight * 0.5;

  return (
    <div className="w-full space-y-6">
      {/* 1. Clean Top Controls Card */}
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-orange-500 text-white shadow-md shadow-orange-500/20 shrink-0">
            <Target className="h-5 w-5" />
          </div>
          <div>
            <h2 className="text-base sm:text-lg font-black tracking-tight text-slate-900 flex items-center gap-2">
              Coordenadas Paralelas de Tiro
              <span className="rounded-md border border-orange-200 bg-orange-50 px-2 py-0.5 text-[11px] font-extrabold text-orange-800">
                {players.length} Jugadores
              </span>
            </h2>
            <p className="text-xs font-medium text-slate-500 mt-0.5">
              Analiza perfiles de efectividad y volumen continuo sobre los 300 jugadores con más minutos
            </p>
          </div>
        </div>

        {/* Toggles & Options */}
        <div className="flex flex-wrap items-center gap-2.5">
          {/* Season Dropdown */}
          {onSeasonChange && (
            <div className="flex items-center gap-1.5 rounded-xl border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs">
              <span className="font-semibold text-slate-500">Temporada:</span>
              <select
                value={currentSeason}
                onChange={(e) => onSeasonChange(e.target.value)}
                className="bg-transparent font-bold text-slate-900 outline-none cursor-pointer"
              >
                <option value="2023-24">2023-24</option>
                <option value="2024-25">2024-25</option>
              </select>
            </div>
          )}

          {/* Metric Switch */}
          <div className="flex items-center rounded-xl border border-slate-200 bg-slate-50 p-0.5 text-xs font-bold">
            <button
              onClick={() => setMetricMode("score")}
              className={`rounded-lg px-3 py-1.5 transition-all ${
                metricMode === "score"
                  ? "bg-white text-orange-700 shadow-2xs font-extrabold"
                  : "text-slate-600 hover:text-slate-900"
              }`}
              title="Volumen x Acierto: premia producción real y eficacia (Curry #1 en 3PT, Giannis #1 en Pintura)"
            >
              Impacto Anotador
            </button>
            <button
              onClick={() => setMetricMode("pct")}
              className={`rounded-lg px-3 py-1.5 transition-all ${
                metricMode === "pct"
                  ? "bg-white text-orange-700 shadow-2xs font-extrabold"
                  : "text-slate-600 hover:text-slate-900"
              }`}
              title="Porcentaje Puro (% de acierto por zona)"
            >
              % Acierto Puro
            </button>
          </div>

          {/* 300 Players Toggle */}
          <button
            onClick={() => setShowCohort(!showCohort)}
            className={`rounded-xl border px-3 py-1.5 text-xs font-bold flex items-center gap-1.5 transition-all ${
              showCohort
                ? "border-slate-300 bg-slate-100 text-slate-900 shadow-2xs"
                : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
            }`}
          >
            <Layers className="h-3.5 w-3.5" />
            300 Jugadores
          </button>

          {/* League Avg Line Toggle */}
          <button
            onClick={() => setShowAverageLine(!showAverageLine)}
            className={`rounded-xl border px-3 py-1.5 text-xs font-bold flex items-center gap-1.5 transition-all ${
              showAverageLine
                ? "border-slate-300 bg-slate-100 text-slate-900 shadow-2xs"
                : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
            }`}
          >
            <SlidersHorizontal className="h-3.5 w-3.5" />
            Media de Liga
          </button>
        </div>
      </div>

      {/* 2. Presets Ribbon */}
      {presets.length > 0 && (
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-xs space-y-2.5">
          <div className="flex items-center gap-1.5 text-xs font-mono font-bold uppercase tracking-wider text-slate-500">
            <Flame className="h-3.5 w-3.5 text-orange-500" />
            Duelos Tácticos & Comparaciones Destacadas:
          </div>
          <div className="flex flex-wrap gap-2">
            {presets.map((preset) => {
              const isActive =
                preset.player_ids.length === selectedPlayerIds.length &&
                preset.player_ids.every((id) => selectedPlayerIds.includes(id));

              return (
                <button
                  key={preset.id}
                  onClick={() => applyPreset(preset)}
                  className={`rounded-xl px-3 py-1.5 text-xs font-bold transition-all border ${
                    isActive
                      ? "bg-orange-500 text-white border-orange-500 shadow-xs font-extrabold"
                      : "border-slate-200 bg-white hover:border-orange-300 hover:bg-orange-50/40 text-slate-700 shadow-2xs"
                  }`}
                  title={preset.subtitle}
                >
                  {preset.title}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* 3. Selected Chips & Live Search Bar */}
      <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-xs flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        {/* Selected Players Chips */}
        <div className="flex flex-wrap items-center gap-2 flex-1">
          <span className="text-xs font-bold text-slate-400 mr-1">Comparando:</span>
          {selectedPlayersWithColor.map((player) => (
            <div
              key={player.id}
              className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold border transition-all ${player.color.border} ${player.color.text}`}
              style={{ backgroundColor: player.color.fill }}
              onMouseEnter={() => setHoveredPlayerId(player.id)}
              onMouseLeave={() => setHoveredPlayerId(null)}
            >
              <div
                className="w-2.5 h-2.5 rounded-full"
                style={{ backgroundColor: player.color.stroke }}
              />
              <span className="text-slate-900 font-black">{player.name}</span>
              <span className="text-[10px] font-bold text-slate-500">({player.team})</span>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  removePlayer(player.id);
                }}
                className="ml-1 rounded-full p-0.5 hover:bg-black/10 text-slate-400 hover:text-rose-600 transition"
                aria-label={`Eliminar ${player.name}`}
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}

          {selectedPlayersWithColor.length === 0 && (
            <span className="text-xs text-slate-400 italic">
              Escribe el nombre de un jugador o selecciona un duelo arriba para visualizar las curvas
            </span>
          )}
        </div>

        {/* Live Search Autocomplete */}
        <div className="relative w-full sm:w-72">
          <div className="relative flex items-center rounded-xl border border-slate-200 bg-slate-50/80 px-3 py-1.5 focus-within:border-orange-500 focus-within:bg-white focus-within:ring-2 focus-within:ring-orange-500/10 transition">
            <Search className="h-4 w-4 text-slate-400 shrink-0 mr-2" />
            <input
              type="text"
              placeholder="Buscar y añadir jugador..."
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setIsSearchOpen(true);
              }}
              onFocus={() => setIsSearchOpen(true)}
              className="w-full bg-transparent text-xs font-medium text-slate-900 placeholder:text-slate-400 outline-none"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery("")}
                className="text-slate-400 hover:text-slate-600"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>

          {/* Autocomplete Results Dropdown */}
          {isSearchOpen && filteredSearchList.length > 0 && (
            <div className="absolute left-0 right-0 top-full mt-1.5 max-h-60 overflow-y-auto rounded-2xl border border-slate-200 bg-white shadow-xl z-50 p-1 divide-y divide-slate-100">
              {filteredSearchList.map((p) => (
                <button
                  key={p.id}
                  onClick={() => addPlayer(p.id)}
                  className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-orange-50/60 rounded-xl transition group"
                >
                  <div className="flex items-center gap-2.5">
                    <div className="relative w-7 h-7 rounded-full overflow-hidden bg-slate-100 border border-slate-200 shrink-0">
                      <Image
                        src={p.headshot_url}
                        alt={p.name}
                        fill
                        sizes="28px"
                        className="object-cover"
                        onError={(e) => {
                          (e.target as HTMLElement).style.display = "none";
                        }}
                      />
                    </div>
                    <div>
                      <div className="text-xs font-bold text-slate-900 group-hover:text-orange-600">
                        {p.name}
                      </div>
                      <div className="text-[10px] text-slate-400 font-medium">
                        {p.team} • {p.pts.toFixed(1)} PTS • {p.gp} PJ
                      </div>
                    </div>
                  </div>
                  <span className="text-[10px] font-extrabold px-2 py-0.5 rounded-md bg-orange-50 text-orange-700 border border-orange-200">
                    + Añadir
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* 4. Main SVG Parallel Coordinates Canvas */}
      <div className="rounded-3xl border border-slate-200 bg-white p-6 sm:p-8 shadow-xs relative overflow-hidden space-y-4">
        {/* Chart Subtitle Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-100 pb-3">
          <div>
            <h3 className="text-sm font-black uppercase tracking-wider text-slate-900">
              300 Jugadores • Efectividad Anotando en 4 Zonas Clave
            </h3>
            <p className="text-xs font-medium text-slate-500">
              Curvas de spline continuo conectando Pintura, Media Distancia, Tiro Libre y Triple
            </p>
          </div>
          <div className="flex items-center gap-3 text-xs font-bold text-slate-400">
            <span className="flex items-center gap-1">
              <span className="h-2 w-2 rounded-full bg-orange-500" /> Tope: #1 de la NBA
            </span>
            <span className="flex items-center gap-1">
              <span className="h-2 w-2 rounded-full bg-slate-400" /> Centro: Media Liga
            </span>
          </div>
        </div>

        {/* SVG Viewport */}
        <div className="w-full overflow-x-auto">
          <svg
            viewBox={`0 0 ${svgWidth} ${svgHeight}`}
            className="w-full h-auto min-w-[720px] select-none"
          >
            <defs>
              <linearGradient id="lightAxisGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                <stop offset="0%" stopColor="#f97316" stopOpacity="0.5" />
                <stop offset="50%" stopColor="#cbd5e1" stopOpacity="0.6" />
                <stop offset="100%" stopColor="#94a3b8" stopOpacity="0.4" />
              </linearGradient>

              {selectedPlayersWithColor.map((p) => (
                <filter key={`glow-${p.id}`} id={`glow-${p.id}`} x="-20%" y="-20%" width="140%" height="140%">
                  <feDropShadow dx="0" dy="1" stdDeviation="3" floodColor={p.color.stroke} floodOpacity="0.3" />
                </filter>
              ))}
            </defs>

            {/* Vertical Guide Columns */}
            {ZONE_KEYS.map((z, idx) => {
              const x = axisXPositions[idx];
              return (
                <g key={`axis-col-${z.key}`}>
                  {/* Vertical Axis Line */}
                  <line
                    x1={x}
                    y1={margin.top}
                    x2={x}
                    y2={margin.top + innerHeight}
                    stroke="url(#lightAxisGrad)"
                    strokeWidth="1.5"
                    strokeDasharray="4 4"
                  />

                  {/* Top Axis Pill Tag */}
                  <g transform={`translate(${x}, ${margin.top - 20})`}>
                    <rect
                      x="-55"
                      y="-16"
                      width="110"
                      height="26"
                      rx="13"
                      fill="#f8fafc"
                      stroke="#cbd5e1"
                      strokeWidth="1"
                    />
                    <text
                      textAnchor="middle"
                      y="1"
                      className="text-xs font-black fill-slate-900 tracking-wide"
                    >
                      {z.label}
                    </text>
                  </g>

                  {/* Top Rank Badge #1 */}
                  <text
                    x={x}
                    y={margin.top - 4}
                    textAnchor="middle"
                    className="text-[10px] font-black fill-orange-600 tracking-wider"
                  >
                    #1
                  </text>

                  {/* Bottom Rank Badge #300 */}
                  <text
                    x={x}
                    y={margin.top + innerHeight + 16}
                    textAnchor="middle"
                    className="text-[10px] font-bold fill-slate-400"
                  >
                    #300
                  </text>
                </g>
              );
            })}

            {/* League Average Dashed Horizontal Line */}
            {showAverageLine && (
              <g>
                <line
                  x1={margin.left}
                  y1={leagueAvgY}
                  x2={margin.left + innerWidth}
                  y2={leagueAvgY}
                  stroke="#94a3b8"
                  strokeWidth="1.5"
                  strokeDasharray="6 4"
                  strokeOpacity="0.75"
                />
                <rect
                  x={margin.left + innerWidth / 2 - 58}
                  y={leagueAvgY - 10}
                  width="116"
                  height="20"
                  rx="10"
                  fill="#f1f5f9"
                  stroke="#cbd5e1"
                  strokeWidth="1"
                />
                <text
                  x={margin.left + innerWidth / 2}
                  y={leagueAvgY + 4}
                  textAnchor="middle"
                  className="text-[10px] font-black fill-slate-700 uppercase tracking-wider"
                >
                  Media de la liga
                </text>
              </g>
            )}

            {/* 300 Players Cohort Curves in background */}
            {showCohort && (
              <g className="cohort-paths">
                {cohortPaths.map((item) => {
                  const isHovered = hoveredPlayerId === item.id;
                  if (selectedPlayerIds.includes(item.id)) return null;

                  return (
                    <path
                      key={`cohort-${item.id}`}
                      d={item.d}
                      fill="none"
                      stroke={isHovered ? "#ea580c" : "#cbd5e1"}
                      strokeWidth={isHovered ? "2.5" : "1"}
                      strokeOpacity={isHovered ? "0.9" : "0.35"}
                      className="transition-all duration-150 cursor-pointer"
                      onMouseEnter={() => setHoveredPlayerId(item.id)}
                      onMouseLeave={() => setHoveredPlayerId(null)}
                    >
                      <title>{item.name}</title>
                    </path>
                  );
                })}
              </g>
            )}

            {/* Selected Players Splines (Vibrant, Bold & Highlighted) */}
            {selectedPlayersWithColor.map((player) => {
              const pathD = generateSmoothPath(player);
              const isHovered = hoveredPlayerId === player.id;

              return (
                <g key={`highlight-${player.id}`}>
                  {/* Subtle Aura */}
                  <path
                    d={pathD}
                    fill="none"
                    stroke={player.color.stroke}
                    strokeWidth={isHovered ? "8" : "6"}
                    strokeOpacity="0.2"
                    strokeLinecap="round"
                  />

                  {/* Main Stroke */}
                  <path
                    d={pathD}
                    fill="none"
                    stroke={player.color.stroke}
                    strokeWidth={isHovered ? "4.5" : "3.5"}
                    strokeLinecap="round"
                    filter={`url(#glow-${player.id})`}
                    className="cursor-pointer transition-all duration-200"
                    onMouseEnter={() => setHoveredPlayerId(player.id)}
                    onMouseLeave={() => setHoveredPlayerId(null)}
                  />

                  {/* Nodes on Axes */}
                  {ZONE_KEYS.map((z, idx) => {
                    const x = axisXPositions[idx];
                    const y = getYForZone(player, z.key);
                    const zoneData = player.zones[z.key];
                    const rank = metricMode === "score" ? zoneData.rank_score : zoneData.rank_pct;
                    const isTop1 = rank === 1;

                    return (
                      <g key={`node-${player.id}-${z.key}`}>
                        <circle
                          cx={x}
                          cy={y}
                          r={isHovered ? "6" : "4.5"}
                          fill="#ffffff"
                          stroke={player.color.stroke}
                          strokeWidth="2.5"
                          className="transition-all duration-200"
                        />

                        {/* Top 1 or Hovered Rank Pill */}
                        {(isTop1 || isHovered) && (
                          <g transform={`translate(${x}, ${y - 14})`}>
                            <rect
                              x="-22"
                              y="-13"
                              width="44"
                              height="17"
                              rx="5"
                              fill={player.color.stroke}
                            />
                            <text
                              textAnchor="middle"
                              y="-1"
                              fill="#ffffff"
                              className="text-[9px] font-black"
                            >
                              {isTop1 ? "#1" : `#${rank}`}
                            </text>
                          </g>
                        )}
                      </g>
                    );
                  })}
                </g>
              );
            })}
          </svg>
        </div>

        {/* Caption */}
        <div className="flex flex-wrap items-center justify-between text-[11px] font-medium text-slate-500 pt-3 border-t border-slate-100">
          <div className="flex items-center gap-1.5">
            <Info className="h-3.5 w-3.5 text-slate-400" />
            <span>
              Eje vertical: <strong>Percentil 100 (#1)</strong> en el tope hasta <strong>Percentil 0 (#300)</strong> en la base.
            </span>
          </div>
          <div>
            Datos calculados sobre splits de tracking oficiales de tiro NBA.
          </div>
        </div>
      </div>

      {/* 5. Clean Player Cards Showcase */}
      <div className="space-y-3">
        <div className="flex items-center justify-between px-1">
          <h3 className="text-sm font-black tracking-tight text-slate-900 flex items-center gap-2">
            <Award className="h-4 w-4 text-orange-600" />
            Detalle de Anotación por Jugador ({selectedPlayersWithColor.length})
          </h3>
          <span className="text-xs font-semibold text-slate-500">
            Métricas por zona y ranking en la temporada {currentSeason}
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {selectedPlayersWithColor.map((player) => {
            const isHovered = hoveredPlayerId === player.id;

            return (
              <div
                key={`card-${player.id}`}
                className={`rounded-2xl border bg-white p-5 shadow-xs transition-all duration-300 ${
                  isHovered
                    ? "border-orange-400 ring-2 ring-orange-400/20 shadow-md"
                    : "border-slate-200 hover:border-slate-300"
                }`}
                onMouseEnter={() => setHoveredPlayerId(player.id)}
                onMouseLeave={() => setHoveredPlayerId(null)}
              >
                {/* Header */}
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <div
                      className="relative w-12 h-12 rounded-2xl overflow-hidden bg-slate-50 border-2 shrink-0"
                      style={{ borderColor: player.color.stroke }}
                    >
                      <Image
                        src={player.headshot_url}
                        alt={player.name}
                        fill
                        sizes="48px"
                        className="object-cover"
                        onError={(e) => {
                          (e.target as HTMLElement).style.display = "none";
                        }}
                      />
                    </div>
                    <div>
                      <div className="flex items-center gap-1.5">
                        <span
                          className="w-2.5 h-2.5 rounded-full inline-block"
                          style={{ backgroundColor: player.color.stroke }}
                        />
                        <h4 className="text-sm font-black text-slate-900 leading-tight">
                          {player.name}
                        </h4>
                      </div>
                      <p className="text-xs text-slate-500 font-semibold mt-0.5">
                        {player.team} • {player.pts.toFixed(1)} PTS • {player.gp} Juegos
                      </p>
                    </div>
                  </div>

                  <button
                    onClick={() => removePlayer(player.id)}
                    className="p-1 rounded-xl hover:bg-slate-100 text-slate-400 hover:text-rose-600 transition"
                    title="Remover de la gráfica"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>

                {/* 4 Mini Zone Boxes */}
                <div className="grid grid-cols-4 gap-2 mt-4 pt-3 border-t border-slate-100">
                  {ZONE_KEYS.map((z) => {
                    const zd = player.zones[z.key];
                    const rank = metricMode === "score" ? zd.rank_score : zd.rank_pct;
                    const isTop1 = rank === 1;
                    const isTop10 = rank <= 10;
                    const isTop30 = rank <= 30;

                    return (
                      <div
                        key={`mini-${player.id}-${z.key}`}
                        className="rounded-xl bg-slate-50 border border-slate-100 p-2 text-center"
                      >
                        <div className="text-[10px] font-bold text-slate-400 truncate">
                          {z.label}
                        </div>
                        <div className="text-xs font-black text-slate-900 mt-0.5">
                          {zd.pct}%
                        </div>
                        <div
                          className={`text-[9px] font-extrabold px-1.5 py-0.5 rounded-md mt-1 inline-block ${
                            isTop1
                              ? "bg-amber-100 text-amber-800 border border-amber-200"
                              : isTop10
                              ? "bg-orange-50 text-orange-700 border border-orange-200"
                              : isTop30
                              ? "bg-blue-50 text-blue-700 border border-blue-200"
                              : "bg-slate-100 text-slate-600 border border-slate-200"
                          }`}
                        >
                          #{rank}
                        </div>
                        <div className="text-[9px] font-semibold text-slate-400 mt-0.5">
                          {zd.fgm.toFixed(0)}/{zd.fga.toFixed(0)}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
