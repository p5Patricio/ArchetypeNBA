"use client";

import React from "react";
import { type ChampionResponse } from "@/lib/api";
import { usePreferences } from "@/context/PreferencesContext";
import { Crown, CheckCircle2, Shield } from "lucide-react";

interface ChampionCardProps {
  champion?: ChampionResponse | null;
  loading?: boolean;
}

export function ChampionCard({ champion, loading }: ChampionCardProps) {
  const { language } = usePreferences();
  const isEs = language === "es";

  if (loading) {
    return (
      <div
        className="rounded-3xl border border-slate-200 bg-white p-6 sm:p-8 shadow-xs animate-pulse space-y-4"
        aria-busy="true"
      >
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 bg-amber-200 rounded-2xl" />
          <div className="space-y-2">
            <div className="h-6 w-48 bg-slate-200 rounded-lg" />
            <div className="h-4 w-32 bg-slate-100 rounded-md" />
          </div>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 pt-4">
          <div className="h-20 bg-slate-100 rounded-2xl" />
          <div className="h-20 bg-slate-100 rounded-2xl" />
          <div className="h-20 bg-slate-100 rounded-2xl" />
          <div className="h-20 bg-slate-100 rounded-2xl" />
        </div>
      </div>
    );
  }

  if (!champion) {
    return (
      <div className="rounded-3xl border border-dashed border-slate-300 bg-white p-8 text-center">
        <Crown className="mx-auto h-8 w-8 text-slate-400 mb-2" />
        <p className="text-sm font-semibold text-slate-700">
          {isEs ? "No hay un modelo campeón registrado" : "No active champion model found"}
        </p>
      </div>
    );
  }

  return (
    <div className="relative overflow-hidden rounded-3xl border border-amber-200 bg-gradient-to-br from-amber-50/60 via-white to-orange-50/30 p-6 sm:p-8 shadow-xs">
      {/* Top Background Glow */}
      <div className="absolute top-0 right-0 -mt-10 -mr-10 h-48 w-48 rounded-full bg-amber-400/10 blur-3xl pointer-events-none" />

      {/* Header Info */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-amber-100/80 pb-6 mb-6">
        <div className="flex items-center gap-3.5">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-amber-500 to-orange-500 text-white shadow-md shadow-amber-500/20 shrink-0">
            <Crown className="h-6 w-6" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-black uppercase tracking-wider text-amber-800">
                {isEs ? "MODELO CAMPEÓN ACTIVO" : "ACTIVE CHAMPION MODEL"}
              </span>
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 text-emerald-800 px-2 py-0.5 text-[10px] font-black border border-emerald-200">
                <CheckCircle2 className="h-3 w-3 text-emerald-600" />
                <span>{isEs ? "En Producción" : "In Production"}</span>
              </span>
            </div>
            <h2 className="text-2xl sm:text-3xl font-black text-slate-900 tracking-tight mt-0.5">
              {champion.label}
            </h2>
          </div>
        </div>

        {/* Model ID Tag */}
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs bg-white border border-amber-200 text-amber-900 px-3 py-1.5 rounded-xl font-bold shadow-2xs">
            Model ID #{champion.model_id}
          </span>
        </div>
      </div>

      {/* KPI Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
        <div className="rounded-2xl bg-white border border-slate-200/80 p-4 shadow-2xs">
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1">
            {isEs ? "Rol en el Sistema" : "System Role"}
          </div>
          <div className="text-base sm:text-lg font-black text-slate-900 capitalize">
            {champion.role}
          </div>
          <div className="text-[11px] text-slate-500 mt-0.5">
            {isEs ? "Genera apuestas de papel" : "Executes paper bets"}
          </div>
        </div>

        <div className="rounded-2xl bg-white border border-slate-200/80 p-4 shadow-2xs">
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1">
            {isEs ? "Pronósticos Emitidos" : "Predictions Made"}
          </div>
          <div className="text-base sm:text-lg font-black text-slate-900 tabular-nums">
            {champion.predictions}
          </div>
          <div className="text-[11px] text-slate-500 mt-0.5">
            {isEs ? "H2H y Hándicaps" : "H2H & Spreads"}
          </div>
        </div>

        <div className="rounded-2xl bg-white border border-slate-200/80 p-4 shadow-2xs">
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1">
            {isEs ? "Partidos Evaluados" : "Final Games"}
          </div>
          <div className="text-base sm:text-lg font-black text-slate-900 tabular-nums">
            {champion.final_games}
          </div>
          <div className="text-[11px] text-slate-500 mt-0.5">
            {isEs ? "Con resultado final" : "With official scores"}
          </div>
        </div>

        <div className="rounded-2xl bg-white border border-slate-200/80 p-4 shadow-2xs">
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1">
            {isEs ? "Días Activo" : "Days Live"}
          </div>
          <div className="text-base sm:text-lg font-black text-slate-900 tabular-nums">
            {champion.days_live != null ? Math.round(champion.days_live) : "—"}
          </div>
          <div className="text-[11px] text-slate-500 mt-0.5">
            {isEs ? "En competencia viva" : "In live competition"}
          </div>
        </div>
      </div>

      {/* Champion Specifications Footer */}
      <div className="rounded-2xl bg-amber-50/80 border border-amber-200/60 p-4 text-xs text-amber-950 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Shield className="h-4 w-4 text-amber-700 shrink-0" />
          <span className="font-semibold">
            {isEs
              ? "Especificación: FiveThirtyEight Elo (K=20, Ventaja Local 60 pts, Carryover 0.75 a 1505, MOV exp 0.8, σ=14.14)."
              : "Spec: FiveThirtyEight Elo (K=20, Home Advantage 60 pts, Carryover 0.75 to 1505, MOV exp 0.8, σ=14.14)."}
          </span>
        </div>
        <span className="text-[11px] font-mono font-bold text-amber-800 shrink-0">
          {isEs ? "Protegido como baseline" : "Protected baseline"}
        </span>
      </div>
    </div>
  );
}
