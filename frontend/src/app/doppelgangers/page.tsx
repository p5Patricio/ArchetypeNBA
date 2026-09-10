"use client";

import React, { useState, useEffect } from "react";
import { usePreferences } from "@/context/PreferencesContext";
import { Navbar } from "@/components/Navbar";
import { CommandPalette } from "@/components/CommandPalette";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { Users, Search, Sparkles, Trophy, ArrowRight, Activity, ArrowLeft } from "lucide-react";
import Link from "next/link";
import { API_BASE } from "@/lib/api";

interface DoppelgangerMatch {
  similar_player_id: number;
  player_name: string;
  headshot_url: string;
  season_label: string;
  age_in_season?: number;
  similarity_pct: number;
  archetype_name_es: string;
  archetype_name_en: string;
  archetype_color: string;
  shared_traits_es: string[];
  shared_traits_en: string[];
  key_comparison_stats: Record<string, { target: number; comp: number }>;
}

interface DoppelgangerData {
  target_player_id: number;
  target_player_name: string;
  target_season_label: string;
  target_position: string;
  matches: DoppelgangerMatch[];
  scouting_takeaway_es: string;
  scouting_takeaway_en: string;
}

const POPULAR_PLAYERS = [
  "Stephen Curry",
  "Nikola Jokic",
  "LeBron James",
  "Luka Doncic",
  "Victor Wembanyama",
  "Michael Jordan",
  "Kobe Bryant",
  "Giannis Antetokounmpo",
];

