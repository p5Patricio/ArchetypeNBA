"use client";

import React from "react";
import { type MoreyballMetricsResponse } from "@/lib/api";
import { usePreferences } from "@/context/PreferencesContext";
import { Gauge, TrendingUp, AlertCircle, CheckCircle2 } from "lucide-react";

interface MoreyballWidgetProps {
  data: MoreyballMetricsResponse;
  className?: string;
}

export function MoreyballWidget({ data, className = "" }: MoreyballWidgetProps) {
  const { language } = usePreferences();

  const moreyPercent = Math.round(data.moreyball_index * 100);
  const rimPercent = Math.round(data.rim_frequency * 100);
  const midPercent = Math.round(data.midrange_frequency * 100);
  const threePercent = Math.round(data.three_frequency * 100);

  const isElite = data.moreyball_index >= 0.80;

  return (
    <div className={`rounded-3xl border border-slate-200 bg-white p-6 shadow-xs space-y-5 ${className}`}>
      
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-100 pb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="p-1.5 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-600">
              <Gauge className="h-4 w-4" />
            </span>
            <h3 className="text-base font-extrabold tracking-tight text-slate-900">
              {language === "es" ? "Índice de Moreyball & Optimización de Tiro" : "Moreyball Shot Optimization Index"}
            </h3>
          </div>
          <p className="text-xs font-medium text-slate-500 mt-1">
            {language === "es"
              ? "Proporción de tiros eficientes (Aro + Triples) frente a la media distancia ineficiente."
              : "Proportion of high-efficiency attempts (Rim + 3-Pointers) vs inefficient mid-range shots."}
          </p>
        </div>

        <span
          className={`self-start sm:self-auto rounded-full border px-3 py-1 text-xs font-black ${
            isElite
              ? "border-emerald-200 bg-emerald-50 text-emerald-700"
              : "border-orange-200 bg-orange-50 text-orange-700"
          }`}
        >
          {data.moreyball_grade}
        </span>
      </div>

      {/* Main Meter & Score */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 items-center">
        
        {/* Main Moreyball Percentage Box */}
        <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4 text-center">
          <span className="text-[10px] uppercase font-bold text-slate-400">
            {language === "es" ? "Volumen Moreyball" : "Moreyball Ratio"}
          </span>
          <div className="font-mono text-3xl font-black text-slate-900 mt-0.5">
            {moreyPercent}%
          </div>
          <div className="mt-2 h-2.5 w-full overflow-hidden rounded-full bg-slate-200">
            <div
              className={`h-full rounded-full transition-all duration-700 ${
                isElite ? "bg-emerald-500" : "bg-orange-500"
              }`}
              style={{ width: `${moreyPercent}%` }}
            />
          </div>
        </div>

        {/* Expected Points Per Shot */}
        <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4 text-center">
          <span className="text-[10px] uppercase font-bold text-slate-400">
            {language === "es" ? "Puntos Esperados por Tiro" : "Expected Points Per Shot"}
          </span>
          <div className="font-mono text-3xl font-black text-emerald-600 mt-0.5">
            {data.expected_points_per_shot.toFixed(2)}
          </div>
          <span className="text-[11px] font-semibold text-slate-500">
            {language === "es" ? "Media NBA: 1.08 xPPS" : "NBA Avg: 1.08 xPPS"}
          </span>
        </div>

        {/* Shot Quality Index (SQI) */}
        <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4 text-center">
          <span className="text-[10px] uppercase font-bold text-slate-400">
            {language === "es" ? "Shot Quality Index (SQI)" : "Shot Quality Index (SQI)"}
          </span>
          <div className="font-mono text-3xl font-black text-sky-700 mt-0.5">
            {data.shot_quality_index.toFixed(1)}
          </div>
          <span className="text-[11px] font-semibold text-sky-600">
            {language === "es" ? "Percentil Élite" : "Elite Percentile"}
          </span>
        </div>

      </div>

      {/* 3-Zone Shot Distribution Breakdown Bar */}
      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs font-bold text-slate-700">
          <span>{language === "es" ? "Desglose por Zona de Tiro" : "Shot Zone Distribution"}</span>
          <span className="text-slate-400 text-[11px] font-normal">100% de tiros intentados</span>
        </div>

        {/* Segmented Stacked Bar */}
        <div className="h-4 w-full overflow-hidden rounded-full bg-slate-100 flex shadow-inner">
          <div
            className="h-full bg-sky-500 transition-all duration-700"
            style={{ width: `${rimPercent}%` }}
            title={`Aro (<5ft): ${rimPercent}%`}
          />
          <div
            className="h-full bg-amber-500 transition-all duration-700"
            style={{ width: `${midPercent}%` }}
            title={`Media Distancia (10-22ft): ${midPercent}%`}
          />
          <div
            className="h-full bg-orange-500 transition-all duration-700"
            style={{ width: `${threePercent}%` }}
            title={`Triples (>22ft): ${threePercent}%`}
          />
        </div>

        {/* Zone Labels Grid */}
        <div className="grid grid-cols-3 gap-2 pt-2 text-xs">
          <div className="flex items-center gap-2">
            <span className="h-3 w-3 rounded-md bg-sky-500 shrink-0" />
            <div>
              <div className="font-bold text-slate-900">{language === "es" ? "Aro (<5ft)" : "Rim (<5ft)"}</div>
              <div className="font-mono text-xs text-slate-500">{rimPercent}% de tiros</div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="h-3 w-3 rounded-md bg-amber-500 shrink-0" />
            <div>
              <div className="font-bold text-slate-900">{language === "es" ? "Media Distancia" : "Mid-Range"}</div>
              <div className="font-mono text-xs text-slate-500">{midPercent}% de tiros</div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="h-3 w-3 rounded-md bg-orange-500 shrink-0" />
            <div>
              <div className="font-bold text-slate-900">{language === "es" ? "Triples (>22ft)" : "3-Pointers"}</div>
              <div className="font-mono text-xs text-slate-500">{threePercent}% de tiros</div>
            </div>
          </div>
        </div>
      </div>

    </div>
  );
}
