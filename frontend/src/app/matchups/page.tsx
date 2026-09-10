"use client";

import React, { useEffect, useState } from "react";
import { Navbar } from "@/components/Navbar";
import { CommandPalette } from "@/components/CommandPalette";
import { MatchupTrackingCard } from "@/components/MatchupTrackingCard";
import {
  fetchPlayerMatchups,
  searchPlayerMatchups,
  PlayerMatchupAnalysisResponse,
} from "@/lib/api";
import {
  ShieldAlert,
  Search,
  Sparkles,
  Target,
  Activity,
  Info,
  Flame,
} from "lucide-react";

const SUGGESTED_PLAYERS = [
  { name: "Luka Dončić", id: 1629029 },
  { name: "Stephen Curry", id: 201939 },
  { name: "Shai Gilgeous-Alexander", id: 1628983 },
  { name: "Giannis Antetokounmpo", id: 203507 },
];

export default function MatchupsPage() {
  const [isCommandOpen, setIsCommandOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("Luka Doncic");
  const [selectedPlayerId, setSelectedPlayerId] = useState<number | null>(1629029);
  const [minPossessions, setMinPossessions] = useState<number>(10);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [matchupData, setMatchupData] = useState<PlayerMatchupAnalysisResponse | null>(null);

  const loadData = async (playerIdOrName: number | string, minPoss: number) => {
    try {
      setLoading(true);
      setError(null);
      let res: PlayerMatchupAnalysisResponse;
      if (typeof playerIdOrName === "number") {
        res = await fetchPlayerMatchups(playerIdOrName, undefined, minPoss);
      } else {
        res = await searchPlayerMatchups(playerIdOrName, undefined, minPoss);
      }
      setMatchupData(res);
      setSelectedPlayerId(res.player_id);
    } catch (err: any) {
      console.error("Error loading matchups:", err);
      setError(
        err.message ||
          "No se pudieron cargar los matchups para este jugador. Intenta con otro nombre de la NBA."
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData(1629029, minPossessions);
  }, []);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    loadData(searchQuery.trim(), minPossessions);
  };

  const handleSelectSuggested = (player: { name: string; id: number }) => {
    setSearchQuery(player.name);
    setSelectedPlayerId(player.id);
    loadData(player.id, minPossessions);
  };

  const handleMinPossessionsChange = (newMin: number) => {
    setMinPossessions(newMin);
    if (selectedPlayerId) {
      loadData(selectedPlayerId, newMin);
    } else if (searchQuery.trim()) {
      loadData(searchQuery.trim(), newMin);
    }
  };

  return (
    <div className="min-h-screen bg-[#F8FAFC] text-slate-900 selection:bg-orange-100 selection:text-orange-900">
      <Navbar onOpenSearch={() => setIsCommandOpen(true)} />
      <CommandPalette isOpen={isCommandOpen} onClose={() => setIsCommandOpen(false)} />

      <div className="md:pl-64">
        {/* Clean Hero Section matching ArchetypeNBA */}
        <section className="relative border-b border-slate-200 bg-gradient-to-b from-orange-50/40 via-white to-white py-12 lg:py-16 shadow-xs">
          <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
            <div className="flex flex-col items-center text-center space-y-4">
              {/* Status Pill Badge */}
              <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3.5 py-1 text-xs font-semibold text-slate-700 shadow-xs">
                <Flame className="w-3.5 h-3.5 text-orange-600" />
                <span>Scouting de Defensas Directas • 1 vs 1</span>
              </div>

              {/* Solid Clean Headline */}
              <h1 className="max-w-4xl text-4xl sm:text-5xl font-black tracking-tight text-slate-900 uppercase">
                ¿Quién lo para?
              </h1>

              <p className="max-w-2xl text-base text-slate-600 font-normal leading-relaxed">
                Evalúa el impacto de cada defensor frente a los mejores anotadores de la liga. Métricas normalizadas a{" "}
                <strong className="text-slate-900 font-bold">75 posesiones</strong>, diferenciales (<span className="font-mono">Δ</span>) de eficiencia (TS%) y detección de kryptonitas defensivas.
              </p>

              {/* Clean Live Search Input (ArchetypeNBA Signature) */}
              <form onSubmit={handleSearchSubmit} className="w-full max-w-xl pt-2">
                <div className="relative flex items-center rounded-2xl border-2 border-slate-200 bg-slate-50/70 p-1.5 shadow-sm transition focus-within:border-orange-500 focus-within:bg-white focus-within:ring-4 focus-within:ring-orange-500/10">
                  <Search className="ml-3 h-5 w-5 text-orange-500 shrink-0" />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Buscar jugador (ej. Luka Doncic, Stephen Curry, Shai...)"
                    className="w-full bg-transparent px-3 py-2 text-sm font-medium text-slate-900 placeholder:text-slate-400 outline-none"
                  />
                  <button
                    type="submit"
                    className="rounded-xl bg-orange-600 hover:bg-orange-700 text-white px-5 py-2 text-xs font-bold transition shadow-xs shrink-0"
                  >
                    Buscar
                  </button>
                </div>
              </form>

              {/* Quick Player Suggestions */}
              <div className="flex flex-wrap items-center justify-center gap-2 pt-1">
                <span className="text-xs font-medium text-slate-400">Populares:</span>
                {SUGGESTED_PLAYERS.map((p) => (
                  <button
                    key={p.id}
                    onClick={() => handleSelectSuggested(p)}
                    className={`px-3 py-1 rounded-xl text-xs font-semibold border transition shadow-2xs ${
                      selectedPlayerId === p.id
                        ? "bg-slate-900 text-white border-transparent"
                        : "bg-white text-slate-700 border-slate-200 hover:border-orange-300 hover:text-orange-600"
                    }`}
                  >
                    {p.name}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* Content Area */}
        <main className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8 py-10 space-y-10">
          {loading ? (
            <div className="p-12 rounded-3xl bg-white border border-slate-200 text-center space-y-4 shadow-xs">
              <div className="w-10 h-10 border-3 border-orange-500 border-t-transparent rounded-full animate-spin mx-auto" />
              <div className="text-sm font-bold text-slate-700">
                Analizando matchups y calculando diferenciales por 75 posesiones...
              </div>
              <p className="text-xs text-slate-400">
                Si es la primera consulta para este jugador, estamos extrayendo su tracking oficial de la NBA.
              </p>
            </div>
          ) : error ? (
            <div className="p-8 rounded-3xl bg-white border border-slate-200 text-center space-y-3 shadow-xs">
              <ShieldAlert className="w-10 h-10 text-orange-500 mx-auto" />
              <h3 className="text-base font-bold text-slate-900">
                No se pudo obtener el análisis
              </h3>
              <p className="text-xs text-slate-500 max-w-md mx-auto">
                {error}
              </p>
              <button
                onClick={() => loadData(1629029, minPossessions)}
                className="mt-2 px-4 py-2 bg-orange-600 hover:bg-orange-700 text-white text-xs font-bold rounded-xl transition shadow-xs"
              >
                Volver a Luka Dončić
              </button>
            </div>
          ) : matchupData ? (
            <MatchupTrackingCard
              data={matchupData}
              currentMinPossessions={minPossessions}
              onMinPossessionsChange={handleMinPossessionsChange}
            />
          ) : null}

          {/* Clean Methodology Card */}
          <div className="p-6 sm:p-8 rounded-3xl bg-white border border-slate-200 shadow-xs">
            <h3 className="text-sm font-black uppercase tracking-wider text-slate-900 mb-4 flex items-center gap-2">
              <Info className="w-4 h-4 text-orange-600" />
              Metodología Analítica de Matchups 1v1
            </h3>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-xs text-slate-600 leading-relaxed">
              <div className="p-4 rounded-2xl bg-slate-50/70 border border-slate-200">
                <h4 className="font-extrabold text-slate-900 text-sm mb-1.5 flex items-center gap-1.5">
                  <Activity className="w-4 h-4 text-orange-500" />
                  Ritmo: 75 Posesiones
                </h4>
                Neutraliza el ritmo de juego por equipo. Permite comparar defensas con volumen parejo, equivalente a la participación en un partido completo regular.
              </div>

              <div className="p-4 rounded-2xl bg-slate-50/70 border border-slate-200">
                <h4 className="font-extrabold text-slate-900 text-sm mb-1.5 flex items-center gap-1.5">
                  <Sparkles className="w-4 h-4 text-orange-500" />
                  True Shooting % (TS%)
                </h4>
                Pondera el valor real del triple y de los tiros libres. Evidencia si el defensor realmente fuerza fallos o si simplemente concede pocos tiros.
                <div className="my-2 p-2 bg-white rounded-lg font-mono text-[11px] text-center border border-slate-200 text-slate-800">
                  PTS / [2 × (FGA + 0.44 × FTA)]
                </div>
              </div>

              <div className="p-4 rounded-2xl bg-slate-50/70 border border-slate-200">
                <h4 className="font-extrabold text-slate-900 text-sm mb-1.5 flex items-center gap-1.5">
                  <Target className="w-4 h-4 text-orange-500" />
                  Kryptonita vs. Switch
                </h4>
                Los diferenciales (<span className="font-mono font-bold">Δ</span>) contrastan frente al promedio del atacante. El sistema clasifica automáticamente quién lo frena y a quién ataca deliberadamente.
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
