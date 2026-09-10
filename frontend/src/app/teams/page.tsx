"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Navbar } from "@/components/Navbar";
import { CommandPalette } from "@/components/CommandPalette";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { TeamLogo } from "@/components/TeamLogo";
import { getTeams, getPlayers, type Team, type PlayerListItem } from "@/lib/api";
import { usePreferences } from "@/context/PreferencesContext";
import {
  Shield,
  Search,
  Users,
  Award,
  ArrowUpRight,
  TrendingUp,
  MapPin,
  Flame,
} from "lucide-react";

export default function TeamsPage() {
  const { t, language, seasonId, seasonLabel } = usePreferences();
  const [teams, setTeams] = useState<Team[]>([]);
  const [selectedTeam, setSelectedTeam] = useState<Team | null>(null);
  const [roster, setRoster] = useState<PlayerListItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [conference, setConference] = useState<"ALL" | "East" | "West">("ALL");
  const [searchTeam, setSearchTeam] = useState<string>("");
  const [isCommandOpen, setIsCommandOpen] = useState<boolean>(false);

  useEffect(() => {
    setLoading(true);
    getTeams()
      .then((data) => {
        setTeams(data);
        if (data.length > 0) {
          // Default to Boston Celtics or first team
          const defaultTeam = data.find((t) => t.abbreviation === "BOS") || data[0];
          setSelectedTeam(defaultTeam);
        }
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (selectedTeam && seasonId) {
      getPlayers(selectedTeam.abbreviation, seasonId)
        .then((data) => setRoster(data))
        .catch(console.error);
    }
  }, [selectedTeam, seasonId]);

  const filteredTeams = teams.filter((t) => {
    if (conference !== "ALL" && t.conference !== conference) return false;
    if (!searchTeam.trim()) return true;
    const q = searchTeam.toLowerCase();
    return (
      t.full_name.toLowerCase().includes(q) ||
      t.city.toLowerCase().includes(q) ||
      t.abbreviation.toLowerCase().includes(q) ||
      t.division.toLowerCase().includes(q)
    );
  });

  return (
    <div className="min-h-screen bg-[#F8FAFC] text-slate-900 selection:bg-orange-100 selection:text-orange-900">
      
      {/* Navigation */}
      <Navbar
        onOpenSearch={() => setIsCommandOpen(true)}
      />

      <CommandPalette
        isOpen={isCommandOpen}
        onClose={() => setIsCommandOpen(false)}
        seasonId={seasonId}
      />

      <div className="md:pl-64">
        {/* Main Content Area */}
        <main className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        
        {/* Header with Conference Filter & Search */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-200 pb-6">
          <div>
            <div className="flex items-center gap-2">
              <span className="p-1.5 rounded-xl bg-sky-50 border border-sky-200 text-sky-600">
                <Shield className="h-4 w-4" />
              </span>
              <h1 className="text-xl font-extrabold tracking-tight text-slate-900">
                {t("teams_title")}
              </h1>
            </div>
            <p className="text-xs font-medium text-slate-500 mt-1">
              {t("teams_subtitle", { season: seasonLabel })}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {/* Team Search Input */}
            <div className="relative flex items-center rounded-xl border border-slate-200 bg-white px-3 py-1.5 w-full sm:w-56 focus-within:border-sky-500 transition shadow-2xs">
              <Search className="h-3.5 w-3.5 text-slate-400 mr-2 shrink-0" />
              <input
                type="text"
                value={searchTeam}
                onChange={(e) => setSearchTeam(e.target.value)}
                placeholder={language === "es" ? "Buscar franquicia..." : "Search team..."}
                className="w-full bg-transparent text-xs font-medium text-slate-900 placeholder:text-slate-400 outline-none"
              />
            </div>

            {/* Conference Tabs */}
            <div className="flex items-center rounded-xl border border-slate-200 bg-white p-1 shadow-2xs">
              <button
                onClick={() => setConference("ALL")}
                className={`rounded-lg px-3 py-1 text-xs font-bold transition ${
                  conference === "ALL"
                    ? "bg-slate-900 text-white shadow-xs"
                    : "text-slate-600 hover:text-slate-900"
                }`}
              >
                {t("conf_all")} (30)
              </button>
              <button
                onClick={() => setConference("East")}
                className={`rounded-lg px-3 py-1 text-xs font-bold transition ${
                  conference === "East"
                    ? "bg-sky-50 text-sky-700 border border-sky-200 shadow-xs"
                    : "text-slate-600 hover:text-slate-900"
                }`}
              >
                {t("conf_east")}
              </button>
              <button
                onClick={() => setConference("West")}
                className={`rounded-lg px-3 py-1 text-xs font-bold transition ${
                  conference === "West"
                    ? "bg-orange-50 text-orange-700 border border-orange-200 shadow-xs"
                    : "text-slate-600 hover:text-slate-900"
                }`}
              >
                {t("conf_west")}
              </button>
            </div>
          </div>
        </div>

        {/* Dual Layout: Teams Grid + Selected Team Roster */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
          
          {/* Teams Grid (7 cols) */}
          <div className="lg:col-span-7 space-y-4">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500 flex items-center justify-between">
              <span>{t("franchises_list_title", { count: filteredTeams.length })}</span>
              <span className="text-[11px] font-normal text-slate-400">{t("select_team_hint")}</span>
            </h2>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-h-[700px] overflow-y-auto pr-1">
              {filteredTeams.map((tItem) => {
                const isSelected = selectedTeam?.abbreviation === tItem.abbreviation;
                return (
                  <button
                    key={tItem.id}
                    onClick={() => setSelectedTeam(tItem)}
                    className={`group rounded-2xl border p-4 text-left transition-all shadow-xs flex items-center gap-3.5 cursor-pointer ${
                      isSelected
                        ? "border-sky-500 bg-sky-50/60 ring-2 ring-sky-500/20"
                        : "border-slate-200 bg-white hover:border-slate-300 hover:shadow-sm"
                    }`}
                  >
                    {/* Official Franchise Logo */}
                    <TeamLogo
                      teamId={tItem.id}
                      abbreviation={tItem.abbreviation}
                      teamName={tItem.full_name}
                      size={44}
                      className="p-1 rounded-xl bg-slate-50/80 border border-slate-100 group-hover:scale-105 transition"
                    />

                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-1">
                        <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider truncate">
                          {tItem.city}
                        </span>
                        <span className="rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.2 font-mono text-[10px] font-extrabold text-slate-800 shrink-0">
                          {tItem.abbreviation}
                        </span>
                      </div>
                      
                      <div className="text-sm font-black text-slate-900 truncate mt-0.5">
                        {tItem.full_name}
                      </div>

                      <div className="flex items-center gap-2 text-[10px] font-semibold text-slate-500 mt-1">
                        <span className="text-sky-700">{tItem.conference}</span>
                        <span>•</span>
                        <span className="text-slate-400 truncate">{tItem.division}</span>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Roster & Tactical Breakdown (5 cols) */}
          <div className="lg:col-span-5 space-y-4">
            {selectedTeam ? (
              <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-xs sticky top-24 space-y-5">
                
                {/* Team Header with Official Logo & Badges */}
                <div className="flex items-center justify-between border-b border-slate-100 pb-5">
                  <div className="flex items-center gap-4">
                    <TeamLogo
                      teamId={selectedTeam.id}
                      abbreviation={selectedTeam.abbreviation}
                      teamName={selectedTeam.full_name}
                      size={64}
                      className="p-1.5 rounded-2xl bg-slate-50 border border-slate-200 shadow-2xs"
                    />
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="rounded-full border border-sky-200 bg-sky-50 px-2 py-0.5 text-[10px] font-bold text-sky-700">
                          {selectedTeam.conference.toUpperCase()}
                        </span>
                        <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-bold text-slate-600">
                          {selectedTeam.division}
                        </span>
                      </div>
                      <h2 className="text-xl font-black text-slate-900 mt-1 leading-tight">
                        {selectedTeam.full_name}
                      </h2>
                      <span className="text-xs font-semibold text-slate-500">
                        {t("roster_season_count", { season: seasonLabel, count: roster.length })}
                      </span>
                    </div>
                  </div>

                  <span className="text-3xl font-black text-slate-200 font-mono hidden sm:inline">
                    {selectedTeam.abbreviation}
                  </span>
                </div>

                {/* Roster List */}
                <div className="space-y-2 max-h-[500px] overflow-y-auto pr-1">
                  {roster.length === 0 ? (
                    <div className="py-12 text-center text-xs text-slate-400 font-medium">
                      {t("no_roster_data")}
                    </div>
                  ) : (
                    roster.map((p, idx) => (
                      <Link
                        key={`${p.player_id}-${idx}`}
                        href={`/player/${encodeURIComponent(p.player_name)}`}
                        className="group flex items-center justify-between rounded-xl border border-slate-100 bg-slate-50/50 p-2.5 hover:border-orange-200 hover:bg-orange-50/60 transition"
                      >
                        <div className="flex items-center gap-3">
                          <PlayerAvatar
                            playerId={p.player_id}
                            playerName={p.player_name}
                            headshotUrl={p.headshot_url}
                            size={42}
                          />
                          <div className="min-w-0">
                            <div className="text-xs font-bold text-slate-900 group-hover:text-orange-600 transition truncate">
                              {p.player_name}
                            </div>
                            <div className="text-[11px] text-sky-700 font-semibold truncate">
                              {p.role_name || "NBA Player"}
                            </div>
                          </div>
                        </div>

                        <div className="flex items-center gap-3 text-right shrink-0">
                          <div>
                            <div className="text-[9px] uppercase font-bold text-slate-400">PPG</div>
                            <div className="font-mono text-xs font-black text-slate-900">
                              {p.pts ? p.pts.toFixed(1) : 0}
                            </div>
                          </div>
                          <div>
                            <div className="text-[9px] uppercase font-bold text-slate-400">RPG</div>
                            <div className="font-mono text-xs font-black text-slate-900">
                              {p.reb ? p.reb.toFixed(1) : 0}
                            </div>
                          </div>
                          <div>
                            <div className="text-[9px] uppercase font-bold text-slate-400">APG</div>
                            <div className="font-mono text-xs font-black text-slate-900">
                              {p.ast ? p.ast.toFixed(1) : 0}
                            </div>
                          </div>
                          <ArrowUpRight className="h-3.5 w-3.5 text-slate-300 group-hover:text-orange-600 transition-colors ml-1" />
                        </div>
                      </Link>
                    ))
                  )}
                </div>

              </div>
            ) : (
              <div className="rounded-3xl border border-slate-200 bg-white p-12 text-center text-xs text-slate-500 font-medium">
                {t("select_team_prompt")}
              </div>
            )}
          </div>

        </div>

        </main>
      </div>

    </div>
  );
}
