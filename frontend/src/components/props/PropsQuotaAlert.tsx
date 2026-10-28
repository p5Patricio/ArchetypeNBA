"use client";

import React from "react";
import { ShieldAlert, RefreshCw, Calendar, Sparkles } from "lucide-react";
import { usePreferences } from "@/context/PreferencesContext";

interface PropsQuotaAlertProps {
  message?: string | null;
  onRetry?: () => void;
  onDismiss?: () => void;
  className?: string;
}

export function PropsQuotaAlert({
  message,
  onRetry,
  onDismiss,
  className = "",
}: PropsQuotaAlertProps) {
  const { language } = usePreferences();
  const isEs = language === "es";

  return (
    <div
      role="alert"
      aria-live="assertive"
      className={`rounded-3xl border border-amber-200 bg-gradient-to-r from-amber-50 via-orange-50/50 to-amber-50 p-6 shadow-sm transition-all ${className}`}
    >
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div className="flex items-start gap-3.5">
          <div className="rounded-2xl bg-amber-100 p-3 text-amber-700 shrink-0">
            <ShieldAlert className="h-6 w-6 text-amber-600" />
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              <h3 className="text-sm sm:text-base font-black text-amber-950">
                {isEs
                  ? "Actualización pausada para proteger tus créditos de The Odds API"
                  : "Refresh paused to protect your monthly free Odds API credits"}
              </h3>
            </div>

            <p className="text-xs text-amber-800 leading-relaxed max-w-2xl font-medium">
              {isEs
                ? "El guardián de créditos automáticos detectó que la cuota restante se encuentra cerca del piso de seguridad (25 créditos). Para evitar agotar el plan mensual gratuito de 500 créditos, las consultas en vivo han sido temporalmente pausadas."
                : "The automated credit guard detected that remaining quota is near the safety floor (25 credits). Live fetches have been paused to prevent exhausting your 500 requests/mo free tier."}
            </p>

            {message && (
              <div className="rounded-xl bg-amber-100/60 px-3 py-1.5 text-[11px] font-mono text-amber-900 border border-amber-200/60 max-w-xl">
                <span className="font-bold">{isEs ? "Detalle:" : "Detail:"}</span> {message}
              </div>
            )}

            <div className="flex flex-wrap items-center gap-3 pt-1 text-[11px] text-amber-700 font-semibold">
              <span className="inline-flex items-center gap-1">
                <Calendar className="h-3.5 w-3.5 text-amber-600" />
                <span>
                  {isEs
                    ? "Reinicio de cuota: 1º del próximo mes"
                    : "Quota resets: 1st of next month"}
                </span>
              </span>
              <span>•</span>
              <span className="inline-flex items-center gap-1">
                <Sparkles className="h-3.5 w-3.5 text-amber-600" />
                <span>
                  {isEs
                    ? "Los datos en caché siguen disponibles para análisis"
                    : "Cached slates remain fully available"}
                </span>
              </span>
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 self-end sm:self-center shrink-0">
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="rounded-xl border border-amber-300 bg-white px-3.5 py-2 text-xs font-bold text-amber-900 shadow-2xs hover:bg-amber-100/60 transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 cursor-pointer inline-flex items-center gap-1.5"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              <span>{isEs ? "Reintentar" : "Retry"}</span>
            </button>
          )}

          {onDismiss && (
            <button
              type="button"
              onClick={onDismiss}
              className="rounded-xl px-3 py-2 text-xs font-semibold text-amber-700 hover:bg-amber-100 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 cursor-pointer"
            >
              {isEs ? "Descartar" : "Dismiss"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
