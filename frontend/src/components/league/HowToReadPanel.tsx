"use client";

import React, { useState } from "react";
import { usePreferences } from "@/context/PreferencesContext";
import { ChevronDown, ChevronUp, BookOpen, Lightbulb, Scale, ShieldAlert, CheckCircle2 } from "lucide-react";

export function HowToReadPanel() {
  const [isOpen, setIsOpen] = useState(false);
  const { language } = usePreferences();
  const isEs = language === "es";

  return (
    <div className="rounded-3xl border border-slate-200 bg-white overflow-hidden shadow-xs transition-all">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        className="w-full flex items-center justify-between p-6 sm:p-7 text-left hover:bg-slate-50/70 transition cursor-pointer focus-visible:ring-2 focus-visible:ring-orange-500 outline-none"
      >
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-orange-100 text-orange-600 shrink-0">
            <BookOpen className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-base sm:text-lg font-black text-slate-900">
              {isEs ? "¿Cómo interpretar la Liga de Modelos?" : "How to Read the Model League?"}
            </h3>
            <p className="text-xs text-slate-500">
              {isEs
                ? "Reglas estadísticas, métricas de decisión e intervalos bootstrap explicados sin tecnicismos."
                : "Statistical gates, scoring rules, and bootstrap intervals explained in plain language."}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 text-xs font-bold text-slate-600 shrink-0">
          <span>{isOpen ? (isEs ? "Ocultar" : "Collapse") : isEs ? "Ver guía" : "Expand guide"}</span>
          {isOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </div>
      </button>

      {isOpen && (
        <div className="px-6 pb-6 sm:px-8 sm:pb-8 pt-2 border-t border-slate-100 text-xs sm:text-sm text-slate-600 space-y-4 animate-in fade-in duration-200">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
            {/* Box 1: Ganancia de Log-Loss */}
            <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4 space-y-1.5">
              <div className="font-bold text-slate-900 flex items-center gap-1.5">
                <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0" />
                <span>{isEs ? "Ganancia de Log-Loss Positiva (> 0)" : "Positive Log-Loss Gain (> 0)"}</span>
              </div>
              <p className="text-xs leading-relaxed text-slate-600">
                {isEs
                  ? "Log-loss (entropía cruzada) premia la calibración probabilística honesta. Una ganancia positiva indica que el retador asignó probabilidades más certeras al ganador real del partido que el campeón actual."
                  : "Log-loss evaluates true probabilistic calibration. A positive gain indicates the challenger assigned higher probabilities to the actual game winners compared to the champion."}
              </p>
            </div>

            {/* Box 2: El Intervalo de Confianza debe superar 0 */}
            <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4 space-y-1.5">
              <div className="font-bold text-slate-900 flex items-center gap-1.5">
                <Scale className="h-4 w-4 text-orange-600 shrink-0" />
                <span>{isEs ? "El Intervalo del 95% no debe cruzar cero" : "95% CI Must Not Cross Zero"}</span>
              </div>
              <p className="text-xs leading-relaxed text-slate-600">
                {isEs
                  ? "Si el intervalo de confianza del 95% cruza la línea vertical de 0.0 (CI low ≤ 0), la aparente ventaja podría ser simple suerte o ruido. Sólo se autoriza la promoción cuando todo el intervalo está a la derecha del cero."
                  : "If the 95% bootstrap confidence interval touches or crosses 0.0, the edge could be variance or luck. Promotion strictly requires the entire interval to sit above zero."}
              </p>
            </div>

            {/* Box 3: Por qué toma semanas */}
            <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4 space-y-1.5">
              <div className="font-bold text-slate-900 flex items-center gap-1.5">
                <Lightbulb className="h-4 w-4 text-amber-600 shrink-0" />
                <span>{isEs ? "Por qué se requieren semanas (n ≥ 150)" : "Why It Takes Weeks (n ≥ 150)"}</span>
              </div>
              <p className="text-xs leading-relaxed text-slate-600">
                {isEs
                  ? "En muestras de 20 a 50 partidos la varianza de la NBA domina los resultados. Exigir un mínimo de 150 partidos pares y al menos 14 días en vivo protege al sistema de falsos positivos."
                  : "Over 20–50 games NBA variance dominates the scores. Requiring at least 150 paired games and 14 days prevents noise-driven promotions."}
              </p>
            </div>

            {/* Box 4: Comparación vs Mercado Sharp */}
            <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4 space-y-1.5">
              <div className="font-bold text-slate-900 flex items-center gap-1.5">
                <ShieldAlert className="h-4 w-4 text-sky-600 shrink-0" />
                <span>{isEs ? "Referencia con el Cierre Sharp" : "Benchmark vs Sharp Market"}</span>
              </div>
              <p className="text-xs leading-relaxed text-slate-600">
                {isEs
                  ? "El cierre sin margen (de-vigged) de Pinnacle es el consenso más eficiente del planeta. Evaluamos periódicamente el Brier score de nuestros modelos contra ese estándar para saber si nos acercamos a la frontera de eficiencia."
                  : "Pinnacle's de-vigged closing price is the sharpest probability consensus in sports. We track the Brier gap against Pinnacle to measure distance to the market efficiency frontier."}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