export default function DoppelgangersPage() {
  const { language, t } = usePreferences();
  const [searchQuery, setSearchQuery] = useState("Stephen Curry");
  const [isCommandOpen, setIsCommandOpen] = useState(false);
  const [selectedPlayer, setSelectedPlayer] = useState("Stephen Curry");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<DoppelgangerData | null>(null);
  const [playerList, setPlayerList] = useState<string[]>([]);
  const [suggestions, setSuggestions] = useState<string[]>([]);

  // Fetch all players for autocomplete
  useEffect(() => {
    fetch(`${API_BASE}/players`)
      .then((res) => res.json())
      .then((names: string[]) => setPlayerList(names))
      .catch(() => {});
  }, []);

  // Filter autocomplete suggestions
  useEffect(() => {
    if (searchQuery.trim().length > 1) {
      const q = searchQuery.toLowerCase();
      setSuggestions(playerList.filter((n) => n.toLowerCase().includes(q)).slice(0, 6));
    } else {
      setSuggestions([]);
    }
  }, [searchQuery, playerList]);

  // Fetch doppelgangers when selectedPlayer changes
  useEffect(() => {
    if (!selectedPlayer) return;
    setLoading(true);
    setError(null);

    fetch(`${API_BASE}/doppelgangers?player_id_or_name=${encodeURIComponent(selectedPlayer)}&top_k=6`)
      .then((res) => {
        if (!res.ok) throw new Error("Failed to calculate historical doppelgängers");
        return res.json();
      })
      .then((resData: DoppelgangerData) => {
        setData(resData);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, [selectedPlayer]);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 md:pl-64 pb-20">
      <Navbar onOpenSearch={() => setIsCommandOpen(true)} />
      <CommandPalette isOpen={isCommandOpen} onClose={() => setIsCommandOpen(false)} />

      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8 space-y-8">
        {/* Back Link */}
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-xs font-bold text-slate-500 hover:text-slate-900 transition-colors uppercase tracking-wider"
        >
          <ArrowLeft className="h-4 w-4" />
          {t("nav_scouting_hub")}
        </Link>

        {/* Header Title Section */}
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 border-b border-slate-200/80 pb-6">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-purple-600 text-white shadow-md shadow-purple-600/20">
              <Users className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-2xl sm:text-3xl font-black tracking-tight text-slate-900 flex items-center gap-2">
                {language === "es" ? "Doppelgängers Históricos" : "Historical Doppelgängers"}
                <span className="rounded-md border border-purple-200 bg-purple-50 px-2 py-0.5 text-[10px] font-black uppercase text-purple-800 tracking-wider">
                  40-Year Cosine Engine
                </span>
              </h1>
              <p className="text-xs sm:text-sm font-medium text-slate-500 mt-0.5 max-w-3xl">
                {language === "es"
                  ? "Búsqueda multidimensional de clones estadísticos y similitud táctica a lo largo de 40 años de historia de la NBA."
                  : "Multi-dimensional statistical clone matchmaking across 40 years of NBA historical player cohorts."}
              </p>
            </div>
          </div>
        </div>

        {/* Search & Quick Preset Chips */}
        <div className="rounded-3xl border border-slate-200 bg-white p-5 shadow-xs space-y-4">
          <div className="relative">
            <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none text-slate-400">
              <Search className="h-4 w-4" />
            </div>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && suggestions.length > 0) {
                  setSelectedPlayer(suggestions[0]);
                  setSearchQuery(suggestions[0]);
                  setSuggestions([]);
                }
              }}
              placeholder={
                language === "es"
                  ? "Buscar jugador para emparejar clones (ej. Stephen Curry, LeBron James, Nikola Jokic)..."
                  : "Search player to find historical clones (e.g. Stephen Curry, LeBron James, Nikola Jokic)..."
              }
              className="w-full pl-11 pr-4 py-3 bg-slate-50 border border-slate-200 rounded-2xl text-slate-900 text-sm placeholder-slate-400 focus:outline-none focus:border-purple-500 focus:bg-white focus:ring-2 focus:ring-purple-500/20 transition"
            />

            {/* Autocomplete Dropdown */}
            {suggestions.length > 0 && (
              <div className="absolute top-full left-0 right-0 mt-2 bg-white border border-slate-200 rounded-2xl overflow-hidden z-50 shadow-xl divide-y divide-slate-100">
                {suggestions.map((name, idx) => (
                  <button
                    key={idx}
                    onClick={() => {
                      setSelectedPlayer(name);
                      setSearchQuery(name);
                      setSuggestions([]);
                    }}
                    className="w-full px-5 py-3 text-left text-xs font-semibold text-slate-700 hover:bg-purple-50 hover:text-purple-900 flex items-center justify-between transition"
                  >
                    <span>{name}</span>
                    <span className="text-[10px] text-purple-600 font-mono font-bold">Seleccionar →</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Quick Preset Buttons */}
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <span className="text-xs font-bold uppercase text-slate-400 mr-1">
              {language === "es" ? "Explorar Casos Rápidos:" : "Quick Cases:"}
            </span>
            {POPULAR_PLAYERS.map((p) => (
              <button
                key={p}
                onClick={() => {
                  setSelectedPlayer(p);
                  setSearchQuery(p);
                }}
                className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all ${
                  selectedPlayer === p
                    ? "bg-purple-600 text-white shadow-xs"
                    : "bg-slate-100 text-slate-700 hover:bg-slate-200 border border-slate-200/60"
                }`}
              >
                {p}
              </button>
            ))}
          </div>
        </div>

        {/* Loading State */}
        {loading && (
          <div className="flex flex-col items-center justify-center py-16 space-y-3">
            <div className="w-9 h-9 border-3 border-purple-600 border-t-transparent rounded-full animate-spin" />
            <p className="text-xs font-bold text-slate-500 font-mono">
              {language === "es" ? "Calculando vectores de similitud de coseno..." : "Computing multi-dimensional cosine vectors..."}
            </p>
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="p-4 bg-rose-50 border border-rose-200 rounded-2xl text-rose-700 text-xs font-semibold">
            {error}
          </div>
        )}

        {/* Match Results */}
        {!loading && data && data.matches && (
          <div className="space-y-6">
            {/* Target Player Card Header */}
            <div className="bg-white border border-purple-200 rounded-3xl p-6 sm:p-7 shadow-xs flex flex-col md:flex-row md:items-center justify-between gap-6">
              <div className="flex items-center gap-4">
                <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-purple-50 border border-purple-200 font-mono text-2xl font-black text-purple-700">
                  🧬
                </div>
                <div>
                  <div className="text-[10px] font-extrabold uppercase text-purple-600 tracking-wider">
                    {language === "es" ? "Jugador Analizado" : "Target Analyzed Player"}
                  </div>
                  <h2 className="text-2xl font-black text-slate-900">{data.target_player_name}</h2>
                  <p className="text-xs font-medium text-slate-500 mt-0.5">
                    {data.target_season_label} • {data.target_position}
                  </p>
                </div>
              </div>

              <div className="bg-purple-50/60 border border-purple-100 rounded-2xl p-4 max-w-md">
                <div className="text-[10px] uppercase font-bold text-purple-800 tracking-wider flex items-center gap-1.5">
                  <Sparkles className="h-3.5 w-3.5 text-purple-600" />
                  {language === "es" ? "Diagnóstico de Scouting" : "Scouting Takeaway"}
                </div>
                <p className="text-xs text-slate-700 mt-1.5 leading-relaxed font-medium">
                  {language === "es" ? data.scouting_takeaway_es : data.scouting_takeaway_en}
                </p>
              </div>
            </div>

            {/* Top 6 Matches Grid */}
            <div className="space-y-4">
              <h3 className="text-base font-extrabold text-slate-900 flex items-center justify-between">
                <span>{language === "es" ? "Clones Históricos de Mayor Coincidencia" : "Top Historical Matches"}</span>
                <span className="text-xs font-semibold text-slate-500">
                  {data.matches.length} {language === "es" ? "resultados" : "results"}
                </span>
              </h3>

              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                {data.matches.map((m, idx) => {
                  const isTopMatch = idx === 0;
                  const traits = language === "es" ? (m.shared_traits_es || []) : (m.shared_traits_en || []);
                  const archetype = language === "es" ? m.archetype_name_es : m.archetype_name_en;

                  return (
                    <div
                      key={`${m.similar_player_id}-${m.season_label}`}
                      className={`rounded-3xl border bg-white p-6 shadow-xs flex flex-col justify-between transition-all duration-200 relative ${
                        isTopMatch
                          ? "border-purple-300 ring-2 ring-purple-400/30"
                          : "border-slate-200 hover:border-slate-300 hover:shadow-sm"
                      }`}
                    >
                      {isTopMatch && (
                        <div className="absolute top-0 right-0 bg-purple-600 text-white text-[9px] font-black uppercase px-3 py-1 rounded-bl-xl tracking-wider">
                          ★ TOP MATCH
                        </div>
                      )}

                      <div>
                        {/* Header: Avatar, Name and Match % */}
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex items-center gap-3">
                            <PlayerAvatar
                              headshotUrl={m.headshot_url}
                              playerName={m.player_name}
                              size={48}
                              className="ring-2 ring-slate-100 shadow-xs"
                            />
                            <div>
                              <span className="text-[10px] font-mono font-bold text-slate-400">#{idx + 1} CLONE</span>
                              <h4 className="text-base font-black text-slate-900 leading-tight">{m.player_name}</h4>
                              <div className="text-xs text-slate-500 font-medium">
                                {m.season_label} {m.age_in_season ? `• ${m.age_in_season} ${language === "es" ? "años" : "yrs"}` : ""}
                              </div>
                            </div>
                          </div>

                          <span
                            className={`px-2.5 py-1 rounded-full text-xs font-black font-mono shrink-0 ${
                              m.similarity_pct >= 95
                                ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                                : "bg-purple-50 text-purple-700 border border-purple-200"
                            }`}
                          >
                            {m.similarity_pct.toFixed(1)}%
                          </span>
                        </div>

                        {/* Archetype Pill */}
                        <div className="mt-3.5">
                          <span className="inline-block px-2.5 py-0.5 rounded-lg text-[11px] font-bold bg-purple-50 text-purple-800 border border-purple-200">
                            {archetype}
                          </span>
                        </div>

                        {/* Matching Tactical Traits */}
                        <div className="mt-3.5 space-y-1.5">
                          <div className="text-[10px] uppercase font-bold text-slate-400 tracking-wider">
                            {language === "es" ? "Rasgos Compartidos:" : "Shared Traits:"}
                          </div>
                          <div className="flex flex-wrap gap-1.5">
                            {traits.map((trait, tIdx) => (
                              <span
                                key={tIdx}
                                className="text-[11px] bg-slate-50 text-slate-700 px-2 py-0.5 rounded-md border border-slate-200 font-medium"
                              >
                                ✓ {trait}
                              </span>
                            ))}
                          </div>
                        </div>
                      </div>

                      {/* Stat Comparisons */}
                      {m.key_comparison_stats && (
                        <div className="mt-5 pt-3 border-t border-slate-100 grid grid-cols-3 gap-1.5 text-center text-[10px] font-mono">
                          {Object.entries(m.key_comparison_stats).slice(0, 3).map(([k, vals], sIdx) => (
                            <div key={sIdx} className="bg-slate-50 p-1.5 rounded-xl border border-slate-100">
                              <div className="text-slate-400 uppercase font-bold text-[9px]">{k}</div>
                              <div className="text-slate-900 font-black">{vals.comp} <span className="text-slate-400 font-normal">vs {vals.target}</span></div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
