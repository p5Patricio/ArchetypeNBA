"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  Activity,
  Zap,
  Shield,
  Target,
  Sparkles,
  BarChart3,
  Flame,
  Layers,
  Gauge,
  PieChart,
  Crosshair,
  Users,
} from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { CommandPalette } from "@/components/CommandPalette";
import { RadarChart } from "@/components/RadarChart";
import { ShotChart } from "@/components/ShotChart";
import { MoreyballWidget } from "@/components/MoreyballWidget";
import { HistoricalComps } from "@/components/HistoricalComps";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { TeamLogo } from "@/components/TeamLogo";
import { PercentilePizzaChart, type PizzaChartData } from "@/components/PercentilePizzaChart";
import { RealShotChart, type RealShotChartData } from "@/components/RealShotChart";
import {
  getPlayerAnalysis,
  getPlayerProfile,
  getPlayerAdvancedStats,
  getPlayerSimilarities,
  getPlayerShots,
  getPlayerMoreyball,
  getHistoricalMatches,
  type PlayerAnalysisResponse,
  type PlayerProfileResponse,
  type PlayerAdvancedStatsResponse,
  type PlayerSimilaritiesResponse,
  type PlayerShot,
  type MoreyballMetricsResponse,
  type HistoricalMatchResponse,
} from "@/lib/api";
import { usePreferences } from "@/context/PreferencesContext";

