"use client";

import React, { useEffect, useState, useMemo } from "react";
import Image from "next/image";
import Link from "next/link";
import {
  Dumbbell,
  Target,
  TrendingUp,
  Zap,
  Shield,
  Flame,
  Sparkles,
  Activity,
  CheckCircle2,
  AlertTriangle,
  Search,
  ChevronDown,
  Layers,
  Award,
  Clock,
  Check,
  BarChart3,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
  Sparkle,
} from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { TrainingTriRadar } from "@/components/TrainingTriRadar";
import {
  getTrainingAnalysis,
  getSeasons,
  getPlayers,
  type TrainingAnalysisResponse,
  type SeasonItem,
  type PlayerListItem,
  type DrillRecommendation,
  type StatGapItem,
} from "@/lib/api";
import { usePreferences } from "@/context/PreferencesContext";

const PRESET_PLAYERS = [
  { name: "Stephen Curry", season: "2015-16", label: "Curry '16 (PG)", pos: "PG" },
  { name: "Nikola Jokic", season: "2023-24", label: "Jokic '24 (C)", pos: "C" },
  { name: "LeBron James", season: "2012-13", label: "LeBron '13 (SF)", pos: "SF" },
  { name: "Kawhi Leonard", season: "2018-19", label: "Kawhi '19 (SF)", pos: "SF" },
  { name: "Anthony Edwards", season: "2023-24", label: "Edwards '24 (SG)", pos: "SG" },
  { name: "Giannis Antetokounmpo", season: "2019-20", label: "Giannis '20 (PF)", pos: "PF" },
];

