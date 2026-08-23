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
} from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { CommandPalette } from "@/components/CommandPalette";
import { RadarChart } from "@/components/RadarChart";
import { ShotChart } from "@/components/ShotChart";
import { MoreyballWidget } from "@/components/MoreyballWidget";
import { HistoricalComps } from "@/components/HistoricalComps";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { TeamLogo } from "@/components/TeamLogo";
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
  const [analysis, setAnalysis] = useState<PlayerAnalysisResponse | null>(null);
  const [profile, setProfile] = useState<PlayerProfileResponse | null>(null);
  const [advanced, setAdvanced] = useState<PlayerAdvancedStatsResponse | null>(null);
  const [similar, setSimilar] = useState<PlayerSimilaritiesResponse | null>(null);
  const [shots, setShots] = useState<PlayerShot[]>([]);
  const [moreyball, setMoreyball] = useState<MoreyballMetricsResponse | null>(null);
  const [histMatches, setHistMatches] = useState<HistoricalMatchResponse | null>(null);
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
    ]).then(([analysisRes, profileRes, advancedRes, similarRes, shotsRes, moreyRes, histRes]) => {
      if (analysisRes.status === "fulfilled") {
        setAnalysis(analysisRes.value);
      } else {
        setAnalysis(null);
      }

      if (profileRes.status === "fulfilled") {
        setProfile(profileRes.value);
      }

      if (advancedRes.status === "fulfilled") {
        setAdvanced(advancedRes.value);
      } else {
        setAdvanced(null);
      }

      if (similarRes.status === "fulfilled") {
        setSimilar(similarRes.value);
      } else {
        setSimilar(null);
      }

      if (shotsRes.status === "fulfilled" && shotsRes.value.shots) {
        setShots(shotsRes.value.shots);
      } else {
        setShots([]);
      }

      if (moreyRes.status === "fulfilled") {
        setMoreyball(moreyRes.value);
      } else {
        setMoreyball(null);
      }

      if (histRes.status === "fulfilled") {
        setHistMatches(histRes.value);
      } else {
        setHistMatches(null);
      }

      setLoading(false);
    });
  }, [decodedName, seasonId]);

  const pStats = analysis?.player_stats || {};
  const cStats = analysis?.cluster_mean || {};
  const roleBreakdown = analysis?.role_breakdown || [];

  return (
    <div className="min-h-screen bg-[#F8FAFC] text-slate-900 selection:bg-orange-100 selection:text-orange-900">
      
      {/* Navigation */}
      <Navbar
        currentSeasonId={seasonId}
        onSeasonChange={(id, label) => {
          setSeasonId(id);
          if (label) setSeasonLabel(label);
        }}
        onOpenSearch={() => setIsCommandOpen(true)}
      />

      <CommandPalette
        isOpen={isCommandOpen}
        onClose={() => setIsCommandOpen(false)}
        seasonId={seasonId}
      />

      <div className="md:pl-64">
        {/* Main Container */}
        <main className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        
        {/* Back Button & Season Indicator */}
        <div className="flex items-center justify-between">
          <button
            onClick={() => router.push("/")}
            className="group inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-1.5 text-xs font-bold text-slate-700 hover:border-slate-300 hover:bg-slate-50 transition shadow-xs"
          >
            <ArrowLeft className="h-3.5 w-3.5 group-hover:-translate-x-0.5 transition-transform text-orange-600" />
            {t("back_to_hub")}
          </button>

          <span className="rounded-lg border border-slate-200 bg-white px-3 py-1 text-xs font-mono font-medium text-slate-700 shadow-xs">
            {t("active_season")}: <strong className="text-orange-600 font-bold">{seasonLabel}</strong>
          </span>
        </div>

        {/* Hero Player Banner */}
        <div className="rounded-3xl border border-slate-200 bg-white p-6 sm:p-8 shadow-xs">
          <div className="flex flex-col md:flex-row items-center md:items-start gap-6 sm:gap-8">
            
            {/* High-res Avatar */}
            <PlayerAvatar
              playerId={profile?.player_id}
              playerName={decodedName}
              headshotUrl={profile?.headshot_url}
              size={120}
              priority
              className="border-2 border-slate-200 shadow-sm"
            />

            {/* Player Info & Title */}
            <div className="flex-1 text-center md:text-left space-y-3">
              <div className="flex flex-wrap items-center justify-center md:justify-start gap-2">
                <span className="inline-flex items-center gap-1.5 rounded-full border border-orange-200 bg-orange-50 px-3 py-1 text-xs font-bold text-orange-700">
                  <TeamLogo
                    abbreviation={profile?.team_abbreviation || "NBA"}
                    teamName={profile?.team_name || "NBA Team"}
                    size={18}
                  />
                  <span>{profile?.team_name || profile?.team_abbreviation || "NBA"}</span>
                </span>
                {analysis?.role_name && (
                  <span className="rounded-full border border-sky-200 bg-sky-50 px-3 py-1 text-xs font-bold text-sky-700">
                    {analysis.role_name}
                  </span>
                )}
              </div>

              <h1 className="text-3xl sm:text-4xl lg:text-5xl font-black tracking-tight text-slate-900">
                {decodedName}
              </h1>

              <div className="flex flex-wrap items-center justify-center md:justify-start gap-4 text-xs font-semibold text-slate-600">
                {profile?.position && <span>{t("position_label")} <strong className="text-slate-900">{profile.position}</strong></span>}
                <span>• {t("height_label")} <strong className="text-slate-900">{formatHeight(profile?.height, profile?.height_cm)}</strong></span>
                <span>• {t("weight_label")} <strong className="text-slate-900">{formatWeight(profile?.weight, profile?.weight_kg)}</strong></span>
                {profile?.age && <span>• {t("age_label")} <strong className="text-slate-900">{profile.age} {t("years_old")}</strong></span>}
              </div>

              {/* Quick Metrics Bar */}
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-2.5 pt-3">
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

          </div>
        </div>

        {/* 1. Soft Clustering Role Breakdown Section */}
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

        {/* 2. Moreyball Optimization & Shot Quality Section */}
        {moreyball && (
          <section className="space-y-4">
            <MoreyballWidget data={moreyball} />
          </section>
        )}

        {/* 3. Dual Scouting Lab Grid: 7D Radar & Advanced Metrics */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
          
          {/* Left: 7D Radar & Cluster Comparison (7 cols) */}
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

            {/* Radar Chart Component */}
            <RadarChart
              playerStats={pStats}
              clusterStats={cStats}
              playerName={decodedName}
              clusterName={analysis?.role_name || t("radar_benchmark")}
            />

            {/* Tactical Interpretation Box */}
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

          {/* Right: ShotQuality Advanced Metrics & Percentile Bars (5 cols) */}
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
              
              {/* True Shooting % */}
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

              {/* Usage Rate % */}
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

              {/* PER (Player Efficiency Rating) */}
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

              {/* Box Plus-Minus (BPM) */}
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

              {/* VORP */}
              <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-xs">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-bold text-slate-700">{t("metric_vorp")}</span>
                  <span className="font-mono font-extrabold text-amber-700">
                    {advanced?.vorp ? advanced.vorp.toFixed(2) : "2.10"}
                  </span>
                </div>
                <div className="mt-2 h-2.5 w-full overflow-hidden rounded-full bg-slate-100">
                  <div
                    className="h-full rounded-full bg-amber-500 transition-all duration-700"
                    style={{ width: `${Math.min(((advanced?.vorp || 2.1) / 6.0) * 100, 100)}%` }}
                  />
                </div>
              </div>

            </div>
          </div>

        </div>

        {/* 4. Interactive 2D Shot Chart Court Section */}
        <section className="space-y-4">
          <ShotChart
            shots={shots}
            playerName={decodedName}
            seasonLabel={seasonLabel}
          />
        </section>

        {/* 5. Historical Cosine Matching Comps (23 Seasons) */}
        {histMatches && histMatches.matches.length > 0 && (
          <section className="space-y-4">
            <HistoricalComps
              matches={histMatches.matches}
              playerName={decodedName}
            />
          </section>
        )}

        </main>
      </div>

    </div>
  );
}