export default function PlayerPage() {
  const params = useParams();
  const router = useRouter();
  const rawName = params.name as string;
  const decodedName = decodeURIComponent(rawName || "");

  const { t, formatHeight, formatWeight, language } = usePreferences();
  const [seasonId, setSeasonId] = useState<number>(1);
  const [seasonLabel, setSeasonLabel] = useState<string>("2023-24");
  const [activeTab, setActiveTab] = useState<"overview" | "pizza" | "shotchart" | "doppelgangers">("overview");

  const [analysis, setAnalysis] = useState<PlayerAnalysisResponse | null>(null);
  const [profile, setProfile] = useState<PlayerProfileResponse | null>(null);
  const [advanced, setAdvanced] = useState<PlayerAdvancedStatsResponse | null>(null);
  const [similar, setSimilar] = useState<PlayerSimilaritiesResponse | null>(null);
  const [shots, setShots] = useState<PlayerShot[]>([]);
  const [moreyball, setMoreyball] = useState<MoreyballMetricsResponse | null>(null);
  const [histMatches, setHistMatches] = useState<HistoricalMatchResponse | null>(null);
  
  // Advanced Expansion Analytics Data
  const [pizzaData, setPizzaData] = useState<PizzaChartData | null>(null);
  const [realShotData, setRealShotData] = useState<RealShotChartData | null>(null);
  const [doppelData, setDoppelData] = useState<any | null>(null);

  const [loading, setLoading] = useState<boolean>(true);
  const [isCommandOpen, setIsCommandOpen] = useState<boolean>(false);

  useEffect(() => {
    if (!decodedName) return;
    setLoading(true);

    Promise.allSettled([
      getPlayerAnalysis(decodedName, seasonId),
      getPlayerProfile(decodedName),
      getPlayerAdvancedStats(decodedName, seasonId),
      getPlayerSimilarities(decodedName, seasonId),
      getPlayerShots(decodedName, seasonId),
      getPlayerMoreyball(decodedName, seasonId),
      getHistoricalMatches(decodedName, seasonId),
      fetch(`http://localhost:8000/api/v1/player/${encodeURIComponent(decodedName)}/pizza-chart?season_id=${seasonId}`).then((r) => r.ok ? r.json() : null),
      fetch(`http://localhost:8000/api/v1/players/${encodeURIComponent(decodedName)}/shot-chart?season_id=${seasonId}&max_shots=350`).then((r) => r.ok ? r.json() : null),
      fetch(`http://localhost:8000/api/v1/doppelgangers?player_id_or_name=${encodeURIComponent(decodedName)}&season_id=${seasonId}&top_k=5`).then((r) => r.ok ? r.json() : null),
    ]).then(([analysisRes, profileRes, advancedRes, similarRes, shotsRes, moreyRes, histRes, pizzaRes, realShotRes, doppelRes]) => {
      if (analysisRes.status === "fulfilled") setAnalysis(analysisRes.value);
      else setAnalysis(null);

      if (profileRes.status === "fulfilled") setProfile(profileRes.value);

      if (advancedRes.status === "fulfilled") setAdvanced(advancedRes.value);
      else setAdvanced(null);

      if (similarRes.status === "fulfilled") setSimilar(similarRes.value);
      else setSimilar(null);

      if (shotsRes.status === "fulfilled" && shotsRes.value?.shots) setShots(shotsRes.value.shots);
      else setShots([]);

      if (moreyRes.status === "fulfilled") setMoreyball(moreyRes.value);
      else setMoreyball(null);

      if (histRes.status === "fulfilled") setHistMatches(histRes.value);
      else setHistMatches(null);

      if (pizzaRes.status === "fulfilled" && pizzaRes.value) setPizzaData(pizzaRes.value);
      if (realShotRes.status === "fulfilled" && realShotRes.value) setRealShotData(realShotRes.value);
      if (doppelRes.status === "fulfilled" && doppelRes.value) setDoppelData(doppelRes.value);

      setLoading(false);
    });
  }, [decodedName, seasonId]);

  const pStats = analysis?.player_stats || {};
  const cStats = analysis?.cluster_mean || {};
  const roleBreakdown = analysis?.role_breakdown || [];

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 pb-20">
      <Navbar onOpenSearch={() => setIsCommandOpen(true)} />
      <CommandPalette isOpen={isCommandOpen} onClose={() => setIsCommandOpen(false)} />

      <div className="md:pl-64">
        <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-8 space-y-6">
          {/* Back Link */}
          <Link
            href="/"
            className="inline-flex items-center gap-2 text-xs font-bold text-slate-500 hover:text-slate-900 transition-colors uppercase tracking-wider"
          >
            <ArrowLeft className="h-4 w-4" />
            {t("nav_scouting_hub")}
          </Link>

        {/* Player Header Card */}
        <div className="rounded-3xl border border-slate-200 bg-white p-6 sm:p-8 shadow-xs relative overflow-hidden">
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-6">
            <div className="flex items-center gap-5">
              <div className="relative">
                <PlayerAvatar
                  headshotUrl={profile?.headshot_url}
                  playerName={decodedName}
                  size={64}
                  className="ring-4 ring-slate-100 shadow-md"
                />

                {profile?.team_abbreviation && (
                  <div className="absolute -bottom-2 -right-2 rounded-full bg-white p-1 shadow-sm ring-1 ring-slate-200">
                    <TeamLogo abbreviation={profile.team_abbreviation} size={28} />
                  </div>
                )}
              </div>

              <div>
                <div className="flex items-center gap-2">
                  <span className="rounded-full bg-slate-100 px-2.5 py-0.5 font-mono text-xs font-bold text-slate-700">
                    {profile?.position || "G/F"}
                  </span>
                  <span className="text-xs font-medium text-slate-500">
                    {profile?.team_name || "NBA"}
                  </span>
                </div>
                <h1 className="text-3xl sm:text-4xl font-black tracking-tight text-slate-900 mt-1">
                  {decodedName}
                </h1>
                <div className="flex items-center gap-2 mt-1">
                  <span className="inline-flex items-center gap-1.5 rounded-lg bg-purple-50 border border-purple-200 px-2.5 py-1 text-xs font-bold text-purple-700">
                    <Sparkles className="h-3.5 w-3.5" />
                    {analysis?.role_name || "Archetype"}
                  </span>
                </div>
              </div>
            </div>

            {/* Quick Bio Info */}
            <div className="flex flex-wrap items-center gap-4 text-xs font-medium text-slate-600 bg-slate-50/80 p-3.5 rounded-2xl border border-slate-100">
              <div>{t("height_label")}: <strong className="text-slate-900 font-bold">{formatHeight(profile?.height, profile?.height_cm)}</strong></div>
              <div>{t("weight_label")}: <strong className="text-slate-900 font-bold">{formatWeight(profile?.weight, profile?.weight_kg)}</strong></div>
              {profile?.age && <div>{t("age_label")}: <strong className="text-slate-900 font-bold">{profile.age} {t("years_old")}</strong></div>}
            </div>
          </div>

          {/* Quick Metrics Bar */}
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-2.5 pt-6 mt-6 border-t border-slate-100">
            <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-3 text-center">
              <div className="text-[10px] uppercase font-bold text-slate-400">{t("pts_label")} ({t("ppg_label")})</div>
              <div className="font-mono text-2xl font-black text-slate-900">
                {pStats.pts ? pStats.pts.toFixed(1) : "0.0"}
              </div>
            </div>

            <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-3 text-center">
              <div className="text-[10px] uppercase font-bold text-slate-400">{t("reb_label")} ({t("rpg_label")})</div>
              <div className="font-mono text-2xl font-black text-slate-900">
                {pStats.reb ? pStats.reb.toFixed(1) : "0.0"}
              </div>
            </div>

            <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-3 text-center">
              <div className="text-[10px] uppercase font-bold text-slate-400">{t("ast_label")} ({t("apg_label")})</div>
              <div className="font-mono text-2xl font-black text-slate-900">
                {pStats.ast ? pStats.ast.toFixed(1) : "0.0"}
              </div>
            </div>

            <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-3 text-center">
              <div className="text-[10px] uppercase font-bold text-slate-400">{t("fg_label")}</div>
              <div className="font-mono text-2xl font-black text-orange-600">
                {pStats.fg_pct ? (pStats.fg_pct * 100).toFixed(1) + "%" : "0.0%"}
              </div>
            </div>

            <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-3 text-center col-span-2 sm:col-span-1">
              <div className="text-[10px] uppercase font-bold text-slate-400">{t("mpg_label")}</div>
              <div className="font-mono text-2xl font-black text-sky-700">
                {pStats.min ? pStats.min.toFixed(1) : "0.0"}
              </div>
            </div>
          </div>
        </div>

        {/* Tactical Expansion Tabs Switcher */}
        <div className="flex items-center gap-2 border-b border-slate-200 pb-3 overflow-x-auto">
          <button
            onClick={() => setActiveTab("overview")}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition-all shrink-0 ${
              activeTab === "overview"
                ? "bg-purple-600 text-white shadow-sm"
                : "bg-white text-slate-600 hover:text-slate-900 border border-slate-200"
            }`}
          >
            <Layers className="h-4 w-4" />
            {language === "es" ? "Arquetipo & Radares" : "Archetypes & Radars"}
          </button>

          <button
            onClick={() => setActiveTab("pizza")}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition-all shrink-0 ${
              activeTab === "pizza"
                ? "bg-indigo-600 text-white shadow-sm"
                : "bg-white text-slate-600 hover:text-slate-900 border border-slate-200"
            }`}
          >
            <PieChart className="h-4 w-4" />
            {language === "es" ? "Pizza Percentiles (FBref)" : "FBref Pizza Chart"}
          </button>

          <button
            onClick={() => setActiveTab("shotchart")}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition-all shrink-0 ${
              activeTab === "shotchart"
                ? "bg-blue-600 text-white shadow-sm"
                : "bg-white text-slate-600 hover:text-slate-900 border border-slate-200"
            }`}
          >
            <Crosshair className="h-4 w-4" />
            {language === "es" ? "Mapa de Tiros Real" : "NBA Shot Chart"}
          </button>

          <button
            onClick={() => setActiveTab("doppelgangers")}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition-all shrink-0 ${
              activeTab === "doppelgangers"
                ? "bg-emerald-600 text-white shadow-sm"
                : "bg-white text-slate-600 hover:text-slate-900 border border-slate-200"
            }`}
          >
            <Users className="h-4 w-4" />
            {language === "es" ? "Clones Históricos" : "Doppelgängers"}
          </button>
        </div>

        {/* TAB 1: OVERVIEW & RADARS */}
        {activeTab === "overview" && (
          <div className="space-y-6">
            {/* Soft Clustering Role Breakdown Section */}
            {roleBreakdown.length > 0 && (
              <section className="rounded-3xl border border-slate-200 bg-white p-6 sm:p-7 shadow-xs space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-100 pb-3.5">
                  <div>
                    <h2 className="text-base font-extrabold tracking-tight text-slate-900 flex items-center gap-2">
                      <Layers className="h-4 w-4 text-purple-600" />
                      {t("soft_clustering_title")}
                    </h2>
                    <p className="text-xs font-medium text-slate-500 mt-0.5">
                      {t("soft_clustering_subtitle")}
                    </p>
                  </div>
                  <span className="self-start sm:self-auto rounded-full border border-purple-200 bg-purple-50 px-3 py-1 font-mono text-xs font-bold text-purple-700">
                    {roleBreakdown[0]?.percentage}% {language === "es" ? roleBreakdown[0]?.role_name_es : roleBreakdown[0]?.role_name_en}
                  </span>
                </div>

                {/* Stacked Multi-Color Progress Bar */}
                <div className="h-4 w-full overflow-hidden rounded-full bg-slate-100 flex shadow-inner">
                  {roleBreakdown.map((item, idx) => (
                    <div
                      key={idx}
                      className="h-full transition-all duration-700 hover:opacity-90 cursor-pointer"
                      style={{
                        width: `${item.percentage}%`,
                        backgroundColor: item.color,
                      }}
                      title={`${language === "es" ? item.role_name_es : item.role_name_en}: ${item.percentage}%`}
                    />
                  ))}
                </div>

                {/* 7 Roles Percentage Cards Grid */}
                <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2.5 pt-2">
                  {roleBreakdown.map((item, idx) => {
                    const isPrimary = idx === 0;
                    return (
                      <div
                        key={idx}
                        className={`rounded-2xl border p-3 flex flex-col justify-between transition ${
                          isPrimary
                            ? "border-purple-300 bg-purple-50/40 ring-1 ring-purple-400"
                            : "border-slate-100 bg-slate-50/50"
                        }`}
                      >
                        <div>
                          <div className="flex items-center justify-between">
                            <span
                              className="h-2.5 w-2.5 rounded-full"
                              style={{ backgroundColor: item.color }}
                            />
                            {isPrimary && (
                              <span className="rounded bg-purple-100 px-1 py-0.2 text-[9px] font-bold text-purple-800">
                                ★
                              </span>
                            )}
                          </div>
                          <div className="text-[11px] font-bold text-slate-800 mt-2 line-clamp-2 leading-tight">
                            {language === "es" ? item.role_name_es : item.role_name_en}
                          </div>
                        </div>

                        <div className="mt-3 font-mono text-base font-black text-slate-900">
                          {item.percentage}%
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            )}

            {/* Moreyball Optimization Widget */}
            {moreyball && (
              <section className="space-y-4">
                <MoreyballWidget data={moreyball} />
              </section>
            )}

            {/* Dual Scouting Lab Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
              {/* Radar Chart (7 cols) */}
              <div className="lg:col-span-7 space-y-5">
                <div>
                  <h2 className="text-lg font-extrabold tracking-tight text-slate-900 flex items-center gap-2">
                    <Target className="h-5 w-5 text-orange-600" />
                    {t("radar_title")}
                  </h2>
                  <p className="text-xs font-medium text-slate-500 mt-0.5">
                    {t("radar_subtitle", {
                      role: analysis?.role_name || "Archetype",
                    })}
                  </p>
                </div>

                <RadarChart
                  playerStats={pStats}
                  clusterStats={cStats}
                  playerName={decodedName}
                  clusterName={analysis?.role_name || t("radar_benchmark")}
                />

                <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-xs">
                  <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-orange-600">
                    <Zap className="h-4 w-4" />
                    {t("diagnostic_title")}
                  </div>
                  <p className="mt-2 text-xs text-slate-700 leading-relaxed font-medium">
                    {t("diagnostic_text", {
                      name: decodedName,
                      role: analysis?.role_name || "Main Role",
                      pts: pStats.pts ? pStats.pts.toFixed(1) : 0,
                      ast: pStats.ast ? pStats.ast.toFixed(1) : 0,
                      season: seasonLabel,
                    })}
                  </p>
                </div>
              </div>

              {/* Advanced Metrics (5 cols) */}
              <div className="lg:col-span-5 space-y-5">
                <div>
                  <h2 className="text-lg font-extrabold tracking-tight text-slate-900 flex items-center gap-2">
                    <BarChart3 className="h-5 w-5 text-sky-600" />
                    {t("advanced_metrics_title")}
                  </h2>
                  <p className="text-xs font-medium text-slate-500 mt-0.5">
                    {t("advanced_metrics_subtitle")}
                  </p>
                </div>

                <div className="space-y-3">
                  <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-xs">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-bold text-slate-700">{t("metric_ts")}</span>
                      <span className="font-mono font-extrabold text-orange-600">
                        {advanced?.ts_pct ? (advanced.ts_pct * 100).toFixed(1) + "%" : "56.5%"}
                      </span>
                    </div>
                    <div className="mt-2 h-2.5 w-full overflow-hidden rounded-full bg-slate-100">
                      <div
                        className="h-full rounded-full bg-orange-500 transition-all duration-700"
                        style={{ width: `${Math.min((advanced?.ts_pct || 0.565) * 130, 100)}%` }}
                      />
                    </div>
                  </div>

                  <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-xs">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-bold text-slate-700">{t("metric_usg")}</span>
                      <span className="font-mono font-extrabold text-sky-700">
                        {advanced?.usg_pct ? (advanced.usg_pct * 100).toFixed(1) + "%" : "24.0%"}
                      </span>
                    </div>
                    <div className="mt-2 h-2.5 w-full overflow-hidden rounded-full bg-slate-100">
                      <div
                        className="h-full rounded-full bg-sky-500 transition-all duration-700"
                        style={{ width: `${Math.min((advanced?.usg_pct || 0.24) * 260, 100)}%` }}
                      />
                    </div>
                  </div>

                  <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-xs">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-bold text-slate-700">{t("metric_per")}</span>
                      <span className="font-mono font-extrabold text-emerald-700">
                        {advanced?.per ? advanced.per.toFixed(1) : "18.5"}
                      </span>
                    </div>
                    <div className="mt-2 h-2.5 w-full overflow-hidden rounded-full bg-slate-100">
                      <div
                        className="h-full rounded-full bg-emerald-500 transition-all duration-700"
                        style={{ width: `${Math.min(((advanced?.per || 18.5) / 32) * 100, 100)}%` }}
                      />
                    </div>
                  </div>

                  <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-xs">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-bold text-slate-700">{t("metric_bpm")}</span>
                      <span className="font-mono font-extrabold text-indigo-700">
                        {advanced?.bpm ? (advanced.bpm > 0 ? `+${advanced.bpm.toFixed(1)}` : advanced.bpm.toFixed(1)) : "+3.2"}
                      </span>
                    </div>
                    <div className="mt-2 h-2.5 w-full overflow-hidden rounded-full bg-slate-100">
                      <div
                        className="h-full rounded-full bg-indigo-500 transition-all duration-700"
                        style={{ width: `${Math.max(Math.min(((advanced?.bpm || 3.2) + 5) * 10, 100), 10)}%` }}
                      />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* TAB 2: PIZZA PERCENTILE CHART */}
        {activeTab === "pizza" && (
          <div className="space-y-4">
            {pizzaData ? (
              <PercentilePizzaChart data={pizzaData} />
            ) : (
              <div className="bg-white p-8 rounded-2xl border border-slate-200 text-center text-slate-500">
                {language === "es" ? "Cargando datos del gráfico de pizza..." : "Loading pizza chart metrics..."}
              </div>
            )}
          </div>
        )}

        {/* TAB 3: REAL NBA SHOT CHART */}
        {activeTab === "shotchart" && (
          <div className="space-y-4">
            {realShotData ? (
              <RealShotChart data={realShotData} />
            ) : (
              <div className="bg-white p-8 rounded-2xl border border-slate-200 text-center text-slate-500">
                {language === "es" ? "Cargando mapa de tiros NBA..." : "Loading NBA spatial shot chart..."}
              </div>
            )}
          </div>
        )}

        {/* TAB 4: HISTORICAL DOPPELGANGERS */}
        {activeTab === "doppelgangers" && (
          <div className="space-y-4">
            {doppelData ? (
              <div className="bg-white rounded-3xl border border-slate-200 p-6 shadow-xs space-y-6">
                <div>
                  <h3 className="text-xl font-extrabold text-slate-900">
                    {language === "es" ? "Clones Históricos de" : "Historical Clones for"} {doppelData.target_player_name}
                  </h3>
                  <p className="text-xs text-slate-500 mt-1">
                    {language === "es"
                      ? "Calculado a través de similitud de coseno multidimensional en 40 años de estadísticas de la NBA."
                      : "Calculated via multi-dimensional cosine similarity across 40 years of NBA statistics."}
                  </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {doppelData.matches?.map((m: any, idx: number) => {
                    const traits = language === "es" ? (m.shared_traits_es || []) : (m.shared_traits_en || []);
                    const archetype = language === "es" ? (m.archetype_name_es || m.archetype_name) : (m.archetype_name_en || m.archetype_name);

                    return (
                      <div
                        key={idx}
                        className="rounded-2xl border border-slate-200 bg-slate-50/70 p-5 flex flex-col justify-between hover:border-purple-300 transition"
                      >
                        <div>
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-bold text-slate-400">#{idx + 1} Match</span>
                            <span className="px-2.5 py-0.5 rounded-full text-xs font-black font-mono bg-purple-100 text-purple-700">
                              {(m.similarity_pct || 90).toFixed(1)}% {language === "es" ? "Similitud" : "Similarity"}
                            </span>
                          </div>

                          <div className="flex items-center gap-3 mt-3">
                            <PlayerAvatar
                              headshotUrl={m.headshot_url}
                              playerName={m.player_name}
                              size={40}
                              className="ring-1 ring-slate-200"
                            />
                            <div>
                              <h4 className="text-base font-bold text-slate-900 leading-tight">{m.player_name}</h4>
                              <div className="text-xs text-slate-500 font-medium">
                                {m.season_label} {m.age_in_season ? `• ${m.age_in_season} ${language === "es" ? "años" : "yrs"}` : ""}
                              </div>
                            </div>
                          </div>

                          <div className="mt-3">
                            <span className="px-2 py-0.5 rounded bg-white text-[11px] font-bold text-purple-700 border border-purple-200">
                              {archetype}
                            </span>
                          </div>

                          {traits.length > 0 && (
                            <div className="mt-3 flex flex-wrap gap-1">
                              {traits.slice(0, 3).map((t: string, tIdx: number) => (
                                <span key={tIdx} className="text-[10px] bg-white text-slate-700 px-2 py-0.5 rounded border border-slate-200 font-medium">
                                  ✓ {t}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>

                        {m.key_comparison_stats && (
                          <div className="mt-4 pt-3 border-t border-slate-200 grid grid-cols-3 gap-1.5 text-center text-[10px] font-mono">
                            {Object.entries(m.key_comparison_stats).slice(0, 3).map(([k, vals]: any, sIdx) => (
                              <div key={sIdx} className="bg-white p-1 rounded border border-slate-100">
                                <div className="text-slate-400 uppercase font-bold">{k}</div>
                                <div className="text-slate-800 font-extrabold">{vals.comp} vs {vals.target}</div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : (
              <div className="bg-white p-8 rounded-2xl border border-slate-200 text-center text-slate-500">
                {language === "es" ? "Cargando doppelgängers históricos..." : "Loading historical clones..."}
              </div>
            )}
          </div>
        )}
      </main>
      </div>
    </div>
  );
}

