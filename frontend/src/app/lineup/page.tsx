"use client";

import React, { useEffect, useState, useMemo } from "react";
import Image from "next/image";
import Link from "next/link";
import {
  Users,
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
  Play,
  RotateCcw,
  CheckCircle2,
  AlertTriangle,
  Layers,
  X,
} from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { CommandPalette } from "@/components/CommandPalette";
import { HorizontalCourt } from "@/components/HorizontalCourt";
import { MatchMomentumChart } from "@/components/MatchMomentumChart";
import {
  getVersusPlayers,
  getLineupPresets,
  evaluateLineup,
  simulate5v5Matchup,
  type VersusPlayerOption,
  type ClassicPresetLineup,
  type LineupSlotRequest,
  type LineupSlotDetail,
  type LineupTeamEvaluationResponse,
  type Lineup5v5SimulationResponse,
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

const POSITIONS = ["PG", "SG", "SF", "PF", "C"];

export default function LineupPage() {
  const { language, unitSystem, t } = usePreferences();
  const isEs = language === "es";

  const [allPlayers, setAllPlayers] = useState<VersusPlayerOption[]>([]);
  const [presets, setPresets] = useState<ClassicPresetLineup[]>([]);
  const [loadingInitial, setLoadingInitial] = useState<boolean>(true);
  const [isCommandOpen, setIsCommandOpen] = useState<boolean>(false);

  // Team 1 (Home) & Team 2 (Away) lineups
  const [team1Name, setTeam1Name] = useState<string>("USA All-Time Dream Team");
  const [team1SlotsReq, setTeam1SlotsReq] = useState<LineupSlotRequest[]>([]);
  const [team1Eval, setTeam1Eval] = useState<LineupTeamEvaluationResponse | null>(null);

  const [team2Name, setTeam2Name] = useState<string>("World All-Time Legends");
  const [team2SlotsReq, setTeam2SlotsReq] = useState<LineupSlotRequest[]>([]);
  const [team2Eval, setTeam2Eval] = useState<LineupTeamEvaluationResponse | null>(null);

  // Simulation state
  const [simulation, setSimulation] = useState<Lineup5v5SimulationResponse | null>(null);
  const [simulating, setSimulating] = useState<boolean>(false);

  // Player selection modal state
  const [modalOpen, setModalOpen] = useState<boolean>(false);
  const [selectedTeamSide, setSelectedTeamSide] = useState<1 | 2>(1);
  const [selectedPosition, setSelectedPosition] = useState<string>("PG");
  const [playerSearch, setPlayerSearch] = useState<string>("");
  const [modalPlayerId, setModalPlayerId] = useState<number | null>(null);
  const [modalSeasonId, setModalSeasonId] = useState<number | null>(null);

  // Active view tab: "chemistry" | "simulation" | "boxscore"
  const [activeTab, setActiveTab] = useState<"chemistry" | "simulation" | "boxscore">("chemistry");

  // Load catalog & initial presets
  useEffect(() => {
    async function loadData() {
      try {
        setLoadingInitial(true);
        const [playersData, presetsData] = await Promise.all([
          getVersusPlayers(),
          getLineupPresets(),
        ]);
        setAllPlayers(playersData);
        setPresets(presetsData);

        // Load Default Preset: USA Dream Team (t1) vs World Legends (t2)
        const usaPreset = presetsData.find((p) => p.id === "all_time_usa") || presetsData[0];
        const worldPreset = presetsData.find((p) => p.id === "all_time_world") || presetsData[1] || presetsData[0];

        if (usaPreset) {
          setTeam1Name(usaPreset.name);
          setTeam1SlotsReq(usaPreset.slots);
        }
        if (worldPreset) {
          setTeam2Name(worldPreset.name);
          setTeam2SlotsReq(worldPreset.slots);
        }
      } catch (err) {
        console.error("Error loading initial lineup data:", err);
      } finally {
        setLoadingInitial(false);
      }
    }
    loadData();
  }, []);

  // Re-evaluate Team 1 whenever its slots change
  useEffect(() => {
    if (team1SlotsReq.length === 0) {
      setTeam1Eval(null);
      return;
    }
    evaluateLineup({ team_name: team1Name, slots: team1SlotsReq })
      .then(setTeam1Eval)
      .catch(console.error);
  }, [team1SlotsReq, team1Name]);

  // Re-evaluate Team 2 whenever its slots change
  useEffect(() => {
    if (team2SlotsReq.length === 0) {
      setTeam2Eval(null);
      return;
    }
    evaluateLineup({ team_name: team2Name, slots: team2SlotsReq })
      .then(setTeam2Eval)
      .catch(console.error);
  }, [team2SlotsReq, team2Name]);

  // Run full 5v5 game simulation
  const handleSimulateGame = async () => {
    if (team1SlotsReq.length === 0 || team2SlotsReq.length === 0) return;
    try {
      setSimulating(true);
      const simRes = await simulate5v5Matchup(
        { team_name: team1Name, slots: team1SlotsReq },
        { team_name: team2Name, slots: team2SlotsReq }
      );
      setSimulation(simRes);
      setActiveTab("simulation");
    } catch (err) {
      console.error("Simulation failed:", err);
    } finally {
      setSimulating(false);
    }
  };

  // Quick Preset Loader
  const loadPresetIntoTeam = (preset: ClassicPresetLineup, teamIndex: 1 | 2) => {
    if (teamIndex === 1) {
      setTeam1Name(preset.name);
      setTeam1SlotsReq(preset.slots);
    } else {
      setTeam2Name(preset.name);
      setTeam2SlotsReq(preset.slots);
    }
  };

  // Slot click handler to open player picker modal
  const handleSlotClick = (teamIndex: 1 | 2, pos: string, currentSlot: LineupSlotDetail | null) => {
    setSelectedTeamSide(teamIndex);
    setSelectedPosition(pos);
    if (currentSlot) {
      setModalPlayerId(currentSlot.player_id);
      setModalSeasonId(currentSlot.season_id);
    } else {
      setModalPlayerId(null);
      setModalSeasonId(null);
    }
    setPlayerSearch("");
    setModalOpen(true);
  };

  // Remove player from slot
  const handleRemovePlayer = (teamIndex: 1 | 2, pos: string) => {
    if (teamIndex === 1) {
      setTeam1SlotsReq((prev) => prev.filter((s) => s.position !== pos));
    } else {
      setTeam2SlotsReq((prev) => prev.filter((s) => s.position !== pos));
    }
  };

  // Confirm player selection in modal
  const handleSaveModalSlot = () => {
    if (!modalPlayerId) return;

    const newSlot: LineupSlotRequest = {
      position: selectedPosition,
      player_id: modalPlayerId,
      season_id: modalSeasonId || undefined,
    };

    if (selectedTeamSide === 1) {
      setTeam1SlotsReq((prev) => {
        const filtered = prev.filter((s) => s.position !== selectedPosition);
        return [...filtered, newSlot];
      });
    } else {
      setTeam2SlotsReq((prev) => {
        const filtered = prev.filter((s) => s.position !== selectedPosition);
        return [...filtered, newSlot];
      });
    }
    setModalOpen(false);
  };

  // Selected player object in modal
  const selectedModalPlayer = useMemo(() => {
    return allPlayers.find((p) => p.player_id === modalPlayerId) || null;
  }, [allPlayers, modalPlayerId]);

  // Filtered players list in modal
  const filteredModalPlayers = useMemo(() => {
    if (!playerSearch.trim()) return allPlayers.slice(0, 10);
    const q = cleanStr(playerSearch);
    return allPlayers
      .filter((p) => cleanStr(p.player_name).includes(q) || cleanStr(p.team_abbreviation).includes(q))
      .slice(0, 15);
  }, [allPlayers, playerSearch]);

  return (
    <div className="min-h-screen bg-[#F8FAFC] text-slate-900 selection:bg-orange-100 selection:text-orange-900">
      <Navbar onOpenSearch={() => setIsCommandOpen(true)} />

      <CommandPalette
        isOpen={isCommandOpen}
        onClose={() => setIsCommandOpen(false)}
      />

      <div className="md:pl-64">
        {/* ========================================================================= */}
        {/* HERO SECTION */}
        {/* ========================================================================= */}
        <section className="relative border-b border-slate-200 bg-gradient-to-b from-orange-50/40 via-white to-white py-12 lg:py-14 shadow-xs">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="flex flex-col items-center text-center space-y-4">
              
              {/* Badge Pill */}
              <div className="inline-flex items-center gap-2 rounded-full border border-orange-200 bg-orange-50 px-4 py-1 text-xs font-black text-orange-800 shadow-2xs">
                <Users className="h-3.5 w-3.5 text-orange-600" />
                <span>{isEs ? "ARMADOR 5 VS 5 • EQUIPOS FANTASÍA & SIMULADOR" : "5 VS 5 LINEUP ARENA • FANTASY TEAMS & SIMULATOR"}</span>
              </div>

              {/* Title */}
              <h1 className="max-w-4xl text-3xl sm:text-5xl font-black tracking-tight text-slate-900 leading-tight">
                {isEs ? "Cancha Táctica & Duelo de Quintetos" : "Tactical Court & 5v5 Lineup Battles"}
              </h1>

              <p className="max-w-3xl text-sm sm:text-base text-slate-600 font-normal leading-relaxed">
                {isEs
                  ? "Armá quintetos históricos combinando cualquier jugador y temporada sobre la duela oficial. El motor analiza química, espaciado y simula partidos completos de 48 minutos con Box Score."
                  : "Build dream lineups mixing any player and season on the interactive full court. The AI engine evaluates spacing, chemistry, and simulates full 48-minute games with complete Box Scores."}
              </p>

              {/* Preset Teams Bar */}
              <div className="pt-2 w-full max-w-5xl">
                <div className="flex items-center justify-center gap-1.5 text-xs font-mono font-bold uppercase tracking-wider text-slate-500 mb-2">
                  <Crown className="h-3.5 w-3.5 text-amber-500" />
                  <span>{isEs ? "Cargar Quintetos Históricos:" : "Load Classic Preset Lineups:"}</span>
                </div>
                <div className="flex flex-wrap items-center justify-center gap-2">
                  {presets.map((preset) => (
                    <div key={preset.id} className="inline-flex rounded-xl border border-slate-200 bg-white p-1 shadow-2xs">
                      <span className="px-2 py-1 text-xs font-black text-slate-800 self-center">
                        {preset.name}
                      </span>
                      <div className="flex gap-1">
                        <button
                          onClick={() => loadPresetIntoTeam(preset, 1)}
                          className="rounded-lg bg-orange-50 hover:bg-orange-600 hover:text-white px-2 py-1 text-[10px] font-black text-orange-700 transition"
                          title={isEs ? "Cargar en Equipo 1" : "Load in Team 1"}
                        >
                          T1 (Local)
                        </button>
                        <button
                          onClick={() => loadPresetIntoTeam(preset, 2)}
                          className="rounded-lg bg-sky-50 hover:bg-sky-600 hover:text-white px-2 py-1 text-[10px] font-black text-sky-700 transition"
                          title={isEs ? "Cargar en Equipo 2" : "Load in Team 2"}
                        >
                          T2 (Visita)
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

            </div>
          </div>
        </section>

        {/* ========================================================================= */}
        {/* MAIN COURT & TEAM INTERACTION SECTION */}
        {/* ========================================================================= */}
        <main className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-8 space-y-8">
          
          {/* Team Headers & Names */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Team 1 Control */}
            <div className="rounded-2xl border border-orange-200 bg-white p-4 shadow-xs flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className="h-3.5 w-3.5 rounded-full bg-orange-500" />
                <input
                  type="text"
                  value={team1Name}
                  onChange={(e) => setTeam1Name(e.target.value)}
                  className="font-black text-base sm:text-lg text-slate-900 border-b border-transparent hover:border-orange-300 focus:border-orange-500 focus:outline-none bg-transparent"
                />
              </div>
              <button
                onClick={() => setTeam1SlotsReq([])}
                className="rounded-lg bg-slate-100 hover:bg-rose-50 hover:text-rose-700 px-2.5 py-1 text-xs font-bold text-slate-600 transition"
                title={isEs ? "Vaciar equipo" : "Clear lineup"}
              >
                <RotateCcw className="h-3.5 w-3.5" />
              </button>
            </div>

            {/* Team 2 Control */}
            <div className="rounded-2xl border border-sky-200 bg-white p-4 shadow-xs flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className="h-3.5 w-3.5 rounded-full bg-sky-500" />
                <input
                  type="text"
                  value={team2Name}
                  onChange={(e) => setTeam2Name(e.target.value)}
                  className="font-black text-base sm:text-lg text-slate-900 border-b border-transparent hover:border-sky-300 focus:border-sky-500 focus:outline-none bg-transparent"
                />
              </div>
              <button
                onClick={() => setTeam2SlotsReq([])}
                className="rounded-lg bg-slate-100 hover:bg-rose-50 hover:text-rose-700 px-2.5 py-1 text-xs font-bold text-slate-600 transition"
                title={isEs ? "Vaciar equipo" : "Clear lineup"}
              >
                <RotateCcw className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>

          {/* HORIZONTAL FULL COURT COMPONENT */}
          <HorizontalCourt
            team1Slots={team1Eval?.slots || []}
            team2Slots={team2Eval?.slots || []}
            team1Name={team1Name}
            team2Name={team2Name}
            onSlotClick={handleSlotClick}
            onRemovePlayer={handleRemovePlayer}
            language={language}
          />

          {/* SIMULATION ACTION BUTTON */}
          <div className="flex justify-center pt-2">
            <button
              onClick={handleSimulateGame}
              disabled={simulating || (team1Eval?.slots.length || 0) < 1 || (team2Eval?.slots.length || 0) < 1}
              className={`flex items-center gap-3 rounded-2xl px-8 py-4 text-base font-black uppercase tracking-wider text-white shadow-lg transition transform hover:scale-105 active:scale-95 ${
                simulating || (team1Eval?.slots.length || 0) < 1 || (team2Eval?.slots.length || 0) < 1
                  ? "bg-slate-300 cursor-not-allowed"
                  : "bg-gradient-to-r from-orange-600 to-amber-600 hover:from-orange-500 hover:to-amber-500"
              }`}
            >
              {simulating ? (
                <>
                  <Swords className="h-6 w-6 animate-spin" />
                  <span>{isEs ? "Simulando 48 Minutos..." : "Simulating 48 Minutes..."}</span>
                </>
              ) : (
                <>
                  <Play className="h-6 w-6 fill-white" />
                  <span>{isEs ? "Simular Partido 5 vs 5" : "Simulate 5 vs 5 Game"}</span>
                </>
              )}
            </button>
          </div>

          {/* ========================================================================= */}
          {/* ANALYSIS & SIMULATION TABS */}
          {/* ========================================================================= */}
          <div className="flex flex-wrap items-center justify-center gap-2 pt-4">
            <button
              onClick={() => setActiveTab("chemistry")}
              className={`flex items-center gap-2 rounded-2xl px-5 py-2.5 text-xs font-black transition ${
                activeTab === "chemistry"
                  ? "bg-orange-600 text-white shadow-xs"
                  : "bg-white border border-slate-200 text-slate-600 hover:bg-slate-50 hover:text-slate-900"
              }`}
            >
              <Activity className="h-4 w-4" />
              {isEs ? "Química, Spacing & Ratings" : "Lineup Chemistry & Ratings"}
            </button>

            <button
              onClick={() => setActiveTab("simulation")}
              className={`flex items-center gap-2 rounded-2xl px-5 py-2.5 text-xs font-black transition ${
                activeTab === "simulation"
                  ? "bg-orange-600 text-white shadow-xs"
                  : "bg-white border border-slate-200 text-slate-600 hover:bg-slate-50 hover:text-slate-900"
              }`}
            >
              <Swords className="h-4 w-4" />
              {isEs ? "Resultado de Partido 5v5" : "5v5 Game Result"}
            </button>

            <button
              onClick={() => setActiveTab("boxscore")}
              className={`flex items-center gap-2 rounded-2xl px-5 py-2.5 text-xs font-black transition ${
                activeTab === "boxscore"
                  ? "bg-orange-600 text-white shadow-xs"
                  : "bg-white border border-slate-200 text-slate-600 hover:bg-slate-50 hover:text-slate-900"
              }`}
            >
              <Target className="h-4 w-4" />
              {isEs ? "Box Score Proyectado Completo" : "Simulated Full Box Score"}
            </button>
          </div>

          {/* ========================================================================= */}
          {/* TAB 1: CHEMISTRY & LINEUP RATINGS */}
          {/* ========================================================================= */}
          {activeTab === "chemistry" && team1Eval && team2Eval && (
            <div className="rounded-3xl border border-slate-200/90 bg-white p-6 sm:p-8 shadow-xs space-y-6">
              <div className="border-b border-slate-100 pb-4 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                <div>
                  <h3 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
                    <Activity className="h-5 w-5 text-orange-600" />
                    {isEs ? "Evaluación Comparativa de Quintetos" : "Head-to-Head Lineup Ratings & Chemistry"}
                  </h3>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {isEs
                      ? "Proyección estadística de eficiencia ofensiva, solidez defensiva y compatibilidad de arquetipos."
                      : "Projected offensive efficiency, defensive solidity, and archetype synergy."}
                  </p>
                </div>
                <div className="flex items-center gap-4 text-xs font-mono font-black">
                  <span className="flex items-center gap-1.5 text-orange-600">
                    <span className="h-3 w-3 rounded-md bg-orange-500" />
                    {team1Name}
                  </span>
                  <span className="flex items-center gap-1.5 text-sky-600">
                    <span className="h-3 w-3 rounded-md bg-sky-500" />
                    {team2Name}
                  </span>
                </div>
              </div>

              {/* Metrics Grid */}
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                {/* ORTG */}
                <div className="rounded-2xl border border-slate-100 bg-slate-50/70 p-4">
                  <span className="text-[10px] font-mono font-bold uppercase text-slate-400 block mb-1">
                    Offensive Rating (ORTG)
                  </span>
                  <div className="flex items-center justify-between">
                    <span className="text-xl font-black text-orange-600">{team1Eval.metrics.ortg}</span>
                    <span className="text-xs font-mono text-slate-400">vs</span>
                    <span className="text-xl font-black text-sky-600">{team2Eval.metrics.ortg}</span>
                  </div>
                </div>

                {/* DRTG */}
                <div className="rounded-2xl border border-slate-100 bg-slate-50/70 p-4">
                  <span className="text-[10px] font-mono font-bold uppercase text-slate-400 block mb-1">
                    Defensive Rating (DRTG)
                  </span>
                  <div className="flex items-center justify-between">
                    <span className="text-xl font-black text-orange-600">{team1Eval.metrics.drtg}</span>
                    <span className="text-xs font-mono text-slate-400">vs</span>
                    <span className="text-xl font-black text-sky-600">{team2Eval.metrics.drtg}</span>
                  </div>
                </div>

                {/* Spacing */}
                <div className="rounded-2xl border border-slate-100 bg-slate-50/70 p-4">
                  <span className="text-[10px] font-mono font-bold uppercase text-slate-400 block mb-1">
                    {isEs ? "Espaciado Ofensivo (0-100)" : "Floor Spacing (0-100)"}
                  </span>
                  <div className="flex items-center justify-between">
                    <span className="text-xl font-black text-orange-600">{team1Eval.metrics.spacing_score}</span>
                    <span className="text-xs font-mono text-slate-400">vs</span>
                    <span className="text-xl font-black text-sky-600">{team2Eval.metrics.spacing_score}</span>
                  </div>
                </div>

                {/* Chemistry */}
                <div className="rounded-2xl border border-slate-100 bg-slate-50/70 p-4">
                  <span className="text-[10px] font-mono font-bold uppercase text-slate-400 block mb-1">
                    {isEs ? "Química & Sinergia (0-100)" : "Synergy & Chemistry (0-100)"}
                  </span>
                  <div className="flex items-center justify-between">
                    <span className="text-xl font-black text-orange-600">{team1Eval.metrics.chemistry_score}</span>
                    <span className="text-xs font-mono text-slate-400">vs</span>
                    <span className="text-xl font-black text-sky-600">{team2Eval.metrics.chemistry_score}</span>
                  </div>
                </div>
              </div>

              {/* Strengths & Weaknesses comparison */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-2">
                {/* Team 1 Notes */}
                <div className="rounded-2xl border border-orange-200 bg-orange-50/40 p-5 shadow-2xs space-y-3">
                  <h4 className="font-mono text-xs font-black text-orange-800 uppercase tracking-wider flex items-center gap-2">
                    <Flame className="h-4 w-4 text-orange-600" />
                    {team1Name} — {isEs ? "Diagnóstico Táctico" : "Tactical Diagnosis"}
                  </h4>
                  <ul className="space-y-1.5 text-xs font-semibold text-slate-700">
                    {(isEs ? team1Eval.metrics.synergy_strengths_es : team1Eval.metrics.synergy_strengths_en).map((s, i) => (
                      <li key={i} className="flex items-start gap-2">
                        <CheckCircle2 className="h-4 w-4 text-orange-600 shrink-0 mt-0.5" />
                        <span>{s}</span>
                      </li>
                    ))}
                    {(isEs ? team1Eval.metrics.synergy_weaknesses_es : team1Eval.metrics.synergy_weaknesses_en).map((w, i) => (
                      <li key={i} className="flex items-start gap-2 text-amber-900">
                        <AlertTriangle className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
                        <span>{w}</span>
                      </li>
                    ))}
                  </ul>
                </div>

                {/* Team 2 Notes */}
                <div className="rounded-2xl border border-sky-200 bg-sky-50/40 p-5 shadow-2xs space-y-3">
                  <h4 className="font-mono text-xs font-black text-sky-800 uppercase tracking-wider flex items-center gap-2">
                    <Flame className="h-4 w-4 text-sky-600" />
                    {team2Name} — {isEs ? "Diagnóstico Táctico" : "Tactical Diagnosis"}
                  </h4>
                  <ul className="space-y-1.5 text-xs font-semibold text-slate-700">
                    {(isEs ? team2Eval.metrics.synergy_strengths_es : team2Eval.metrics.synergy_strengths_en).map((s, i) => (
                      <li key={i} className="flex items-start gap-2">
                        <CheckCircle2 className="h-4 w-4 text-sky-600 shrink-0 mt-0.5" />
                        <span>{s}</span>
                      </li>
                    ))}
                    {(isEs ? team2Eval.metrics.synergy_weaknesses_es : team2Eval.metrics.synergy_weaknesses_en).map((w, i) => (
                      <li key={i} className="flex items-start gap-2 text-amber-900">
                        <AlertTriangle className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
                        <span>{w}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          )}

          {/* ========================================================================= */}
          {/* TAB 2: SIMULATION RESULTS */}
          {/* ========================================================================= */}
          {activeTab === "simulation" && (
            <div className="space-y-6">
              {simulation ? (
                <div className="rounded-3xl border border-slate-200/90 bg-white p-6 sm:p-8 shadow-xs space-y-6">
                  {/* Scoreboard Billboard */}
                  <div className="rounded-2xl border border-slate-200 bg-gradient-to-r from-orange-50/60 via-white to-sky-50/60 p-6 text-center shadow-xs">
                    <span className="text-[11px] font-mono font-black uppercase tracking-widest text-slate-400 block mb-2">
                      {isEs ? "MARCADOR FINAL PROYECTADO A 48 MINUTOS" : "PROJECTED FINAL 48-MINUTE SCORE"}
                    </span>
                    <div className="flex items-center justify-center gap-6 sm:gap-12">
                      <div className="text-right">
                        <span className="block font-sans text-base sm:text-xl font-black text-orange-900">{simulation.team1_name}</span>
                        <span className="font-mono text-4xl sm:text-6xl font-black text-orange-600">{simulation.team1_score}</span>
                      </div>
                      <span className="text-3xl font-mono text-slate-300">-</span>
                      <div className="text-left">
                        <span className="block font-sans text-base sm:text-xl font-black text-sky-900">{simulation.team2_name}</span>
                        <span className="font-mono text-4xl sm:text-6xl font-black text-sky-600">{simulation.team2_score}</span>
                      </div>
                    </div>

                    {/* Win Prob Bar */}
                    <div className="max-w-md mx-auto mt-4">
                      <div className="flex justify-between text-xs font-mono font-black mb-1">
                        <span className="text-orange-600">{simulation.team1_win_prob}%</span>
                        <span className="text-sky-600">{simulation.team2_win_prob}%</span>
                      </div>
                      <div className="h-3 w-full rounded-full bg-slate-100 overflow-hidden flex border border-slate-200">
                        <div
                          className="h-full bg-gradient-to-r from-orange-500 to-amber-500 transition-all duration-700"
                          style={{ width: `${simulation.team1_win_prob}%` }}
                        />
                        <div
                          className="h-full bg-gradient-to-l from-sky-500 to-blue-500 transition-all duration-700"
                          style={{ width: `${simulation.team2_win_prob}%` }}
                        />
                      </div>
                    </div>
                  </div>

                  {/* Quarter by Quarter Breakdown Table */}
                  <div className="overflow-x-auto">
                    <table className="w-full text-center text-xs font-mono">
                      <thead>
                        <tr className="border-b border-slate-200 text-slate-400 uppercase text-[10px]">
                          <th className="pb-2 text-left text-slate-700 font-bold">Equipo</th>
                          <th className="pb-2">Q1</th>
                          <th className="pb-2">Q2</th>
                          <th className="pb-2">Q3</th>
                          <th className="pb-2">Q4</th>
                          <th className="pb-2 font-black text-slate-900">Total</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        <tr>
                          <td className="py-2.5 text-left font-black text-orange-700">{simulation.team1_name}</td>
                          <td className="py-2.5">{simulation.quarter_scores_t1[0]}</td>
                          <td className="py-2.5">{simulation.quarter_scores_t1[1]}</td>
                          <td className="py-2.5">{simulation.quarter_scores_t1[2]}</td>
                          <td className="py-2.5">{simulation.quarter_scores_t1[3]}</td>
                          <td className="py-2.5 font-black text-orange-600 text-sm">{simulation.team1_score}</td>
                        </tr>
                        <tr>
                          <td className="py-2.5 text-left font-black text-sky-700">{simulation.team2_name}</td>
                          <td className="py-2.5">{simulation.quarter_scores_t2[0]}</td>
                          <td className="py-2.5">{simulation.quarter_scores_t2[1]}</td>
                          <td className="py-2.5">{simulation.quarter_scores_t2[2]}</td>
                          <td className="py-2.5">{simulation.quarter_scores_t2[3]}</td>
                          <td className="py-2.5 font-black text-sky-600 text-sm">{simulation.team2_score}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>

                  {/* 48-Minute Match Momentum Timeline Chart */}
                  {simulation.momentum_timeline && (
                    <div className="pt-2">
                      <MatchMomentumChart timeline={simulation.momentum_timeline} />
                    </div>
                  )}

                  {/* MVP Badge */}
                  <div className="rounded-2xl border border-amber-200 bg-amber-50/60 p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-2xs">
                    <div className="flex items-center gap-3">
                      <div className="h-10 w-10 rounded-xl bg-amber-500 text-white flex items-center justify-center shadow-xs">
                        <Crown className="h-5 w-5 fill-white" />
                      </div>
                      <div>
                        <span className="text-[10px] font-mono font-bold uppercase text-amber-800 block">
                          MVP DEL PARTIDO
                        </span>
                        <span className="text-base font-black text-slate-900">{simulation.game_mvp_name}</span>
                      </div>
                    </div>
                    <span className="rounded-xl border border-amber-300 bg-white px-3 py-1 font-mono text-xs font-black text-amber-900 shadow-2xs">
                      {simulation.game_mvp_stats}
                    </span>
                  </div>

                  {/* Tactical Summary */}
                  <div className="rounded-2xl border border-slate-200 bg-slate-50/80 p-5 text-xs sm:text-sm text-slate-800 leading-relaxed font-medium shadow-2xs">
                    {isEs ? simulation.tactical_summary_es : simulation.tactical_summary_en}
                  </div>
                </div>
              ) : (
                <div className="rounded-3xl border border-slate-200 bg-white p-12 text-center text-slate-500 shadow-xs">
                  <Play className="h-8 w-8 text-orange-500 mx-auto mb-3" />
                  <p className="font-bold text-sm">
                    {isEs
                      ? "Hacé clic en 'Simular Partido 5 vs 5' para proyectar el resultado del encuentro."
                      : "Click 'Simulate 5 vs 5 Game' above to generate the projected outcome."}
                  </p>
                </div>
              )}
            </div>
          )}

          {/* ========================================================================= */}
          {/* TAB 3: BOX SCORE SIMULADO COMPLETO */}
          {/* ========================================================================= */}
          {activeTab === "boxscore" && (
            <div className="space-y-6">
              {simulation ? (
                <>
                  {/* Team 1 Box Score */}
                  <div className="rounded-3xl border border-orange-100 bg-white p-6 shadow-xs space-y-4">
                    <h4 className="font-black text-base text-orange-800 flex items-center gap-2">
                      <span className="h-3 w-3 rounded-full bg-orange-500" />
                      {simulation.team1_name} — Box Score
                    </h4>
                    <div className="overflow-x-auto">
                      <table className="w-full text-right text-xs font-mono">
                        <thead>
                          <tr className="border-b border-slate-200 text-slate-400 uppercase text-[10px]">
                            <th className="pb-2 text-left text-slate-700 font-bold">Jugador</th>
                            <th className="pb-2">POS</th>
                            <th className="pb-2">MIN</th>
                            <th className="pb-2 font-black text-slate-900">PTS</th>
                            <th className="pb-2">REB</th>
                            <th className="pb-2">AST</th>
                            <th className="pb-2">ROB</th>
                            <th className="pb-2">TAP</th>
                            <th className="pb-2">TC</th>
                            <th className="pb-2">3PT</th>
                            <th className="pb-2">+/-</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100">
                          {simulation.team1_boxscore.map((b) => (
                            <tr key={b.player_id} className="hover:bg-slate-50/80 transition">
                              <td className="py-2.5 text-left font-sans font-black text-slate-900">{b.player_name}</td>
                              <td className="py-2.5 font-bold text-orange-700">{b.position}</td>
                              <td className="py-2.5 text-slate-500">{b.minutes}</td>
                              <td className="py-2.5 font-black text-orange-600 text-sm">{b.pts}</td>
                              <td className="py-2.5">{b.reb}</td>
                              <td className="py-2.5">{b.ast}</td>
                              <td className="py-2.5">{b.stl}</td>
                              <td className="py-2.5">{b.blk}</td>
                              <td className="py-2.5">{b.fgm}/{b.fga}</td>
                              <td className="py-2.5">{b.fg3m}/{b.fg3a}</td>
                              <td className={`py-2.5 font-bold ${b.plus_minus >= 0 ? "text-emerald-600" : "text-rose-600"}`}>
                                {b.plus_minus > 0 ? `+${b.plus_minus}` : b.plus_minus}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  {/* Team 2 Box Score */}
                  <div className="rounded-3xl border border-sky-100 bg-white p-6 shadow-xs space-y-4">
                    <h4 className="font-black text-base text-sky-800 flex items-center gap-2">
                      <span className="h-3 w-3 rounded-full bg-sky-500" />
                      {simulation.team2_name} — Box Score
                    </h4>
                    <div className="overflow-x-auto">
                      <table className="w-full text-right text-xs font-mono">
                        <thead>
                          <tr className="border-b border-slate-200 text-slate-400 uppercase text-[10px]">
                            <th className="pb-2 text-left text-slate-700 font-bold">Jugador</th>
                            <th className="pb-2">POS</th>
                            <th className="pb-2">MIN</th>
                            <th className="pb-2 font-black text-slate-900">PTS</th>
                            <th className="pb-2">REB</th>
                            <th className="pb-2">AST</th>
                            <th className="pb-2">ROB</th>
                            <th className="pb-2">TAP</th>
                            <th className="pb-2">TC</th>
                            <th className="pb-2">3PT</th>
                            <th className="pb-2">+/-</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100">
                          {simulation.team2_boxscore.map((b) => (
                            <tr key={b.player_id} className="hover:bg-slate-50/80 transition">
                              <td className="py-2.5 text-left font-sans font-black text-slate-900">{b.player_name}</td>
                              <td className="py-2.5 font-bold text-sky-700">{b.position}</td>
                              <td className="py-2.5 text-slate-500">{b.minutes}</td>
                              <td className="py-2.5 font-black text-sky-600 text-sm">{b.pts}</td>
                              <td className="py-2.5">{b.reb}</td>
                              <td className="py-2.5">{b.ast}</td>
                              <td className="py-2.5">{b.stl}</td>
                              <td className="py-2.5">{b.blk}</td>
                              <td className="py-2.5">{b.fgm}/{b.fga}</td>
                              <td className="py-2.5">{b.fg3m}/{b.fg3a}</td>
                              <td className={`py-2.5 font-bold ${b.plus_minus >= 0 ? "text-emerald-600" : "text-rose-600"}`}>
                                {b.plus_minus > 0 ? `+${b.plus_minus}` : b.plus_minus}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </>
              ) : (
                <div className="rounded-3xl border border-slate-200 bg-white p-12 text-center text-slate-500 shadow-xs">
                  <Play className="h-8 w-8 text-orange-500 mx-auto mb-3" />
                  <p className="font-bold text-sm">
                    {isEs
                      ? "Ejecutá la simulación para visualizar el Box Score detallado con minutos y tiros anotados."
                      : "Run the simulation to inspect the projected Box Score with minutes and shot breakdowns."}
                  </p>
                </div>
              )}
            </div>
          )}

        </main>
      </div>

      {/* ========================================================================= */}
      {/* PLAYER PICKER MODAL */}
      {/* ========================================================================= */}
      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-xs animate-fadeIn">
          <div className="w-full max-w-xl rounded-3xl border border-slate-200 bg-white p-6 shadow-2xl space-y-4">
            
            {/* Modal Header */}
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <span className={`h-3 w-3 rounded-full ${selectedTeamSide === 1 ? "bg-orange-500" : "bg-sky-500"}`} />
                <h3 className="text-lg font-black text-slate-900">
                  {isEs ? `Asignar ${selectedPosition} en ${selectedTeamSide === 1 ? team1Name : team2Name}` : `Assign ${selectedPosition} to ${selectedTeamSide === 1 ? team1Name : team2Name}`}
                </h3>
              </div>
              <button
                onClick={() => setModalOpen(false)}
                className="rounded-full p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* Search Input */}
            <div className="relative">
              <Search className="absolute left-3.5 top-3 h-4 w-4 text-slate-400" />
              <input
                type="text"
                placeholder={isEs ? "Buscar jugador por nombre o franquicia..." : "Search player by name or team..."}
                value={playerSearch}
                onChange={(e) => setPlayerSearch(e.target.value)}
                className="w-full rounded-2xl border border-slate-200 bg-slate-50/80 py-2.5 pl-10 pr-4 text-xs font-bold text-slate-900 placeholder:text-slate-400 focus:border-orange-500 focus:bg-white focus:outline-none"
                autoFocus
              />
            </div>

            {/* Players List Grid */}
            <div className="max-h-60 overflow-y-auto space-y-1.5 pr-1">
              {filteredModalPlayers.map((p) => {
                const isSelected = p.player_id === modalPlayerId;
                return (
                  <div
                    key={p.player_id}
                    onClick={() => {
                      setModalPlayerId(p.player_id);
                      setModalSeasonId(p.best_season_id);
                    }}
                    className={`flex items-center justify-between rounded-xl px-3.5 py-2 cursor-pointer text-xs transition ${
                      isSelected
                        ? "bg-orange-600 text-white font-black"
                        : "bg-slate-50 hover:bg-slate-100 text-slate-800 font-bold"
                    }`}
                  >
                    <div className="flex items-center gap-2.5">
                      <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${isSelected ? "bg-orange-700 text-white" : "bg-slate-200 text-slate-700"}`}>
                        {p.team_abbreviation}
                      </span>
                      <span>{p.player_name}</span>
                    </div>
                    <span className={`text-[10px] font-mono ${isSelected ? "text-orange-100" : "text-amber-600"}`}>
                      Peak: {p.best_season_label}
                    </span>
                  </div>
                );
              })}
            </div>

            {/* Season Picker for Selected Player */}
            {selectedModalPlayer && (
              <div className="pt-2 border-t border-slate-100">
                <label className="block text-[11px] font-mono font-bold uppercase text-slate-500 mb-1">
                  {isEs ? "Temporada a Utilizar:" : "Season to Use:"}
                </label>
                <select
                  value={modalSeasonId || selectedModalPlayer.best_season_id}
                  onChange={(e) => setModalSeasonId(Number(e.target.value))}
                  className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-bold text-slate-800 focus:border-orange-500 focus:outline-none"
                >
                  {selectedModalPlayer.seasons.map((s) => (
                    <option key={s.season_id} value={s.season_id}>
                      {s.season_label} ({s.team_abbreviation}) — {s.pts_pg} PPG, {s.reb_pg} RPG, {s.ast_pg} APG{" "}
                      {s.is_best_season ? "⭐ [PEAK]" : ""}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {/* Modal Actions */}
            <div className="flex justify-end gap-2 pt-3 border-t border-slate-100">
              <button
                onClick={() => setModalOpen(false)}
                className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-bold text-slate-600 hover:bg-slate-50"
              >
                {isEs ? "Cancelar" : "Cancel"}
              </button>
              <button
                onClick={handleSaveModalSlot}
                disabled={!modalPlayerId}
                className="rounded-xl bg-orange-600 px-5 py-2 text-xs font-black text-white shadow-xs hover:bg-orange-700 disabled:opacity-50"
              >
                {isEs ? "Confirmar Jugador" : "Confirm Player"}
              </button>
            </div>

          </div>
        </div>
      )}

    </div>
  );
}
