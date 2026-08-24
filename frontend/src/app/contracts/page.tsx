"use client";

import React, { useState, useEffect } from "react";
import { usePreferences } from "@/context/PreferencesContext";
import { Navbar } from "@/components/Navbar";
import { CommandPalette } from "@/components/CommandPalette";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { DollarSign, Layers, ArrowLeft, TrendingUp, ShieldAlert, Award, Star } from "lucide-react";
import Link from "next/link";

interface ContractDetail {
  player_id: number;
  player_name: string;
  team_abbreviation: string;
  team_name: string;
  annual_salary: number;
  salary_formatted: string;
  cap_hit_pct: number;
  contract_type: string;
  years_remaining: number;
  free_agency_year: number;
  cost_per_pt: number;
  cost_per_ws: number;
  surplus_value_rating: number;
  value_tier: string;
}

interface TeamPayroll {
  team_id: number;
  team_abbreviation: string;
  team_name: string;
  total_payroll: number;
  payroll_formatted: string;
  salary_cap: number;
  luxury_tax_threshold: number;
  cap_space: number;
  is_in_luxury_tax: boolean;
  top_contracts: ContractDetail[];
}

interface FinancialData {
  salary_cap_current: number;
  luxury_tax_current: number;
  top_bargain_contracts: ContractDetail[];
  top_salary_contracts: ContractDetail[];
  team_payrolls: TeamPayroll[];
}

