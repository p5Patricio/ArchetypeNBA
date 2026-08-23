"use client";

import React from "react";
import Link from "next/link";
import { type HistoricalMatchItem } from "@/lib/api";
import { usePreferences } from "@/context/PreferencesContext";
import { PlayerAvatar } from "./PlayerAvatar";
import { Sparkles, Crown, ArrowUpRight } from "lucide-react";

interface HistoricalCompsProps {
  matches: HistoricalMatchItem[];
  playerName?: string;
  className?: string;
}

export function HistoricalComps({
  matches = [],
  playerName = "Jugador",
  className = "",
}: HistoricalCompsProps) {
  const { language } = usePreferences();

  if (matches.length === 0) return null;

  return (
    <div className={`rounded-3xl border border-slate-200 bg-white p-6 shadow-xs space-y-5 ${className}`}>
      
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-100 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="p-1.5 rounded-xl bg-orange-50 border border-orange-200 text-orange-600">
              <Sparkles className="h-4 w-4" />
            </span>
            <h3 className="text-base font-extrabold tracking-tight text-slate-900">
              {language === "es"
                ? "Similitudes Históricas Multitemporada (Cosine Engine)"
                : "Historical Multi-Season Comps (Cosine Engine)"}
            </h3>
          </div>
          <p className="text-xs font-medium text-slate-500 mt-1">
            {language === "es"
              ? `Comparación vectorial multidimensional frente a 23 temporadas de la NBA en PostgreSQL.`
              : `Vectorial multi-dimensional comparison against 23 seasons of NBA history in PostgreSQL.`}
          </p>
        </div>

        <span className="self-start sm:self-auto rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-mono font-bold text-slate-600">
          {matches.length} {language === "es" ? "arquetipos cercanos" : "closest matches"}
        </span>
      </div>

      {/* Matches Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {matches.map((item, idx) => {
          const simPercent = Math.round(item.similarity_score * 100);

          return (
            <Link
              key={idx}
              href={`/player/${encodeURIComponent(item.player_name)}`}
              className="group rounded-2xl border border-slate-200 bg-slate-50/50 p-4 shadow-2xs hover:border-orange-300 hover:bg-orange-50/30 hover:shadow-md transition-all flex flex-col justify-between space-y-3"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <PlayerAvatar
                    playerName={item.player_name}
                    headshotUrl={item.headshot_url}
                    size={46}
                    className="border border-slate-200 shrink-0"
                  />
                  <div>
                    <div className="flex items-center gap-1.5">
                      <span className="rounded bg-slate-200 px-1.5 py-0.2 font-mono text-[10px] font-bold text-slate-700">
                        {item.season_label}
                      </span>
                      {item.is_hall_of_fame && (
                        <span className="flex items-center gap-0.5 rounded-full border border-amber-300 bg-amber-50 px-1.5 py-0.2 text-[9px] font-bold text-amber-800">
                          <Crown className="h-2.5 w-2.5 text-amber-600" />
                          HOF
                        </span>
                      )}
                    </div>
                    <h4 className="text-sm font-black text-slate-900 group-hover:text-orange-600 transition truncate mt-0.5">
                      {item.player_name}
                    </h4>
                    <p className="text-[11px] font-semibold text-sky-700 truncate">
                      {item.role_name}
                    </p>
                  </div>
                </div>

                <div className="text-right shrink-0">
                  <div className="font-mono text-base font-black text-orange-600">
                    {simPercent}%
                  </div>
                  <span className="text-[10px] uppercase font-bold text-slate-400">
                    {language === "es" ? "Match" : "Match"}
                  </span>
                </div>
              </div>

              {/* Stat Line */}
              <div className="grid grid-cols-4 gap-1 text-center text-xs border-t border-slate-200/60 pt-2 font-mono">
                <div>
                  <span className="text-[9px] uppercase font-bold text-slate-400">PTS</span>
                  <div className="font-bold text-slate-900">{item.ppg.toFixed(1)}</div>
                </div>
                <div>
                  <span className="text-[9px] uppercase font-bold text-slate-400">REB</span>
                  <div className="font-bold text-slate-900">{item.rpg.toFixed(1)}</div>
                </div>
                <div>
                  <span className="text-[9px] uppercase font-bold text-slate-400">AST</span>
                  <div className="font-bold text-slate-900">{item.apg.toFixed(1)}</div>
                </div>
                <div>
                  <span className="text-[9px] uppercase font-bold text-slate-400">3PM</span>
                  <div className="font-bold text-orange-600">{item.fg3m.toFixed(1)}</div>
                </div>
              </div>

              <div className="flex items-center justify-between text-[11px] font-bold text-slate-500 group-hover:text-orange-600 transition pt-1">
                <span>{language === "es" ? "Ver Perfil Histórico" : "View Historical Profile"}</span>
                <ArrowUpRight className="h-3.5 w-3.5 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-transform" />
              </div>
            </Link>
          );
        })}
      </div>

    </div>
  );
}
