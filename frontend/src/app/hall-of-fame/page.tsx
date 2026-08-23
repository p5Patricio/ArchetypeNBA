"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Award,
  Crown,
  Search,
  Sparkles,
  Shield,
  Medal,
  GraduationCap,
  Globe,
  Flame,
  ArrowUpRight,
  TrendingUp,
} from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { CommandPalette } from "@/components/CommandPalette";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { getHallOfFame, type HOFPlayerItem } from "@/lib/api";
import { usePreferences } from "@/context/PreferencesContext";

export default function HallOfFamePage() {
  const { t, language } = usePreferences();
  const [hofList, setHofList] = useState<HOFPlayerItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [filterTab, setFilterTab] = useState<"all" | "inducted" | "active" | "international">("all");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [isCommandOpen, setIsCommandOpen] = useState<boolean>(false);

  useEffect(() => {
    setLoading(true);
    getHallOfFame()
      .then((data) => setHofList(data))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const filteredList = hofList.filter((player) => {
    // Tab filter
    if (filterTab === "inducted" && player.status !== "inducted") return false;
    if (filterTab === "active" && !player.status.startsWith("active")) return false;
    if (filterTab === "international" && player.olympic_medals.length === 0 && player.fiba_accolades.length === 0) {
      return false;
    }

    // Search query
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return (
      player.player_name.toLowerCase().includes(q) ||
      player.team_abbreviation.toLowerCase().includes(q) ||
      player.primary_archetype.toLowerCase().includes(q)
    );
  });

  return (
    <div className="min-h-screen bg-[#F8FAFC] text-slate-900 selection:bg-amber-100 selection:text-amber-900">
      
      {/* Navigation */}
      <Navbar onOpenSearch={() => setIsCommandOpen(true)} />

      <CommandPalette
        isOpen={isCommandOpen}
        onClose={() => setIsCommandOpen(false)}
      />

      <div className="md:pl-64">
        {/* Hero Section */}
        <section className="relative border-b border-slate-200 bg-gradient-to-b from-amber-50/40 via-white to-white py-14 lg:py-20 shadow-xs">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="flex flex-col items-center text-center space-y-5">
            
            {/* Crown Tag */}
            <div className="inline-flex items-center gap-2 rounded-full border border-amber-300 bg-amber-50 px-4 py-1 text-xs font-black text-amber-800 shadow-2xs">
              <Crown className="h-3.5 w-3.5 text-amber-600" />
              <span>NAISMITH MEMORIAL BASKETBALL HALL OF FAME</span>
            </div>

            {/* Headline */}
            <h1 className="max-w-4xl text-4xl sm:text-5xl font-black tracking-tight text-slate-900 leading-tight">
              {t("hof_page_title")}
            </h1>

            <p className="max-w-3xl text-base sm:text-lg text-slate-600 font-normal leading-relaxed">
              {t("hof_page_subtitle")}
            </p>

            {/* Search Bar */}
            <div className="w-full max-w-xl pt-2">
              <div className="relative flex items-center rounded-2xl border-2 border-slate-200 bg-white p-1.5 shadow-sm transition focus-within:border-amber-500 focus-within:ring-4 focus-within:ring-amber-500/10">
                <Search className="ml-3 h-5 w-5 text-amber-500 shrink-0" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder={language === "es" ? "Buscar leyenda o candidato..." : "Search legend or contender..."}
                  className="w-full bg-transparent px-3 py-2 text-sm font-medium text-slate-900 placeholder:text-slate-400 outline-none"
                />
              </div>
            </div>

          </div>
        </div>
      </section>

      {/* Main Content Area */}
      <main className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-10 space-y-8">
        
        {/* Filter Tabs Bar */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-200 pb-4">
          <div className="flex items-center rounded-2xl border border-slate-200 bg-white p-1 shadow-xs flex-wrap gap-1">
            <button
              onClick={() => setFilterTab("all")}
              className={`rounded-xl px-4 py-1.5 text-xs font-bold transition ${
                filterTab === "all"
                  ? "bg-slate-900 text-white shadow-xs"
                  : "text-slate-600 hover:text-slate-900"
              }`}
            >
              {t("hof_tab_all", { count: hofList.length })}
            </button>
            <button
              onClick={() => setFilterTab("inducted")}
              className={`flex items-center gap-1.5 rounded-xl px-4 py-1.5 text-xs font-bold transition ${
                filterTab === "inducted"
                  ? "bg-amber-500 text-white shadow-xs"
                  : "text-slate-600 hover:text-slate-900"
              }`}
            >
              👑 {t("hof_tab_inducted")}
            </button>
            <button
              onClick={() => setFilterTab("active")}
              className={`flex items-center gap-1.5 rounded-xl px-4 py-1.5 text-xs font-bold transition ${
                filterTab === "active"
                  ? "bg-orange-600 text-white shadow-xs"
                  : "text-slate-600 hover:text-slate-900"
              }`}
            >
              ⚡ {t("hof_tab_active")}
            </button>
            <button
              onClick={() => setFilterTab("international")}
              className={`flex items-center gap-1.5 rounded-xl px-4 py-1.5 text-xs font-bold transition ${
                filterTab === "international"
                  ? "bg-sky-600 text-white shadow-xs"
                  : "text-slate-600 hover:text-slate-900"
              }`}
            >
              🥇 {t("hof_tab_international")}
            </button>
          </div>

          <span className="text-xs font-semibold text-slate-500">
            {filteredList.length} {language === "es" ? "figuras encontradas" : "figures listed"}
          </span>
        </div>

        {/* Player Cards Grid */}
        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {[...Array(6)].map((_, i) => (
              <div key={i} className="h-64 rounded-3xl border border-slate-200 bg-white p-6 animate-pulse shadow-xs" />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {filteredList.map((player) => {
              const isInducted = player.status === "inducted";
              const isLock = player.status === "active_lock";
              const probPercent = Math.round(player.hof_probability * 100);

              return (
                <div
                  key={player.player_id}
                  className="rounded-3xl border border-slate-200 bg-white p-6 shadow-xs hover:border-slate-300 hover:shadow-md transition-all flex flex-col justify-between space-y-5"
                >
                  {/* Card Header */}
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex items-start gap-4">
                      <PlayerAvatar
                        playerId={player.player_id}
                        playerName={player.player_name}
                        headshotUrl={player.headshot_url}
                        size={68}
                        className="border-2 border-slate-200 shadow-sm shrink-0"
                      />
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="rounded bg-slate-100 px-2 py-0.5 font-mono text-xs font-bold text-slate-700">
                            {player.team_abbreviation}
                          </span>
                          <span className="text-xs font-semibold text-slate-400">
                            {player.career_span}
                          </span>
                        </div>
                        <h2 className="text-xl font-black text-slate-900 mt-1">
                          {player.player_name}
                        </h2>
                        <p className="text-xs font-semibold text-sky-700 mt-0.5">
                          {player.primary_archetype}
                        </p>
                      </div>
                    </div>

                    {/* HOF Probability / Induction Badge */}
                    <div className="text-right shrink-0">
                      {isInducted ? (
                        <div className="inline-flex items-center gap-1.5 rounded-full border border-amber-300 bg-amber-50 px-3 py-1 text-xs font-black text-amber-800 shadow-2xs">
                          👑 {t("hof_inducted_year", { year: player.induction_year || 2020 })}
                        </div>
                      ) : (
                        <div className="flex flex-col items-end">
                          <span className="text-[10px] uppercase font-bold text-slate-400">
                            {t("hof_prob_label")}
                          </span>
                          <div className={`font-mono text-lg font-black ${isLock ? "text-emerald-600" : "text-orange-600"}`}>
                            {probPercent === 100 ? "100%" : `${(player.hof_probability * 100).toFixed(1)}%`}
                          </div>
                          <span className={`text-[10px] font-bold ${isLock ? "text-emerald-700" : "text-orange-600"}`}>
                            {isLock ? t("hof_status_lock") : (probPercent > 80 ? t("hof_status_high") : t("hof_status_rising"))}
                          </span>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Accolades Counters Pills */}
                  <div className="flex flex-wrap gap-2 border-y border-slate-100 py-3">
                    {player.nba_championships > 0 && (
                      <span className="inline-flex items-center gap-1 rounded-lg border border-amber-200 bg-amber-50/80 px-2.5 py-1 text-xs font-black text-amber-800">
                        🏆 {t("hof_rings", { count: player.nba_championships })}
                      </span>
                    )}
                    {player.mvp_count > 0 && (
                      <span className="inline-flex items-center gap-1 rounded-lg border border-orange-200 bg-orange-50/80 px-2.5 py-1 text-xs font-black text-orange-800">
                        🌟 {t("hof_mvps", { count: player.mvp_count })}
                      </span>
                    )}
                    {player.finals_mvp_count > 0 && (
                      <span className="inline-flex items-center gap-1 rounded-lg border border-red-200 bg-red-50/80 px-2.5 py-1 text-xs font-black text-red-800">
                        🏅 {t("hof_fmvps", { count: player.finals_mvp_count })}
                      </span>
                    )}
                    {player.all_star_count > 0 && (
                      <span className="inline-flex items-center gap-1 rounded-lg border border-blue-200 bg-blue-50/80 px-2.5 py-1 text-xs font-bold text-blue-800">
                        ⭐ {t("hof_allstars", { count: player.all_star_count })}
                      </span>
                    )}
                    {player.all_nba_count > 0 && (
                      <span className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-100 px-2.5 py-1 text-xs font-bold text-slate-800">
                        🎖️ {t("hof_allnba", { count: player.all_nba_count })}
                      </span>
                    )}
                    {player.dpoy_count > 0 && (
                      <span className="inline-flex items-center gap-1 rounded-lg border border-emerald-200 bg-emerald-50/80 px-2.5 py-1 text-xs font-bold text-emerald-800">
                        🛡️ {t("hof_dpoy", { count: player.dpoy_count })}
                      </span>
                    )}
                  </div>

                  {/* International, FIBA & NCAA Accolades */}
                  {(player.olympic_medals.length > 0 || player.fiba_accolades.length > 0 || player.ncaa_accolades.length > 0) && (
                    <div className="space-y-2 rounded-2xl border border-slate-100 bg-slate-50/70 p-3 text-xs">
                      {player.olympic_medals.length > 0 && (
                        <div className="flex items-start gap-2">
                          <span className="font-bold text-slate-600 shrink-0 flex items-center gap-1">
                            <Medal className="h-3.5 w-3.5 text-amber-500" />
                            {t("hof_olympics_title")}
                          </span>
                          <span className="font-semibold text-slate-800">
                            {player.olympic_medals.join(" • ")}
                          </span>
                        </div>
                      )}

                      {player.fiba_accolades.length > 0 && (
                        <div className="flex items-start gap-2">
                          <span className="font-bold text-slate-600 shrink-0 flex items-center gap-1">
                            <Globe className="h-3.5 w-3.5 text-sky-500" />
                            FIBA:
                          </span>
                          <span className="font-semibold text-slate-800">
                            {player.fiba_accolades.join(" • ")}
                          </span>
                        </div>
                      )}

                      {player.ncaa_accolades.length > 0 && (
                        <div className="flex items-start gap-2">
                          <span className="font-bold text-slate-600 shrink-0 flex items-center gap-1">
                            <GraduationCap className="h-3.5 w-3.5 text-indigo-500" />
                            {t("hof_ncaa_title")}
                          </span>
                          <span className="font-semibold text-slate-800">
                            {player.ncaa_accolades.join(" • ")}
                          </span>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Career Peak Metrics & Tactical Summary */}
                  <div className="space-y-3">
                    <div className="grid grid-cols-4 gap-2 text-center text-xs">
                      <div className="rounded-xl border border-slate-100 bg-slate-50 p-2">
                        <div className="text-[10px] uppercase font-bold text-slate-400">PPG</div>
                        <div className="font-mono text-sm font-black text-slate-900">{player.career_ppg.toFixed(1)}</div>
                      </div>
                      <div className="rounded-xl border border-slate-100 bg-slate-50 p-2">
                        <div className="text-[10px] uppercase font-bold text-slate-400">RPG</div>
                        <div className="font-mono text-sm font-black text-slate-900">{player.career_rpg.toFixed(1)}</div>
                      </div>
                      <div className="rounded-xl border border-slate-100 bg-slate-50 p-2">
                        <div className="text-[10px] uppercase font-bold text-slate-400">APG</div>
                        <div className="font-mono text-sm font-black text-slate-900">{player.career_apg.toFixed(1)}</div>
                      </div>
                      <div className="rounded-xl border border-slate-100 bg-slate-50 p-2">
                        <div className="text-[10px] uppercase font-bold text-slate-400">PEAK PER</div>
                        <div className="font-mono text-sm font-black text-orange-600">{player.peak_per.toFixed(1)}</div>
                      </div>
                    </div>

                    <p className="text-xs font-medium text-slate-600 leading-relaxed">
                      {language === "es" ? player.tactical_summary : player.tactical_summary_en}
                    </p>
                  </div>

                  {/* Card Footer Link */}
                  <div className="border-t border-slate-100 pt-3">
                    <Link
                      href={`/player/${encodeURIComponent(player.player_name)}`}
                      className="group flex items-center justify-between text-xs font-bold text-slate-700 hover:text-orange-600 transition"
                    >
                      <span>{language === "es" ? "Ver Scouting Lab & Radar 7D" : "Inspect Scouting Lab & 7D Radar"}</span>
                      <ArrowUpRight className="h-4 w-4 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-transform" />
                    </Link>
                  </div>

                </div>
              );
            })}
          </div>
        )}

      </main>

      {/* Clean Footer */}
      <footer className="border-t border-slate-200 bg-white py-8 text-center text-xs text-slate-500">
        <div className="mx-auto max-w-7xl px-4 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <span className="font-black text-slate-900">Archetype<span className="text-orange-600">NBA</span></span>
            <span>•</span>
            <span>{t("footer_engine")}</span>
          </div>
          <div>
            <span>{t("footer_db_info")}</span>
          </div>
        </div>
      </footer>

      </div>
    </div>
  );
}
