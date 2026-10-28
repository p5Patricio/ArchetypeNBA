"use client";

import React from "react";
import { type RoleChangeResponse } from "@/lib/api";
import { usePreferences } from "@/context/PreferencesContext";
import { History, CheckCircle2, ArrowDownCircle, XCircle, Inbox } from "lucide-react";

interface RoleHistoryTableProps {
  changes: RoleChangeResponse[];
}

export function RoleHistoryTable({ changes }: RoleHistoryTableProps) {
  const { language } = usePreferences();
  const isEs = language === "es";

  const getDecisionBadge = (decision: string) => {
    switch (decision.toLowerCase()) {
      case "promote":
      case "promoted":
        return {
          label: isEs ? "Promoción" : "Promotion",
          styles: "bg-emerald-50 text-emerald-800 border-emerald-200",
          icon: CheckCircle2,
        };
      case "demote":
      case "demoted":
        return {
          label: isEs ? "Degradación" : "Demotion",
          styles: "bg-amber-50 text-amber-800 border-amber-200",
          icon: ArrowDownCircle,
        };
      case "retire":
      case "retired":
        return {
          label: isEs ? "Retiro" : "Retirement",
          styles: "bg-rose-50 text-rose-800 border-rose-200",
          icon: XCircle,
        };
      default:
        return {
          label: decision,
          styles: "bg-slate-100 text-slate-700 border-slate-200",
          icon: History,
        };
    }
  };

  return (
    <div className="rounded-3xl border border-slate-200 bg-white p-6 sm:p-8 shadow-xs">
      <div className="flex items-center gap-2 mb-2">
        <div className="inline-flex items-center gap-1.5 rounded-full border border-orange-200 bg-orange-50 px-3 py-0.5 text-[11px] font-black text-orange-800">
          <History className="h-3 w-3 text-orange-600" />
          <span>{isEs ? "REGISTRO DE AUDITORÍA" : "AUDIT LOG"}</span>
        </div>
      </div>
      <h3 className="text-xl sm:text-2xl font-black text-slate-900 tracking-tight">
        {isEs ? "Historial de Promociones y Retiros" : "Promotion & Retirement History"}
      </h3>
      <p className="text-xs sm:text-sm text-slate-500 mt-1 mb-6">
        {isEs
          ? "Trazabilidad inmutable de cada decisión de ascenso a campeón o retiro de retadores basada en evidencia matemática."
          : "Immutable audit trail of every model promotion to champion or challenger retirement based on statistical gates."}
      </p>

      {changes.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50/50 p-8 text-center">
          <Inbox className="mx-auto h-8 w-8 text-slate-400 mb-2" />
          <p className="text-sm font-semibold text-slate-700">
            {isEs ? "Sin cambios de rol registrados aún" : "No role transitions recorded yet"}
          </p>
          <p className="text-xs text-slate-500 mt-1 max-w-md mx-auto">
            {isEs
              ? "El campeón inaugural (elo_538) se mantiene en ejercicio y los retadores acumulan muestra hacia el umbral de 150 partidos."
              : "The inaugural champion (elo_538) remains active as challengers accumulate paired games toward the 150-game gate."}
          </p>
        </div>
      ) : (
        <>
          {/* Mobile Card View */}
          <div className="block md:hidden space-y-3">
            {changes.map((change, idx) => {
              const badge = getDecisionBadge(change.decision);
              const BadgeIcon = badge.icon;
              return (
                <div
                  key={idx}
                  className="rounded-2xl border border-slate-200 bg-white p-4 space-y-2 shadow-2xs"
                >
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-mono text-[11px] text-slate-500">
                      {change.at
                        ? new Date(change.at).toLocaleDateString(isEs ? "es-MX" : "en-US", {
                            month: "short",
                            day: "numeric",
                            year: "numeric",
                          })
                        : "—"}
                    </span>
                    <span
                      className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-black border ${badge.styles}`}
                    >
                      <BadgeIcon className="h-3 w-3" />
                      <span>{badge.label}</span>
                    </span>
                  </div>

                  <div className="font-black text-sm text-slate-900">{change.model}</div>

                  <p className="text-xs text-slate-600 leading-relaxed bg-slate-50 p-2.5 rounded-xl border border-slate-100">
                    {change.reason}
                  </p>
                </div>
              );
            })}
          </div>

          {/* Desktop Table */}
          <div className="hidden md:block overflow-x-auto">
            <table
              className="w-full text-left text-xs text-slate-700"
              aria-label={
                isEs
                  ? "Historial de promociones y transiciones de la liga de modelos"
                  : "Model league promotion and role transition history"
              }
            >
              <caption className="sr-only">
                {isEs ? "Tabla de auditoría de modelos" : "Model audit ledger table"}
              </caption>
              <thead className="border-b border-slate-200 bg-slate-50 text-[11px] font-black uppercase tracking-wider text-slate-600">
                <tr>
                  <th scope="col" className="px-3.5 py-3 rounded-l-xl">
                    {isEs ? "Fecha" : "Date"}
                  </th>
                  <th scope="col" className="px-3.5 py-3">
                    {isEs ? "Decisión" : "Decision"}
                  </th>
                  <th scope="col" className="px-3.5 py-3">
                    {isEs ? "Modelo" : "Model"}
                  </th>
                  <th scope="col" className="px-3.5 py-3 rounded-r-xl">
                    {isEs ? "Motivo / Justificación Matemática" : "Reason / Statistical Audit"}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {changes.map((change, idx) => {
                  const badge = getDecisionBadge(change.decision);
                  const BadgeIcon = badge.icon;
                  return (
                    <tr key={idx} className="hover:bg-slate-50/70 transition">
                      <td className="px-3.5 py-3 font-mono text-[11px] text-slate-600 whitespace-nowrap">
                        {change.at
                          ? new Date(change.at).toLocaleDateString(isEs ? "es-MX" : "en-US", {
                              month: "short",
                              day: "numeric",
                              year: "numeric",
                            })
                          : "—"}
                      </td>
                      <td className="px-3.5 py-3 whitespace-nowrap">
                        <span
                          className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-black border ${badge.styles}`}
                        >
                          <BadgeIcon className="h-3 w-3" />
                          <span>{badge.label}</span>
                        </span>
                      </td>
                      <td className="px-3.5 py-3 font-bold text-slate-900 whitespace-nowrap">
                        {change.model}
                      </td>
                      <td className="px-3.5 py-3 text-slate-600 leading-relaxed">{change.reason}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
