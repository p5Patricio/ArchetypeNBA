"use client";

import React, { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { Navbar } from "@/components/Navbar";
import { CommandPalette } from "@/components/CommandPalette";
import { usePreferences } from "@/context/PreferencesContext";
import { getPaperSummary, type PaperSummaryResponse } from "@/lib/api";
import { MODE_ROUTES, type Bilingual } from "@/lib/modes";
import {
  Banknote,
  ShieldAlert,
  ArrowRight,
  Calendar,
  Trophy,
  TrendingUp,
  FlaskConical,
  RefreshCw,
  Scale,
  type LucideIcon,
} from "lucide-react";

interface HubCard {
  href: string;
  icon: LucideIcon;
  title: Bilingual;
  desc: Bilingual;
  experimental?: boolean;
}

// The hub only links to pages that are classified as betting in lib/modes.ts.
const HUB_CARDS: HubCard[] = [
  {
    href: "/week",
    icon: Calendar,
    title: { es: "Semana", en: "Week" },
    desc: {
      es: "Partidos de los próximos días con probabilidades del modelo, líneas del mercado y candidatos de apuesta simulada.",
      en: "Upcoming games with model probabilities, market lines and paper-bet candidates.",
    },
  },
  {
    href: "/paper",
    icon: Banknote,
    title: { es: "Paper Trading", en: "Paper Trading" },
    desc: {
      es: "Apuestas simuladas, bankroll virtual, CLV contra Pinnacle y Brier contra el mercado.",
      en: "Simulated bets, virtual bankroll, CLV against Pinnacle and Brier against the market.",
    },
  },
  {
    href: "/league",
    icon: Trophy,
    title: { es: "Model League", en: "Model League" },
    desc: {
      es: "Campeón y retadores en sombra: qué modelo predice mejor y cuándo podría ser promovido.",
      en: "Champion and shadow challengers: which model predicts best and when it could be promoted.",
    },
  },
  {
    href: "/props",
    icon: TrendingUp,
    title: { es: "Player Props", en: "Player Props" },
    desc: {
      es: "Proyecciones de puntos, rebotes y asistencias por jugador. Experimental: el modelo no está validado.",
      en: "Per-player points, rebounds and assists projections. Experimental: the model is not validated.",
    },
    experimental: true,
  },
];

function formatPct(value: number | null | undefined, digits = 1): string {
  if (value == null) return "—";
  return `${value > 0 ? "+" : ""}${(value * 100).toFixed(digits)}%`;
}

export default function BettingHubPage() {
  const { language } = usePreferences();
  const isEs = language === "es";
  const [isCommandOpen, setIsCommandOpen] = useState(false);

  const [summary, setSummary] = useState<PaperSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      setSummary(await getPaperSummary());
    } catch (err) {
      console.error("Error fetching paper summary for the betting hub:", err);
      setSummary(null);
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Headline numbers come straight from the paper-trading summary; nothing is hardcoded.
  const flat = summary?.strategies.find((s) => s.strategy === "flat") ?? summary?.strategies[0] ?? null;
  const clv = summary?.pinnacle_clv ?? null;
  const brier = summary?.brier ?? null;

  const stats: { label: string; value: string; hint: string }[] = [
    {
      label: isEs ? "Apuestas simuladas" : "Paper bets",
      value: flat ? String(flat.bets) : "—",
      hint: flat
        ? isEs
          ? `${flat.settled} liquidadas • estrategia ${flat.strategy}`
          : `${flat.settled} settled • ${flat.strategy} strategy`
        : isEs
        ? "Sin datos"
        : "No data",
    },
    {
      label: "ROI",
      value: formatPct(flat?.roi),
      hint: isEs ? "Ruido con muestras pequeñas; no es evidencia" : "Noise at small samples; not evidence",
    },
    {
      label: isEs ? "CLV vs Pinnacle" : "CLV vs Pinnacle",
      value: formatPct(clv?.mean_clv, 2),
      hint: clv
        ? isEs
          ? `${clv.games} partidos independientes${clv.t_stat != null ? ` • t = ${clv.t_stat.toFixed(2)}` : ""}`
          : `${clv.games} independent games${clv.t_stat != null ? ` • t = ${clv.t_stat.toFixed(2)}` : ""}`
        : isEs
        ? "Sin datos"
        : "No data",
    },
    {
      label: isEs ? "Brier modelo vs mercado" : "Brier model vs market",
      value:
        brier?.brier_model != null && brier?.brier_market != null
          ? `${brier.brier_model.toFixed(4)} vs ${brier.brier_market.toFixed(4)}`
          : "—",
      hint: brier
        ? isEs
          ? `Menor es mejor • ${brier.games_compared} partidos`
          : `Lower is better • ${brier.games_compared} games`
        : isEs
        ? "Sin datos"
        : "No data",
    },
  ];

  return (
    <div className="min-h-screen bg-[#F8FAFC] text-slate-900 selection:bg-emerald-100 selection:text-emerald-900">
      <Navbar onOpenSearch={() => setIsCommandOpen(true)} />
      <CommandPalette isOpen={isCommandOpen} onClose={() => setIsCommandOpen(false)} />

      <main className="md:pl-64">
        {/* Hero */}
        <section className="border-b border-slate-200 bg-gradient-to-b from-emerald-50/50 via-white to-white py-10 lg:py-14 shadow-2xs">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <div className="inline-flex items-center gap-2 rounded-full border border-emerald-300 bg-emerald-50 px-3.5 py-1 text-xs font-black text-emerald-800 shadow-2xs">
                <Banknote className="h-3.5 w-3.5 text-emerald-600" />
                <span>
                  {isEs ? "APUESTAS • PAPER TRADING • CAPITAL FICTICIO" : "BETTING • PAPER TRADING • VIRTUAL FUNDS"}
                </span>
              </div>
            </div>
            <h1 className="text-3xl sm:text-4xl font-black tracking-tight text-slate-900">
              {isEs ? "Hub de Apuestas" : "Betting Hub"}
            </h1>
            <p className="max-w-3xl text-xs sm:text-sm text-slate-600 leading-relaxed">
              {isEs
                ? "Sistema de investigación cuantitativa: predice partidos, simula apuestas y mide si el modelo aporta algo frente al mercado. Todo en un solo lugar, separado del análisis de jugadores."
                : "A quantitative research system: it predicts games, simulates bets and measures whether the model adds anything over the market. Kept apart from the player analytics side."}
            </p>
          </div>
        </section>

        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-8 space-y-8">
          {/* Permanent honest notice (not dismissable) */}
          <section
            role="note"
            aria-labelledby="betting-notice-heading"
            className="rounded-3xl border border-amber-300 bg-amber-50 p-5 sm:p-6 shadow-xs"
          >
            <h2
              id="betting-notice-heading"
              className="flex items-center gap-2 text-sm sm:text-base font-black text-amber-950"
            >
              <ShieldAlert className="h-5 w-5 text-amber-600 shrink-0" />
              {isEs ? "Léelo antes de interpretar nada" : "Read this before interpreting anything"}
            </h2>
            <ul className="mt-3 space-y-2 text-xs sm:text-sm text-amber-950/90 leading-relaxed list-disc pl-5">
              <li>
                {isEs
                  ? "Solo paper trading: no se usa dinero real y esta plataforma no realiza apuestas reales."
                  : "Paper trading only: no real money is used and this platform never places real bets."}
              </li>
              <li>
                {isEs
                  ? "El modelo actual todavía no supera al mercado: el cierre de Pinnacle es más preciso que nuestras probabilidades."
                  : "The current model does not beat the market yet: Pinnacle's closing line is more accurate than our probabilities."}
              </li>
              <li>
                {isEs
                  ? "Juzga el progreso por el CLV contra Pinnacle, no por el ROI. El ROI necesita miles de apuestas para significar algo."
                  : "Judge progress by CLV against Pinnacle, not by ROI. ROI needs thousands of bets to mean anything."}
              </li>
            </ul>
          </section>

          {/* Live headline numbers */}
          <section aria-labelledby="betting-stats-heading" className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <h2 id="betting-stats-heading" className="text-lg sm:text-xl font-black text-slate-900 tracking-tight">
                {isEs ? "Cifras en vivo" : "Live headline numbers"}
              </h2>
              <button
                type="button"
                onClick={load}
                disabled={loading}
                aria-label={isEs ? "Actualizar cifras" : "Refresh numbers"}
                className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-bold text-slate-700 shadow-2xs hover:border-emerald-300 hover:bg-emerald-50/40 transition disabled:opacity-50 cursor-pointer focus-visible:ring-2 focus-visible:ring-emerald-500 outline-none"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin text-emerald-600" : ""}`} />
                <span>{isEs ? "Actualizar" : "Refresh"}</span>
              </button>
            </div>

            {failed && (
              <div role="alert" className="rounded-2xl border border-rose-200 bg-rose-50 p-3 text-xs font-bold text-rose-900">
                {isEs
                  ? "No se pudo cargar el resumen de paper trading; no se muestran cifras."
                  : "Could not load the paper-trading summary; no figures are shown."}
              </div>
            )}

            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4" aria-busy={loading}>
              {stats.map((s) => (
                <div key={s.label} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-xs">
                  <div className="text-[11px] font-semibold text-slate-400 mb-1">{s.label}</div>
                  <div
                    className={`text-lg sm:text-xl font-black tabular-nums text-slate-900 ${
                      loading ? "animate-pulse text-slate-300" : ""
                    }`}
                  >
                    {loading ? "…" : s.value}
                  </div>
                  <div className="mt-1 text-[10px] text-slate-500 leading-snug">{loading ? "" : s.hint}</div>
                </div>
              ))}
            </div>
            <p className="flex items-start gap-1.5 text-[11px] text-slate-500">
              <Scale className="h-3.5 w-3.5 mt-0.5 shrink-0 text-slate-400" />
              <span>
                {isEs
                  ? "Fuente: resumen de paper trading en vivo (GET /api/v1/paper/summary). Muestras pequeñas: tómalas como ruido hasta que el CLV tenga significancia."
                  : "Source: live paper-trading summary (GET /api/v1/paper/summary). Small samples: treat as noise until CLV is significant."}
              </span>
            </p>
          </section>

          {/* Section cards */}
          <section aria-labelledby="betting-sections-heading" className="space-y-3">
            <h2 id="betting-sections-heading" className="text-lg sm:text-xl font-black text-slate-900 tracking-tight">
              {isEs ? "Secciones" : "Sections"}
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {HUB_CARDS.filter((c) => MODE_ROUTES.some((r) => r.href === c.href && r.mode === "betting")).map((card) => {
                const Icon = card.icon;
                return (
                  <Link
                    key={card.href}
                    href={card.href}
                    className="group flex flex-col justify-between gap-4 rounded-3xl border border-slate-200 bg-white p-5 shadow-xs transition hover:border-emerald-300 hover:shadow-md focus-visible:ring-2 focus-visible:ring-emerald-500 outline-none"
                  >
                    <div className="space-y-2">
                      <div className="flex items-center gap-3">
                        <div className="h-10 w-10 rounded-2xl border border-emerald-200 bg-emerald-50 flex items-center justify-center">
                          <Icon className="h-5 w-5 text-emerald-600" />
                        </div>
                        <h3 className="text-base font-black text-slate-900">{card.title[language]}</h3>
                        {card.experimental && (
                          <span className="inline-flex items-center gap-1 rounded-md border border-amber-300 bg-amber-50 px-1.5 py-0.5 text-[9px] font-black text-amber-800">
                            <FlaskConical className="h-3 w-3" />
                            {isEs ? "EXPERIMENTAL" : "EXPERIMENTAL"}
                          </span>
                        )}
                      </div>
                      <p className="text-xs sm:text-sm text-slate-600 leading-relaxed">{card.desc[language]}</p>
                    </div>
                    <span className="inline-flex items-center gap-1.5 text-xs font-black text-emerald-700">
                      {isEs ? "Abrir" : "Open"}
                      <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
                    </span>
                  </Link>
                );
              })}
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}
