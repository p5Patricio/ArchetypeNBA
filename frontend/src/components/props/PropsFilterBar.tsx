"use client";

import React, { useState } from "react";
import { usePreferences } from "@/context/PreferencesContext";
import {
  Search,
  SlidersHorizontal,
  Flame,
  LayoutGrid,
  List,
  X,
  ChevronDown,
  ChevronUp,
} from "lucide-react";

export type StatCategory = "ALL" | "POINTS" | "REBOUNDS" | "ASSISTS" | "PRA";
export type SortOption = "EV_DESC" | "EDGE_DESC" | "KELLY_DESC" | "LINE_DESC";
export type ViewMode = "cards" | "table";

interface PropsFilterBarProps {
  selectedCategory: StatCategory;
  onSelectCategory: (cat: StatCategory) => void;
  onlyValuePicks: boolean;
  onToggleOnlyValue: (val: boolean) => void;
  searchQuery: string;
  onSearchChange: (q: string) => void;
  sortBy: SortOption;
  onSortChange: (sort: SortOption) => void;
  viewMode: ViewMode;
  onViewModeChange: (view: ViewMode) => void;
  totalFilteredCount: number;
}

const CATEGORIES: StatCategory[] = ["ALL", "POINTS", "REBOUNDS", "ASSISTS", "PRA"];

