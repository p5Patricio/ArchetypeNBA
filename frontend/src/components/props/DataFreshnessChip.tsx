"use client";

import React from "react";
import { Clock, RefreshCw, AlertTriangle } from "lucide-react";
import { usePreferences } from "@/context/PreferencesContext";

interface DataFreshnessChipProps {
  stale?: boolean;
  age?: string | null;
  date?: string;
  onRefresh: () => void;
  isRefreshing: boolean;
  disabled?: boolean;
  className?: string;
}

export function DataFreshnessChip({
  stale = false,
  age,
  date,
  onRefresh,
  isRefreshing,
  disabled = false,
  className = "",
}: DataFreshnessChipProps) {
  const { language } = usePreferences();
  const isEs = language === "es";

  const formattedAge = age
    ? isEs
      ? `hace ${age}`
      : `${age} ago`
    : isEs
    ? "recién"
    : "just now";

  if (stale) {
    return (
      <div
        className={`inline-flex items-center gap-2 rounded-2xl border border-amber-300 bg-amber-50/90 px-3 py-1.5 text-xs text-amber-900 shadow-2xs transition-all ${className}`}
        role="status"
        aria-label={
          isEs
            ? `Datos desactualizados del ${date || "día anterior"}`
            : `Stale data from ${date || "previous slate"}`
        }
      >
        <AlertTriangle className="h-3.5 w-3.5 text-amber-600 shrink-0" />
        <span className="font-bold">
          {isEs ? "Desactualizado" : "Stale"}
          {date && (
            <span className="font-normal text-amber-800">
              {" "}
              — {isEs ? "del" : "from"} {date}
            </span>
          )}
        </span>

        <button
          type="button"
          onClick={onRefresh}
          disabled={disabled || isRefreshing}
          aria-label={isEs ? "Actualizar datos ahora" : "Refresh data now"}
          className="ml-1 inline-flex items-center gap-1 rounded-xl bg-amber-600 px-2 py-0.5 text-[11px] font-bold text-white hover:bg-amber-700 active:scale-95 disabled:opacity-50 transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 cursor-pointer"
        >
          <RefreshCw
            className={`h-3 w-3 ${isRefreshing ? "animate-spin" : ""}`}
          />
          <span>{isRefreshing ? (isEs ? "Cargando..." : "Refreshing...") : isEs ? "Actualizar" : "Refresh"}</span>
        </button>
      </div>
    );
  }

  return (
    <div
      className={`inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white/95 px-3 py-1.5 text-xs text-slate-700 shadow-2xs transition-all ${className}`}
      role="status"
      aria-label={
        isEs
          ? `Datos actualizados ${formattedAge}`
          : `Data updated ${formattedAge}`
      }
    >
      <span className="relative flex h-2 w-2 shrink-0">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
        <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
      </span>

      <Clock className="h-3.5 w-3.5 text-slate-400 shrink-0" />
      <span className="font-medium text-slate-600">
        {isEs ? "Actualizado" : "Updated"}{" "}
        <span className="font-bold text-slate-900 tabular-nums">
          {formattedAge}
        </span>
      </span>

      <button
        type="button"
        onClick={onRefresh}
        disabled={disabled || isRefreshing}
        title={isEs ? "Actualizar líneas" : "Refresh lines"}
        aria-label={isEs ? "Actualizar líneas de props" : "Refresh prop lines"}
        className="ml-1 rounded-lg p-1 text-slate-400 hover:text-orange-600 hover:bg-orange-50 active:scale-95 disabled:opacity-50 transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-500 cursor-pointer"
      >
        <RefreshCw
          className={`h-3.5 w-3.5 ${isRefreshing ? "animate-spin text-orange-600" : ""}`}
        />
      </button>
    </div>
  );
}
