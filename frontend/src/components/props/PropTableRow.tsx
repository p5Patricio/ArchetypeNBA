"use client";

import React, { useState } from "react";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { TeamLogo } from "@/components/TeamLogo";
import { usePreferences } from "@/context/PreferencesContext";
import type { PropItem } from "@/lib/api";
import {
  ArrowUpRight,
  ArrowDownRight,
  ShieldCheck,
  ChevronDown,
  ChevronUp,
  Sparkles,
} from "lucide-react";
import { formatOdds, getSideView } from "./PropCard";

interface PropTableRowProps {
  prop: PropItem;
}

export function PropTableRow({ prop }: PropTableRowProps) {
  const { language } = usePreferences();
  const [isExpanded, setIsExpanded] = useState(false);
  const isEs = language === "es";

  const sideView = getSideView(prop);
  const hasPositiveEV = prop.expected_value_pct > 0;

  // Stat badge
  const getStatBadge = (statType: string) => {
    const st = statType.toUpperCase();
    if (st === "PTS") return { label: isEs ? "PTS" : "PTS", color: "bg-orange-50 border-orange-200 text-orange-700" };
    if (st === "REB") return { label: isEs ? "REB" : "REB", color: "bg-blue-50 border-blue-200 text-blue-700" };
    if (st === "AST") return { label: isEs ? "AST" : "AST", color: "bg-emerald-50 border-emerald-200 text-emerald-700" };
    return { label: "PRA", color: "bg-purple-50 border-purple-200 text-purple-700" };
  };
  const statBadge = getStatBadge(prop.stat_type);

  // Recommendation badge style
  const getRecBadge = (rec: string) => {
    const r = rec.toUpperCase();
    const strength = r.startsWith("STRONG") ? (isEs ? "FUERTE" : "STRONG") : (isEs ? "LEVE" : "LEAN");
    if (r.includes("OVER")) {
      return {
        bg: "bg-emerald-50 border-emerald-200 text-emerald-800",
        text: `OVER (${strength})`,
        icon: ArrowUpRight,
      };
    }
    if (r.includes("UNDER")) {
      return {
        bg: "bg-rose-50 border-rose-200 text-rose-800",
        text: `UNDER (${strength})`,
        icon: ArrowDownRight,
      };
    }
    return {
      bg: "bg-slate-100 border-slate-200 text-slate-600",
      text: "PASS",
      icon: ShieldCheck,
    };
  };
  const rec = getRecBadge(prop.recommendation);
  const RecIcon = rec.icon;

  return (
    <>
      <tr
        className={`border-b border-slate-100 hover:bg-slate-50/80 transition-colors text-xs ${
          hasPositiveEV ? "bg-emerald-50/20" : ""
        }`}
      >
        {/* Player Name and Team */}
        <th scope="row" className="py-3 px-4 text-left font-normal">
          <div className="flex items-center gap-2.5">
            <PlayerAvatar
              playerName={prop.player_name}
              size={36}
              className="rounded-xl ring-1 ring-slate-200 shrink-0"
            />
            <div className="min-w-0">
              <span className="font-black text-slate-900 block truncate">
                {prop.player_name}
              </span>
              <div className="flex items-center gap-1.5 mt-0.5">
                <div className="inline-flex items-center gap-1 px-1 py-0.2 rounded bg-slate-100 text-[9px] font-bold text-slate-700">
                  <TeamLogo abbreviation={prop.team} size={10} />
                  <span>{prop.team}</span>
                </div>
                <span className={`px-1.5 py-0.2 rounded border text-[9px] font-bold ${statBadge.color}`}>
                  {statBadge.label}
                </span>
              </div>
            </div>
          </div>
        </th>

        {/* Line & Side */}
        <td className="py-3 px-3 font-semibold text-slate-900 tabular-nums">
          <div className="flex items-baseline gap-1">
            <span className="font-bold">{sideView.label}</span>
            <span className="font-black">{prop.line}</span>
          </div>
          <span className="text-[11px] font-mono text-orange-600 tabular-nums">
            {formatOdds(sideView.price)}
          </span>
          {prop.bookmaker && (
            <span className="block text-[9px] text-slate-400 truncate max-w-[80px]">
              {prop.bookmaker}
            </span>
          )}
        </td>

        {/* Projections & Probabilities */}
        <td className="py-3 px-3 text-center tabular-nums">
          <div className="font-mono font-bold text-slate-800 text-[11px]">
            {sideView.modelPct.toFixed(1)}%
          </div>
          <div className="text-[10px] font-mono text-slate-400">
            vs {sideView.bookPct.toFixed(1)}%
          </div>
        </td>

        {/* Model Edge */}
        <td className="py-3 px-3 text-center tabular-nums">
          <span
            className={`font-mono font-black text-xs ${
              prop.edge_pct > 0 ? "text-emerald-700" : "text-slate-600"
            }`}
          >
            {prop.edge_pct > 0 ? `+${prop.edge_pct.toFixed(1)}%` : `${prop.edge_pct.toFixed(1)}%`}
          </span>
        </td>

        {/* Expected Value */}
        <td className="py-3 px-3 text-center tabular-nums">
          <span
            className={`inline-block px-2 py-0.5 rounded-lg font-mono font-black text-xs ${
              prop.expected_value_pct > 0
                ? "bg-emerald-100/70 text-emerald-900 border border-emerald-200"
                : "bg-slate-100 text-slate-600 border border-slate-200"
            }`}
          >
            {prop.expected_value_pct > 0
              ? `+${prop.expected_value_pct.toFixed(1)}%`
              : `${prop.expected_value_pct.toFixed(1)}%`}
          </span>
        </td>

        {/* Kelly Stake */}
        <td className="py-3 px-3 text-center font-mono font-bold text-slate-700 tabular-nums text-xs">
          {prop.kelly_stake_pct > 0 ? `${prop.kelly_stake_pct.toFixed(1)}%` : "0.0%"}
        </td>

        {/* Recommendation */}
        <td className="py-3 px-3 text-center">
          <div
            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-[11px] font-black tracking-wide border shadow-2xs ${rec.bg}`}
          >
            <RecIcon className="h-3 w-3 shrink-0" />
            <span>{rec.text}</span>
          </div>
        </td>

        {/* Details toggle button */}
        <td className="py-3 px-3 text-right">
          <button
            type="button"
            onClick={() => setIsExpanded((prev) => !prev)}
            aria-expanded={isExpanded}
            aria-label={`${isEs ? "Ver detalles de" : "View details for"} ${prop.player_name}`}
            className="rounded-lg p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-500 cursor-pointer"
          >
            {isExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </button>
        </td>
      </tr>

      {/* Expandable row with reasoning and Monte Carlo distribution */}
      {isExpanded && (
        <tr className="bg-slate-50/70 border-b border-slate-200/80">
          <td colSpan={8} className="py-3 px-6 text-xs">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-1">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">
                  {isEs ? "Distribución Monte Carlo (10,000 corridas)" : "Monte Carlo Distribution (10k runs)"}
                </span>
                <div className="flex items-center gap-4 text-xs font-mono">
                  <span>
                    {isEs ? "Media:" : "Mean:"}{" "}
                    <strong className="text-slate-900">{prop.projected_mean.toFixed(1)}</strong>
                  </span>
                  <span>
                    {isEs ? "Mediana:" : "Median:"}{" "}
                    <strong className="text-slate-900">{prop.projected_median.toFixed(1)}</strong>
                  </span>
                  <span>
                    P10-P90:{" "}
                    <strong className="text-slate-900">
                      [{prop.projected_p10.toFixed(1)} — {prop.projected_p90.toFixed(1)}]
                    </strong>
                  </span>
                </div>
              </div>

              <div className="space-y-1">
                <span className="text-[10px] font-black text-orange-800 inline-flex items-center gap-1">
                  <Sparkles className="h-3 w-3 text-orange-600" />
                  <span>Gemini AI Context ({isEs ? "Riesgo:" : "Risk:"} {prop.risk_level})</span>
                </span>
                <p className="text-[11px] text-slate-600 leading-relaxed font-normal">
                  {prop.reasoning}
                </p>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
