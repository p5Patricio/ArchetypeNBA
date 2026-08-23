"use client";

import React, { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { type GalaxyPlayerPoint } from "@/lib/api";
import { usePreferences } from "@/context/PreferencesContext";
import { PlayerAvatar } from "./PlayerAvatar";
import {
  Sparkles,
  Search,
  Compass,
  ArrowUpRight,
  ArrowUp,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  Shield,
  Zap,
  Target,
  Activity,
  Flame,
  UserCheck,
} from "lucide-react";

interface GalaxyMapProps {
  players: GalaxyPlayerPoint[];
  seasonLabel?: string;
  className?: string;
}

export function GalaxyMap({
  players = [],
  seasonLabel = "2023-24",
  className = "",
}: GalaxyMapProps) {
  const router = useRouter();
  const { language } = usePreferences();
  const [selectedCluster, setSelectedCluster] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [hoveredPlayer, setHoveredPlayer] = useState<GalaxyPlayerPoint | null>(null);
  const [pinnedPlayer, setPinnedPlayer] = useState<GalaxyPlayerPoint | null>(null);
  const [showGuide, setShowGuide] = useState<boolean>(true);

  // Deduplicate any potential duplicate players
  const uniquePlayers = useMemo(() => {
    const seen = new Set<number>();
    const list: GalaxyPlayerPoint[] = [];
    for (const p of players) {
      if (!seen.has(p.player_id)) {
        seen.add(p.player_id);
        list.push(p);
      }
    }
    return list;
  }, [players]);

  const filteredPlayers = useMemo(() => {
    return uniquePlayers.filter((p) => {
      if (selectedCluster !== null && p.cluster_id !== selectedCluster) {
        return false;
      }
      if (!searchQuery.trim()) return true;
      const q = searchQuery.toLowerCase();
      return (
        p.player_name.toLowerCase().includes(q) ||
        p.team_abbreviation.toLowerCase().includes(q) ||
        p.role_name_es.toLowerCase().includes(q) ||
        p.role_name_en.toLowerCase().includes(q)
      );
    });
  }, [uniquePlayers, selectedCluster, searchQuery]);

  // Default active player for the right-side inspector panel
  const activeInspectorPlayer = useMemo(() => {
    if (hoveredPlayer) return hoveredPlayer;
    if (pinnedPlayer) return pinnedPlayer;
    if (filteredPlayers.length > 0) {
      return [...filteredPlayers].sort((a, b) => b.ppg - a.ppg)[0];
    }
    return null;
  }, [hoveredPlayer, pinnedPlayer, filteredPlayers]);

  const clusterMeta = [
    { id: 0, name_es: "Interior Facilitador", name_en: "Unicorn Big", color: "#8B5CF6" },
    { id: 1, name_es: "POA Stopper", name_en: "POA Stopper", color: "#10B981" },
    { id: 2, name_es: "Rim Protector", name_en: "Rim Protector", color: "#0284C7" },
    { id: 3, name_es: "Alero Conector", name_en: "Connecting Wing", color: "#64748B" },
    { id: 4, name_es: "Motor Heliocéntrico", name_en: "Heliocentric Scorer", color: "#EA580C" },
    { id: 5, name_es: "3&D Sniper", name_en: "3&D Sniper", color: "#06B6D4" },
    { id: 6, name_es: "General de Piso", name_en: "Floor General", color: "#F59E0B" },
  ];

  // Map normalized coordinates [-90, 90] to SVG viewBox [0, 1000] x [0, 680]
  const mapSvgX = (x: number) => 500 + (x * 4.9);
  const mapSvgY = (y: number) => 340 - (y * 3.3);

  return (
    <div className={`rounded-3xl border border-slate-200 bg-white p-6 sm:p-8 shadow-xs space-y-6 ${className}`}>
      
      {/* Header with Title, Live Search & Guide Toggle */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-100 pb-5">
        <div>
          <div className="flex items-center gap-2">
            <span className="p-1.5 rounded-xl bg-purple-50 border border-purple-200 text-purple-600">
              <Sparkles className="h-4 w-4" />
            </span>
            <h2 className="text-xl font-extrabold tracking-tight text-slate-900">
              {language === "es" ? "Mapa Galaxia Táctica UMAP (2D Manifold)" : "Tactical Galaxy Map (2D UMAP Manifold)"}
            </h2>
          </div>
          <p className="text-xs font-medium text-slate-500 mt-1">
            {language === "es"
              ? `Proyección a gran escala de ${uniquePlayers.length} jugadores en la temporada ${seasonLabel}. Pasá el cursor o clickeá cualquier estrella para inspeccionar sus métricas.`
              : `Large-scale 2D manifold projection of ${uniquePlayers.length} NBA players in season ${seasonLabel}. Hover or click any star to inspect full analytics.`}
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Guide Toggle Button */}
          <button
            onClick={() => setShowGuide(!showGuide)}
            className={`flex items-center gap-1.5 rounded-xl border px-3.5 py-1.5 text-xs font-bold transition ${
              showGuide
                ? "border-purple-200 bg-purple-50 text-purple-700"
                : "border-slate-200 bg-slate-50 text-slate-600 hover:bg-slate-100"
            }`}
          >
            <Compass className="h-3.5 w-3.5" />
            {language === "es" ? "Guía de Ejes" : "Axis Guide"}
          </button>

          {/* Live Search Input */}
          <div className="relative flex items-center rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-1.5 w-full md:w-72 focus-within:border-purple-500 focus-within:bg-white transition">
            <Search className="h-3.5 w-3.5 text-slate-400 mr-2 shrink-0" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={language === "es" ? "Buscar estrella en la galaxia..." : "Search star in galaxy..."}
              className="w-full bg-transparent text-xs font-medium text-slate-900 placeholder:text-slate-400 outline-none"
            />
          </div>
        </div>
      </div>

      {/* Cluster Filter Buttons Bar */}
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => setSelectedCluster(null)}
          className={`rounded-xl px-3.5 py-1.5 text-xs font-bold transition ${
            selectedCluster === null
              ? "bg-slate-900 text-white shadow-xs"
              : "border border-slate-200 bg-slate-50 text-slate-600 hover:bg-slate-100"
          }`}
        >
          {language === "es" ? "Todos los Roles" : "All Roles"} ({uniquePlayers.length})
        </button>
        {clusterMeta.map((c) => {
          const isSelected = selectedCluster === c.id;
          return (
            <button
              key={c.id}
              onClick={() => setSelectedCluster(isSelected ? null : c.id)}
              className={`flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-bold transition border ${
                isSelected
                  ? "text-white shadow-xs"
                  : "bg-slate-50 text-slate-700 hover:bg-slate-100 border-slate-200"
              }`}
              style={{
                backgroundColor: isSelected ? c.color : undefined,
                borderColor: isSelected ? c.color : undefined,
              }}
            >
              <span
                className="h-2 w-2 rounded-full"
                style={{ backgroundColor: isSelected ? "#FFFFFF" : c.color }}
              />
              <span>{language === "es" ? c.name_es : c.name_en}</span>
            </button>
          );
        })}
      </div>

      {/* Split Master-Detail Grid: Left Expansive Canvas (8 cols) + Right Inspector Card (4 cols) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        
        {/* Left Side: Expansive Galaxy Map Canvas (8 cols) */}
        <div className="lg:col-span-8 xl:col-span-8 space-y-3">
          
          {/* Top Axis Label */}
          <div className="flex justify-center">
            <div className="inline-flex items-center gap-1.5 rounded-full border border-orange-200 bg-orange-50 px-4 py-1 text-xs font-bold text-orange-700 shadow-2xs">
              <ArrowUp className="h-3.5 w-3.5 text-orange-600" />
              <span>{language === "es" ? "ALTO USO & CREACIÓN HELIOCÉNTRICA" : "HIGH USAGE & HELIOCENTRIC SCORING"}</span>
            </div>
          </div>

          {/* Horizontal Canvas with Left/Right labels */}
          <div className="flex items-center gap-2.5">
            
            {/* Left Axis Label */}
            <div className="hidden sm:flex flex-col items-center justify-center rounded-2xl border border-blue-200 bg-blue-50/80 p-2.5 text-center shadow-2xs max-w-[76px] shrink-0">
              <ArrowLeft className="h-4 w-4 text-blue-600 mb-1" />
              <span className="text-[9px] font-black uppercase text-blue-900 leading-tight">
                {language === "es" ? "DOMINIO INTERIOR" : "INTERIOR RIM"}
              </span>
              <span className="text-[8px] font-semibold text-blue-700 mt-0.5">
                {language === "es" ? "Pivots & Aro" : "Bigs"}
              </span>
            </div>

            {/* SVG Galaxy Canvas (Grand 1000x680 ViewBox) */}
            <div className="relative flex-1 overflow-hidden rounded-2xl border border-slate-700 bg-[#0B1120] p-2 shadow-2xl min-h-[580px]">
              <svg
                viewBox="0 0 1000 680"
                className="w-full h-auto select-none"
              >
                <defs>
                  <radialGradient id="galaxyGlow" cx="50%" cy="50%" r="50%">
                    <stop offset="0%" stopColor="#1E293B" stopOpacity="0.85" />
                    <stop offset="100%" stopColor="#080D1A" stopOpacity="1" />
                  </radialGradient>
                </defs>

                <rect x="0" y="0" width="1000" height="680" fill="url(#galaxyGlow)" />

                {/* Quadrant Tint Overlays */}
                <rect x="500" y="0" width="500" height="340" fill="rgba(234, 88, 12, 0.025)" />
                <rect x="0" y="0" width="500" height="340" fill="rgba(139, 92, 246, 0.025)" />
                <rect x="0" y="340" width="500" height="340" fill="rgba(2, 132, 199, 0.025)" />
                <rect x="500" y="340" width="500" height="340" fill="rgba(6, 182, 212, 0.025)" />

                {/* Coordinate Axes Cross */}
                <line x1="500" y1="20" x2="500" y2="660" stroke="#334155" strokeWidth="1.2" strokeDasharray="5,5" />
                <line x1="20" y1="340" x2="980" y2="340" stroke="#334155" strokeWidth="1.2" strokeDasharray="5,5" />

                {/* Concentric distance rings */}
                <circle cx="500" cy="340" r="170" fill="none" stroke="#1E293B" strokeWidth="1.5" />
                <circle cx="500" cy="340" r="310" fill="none" stroke="#1E293B" strokeWidth="1.5" />

                {/* Render Player Stars with unique keys */}
                {filteredPlayers.map((player, idx) => {
                  const cx = mapSvgX(player.x);
                  const cy = mapSvgY(player.y);
                  const isHovered = hoveredPlayer?.player_id === player.player_id;
                  const isPinned = pinnedPlayer?.player_id === player.player_id;
                  const isSearched =
                    searchQuery.trim().length > 1 &&
                    player.player_name.toLowerCase().includes(searchQuery.toLowerCase());

                  return (
                    <g
                      key={`${player.player_id}-${idx}`}
                      className="cursor-pointer"
                      onClick={() => setPinnedPlayer(player)}
                      onDoubleClick={() => router.push(`/player/${encodeURIComponent(player.player_name)}`)}
                      onMouseEnter={() => setHoveredPlayer(player)}
                      onMouseLeave={() => {
                        if (hoveredPlayer?.player_id === player.player_id) {
                          setHoveredPlayer(null);
                        }
                      }}
                    >
                      {/* Invisible Hitbox (15px radius) prevents flicker */}
                      <circle cx={cx} cy={cy} r={15} fill="transparent" pointerEvents="all" />

                      {/* Clean Search Highlight Ring */}
                      {isSearched && (
                        <circle
                          cx={cx}
                          cy={cy}
                          r={11}
                          fill="none"
                          stroke="#F59E0B"
                          strokeWidth="2.5"
                          pointerEvents="none"
                        />
                      )}

                      {/* Outer Glow on Hover or Pin */}
                      {(isHovered || isPinned) && (
                        <circle
                          cx={cx}
                          cy={cy}
                          r={14}
                          fill={player.color}
                          opacity="0.5"
                          pointerEvents="none"
                        />
                      )}

                      {/* Star Dot */}
                      <circle
                        cx={cx}
                        cy={cy}
                        r={isHovered || isPinned ? 7 : isSearched ? 6 : 4.5}
                        fill={player.color}
                        stroke={isHovered || isPinned || isSearched ? "#FFFFFF" : "rgba(255,255,255,0.6)"}
                        strokeWidth={isHovered || isPinned || isSearched ? 2 : 1}
                        pointerEvents="none"
                        className="transition-all duration-150"
                      />
                    </g>
                  );
                })}
              </svg>
            </div>

            {/* Right Axis Label */}
            <div className="hidden sm:flex flex-col items-center justify-center rounded-2xl border border-cyan-200 bg-cyan-50/80 p-2.5 text-center shadow-2xs max-w-[76px] shrink-0">
              <ArrowRight className="h-4 w-4 text-cyan-600 mb-1" />
              <span className="text-[9px] font-black uppercase text-cyan-900 leading-tight">
                {language === "es" ? "TRIPLES & ESPACIO" : "3-POINT SPACE"}
              </span>
              <span className="text-[8px] font-semibold text-cyan-700 mt-0.5">
                {language === "es" ? "Perímetro" : "Shooters"}
              </span>
            </div>

          </div>

          {/* Bottom Axis Label */}
          <div className="flex justify-center">
            <div className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-100 px-4 py-1 text-xs font-bold text-slate-700 shadow-2xs">
              <ArrowDown className="h-3.5 w-3.5 text-slate-500" />
              <span>{language === "es" ? "ROLES COMPLEMENTARIOS & ESPECIALISTAS (3&D / Conectores)" : "COMPLEMENTARY & DEFENSIVE SPECIALISTS (3&D / Connectors)"}</span>
            </div>
          </div>

        </div>

        {/* Right Side: Dedicated Player Scouting Inspector Panel (4 cols) */}
        <div className="lg:col-span-4 xl:col-span-4 space-y-4">
          <div className="rounded-3xl border border-slate-200 bg-white p-6 sm:p-7 shadow-sm sticky top-24 space-y-6">
            
            <div className="flex items-center justify-between border-b border-slate-100 pb-3.5">
              <div className="flex items-center gap-1.5 text-xs font-extrabold uppercase tracking-wider text-slate-600">
                <UserCheck className="h-4 w-4 text-purple-600" />
                <span>{language === "es" ? "Inspector de Jugador" : "Player Inspector"}</span>
              </div>
              {activeInspectorPlayer && (
                <span
                  className="rounded-full px-3 py-0.5 font-mono text-[11px] font-bold text-white shadow-2xs"
                  style={{ backgroundColor: activeInspectorPlayer.color }}
                >
                  {language === "es" ? activeInspectorPlayer.role_name_es : activeInspectorPlayer.role_name_en}
                </span>
              )}
            </div>

            {activeInspectorPlayer ? (
              <div className="space-y-6">
                {/* Large Player Photo & Team Header */}
                <div className="flex items-center gap-4">
                  <PlayerAvatar
                    playerId={activeInspectorPlayer.player_id}
                    playerName={activeInspectorPlayer.player_name}
                    headshotUrl={activeInspectorPlayer.headshot_url}
                    size={96}
                    priority
                    className="border-2 border-slate-200 shadow-sm"
                  />
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <span className="rounded-md bg-slate-100 px-2.5 py-0.5 font-mono text-xs font-bold text-slate-700">
                      {activeInspectorPlayer.team_abbreviation}
                    </span>
                    <h3 className="text-xl font-black tracking-tight text-slate-900 leading-snug line-clamp-2">
                      {activeInspectorPlayer.player_name}
                    </h3>
                    <p className="text-xs font-semibold text-slate-500">
                      {activeInspectorPlayer.mpg.toFixed(1)} MPG • {seasonLabel}
                    </p>
                  </div>
                </div>

                {/* KPI Metrics Grid */}
                <div className="grid grid-cols-2 gap-3 text-center text-xs">
                  <div className="rounded-2xl border border-slate-100 bg-slate-50/80 p-3.5">
                    <span className="text-[10px] uppercase font-bold text-slate-400">Puntos (PPG)</span>
                    <div className="font-mono text-2xl font-black text-slate-900 mt-0.5">
                      {activeInspectorPlayer.ppg.toFixed(1)}
                    </div>
                  </div>

                  <div className="rounded-2xl border border-slate-100 bg-slate-50/80 p-3.5">
                    <span className="text-[10px] uppercase font-bold text-slate-400">Rebotes (RPG)</span>
                    <div className="font-mono text-2xl font-black text-slate-900 mt-0.5">
                      {activeInspectorPlayer.rpg.toFixed(1)}
                    </div>
                  </div>

                  <div className="rounded-2xl border border-slate-100 bg-slate-50/80 p-3.5">
                    <span className="text-[10px] uppercase font-bold text-slate-400">Asistencias (APG)</span>
                    <div className="font-mono text-2xl font-black text-slate-900 mt-0.5">
                      {activeInspectorPlayer.apg.toFixed(1)}
                    </div>
                  </div>

                  <div className="rounded-2xl border border-slate-100 bg-slate-50/80 p-3.5">
                    <span className="text-[10px] uppercase font-bold text-slate-400">Triples (3PM)</span>
                    <div className="font-mono text-2xl font-black text-orange-600 mt-0.5">
                      {activeInspectorPlayer.fg3m.toFixed(1)}
                    </div>
                  </div>
                </div>

                {/* Soft Affinity Progress Meter */}
                <div className="rounded-2xl border border-slate-100 bg-slate-50/70 p-4 space-y-2.5">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-bold text-slate-700">
                      {language === "es" ? "Afinidad Táctica al Rol" : "Tactical Role Affinity"}
                    </span>
                    <span className="font-mono font-extrabold text-purple-700 text-sm">
                      {activeInspectorPlayer.primary_percentage}%
                    </span>
                  </div>
                  <div className="h-3 w-full overflow-hidden rounded-full bg-slate-200 shadow-inner">
                    <div
                      className="h-full rounded-full transition-all duration-500"
                      style={{
                        width: `${activeInspectorPlayer.primary_percentage}%`,
                        backgroundColor: activeInspectorPlayer.color,
                      }}
                    />
                  </div>
                </div>

                {/* Direct Action Link to Player Scouting Lab */}
                <button
                  onClick={() => router.push(`/player/${encodeURIComponent(activeInspectorPlayer.player_name)}`)}
                  className="w-full flex items-center justify-center gap-2 rounded-2xl bg-slate-900 py-3.5 text-xs font-bold text-white shadow-xs hover:bg-orange-600 transition cursor-pointer"
                >
                  <span>{language === "es" ? "Abrir Scouting Lab Completo" : "Open Full Scouting Lab"}</span>
                  <ArrowUpRight className="h-4 w-4" />
                </button>
              </div>
            ) : (
              <div className="py-16 text-center text-xs text-slate-400">
                {language === "es" ? "Pasá el cursor o clickeá una estrella para ver sus datos" : "Hover or click any star to inspect"}
              </div>
            )}

          </div>
        </div>

      </div>

      {/* 4-Quadrant Tactical Navigation Guide */}
      {showGuide && (
        <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-5 space-y-3 transition-all">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs font-bold text-slate-800">
              <Compass className="h-4 w-4 text-purple-600" />
              <span>{language === "es" ? "Guía Táctica de los 4 Cuadrantes Espaciales" : "4-Quadrant Tactical Orientation Guide"}</span>
            </div>
            <span className="text-[11px] font-mono font-semibold text-slate-400">PCA Vector Space</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
            
            {/* Quadrant 1: Top-Right */}
            <div className="rounded-xl border border-orange-200 bg-white p-3.5 shadow-2xs space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="font-black text-orange-600">↗ Cuadrante I (Arriba-Derecha)</span>
                <Zap className="h-3.5 w-3.5 text-orange-500" />
              </div>
              <div className="font-bold text-slate-900">Motores Heliocéntricos & Estrellas</div>
              <p className="text-[11px] text-slate-600 leading-tight">
                Alto volumen de tiro, uso estelar (USG% superior a 28%), generación de triples y creación de juego (Luka, SGA, Brunson, Mitchell).
              </p>
            </div>

            {/* Quadrant 2: Top-Left */}
            <div className="rounded-xl border border-purple-200 bg-white p-3.5 shadow-2xs space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="font-black text-purple-600">↖ Cuadrante II (Arriba-Izquierda)</span>
                <Activity className="h-3.5 w-3.5 text-purple-500" />
              </div>
              <div className="font-bold text-slate-900">Unicornios & Interiores Creadores</div>
              <p className="text-[11px] text-slate-600 leading-tight">
                Pivots y aleros con impacto multidimensional: rebote de élite, facilitación desde el poste y juego hacia el aro (Giannis, Jokić, Sengun).
              </p>
            </div>

            {/* Quadrant 3: Bottom-Left */}
            <div className="rounded-xl border border-blue-200 bg-white p-3.5 shadow-2xs space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="font-black text-blue-600">↙ Cuadrante III (Abajo-Izquierda)</span>
                <Shield className="h-3.5 w-3.5 text-blue-500" />
              </div>
              <div className="font-bold text-slate-900">Protectores de Aro Tradicionales</div>
              <p className="text-[11px] text-slate-600 leading-tight">
                Anclas de pintura puras: alta tasa de tapones y rebotes, finalización vertical de alley-oops y nulo tiro exterior (Gobert, Capela, Kessler).
              </p>
            </div>

            {/* Quadrant 4: Bottom-Right */}
            <div className="rounded-xl border border-cyan-200 bg-white p-3.5 shadow-2xs space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="font-black text-cyan-600">↘ Cuadrante IV (Abajo-Derecha)</span>
                <Target className="h-3.5 w-3.5 text-cyan-500" />
              </div>
              <div className="font-bold text-slate-900">Especialistas 3&D & Conectores</div>
              <p className="text-[11px] text-slate-600 leading-tight">
                Roles complementarios de alta eficiencia: triples catch & shoot (más de 60% de sus tiros), defensa en el punto de ataque y rotaciones (Caruso, Dort, Grayson Allen).
              </p>
            </div>

          </div>
        </div>
      )}

    </div>
  );
}
