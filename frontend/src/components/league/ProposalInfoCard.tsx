"use client";

import React from "react";
import { usePreferences } from "@/context/PreferencesContext";
import { FlaskConical, Calendar, Cpu } from "lucide-react";

interface ProposalInfoCardProps {
  lastProposal?: string | null;
  lastProposalSummary?: string | null;
}

export function ProposalInfoCard({
  lastProposal,
  lastProposalSummary,
}: ProposalInfoCardProps) {
  const { language } = usePreferences();
  const isEs = language === "es";

  return (
    <div className="rounded-3xl border border-slate-200 bg-white p-6 sm:p-8 shadow-xs space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-orange-100 text-orange-600 shrink-0">
            <FlaskConical className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-base sm:text-lg font-black text-slate-900">
              {isEs ? "Laboratorio de Candidatos & Búsqueda Automática" : "Candidate Lab & Automated Search"}
            </h3>
            <p className="text-xs text-slate-500">
              {isEs
                ? "Evaluación semanal de arquitecturas de modelos (presupuesto de 4 minutos por corrida)."
                : "Weekly candidate architecture evaluation (4-minute computational budget)."}
            </p>
          </div>
        </div>

        {lastProposal && (
          <div className="flex items-center gap-1.5 text-xs text-slate-500 bg-slate-50 border border-slate-200 px-3 py-1.5 rounded-xl font-mono">
            <Calendar className="h-3.5 w-3.5 text-slate-400" />
            <span>
              {isEs ? "Última propuesta:" : "Last proposal:"}{" "}
              {new Date(lastProposal).toLocaleDateString(isEs ? "es-MX" : "en-US", {
                month: "short",
                day: "numeric",
                year: "numeric",
              })}
            </span>
          </div>
        )}
      </div>

      <div className="rounded-2xl bg-slate-50 border border-slate-100 p-4 text-xs text-slate-600 leading-relaxed space-y-2">
        <div className="font-semibold text-slate-800 flex items-center gap-1.5">
          <Cpu className="h-4 w-4 text-orange-600" />
          <span>{isEs ? "Metodología Walk-Forward Time-Split:" : "Walk-Forward Time-Split Protocol:"}</span>
        </div>
        <p>
          {isEs
            ? "El laboratorio entrena sobre temporadas históricas [T-9, T-2] y valida estrictamente en hold-out [T-1, T]. Se evalúan 40 configuraciones Elo aleatorias más modelos de regresión ridge y logística con 12 variables sin filtraciones (leak-free)."
            : "The lab selects hyperparameter configurations across seasons [T-9, T-2] and tests strictly on out-of-sample hold-out [T-1, T]. It benchmarks 40 random Elo seeds alongside ridge/logistic models over 12 leak-free features."}
        </p>

        {lastProposalSummary ? (
          <div className="pt-2 border-t border-slate-200/60">
            <span className="font-bold text-slate-700 block mb-0.5">
              {isEs ? "Resumen de la última propuesta:" : "Proposal summary:"}
            </span>
            <p className="font-mono text-[11px] text-slate-800 bg-white p-2.5 rounded-xl border border-slate-200">
              {lastProposalSummary}
            </p>
          </div>
        ) : (
          <div className="pt-2 text-slate-500 italic">
            {isEs
              ? "No se han propuesto nuevos candidatos en la ventana reciente; el retador en sombra actual continúa acumulando partidos."
              : "No new candidates were proposed recently; current shadow challenger continues gathering paired games."}
          </div>
        )}
      </div>
    </div>
  );
}
