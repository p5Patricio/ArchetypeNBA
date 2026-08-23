"use client";

import React, { useEffect, useState, useMemo } from "react";
import Image from "next/image";
import Link from "next/link";
import {
  Swords,
  Trophy,
  Sparkles,
  Award,
  Crown,
  Flame,
  Shield,
  Zap,
  Target,
  ArrowRightLeft,
  Search,
  Check,
  ChevronDown,
  Info,
  Medal,
  Star,
  Activity,
  Dumbbell,
  Eye,
  Sliders,
  CheckCircle2,
  TrendingUp,
} from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { CommandPalette } from "@/components/CommandPalette";
import {
  getVersusPlayers,
  getVersusMatchup,
  type VersusPlayerOption,
  type VersusMatchupResponse,
  type VersusSeasonOption,
} from "@/lib/api";
import { usePreferences } from "@/context/PreferencesContext";

function cleanStr(s: string) {
  return (s || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/['’.\-_\s]/g, "")
    .trim();
}

type PresetMatchup = {
  p1: string;
  p2: string;
  label: string;
  s1?: string;
  s2?: string;
};

// Preset legendary rivalries for quick one-click battles
const PRESET_MATCHUPS: PresetMatchup[] = [
  { p1: "Michael Jordan", p2: "LeBron James", label: "Jordan '88 vs LeBron '13", s1: "1987-88", s2: "2012-13" },
  { p1: "LeBron James", p2: "Kobe Bryant", label: "LeBron '09 vs Kobe '06", s1: "2008-09", s2: "2005-06" },
  { p1: "Stephen Curry", p2: "Kobe Bryant", label: "Curry '16 vs Kobe '06", s1: "2015-16", s2: "2005-06" },
  { p1: "Shaquille O'Neal", p2: "Nikola Jokic", label: "Shaq '04 vs Jokic '24", s1: "2003-04", s2: "2023-24" },
  { p1: "Luka Doncic", p2: "Dwyane Wade", label: "Luka '24 vs Wade '09", s1: "2023-24", s2: "2008-09" },
  { p1: "Giannis Antetokounmpo", p2: "Kevin Durant", label: "Giannis '20 vs KD '14", s1: "2019-20", s2: "2013-14" },
  { p1: "Victor Wembanyama", p2: "Anthony Davis", label: "Wemby '24 vs AD '20", s1: "2023-24", s2: "2019-20" },
  { p1: "Dirk Nowitzki", p2: "Tim Duncan", label: "Dirk '06 vs Duncan '04", s1: "2005-06", s2: "2003-04" },
];

export default function VersusPage() {
  const { language, unitSystem, t } = usePreferences();
  const isEs = language === "es";

  const [allPlayers, setAllPlayers] = useState<VersusPlayerOption[]>([]);
  const [loadingPlayers, setLoadingPlayers] = useState<boolean>(true);
  const [isCommandOpen, setIsCommandOpen] = useState<boolean>(false);

  // Selected player IDs & seasons
  const [player1Id, setPlayer1Id] = useState<number | null>(null);
  const [season1Id, setSeason1Id] = useState<number | null>(null);

  const [player2Id, setPlayer2Id] = useState<number | null>(null);
  const [season2Id, setSeason2Id] = useState<number | null>(null);

  // Search dropdown filters
  const [p1Search, setP1Search] = useState("");
  const [p2Search, setP2Search] = useState("");
  const [p1DropdownOpen, setP1DropdownOpen] = useState(false);
  const [p2DropdownOpen, setP2DropdownOpen] = useState(false);

  // Matchup calculation state
  const [matchup, setMatchup] = useState<VersusMatchupResponse | null>(null);
  const [loadingMatchup, setLoadingMatchup] = useState<boolean>(false);
  const [matchupError, setMatchupError] = useState<string | null>(null);

  // Active view tab in comparison: "dimensions" | "stats" | "accolades" | "tactics"
  const [activeTab, setActiveTab] = useState<"dimensions" | "stats" | "accolades" | "tactics">("dimensions");

  // Robust accent-insensitive search finder
  const findPlayer = (name: string) => {
    const target = cleanStr(name);
    return (
      allPlayers.find((p) => cleanStr(p.player_name) === target) ||
      allPlayers.find((p) => cleanStr(p.player_name).includes(target) || target.includes(cleanStr(p.player_name)))
    );
  };

  // Load initial players catalog
  useEffect(() => {
    async function loadCatalog() {
      try {
        setLoadingPlayers(true);
        const data = await getVersusPlayers();
        setAllPlayers(data);

        // Find defaults: LeBron James vs Kobe Bryant or first two
        const p1Default = data.find((p) => cleanStr(p.player_name).includes("lebron")) || data[0];
        const p2Default = data.find((p) => cleanStr(p.player_name).includes("kobe")) || data[1] || data[0];

        if (p1Default) {
          setPlayer1Id(p1Default.player_id);
          setSeason1Id(p1Default.best_season_id);
        }
        if (p2Default) {
          setPlayer2Id(p2Default.player_id);
          setSeason2Id(p2Default.best_season_id);
        }
      } catch (err) {
        console.error("Error loading players for versus:", err);
      } finally {
        setLoadingPlayers(false);
      }
    }
    loadCatalog();
  }, []);

  // Fetch matchup whenever selection changes
  useEffect(() => {
    if (!player1Id || !player2Id) return;

    async function fetchMatchupData() {
      try {
        setLoadingMatchup(true);
        setMatchupError(null);
        const res = await getVersusMatchup(
          player1Id || undefined,
          undefined,
          season1Id || undefined,
          player2Id || undefined,
          undefined,
          season2Id || undefined
        );
        setMatchup(res);
      } catch (err: any) {
        console.error("Error fetching versus matchup:", err);
        setMatchupError(err?.message || "No se pudo calcular el duelo");
      } finally {
        setLoadingMatchup(false);
      }
    }

    fetchMatchupData();
  }, [player1Id, season1Id, player2Id, season2Id]);

  // Selected player objects from list
  const selectedP1Obj = useMemo(
    () => allPlayers.find((p) => p.player_id === player1Id),
    [allPlayers, player1Id]
  );
  const selectedP2Obj = useMemo(
    () => allPlayers.find((p) => p.player_id === player2Id),
    [allPlayers, player2Id]
  );

  // Filtered dropdown results with accent normalization
  const filteredP1 = useMemo(() => {
    if (!p1Search.trim()) return allPlayers.slice(0, 8);
    const q = cleanStr(p1Search);
    return allPlayers
      .filter((p) => cleanStr(p.player_name).includes(q) || cleanStr(p.team_abbreviation).includes(q))
      .slice(0, 10);
  }, [allPlayers, p1Search]);

  const filteredP2 = useMemo(() => {
    if (!p2Search.trim()) return allPlayers.slice(0, 8);
    const q = cleanStr(p2Search);
    return allPlayers
      .filter((p) => cleanStr(p.player_name).includes(q) || cleanStr(p.team_abbreviation).includes(q))
      .slice(0, 10);
  }, [allPlayers, p2Search]);

  // Handler for quick presets
  const applyPreset = (preset: PresetMatchup) => {
    const p1 = findPlayer(preset.p1);
    const p2 = findPlayer(preset.p2);
    if (p1 && p2) {
      let s1 = p1.best_season_id;
      if (preset.s1) {
        const matchSeason = p1.seasons.find((s) => s.season_label === preset.s1);
        if (matchSeason) s1 = matchSeason.season_id;
      }
      let s2 = p2.best_season_id;
      if (preset.s2) {
        const matchSeason = p2.seasons.find((s) => s.season_label === preset.s2);
        if (matchSeason) s2 = matchSeason.season_id;
      }
      setPlayer1Id(p1.player_id);
      setSeason1Id(s1);
      setPlayer2Id(p2.player_id);
      setSeason2Id(s2);
    }
  };

  // Swap sides
  const swapPlayers = () => {
    const oldP1 = player1Id;
    const oldS1 = season1Id;
    setPlayer1Id(player2Id);
    setSeason1Id(season2Id);
    setPlayer2Id(oldP1);
    setSeason2Id(oldS1);
  };

  return (
    <div className="min-h-screen bg-[#F8FAFC] text-slate-900 selection:bg-orange-100 selection:text-orange-900">
      <Navbar onOpenSearch={() => setIsCommandOpen(true)} />

      <CommandPalette
        isOpen={isCommandOpen}
        onClose={() => setIsCommandOpen(false)}
      />

      <div className="md:pl-64">
        {/* ========================================================================= */}
        {/* HERO SECTION (Clean White / Warm Gradient consistent with ArchetypeNBA) */}
        {/* ========================================================================= */}
        <section className="relative border-b border-slate-200 bg-gradient-to-b from-orange-50/40 via-white to-white py-12 lg:py-16 shadow-xs">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="flex flex-col items-center text-center space-y-4">
              {/* Crown/Swords Pill Badge */}
              <div className="inline-flex items-center gap-2 rounded-full border border-orange-200 bg-orange-50 px-4 py-1 text-xs font-black text-orange-800 shadow-2xs">
                <Swords className="h-3.5 w-3.5 text-orange-600" />
                <span>{isEs ? "COLISEO 1 VS 1 • SIMULADOR MACHINE LEARNING" : "1 VS 1 COLOSSEUM • MACHINE LEARNING SIMULATOR"}</span>
              </div>

              {/* Headline */}
              <h1 className="max-w-4xl text-3xl sm:text-5xl font-black tracking-tight text-slate-900 leading-tight">
                {isEs ? "Duelo de Leyendas & Estrellas NBA" : "NBA Legends & Superstars 1v1 Battle"}
              </h1>

              <p className="max-w-3xl text-sm sm:text-base text-slate-600 font-normal leading-relaxed">
                {isEs
                  ? "Enfrentá a cualquier par de jugadores eligiendo temporadas específicas o su mejor campaña histórica recomendada. El motor evalúa 7 dimensiones tácticas para proyectar al ganador."
                  : "Pit any two players head-to-head across custom or peak-recommended seasons. The AI simulation engine assesses 7 tactical dimensions to project the winner."}
              </p>

              {/* Quick Preset Matches */}
              <div className="pt-3 w-full max-w-4xl">
                <div className="flex items-center justify-center gap-1.5 text-xs font-mono font-bold uppercase tracking-wider text-slate-500 mb-2.5">
                  <Flame className="h-3.5 w-3.5 text-orange-500" />
                  <span>{isEs ? "Duelos Legendarios Rápidos:" : "Legendary Matchup Presets:"}</span>
                </div>
                <div className="flex flex-wrap items-center justify-center gap-2">
                  {PRESET_MATCHUPS.map((preset, idx) => (
                    <button
                      key={idx}
                      onClick={() => applyPreset(preset)}
                      className="rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-bold text-slate-700 shadow-2xs transition hover:border-orange-400 hover:bg-orange-50 hover:text-orange-900"
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ========================================================================= */}
        {/* MAIN INTERACTIVE ARENA */}
        {/* ========================================================================= */}
        <main className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-8 space-y-8">
          
          {/* PLAYER & SEASON SELECTORS BAR */}
          <div className="grid grid-cols-1 md:grid-cols-12 gap-4 items-center">
            {/* Player 1 Selection Box (5 cols) */}
            <div className="md:col-span-5 rounded-2xl border border-slate-200/90 bg-white p-4 sm:p-5 shadow-xs">
              <div className="flex items-center justify-between mb-2.5">
                <span className="text-xs font-mono font-black uppercase tracking-wider text-orange-700 flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-orange-500" />
                  {isEs ? "JUGADOR 1 (LADO ROJO)" : "PLAYER 1 (RED CORNER)"}
                </span>
                {matchup?.player1.is_best_season && (
                  <span className="inline-flex items-center gap-1 rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-[10px] font-black text-amber-800 shadow-2xs">
                    <Star className="h-3 w-3 fill-amber-500 text-amber-500" />
                    {isEs ? "Mejor Temporada" : "Peak Season"}
                  </span>
                )}
              </div>

              {/* Player Search Trigger */}
              <div className="relative mb-3">
                <div
                  onClick={() => setP1DropdownOpen(!p1DropdownOpen)}
                  className="flex items-center justify-between cursor-pointer rounded-xl border border-slate-200 bg-slate-50/70 px-3.5 py-2.5 text-sm font-extrabold text-slate-900 hover:border-orange-400 hover:bg-white transition shadow-2xs"
                >
                  <div className="flex items-center gap-2 truncate">
                    <Search className="h-4 w-4 text-slate-400 shrink-0" />
                    <span className="truncate">{selectedP1Obj?.player_name || (isEs ? "Seleccionar jugador..." : "Select player...")}</span>
                  </div>
                  <ChevronDown className="h-4 w-4 text-slate-400 shrink-0" />
                </div>

                {p1DropdownOpen && (
                  <div className="absolute top-full left-0 z-50 mt-1 w-full rounded-2xl border border-slate-200 bg-white p-2 shadow-xl">
                    <input
                      type="text"
                      placeholder={isEs ? "Buscar jugador por nombre..." : "Search player by name..."}
                      value={p1Search}
                      onChange={(e) => setP1Search(e.target.value)}
                      className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-orange-500 focus:bg-white mb-2"
                      autoFocus
                    />
                    <div className="max-h-56 overflow-y-auto space-y-1">
                      {filteredP1.map((p) => (
                        <div
                          key={p.player_id}
                          onClick={() => {
                            setPlayer1Id(p.player_id);
                            setSeason1Id(p.best_season_id);
                            setP1DropdownOpen(false);
                            setP1Search("");
                          }}
                          className={`flex items-center justify-between px-3 py-2 rounded-xl cursor-pointer text-xs font-bold transition ${
                            p.player_id === player1Id
                              ? "bg-orange-600 text-white"
                              : "text-slate-700 hover:bg-slate-100 hover:text-slate-900"
                          }`}
                        >
                          <div className="flex items-center gap-2">
                            <span className={`text-[10px] font-mono uppercase px-1.5 py-0.5 rounded ${p.player_id === player1Id ? "bg-orange-700 text-white" : "bg-slate-100 text-slate-600"}`}>
                              {p.team_abbreviation}
                            </span>
                            <span>{p.player_name}</span>
                          </div>
                          <span className={`text-[10px] font-mono ${p.player_id === player1Id ? "text-orange-200" : "text-amber-600"}`}>
                            Peak: {p.best_season_label}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Season Selector */}
              {selectedP1Obj && (
                <div>
                  <label className="block text-[11px] font-mono font-bold uppercase text-slate-500 mb-1">
                    {isEs ? "Temporada a Evaluar:" : "Season to Evaluate:"}
                  </label>
                  <select
                    value={season1Id || selectedP1Obj.best_season_id}
                    onChange={(e) => setSeason1Id(Number(e.target.value))}
                    className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-bold text-slate-800 focus:outline-none focus:border-orange-500 focus:bg-white shadow-2xs"
                  >
                    {selectedP1Obj.seasons.map((s) => (
                      <option key={s.season_id} value={s.season_id}>
                        {s.season_label} ({s.team_abbreviation}) — {s.pts_pg} PPG, {s.reb_pg} RPG, {s.ast_pg} APG{" "}
                        {s.is_best_season ? "⭐ [PEAK]" : ""}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>

            {/* Center Swap Action Button (2 cols) */}
            <div className="md:col-span-2 flex flex-col items-center justify-center">
              <button
                onClick={swapPlayers}
                className="group flex h-12 w-12 items-center justify-center rounded-full border-2 border-slate-200 bg-white text-slate-600 shadow-sm transition hover:border-orange-500 hover:bg-orange-50 hover:text-orange-600 hover:scale-105 active:scale-95"
                title={isEs ? "Invertir posiciones" : "Swap positions"}
              >
                <ArrowRightLeft className="h-5 w-5 transition-transform group-hover:rotate-180 duration-300" />
              </button>
              <span className="text-[10px] font-mono font-bold text-slate-400 uppercase mt-1">
                {isEs ? "Invertir" : "Swap"}
              </span>
            </div>

            {/* Player 2 Selection Box (5 cols) */}
            <div className="md:col-span-5 rounded-2xl border border-slate-200/90 bg-white p-4 sm:p-5 shadow-xs">
              <div className="flex items-center justify-between mb-2.5">
                <span className="text-xs font-mono font-black uppercase tracking-wider text-sky-700 flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-sky-500" />
                  {isEs ? "JUGADOR 2 (LADO AZUL)" : "PLAYER 2 (BLUE CORNER)"}
                </span>
                {matchup?.player2.is_best_season && (
                  <span className="inline-flex items-center gap-1 rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-[10px] font-black text-amber-800 shadow-2xs">
                    <Star className="h-3 w-3 fill-amber-500 text-amber-500" />
                    {isEs ? "Mejor Temporada" : "Peak Season"}
                  </span>
                )}
              </div>

              {/* Player Search Trigger */}
              <div className="relative mb-3">
                <div
                  onClick={() => setP2DropdownOpen(!p2DropdownOpen)}
                  className="flex items-center justify-between cursor-pointer rounded-xl border border-slate-200 bg-slate-50/70 px-3.5 py-2.5 text-sm font-extrabold text-slate-900 hover:border-sky-400 hover:bg-white transition shadow-2xs"
                >
                  <div className="flex items-center gap-2 truncate">
                    <Search className="h-4 w-4 text-slate-400 shrink-0" />
                    <span className="truncate">{selectedP2Obj?.player_name || (isEs ? "Seleccionar jugador..." : "Select player...")}</span>
                  </div>
                  <ChevronDown className="h-4 w-4 text-slate-400 shrink-0" />
                </div>

                {p2DropdownOpen && (
                  <div className="absolute top-full left-0 z-50 mt-1 w-full rounded-2xl border border-slate-200 bg-white p-2 shadow-xl">
                    <input
                      type="text"
                      placeholder={isEs ? "Buscar jugador por nombre..." : "Search player by name..."}
                      value={p2Search}
                      onChange={(e) => setP2Search(e.target.value)}
                      className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-sky-500 focus:bg-white mb-2"
                      autoFocus
                    />
                    <div className="max-h-56 overflow-y-auto space-y-1">
                      {filteredP2.map((p) => (
                        <div
                          key={p.player_id}
                          onClick={() => {
                            setPlayer2Id(p.player_id);
                            setSeason2Id(p.best_season_id);
                            setP2DropdownOpen(false);
                            setP2Search("");
                          }}
                          className={`flex items-center justify-between px-3 py-2 rounded-xl cursor-pointer text-xs font-bold transition ${
                            p.player_id === player2Id
                              ? "bg-sky-600 text-white"
                              : "text-slate-700 hover:bg-slate-100 hover:text-slate-900"
                          }`}
                        >
                          <div className="flex items-center gap-2">
                            <span className={`text-[10px] font-mono uppercase px-1.5 py-0.5 rounded ${p.player_id === player2Id ? "bg-sky-700 text-white" : "bg-slate-100 text-slate-600"}`}>
                              {p.team_abbreviation}
                            </span>
                            <span>{p.player_name}</span>
                          </div>
                          <span className={`text-[10px] font-mono ${p.player_id === player2Id ? "text-sky-200" : "text-amber-600"}`}>
                            Peak: {p.best_season_label}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Season Selector */}
              {selectedP2Obj && (
                <div>
                  <label className="block text-[11px] font-mono font-bold uppercase text-slate-500 mb-1">
                    {isEs ? "Temporada a Evaluar:" : "Season to Evaluate:"}
                  </label>
                  <select
                    value={season2Id || selectedP2Obj.best_season_id}
                    onChange={(e) => setSeason2Id(Number(e.target.value))}
                    className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-bold text-slate-800 focus:outline-none focus:border-sky-500 focus:bg-white shadow-2xs"
                  >
                    {selectedP2Obj.seasons.map((s) => (
                      <option key={s.season_id} value={s.season_id}>
                        {s.season_label} ({s.team_abbreviation}) — {s.pts_pg} PPG, {s.reb_pg} RPG, {s.ast_pg} APG{" "}
                        {s.is_best_season ? "⭐ [PEAK]" : ""}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>
          </div>

          {/* ========================================================================= */}
          {/* HEAD-TO-HEAD CARDS & PREDICTION SCOREBOARD */}
          {/* ========================================================================= */}
          {loadingMatchup ? (
            <div className="flex flex-col items-center justify-center py-20 rounded-3xl border border-slate-200 bg-white shadow-xs">
              <Swords className="h-10 w-10 text-orange-500 animate-spin mb-4" />
              <p className="text-sm font-mono font-bold text-slate-600">
                {isEs ? "Simulando duelo táctico y calculando métricas 1v1..." : "Simulating 1v1 matchup and computing tactical dimensions..."}
              </p>
            </div>
          ) : matchupError ? (
            <div className="p-6 rounded-2xl border border-rose-200 bg-rose-50 text-rose-800 text-center font-medium shadow-xs">
              {matchupError}
            </div>
          ) : matchup ? (
            <>
              {/* LARGE GIANT DISPLAY CARDS */}
              <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-stretch">
                
                {/* Player 1 Card (Left - 5 cols) */}
                <div className="lg:col-span-5 rounded-3xl border-2 border-orange-100 bg-white p-6 flex flex-col justify-between shadow-xs hover:border-orange-200 transition">
                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <span className="rounded-lg bg-orange-50 border border-orange-200 px-2.5 py-1 text-xs font-mono font-black text-orange-800">
                        {matchup.player1.team_abbreviation} • {matchup.player1.selected_season_label}
                      </span>
                      <span
                        className="rounded-full px-3 py-1 text-[11px] font-black uppercase text-white shadow-xs"
                        style={{ backgroundColor: matchup.player1.archetype_color }}
                      >
                        {isEs ? matchup.player1.archetype_es : matchup.player1.archetype_en}
                      </span>
                    </div>

                    <h2 className="text-2xl sm:text-3xl font-black text-slate-900 tracking-tight">
                      {matchup.player1.player_name}
                    </h2>
                    <div className="flex items-center gap-3 text-xs font-mono font-bold text-slate-500 mt-1">
                      <span>{matchup.player1.position}</span>
                      <span>•</span>
                      <span>{unitSystem === "metric" ? `${matchup.player1.height_cm} cm` : matchup.player1.height}</span>
                      <span>•</span>
                      <span>{unitSystem === "metric" ? `${matchup.player1.weight_kg} kg` : matchup.player1.weight}</span>
                    </div>
                  </div>

                  {/* High-Res Player Headshot */}
                  <div className="relative my-6 mx-auto h-64 sm:h-80 w-full max-w-[280px] sm:max-w-[320px]">
                    <Image
                      src={matchup.player1.headshot_url}
                      alt={matchup.player1.player_name}
                      fill
                      className="object-contain drop-shadow-[0_15px_25px_rgba(249,115,22,0.2)] transition-transform duration-500 hover:scale-105"
                      priority
                      unoptimized
                    />
                  </div>

                  {/* Player 1 Stats Summary Pill */}
                  <div className="grid grid-cols-4 gap-2 pt-4 border-t border-slate-100 text-center">
                    <div className="bg-slate-50 rounded-2xl p-2.5 border border-slate-100">
                      <span className="block text-[10px] font-mono font-bold text-slate-500 uppercase">PTS</span>
                      <span className="text-base font-black text-slate-900">{matchup.player1.stats.pts_pg}</span>
                    </div>
                    <div className="bg-slate-50 rounded-2xl p-2.5 border border-slate-100">
                      <span className="block text-[10px] font-mono font-bold text-slate-500 uppercase">REB</span>
                      <span className="text-base font-black text-slate-900">{matchup.player1.stats.reb_pg}</span>
                    </div>
                    <div className="bg-slate-50 rounded-2xl p-2.5 border border-slate-100">
                      <span className="block text-[10px] font-mono font-bold text-slate-500 uppercase">AST</span>
                      <span className="text-base font-black text-slate-900">{matchup.player1.stats.ast_pg}</span>
                    </div>
                    <div className="bg-orange-50/70 rounded-2xl p-2.5 border border-orange-100">
                      <span className="block text-[10px] font-mono font-bold text-orange-700 uppercase">PER</span>
                      <span className="text-base font-black text-orange-900">{matchup.player1.stats.per || "—"}</span>
                    </div>
                  </div>
                </div>

                {/* Center Matchup Hub (2 cols) */}
                <div className="lg:col-span-2 flex flex-col justify-center items-center rounded-3xl border border-slate-200 bg-white p-5 shadow-xs text-center">
                  <div className="w-full space-y-4">
                    {/* Swords Icon */}
                    <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-orange-50 border border-orange-200 text-orange-600 shadow-2xs">
                      <Swords className="h-6 w-6" />
                    </div>

                    <div>
                      <span className="text-[10px] font-mono font-black uppercase tracking-widest text-slate-400 block mb-1">
                        {isEs ? "PROYECCIÓN 1v1" : "1v1 PREDICTION"}
                      </span>

                      {/* Projected Score to 21 */}
                      <div className="my-2 py-2.5 px-3 rounded-2xl border border-slate-100 bg-slate-50/80">
                        <div className="text-[10px] font-mono font-bold text-slate-500 uppercase mb-1">
                          {isEs ? "Marcador a 21 Pts" : "Game to 21 Pts"}
                        </div>
                        <div className="text-3xl font-black tracking-tight text-slate-900 flex items-center justify-center gap-2">
                          <span className={matchup.simulation.p1_win_prob >= 50 ? "text-orange-600" : "text-slate-400"}>
                            {matchup.simulation.projected_score_p1}
                          </span>
                          <span className="text-slate-300">-</span>
                          <span className={matchup.simulation.p2_win_prob >= 50 ? "text-sky-600" : "text-slate-400"}>
                            {matchup.simulation.projected_score_p2}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Win Probability Percentages */}
                    <div>
                      <div className="flex justify-between text-xs font-mono font-black mb-1.5">
                        <span className="text-orange-600">{matchup.simulation.p1_win_prob}%</span>
                        <span className="text-sky-600">{matchup.simulation.p2_win_prob}%</span>
                      </div>
                      {/* Dual Progress Bar */}
                      <div className="h-3 w-full rounded-full bg-slate-100 overflow-hidden flex p-0.5 border border-slate-200">
                        <div
                          className="h-full rounded-l-full bg-gradient-to-r from-orange-500 to-amber-500 transition-all duration-700"
                          style={{ width: `${matchup.simulation.p1_win_prob}%` }}
                        />
                        <div
                          className="h-full rounded-r-full bg-gradient-to-l from-sky-500 to-blue-500 transition-all duration-700"
                          style={{ width: `${matchup.simulation.p2_win_prob}%` }}
                        />
                      </div>
                    </div>

                    {/* Winner Crown Banner */}
                    <div className="pt-3 border-t border-slate-100">
                      <span className="text-[10px] font-mono font-bold text-slate-500 uppercase block mb-1">
                        {isEs ? "Ganador Proyectado" : "Projected Winner"}
                      </span>
                      <div className="inline-flex items-center gap-1.5 text-xs font-black text-amber-900 bg-amber-50 border border-amber-200 px-3 py-1.5 rounded-xl shadow-2xs">
                        <Crown className="h-3.5 w-3.5 text-amber-600" />
                        <span className="truncate max-w-[125px]">{matchup.simulation.predicted_winner_name}</span>
                      </div>
                      <div className="text-[11px] font-mono text-slate-500 mt-2">
                        {isEs ? "Serie al mejor de 7:" : "Best-of-7 Series:"}{" "}
                        <strong className="text-slate-800">{matchup.simulation.series_score}</strong>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Player 2 Card (Right - 5 cols) */}
                <div className="lg:col-span-5 rounded-3xl border-2 border-sky-100 bg-white p-6 flex flex-col justify-between shadow-xs hover:border-sky-200 transition">
                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <span className="rounded-lg bg-sky-50 border border-sky-200 px-2.5 py-1 text-xs font-mono font-black text-sky-800">
                        {matchup.player2.team_abbreviation} • {matchup.player2.selected_season_label}
                      </span>
                      <span
                        className="rounded-full px-3 py-1 text-[11px] font-black uppercase text-white shadow-xs"
                        style={{ backgroundColor: matchup.player2.archetype_color }}
                      >
                        {isEs ? matchup.player2.archetype_es : matchup.player2.archetype_en}
                      </span>
                    </div>

                    <h2 className="text-2xl sm:text-3xl font-black text-slate-900 tracking-tight">
                      {matchup.player2.player_name}
                    </h2>
                    <div className="flex items-center gap-3 text-xs font-mono font-bold text-slate-500 mt-1">
                      <span>{matchup.player2.position}</span>
                      <span>•</span>
                      <span>{unitSystem === "metric" ? `${matchup.player2.height_cm} cm` : matchup.player2.height}</span>
                      <span>•</span>
                      <span>{unitSystem === "metric" ? `${matchup.player2.weight_kg} kg` : matchup.player2.weight}</span>
                    </div>
                  </div>

                  {/* High-Res Player Headshot */}
                  <div className="relative my-6 mx-auto h-64 sm:h-80 w-full max-w-[280px] sm:max-w-[320px]">
                    <Image
                      src={matchup.player2.headshot_url}
                      alt={matchup.player2.player_name}
                      fill
                      className="object-contain drop-shadow-[0_15px_25px_rgba(56,189,248,0.2)] transition-transform duration-500 hover:scale-105"
                      priority
                      unoptimized
                    />
                  </div>

                  {/* Player 2 Stats Summary Pill */}
                  <div className="grid grid-cols-4 gap-2 pt-4 border-t border-slate-100 text-center">
                    <div className="bg-slate-50 rounded-2xl p-2.5 border border-slate-100">
                      <span className="block text-[10px] font-mono font-bold text-slate-500 uppercase">PTS</span>
                      <span className="text-base font-black text-slate-900">{matchup.player2.stats.pts_pg}</span>
                    </div>
                    <div className="bg-slate-50 rounded-2xl p-2.5 border border-slate-100">
                      <span className="block text-[10px] font-mono font-bold text-slate-500 uppercase">REB</span>
                      <span className="text-base font-black text-slate-900">{matchup.player2.stats.reb_pg}</span>
                    </div>
                    <div className="bg-slate-50 rounded-2xl p-2.5 border border-slate-100">
                      <span className="block text-[10px] font-mono font-bold text-slate-500 uppercase">AST</span>
                      <span className="text-base font-black text-slate-900">{matchup.player2.stats.ast_pg}</span>
                    </div>
                    <div className="bg-sky-50/70 rounded-2xl p-2.5 border border-sky-100">
                      <span className="block text-[10px] font-mono font-bold text-sky-700 uppercase">PER</span>
                      <span className="text-base font-black text-sky-900">{matchup.player2.stats.per || "—"}</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* ========================================================================= */}
              {/* TACTICAL NAVIGATION TABS */}
              {/* ========================================================================= */}
              <div className="flex flex-wrap items-center justify-center gap-2 pt-2">
                <button
                  onClick={() => setActiveTab("dimensions")}
                  className={`flex items-center gap-2 rounded-2xl px-5 py-2.5 text-xs font-black transition ${
                    activeTab === "dimensions"
                      ? "bg-orange-600 text-white shadow-xs"
                      : "bg-white border border-slate-200 text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                  }`}
                >
                  <Activity className="h-4 w-4" />
                  {isEs ? "7 Dimensiones Tácticas 1v1" : "7 Tactical 1v1 Dimensions"}
                </button>

                <button
                  onClick={() => setActiveTab("stats")}
                  className={`flex items-center gap-2 rounded-2xl px-5 py-2.5 text-xs font-black transition ${
                    activeTab === "stats"
                      ? "bg-orange-600 text-white shadow-xs"
                      : "bg-white border border-slate-200 text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                  }`}
                >
                  <Target className="h-4 w-4" />
                  {isEs ? "Comparativa Estadística Completa" : "Complete Stats Face-Off"}
                </button>

                <button
                  onClick={() => setActiveTab("accolades")}
                  className={`flex items-center gap-2 rounded-2xl px-5 py-2.5 text-xs font-black transition ${
                    activeTab === "accolades"
                      ? "bg-orange-600 text-white shadow-xs"
                      : "bg-white border border-slate-200 text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                  }`}
                >
                  <Trophy className="h-4 w-4" />
                  {isEs ? "Vitrina de Títulos & Palmarés" : "Trophy Cabinet & Honors"}
                </button>

                <button
                  onClick={() => setActiveTab("tactics")}
                  className={`flex items-center gap-2 rounded-2xl px-5 py-2.5 text-xs font-black transition ${
                    activeTab === "tactics"
                      ? "bg-orange-600 text-white shadow-xs"
                      : "bg-white border border-slate-200 text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                  }`}
                >
                  <Zap className="h-4 w-4" />
                  {isEs ? "Informe de Scouting & Claves" : "Scouting Report & Keys"}
                </button>
              </div>

              {/* ========================================================================= */}
              {/* TAB 1: 7 DIMENSIONES TÁCTICAS */}
              {/* ========================================================================= */}
              {activeTab === "dimensions" && (
                <div className="rounded-3xl border border-slate-200/90 bg-white p-6 sm:p-8 shadow-xs space-y-6">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-100 pb-4">
                    <div>
                      <h3 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
                        <Activity className="h-5 w-5 text-orange-600" />
                        {isEs ? "Evaluación Multidimensional de Duelo 1 vs 1" : "Multi-Dimensional 1v1 Duel Evaluation"}
                      </h3>
                      <p className="text-xs text-slate-500 mt-0.5">
                        {isEs
                          ? "Puntuación de 0 a 100 en cada área fundamental del básquetbol individual."
                          : "0-100 rating scale across each foundational area of one-on-one basketball."}
                      </p>
                    </div>
                    <div className="flex items-center gap-4 text-xs font-mono font-black">
                      <span className="flex items-center gap-1.5 text-orange-600">
                        <span className="h-3 w-3 rounded-md bg-orange-500" />
                        {matchup.player1.player_name}
                      </span>
                      <span className="flex items-center gap-1.5 text-sky-600">
                        <span className="h-3 w-3 rounded-md bg-sky-500" />
                        {matchup.player2.player_name}
                      </span>
                    </div>
                  </div>

                  <div className="space-y-4">
                    {matchup.simulation.dimensions.map((dim) => {
                      const p1Wins = dim.p1_score >= dim.p2_score;
                      return (
                        <div key={dim.key} className="rounded-2xl border border-slate-100 bg-slate-50/60 p-4 sm:p-5">
                          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-2">
                            <div>
                              <span className="text-sm font-black text-slate-900 block">
                                {isEs ? dim.name_es : dim.name_en}
                              </span>
                              <span className="text-xs text-slate-500">
                                {isEs ? dim.description_es : dim.description_en}
                              </span>
                            </div>
                            <div className="flex items-center gap-3 font-mono text-xs font-black">
                              <span className={`px-2.5 py-1 rounded-lg ${p1Wins ? "bg-orange-100 text-orange-800 font-extrabold border border-orange-200" : "bg-white text-slate-600 border border-slate-200"}`}>
                                {dim.p1_score}
                              </span>
                              <span className="text-slate-400">vs</span>
                              <span className={`px-2.5 py-1 rounded-lg ${!p1Wins ? "bg-sky-100 text-sky-800 font-extrabold border border-sky-200" : "bg-white text-slate-600 border border-slate-200"}`}>
                                {dim.p2_score}
                              </span>
                            </div>
                          </div>

                          {/* Dual Progress Bar */}
                          <div className="grid grid-cols-2 gap-3 mt-3">
                            <div className="h-3 w-full bg-slate-200/80 rounded-full overflow-hidden flex justify-end">
                              <div
                                className="h-full bg-gradient-to-l from-orange-500 to-amber-500 rounded-full transition-all duration-700"
                                style={{ width: `${dim.p1_score}%` }}
                              />
                            </div>
                            <div className="h-3 w-full bg-slate-200/80 rounded-full overflow-hidden flex justify-start">
                              <div
                                className="h-full bg-gradient-to-r from-sky-500 to-blue-500 rounded-full transition-all duration-700"
                                style={{ width: `${dim.p2_score}%` }}
                              />
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* ========================================================================= */}
              {/* TAB 2: COMPARATIVA ESTADÍSTICA COMPLETA */}
              {/* ========================================================================= */}
              {activeTab === "stats" && (
                <div className="rounded-3xl border border-slate-200/90 bg-white p-6 sm:p-8 shadow-xs">
                  <div className="mb-6 border-b border-slate-100 pb-4">
                    <h3 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
                      <Target className="h-5 w-5 text-orange-600" />
                      {isEs ? "Comparativa Estadística Cara a Cara" : "Head-to-Head Statistics Comparison"}
                    </h3>
                    <p className="text-xs text-slate-500 mt-0.5">
                      {isEs
                        ? "Valores reales por partido y métricas de eficiencia avanzada para la temporada elegida."
                        : "Actual per-game and advanced metrics recorded for each player's selected season."}
                    </p>
                  </div>

                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs font-mono">
                      <thead>
                        <tr className="border-b border-slate-200 text-slate-500 uppercase text-[11px]">
                          <th className="pb-3 text-orange-700 font-black">{matchup.player1.player_name}</th>
                          <th className="pb-3 text-center text-slate-700 font-bold">Métrica / Categoría</th>
                          <th className="pb-3 text-right text-sky-700 font-black">{matchup.player2.player_name}</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {matchup.stat_comparisons.map((stat) => {
                          const p1Leader = stat.leader === 1;
                          const p2Leader = stat.leader === 2;

                          const formatVal = (v: number, type: string) => {
                            if (type === "percent") return `${v.toFixed(1)}%`;
                            if (type === "float3") return v.toFixed(3);
                            if (type === "integer") return Math.round(v);
                            return v.toFixed(1);
                          };

                          return (
                            <tr key={stat.category_key} className="hover:bg-slate-50/80 transition">
                              {/* P1 Value */}
                              <td className="py-3 font-bold text-sm">
                                <span
                                  className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg ${
                                    p1Leader
                                      ? "bg-emerald-50 text-emerald-800 font-black border border-emerald-200 shadow-2xs"
                                      : "text-slate-600"
                                  }`}
                                >
                                  {p1Leader && <Check className="h-3.5 w-3.5 text-emerald-600" />}
                                  {formatVal(stat.p1_value, stat.format_type)}
                                </span>
                              </td>

                              {/* Stat Label */}
                              <td className="py-3 text-center font-sans font-extrabold text-slate-800">
                                {isEs ? stat.label_es : stat.label_en}
                              </td>

                              {/* P2 Value */}
                              <td className="py-3 text-right font-bold text-sm">
                                <span
                                  className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg ${
                                    p2Leader
                                      ? "bg-emerald-50 text-emerald-800 font-black border border-emerald-200 shadow-2xs"
                                      : "text-slate-600"
                                  }`}
                                >
                                  {formatVal(stat.p2_value, stat.format_type)}
                                  {p2Leader && <Check className="h-3.5 w-3.5 text-emerald-600" />}
                                </span>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* ========================================================================= */}
              {/* TAB 3: VITRINA DE TÍTULOS & PALMARÉS */}
              {/* ========================================================================= */}
              {activeTab === "accolades" && (
                <div className="rounded-3xl border border-slate-200/90 bg-white p-6 sm:p-8 shadow-xs space-y-6">
                  <div className="border-b border-slate-100 pb-4">
                    <h3 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
                      <Trophy className="h-5 w-5 text-amber-600" />
                      {isEs ? "Vitrina de Títulos, Anillos & Galardones Históricos" : "Career Championship Rings & Major Accolades"}
                    </h3>
                    <p className="text-xs text-slate-500 mt-0.5">
                      {isEs
                        ? "Comparativa de títulos colectivos e individuales a lo largo de toda la trayectoria."
                        : "Total career achievements, NBA championship rings, and individual accolades."}
                    </p>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {matchup.accolades_comparisons.map((acc) => {
                      const p1Lead = acc.leader === 1;
                      const p2Lead = acc.leader === 2;

                      return (
                        <div
                          key={acc.category_key}
                          className="rounded-2xl border border-slate-200 bg-slate-50/60 p-4 flex items-center justify-between shadow-2xs hover:bg-white hover:border-amber-300 transition"
                        >
                          <div className="flex items-center gap-3">
                            <div className="h-10 w-10 rounded-xl bg-amber-50 border border-amber-200 flex items-center justify-center shadow-2xs">
                              <Crown className="h-5 w-5 text-amber-600" />
                            </div>
                            <div>
                              <span className="text-xs font-black text-slate-900 block">
                                {isEs ? acc.label_es : acc.label_en}
                              </span>
                              <span className="text-[10px] text-slate-500 font-mono">
                                {acc.diff === 0
                                  ? isEs ? "Empate histórico" : "All-time Tie"
                                  : p1Lead
                                  ? `+${acc.diff} ${matchup.player1.player_name}`
                                  : `+${Math.abs(acc.diff)} ${matchup.player2.player_name}`}
                              </span>
                            </div>
                          </div>

                          <div className="flex items-center gap-2 font-mono">
                            <span
                              className={`px-3 py-1 rounded-xl text-sm font-black ${
                                p1Lead
                                  ? "bg-amber-100 text-amber-900 border border-amber-300 shadow-2xs"
                                  : "bg-white text-slate-600 border border-slate-200"
                              }`}
                            >
                              {acc.p1_value}
                            </span>
                            <span className="text-slate-400 font-bold">:</span>
                            <span
                              className={`px-3 py-1 rounded-xl text-sm font-black ${
                                p2Lead
                                  ? "bg-amber-100 text-amber-900 border border-amber-300 shadow-2xs"
                                  : "bg-white text-slate-600 border border-slate-200"
                              }`}
                            >
                              {acc.p2_value}
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* ========================================================================= */}
              {/* TAB 4: INFORME TÁCTICO DE SCOUTING */}
              {/* ========================================================================= */}
              {activeTab === "tactics" && (
                <div className="rounded-3xl border border-slate-200/90 bg-white p-6 sm:p-8 shadow-xs space-y-6">
                  <div>
                    <h3 className="text-xl font-extrabold text-slate-900 flex items-center gap-2 mb-3">
                      <Zap className="h-5 w-5 text-orange-600" />
                      {isEs ? "Diagnóstico & Claves del Simulador" : "Tactical Simulator Scouting Diagnosis"}
                    </h3>
                    <div className="rounded-2xl border border-slate-200 bg-slate-50/80 p-5 text-sm sm:text-base text-slate-800 leading-relaxed font-medium shadow-2xs">
                      {isEs ? matchup.simulation.tactical_summary_es : matchup.simulation.tactical_summary_en}
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {/* P1 Advantages */}
                    <div className="rounded-2xl border border-orange-200 bg-orange-50/40 p-5 shadow-2xs">
                      <h4 className="text-xs font-mono font-black text-orange-800 uppercase tracking-wider mb-3 flex items-center gap-2">
                        <Flame className="h-4 w-4 text-orange-600" />
                        {isEs ? `Ventajas Clave: ${matchup.player1.player_name}` : `Key Advantages: ${matchup.player1.player_name}`}
                      </h4>
                      <ul className="space-y-2 text-xs font-semibold text-slate-700">
                        {matchup.simulation.key_advantages_p1.map((adv, idx) => (
                          <li key={idx} className="flex items-start gap-2">
                            <CheckCircle2 className="h-4 w-4 text-orange-600 shrink-0 mt-0.5" />
                            <span>{adv}</span>
                          </li>
                        ))}
                      </ul>
                    </div>

                    {/* P2 Advantages */}
                    <div className="rounded-2xl border border-sky-200 bg-sky-50/40 p-5 shadow-2xs">
                      <h4 className="text-xs font-mono font-black text-sky-800 uppercase tracking-wider mb-3 flex items-center gap-2">
                        <Flame className="h-4 w-4 text-sky-600" />
                        {isEs ? `Ventajas Clave: ${matchup.player2.player_name}` : `Key Advantages: ${matchup.player2.player_name}`}
                      </h4>
                      <ul className="space-y-2 text-xs font-semibold text-slate-700">
                        {matchup.simulation.key_advantages_p2.map((adv, idx) => (
                          <li key={idx} className="flex items-start gap-2">
                            <CheckCircle2 className="h-4 w-4 text-sky-600 shrink-0 mt-0.5" />
                            <span>{adv}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </div>
              )}
            </>
          ) : null}
        </main>
      </div>
    </div>
  );
}