export default function TrainingCampPage() {
  const { t, language } = usePreferences();

  // State
  const [selectedPlayer, setSelectedPlayer] = useState<string>("Stephen Curry");
  const [selectedSeasonId, setSelectedSeasonId] = useState<number | undefined>(undefined);
  const [activeRegimeId, setActiveRegimeId] = useState<string>("balanced");
  const [trainingIntensity, setTrainingIntensity] = useState<string>("high");

  const [analysis, setAnalysis] = useState<TrainingAnalysisResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const [seasons, setSeasons] = useState<SeasonItem[]>([]);
  const [allPlayers, setAllPlayers] = useState<PlayerListItem[]>([]);
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [isSearchOpen, setIsSearchOpen] = useState<boolean>(false);

  // Load Seasons and Player Catalog
  useEffect(() => {
    async function initCatalog() {
      try {
        const [seasonData, playersData] = await Promise.all([
          getSeasons().catch(() => []),
          getPlayers().catch(() => []),
        ]);
        setSeasons(seasonData);
        setAllPlayers(playersData);
        if (seasonData.length > 0 && selectedSeasonId === undefined) {
          const activeS = seasonData.find((s) => s.is_active) || seasonData[0];
          setSelectedSeasonId(activeS.id);
        }
      } catch (err) {
        console.error("Failed to load catalog:", err);
      }
    }
    initCatalog();
  }, []);

  // Fetch Training Analysis
  useEffect(() => {
    let isCancelled = false;
    async function loadAnalysis() {
      setLoading(true);
      setError(null);
      try {
        const res = await getTrainingAnalysis(
          selectedPlayer,
          selectedSeasonId,
          trainingIntensity
        );
        if (!isCancelled) {
          setAnalysis(res);
        }
      } catch (err: any) {
        if (!isCancelled) {
          setError(err?.message || "No se pudo cargar el análisis de entrenamiento");
        }
      } finally {
        if (!isCancelled) {
          setLoading(false);
        }
      }
    }

    if (selectedPlayer) {
      loadAnalysis();
    }

    return () => {
      isCancelled = true;
    };
  }, [selectedPlayer, selectedSeasonId, trainingIntensity]);

  // Filtered Players for Autocomplete
  const filteredPlayers = useMemo(() => {
    if (!searchQuery.trim()) return allPlayers.slice(0, 10);
    const q = searchQuery.toLowerCase();
    return allPlayers
      .filter((p) => p.player_name.toLowerCase().includes(q))
      .slice(0, 12);
  }, [allPlayers, searchQuery]);

  // Active Regime Plan
  const currentRegime = useMemo(() => {
    if (!analysis || !analysis.training_regimes) return null;
    return (
      analysis.training_regimes.find((r) => r.regime_id === activeRegimeId) ||
      analysis.training_regimes[0]
    );
  }, [analysis, activeRegimeId]);

  // Grade color helper
  const getGradeBadge = (grade: string) => {
    if (grade.startsWith("A")) {
      return "border-emerald-300 bg-emerald-50 text-emerald-700 ring-emerald-200";
    }
    if (grade.startsWith("B")) {
      return "border-sky-300 bg-sky-50 text-sky-700 ring-sky-200";
    }
    if (grade.startsWith("C")) {
      return "border-amber-300 bg-amber-50 text-amber-700 ring-amber-200";
    }
    return "border-rose-300 bg-rose-50 text-rose-700 ring-rose-200";
  };

  const getStatusBadge = (status: StatGapItem["status"]) => {
    switch (status) {
      case "elite":
        return {
          label: language === "es" ? "Élite (+40%)" : "Elite (+40%)",
          classes: "border-purple-200 bg-purple-50 text-purple-700",
          icon: Sparkles,
        };
      case "strength":
        return {
          label: language === "es" ? "Fortaleza" : "Strength",
          classes: "border-emerald-200 bg-emerald-50 text-emerald-700",
          icon: ArrowUpRight,
        };
      case "average":
        return {
          label: language === "es" ? "En la Media" : "Average",
          classes: "border-slate-200 bg-slate-50 text-slate-600",
          icon: Minus,
        };
      case "weakness":
        return {
          label: language === "es" ? "Punto Débil" : "Weakness",
          classes: "border-amber-200 bg-amber-50 text-amber-700",
          icon: ArrowDownRight,
        };
      case "critical_deficit":
        return {
          label: language === "es" ? "Déficit Crítico" : "Critical Gap",
          classes: "border-rose-200 bg-rose-50 text-rose-700 font-bold",
          icon: AlertTriangle,
        };
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 md:pl-64">
      <Navbar />

      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8 space-y-8">
        
        {/* Header Title Section */}
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 border-b border-slate-200/80 pb-6">
          <div>
            <div className="flex items-center gap-2.5">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-cyan-600 text-white shadow-md shadow-cyan-600/20">
                <Dumbbell className="h-5 w-5" />
              </div>
              <div>
                <h1 className="text-2xl sm:text-3xl font-black tracking-tight text-slate-900 flex items-center gap-2">
                  {t("training_page_title") || "Campo de Análisis y Entrenamiento"}
                  <span className="rounded-md border border-cyan-200 bg-cyan-50 px-2 py-0.5 text-[10px] font-black uppercase text-cyan-800 tracking-wider">
                    Core Engine
                  </span>
                </h1>
                <p className="text-xs sm:text-sm font-medium text-slate-500 mt-0.5 max-w-3xl">
                  {t("training_page_subtitle") ||
                    "Comparativa científica contra pares de posición, evaluación de cumplimiento de rol y prescripción de rutinas de entrenamiento personalizado."}
                </p>
              </div>
            </div>
          </div>

          {/* Quick Stats Pill */}
          {analysis && (
            <div className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-white p-2 shadow-2xs">
              <div className="rounded-xl bg-cyan-50 px-3 py-1.5 text-center">
                <span className="block text-[10px] font-extrabold uppercase text-cyan-700">
                  {analysis.position_group} ({analysis.position})
                </span>
                <span className="text-xs font-black text-slate-900">
                  {analysis.total_position_peers} {language === "es" ? "Pares" : "Peers"}
                </span>
              </div>
              <div className="rounded-xl bg-orange-50 px-3 py-1.5 text-center">
                <span className="block text-[10px] font-extrabold uppercase text-orange-700">
                  {t("training_fulfillment_score") || "Cumplimiento"}
                </span>
                <span className="text-xs font-black text-orange-900">
                  {analysis.role_fulfillment.overall_score}%
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Preset Selector Chips & Search Bar */}
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-xs space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
              {language === "es" ? "Exploración Rápida de Casos Tácticos:" : "Quick Tactical Presets:"}
            </span>

            {/* Season Selector Dropdown */}
            {seasons.length > 0 && (
              <div className="flex items-center gap-2">
                <label className="text-xs font-semibold text-slate-500">
                  {t("training_select_season") || "Temporada"}:
                </label>
                <select
                  value={selectedSeasonId || ""}
                  onChange={(e) => setSelectedSeasonId(Number(e.target.value))}
                  className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-bold text-slate-800 focus:border-cyan-500 focus:outline-hidden"
                >
                  {seasons.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.season_label} {s.is_active ? "🔥" : ""}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          <div className="flex flex-wrap gap-2">
            {PRESET_PLAYERS.map((preset) => {
              const isSelected = selectedPlayer === preset.name;
              return (
                <button
                  key={preset.name}
                  onClick={() => {
                    setSelectedPlayer(preset.name);
                    const matchSeason = seasons.find((s) => s.season_label.includes(preset.season));
                    if (matchSeason) setSelectedSeasonId(matchSeason.id);
                  }}
                  className={`rounded-xl border px-3 py-1.5 text-xs font-bold transition-all ${
                    isSelected
                      ? "border-cyan-600 bg-cyan-50 text-cyan-800 shadow-2xs"
                      : "border-slate-200 bg-slate-50 text-slate-600 hover:border-slate-300 hover:bg-slate-100"
                  }`}
                >
                  {preset.label}
                </button>
              );
            })}
          </div>

          {/* Search Player Dropdown */}
          <div className="relative pt-2">
            <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
              <Search className="h-4 w-4 text-slate-400" />
              <input
                type="text"
                placeholder={t("nav_search_placeholder") || "Buscar otro jugador de la NBA..."}
                value={searchQuery}
                onFocus={() => setIsSearchOpen(true)}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setIsSearchOpen(true);
                }}
                className="w-full bg-transparent text-xs font-medium text-slate-800 placeholder-slate-400 focus:outline-hidden"
              />
              {selectedPlayer && (
                <span className="text-[11px] font-bold text-cyan-700 bg-cyan-100/70 px-2 py-0.5 rounded-md truncate max-w-[140px]">
                  {selectedPlayer}
                </span>
              )}
            </div>

            {/* Dropdown list */}
            {isSearchOpen && (
              <div className="absolute left-0 right-0 top-full z-30 mt-1 max-h-56 overflow-y-auto rounded-xl border border-slate-200 bg-white p-1 shadow-lg">
                {filteredPlayers.length === 0 ? (
                  <div className="p-3 text-center text-xs text-slate-400">
                    {language === "es" ? "No se encontraron jugadores" : "No players found"}
                  </div>
                ) : (
                  filteredPlayers.map((p) => (
                    <button
                      key={p.player_id}
                      onClick={() => {
                        setSelectedPlayer(p.player_name);
                        setIsSearchOpen(false);
                        setSearchQuery("");
                      }}
                      className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-xs font-semibold text-slate-700 hover:bg-cyan-50 hover:text-cyan-900 transition"
                    >
                      <span>{p.player_name}</span>
                      <span className="text-[10px] font-mono font-bold text-slate-400">
                        {p.team_abbreviation || "NBA"}
                      </span>
                    </button>
                  ))
                )}
              </div>
            )}
          </div>
        </div>

        {/* Loading / Error States */}
        {loading && (
          <div className="flex flex-col items-center justify-center rounded-3xl border border-slate-200 bg-white p-16 text-center shadow-xs">
            <div className="h-10 w-10 animate-spin rounded-full border-4 border-cyan-500 border-t-transparent" />
            <p className="mt-4 text-sm font-bold text-slate-700">
              {language === "es"
                ? "Extrayendo cohorte posicional y calculando plan de entrenamiento..."
                : "Extracting positional cohort and calculating training prescription..."}
            </p>
          </div>
        )}

        {error && !loading && (
          <div className="rounded-3xl border border-rose-200 bg-rose-50 p-8 text-center text-rose-800">
            <AlertTriangle className="mx-auto h-8 w-8 text-rose-600 mb-2" />
            <h3 className="text-base font-bold">Error en el análisis de entrenamiento</h3>
            <p className="text-xs mt-1">{error}</p>
          </div>
        )}

        {/* Main Analysis Content */}
        {analysis && !loading && (
          <div className="space-y-8">
            
            {/* HERO CARD: Player Profile & Role Fulfillment Assessment */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              
              {/* Left Column: Player Identity & Tactical Archetype */}
              <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-xs flex flex-col justify-between space-y-6">
                <div className="flex items-start gap-4">
                  <div className="relative h-20 w-20 shrink-0 overflow-hidden rounded-2xl border-2 border-slate-100 bg-slate-100 shadow-inner">
                    <Image
                      src={analysis.headshot_url}
                      alt={analysis.player_name}
                      fill
                      className="object-cover object-top"
                      unoptimized
                    />
                  </div>
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="rounded-md border border-cyan-200 bg-cyan-50 px-2 py-0.5 text-[10px] font-black text-cyan-800">
                        {analysis.position} • {analysis.position_group}
                      </span>
                      <span className="text-xs font-mono font-bold text-slate-400">
                        {analysis.season_label}
                      </span>
                    </div>
                    <h2 className="text-xl font-black text-slate-900 tracking-tight leading-tight">
                      {analysis.player_name}
                    </h2>
                    <p className="text-xs font-semibold text-slate-500">
                      {analysis.team_name} ({analysis.team_abbreviation})
                    </p>
                  </div>
                </div>

                {/* Archetype Pill */}
                <div className="rounded-2xl border border-slate-100 bg-slate-50/80 p-4 space-y-2">
                  <div className="flex items-center justify-between text-xs font-bold text-slate-500">
                    <span>{language === "es" ? "Arquetipo Táctico:" : "Tactical Archetype:"}</span>
                    <span
                      className="h-2.5 w-2.5 rounded-full"
                      style={{ backgroundColor: analysis.archetype_color }}
                    />
                  </div>
                  <div
                    className="rounded-xl px-3 py-1.5 text-xs font-extrabold text-white text-center shadow-2xs"
                    style={{ backgroundColor: analysis.archetype_color }}
                  >
                    {language === "es" ? analysis.archetype_name_es : analysis.archetype_name_en}
                  </div>
                </div>

                {/* Per-Game Stats Strip */}
                <div className="grid grid-cols-4 gap-2 text-center pt-2 border-t border-slate-100">
                  <div className="rounded-xl bg-slate-50 p-2">
                    <span className="block text-[10px] font-bold text-slate-400 uppercase">PTS</span>
                    <span className="text-sm font-black text-slate-900">{analysis.current_stats.pts}</span>
                  </div>
                  <div className="rounded-xl bg-slate-50 p-2">
                    <span className="block text-[10px] font-bold text-slate-400 uppercase">REB</span>
                    <span className="text-sm font-black text-slate-900">{analysis.current_stats.reb}</span>
                  </div>
                  <div className="rounded-xl bg-slate-50 p-2">
                    <span className="block text-[10px] font-bold text-slate-400 uppercase">AST</span>
                    <span className="text-sm font-black text-slate-900">{analysis.current_stats.ast}</span>
                  </div>
                  <div className="rounded-xl bg-slate-50 p-2">
                    <span className="block text-[10px] font-bold text-slate-400 uppercase">3P%</span>
                    <span className="text-sm font-black text-slate-900">
                      {Math.round((analysis.current_stats.fg3_pct || 0) * 100)}%
                    </span>
                  </div>
                </div>
              </div>

              {/* Center & Right Column: Role Fulfillment Assessment */}
              <div className="lg:col-span-2 rounded-3xl border border-slate-200 bg-white p-6 shadow-xs flex flex-col justify-between space-y-6">
                <div>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Award className="h-5 w-5 text-cyan-600" />
                      <h3 className="text-base font-extrabold text-slate-900">
                        {t("training_role_assessment") || "Diagnóstico de Cumplimiento de Rol"}
                      </h3>
                    </div>
                    <span className="text-xs font-semibold text-slate-400">
                      {analysis.total_position_peers} {language === "es" ? "jugadores en la cohorte" : "peers in cohort"}
                    </span>
                  </div>

                  {/* Big Grade Banner */}
                  <div className="mt-4 flex flex-col sm:flex-row items-center gap-6 rounded-2xl border border-slate-100 bg-slate-50/50 p-4">
                    <div className="flex items-center gap-3">
                      <div
                        className={`flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl border-2 text-2xl font-black shadow-xs ring-4 ${getGradeBadge(
                          analysis.role_fulfillment.letter_grade
                        )}`}
                      >
                        {analysis.role_fulfillment.letter_grade}
                      </div>
                      <div>
                        <span className="block text-[10px] font-extrabold uppercase tracking-wider text-slate-400">
                          {t("training_role_grade") || "Calificación Posicional"}
                        </span>
                        <h4 className="text-sm font-black text-slate-800">
                          {language === "es"
                            ? analysis.role_fulfillment.grade_label_es
                            : analysis.role_fulfillment.grade_label_en}
                        </h4>
                        <div className="flex items-center gap-2 mt-1">
                          <div className="h-2 w-28 rounded-full bg-slate-200 overflow-hidden">
                            <div
                              className="h-full bg-cyan-600 rounded-full"
                              style={{ width: `${analysis.role_fulfillment.overall_score}%` }}
                            />
                          </div>
                          <span className="text-xs font-black text-cyan-800">
                            {analysis.role_fulfillment.overall_score}/100
                          </span>
                        </div>
                      </div>
                    </div>

                    <div className="sm:border-l sm:border-slate-200 sm:pl-6 text-xs text-slate-600 font-medium leading-relaxed">
                      {language === "es"
                        ? analysis.role_fulfillment.verdict_es
                        : analysis.role_fulfillment.verdict_en}
                    </div>
                  </div>
                </div>

                {/* Strengths & Deficits Pill List */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
                  <div className="space-y-2">
                    <div className="flex items-center gap-1.5 text-xs font-bold text-emerald-700">
                      <CheckCircle2 className="h-4 w-4" />
                      <span>{language === "es" ? "Fortalezas en su Posición" : "Positional Strengths"}</span>
                    </div>
                    <ul className="space-y-1.5">
                      {(language === "es"
                        ? analysis.role_fulfillment.key_strengths_es
                        : analysis.role_fulfillment.key_strengths_en
                      ).map((str, idx) => (
                        <li
                          key={idx}
                          className="flex items-center gap-2 rounded-xl bg-emerald-50/60 border border-emerald-100 px-3 py-1.5 text-xs font-medium text-emerald-900"
                        >
                          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                          <span className="truncate">{str}</span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  <div className="space-y-2">
                    <div className="flex items-center gap-1.5 text-xs font-bold text-amber-700">
                      <AlertTriangle className="h-4 w-4" />
                      <span>{language === "es" ? "Áreas Críticas por Desarrollar" : "Primary Deficits to Address"}</span>
                    </div>
                    <ul className="space-y-1.5">
                      {(language === "es"
                        ? analysis.role_fulfillment.primary_deficits_es
                        : analysis.role_fulfillment.primary_deficits_en
                      ).map((def, idx) => (
                        <li
                          key={idx}
                          className="flex items-center gap-2 rounded-xl bg-amber-50/60 border border-amber-100 px-3 py-1.5 text-xs font-medium text-amber-900"
                        >
                          <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
                          <span className="truncate">{def}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>

              </div>

            </div>

            {/* RADAR TRI-DIMENSIONAL & POSITIONAL COHORT BENCHMARK */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
              
              {/* Radar Chart Component */}
              <div className="lg:col-span-6 rounded-3xl border border-slate-200 bg-white p-6 shadow-xs flex flex-col justify-between">
                <div>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Layers className="h-5 w-5 text-cyan-600" />
                      <h3 className="text-base font-extrabold text-slate-900">
                        {t("training_radar_title") || "Radar Tri-Dimensional de Rendimiento"}
                      </h3>
                    </div>
                    <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-bold text-slate-600">
                      3 Layers
                    </span>
                  </div>
                  <p className="text-xs text-slate-500 mt-1">
                    {t("training_radar_sub") ||
                      "Actual vs Benchmark Posicional vs Proyección Post-Entrenamiento"}
                  </p>
                </div>

                <div className="py-4">
                  <TrainingTriRadar
                    labels={analysis.radar_labels}
                    playerValues={analysis.radar_player_values}
                    benchmarkValues={analysis.radar_benchmark_values}
                    projectedValues={analysis.radar_projected_values}
                    playerName={analysis.player_name}
                    positionLabel={analysis.position}
                  />
                </div>

                {/* Radar Legend Helper */}
                <div className="grid grid-cols-3 gap-2 rounded-2xl border border-slate-100 bg-slate-50/70 p-3 text-center text-[11px] font-bold">
                  <div className="flex items-center justify-center gap-1.5 text-orange-700">
                    <span className="h-2.5 w-2.5 rounded-full bg-orange-600" />
                    <span>{analysis.player_name}</span>
                  </div>
                  <div className="flex items-center justify-center gap-1.5 text-slate-600">
                    <span className="h-2.5 w-2.5 rounded-full bg-slate-500" />
                    <span>Media {analysis.position}</span>
                  </div>
                  <div className="flex items-center justify-center gap-1.5 text-cyan-700">
                    <span className="h-2.5 w-2.5 rounded-full bg-cyan-500" />
                    <span>Proyección ⚡</span>
                  </div>
                </div>
              </div>

              {/* Positional Stat Gaps Matrix */}
              <div className="lg:col-span-6 rounded-3xl border border-slate-200 bg-white p-6 shadow-xs flex flex-col justify-between space-y-4">
                <div>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <BarChart3 className="h-5 w-5 text-cyan-600" />
                      <h3 className="text-base font-extrabold text-slate-900">
                        {t("training_gaps_title") || "Matriz de Brechas Estadísticas"}
                      </h3>
                    </div>
                    <span className="text-xs font-semibold text-slate-400">
                      vs {analysis.position_group} ({analysis.season_label})
                    </span>
                  </div>
                  <p className="text-xs text-slate-500 mt-1">
                    {language === "es"
                      ? "Diferencias relativas respecto a la media de otros jugadores en la misma posición."
                      : "Relative deltas against the average of positional peers in the active season."}
                  </p>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-slate-200 text-[10px] font-extrabold uppercase text-slate-400 tracking-wider">
                        <th className="pb-2">{t("training_stat_name") || "Métrica"}</th>
                        <th className="pb-2 text-right">{analysis.player_name.split(" ").pop()}</th>
                        <th className="pb-2 text-right">Media {analysis.position}</th>
                        <th className="pb-2 text-right">{t("training_diff") || "Delta"}</th>
                        <th className="pb-2 text-right">{t("training_status") || "Estado"}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 font-medium">
                      {analysis.stat_gaps.map((gap) => {
                        const statusBadge = getStatusBadge(gap.status);
                        const Icon = statusBadge.icon;
                        return (
                          <tr key={gap.stat_key} className="hover:bg-slate-50/70 transition">
                            <td className="py-2.5 font-bold text-slate-900">
                              {language === "es" ? gap.label_es : gap.label_en}
                            </td>
                            <td className="py-2.5 text-right font-mono font-bold text-slate-800">
                              {gap.stat_key.includes("_pct")
                                ? `${Math.round(gap.player_value * 1000) / 10}%`
                                : gap.player_value}
                            </td>
                            <td className="py-2.5 text-right font-mono text-slate-500">
                              {gap.stat_key.includes("_pct")
                                ? `${Math.round(gap.position_avg * 1000) / 10}%`
                                : gap.position_avg}
                            </td>
                            <td
                              className={`py-2.5 text-right font-mono font-extrabold ${
                                gap.diff > 0
                                  ? gap.stat_key === "tov" || gap.stat_key === "pf"
                                    ? "text-rose-600"
                                    : "text-emerald-600"
                                  : gap.stat_key === "tov" || gap.stat_key === "pf"
                                  ? "text-emerald-600"
                                  : "text-rose-600"
                              }`}
                            >
                              {gap.diff > 0 ? `+${gap.diff}` : gap.diff}
                              {gap.stat_key.includes("_pct") ? "" : ""}
                            </td>
                            <td className="py-2.5 text-right">
                              <span
                                className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[10px] font-bold ${statusBadge.classes}`}
                              >
                                <Icon className="h-3 w-3" />
                                <span>{statusBadge.label}</span>
                              </span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

              </div>

            </div>

            {/* PERSONALIZED TRAINING PRESCRIPTION & DRILLS */}
            <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-xs space-y-6">
              
              {/* Title & Regime Selector Tabs */}
              <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 border-b border-slate-100 pb-5">
                <div>
                  <div className="flex items-center gap-2">
                    <Target className="h-5 w-5 text-cyan-600" />
                    <h3 className="text-lg font-black text-slate-900">
                      {t("training_plans_title") || "Prescripción de Entrenamiento Personalizado"}
                    </h3>
                  </div>
                  <p className="text-xs text-slate-500 mt-1">
                    {t("training_plans_sub") ||
                      "Drills de élite seleccionados para compensar debilidades y potenciar virtudes en su posición."}
                  </p>
                </div>

                {/* Regime Tabs */}
                <div className="flex flex-wrap gap-2">
                  {analysis.training_regimes.map((regime) => {
                    const isSelected = activeRegimeId === regime.regime_id;
                    return (
                      <button
                        key={regime.regime_id}
                        onClick={() => setActiveRegimeId(regime.regime_id)}
                        className={`flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-xs font-bold transition-all ${
                          isSelected
                            ? "border-cyan-600 bg-cyan-600 text-white shadow-sm shadow-cyan-600/20"
                            : "border-slate-200 bg-slate-50 text-slate-600 hover:border-slate-300 hover:bg-slate-100"
                        }`}
                      >
                        {regime.regime_id === "balanced" && <Sparkles className="h-3.5 w-3.5" />}
                        {regime.regime_id === "shooting_focus" && <Flame className="h-3.5 w-3.5" />}
                        {regime.regime_id === "defensive_lockdown" && <Shield className="h-3.5 w-3.5" />}
                        {regime.regime_id === "playmaking_mastery" && <Zap className="h-3.5 w-3.5" />}
                        <span>{language === "es" ? regime.title_es : regime.title_en}</span>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Regime Details Header Strip */}
              {currentRegime && (
                <div className="rounded-2xl border border-cyan-100 bg-cyan-50/50 p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div className="space-y-1">
                    <span className="text-[10px] font-black uppercase tracking-wider text-cyan-800">
                      {language === "es" ? currentRegime.title_es : currentRegime.title_en}
                    </span>
                    <p className="text-xs text-slate-700 font-medium">
                      {language === "es" ? currentRegime.description_es : currentRegime.description_en}
                    </p>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    <div className="rounded-xl border border-cyan-200 bg-white px-3 py-1.5 text-center">
                      <span className="block text-[9px] font-extrabold uppercase text-slate-400">
                        {language === "es" ? "Frecuencia" : "Frequency"}
                      </span>
                      <span className="text-xs font-black text-cyan-800">
                        {currentRegime.weekly_frequency}
                      </span>
                    </div>
                  </div>
                </div>
              )}

              {/* Drills Grid */}
              {currentRegime && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {currentRegime.drills.map((drill, idx) => (
                    <div
                      key={drill.id}
                      className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs flex flex-col justify-between space-y-4 hover:border-cyan-400 transition"
                    >
                      <div className="space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-black uppercase text-slate-600">
                            Drill #{idx + 1} • {drill.category}
                          </span>
                          <span
                            className={`rounded-md px-2 py-0.5 text-[10px] font-extrabold uppercase ${
                              drill.intensity === "elite"
                                ? "bg-purple-100 text-purple-800"
                                : drill.intensity === "high"
                                ? "bg-orange-100 text-orange-800"
                                : "bg-cyan-100 text-cyan-800"
                            }`}
                          >
                            {drill.intensity}
                          </span>
                        </div>

                        <h4 className="text-sm font-extrabold text-slate-900">
                          {language === "es" ? drill.name_es : drill.name_en}
                        </h4>

                        <p className="text-xs text-slate-600 font-medium leading-relaxed">
                          {language === "es" ? drill.description_es : drill.description_en}
                        </p>
                      </div>

                      <div className="space-y-2 pt-3 border-t border-slate-100">
                        <div className="flex items-center gap-1.5 text-xs text-slate-700 font-semibold">
                          <Clock className="h-3.5 w-3.5 text-slate-400 shrink-0" />
                          <span className="truncate">{drill.sets_and_reps}</span>
                        </div>
                        <div className="flex items-center gap-1.5 rounded-xl bg-emerald-50 border border-emerald-100 px-3 py-1.5 text-xs font-bold text-emerald-800">
                          <Zap className="h-3.5 w-3.5 text-emerald-600 shrink-0" />
                          <span className="truncate">
                            {language === "es" ? drill.projected_impact_es : drill.projected_impact_en}
                          </span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

            </div>

            {/* SIMULATED IMPACT: BEFORE vs AFTER */}
            <div className="rounded-3xl border border-slate-200 bg-gradient-to-br from-slate-900 to-slate-800 text-white p-6 shadow-md space-y-6">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="flex items-center gap-2.5">
                  <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-cyan-500 text-slate-900 font-black">
                    ⚡
                  </div>
                  <div>
                    <h3 className="text-base sm:text-lg font-black tracking-tight text-white">
                      {t("training_simulation_title") || "Simulación de Impacto Post-Entrenamiento"}
                    </h3>
                    <p className="text-xs text-slate-300">
                      {language === "es"
                        ? "Proyección basada en la compleción del régimen de entrenamiento prescrito."
                        : "Projection modeled upon successful completion of the prescribed training program."}
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <div className="rounded-xl border border-slate-700 bg-slate-800/80 px-3 py-1.5 text-center">
                    <span className="block text-[9px] font-bold text-slate-400 uppercase">
                      {t("training_before") || "Antes"}
                    </span>
                    <span className="text-xs font-black text-rose-400">
                      {analysis.role_fulfillment.overall_score}% ({analysis.role_fulfillment.letter_grade})
                    </span>
                  </div>
                  <span className="text-cyan-400 font-black">➔</span>
                  <div className="rounded-xl border border-cyan-500/50 bg-cyan-950/80 px-3 py-1.5 text-center">
                    <span className="block text-[9px] font-bold text-cyan-300 uppercase">
                      {t("training_after") || "Después"}
                    </span>
                    <span className="text-xs font-black text-cyan-300">
                      {analysis.role_fulfillment.projected_score}% ({analysis.role_fulfillment.projected_grade})
                    </span>
                  </div>
                </div>
              </div>

              {/* Stat Deltas Comparison Grid */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2">
                <div className="rounded-2xl border border-slate-700/80 bg-slate-800/60 p-3.5 space-y-1">
                  <span className="text-[10px] font-bold uppercase text-slate-400">Puntos (PTS)</span>
                  <div className="flex items-baseline justify-between">
                    <span className="text-xs text-slate-400 line-through">{analysis.current_stats.pts}</span>
                    <span className="text-base font-black text-cyan-400">
                      {analysis.projected_stats.pts} PPG
                    </span>
                  </div>
                </div>

                <div className="rounded-2xl border border-slate-700/80 bg-slate-800/60 p-3.5 space-y-1">
                  <span className="text-[10px] font-bold uppercase text-slate-400">Triples (3P%)</span>
                  <div className="flex items-baseline justify-between">
                    <span className="text-xs text-slate-400 line-through">
                      {Math.round((analysis.current_stats.fg3_pct || 0) * 1000) / 10}%
                    </span>
                    <span className="text-base font-black text-cyan-400">
                      {Math.round((analysis.projected_stats.fg3_pct || 0) * 1000) / 10}%
                    </span>
                  </div>
                </div>

                <div className="rounded-2xl border border-slate-700/80 bg-slate-800/60 p-3.5 space-y-1">
                  <span className="text-[10px] font-bold uppercase text-slate-400">Pérdidas (TOV)</span>
                  <div className="flex items-baseline justify-between">
                    <span className="text-xs text-slate-400 line-through">{analysis.current_stats.tov}</span>
                    <span className="text-base font-black text-emerald-400">
                      {analysis.projected_stats.tov} TOV
                    </span>
                  </div>
                </div>

                <div className="rounded-2xl border border-slate-700/80 bg-slate-800/60 p-3.5 space-y-1">
                  <span className="text-[10px] font-bold uppercase text-slate-400">Tiro de Campo (FG%)</span>
                  <div className="flex items-baseline justify-between">
                    <span className="text-xs text-slate-400 line-through">
                      {Math.round((analysis.current_stats.fg_pct || 0) * 1000) / 10}%
                    </span>
                    <span className="text-base font-black text-cyan-400">
                      {Math.round((analysis.projected_stats.fg_pct || 0) * 1000) / 10}%
                    </span>
                  </div>
                </div>
              </div>

            </div>

          </div>
        )}

      </main>
    </div>
  );
}
