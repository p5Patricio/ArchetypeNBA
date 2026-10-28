"use client";

import React from "react";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { TeamLogo } from "@/components/TeamLogo";
import { usePreferences } from "@/context/PreferencesContext";
import type { PropItem } from "@/lib/api";
import {
  ArrowUpRight,
  ArrowDownRight,
  ShieldCheck,
  Percent,
  Sparkles,
} from "lucide-react";
import { HelpPopover } from "./HelpPopover";

interface PropCardProps {
  prop: PropItem;
  className?: string;
}

export function formatOdds(odds: number): string {
  if (odds > 0) return `+${odds}`;
  return `${odds}`;
}

export function getSideView(prop: PropItem) {
  const isUnder = prop.side === "under";
  const price = isUnder && prop.under_odds != null ? prop.under_odds : prop.over_odds;
  const modelProb = isUnder ? prop.prob_under ?? 1 - prop.prob_over : prop.prob_over;
  return {
    isUnder,
    label: isUnder ? "Under" : "Over",
    price,
    modelPct: modelProb * 100,
    bookPct: prop.book_implied_prob * 100,
    devigged: prop.devigged === true,
  };
}

export function PropCard({ prop, className = "" }: PropCardProps) {
  const { language } = usePreferences();
  const isEs = language === "es";

  const sideView = getSideView(prop);
  const hasPositiveEV = prop.expected_value_pct > 0;

  // Stat badge
  const getStatBadge = (statType: string) => {
    const st = statType.toUpperCase();
    if (st === "PTS") {
      return {
        label: isEs ? "Puntos" : "Points",
        color: "bg-orange-50 border-orange-200 text-orange-700",
      };
    }
    if (st === "REB") {
      return {
        label: isEs ? "Rebotes" : "Rebounds",
        color: "bg-blue-50 border-blue-200 text-blue-700",
      };
    }
    if (st === "AST") {
      return {
        label: isEs ? "Asistencias" : "Assists",
        color: "bg-emerald-50 border-emerald-200 text-emerald-700",
      };
    }
    return {
      label: "PTS+REB+AST",
      color: "bg-purple-50 border-purple-200 text-purple-700",
    };
  };

  const statBadge = getStatBadge(prop.stat_type);

  // Recommendation badge style
  const getRecBadge = (rec: string) => {
    const r = rec.toUpperCase();
    const strength = r.startsWith("STRONG")
      ? isEs
        ? "FUERTE"
        : "STRONG"
      : isEs
      ? "LEVE"
      : "LEAN";

    if (r.includes("OVER")) {
      return {
        bg: "bg-emerald-50 border border-emerald-200 text-emerald-800",
        text: `OVER (${strength})`,
        icon: ArrowUpRight,
      };
    }
    if (r.includes("UNDER")) {
      return {
        bg: "bg-rose-50 border border-rose-200 text-rose-800",
        text: `UNDER (${strength})`,
        icon: ArrowDownRight,
      };
    }
    return {
      bg: "bg-slate-100 border border-slate-200 text-slate-600",
      text: "PASS (NEUTRAL)",
      icon: ShieldCheck,
    };
  };

  const rec = getRecBadge(prop.recommendation);
  const RecIcon = rec.icon;

  return (
    <article
      aria-label={`${prop.player_name} ${prop.stat_type} ${prop.line}`}
      className={`relative rounded-3xl border bg-white p-5 shadow-xs transition-all duration-200 hover:shadow-md hover:border-slate-300 flex flex-col justify-between overflow-hidden space-y-4 ${
        hasPositiveEV ? "border-emerald-200/90" : "border-slate-200"
      } ${className}`}
    >
      {/* Value Pick Accent Bar */}
      {hasPositiveEV && (
        <div
          className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-emerald-400 via-teal-500 to-emerald-500"
          aria-hidden="true"
        />
      )}

      <div className="space-y-4">
        {/* Top: Player Avatar, Name, Team, Stat badge, Recommendation */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <PlayerAvatar
              playerName={prop.player_name}
              size={44}
              className="rounded-2xl ring-1 ring-slate-200 shrink-0"
            />
            <div className="min-w-0">
              <h3 className="text-sm font-black text-slate-900 leading-tight truncate">
                {prop.player_name}
              </h3>
              <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                <div className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-slate-100 text-[10px] font-bold text-slate-700">
                  <TeamLogo abbreviation={prop.team} size={12} />
                  <span>{prop.team}</span>
                </div>
                <span className="text-slate-300 text-xs" aria-hidden="true">
                  •
                </span>
                <div
                  className={`px-2 py-0.5 rounded-md border text-[10px] font-extrabold uppercase ${statBadge.color}`}
                >
                  {statBadge.label}
                </div>
              </div>
            </div>
          </div>

          {/* Recommendation Pill */}
          <div
            className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-xl text-xs font-black tracking-wide shrink-0 shadow-2xs ${rec.bg}`}
          >
            <RecIcon className="h-3 w-3" />
            <span>{rec.text}</span>
          </div>
        </div>

        {/* Sportsbook vs Model Matrix Box */}
        <div className="rounded-2xl bg-slate-50 border border-slate-100 p-3.5 space-y-3">
          <div className="flex items-center justify-between border-b border-slate-200/60 pb-2.5">
            <div>
              <span className="text-[10px] font-bold uppercase text-slate-400 tracking-wider block">
                {isEs ? "Línea Casa de Apuestas" : "Sportsbook Line"}
              </span>
              <div className="text-sm font-black text-slate-900 flex items-baseline gap-1.5 mt-0.5">
                <span className="tabular-nums">
                  {sideView.label} {prop.line}
                </span>
                <span className="text-xs font-mono font-bold text-orange-600 tabular-nums">
                  ({formatOdds(sideView.price)})
                </span>
              </div>
              {prop.bookmaker && (
                <div className="text-[10px] font-semibold text-slate-500 mt-0.5">
                  {isEs ? "Casa:" : "Book:"} {prop.bookmaker}
                </div>
              )}
            </div>

            <div className="text-right">
              <div className="flex items-center justify-end gap-1">
                <span className="text-[10px] font-bold uppercase text-slate-400 tracking-wider">
                  {sideView.devigged
                    ? isEs
                      ? "Prob. Justa (sin vig)"
                      : "Fair Prob (no vig)"
                    : isEs
                    ? "Prob. Implícita Casa"
                    : "Book Implied"}
                </span>
                <HelpPopover topic="DEVIGGED" />
              </div>
              <div className="text-sm font-mono font-black text-slate-700 tabular-nums mt-0.5">
                {sideView.bookPct.toFixed(1)}%
              </div>
              {!sideView.devigged && (
                <span
                  title={
                    isEs
                      ? "Solo hay precio del Over: la referencia incluye el margen (vig) de la casa."
                      : "Only the over was quoted: the reference includes the bookmaker margin (vig)."
                  }
                  className="inline-block mt-0.5 px-1.5 py-0.5 rounded-md bg-amber-50 border border-amber-200 text-[9px] font-bold text-amber-700"
                >
                  {isEs ? "con vig" : "vigged"}
                </span>
              )}
            </div>
          </div>

          {/* Model Projected Stats Grid */}
          <div className="grid grid-cols-3 gap-2 text-center pt-1">
            <div>
              <span className="text-[10px] font-bold text-slate-400 uppercase block">
                {isEs ? "Media Proy." : "Proj. Mean"}
              </span>
              <div className="text-xs font-mono font-black text-slate-900 tabular-nums">
                {prop.projected_mean.toFixed(1)}
              </div>
            </div>
            <div>
              <span className="text-[10px] font-bold text-slate-400 uppercase block">
                {isEs ? "Mediana" : "Median"}
              </span>
              <div className="text-xs font-mono font-black text-slate-900 tabular-nums">
                {prop.projected_median.toFixed(1)}
              </div>
            </div>
            <div>
              <span className="text-[10px] font-bold text-slate-400 uppercase block">
                {isEs
                  ? `Prob. (${sideView.label})`
                  : `Model (${sideView.label})`}
              </span>
              <div className="text-xs font-mono font-black text-emerald-700 tabular-nums">
                {sideView.modelPct.toFixed(1)}%
              </div>
            </div>
          </div>

          {/* Probability Comparison Bar */}
          <div className="space-y-1 pt-1">
            <div className="flex justify-between text-[10px] font-bold text-slate-400">
              <span>
                {prop.bookmaker || "Vegas"}:{" "}
                <span className="tabular-nums text-slate-600">
                  {sideView.bookPct.toFixed(1)}%
                </span>
              </span>
              <span className="text-emerald-700 font-extrabold">
                Modelo:{" "}
                <span className="tabular-nums">
                  {sideView.modelPct.toFixed(1)}%
                </span>
              </span>
            </div>
            <div className="relative w-full h-2 rounded-full bg-slate-200 overflow-hidden">
              <div
                className="absolute top-0 bottom-0 left-0 bg-slate-400"
                style={{
                  width: `${Math.min(100, Math.max(0, sideView.bookPct))}%`,
                }}
              />
              <div
                className={`absolute top-0 bottom-0 left-0 transition-all ${
                  sideView.modelPct >= sideView.bookPct
                    ? "bg-emerald-500"
                    : "bg-rose-500"
                }`}
                style={{
                  width: `${Math.min(100, Math.max(0, sideView.modelPct))}%`,
                  opacity: 0.85,
                }}
              />
            </div>
          </div>
        </div>

        {/* Edge & Expected Value Cards with Help Popovers */}
        <div className="grid grid-cols-2 gap-2.5">
          <div
            className={`p-2.5 rounded-2xl border flex flex-col justify-center transition-all ${
              prop.edge_pct > 0
                ? "bg-emerald-50 border-emerald-200 text-emerald-900"
                : "bg-slate-50 border-slate-200 text-slate-700"
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wide">
                {isEs ? "Ventaja (Edge)" : "Model Edge"}
              </span>
              <HelpPopover topic="EDGE" />
            </div>
            <span className="text-sm font-mono font-black mt-0.5 tabular-nums">
              {prop.edge_pct > 0
                ? `+${prop.edge_pct.toFixed(1)}%`
                : `${prop.edge_pct.toFixed(1)}%`}
            </span>
          </div>

          <div
            className={`p-2.5 rounded-2xl border flex flex-col justify-center transition-all ${
              prop.expected_value_pct > 0
                ? "bg-emerald-50 border-emerald-200 text-emerald-900"
                : "bg-slate-50 border-slate-200 text-slate-700"
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wide">
                Expected Value
              </span>
              <HelpPopover topic="EV" />
            </div>
            <span className="text-sm font-mono font-black mt-0.5 tabular-nums">
              {prop.expected_value_pct > 0
                ? `+${prop.expected_value_pct.toFixed(1)}% EV`
                : `${prop.expected_value_pct.toFixed(1)}% EV`}
            </span>
          </div>
        </div>

        {/* Quarter-Kelly Stake Row */}
        <div className="flex items-center justify-between px-3 py-2 rounded-2xl bg-slate-50 border border-slate-100 text-xs">
          <span className="font-semibold text-slate-600 flex items-center gap-1.5">
            <Percent className="h-3.5 w-3.5 text-orange-500" />
            <span>{isEs ? "Stake Kelly Sugerido:" : "Kelly Stake:"}</span>
            <HelpPopover topic="KELLY" />
          </span>
          <span className="font-mono font-black text-slate-900 tabular-nums">
            {prop.kelly_stake_pct > 0
              ? `${prop.kelly_stake_pct.toFixed(1)}% bankroll`
              : "0.0% (No bet)"}
          </span>
        </div>

        {/* Monte Carlo Range P10-P90 */}
        <div className="text-[11px] text-slate-500 flex items-center justify-between font-medium px-1">
          <span className="flex items-center gap-1">
            <span>Rango Monte Carlo (P10 - P90):</span>
            <HelpPopover topic="MONTE_CARLO" />
          </span>
          <span className="font-mono font-bold text-slate-700 tabular-nums">
            [{prop.projected_p10.toFixed(1)} — {prop.projected_p90.toFixed(1)}]
          </span>
        </div>

        {/* Gemini AI Contextual Reasoning */}
        <div className="pt-2 border-t border-slate-100">
          <div className="rounded-2xl bg-orange-50/50 border border-orange-100/80 p-3 space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-black text-orange-800 inline-flex items-center gap-1.5">
                <Sparkles className="h-3 w-3 text-orange-600" />
                <span>Gemini AI Context</span>
              </span>
              <span
                className={`text-[9px] font-bold px-1.5 py-0.5 rounded-md ${
                  prop.risk_level === "LOW"
                    ? "bg-emerald-100 text-emerald-800"
                    : prop.risk_level === "MEDIUM"
                    ? "bg-amber-100 text-amber-800"
                    : "bg-rose-100 text-rose-800"
                }`}
              >
                {isEs ? "Riesgo:" : "Risk:"} {prop.risk_level}
              </span>
            </div>
            <p className="text-[11px] text-slate-600 leading-relaxed font-normal">
              {prop.reasoning}
            </p>
          </div>
        </div>
      </div>
    </article>
  );
}
