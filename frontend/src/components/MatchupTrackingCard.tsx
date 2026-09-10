"use client";

import React, { useState } from "react";
import Image from "next/image";
import {
  ShieldAlert,
  Target,
  Zap,
  TrendingDown,
  TrendingUp,
  Minus,
  ChevronDown,
  ChevronUp,
  Layers,
  Sparkles,
  Activity,
  Flame,
} from "lucide-react";
import {
  PlayerMatchupAnalysisResponse,
} from "@/lib/api";

interface MatchupTrackingCardProps {
  data: PlayerMatchupAnalysisResponse;
  onMinPossessionsChange?: (minPoss: number) => void;
  currentMinPossessions?: number;
}

export function MatchupTrackingCard({
  data,
  onMinPossessionsChange,
  currentMinPossessions = 10,
}: MatchupTrackingCardProps) {
  const [activeTab, setActiveTab] = useState<"all" | "kryptonite" | "mismatch" | "playmaker">("all");
  const [expandedDefenderId, setExpandedDefenderId] = useState<number | null>(null);

  const { baseline, matchups, top_stoppers, top_targets } = data;

  // Filter defenders according to active category tab
  const displayedMatchups = matchups.filter((item) => {
    if (activeTab === "kryptonite") return item.classification === "kryptonite";
    if (activeTab === "mismatch") return item.classification === "mismatch_exploited";
    if (activeTab === "playmaker") return item.classification === "playmaker_trigger";
    return true;
  });

  const toggleExpand = (defId: number) => {
    setExpandedDefenderId(expandedDefenderId === defId ? null : defId);
  };

  // Directional delta badge
  const renderDeltaBadge = (
    delta: number,
    isGoodWhenHigher: boolean = false,
    suffix: string = ""
  ) => {
    if (Math.abs(delta) < 0.1) {
      return (
        <span className="inline-flex items-center gap-0.5 text-[11px] font-mono text-slate-400 font-semibold">
          <Minus className="w-3 h-3" /> 0.0{suffix}
        </span>
      );
    }

    const isPositive = delta > 0;
    // For defensive evaluation:
    // Lower opponent PTS, AST, TS% is good for defense (green reduction).
    // Higher opponent TOV caused is good for defense (green increase).
    const isGood = isGoodWhenHigher ? isPositive : !isPositive;

    const colorClass = isGood
      ? "text-emerald-700 bg-emerald-50 border-emerald-200"
      : "text-rose-700 bg-rose-50 border-rose-200";

    const Icon = isPositive ? TrendingUp : TrendingDown;
    const formatted = Math.abs(delta).toFixed(1);

    return (
      <span
        className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-md text-[11px] font-mono font-bold border ${colorClass}`}
      >
        <Icon className="w-3 h-3 stroke-[2.5]" />
        {formatted}
        {suffix}
      </span>
    );
  };

  return (
    <div className="w-full max-w-5xl mx-auto space-y-6">
      {/* Player Profile & Baseline Header Card (ArchetypeNBA Clean Light Style) */}
      <div className="bg-white border border-slate-200 rounded-3xl p-6 sm:p-8 shadow-xs">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-6">
          {/* Player Identity */}
          <div className="flex items-center gap-5">
            <div className="relative w-20 h-20 sm:w-24 sm:h-24 rounded-2xl bg-slate-100 border border-slate-200 p-1 shadow-2xs overflow-hidden shrink-0">
              <Image
                src={
                  data.player_headshot_url ||
                  `https://cdn.nba.com/headshots/nba/latest/260x190/${data.player_id}.png`
                }
                alt={data.player_name}
                width={96}
                height={96}
                className="w-full h-full object-cover rounded-xl"
                unoptimized
              />
            </div>

            <div>
              <div className="inline-flex items-center gap-1.5 rounded-full border border-orange-200 bg-orange-50 px-3 py-0.5 text-xs font-bold text-orange-700 shadow-2xs mb-1.5">
                <Flame className="w-3.5 h-3.5 text-orange-600" />
                ¿Quién lo para? • Scouting 1v1
              </div>
              <h1 className="text-2xl sm:text-4xl font-black tracking-tight text-slate-900 uppercase">
                {data.player_name}
              </h1>
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mt-1">
                Normalizado cada 75 posesiones • {baseline.seasons.join(" / ")}
              </p>
            </div>
          </div>

          {/* Clean Baseline Stats Grid */}
          <div className="grid grid-cols-4 gap-2.5 sm:gap-3 bg-slate-50/90 border border-slate-200/80 p-3 sm:p-4 rounded-2xl">
            <div className="px-2 text-center">
              <div className="text-[10px] sm:text-[11px] font-bold text-slate-400 uppercase">PTS / 75</div>
              <div className="font-mono text-xl sm:text-2xl font-black text-slate-900">{baseline.pts_per_75}</div>
            </div>
            <div className="px-2 border-l border-slate-200 text-center">
              <div className="text-[10px] sm:text-[11px] font-bold text-slate-400 uppercase">AST / 75</div>
              <div className="font-mono text-xl sm:text-2xl font-black text-slate-900">{baseline.ast_per_75}</div>
            </div>
            <div className="px-2 border-l border-slate-200 text-center">
              <div className="text-[10px] sm:text-[11px] font-bold text-orange-500 uppercase">TS%</div>
              <div className="font-mono text-xl sm:text-2xl font-black text-orange-600">{baseline.ts_pct}%</div>
            </div>
            <div className="px-2 border-l border-slate-200 text-center">
              <div className="text-[10px] sm:text-[11px] font-bold text-slate-400 uppercase">TOV / 75</div>
              <div className="font-mono text-xl sm:text-2xl font-black text-slate-900">{baseline.tov_per_75}</div>
            </div>
          </div>
        </div>
      </div>

      {/* Main Table Card */}
      <div className="bg-white border border-slate-200 rounded-3xl shadow-xs overflow-hidden">
        {/* Controls Toolbar */}
        <div className="px-6 py-4 border-b border-slate-200 bg-slate-50/50 flex flex-wrap items-center justify-between gap-4">
          {/* Segmented Category Tabs */}
          <div className="flex flex-wrap items-center gap-1.5 p-1 bg-slate-200/70 rounded-xl">
            <button
              onClick={() => setActiveTab("all")}
              className={`px-3.5 py-1.5 rounded-lg text-xs font-bold transition-all ${
                activeTab === "all"
                  ? "bg-white text-slate-900 shadow-xs border border-slate-200/60"
                  : "text-slate-600 hover:text-slate-900"
              }`}
            >
              Todos ({matchups.length})
            </button>

            <button
              onClick={() => setActiveTab("kryptonite")}
              className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-bold transition-all ${
                activeTab === "kryptonite"
                  ? "bg-purple-600 text-white shadow-xs"
                  : "text-purple-700 hover:bg-purple-50"
              }`}
            >
              <ShieldAlert className="w-3.5 h-3.5" />
              Kryptonita ({top_stoppers.length})
            </button>

            <button
              onClick={() => setActiveTab("mismatch")}
              className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-bold transition-all ${
                activeTab === "mismatch"
                  ? "bg-orange-600 text-white shadow-xs"
                  : "text-orange-700 hover:bg-orange-50"
              }`}
            >
              <Target className="w-3.5 h-3.5" />
              Mismatches ({top_targets.length})
            </button>

            <button
              onClick={() => setActiveTab("playmaker")}
              className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-bold transition-all ${
                activeTab === "playmaker"
                  ? "bg-sky-600 text-white shadow-xs"
                  : "text-sky-700 hover:bg-sky-50"
              }`}
            >
              <Zap className="w-3.5 h-3.5" />
              Generadores
            </button>
          </div>

          {/* Possessions Threshold Selector */}
          {onMinPossessionsChange && (
            <div className="flex items-center gap-2 text-xs font-semibold text-slate-600">
              <span className="text-slate-500">Mín. Posesiones:</span>
              <div className="flex items-center gap-1">
                {[10, 25, 40, 60].map((poss) => (
                  <button
                    key={poss}
                    onClick={() => onMinPossessionsChange(poss)}
                    className={`px-2.5 py-1 rounded-lg text-xs font-bold border transition-colors ${
                      currentMinPossessions === poss
                        ? "bg-slate-900 text-white border-transparent shadow-xs"
                        : "bg-white text-slate-700 border-slate-200 hover:bg-slate-100"
                    }`}
                  >
                    {poss}+
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200 text-[11px] font-extrabold uppercase tracking-wider text-slate-400">
                <th className="py-3.5 px-6">Defensor</th>
                <th className="py-3.5 px-4 text-center">PTS / 75</th>
                <th className="py-3.5 px-4 text-center">AST / 75</th>
                <th className="py-3.5 px-4 text-center">TS%</th>
                <th className="py-3.5 px-4 text-center">PER (TOV)</th>
                <th className="py-3.5 px-4 text-center">Impacto</th>
                <th className="py-3.5 px-4 text-right">Detalle</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {displayedMatchups.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-slate-400 font-medium">
                    <Activity className="w-8 h-8 mx-auto mb-2 opacity-30 animate-pulse" />
                    No se encontraron defensores con los filtros seleccionados.
                  </td>
                </tr>
              ) : (
                displayedMatchups.map((item) => {
                  const isExpanded = expandedDefenderId === item.defender_id;

                  let badgeStyle = "bg-slate-100 text-slate-700 border-slate-200";
                  if (item.classification === "kryptonite") {
                    badgeStyle = "bg-purple-50 text-purple-700 border-purple-200";
                  } else if (item.classification === "mismatch_exploited") {
                    badgeStyle = "bg-orange-50 text-orange-700 border-orange-200";
                  } else if (item.classification === "playmaker_trigger") {
                    badgeStyle = "bg-sky-50 text-sky-700 border-sky-200";
                  }

                  return (
                    <React.Fragment key={item.defender_id}>
                      <tr
                        onClick={() => toggleExpand(item.defender_id)}
                        className={`cursor-pointer transition-colors hover:bg-slate-50/80 ${
                          isExpanded ? "bg-slate-50/60" : ""
                        }`}
                      >
                        {/* Defender Avatar & Info */}
                        <td className="py-4 px-6">
                          <div className="flex items-center gap-3.5">
                            <div className="relative w-10 h-10 rounded-full bg-slate-100 p-0.5 border border-slate-200 overflow-hidden shrink-0 shadow-2xs">
                              <Image
                                src={
                                  item.defender_headshot_url ||
                                  `https://cdn.nba.com/headshots/nba/latest/260x190/${item.defender_id}.png`
                                }
                                alt={item.defender_name}
                                width={40}
                                height={40}
                                className="w-full h-full object-cover rounded-full"
                                unoptimized
                              />
                            </div>
                            <div>
                              <div className="font-extrabold text-sm text-slate-900 uppercase tracking-tight">
                                {item.defender_name}
                              </div>
                              <div className="text-[11px] font-medium text-slate-400">
                                {item.partial_poss} posesiones directas • {item.matchup_min} min
                              </div>
                            </div>
                          </div>
                        </td>

                        {/* PTS / 75 */}
                        <td className="py-4 px-4 text-center">
                          <div className="font-mono text-base font-black text-slate-900">
                            {item.pts_per_75}
                          </div>
                          <div className="mt-0.5">
                            {renderDeltaBadge(item.delta_pts, false)}
                          </div>
                        </td>

                        {/* AST / 75 */}
                        <td className="py-4 px-4 text-center">
                          <div className="font-mono text-base font-black text-slate-900">
                            {item.ast_per_75}
                          </div>
                          <div className="mt-0.5">
                            {renderDeltaBadge(item.delta_ast, false)}
                          </div>
                        </td>

                        {/* TS% */}
                        <td className="py-4 px-4 text-center">
                          <div className="font-mono text-base font-black text-orange-600">
                            {item.ts_pct}%
                          </div>
                          <div className="mt-0.5">
                            {renderDeltaBadge(item.delta_ts_pct, false, "%")}
                          </div>
                        </td>

                        {/* TOV / 75 */}
                        <td className="py-4 px-4 text-center">
                          <div className="font-mono text-base font-black text-slate-900">
                            {item.tov_per_75}
                          </div>
                          <div className="mt-0.5">
                            {renderDeltaBadge(item.delta_tov, true)}
                          </div>
                        </td>

                        {/* Impact Classification Badge */}
                        <td className="py-4 px-4 text-center">
                          <span
                            className={`inline-block px-2.5 py-1 rounded-full text-xs font-bold border ${badgeStyle}`}
                          >
                            {item.classification_label.split("/")[0].trim()}
                          </span>
                        </td>

                        {/* Expand Button */}
                        <td className="py-4 px-4 text-right">
                          <button
                            type="button"
                            className="p-1 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition"
                          >
                            {isExpanded ? (
                              <ChevronUp className="w-5 h-5" />
                            ) : (
                              <ChevronDown className="w-5 h-5" />
                            )}
                          </button>
                        </td>
                      </tr>

                      {/* Expanded Tactical Drawer */}
                      {isExpanded && (
                        <tr className="bg-slate-50/60">
                          <td colSpan={7} className="p-6 border-y border-slate-200">
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                              {/* Shooting Splits */}
                              <div className="p-4 bg-white rounded-2xl border border-slate-200 shadow-2xs">
                                <h4 className="text-xs font-black uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-1.5">
                                  <Layers className="w-3.5 h-3.5 text-orange-500" />
                                  Desglose de Tiro
                                </h4>
                                <div className="space-y-2 text-xs">
                                  <div className="flex justify-between font-semibold">
                                    <span className="text-slate-500">Tiros de Campo (FG):</span>
                                    <span className="font-mono font-bold text-slate-900">
                                      {item.matchup_fgm}/{item.matchup_fga} ({item.matchup_fg_pct}%)
                                    </span>
                                  </div>
                                  <div className="flex justify-between font-semibold">
                                    <span className="text-slate-500">Triples (3PT):</span>
                                    <span className="font-mono font-bold text-slate-900">
                                      {item.matchup_fg3m}/{item.matchup_fg3a} ({item.matchup_fg3_pct}%)
                                    </span>
                                  </div>
                                  <div className="flex justify-between font-semibold">
                                    <span className="text-slate-500">Tiros Libres (FT):</span>
                                    <span className="font-mono font-bold text-slate-900">
                                      {item.matchup_ftm}/{item.matchup_fta}
                                    </span>
                                  </div>
                                  <div className="flex justify-between font-semibold">
                                    <span className="text-slate-500">Puntos Totales:</span>
                                    <span className="font-mono font-bold text-slate-900">
                                      {item.player_pts} pts
                                    </span>
                                  </div>
                                </div>
                              </div>

                              {/* Playmaking & Fouls */}
                              <div className="p-4 bg-white rounded-2xl border border-slate-200 shadow-2xs">
                                <h4 className="text-xs font-black uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-1.5">
                                  <Activity className="w-3.5 h-3.5 text-sky-500" />
                                  Creación y Faltas
                                </h4>
                                <div className="space-y-2 text-xs">
                                  <div className="flex justify-between font-semibold">
                                    <span className="text-slate-500">Asistencias directas:</span>
                                    <span className="font-mono font-bold text-slate-900">
                                      {item.matchup_ast} ast
                                    </span>
                                  </div>
                                  <div className="flex justify-between font-semibold">
                                    <span className="text-slate-500">Pérdidas provocadas:</span>
                                    <span className="font-mono font-bold text-slate-900">
                                      {item.matchup_tov} pérdidas
                                    </span>
                                  </div>
                                  <div className="flex justify-between font-semibold">
                                    <span className="text-slate-500">Faltas de tiro recibidas:</span>
                                    <span className="font-mono font-bold text-slate-900">
                                      {item.matchup_ftm > 0 ? `${Math.round(item.matchup_fta / 2)} aprox` : "0"}
                                    </span>
                                  </div>
                                  <div className="flex justify-between font-semibold">
                                    <span className="text-slate-500">Temporadas:</span>
                                    <span className="font-semibold text-slate-700">
                                      {item.seasons.join(", ")}
                                    </span>
                                  </div>
                                </div>
                              </div>

                              {/* Tactical Verdict */}
                              <div className="p-4 bg-slate-900 text-white rounded-2xl shadow-xs">
                                <h4 className="text-xs font-black uppercase tracking-wider text-orange-400 mb-2 flex items-center gap-1.5">
                                  <Sparkles className="w-3.5 h-3.5 text-orange-400" />
                                  Veredicto Táctico
                                </h4>
                                <p className="text-xs text-slate-300 leading-relaxed">
                                  {item.classification === "kryptonite" && (
                                    <>
                                      <strong className="text-purple-300 font-bold">{item.defender_name}</strong> actúa como
                                      un bloqueador de impacto frente a {data.player_name}. Reduce su TS% en{" "}
                                      <span className="text-emerald-400 font-bold font-mono">{Math.abs(item.delta_ts_pct)}%</span>{" "}
                                      y sofoca su volumen anotador.
                                    </>
                                  )}
                                  {item.classification === "mismatch_exploited" && (
                                    <>
                                      <strong className="text-orange-300 font-bold">{item.defender_name}</strong> es un
                                      mismatch evidente en switch. {data.player_name} explota esta ventaja anotando a
                                      ritmo de{" "}
                                      <span className="text-orange-400 font-bold font-mono">{item.pts_per_75} PTS/75</span> (+
                                      {item.delta_pts} sobre su media).
                                    </>
                                  )}
                                  {item.classification === "playmaker_trigger" && (
                                    <>
                                      Ante <strong className="text-sky-300 font-bold">{item.defender_name}</strong>,{" "}
                                      {data.player_name} activa su visión de juego, elevando sus asistencias a{" "}
                                      <span className="text-sky-400 font-bold font-mono">{item.ast_per_75} AST/75</span>.
                                    </>
                                  )}
                                  {item.classification === "neutral" && (
                                    <>
                                      Matchup equilibrado dentro de los rangos estadísticos esperados frente a{" "}
                                      {item.defender_name}.
                                    </>
                                  )}
                                </p>
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
