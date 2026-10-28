"use client";

import React from "react";
import { Info, ShieldCheck } from "lucide-react";
import { usePreferences } from "@/context/PreferencesContext";

interface InjuryNoticeBannerProps {
  injuryReport?: {
    available: boolean;
    reason?: string | null;
  } | null;
  className?: string;
}

export function InjuryNoticeBanner({
  injuryReport,
  className = "",
}: InjuryNoticeBannerProps) {
  const { language } = usePreferences();
  const isEs = language === "es";

  // Only render when injury report exists and is NOT available
  if (!injuryReport || injuryReport.available) {
    return null;
  }

  const reason = injuryReport.reason?.trim() || (isEs ? "Deshabilitado por política de honestidad" : "Disabled per data honesty policy");

  return (
    <aside
      aria-label={isEs ? "Aviso sobre reporte de lesiones" : "Injury report notice"}
      className={`rounded-2xl border border-sky-200/80 bg-sky-50/70 p-4 shadow-2xs text-sky-950 transition-all ${className}`}
    >
      <div className="flex items-start gap-3">
        <div className="rounded-xl bg-sky-100 p-2 text-sky-700 shrink-0 mt-0.5">
          <Info className="h-4 w-4" />
        </div>
        <div className="space-y-1 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-extrabold text-sky-900">
              {isEs
                ? "Información de lesiones oficial no utilizada"
                : "Official injury report not in use"}
            </span>
            <span className="inline-flex items-center gap-1 rounded-md bg-sky-100/80 px-2 py-0.5 text-[10px] font-bold text-sky-800">
              <ShieldCheck className="h-3 w-3 text-sky-600" />
              <span>{isEs ? "Integridad de datos" : "Data integrity"}</span>
            </span>
          </div>

          <p className="text-sky-800/90 leading-relaxed font-medium">
            {isEs ? (
              <>
                Motivo: <strong className="font-semibold text-sky-950">{reason}</strong>. Las simulaciones de props se calculan utilizando exclusivamente líneas base de rotación y estadísticas reales de la base de datos, sin modificaciones heurísticas ni datos de lesiones inventados.
              </>
            ) : (
              <>
                Reason: <strong className="font-semibold text-sky-950">{reason}</strong>. Prop projections are computed using standard rotation baselines and verified historical player logs only, with no heuristic modifiers or fabricated injury statuses.
              </>
            )}
          </p>
        </div>
      </div>
    </aside>
  );
}
