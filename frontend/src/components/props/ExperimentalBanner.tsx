"use client";

import React from "react";
import Link from "next/link";
import { FlaskConical } from "lucide-react";
import { usePreferences } from "@/context/PreferencesContext";
import type { PropsShadowSummaryResponse } from "@/lib/api";

interface ExperimentalBannerProps {
  /** Live shadow evaluation of the props model vs the bookmaker, when the API exposes it. */
  shadow?: PropsShadowSummaryResponse | null;
  loading?: boolean;
}

const fmt = (v: number) => v.toFixed(4);
const fmtSigned = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(4)}`;

/**
 * Permanent (not dismissable) warning that the props model is not validated.
 * Numbers come from the live shadow evaluation (GET /api/v1/paper/summary -> props_shadow);
 * without them the finding is stated qualitatively.
 */
export function ExperimentalBanner({ shadow, loading = false }: ExperimentalBannerProps) {
  const { language } = usePreferences();
  const isEs = language === "es";

  const hasNumbers =
    !!shadow &&
    shadow.n > 0 &&
    shadow.brier_model != null &&
    shadow.brier_book != null &&
    shadow.brier_diff != null;

  const ciLow = shadow?.brier_diff_ci_low ?? null;
  const ciHigh = shadow?.brier_diff_ci_high ?? null;
  const hasCi = ciLow != null && ciHigh != null;
  // brier_diff = model - book; positive means the model is less accurate than the book.
  const significantlyWorse = hasNumbers && hasCi && (ciLow as number) > 0;

  let explanation: string;
  if (!hasNumbers) {
    explanation = isEs
      ? "En la evaluación en sombra, el modelo de props resultó menos preciso que las probabilidades de la propia casa de apuestas. No hay cifras en vivo disponibles ahora mismo."
      : "In the shadow evaluation, the props model came out less accurate than the bookmaker's own probabilities. Live figures are not available right now.";
  } else if (significantlyWorse) {
    explanation = isEs
      ? "El modelo es peor que la casa de apuestas, y la diferencia no es ruido: el intervalo de confianza del 95% excluye el cero."
      : "The model is worse than the bookmaker, and the gap is not noise: the 95% confidence interval excludes zero.";
  } else {
    explanation = isEs
      ? "El modelo no ha demostrado superar a la casa de apuestas en la evaluación en sombra."
      : "The model has not shown that it beats the bookmaker in the shadow evaluation.";
  }

  return (
    <section
      role="note"
      aria-labelledby="props-experimental-heading"
      className="rounded-3xl border-2 border-amber-400 bg-amber-50 p-5 sm:p-6 shadow-xs"
    >
      <div className="flex items-start gap-3">
        <div className="h-10 w-10 shrink-0 rounded-2xl bg-amber-500 text-white flex items-center justify-center">
          <FlaskConical className="h-5 w-5" />
        </div>
        <div className="space-y-2 min-w-0">
          <h2 id="props-experimental-heading" className="text-sm sm:text-base font-black text-amber-950">
            {isEs ? "Experimental — no validado" : "Experimental — not validated"}
          </h2>
          <p className="text-xs sm:text-sm text-amber-950/90 leading-relaxed">{explanation}</p>

          {loading && !shadow ? (
            <p className="text-[11px] font-medium text-amber-900/70">
              {isEs ? "Cargando evaluación en sombra…" : "Loading shadow evaluation…"}
            </p>
          ) : (
            hasNumbers && (
              <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 rounded-2xl border border-amber-200 bg-white/70 p-3 text-xs">
                <div>
                  <dt className="text-amber-900/70">{isEs ? "Brier del modelo" : "Model Brier"}</dt>
                  <dd className="font-mono font-black text-slate-900 tabular-nums">{fmt(shadow!.brier_model as number)}</dd>
                </div>
                <div>
                  <dt className="text-amber-900/70">{isEs ? "Brier de la casa" : "Bookmaker Brier"}</dt>
                  <dd className="font-mono font-black text-slate-900 tabular-nums">{fmt(shadow!.brier_book as number)}</dd>
                </div>
                <div>
                  <dt className="text-amber-900/70">
                    {isEs ? "Diferencia (IC 95%)" : "Difference (95% CI)"}
                  </dt>
                  <dd className="font-mono font-black text-slate-900 tabular-nums">
                    {fmtSigned(shadow!.brier_diff as number)}
                    {hasCi && (
                      <span className="block text-[10px] font-semibold text-slate-600">
                        [{fmtSigned(ciLow as number)}, {fmtSigned(ciHigh as number)}]
                      </span>
                    )}
                  </dd>
                </div>
                <div>
                  <dt className="text-amber-900/70">{isEs ? "Predicciones evaluadas" : "Predictions evaluated"}</dt>
                  <dd className="font-mono font-black text-slate-900 tabular-nums">{shadow!.n}</dd>
                </div>
              </dl>
            )
          )}

          <p className="text-xs text-amber-950/90 leading-relaxed">
            {isEs
              ? "El Brier mide el error de las probabilidades (menor es mejor). Por eso los valores de EV y ventaja de esta página son cifras del modelo sin validar, no oportunidades reales, y no se muestra ninguna recomendación de monto. Las proyecciones (media, mediana, rango) siguen disponibles como análisis. Solo paper trading, sin dinero real."
              : "Brier measures probability error (lower is better). That is why the EV and edge figures on this page are unvalidated model numbers, not real opportunities, and no stake recommendation is shown. The projections (mean, median, range) remain available as analysis. Paper trading only, no real money."}{" "}
            <Link href="/paper" className="font-bold underline underline-offset-2 hover:text-amber-700">
              {isEs ? "Ver la evidencia completa" : "See the full evidence"}
            </Link>
          </p>
        </div>
      </div>
    </section>
  );
}
