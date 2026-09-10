"use client";

import React, { useEffect, useState } from "react";
import { Navbar } from "@/components/Navbar";
import { CommandPalette } from "@/components/CommandPalette";
import { ParallelShotZonesChart } from "@/components/ParallelShotZonesChart";
import {
  getParallelShotZones,
  type ParallelShotZonesResponse,
} from "@/lib/api";
import { Target, AlertCircle, RefreshCw } from "lucide-react";
import { usePreferences } from "@/context/PreferencesContext";

export default function ShotZonesPage() {
  const { language } = usePreferences();
  const [season, setSeason] = useState<string>("2023-24");
  const [data, setData] = useState<ParallelShotZonesResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [isCommandOpen, setIsCommandOpen] = useState<boolean>(false);

  useEffect(() => {
    let isCancelled = false;
    async function loadData() {
      setLoading(true);
      setError(null);
      try {
        const res = await getParallelShotZones(season);
        if (!isCancelled) {
          setData(res);
        }
      } catch (err: unknown) {
        if (!isCancelled) {
          setError(
            err instanceof Error
              ? err.message
              : "No se pudieron cargar los datos de efectividad por zona."
          );
        }
      } finally {
        if (!isCancelled) {
          setLoading(false);
        }
      }
    }

    loadData();
    return () => {
      isCancelled = true;
    };
  }, [season]);

  const isEs = language === "es";

  return (
    <div className="min-h-screen bg-[#F8FAFC] text-slate-900 selection:bg-orange-100 selection:text-orange-900">
      <Navbar onOpenSearch={() => setIsCommandOpen(true)} />
      <CommandPalette isOpen={isCommandOpen} onClose={() => setIsCommandOpen(false)} />

      {/* Desktop sidebar offset wrapper */}
      <div className="md:pl-64">
        {/* ========================================================================= */}
        {/* HERO SECTION (Clean White / Warm Gradient consistent with ArchetypeNBA) */}
        {/* ========================================================================= */}
        <section className="relative border-b border-slate-200 bg-gradient-to-b from-orange-50/40 via-white to-white py-12 lg:py-16 shadow-xs">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="flex flex-col items-center text-center space-y-4">
              {/* Pill Badge */}
              <div className="inline-flex items-center gap-2 rounded-full border border-orange-200 bg-orange-50 px-4 py-1 text-xs font-black text-orange-800 shadow-2xs">
                <Target className="h-3.5 w-3.5 text-orange-600" />
                <span>
                  {isEs
                    ? "SCOUTING MULTIVARIABLE • COORDENADAS PARALELAS"
                    : "MULTIVARIATE SCOUTING • PARALLEL COORDINATES"}
                </span>
              </div>

              {/* Headline */}
              <h1 className="max-w-4xl text-3xl sm:text-5xl font-black tracking-tight text-slate-900 leading-tight">
                {isEs
                  ? "Efectividad de Tiro en 4 Zonas Clave"
                  : "Shooting Efficiency Across 4 Key NBA Zones"}
              </h1>

              {/* Subtitle */}
              <p className="max-w-3xl text-sm sm:text-base text-slate-600 font-normal leading-relaxed">
                {isEs
                  ? "Explorá el perfil ofensivo de los 300 jugadores con más minutos en la NBA a través de curvas fluidas de spline sobre Pintura, Media Distancia, Tiro Libre y Triple."
                  : "Explore the offensive shooting profile of the top 300 NBA players by minutes using smooth continuous splines across Paint, Mid-Range, Free Throw, and 3-Point."}
              </p>
            </div>
          </div>
        </section>

        {/* ========================================================================= */}
        {/* MAIN CONTENT AREA */}
        {/* ========================================================================= */}
        <main className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-10 space-y-10">
          {/* Loading State */}
          {loading && (
            <div className="flex flex-col items-center justify-center py-24 space-y-4">
              <RefreshCw className="h-10 w-10 text-orange-500 animate-spin" />
              <p className="text-sm font-bold text-slate-500">
                {isEs
                  ? `Calculando splines y percentiles de la cohorte para la temporada ${season}...`
                  : `Computing splines and cohort percentiles for season ${season}...`}
              </p>
            </div>
          )}

          {/* Error State */}
          {error && !loading && (
            <div className="rounded-2xl border border-rose-200 bg-rose-50/70 p-6 text-center space-y-3">
              <AlertCircle className="h-8 w-8 text-rose-500 mx-auto" />
              <div className="text-base font-bold text-rose-900">
                {isEs ? "Error al cargar datos" : "Error loading data"}
              </div>
              <p className="text-xs text-rose-700 max-w-md mx-auto">{error}</p>
              <button
                onClick={() => setSeason((prev) => prev)}
                className="px-4 py-2 rounded-xl bg-rose-600 text-white text-xs font-bold hover:bg-rose-700 transition-colors inline-flex items-center gap-1.5"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                {isEs ? "Reintentar" : "Retry"}
              </button>
            </div>
          )}

          {/* Chart View */}
          {!loading && !error && data && (
            <ParallelShotZonesChart
              players={data.players}
              leagueAverages={data.league_averages}
              presets={data.presets}
              currentSeason={season}
              onSeasonChange={setSeason}
            />
          )}
        </main>
      </div>
    </div>
  );
}
