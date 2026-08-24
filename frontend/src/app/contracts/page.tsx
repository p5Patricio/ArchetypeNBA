"use client";

import React, { useState, useEffect } from "react";
import { usePreferences } from "@/context/PreferencesContext";
import { Navbar } from "@/components/Navbar";
import { CommandPalette } from "@/components/CommandPalette";


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
  const { language } = usePreferences();
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
          color: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
        };
      case "high_value":
        return {
          label: language === "es" ? "Alto Valor (A-Tier)" : "High Value (A-Tier)",
          color: "bg-blue-500/20 text-blue-300 border-blue-500/40",
        };
      case "fair_value":
        return {
          label: language === "es" ? "Valor Justo" : "Fair Value",
          color: "bg-amber-500/20 text-amber-300 border-amber-500/40",
        };
      default:
        return {
          label: language === "es" ? "Salario Elevado" : "Overpaid",
          color: "bg-rose-500/20 text-rose-300 border-rose-500/40",
        };
    }
  };

  return (
    <div className="min-h-screen bg-[#0A0E17] text-white relative overflow-hidden">
      <Navbar onOpenSearch={() => setIsCommandOpen(true)} />
      <CommandPalette isOpen={isCommandOpen} onClose={() => setIsCommandOpen(false)} />

      {/* Background Neon Brand Glow */}
      <div className="absolute top-0 right-1/3 w-96 h-96 bg-emerald-600/10 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute bottom-10 right-10 w-96 h-96 bg-amber-600/10 rounded-full blur-3xl pointer-events-none" />

      <div className="md:pl-64 p-6 md:p-10">
        <div className="max-w-6xl mx-auto space-y-6">
          <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 border-b border-white/10 pb-6">
          <div>
            <div className="flex items-center gap-2.5">
              <span className="px-3 py-1 text-xs font-bold uppercase tracking-wider rounded-lg bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                NBA Financial Analytics & Cap Valuation
              </span>
              <span className="text-xs text-gray-400">
                Surplus Value Model ($/PTS • $/WS • Cap Hit %)
              </span>
            </div>
            <h1 className="text-3xl md:text-5xl font-black tracking-tight mt-2 bg-gradient-to-r from-white via-gray-100 to-emerald-400 bg-clip-text text-transparent">
              {language === "es" ? "Finanzas & Contratos NBA" : "NBA Contracts & Payroll"}
            </h1>
            <p className="text-sm text-gray-400 max-w-2xl mt-1">
              {language === "es"
                ? "Evaluación de eficiencia financiera de plantillas, valor de producción por dólar invertido y análisis del tope salarial de las 30 franquicias."
                : "Financial efficiency modeling, cost-per-production valuation, and salary cap payroll breakdown across all 30 NBA franchises."}
            </p>
          </div>

          {/* Salary Cap Metrics Cards */}
          {data && (
            <div className="flex items-center gap-3">
              <div className="bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-right">
                <div className="text-[10px] uppercase font-bold text-gray-400 tracking-wider">
                  {language === "es" ? "Tope Salarial 24-25" : "Salary Cap 24-25"}
                </div>
                <div className="text-xl font-black text-emerald-400 font-mono">
                  ${(data.salary_cap_current / 1000000).toFixed(1)}M
                </div>
              </div>
              <div className="bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-right">
                <div className="text-[10px] uppercase font-bold text-gray-400 tracking-wider">
                  {language === "es" ? "Impuesto de Lujo" : "Luxury Tax Line"}
                </div>
                <div className="text-xl font-black text-amber-400 font-mono">
                  ${(data.luxury_tax_current / 1000000).toFixed(1)}M
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Tab Navigation */}
        <div className="flex items-center gap-2 border-b border-white/10 pb-3">
          <button
            onClick={() => setActiveTab("bargains")}
            className={`px-4 py-2 rounded-xl text-sm font-bold transition-all ${
              activeTab === "bargains"
                ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 shadow-sm"
                : "text-gray-400 hover:text-white"
            }`}
          >
            ★ {language === "es" ? "Mayores Gangas (Surplus Value)" : "Top Bargains (Surplus Value)"}
          </button>
          <button
            onClick={() => setActiveTab("salaries")}
            className={`px-4 py-2 rounded-xl text-sm font-bold transition-all ${
              activeTab === "salaries"
                ? "bg-amber-500/20 text-amber-300 border border-amber-500/40 shadow-sm"
                : "text-gray-400 hover:text-white"
            }`}
          >
            💰 {language === "es" ? "Mayores Salarios (Supermax)" : "Top Supermax Salaries"}
          </button>
          <button
            onClick={() => setActiveTab("payrolls")}
            className={`px-4 py-2 rounded-xl text-sm font-bold transition-all ${
              activeTab === "payrolls"
                ? "bg-blue-500/20 text-blue-300 border border-blue-500/40 shadow-sm"
                : "text-gray-400 hover:text-white"
            }`}
          >
            🏛 {language === "es" ? "Planillas de Franquicias" : "Franchise Payrolls"}
          </button>
        </div>

        {/* Loading State */}
        {loading && (
          <div className="flex justify-center py-20">
            <div className="w-8 h-8 border-4 border-emerald-500 border-t-transparent rounded-full animate-spin" />
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="p-4 bg-rose-500/20 border border-rose-500/30 rounded-xl text-rose-300 text-sm">
            {error}
          </div>
        )}

        {/* TAB 1: Surplus Value Bargains */}
        {data && activeTab === "bargains" && (
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {data.top_bargain_contracts.map((c, idx) => {
                const badge = getTierBadge(c.value_tier);
                return (
                  <div
                    key={`${c.player_id}-${idx}`}
                    className="bg-slate-900/90 border border-white/10 rounded-2xl p-5 backdrop-blur-xl shadow-xl flex flex-col justify-between hover:border-emerald-500/30 transition-all"
                  >
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-mono font-bold text-gray-400">#{idx + 1}</span>
                          <span className="text-xs font-semibold px-2 py-0.5 rounded bg-white/5 text-gray-300">
                            {c.team_abbreviation}
                          </span>
                          <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${badge.color}`}>
                            {badge.label}
                          </span>
                        </div>
                        <h3 className="text-xl font-bold text-white mt-1.5">{c.player_name}</h3>
                        <p className="text-xs text-gray-400 mt-0.5">{c.contract_type}</p>
                      </div>

                      <div className="text-right">
                        <div className="text-2xl font-black text-emerald-400 font-mono">{c.salary_formatted}</div>
                        <div className="text-xs text-gray-400">{c.cap_hit_pct}% Cap Hit</div>
                      </div>
                    </div>

                    <div className="grid grid-cols-3 gap-2 mt-4 pt-3 border-t border-white/10 text-center">
                      <div className="bg-black/30 p-2 rounded-xl">
                        <div className="text-[10px] uppercase text-gray-500 font-bold">Surplus Score</div>
                        <div className="text-sm font-black text-emerald-300">{c.surplus_value_rating}/100</div>
                      </div>
                      <div className="bg-black/30 p-2 rounded-xl">
                        <div className="text-[10px] uppercase text-gray-500 font-bold">Cost / PT</div>
                        <div className="text-sm font-mono font-bold text-gray-200">${Math.round(c.cost_per_pt).toLocaleString()}</div>
                      </div>
                      <div className="bg-black/30 p-2 rounded-xl">
                        <div className="text-[10px] uppercase text-gray-500 font-bold">Cost / WS</div>
                        <div className="text-sm font-mono font-bold text-gray-200">${(c.cost_per_ws / 1000000).toFixed(1)}M</div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* TAB 2: Top Salaries */}
        {data && activeTab === "salaries" && (
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {data.top_salary_contracts.map((c, idx) => (
                <div
                  key={`${c.player_id}-${idx}`}
                  className="bg-slate-900/90 border border-white/10 rounded-2xl p-5 backdrop-blur-xl shadow-xl flex flex-col justify-between hover:border-amber-500/30 transition-all"
                >
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-mono font-bold text-gray-400">#{idx + 1}</span>
                        <span className="text-xs font-semibold px-2 py-0.5 rounded bg-white/5 text-gray-300">
                          {c.team_abbreviation}
                        </span>
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/40">
                          {c.contract_type}
                        </span>
                      </div>
                      <h3 className="text-xl font-bold text-white mt-1.5">{c.player_name}</h3>
                      <p className="text-xs text-gray-400 mt-0.5">
                        {c.years_remaining} {language === "es" ? "Años Restantes • Agente Libre" : "Years Remaining • Free Agent"}{" "}
                        {c.free_agency_year}
                      </p>
                    </div>

                    <div className="text-right">
                      <div className="text-2xl font-black text-amber-400 font-mono">{c.salary_formatted}</div>
                      <div className="text-xs text-gray-400">{c.cap_hit_pct}% Cap Hit</div>
                    </div>
                  </div>

                  <div className="grid grid-cols-3 gap-2 mt-4 pt-3 border-t border-white/10 text-center">
                    <div className="bg-black/30 p-2 rounded-xl">
                      <div className="text-[10px] uppercase text-gray-500 font-bold">Surplus Score</div>
                      <div className="text-sm font-black text-gray-200">{c.surplus_value_rating}/100</div>
                    </div>
                    <div className="bg-black/30 p-2 rounded-xl">
                      <div className="text-[10px] uppercase text-gray-500 font-bold">Cost / PT</div>
                      <div className="text-sm font-mono font-bold text-gray-200">${Math.round(c.cost_per_pt).toLocaleString()}</div>
                    </div>
                    <div className="bg-black/30 p-2 rounded-xl">
                      <div className="text-[10px] uppercase text-gray-500 font-bold">Cost / WS</div>
                      <div className="text-sm font-mono font-bold text-gray-200">${(c.cost_per_ws / 1000000).toFixed(1)}M</div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* TAB 3: Franchise Payrolls */}
        {data && activeTab === "payrolls" && (
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {data.team_payrolls.map((tm) => (
                <div
                  key={tm.team_id}
                  className={`bg-slate-900/90 border rounded-2xl p-5 backdrop-blur-xl shadow-xl transition-all ${
                    tm.is_in_luxury_tax ? "border-amber-500/30" : "border-white/10"
                  }`}
                >
                  <div className="flex items-start justify-between">
                    <div>
                      <span className="text-xs font-semibold px-2 py-0.5 rounded bg-white/5 text-gray-300 font-mono">
                        {tm.team_abbreviation}
                      </span>
                      <h4 className="text-lg font-bold text-white mt-1">{tm.team_name}</h4>
                    </div>

                    <div className="text-right">
                      <div className="text-xl font-black text-white font-mono">{tm.payroll_formatted}</div>
                      {tm.is_in_luxury_tax ? (
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-rose-500/20 text-rose-300 border border-rose-500/40">
                          {language === "es" ? "En Impuesto de Lujo" : "Luxury Tax"}
                        </span>
                      ) : (
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
                          {language === "es" ? "Bajo el Límite" : "Under Tax"}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Cap Space / Over Cap */}
                  <div className="mt-4 p-2.5 bg-black/30 rounded-xl flex items-center justify-between text-xs">
                    <span className="text-gray-400">
                      {tm.cap_space >= 0
                        ? (language === "es" ? "Espacio Salarial:" : "Cap Space:")
                        : (language === "es" ? "Exceso Salarial:" : "Over Cap:")}
                    </span>
                    <span
                      className={`font-mono font-bold ${
                        tm.cap_space >= 0 ? "text-emerald-400" : "text-amber-400"
                      }`}
                    >
                      ${Math.abs(roundVal(tm.cap_space / 1000000)).toFixed(1)}M
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
      </div>
    </div>
  );
}


function roundVal(v: number): number {
  return Math.round(v * 10) / 10;
}
