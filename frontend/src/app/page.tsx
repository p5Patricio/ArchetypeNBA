"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Search,
  Sparkles,
  Zap,
  Shield,
  Activity,
  Target,
  Award,
} from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { CommandPalette } from "@/components/CommandPalette";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { getPlayers, getSeasons, checkHealth, type PlayerListItem } from "@/lib/api";
import { usePreferences } from "@/context/PreferencesContext";

export default function Home() {
  const { t, language, seasonId, seasonLabel, setSeason } = usePreferences();
  const [players, setPlayers] = useState<PlayerListItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [search, setSearch] = useState<string>("");
  const [isCommandOpen, setIsCommandOpen] = useState<boolean>(false);
  const [dbConnected, setDbConnected] = useState<boolean>(true);

  useEffect(() => {
    checkHealth()
      .then((res) => {
        setDbConnected(Boolean(res.status === "ok" && res.db_connected));
      })
      .catch(() => setDbConnected(false));
  }, []);

  useEffect(() => {
    if (seasonId === null) return;
    setLoading(true);
    getPlayers(undefined, seasonId)
      .then((data) => {
        // Ensure strictly unique players by player_id
        const seen = new Set<number>();
        const uniqueList: PlayerListItem[] = [];
        for (const p of data) {
          if (!seen.has(p.player_id)) {
            seen.add(p.player_id);
            uniqueList.push(p);
          }
        }
        setPlayers(uniqueList);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [seasonId]);

  const filteredPlayers = players.filter(
    (p) =>
      p.player_name.toLowerCase().includes(search.toLowerCase()) ||
      (p.team_name && p.team_name.toLowerCase().includes(search.toLowerCase())) ||
      (p.team_abbreviation && p.team_abbreviation.toLowerCase().includes(search.toLowerCase())) ||
      (p.role_name && p.role_name.toLowerCase().includes(search.toLowerCase()))
  );

  const topScorers = [...players].sort((a, b) => (b.pts || 0) - (a.pts || 0)).slice(0, 8);

  const archetypeClusters = [
    {
      id: 0,
      nameKey: "archetype_0_name" as const,
      descKey: "archetype_0_desc" as const,
      icon: Activity,
      badgeColor: "bg-purple-50 text-purple-700 border-purple-200",
      accent: "border-purple-200 hover:border-purple-400",
      examples: "Giannis Antetokounmpo, Bam Adebayo, Alperen Sengun, Domantas Sabonis",
    },
    {
      id: 1,
      nameKey: "archetype_1_name" as const,
      descKey: "archetype_1_desc" as const,
      icon: Shield,
      badgeColor: "bg-emerald-50 text-emerald-700 border-emerald-200",
      accent: "border-emerald-200 hover:border-emerald-400",
      examples: "Alex Caruso, Jose Alvarado, Dyson Daniels, Marcus Smart, Lu Dort",
    },
    {
      id: 2,
      nameKey: "archetype_2_name" as const,
      descKey: "archetype_2_desc" as const,
      icon: Shield,
      badgeColor: "bg-blue-50 text-blue-700 border-blue-200",
      accent: "border-blue-200 hover:border-blue-400",
      examples: "Jarrett Allen, Rudy Gobert, Clint Capela, Deandre Ayton, Walker Kessler",
    },
    {
      id: 3,
      nameKey: "archetype_3_name" as const,
      descKey: "archetype_3_desc" as const,
      icon: Sparkles,
      badgeColor: "bg-slate-100 text-slate-700 border-slate-200",
      accent: "border-slate-200 hover:border-slate-400",
      examples: "OG Anunoby, Santi Aldama, Harrison Barnes, Royce O'Neale, Jaden McDaniels",
    },
    {
      id: 4,
      nameKey: "archetype_4_name" as const,
      descKey: "archetype_4_desc" as const,
      icon: Zap,
      badgeColor: "bg-orange-50 text-orange-700 border-orange-200",
      accent: "border-orange-200 hover:border-orange-400",
      examples: "Luka Dončić, Shai Gilgeous-Alexander, Jalen Brunson, Donovan Mitchell",
    },
    {
      id: 5,
      nameKey: "archetype_5_name" as const,
      descKey: "archetype_5_desc" as const,
      icon: Target,
      badgeColor: "bg-cyan-50 text-cyan-700 border-cyan-200",
      accent: "border-cyan-200 hover:border-cyan-400",
      examples: "Grayson Allen, Malik Beasley, Bogdan Bogdanović, Klay Thompson, Sam Hauser",
    },
    {
      id: 6,
      nameKey: "archetype_6_name" as const,
      descKey: "archetype_6_desc" as const,
      icon: Sparkles,
      badgeColor: "bg-amber-50 text-amber-700 border-amber-200",
      accent: "border-amber-200 hover:border-amber-400",
      examples: "Mike Conley, Tyrese Haliburton, Chris Paul, Tyus Jones, Spencer Dinwiddie",
    },
  ];

  return (
    <div className="min-h-screen bg-[#F8FAFC] text-slate-900 selection:bg-orange-100 selection:text-orange-900">
      
      {/* Navigation */}
      <Navbar onOpenSearch={() => setIsCommandOpen(true)} />

      <CommandPalette
        isOpen={isCommandOpen}
        onClose={() => setIsCommandOpen(false)}
        seasonId={seasonId}
      />

      <div className="md:pl-64">
        {/* Clean White Hero Section */}
        <section className="relative border-b border-slate-200 bg-white py-14 lg:py-20 shadow-xs">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="flex flex-col items-center text-center space-y-5">
            
            {/* Status Pill */}
            <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3.5 py-1 text-xs font-semibold text-slate-700 shadow-xs">
              <span className={`flex h-2 w-2 rounded-full ${dbConnected ? "bg-emerald-500" : "bg-amber-500"}`} />
              <span>
                {t("active_season")}: <strong className="text-slate-900">{seasonLabel}</strong>
              </span>
              <span className="text-slate-300">•</span>
              <span className="text-slate-500 font-medium">
                {dbConnected ? t("db_connected") : t("db_local")}
              </span>
            </div>

            {/* Solid Clean Headline */}
            <h1 className="max-w-4xl text-4xl sm:text-5xl font-black tracking-tight text-slate-900 leading-tight">
              {t("hero_title")}
            </h1>

            <p className="max-w-2xl text-base sm:text-lg text-slate-600 font-normal leading-relaxed">
              {t("hero_subtitle")}
            </p>

            {/* Live Search Input */}
            <div className="w-full max-w-xl pt-2">
              <div className="relative flex items-center rounded-2xl border-2 border-slate-200 bg-slate-50/70 p-1.5 shadow-sm transition focus-within:border-orange-500 focus-within:bg-white focus-within:ring-4 focus-within:ring-orange-500/10">
                <Search className="ml-3 h-5 w-5 text-orange-500 shrink-0" />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={t("hero_search_placeholder")}
                  className="w-full bg-transparent px-3 py-2 text-sm font-medium text-slate-900 placeholder:text-slate-400 outline-none"
                />
                <button
                  type="button"
                  onClick={() => setIsCommandOpen(true)}
                  className="hidden sm:flex items-center gap-1 rounded-xl border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-500 shadow-xs hover:text-slate-800 transition"
                >
                  <kbd className="font-mono text-[10px]">⌘K</kbd>
                </button>
              </div>
            </div>

          </div>
        </div>
      </section>

      {/* Main Content Area */}
      <main className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-10 space-y-14">
        
        {/* Real Season Leaders / Search Grid */}
        <section className="space-y-5">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <div>
              <h2 className="text-xl font-extrabold tracking-tight text-slate-900 flex items-center gap-2">
                <Award className="h-5 w-5 text-orange-600" />
                {search
                  ? `${t("search_results_title")} (${filteredPlayers.length})`
                  : `${t("season_leaders_title")} ${seasonLabel}`}
              </h2>
              <p className="text-xs font-medium text-slate-500 mt-0.5">
                {t("season_leaders_desc", { season: seasonLabel })}
              </p>
            </div>
            <span className="self-start sm:self-auto rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-mono font-semibold text-slate-600 shadow-xs">
              {t("players_loaded", { count: filteredPlayers.length })}
            </span>
          </div>

          {loading ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              {[...Array(8)].map((_, i) => (
                <div key={i} className="h-32 rounded-2xl border border-slate-200 bg-white p-4 animate-pulse shadow-xs" />
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              {(search ? filteredPlayers.slice(0, 16) : topScorers).map((player, idx) => (
                <Link
                  key={`${player.player_id}-${idx}`}
                  href={`/player/${encodeURIComponent(player.player_name)}`}
                  className="group rounded-2xl border border-slate-200 bg-white p-4 shadow-xs hover:border-orange-300 hover:shadow-md transition-all flex flex-col justify-between"
                >
                  <div>
                    <div className="flex items-start gap-3">
                      <PlayerAvatar
                        playerId={player.player_id}
                        playerName={player.player_name}
                        headshotUrl={player.headshot_url}
                        size={52}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-bold text-slate-700">
                            {player.team_abbreviation || player.team_name || "NBA"}
                          </span>
                        </div>
                        <h3 className="mt-1 text-sm font-bold text-slate-900 group-hover:text-orange-600 transition truncate">
                          {player.player_name}
                        </h3>
                        <p className="text-[11px] font-medium text-sky-700 truncate mt-0.5">
                          {player.role_name || "NBA Player"}
                        </p>
                      </div>
                    </div>
                  </div>

                  <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-2.5 text-xs">
                    <div className="text-left">
                      <span className="text-[10px] uppercase font-bold text-slate-400">{t("pts_label")}</span>
                      <div className="font-mono text-sm font-extrabold text-slate-900">
                        {player.pts ? player.pts.toFixed(1) : 0}
                      </div>
                    </div>
                    <div className="text-center">
                      <span className="text-[10px] uppercase font-bold text-slate-400">{t("reb_label")}</span>
                      <div className="font-mono text-sm font-extrabold text-slate-900">
                        {player.reb ? player.reb.toFixed(1) : 0}
                      </div>
                    </div>
                    <div className="text-right">
                      <span className="text-[10px] uppercase font-bold text-slate-400">{t("ast_label")}</span>
                      <div className="font-mono text-sm font-extrabold text-slate-900">
                        {player.ast ? player.ast.toFixed(1) : 0}
                      </div>
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </section>

        {/* 5 Tactical Archetypes Grid */}
        <section className="space-y-5">
          <div>
            <h2 className="text-xl font-extrabold tracking-tight text-slate-900 flex items-center gap-2">
              <Zap className="h-5 w-5 text-sky-600" />
              {t("taxonomy_title")}
            </h2>
            <p className="text-xs font-medium text-slate-500 mt-0.5">
              {t("taxonomy_subtitle")}
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {archetypeClusters.map((cluster) => {
              const Icon = cluster.icon;
              return (
                <div
                  key={cluster.id}
                  className={`rounded-2xl border bg-white p-5 shadow-xs transition-all flex flex-col justify-between ${cluster.accent}`}
                >
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <div className={`p-2 rounded-xl border ${cluster.badgeColor}`}>
                        <Icon className="h-5 w-5" />
                      </div>
                      <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-0.5 font-mono text-[10px] font-bold text-slate-600">
                        {t("cluster_label")} #{cluster.id + 1}
                      </span>
                    </div>

                    <div>
                      <h3 className="text-base font-bold text-slate-900">
                        {t(cluster.nameKey)}
                      </h3>
                      <p className="mt-1.5 text-xs text-slate-600 leading-relaxed font-medium">
                        {t(cluster.descKey)}
                      </p>
                    </div>
                  </div>

                  <div className="border-t border-slate-100 pt-3 mt-4">
                    <span className="text-[10px] uppercase font-bold tracking-wider text-slate-400">
                      {t("archetype_examples_label")}
                    </span>
                    <p className="text-xs font-semibold text-slate-800 mt-0.5">
                      {cluster.examples}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        </section>

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