export function PropsFilterBar({
  selectedCategory,
  onSelectCategory,
  onlyValuePicks,
  onToggleOnlyValue,
  searchQuery,
  onSearchChange,
  sortBy,
  onSortChange,
  viewMode,
  onViewModeChange,
  totalFilteredCount,
}: PropsFilterBarProps) {
  const { language } = usePreferences();
  const [isMobileExpanded, setIsMobileExpanded] = useState(false);
  const isEs = language === "es";

  const statCategoryLabels: Record<StatCategory, { es: string; en: string }> = {
    ALL: { es: "Todas", en: "All" },
    POINTS: { es: "Puntos (PTS)", en: "Points (PTS)" },
    REBOUNDS: { es: "Rebotes (REB)", en: "Rebounds (REB)" },
    ASSISTS: { es: "Asistencias (AST)", en: "Assists (AST)" },
    PRA: { es: "PTS + REB + AST", en: "PTS + REB + AST" },
  };

  const activeFiltersCount =
    (selectedCategory !== "ALL" ? 1 : 0) +
    (onlyValuePicks ? 1 : 0) +
    (searchQuery.trim() ? 1 : 0);

  return (
    <nav
      aria-label={isEs ? "Filtros y ordenación de props" : "Props filters and sorting"}
      className="rounded-3xl border border-slate-200 bg-white p-4 sm:p-5 shadow-xs space-y-4"
    >
      {/* Top Row: Horizontally scrollable Category Chips & Mobile disclosure button / Desktop Value Toggle */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
        {/* Category Pills (Full width on Mobile with scroll hint fade, flex-1 on Desktop) */}
        <div className="relative w-full md:w-auto flex-1 min-w-0">
          <div
            role="tablist"
            aria-label={isEs ? "Categorías de estadísticas" : "Stat categories"}
            className="flex items-center gap-1.5 overflow-x-auto pb-1 sm:pb-0 scrollbar-none no-scrollbar -mx-2 px-2 sm:mx-0 sm:px-0"
          >
            {CATEGORIES.map((cat) => {
              const isSelected = selectedCategory === cat;
              return (
                <button
                  key={cat}
                  role="tab"
                  aria-selected={isSelected}
                  onClick={() => onSelectCategory(cat)}
                  className={`px-3.5 py-1.5 rounded-xl text-xs font-bold transition-all border shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-500 cursor-pointer ${
                    isSelected
                      ? "bg-slate-900 text-white border-slate-900 shadow-xs font-black"
                      : "border-slate-200 bg-slate-50 text-slate-700 hover:bg-slate-100 hover:text-slate-900"
                  }`}
                >
                  {statCategoryLabels[cat][isEs ? "es" : "en"]}
                </button>
              );
            })}
          </div>

          {/* Right-edge subtle fade hint on mobile */}
          <div
            aria-hidden="true"
            className="pointer-events-none absolute right-0 top-0 bottom-0 w-8 bg-gradient-to-l from-white to-transparent md:hidden"
          />
        </div>

        {/* Mobile Disclosure Button (< 768px): on its own line beneath chips */}
        <div className="flex items-center justify-end md:hidden">
          <button
            type="button"
            onClick={() => setIsMobileExpanded((prev) => !prev)}
            aria-expanded={isMobileExpanded}
            aria-label={isEs ? "Alternar panel de filtros y búsqueda" : "Toggle filters and search panel"}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-slate-200 bg-slate-50 text-xs font-bold text-slate-700 hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-500 cursor-pointer"
          >
            <SlidersHorizontal className="h-3.5 w-3.5 text-slate-500" />
            <span>{isEs ? "Filtros" : "Filters"}</span>
            {activeFiltersCount > 0 && (
              <span className="flex h-4 w-4 items-center justify-center rounded-full bg-orange-600 text-[10px] font-black text-white">
                {activeFiltersCount}
              </span>
            )}
            {isMobileExpanded ? (
              <ChevronUp className="h-3.5 w-3.5 text-slate-400" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
            )}
          </button>
        </div>

        {/* Desktop Value Toggle (Visible on md+) */}
        <div className="hidden md:flex items-center gap-3 shrink-0">
          <label className="relative inline-flex items-center cursor-pointer select-none">
            <input
              type="checkbox"
              checked={onlyValuePicks}
              onChange={(e) => onToggleOnlyValue(e.target.checked)}
              className="sr-only peer"
            />
            <div className="w-9 h-5 bg-slate-200 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-emerald-500 focus-visible:ring-2 focus-visible:ring-emerald-500"></div>
            <span className="ml-2.5 text-xs font-bold text-slate-800 flex items-center gap-1.5">
              <Flame className="h-3.5 w-3.5 text-emerald-600" />
              <span>{isEs ? "Solo picks con valor (+EV)" : "Only +EV Picks"}</span>
            </span>
          </label>
        </div>
      </div>

      {/* Secondary Controls: Search, Sort, View Toggle, Mobile Controls */}
      <div
        className={`${
          isMobileExpanded ? "block" : "hidden"
        } md:block pt-3 border-t border-slate-100 transition-all`}
      >
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
          {/* Mobile Only: Value Toggle when expanded */}
          <div className="md:hidden pb-1 flex items-center justify-between">
            <label className="relative inline-flex items-center cursor-pointer select-none">
              <input
                type="checkbox"
                checked={onlyValuePicks}
                onChange={(e) => onToggleOnlyValue(e.target.checked)}
                className="sr-only peer"
              />
              <div className="w-9 h-5 bg-slate-200 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-emerald-500"></div>
              <span className="ml-2 text-xs font-bold text-slate-800 flex items-center gap-1">
                <Flame className="h-3.5 w-3.5 text-emerald-600" />
                <span>{isEs ? "Solo picks con +EV" : "Only +EV Picks"}</span>
              </span>
            </label>

            <span className="text-[11px] font-bold text-slate-400 tabular-nums">
              {totalFilteredCount} {isEs ? "props" : "props"}
            </span>
          </div>

          {/* Search Bar */}
          <div className="relative w-full sm:w-72 lg:w-80">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
            <input
              type="search"
              value={searchQuery}
              onChange={(e) => onSearchChange(e.target.value)}
              aria-label={isEs ? "Buscar jugador o equipo" : "Search player or team"}
              placeholder={
                isEs
                  ? "Buscar jugador o equipo (ej. Luka, LAL)..."
                  : "Search player or team (e.g. Luka, LAL)..."
              }
              className="w-full pl-9 pr-8 py-2 rounded-xl border border-slate-200 bg-slate-50/80 text-xs font-medium text-slate-900 placeholder:text-slate-400 focus:border-orange-500 focus:bg-white focus:ring-2 focus:ring-orange-500/10 transition-all outline-none"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => onSearchChange("")}
                aria-label={isEs ? "Limpiar búsqueda" : "Clear search"}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-full p-0.5 text-slate-400 hover:text-slate-600 hover:bg-slate-200 transition-colors cursor-pointer"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>

          {/* Sort Selector & View Mode Switcher */}
          <div className="flex items-center justify-between sm:justify-end gap-3 flex-wrap">
            <div className="flex items-center gap-2">
              <SlidersHorizontal className="h-3.5 w-3.5 text-slate-400 shrink-0" />
              <label htmlFor="props-sort-select" className="text-xs font-semibold text-slate-500 shrink-0">
                {isEs ? "Ordenar:" : "Sort:"}
              </label>
              <select
                id="props-sort-select"
                value={sortBy}
                onChange={(e) => onSortChange(e.target.value as SortOption)}
                aria-label={isEs ? "Ordenar resultados" : "Sort results"}
                className="px-3 py-1.5 rounded-xl border border-slate-200 bg-slate-50 text-xs font-bold text-slate-800 outline-none cursor-pointer focus-visible:ring-2 focus-visible:ring-orange-500"
              >
                <option value="EV_DESC">
                  {isEs ? "Mayor Expected Value (+EV %)" : "Highest +EV %"}
                </option>
                <option value="EDGE_DESC">
                  {isEs ? "Mayor Ventaja Modelo (Edge %)" : "Highest Edge %"}
                </option>
                <option value="KELLY_DESC">
                  {isEs ? "Mayor Stake Kelly %" : "Highest Kelly Stake"}
                </option>
                <option value="LINE_DESC">
                  {isEs ? "Línea más alta" : "Highest Line"}
                </option>
              </select>
            </div>

            {/* Grid / Table Toggle */}
            <div
              role="group"
              aria-label={isEs ? "Modo de visualización" : "View mode"}
              className="inline-flex items-center rounded-xl border border-slate-200 bg-slate-50 p-0.5"
            >
              <button
                type="button"
                onClick={() => onViewModeChange("cards")}
                aria-label={isEs ? "Vista de tarjetas" : "Cards view"}
                aria-pressed={viewMode === "cards"}
                className={`rounded-lg p-1.5 transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-500 cursor-pointer ${
                  viewMode === "cards"
                    ? "bg-white text-slate-900 shadow-2xs font-bold"
                    : "text-slate-400 hover:text-slate-700"
                }`}
              >
                <LayoutGrid className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={() => onViewModeChange("table")}
                aria-label={isEs ? "Vista de tabla" : "Table view"}
                aria-pressed={viewMode === "table"}
                className={`rounded-lg p-1.5 transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-500 cursor-pointer ${
                  viewMode === "table"
                    ? "bg-white text-slate-900 shadow-2xs font-bold"
                    : "text-slate-400 hover:text-slate-700"
                }`}
              >
                <List className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </nav>
  );
}