export default function ContractsPage() {
  const { language, t } = usePreferences();
  const [activeTab, setActiveTab] = useState<"bargains" | "salaries" | "payrolls">("bargains");
  const [isCommandOpen, setIsCommandOpen] = useState(false);
  const [data, setData] = useState<FinancialData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("http://localhost:8000/api/v1/financial/contracts")
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load financial analytics");
        return res.json();
      })
      .then((resData: FinancialData) => {
        setData(resData);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  const getTierBadge = (tier: string) => {
    switch (tier) {
      case "elite_bargain":
        return {
          label: language === "es" ? "Ganga Élite (S-Tier)" : "Elite Bargain (S-Tier)",
          color: "bg-emerald-50 text-emerald-800 border-emerald-200",
        };
      case "high_value":
        return {
          label: language === "es" ? "Alto Valor (A-Tier)" : "High Value (A-Tier)",
          color: "bg-blue-50 text-blue-800 border-blue-200",
        };
      case "fair_value":
        return {
          label: language === "es" ? "Valor Justo" : "Fair Value",
          color: "bg-amber-50 text-amber-800 border-amber-200",
        };
      default:
        return {
          label: language === "es" ? "Salario Elevado" : "Overpaid",
          color: "bg-rose-50 text-rose-800 border-rose-200",
        };
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 md:pl-64 pb-20">
      <Navbar onOpenSearch={() => setIsCommandOpen(true)} />
      <CommandPalette isOpen={isCommandOpen} onClose={() => setIsCommandOpen(false)} />

      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8 space-y-8">
        {/* Back Link */}
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-xs font-bold text-slate-500 hover:text-slate-900 transition-colors uppercase tracking-wider"
        >
          <ArrowLeft className="h-4 w-4" />
          {t("nav_scouting_hub")}
        </Link>

        {/* Header Title Section with Cap Line Metrics */}
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 border-b border-slate-200/80 pb-6">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-emerald-600 text-white shadow-md shadow-emerald-600/20">
              <DollarSign className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-2xl sm:text-3xl font-black tracking-tight text-slate-900 flex items-center gap-2">
                {language === "es" ? "Finanzas & Contratos NBA" : "NBA Contracts & Payroll"}
                <span className="rounded-md border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[10px] font-black uppercase text-emerald-800 tracking-wider">
                  Surplus Valuation
                </span>
              </h1>
              <p className="text-xs sm:text-sm font-medium text-slate-500 mt-0.5 max-w-3xl">
                {language === "es"
                  ? "Evaluación de eficiencia financiera por dólar invertido, coste por punto y victoria producida, y estado del tope salarial."
                  : "Financial efficiency modeling, cost-per-point production, and salary cap space evaluation across NBA franchises."}
              </p>
            </div>
          </div>

          {/* Salary Cap Metrics Cards */}
          {data && (
            <div className="flex items-center gap-2.5">
              <div className="rounded-2xl border border-slate-200 bg-white px-4 py-2 shadow-2xs text-right">
                <span className="block text-[10px] font-bold uppercase text-slate-400">
                  {language === "es" ? "Tope Salarial 24-25" : "Salary Cap 24-25"}
                </span>
                <span className="text-lg font-black font-mono text-emerald-700">
                  ${(data.salary_cap_current / 1000000).toFixed(1)}M
                </span>
              </div>
              <div className="rounded-2xl border border-slate-200 bg-white px-4 py-2 shadow-2xs text-right">
                <span className="block text-[10px] font-bold uppercase text-slate-400">
                  {language === "es" ? "Límite Impuesto de Lujo" : "Luxury Tax Line"}
                </span>
                <span className="text-lg font-black font-mono text-amber-700">
                  ${(data.luxury_tax_current / 1000000).toFixed(1)}M
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Tab Navigation Pill Group */}
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 pb-3">
          <button
            onClick={() => setActiveTab("bargains")}
            className={`px-4 py-2 rounded-xl text-xs font-bold transition-all ${
              activeTab === "bargains"
                ? "bg-emerald-600 text-white shadow-xs"
                : "bg-white text-slate-700 hover:text-slate-900 border border-slate-200"
            }`}
          >
            ★ {language === "es" ? "Mayores Gangas (Surplus Value)" : "Top Bargains (Surplus Value)"}
          </button>
          <button
            onClick={() => setActiveTab("salaries")}
            className={`px-4 py-2 rounded-xl text-xs font-bold transition-all ${
              activeTab === "salaries"
                ? "bg-amber-600 text-white shadow-xs"
                : "bg-white text-slate-700 hover:text-slate-900 border border-slate-200"
            }`}
          >
            💰 {language === "es" ? "Mayores Salarios (Supermax)" : "Top Supermax Salaries"}
          </button>
          <button
            onClick={() => setActiveTab("payrolls")}
            className={`px-4 py-2 rounded-xl text-xs font-bold transition-all ${
              activeTab === "payrolls"
                ? "bg-blue-600 text-white shadow-xs"
                : "bg-white text-slate-700 hover:text-slate-900 border border-slate-200"
            }`}
          >
            🏛 {language === "es" ? "Planillas de Franquicias" : "Franchise Payrolls"}
          </button>
        </div>

        {/* Loading State */}
        {loading && (
          <div className="flex flex-col items-center justify-center py-16 space-y-3">
            <div className="w-9 h-9 border-3 border-emerald-600 border-t-transparent rounded-full animate-spin" />
            <p className="text-xs font-bold text-slate-500 font-mono">
              {language === "es" ? "Cargando analítica financiera..." : "Loading financial analytics..."}
            </p>
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="p-4 bg-rose-50 border border-rose-200 rounded-2xl text-rose-700 text-xs font-semibold">
            {error}
          </div>
        )}

        {/* TAB 1: Surplus Value Bargains */}
        {!loading && data && activeTab === "bargains" && (
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
              {data.top_bargain_contracts.map((c, idx) => {
                const badge = getTierBadge(c.value_tier);
                return (
                  <div
                    key={`${c.player_id}-${idx}`}
                    className="rounded-3xl border border-slate-200 bg-white p-6 shadow-xs flex flex-col justify-between hover:border-emerald-300 hover:shadow-sm transition duration-200"
                  >
                    <div>
                      <div className="flex items-start justify-between">
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="text-[10px] font-mono font-bold text-slate-400">#{idx + 1}</span>
                            <span className="text-[11px] font-bold px-2 py-0.5 rounded bg-slate-100 text-slate-700 font-mono">
                              {c.team_abbreviation}
                            </span>
                            <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${badge.color}`}>
                              {badge.label}
                            </span>
                          </div>
                          <h3 className="text-lg font-black text-slate-900 mt-2">{c.player_name}</h3>
                          <p className="text-xs text-slate-500 mt-0.5">{c.contract_type}</p>
                        </div>

                        <div className="text-right">
                          <div className="text-xl font-black text-emerald-700 font-mono">{c.salary_formatted}</div>
                          <div className="text-[11px] text-slate-400 font-medium">{c.cap_hit_pct}% Cap</div>
                        </div>
                      </div>
                    </div>

                    <div className="grid grid-cols-3 gap-2 mt-5 pt-3 border-t border-slate-100 text-center">
                      <div className="bg-slate-50 p-2 rounded-xl border border-slate-100">
                        <div className="text-[9px] uppercase text-slate-400 font-bold">Surplus Score</div>
                        <div className="text-xs font-black text-emerald-700 font-mono">{c.surplus_value_rating}/100</div>
                      </div>
                      <div className="bg-slate-50 p-2 rounded-xl border border-slate-100">
                        <div className="text-[9px] uppercase text-slate-400 font-bold">Cost / PT</div>
                        <div className="text-xs font-mono font-bold text-slate-800">${Math.round(c.cost_per_pt).toLocaleString()}</div>
                      </div>
                      <div className="bg-slate-50 p-2 rounded-xl border border-slate-100">
                        <div className="text-[9px] uppercase text-slate-400 font-bold">Cost / WS</div>
                        <div className="text-xs font-mono font-bold text-slate-800">${(c.cost_per_ws / 1000000).toFixed(1)}M</div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* TAB 2: Top Salaries */}
        {!loading && data && activeTab === "salaries" && (
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
              {data.top_salary_contracts.map((c, idx) => (
                <div
                  key={`${c.player_id}-${idx}`}
                  className="rounded-3xl border border-slate-200 bg-white p-6 shadow-xs flex flex-col justify-between hover:border-amber-300 hover:shadow-sm transition duration-200"
                >
                  <div>
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] font-mono font-bold text-slate-400">#{idx + 1}</span>
                          <span className="text-[11px] font-bold px-2 py-0.5 rounded bg-slate-100 text-slate-700 font-mono">
                            {c.team_abbreviation}
                          </span>
                          <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-amber-50 text-amber-800 border border-amber-200">
                            {c.contract_type}
                          </span>
                        </div>
                        <h3 className="text-lg font-black text-slate-900 mt-2">{c.player_name}</h3>
                        <p className="text-xs text-slate-500 mt-0.5">
                          {c.years_remaining} {language === "es" ? "Años Restantes • Agente Libre" : "Years Left • Free Agent"}{" "}
                          {c.free_agency_year}
                        </p>
                      </div>

                      <div className="text-right">
                        <div className="text-xl font-black text-amber-700 font-mono">{c.salary_formatted}</div>
                        <div className="text-[11px] text-slate-400 font-medium">{c.cap_hit_pct}% Cap</div>
                      </div>
                    </div>
                  </div>

                  <div className="grid grid-cols-3 gap-2 mt-5 pt-3 border-t border-slate-100 text-center">
                    <div className="bg-slate-50 p-2 rounded-xl border border-slate-100">
                      <div className="text-[9px] uppercase text-slate-400 font-bold">Surplus Score</div>
                      <div className="text-xs font-black text-slate-800 font-mono">{c.surplus_value_rating}/100</div>
                    </div>
                    <div className="bg-slate-50 p-2 rounded-xl border border-slate-100">
                      <div className="text-[9px] uppercase text-slate-400 font-bold">Cost / PT</div>
                      <div className="text-xs font-mono font-bold text-slate-800">${Math.round(c.cost_per_pt).toLocaleString()}</div>
                    </div>
                    <div className="bg-slate-50 p-2 rounded-xl border border-slate-100">
                      <div className="text-[9px] uppercase text-slate-400 font-bold">Cost / WS</div>
                      <div className="text-xs font-mono font-bold text-slate-800">${(c.cost_per_ws / 1000000).toFixed(1)}M</div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* TAB 3: Franchise Payrolls */}
        {!loading && data && activeTab === "payrolls" && (
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
              {data.team_payrolls.map((tm) => (
                <div
                  key={tm.team_id}
                  className={`rounded-3xl border bg-white p-6 shadow-xs transition-all ${
                    tm.is_in_luxury_tax ? "border-amber-200" : "border-slate-200"
                  }`}
                >
                  <div className="flex items-start justify-between">
                    <div>
                      <span className="text-xs font-semibold px-2 py-0.5 rounded bg-slate-100 text-slate-700 font-mono">
                        {tm.team_abbreviation}
                      </span>
                      <h4 className="text-lg font-black text-slate-900 mt-1">{tm.team_name}</h4>
                    </div>

                    <div className="text-right">
                      <div className="text-xl font-black text-slate-900 font-mono">{tm.payroll_formatted}</div>
                      {tm.is_in_luxury_tax ? (
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-rose-50 text-rose-700 border border-rose-200">
                          {language === "es" ? "En Impuesto de Lujo" : "Luxury Tax"}
                        </span>
                      ) : (
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200">
                          {language === "es" ? "Bajo el Límite" : "Under Tax"}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Cap Space / Over Cap Indicator */}
                  <div className="mt-4 p-2.5 bg-slate-50 rounded-2xl flex items-center justify-between text-xs border border-slate-100">
                    <span className="text-slate-500 font-medium">
                      {tm.cap_space >= 0
                        ? (language === "es" ? "Espacio Salarial:" : "Cap Space:")
                        : (language === "es" ? "Exceso Salarial:" : "Over Cap:")}
                    </span>
                    <span
                      className={`font-mono font-bold ${
                        tm.cap_space >= 0 ? "text-emerald-700" : "text-amber-700"
                      }`}
                    >
                      ${Math.abs(Math.round(tm.cap_space / 100000) / 10).toFixed(1)}M
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
