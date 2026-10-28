"use client";

import React from "react";
import { type PaperBetItem } from "@/lib/api";
import { TeamLogo } from "@/components/TeamLogo";
import { usePreferences } from "@/context/PreferencesContext";
import {
  ChevronLeft,
  ChevronRight,
  Filter,
  RefreshCw,
  AlertCircle,
  Inbox,
  Calendar,
  Building2,
} from "lucide-react";

interface BetsTableProps {
  bets: PaperBetItem[];
  total: number;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  strategyFilter: string;
  onStrategyFilterChange: (strategy: string) => void;
  statusFilter: string;
  onStatusFilterChange: (status: string) => void;
  page: number;
  onPageChange: (newPage: number) => void;
  pageSize?: number;
}

export function BetsTable({
  bets,
  total,
  loading,
  error,
  onRetry,
  strategyFilter,
  onStrategyFilterChange,
  statusFilter,
  onStatusFilterChange,
  page,
  onPageChange,
  pageSize = 50,
}: BetsTableProps) {
  const { language } = usePreferences();
  const isEs = language === "es";

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const getStatusBadge = (status: string) => {
    const s = status.toLowerCase();
    switch (s) {
      case "won":
        return {
          label: isEs ? "Ganada" : "Won",
          styles: "bg-emerald-50 text-emerald-800 border-emerald-200",
        };
      case "lost":
        return {
          label: isEs ? "Perdida" : "Lost",
          styles: "bg-rose-50 text-rose-800 border-rose-200",
        };
      case "pending":
        return {
          label: isEs ? "Pendiente" : "Pending",
          styles: "bg-amber-50 text-amber-800 border-amber-200",
        };
      case "push":
        return {
          label: isEs ? "Empate (Push)" : "Push",
          styles: "bg-slate-100 text-slate-700 border-slate-200",
        };
      case "void":
        return {
          label: isEs ? "Anulada" : "Void",
          styles: "bg-slate-100 text-slate-600 border-slate-200",
        };
      default:
        return {
          label: status,
          styles: "bg-slate-100 text-slate-700 border-slate-200",
        };
    }
  };

  const formatSelection = (bet: PaperBetItem) => {
    const m = bet.market.toLowerCase();
    const s = bet.side.toLowerCase();
    const line = bet.line;

    let targetTeam = "";
    if (s === "home") targetTeam = bet.game.home_team;
    else if (s === "away") targetTeam = bet.game.away_team;
    else targetTeam = s.toUpperCase();

    if (m === "spreads") {
      const lineStr = line != null ? (line > 0 ? `+${line}` : `${line}`) : "";
      return `${targetTeam} ${lineStr}`;
    }
    if (m === "totals") {
      const lineStr = line != null ? `${line}` : "";
      return `${s.toUpperCase()} ${lineStr}`;
    }
    return `${targetTeam} (ML)`;
  };

  const formatMarketName = (market: string) => {
    switch (market.toLowerCase()) {
      case "spreads":
        return isEs ? "Hándicap" : "Spread";
      case "h2h":
        return "Moneyline";
      case "totals":
        return isEs ? "Totales" : "Totals";
      default:
        return market;
    }
  };

  return (
    <div className="rounded-3xl border border-slate-200 bg-white p-6 sm:p-8 shadow-xs">
      {/* Title & Filter Controls Header */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 border-b border-slate-100 pb-6 mb-6">
        <div>
          <div className="inline-flex items-center gap-1.5 rounded-full border border-orange-200 bg-orange-50 px-3 py-0.5 text-[11px] font-black text-orange-800 mb-2">
            <Building2 className="h-3 w-3 text-orange-600" />
            <span>{isEs ? "REGISTRO DE APUESTAS" : "BETS LEDGER"}</span>
          </div>
          <h2 className="text-xl sm:text-2xl font-black text-slate-900 tracking-tight">
            {isEs ? "Historial de Apuestas Simuladas" : "Simulated Paper Bets History"}
          </h2>
          <p className="text-xs sm:text-sm text-slate-500 mt-0.5">
            {isEs
              ? `Mostrando ${total} apuestas registradas (ordenadas por fecha descendente).`
              : `Displaying ${total} recorded bets (ordered newest first).`}
          </p>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Strategy Select */}
          <div className="flex items-center gap-1.5 bg-slate-50 border border-slate-200 rounded-2xl px-3 py-1.5 text-xs">
            <Filter className="h-3.5 w-3.5 text-slate-400" />
            <label htmlFor="strategy-filter" className="text-slate-500 font-medium">
              {isEs ? "Estrategia:" : "Strategy:"}
            </label>
            <select
              id="strategy-filter"
              value={strategyFilter}
              onChange={(e) => {
                onStrategyFilterChange(e.target.value);
                onPageChange(1);
              }}
              className="bg-transparent font-bold text-slate-800 outline-none cursor-pointer pr-1"
            >
              <option value="all">{isEs ? "Todas" : "All"}</option>
              <option value="flat">Flat (1 u)</option>
              <option value="kelly_fractional">Quarter-Kelly</option>
              <option value="kelly_shrunk">Kelly Shrunk</option>
              <option value="market_edge">Market Benchmark</option>
            </select>
          </div>

          {/* Status Select */}
          <div className="flex items-center gap-1.5 bg-slate-50 border border-slate-200 rounded-2xl px-3 py-1.5 text-xs">
            <label htmlFor="status-filter" className="text-slate-500 font-medium">
              {isEs ? "Estado:" : "Status:"}
            </label>
            <select
              id="status-filter"
              value={statusFilter}
              onChange={(e) => {
                onStatusFilterChange(e.target.value);
                onPageChange(1);
              }}
              className="bg-transparent font-bold text-slate-800 outline-none cursor-pointer pr-1"
            >
              <option value="all">{isEs ? "Todos" : "All"}</option>
              <option value="pending">{isEs ? "Pendientes" : "Pending"}</option>
              <option value="won">{isEs ? "Ganadas" : "Won"}</option>
              <option value="lost">{isEs ? "Perdidas" : "Lost"}</option>
              <option value="push">{isEs ? "Empates" : "Push"}</option>
            </select>
          </div>
        </div>
      </div>

      {/* Error State */}
      {error && (
        <div className="rounded-2xl border border-rose-200 bg-rose-50 p-6 text-center my-6">
          <AlertCircle className="mx-auto h-8 w-8 text-rose-500 mb-2" />
          <p className="text-sm font-bold text-rose-900 mb-1">{error}</p>
          <p className="text-xs text-rose-700 mb-4">
            {isEs
              ? "Ocurrió un problema al obtener el listado de apuestas desde el servidor."
              : "An error occurred while fetching the bets from the backend."}
          </p>
          <button
            onClick={onRetry}
            className="inline-flex items-center gap-2 rounded-xl bg-rose-600 px-4 py-2 text-xs font-bold text-white shadow-xs hover:bg-rose-700 transition"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            <span>{isEs ? "Reintentar" : "Retry"}</span>
          </button>
        </div>
      )}

      {/* Loading Skeleton */}
      {loading && (
        <div className="space-y-3 py-4 animate-pulse" aria-busy="true">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="h-14 w-full bg-slate-100 rounded-2xl" />
          ))}
        </div>
      )}

      {/* Empty State */}
      {!loading && !error && bets.length === 0 && (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50/50 p-12 text-center my-6">
          <Inbox className="mx-auto h-10 w-10 text-slate-400 mb-3" />
          <h3 className="text-sm font-bold text-slate-700">
            {isEs ? "No se encontraron apuestas" : "No bets found"}
          </h3>
          <p className="text-xs text-slate-500 mt-1 max-w-sm mx-auto">
            {isEs
              ? "No existen registros que coincidan con los filtros seleccionados o el sistema aún no ha colocado apuestas."
              : "No records match your selected filters or the system hasn't recorded paper bets yet."}
          </p>
        </div>
      )}

      {/* Content: Desktop Table & Mobile Stacked Cards */}
      {!loading && !error && bets.length > 0 && (
        <>
          {/* Mobile Card View (< 768px) */}
          <div className="block md:hidden space-y-3">
            {bets.map((bet) => {
              const statusBadge = getStatusBadge(bet.status);
              const isProfit = bet.profit_units != null && bet.profit_units > 0;
              const isLoss = bet.profit_units != null && bet.profit_units < 0;
              const clvPositive = bet.clv_pct != null && bet.clv_pct > 0;
              const clvNegative = bet.clv_pct != null && bet.clv_pct < 0;

              return (
                <div
                  key={bet.id}
                  className="rounded-2xl border border-slate-200 bg-white p-4 shadow-2xs space-y-3"
                >
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-mono text-[11px] text-slate-500 flex items-center gap-1">
                      <Calendar className="h-3.5 w-3.5 text-slate-400" />
                      {new Date(bet.game.commence_time).toLocaleDateString(
                        isEs ? "es-MX" : "en-US",
                        { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }
                      )}
                    </span>
                    <span
                      className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-black border ${statusBadge.styles}`}
                    >
                      {statusBadge.label}
                    </span>
                  </div>

                  {/* Teams & Logos */}
                  <div className="flex items-center justify-between border-y border-slate-100 py-2.5">
                    <div className="flex items-center gap-2">
                      <TeamLogo abbreviation={bet.game.away_team} size={28} />
                      <span className="text-xs font-black text-slate-800">{bet.game.away_team}</span>
                      <span className="text-[10px] text-slate-400 font-bold">@</span>
                      <TeamLogo abbreviation={bet.game.home_team} size={28} />
                      <span className="text-xs font-black text-slate-800">{bet.game.home_team}</span>
                    </div>

                    <div className="text-right">
                      <div className="text-xs font-black text-slate-900">{formatSelection(bet)}</div>
                      <div className="text-[10px] font-semibold text-slate-500">
                        {formatMarketName(bet.market)}
                      </div>
                    </div>
                  </div>

                  {/* Details grid */}
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div className="p-2 rounded-xl bg-slate-50">
                      <div className="text-[10px] text-slate-400 uppercase font-semibold">
                        {isEs ? "Casa / Cuota" : "Book / Odds"}
                      </div>
                      <div className="font-bold text-slate-800 mt-0.5">
                        {bet.book || "—"}{" "}
                        <span className="font-mono text-slate-600 font-normal">
                          @{bet.price_taken.toFixed(2)}
                        </span>
                      </div>
                    </div>

                    <div className="p-2 rounded-xl bg-slate-50">
                      <div className="text-[10px] text-slate-400 uppercase font-semibold">
                        {isEs ? "Estrategia / Stake" : "Strategy / Stake"}
                      </div>
                      <div className="font-bold text-slate-800 mt-0.5 font-mono">
                        {bet.stake_units.toFixed(2)} u{" "}
                        <span className="text-[10px] text-slate-500 font-sans font-normal">
                          ({bet.strategy.replace(/_/g, " ")})
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* P/L & CLV Bottom Row */}
                  <div className="flex items-center justify-between pt-1 text-xs">
                    <div>
                      <span className="text-slate-400 text-[10px] uppercase font-semibold mr-1">
                        CLV:
                      </span>
                      <span
                        className={`font-mono font-bold ${
                          clvPositive
                            ? "text-emerald-600"
                            : clvNegative
                            ? "text-rose-600"
                            : "text-slate-500"
                        }`}
                      >
                        {bet.clv_pct != null
                          ? `${bet.clv_pct > 0 ? "+" : ""}${(bet.clv_pct * 100).toFixed(1)}%`
                          : "—"}
                      </span>
                    </div>

                    <div>
                      <span className="text-slate-400 text-[10px] uppercase font-semibold mr-1">
                        P/L:
                      </span>
                      <span
                        className={`font-mono font-black ${
                          isProfit
                            ? "text-emerald-600"
                            : isLoss
                            ? "text-rose-600"
                            : "text-slate-500"
                        }`}
                      >
                        {bet.profit_units != null
                          ? `${bet.profit_units > 0 ? "+" : ""}${bet.profit_units.toFixed(2)} u`
                          : "—"}
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Desktop Table View (>= 768px) */}
          <div className="hidden md:block overflow-x-auto">
            <table
              className="w-full text-left text-xs text-slate-700"
              aria-label={
                isEs
                  ? "Tabla de detalle de apuestas simuladas"
                  : "Simulated paper bets detail table"
              }
            >
              <caption className="sr-only">
                {isEs ? "Listado completo de apuestas simuladas" : "Full list of simulated paper bets"}
              </caption>
              <thead className="border-b border-slate-200 bg-slate-50 text-[11px] font-black uppercase tracking-wider text-slate-600">
                <tr>
                  <th scope="col" className="px-3.5 py-3 rounded-l-xl">
                    {isEs ? "Fecha & Hora" : "Date & Time"}
                  </th>
                  <th scope="col" className="px-3 py-3">
                    {isEs ? "Partido" : "Game"}
                  </th>
                  <th scope="col" className="px-3 py-3">
                    {isEs ? "Mercado / Selección" : "Market / Selection"}
                  </th>
                  <th scope="col" className="px-3 py-3">
                    {isEs ? "Casa" : "Book"}
                  </th>
                  <th scope="col" className="px-3 py-3 text-right">
                    {isEs ? "Cuota" : "Price"}
                  </th>
                  <th scope="col" className="px-3 py-3 text-right">
                    Stake
                  </th>
                  <th scope="col" className="px-3 py-3 text-center">
                    {isEs ? "Estado" : "Status"}
                  </th>
                  <th scope="col" className="px-3 py-3 text-right">
                    P/L
                  </th>
                  <th scope="col" className="px-3.5 py-3 text-right rounded-r-xl">
                    CLV
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {bets.map((bet) => {
                  const statusBadge = getStatusBadge(bet.status);
                  const isProfit = bet.profit_units != null && bet.profit_units > 0;
                  const isLoss = bet.profit_units != null && bet.profit_units < 0;
                  const clvPositive = bet.clv_pct != null && bet.clv_pct > 0;
                  const clvNegative = bet.clv_pct != null && bet.clv_pct < 0;

                  return (
                    <tr
                      key={bet.id}
                      className="hover:bg-slate-50/70 transition-colors duration-150"
                    >
                      {/* Date */}
                      <td className="px-3.5 py-3 text-slate-600 font-mono text-[11px] whitespace-nowrap">
                        {new Date(bet.game.commence_time).toLocaleDateString(
                          isEs ? "es-MX" : "en-US",
                          { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }
                        )}
                      </td>

                      {/* Game with TeamLogos */}
                      <td className="px-3 py-3 whitespace-nowrap">
                        <div className="flex items-center gap-1.5 font-bold text-slate-900">
                          <TeamLogo abbreviation={bet.game.away_team} size={20} />
                          <span>{bet.game.away_team}</span>
                          <span className="text-slate-400 font-normal text-[10px]">@</span>
                          <TeamLogo abbreviation={bet.game.home_team} size={20} />
                          <span>{bet.game.home_team}</span>
                        </div>
                      </td>

                      {/* Market / Selection */}
                      <td className="px-3 py-3">
                        <div className="font-black text-slate-900">{formatSelection(bet)}</div>
                        <div className="text-[10px] text-slate-400 font-medium">
                          {formatMarketName(bet.market)} • {bet.strategy.replace(/_/g, " ")}
                        </div>
                      </td>

                      {/* Sportsbook */}
                      <td className="px-3 py-3 font-medium text-slate-700 whitespace-nowrap">
                        {bet.book || "—"}
                      </td>

                      {/* Price decimal */}
                      <td className="px-3 py-3 text-right font-mono tabular-nums font-bold text-slate-800 whitespace-nowrap">
                        {bet.price_taken.toFixed(2)}
                      </td>

                      {/* Stake */}
                      <td className="px-3 py-3 text-right font-mono tabular-nums text-slate-700 whitespace-nowrap">
                        {bet.stake_units.toFixed(2)} u
                      </td>

                      {/* Status */}
                      <td className="px-3 py-3 text-center whitespace-nowrap">
                        <span
                          className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[10px] font-black border ${statusBadge.styles}`}
                        >
                          {statusBadge.label}
                        </span>
                      </td>

                      {/* Profit Units */}
                      <td className="px-3 py-3 text-right font-mono tabular-nums font-black whitespace-nowrap">
                        {bet.profit_units != null ? (
                          <span
                            className={
                              isProfit
                                ? "text-emerald-600"
                                : isLoss
                                ? "text-rose-600"
                                : "text-slate-600"
                            }
                          >
                            {bet.profit_units > 0 ? `+${bet.profit_units.toFixed(2)}` : bet.profit_units.toFixed(2)} u
                          </span>
                        ) : (
                          <span className="text-slate-400 font-normal">—</span>
                        )}
                      </td>

                      {/* CLV */}
                      <td className="px-3.5 py-3 text-right font-mono tabular-nums font-bold whitespace-nowrap">
                        {bet.clv_pct != null ? (
                          <span
                            className={
                              clvPositive
                                ? "text-emerald-600"
                                : clvNegative
                                ? "text-rose-600"
                                : "text-slate-600"
                            }
                          >
                            {bet.clv_pct > 0 ? "+" : ""}
                            {(bet.clv_pct * 100).toFixed(1)}%
                          </span>
                        ) : (
                          <span className="text-slate-400 font-normal">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Pagination Controls */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-t border-slate-100 pt-6 mt-4">
            <div className="text-xs text-slate-500">
              {isEs
                ? `Página ${page} de ${totalPages} • Total: ${total} apuestas`
                : `Page ${page} of ${totalPages} • Total: ${total} bets`}
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => onPageChange(page - 1)}
                disabled={page <= 1}
                aria-label={isEs ? "Página anterior" : "Previous page"}
                className="flex items-center gap-1 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-bold text-slate-700 shadow-2xs hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition focus-visible:ring-2 focus-visible:ring-orange-500 outline-none"
              >
                <ChevronLeft className="h-4 w-4" />
                <span>{isEs ? "Anterior" : "Previous"}</span>
              </button>

              <button
                type="button"
                onClick={() => onPageChange(page + 1)}
                disabled={page >= totalPages}
                aria-label={isEs ? "Página siguiente" : "Next page"}
                className="flex items-center gap-1 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-bold text-slate-700 shadow-2xs hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition focus-visible:ring-2 focus-visible:ring-orange-500 outline-none"
              >
                <span>{isEs ? "Siguiente" : "Next"}</span>
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
