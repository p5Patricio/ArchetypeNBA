"use client";

import React, { useState, useEffect } from "react";
import { usePreferences } from "@/context/PreferencesContext";
import { Navbar } from "@/components/Navbar";
import { CommandPalette } from "@/components/CommandPalette";
import { PlayerAvatar } from "@/components/PlayerAvatar";

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
  const { language } = usePreferences();
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
    fetch("http://localhost:8000/api/v1/players")
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

    fetch(`http://localhost:8000/api/v1/doppelgangers?player_id_or_name=${encodeURIComponent(selectedPlayer)}&top_k=6`)
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
    <div className="min-h-screen bg-[#0A0E17] text-white relative overflow-hidden">
      <Navbar onOpenSearch={() => setIsCommandOpen(true)} />
      <CommandPalette isOpen={isCommandOpen} onClose={() => setIsCommandOpen(false)} />

      {/* Background Neon Brand Glow */}
      <div className="absolute top-0 right-1/4 w-96 h-96 bg-purple-600/10 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute bottom-10 left-1/4 w-96 h-96 bg-cyan-600/10 rounded-full blur-3xl pointer-events-none" />

      <div className="md:pl-64 p-6 md:p-10">
        <div className="max-w-6xl mx-auto space-y-6">
          <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 border-b border-white/10 pb-6">
            <div>
              <div className="flex items-center gap-2.5">
                <span className="px-3 py-1 text-xs font-bold uppercase tracking-wider rounded-lg bg-purple-500/20 text-purple-400 border border-purple-500/30">
                  AI Historical Clones
                </span>
                <span className="text-xs text-gray-400">
                  CraftedNBA / Multi-Dimensional Cosine Similarity (40 Years)
                </span>
              </div>
              <h1 className="text-3xl md:text-5xl font-black tracking-tight mt-2 bg-gradient-to-r from-white via-gray-100 to-purple-400 bg-clip-text text-transparent">
                {language === "es" ? "Doppelgängers Históricos" : "Historical Doppelgängers"}
              </h1>
              <p className="text-sm text-gray-400 max-w-2xl mt-1">
                {language === "es"
                  ? "Encuentra los clones históricos más parecidos de cualquier jugador en 40 años de datos de la NBA usando similitud de coseno y arquetipos tácticos."
                  : "Find the most accurate historical player clones across 40 years of NBA data using multi-dimensional cosine similarity and tactical archetypes."}
              </p>
            </div>
          </div>

          {/* Search Input & Quick Preset Buttons */}
          <div className="space-y-4">
            <div className="relative">
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
                    ? "Buscar jugador para clonar (ej. Stephen Curry, LeBron James, Nikola Jokic)..."
                    : "Search player to match (e.g. Stephen Curry, LeBron James, Nikola Jokic)..."
                }
                className="w-full bg-slate-900/90 border border-white/15 rounded-2xl px-5 py-4 text-white text-base placeholder-gray-500 focus:outline-none focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 backdrop-blur-xl shadow-2xl"
              />

              {/* Autocomplete Dropdown */}
              {suggestions.length > 0 && (
                <div className="absolute top-full left-0 right-0 mt-2 bg-slate-900 border border-white/15 rounded-2xl overflow-hidden z-50 shadow-2xl backdrop-blur-2xl">
                  {suggestions.map((name, idx) => (
                    <button
                      key={idx}
                      onClick={() => {
                        setSelectedPlayer(name);
                        setSearchQuery(name);
                        setSuggestions([]);
                      }}
                      className="w-full px-5 py-3 text-left text-sm text-gray-200 hover:bg-purple-600/30 hover:text-white flex items-center justify-between border-b border-white/5 last:border-none transition"
                    >
                      <span className="font-semibold">{name}</span>
                      <span className="text-xs text-gray-400 font-mono">Seleccionar →</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Quick Preset Buttons */}
            <div className="flex items-center gap-2 overflow-x-auto pb-2 scrollbar-none">
              <span className="text-xs font-bold uppercase text-gray-400 shrink-0">
                {language === "es" ? "Populares:" : "Popular:"}
              </span>
              {POPULAR_PLAYERS.map((p) => (
                <button
                  key={p}
                  onClick={() => {
                    setSelectedPlayer(p);
                    setSearchQuery(p);
                  }}
                  className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all shrink-0 ${
                    selectedPlayer === p
                      ? "bg-purple-500 text-white shadow-lg shadow-purple-500/30 border border-purple-400"
                      : "bg-white/5 text-gray-300 hover:bg-white/10 border border-white/10"
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>

          {/* Loading State */}
          {loading && (
            <div className="flex flex-col items-center justify-center py-20 space-y-3">
              <div className="w-10 h-10 border-4 border-purple-500 border-t-transparent rounded-full animate-spin" />
              <p className="text-xs font-bold text-gray-400 font-mono">
                {language === "es" ? "Calculando vectores de similitud..." : "Computing multi-dimensional cosine vectors..."}
              </p>
            </div>
          )}

          {/* Error State */}
          {error && (
            <div className="p-4 bg-rose-500/20 border border-rose-500/30 rounded-2xl text-rose-300 text-sm">
              {error}
            </div>
          )}

          {/* Match Results */}
          {!loading && data && data.matches && (
            <div className="space-y-6">
              {/* Target Player Card Header */}
              <div className="bg-gradient-to-r from-purple-950/40 via-slate-900/60 to-slate-900/40 border border-purple-500/30 rounded-3xl p-6 backdrop-blur-xl shadow-2xl flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div className="flex items-center gap-4">
                  <div className="w-14 h-14 rounded-2xl bg-purple-500/20 border border-purple-500/40 flex items-center justify-center font-mono text-2xl font-black text-purple-300">
                    🧬
                  </div>
                  <div>
                    <div className="text-xs font-bold uppercase text-purple-400 tracking-wider">
                      {language === "es" ? "Jugador Analizado" : "Analyzed Target Player"}
                    </div>
                    <h2 className="text-2xl font-black text-white">{data.target_player_name}</h2>
                    <p className="text-xs text-gray-400">
                      {data.target_season_label} • {data.target_position}
                    </p>
                  </div>
                </div>

                <div className="bg-black/40 border border-white/10 rounded-2xl p-3.5 max-w-md">
                  <div className="text-[10px] uppercase font-bold text-gray-400 tracking-wider">
                    {language === "es" ? "Diagnóstico de Scouting" : "Scouting Takeaway"}
                  </div>
                  <p className="text-xs text-gray-200 mt-1 leading-relaxed">
                    {language === "es" ? data.scouting_takeaway_es : data.scouting_takeaway_en}
                  </p>
                </div>
              </div>

              {/* Top 6 Matches Grid */}
              <h3 className="text-lg font-extrabold text-white flex items-center gap-2">
                <span>{language === "es" ? "Top Clones Históricos Identificados" : "Top Historical Clones Found"}</span>
                <span className="text-xs font-normal text-gray-400">({data.matches.length} matches)</span>
              </h3>

              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                {data.matches.map((m, idx) => {
                  const isTopMatch = idx === 0;
                  const traits = language === "es" ? (m.shared_traits_es || []) : (m.shared_traits_en || []);
                  const archetype = language === "es" ? m.archetype_name_es : m.archetype_name_en;

                  return (
                    <div
                      key={`${m.similar_player_id}-${m.season_label}`}
                      className={`bg-slate-900/90 border rounded-2xl p-5 backdrop-blur-xl shadow-xl transition-all duration-300 relative overflow-hidden flex flex-col justify-between ${
                        isTopMatch
                          ? "border-amber-500/40 hover:border-amber-500/70 shadow-amber-500/10"
                          : "border-white/10 hover:border-white/20"
                      }`}
                    >
                      {isTopMatch && (
                        <div className="absolute top-0 right-0 bg-amber-500/20 border-b border-l border-amber-500/40 text-amber-300 text-[10px] font-bold px-3 py-1 rounded-bl-xl tracking-wider">
                          ★ TOP CLONE
                        </div>
                      )}

                      <div>
                        {/* Similarity Badge & Avatar */}
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-3">
                            <PlayerAvatar
                              headshotUrl={m.headshot_url}
                              playerName={m.player_name}
                              size={44}
                              className="ring-2 ring-white/10"
                            />
                            <div>
                              <span className="text-xs font-mono text-gray-400">#{idx + 1} Match</span>
                              <h4 className="text-base font-bold text-white leading-tight">{m.player_name}</h4>
                            </div>
                          </div>

                          <span
                            className={`px-2.5 py-1 rounded-full text-xs font-black font-mono ${
                              m.similarity_pct >= 90
                                ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                                : "bg-purple-500/20 text-purple-300 border border-purple-500/40"
                            }`}
                          >
                            {m.similarity_pct.toFixed(1)}%
                          </span>
                        </div>

                        {/* Season & Age */}
                        <div className="flex items-center gap-2 text-xs text-gray-400 mt-2.5">
                          <span className="font-mono font-bold text-gray-300">{m.season_label}</span>
                          {m.age_in_season && <span>• {m.age_in_season} {language === "es" ? "años" : "yrs"}</span>}
                        </div>

                        {/* Archetype */}
                        <div className="mt-2">
                          <span className="inline-block px-2 py-0.5 rounded text-[10px] font-bold bg-white/5 text-purple-300 border border-purple-500/30">
                            {archetype}
                          </span>
                        </div>

                        {/* Matching Tactical Traits */}
                        <div className="mt-3.5 space-y-1.5">
                          <div className="text-[10px] uppercase font-bold text-gray-400 tracking-wider">
                            {language === "es" ? "Rasgos Compartidos:" : "Matching Traits:"}
                          </div>
                          <div className="flex flex-wrap gap-1.5">
                            {traits.map((trait, tIdx) => (
                              <span
                                key={tIdx}
                                className="text-[10px] bg-slate-800/90 text-gray-200 px-2 py-0.5 rounded-md border border-white/5"
                              >
                                ✓ {trait}
                              </span>
                            ))}
                          </div>
                        </div>
                      </div>

                      {/* Key Comparison Metric Stats */}
                      {m.key_comparison_stats && (
                        <div className="mt-4 pt-3 border-t border-white/10 grid grid-cols-3 gap-2 text-center text-[10px] font-mono">
                          {Object.entries(m.key_comparison_stats).slice(0, 3).map(([k, vals], sIdx) => (
                            <div key={sIdx} className="bg-black/30 p-1.5 rounded-lg">
                              <div className="text-gray-500 uppercase">{k}</div>
                              <div className="text-gray-200 font-bold">{vals.comp} vs {vals.target}</div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
