"use client";

import React, { useState, useEffect } from "react";
import { usePreferences } from "@/context/PreferencesContext";


interface DoppelgangerMatch {
  player_id: number;
  player_name: string;
  season_label: string;
  era: string;
  archetype_name: string;
  similarity_pct: number;
  matching_traits_es: string[];
  matching_traits_en: string[];
  key_comparison_stat_es: string;
  key_comparison_stat_en: string;
}

interface DoppelgangerData {
  target_player_id: number;
  target_player_name: string;
  target_season: string;
  target_archetype: string;
  matches: DoppelgangerMatch[];
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

    fetch(`http://localhost:8000/api/v1/doppelgangers?player_id_or_name=${encodeURIComponent(selectedPlayer)}&top_k=5`)
      .then(async (res) => {
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || "Player not found");
        }
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
    <div className="min-h-screen bg-[#0A0E17] text-white p-6 md:p-10 relative overflow-hidden">
      {/* Background Neon Brand Glow */}
      <div className="absolute top-0 right-1/4 w-96 h-96 bg-purple-600/10 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute bottom-10 left-1/4 w-96 h-96 bg-cyan-600/10 rounded-full blur-3xl pointer-events-none" />

      {/* Hero Header */}
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
                : "Discover the closest historical player clones across 40 years of NBA data using multi-dimensional cosine similarity and tactical archetypes."}
            </p>
          </div>

          {/* Quick Presets */}
          <div className="flex flex-wrap gap-1.5 max-w-md">
            {POPULAR_PLAYERS.map((p) => (
              <button
                key={p}
                onClick={() => {
                  setSearchQuery(p);
                  setSelectedPlayer(p);
                }}
                className={`px-2.5 py-1 text-xs rounded-lg transition-all ${
                  selectedPlayer === p
                    ? "bg-purple-500/30 text-purple-300 border border-purple-500/50 font-bold"
                    : "bg-white/5 text-gray-400 hover:text-white border border-white/5 hover:bg-white/10"
                }`}
              >
                {p}
              </button>
            ))}
          </div>
        </div>

        {/* Search Bar with Autocomplete */}
        <div className="relative max-w-xl">
          <div className="relative">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={language === "es" ? "Buscar jugador (ej. Stephen Curry, Nikola Jokic)..." : "Search player (e.g. Stephen Curry, Nikola Jokic)..."}
              className="w-full bg-slate-900/90 border border-white/15 rounded-xl px-4 py-3 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-purple-500/60 focus:ring-1 focus:ring-purple-500/40 shadow-inner"
            />
            {loading && (
              <div className="absolute right-3.5 top-3.5 w-4 h-4 border-2 border-purple-500 border-t-transparent rounded-full animate-spin" />
            )}
          </div>

          {/* Suggestions Dropdown */}
          {suggestions.length > 0 && (
            <div className="absolute top-full left-0 right-0 mt-1.5 bg-slate-900/95 border border-white/15 rounded-xl shadow-2xl overflow-hidden z-30 backdrop-blur-xl">
              {suggestions.map((name) => (
                <button
                  key={name}
                  onClick={() => {
                    setSelectedPlayer(name);
                    setSearchQuery(name);
                    setSuggestions([]);
                  }}
                  className="w-full text-left px-4 py-2.5 text-sm text-gray-200 hover:bg-purple-600/20 hover:text-white transition-colors border-b border-white/5 last:border-0"
                >
                  {name}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Error State */}
        {error && (
          <div className="p-4 bg-rose-500/20 border border-rose-500/30 rounded-xl text-rose-300 text-sm">
            {error}
          </div>
        )}

        {/* Target Player Card */}
        {data && (
          <div className="bg-[#111827]/80 border border-white/10 rounded-2xl p-6 backdrop-blur-xl shadow-xl flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
            <div>
              <span className="text-xs uppercase font-bold text-gray-400 tracking-wider">
                {language === "es" ? "Jugador Objetivo" : "Target Subject"}
              </span>
              <h2 className="text-3xl font-black text-white mt-0.5">{data.target_player_name}</h2>
              <div className="flex items-center gap-3 text-sm text-gray-300 mt-1">
                <span className="font-mono text-purple-400 font-bold">{data.target_season}</span>
                <span>•</span>
                <span className="px-2.5 py-0.5 rounded-md bg-purple-500/20 text-purple-300 text-xs font-semibold border border-purple-500/30">
                  {data.target_archetype}
                </span>
              </div>
            </div>

            <div className="bg-white/5 border border-white/10 px-5 py-3 rounded-xl">
              <div className="text-xs text-gray-400 uppercase font-medium">
                {language === "es" ? "Algoritmo de Rastreo" : "Match Engine"}
              </div>
              <div className="text-sm font-bold text-gray-200 mt-0.5">
                40-Year Historical Cohort Matrix
              </div>
            </div>
          </div>
        )}

        {/* Doppelgänger Matches List */}
        {data && (
          <div className="space-y-4">
            <h3 className="text-lg font-bold text-gray-200 flex items-center gap-2">
              <span>{language === "es" ? "Top 5 Clones Históricos Identificados" : "Top 5 Historical Clones Found"}</span>
              <span className="text-xs font-normal text-gray-400">({data.matches.length} matches)</span>
            </h3>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
              {data.matches.map((m, idx) => {
                const isTopMatch = idx === 0;
                return (
                  <div
                    key={`${m.player_id}-${m.season_label}`}
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
                      {/* Similarity Badge */}
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-mono text-gray-400">#{idx + 1} Match</span>
                        <span
                          className={`px-2.5 py-0.5 rounded-full text-xs font-black font-mono ${
                            m.similarity_pct >= 90
                              ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                              : "bg-purple-500/20 text-purple-300 border border-purple-500/40"
                          }`}
                        >
                          {m.similarity_pct.toFixed(1)}% {language === "es" ? "Similitud" : "Similarity"}
                        </span>
                      </div>

                      {/* Player Name & Era */}
                      <h4 className="text-xl font-bold text-white mt-2.5">{m.player_name}</h4>
                      <div className="flex items-center gap-2 text-xs text-gray-400 mt-1">
                        <span className="font-mono font-bold text-gray-300">{m.season_label}</span>
                        <span>•</span>
                        <span>{m.era}</span>
                      </div>

                      {/* Archetype */}
                      <div className="mt-2.5">
                        <span className="inline-block px-2.5 py-0.5 rounded text-[11px] font-semibold bg-white/5 text-gray-300 border border-white/10">
                          {m.archetype_name}
                        </span>
                      </div>

                      {/* Matching Tactical Traits */}
                      <div className="mt-4 space-y-1.5">
                        <div className="text-[11px] uppercase font-bold text-gray-400 tracking-wider">
                          {language === "es" ? "Rasgos Compartidos:" : "Matching Traits:"}
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                          {(language === "es" ? m.matching_traits_es : m.matching_traits_en).map((trait, tIdx) => (
                            <span
                              key={tIdx}
                              className="text-[11px] bg-slate-800/90 text-gray-200 px-2 py-0.5 rounded-md border border-white/5"
                            >
                              ✓ {trait}
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>

                    {/* Key Comparison Metric Footer */}
                    <div className="mt-5 pt-3 border-t border-white/10">
                      <div className="text-xs text-gray-300 font-mono">
                        {language === "es" ? m.key_comparison_stat_es : m.key_comparison_stat_en}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
