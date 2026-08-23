"use client";

import React, { useState } from "react";
import { usePathname } from "next/navigation";
import { Search, Menu, Globe, Ruler } from "lucide-react";
import { SeasonSelect } from "./SeasonSelect";
import { Sidebar } from "./Sidebar";
import { usePreferences } from "@/context/PreferencesContext";

interface NavbarProps {
  currentSeasonId?: number;
  onSeasonChange?: (seasonId: number, seasonLabel?: string) => void;
  onOpenSearch?: () => void;
}

export function Navbar({ currentSeasonId = 1, onSeasonChange, onOpenSearch }: NavbarProps) {
  const pathname = usePathname();
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const { language, setLanguage, unitSystem, setUnitSystem, t } = usePreferences();

  // Page title resolution for top header
  const getPageTitle = () => {
    if (pathname === "/") return language === "es" ? "Scouting Hub" : "Scouting Hub";
    if (pathname.startsWith("/versus")) return language === "es" ? "Coliseo 1 vs 1" : "1 vs 1 Colosseum";
    if (pathname.startsWith("/lineup")) return language === "es" ? "Armador 5 vs 5" : "5 vs 5 Lineup Builder";
    if (pathname.startsWith("/galaxy")) return language === "es" ? "Galaxia Táctica" : "Tactical Galaxy";
    if (pathname.startsWith("/hall-of-fame")) return language === "es" ? "Salón de la Fama" : "Hall of Fame";
    if (pathname.startsWith("/teams")) return language === "es" ? "Franquicias NBA" : "NBA Franchises";
    if (pathname.startsWith("/player")) return language === "es" ? "Scouting Lab de Jugador" : "Player Scouting Lab";
    return "ArchetypeNBA";
  };

  return (
    <>
      {/* Sidebar Component (Desktop Fixed + Mobile Drawer) */}
      <Sidebar
        isOpen={isMobileMenuOpen}
        onClose={() => setIsMobileMenuOpen(false)}
      />

      {/* Top Header Navigation (Offset on desktop for sidebar) */}
      <header className="sticky top-0 z-30 w-full border-b border-slate-200 bg-white/90 backdrop-blur-md transition-all shadow-2xs md:pl-64">
        <div className="flex h-16 items-center justify-between px-4 sm:px-6 lg:px-8">
          
          {/* Left: Mobile Toggle & Page Breadcrumb Title */}
          <div className="flex items-center gap-3">
            <button
              onClick={() => setIsMobileMenuOpen(true)}
              className="rounded-xl border border-slate-200 bg-slate-50 p-2 text-slate-600 hover:bg-slate-100 hover:text-slate-900 md:hidden shadow-2xs"
              aria-label="Abrir menú"
            >
              <Menu className="h-5 w-5" />
            </button>

            <div className="flex items-center gap-2">
              <span className="text-xs font-mono font-bold uppercase tracking-wider text-slate-400 hidden sm:inline">
                PANEL /
              </span>
              <h1 className="text-sm sm:text-base font-black tracking-tight text-slate-900 truncate">
                {getPageTitle()}
              </h1>
            </div>
          </div>

          {/* Right Actions: Search Bar, Season Dropdown & Preference Toggles */}
          <div className="flex items-center gap-2.5">
            
            {/* Universal Search Bar Trigger */}
            <button
              type="button"
              onClick={onOpenSearch}
              className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600 shadow-2xs transition hover:border-orange-400 hover:bg-white hover:text-slate-900"
            >
              <Search className="h-3.5 w-3.5 text-slate-400" />
              <span className="hidden sm:inline">{t("nav_search_placeholder")}</span>
              <kbd className="rounded border border-slate-200 bg-white px-1.5 py-0.2 font-mono text-[10px] text-slate-500 shadow-xs">
                ⌘K
              </kbd>
            </button>

            {/* Season Selector */}
            {onSeasonChange && (
              <SeasonSelect
                value={currentSeasonId}
                onChange={onSeasonChange}
                className="bg-slate-50 border-slate-200 text-slate-800 text-xs shadow-2xs"
              />
            )}

            {/* Language Switcher Pill */}
            <div className="flex items-center rounded-xl border border-slate-200 bg-slate-50 p-0.5 shadow-2xs">
              <button
                onClick={() => setLanguage("es")}
                className={`rounded-lg px-2 py-1 text-[11px] font-black transition ${
                  language === "es"
                    ? "bg-white text-orange-600 shadow-xs border border-slate-200/80"
                    : "text-slate-500 hover:text-slate-900"
                }`}
                title="Español"
              >
                ES
              </button>
              <button
                onClick={() => setLanguage("en")}
                className={`rounded-lg px-2 py-1 text-[11px] font-black transition ${
                  language === "en"
                    ? "bg-white text-orange-600 shadow-xs border border-slate-200/80"
                    : "text-slate-500 hover:text-slate-900"
                }`}
                title="English"
              >
                EN
              </button>
            </div>

            {/* Unit System Switcher Pill */}
            <div className="hidden sm:flex items-center rounded-xl border border-slate-200 bg-slate-50 p-0.5 shadow-2xs">
              <button
                onClick={() => setUnitSystem("metric")}
                className={`flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-bold transition ${
                  unitSystem === "metric"
                    ? "bg-white text-sky-700 shadow-xs border border-slate-200/80"
                    : "text-slate-500 hover:text-slate-900"
                }`}
                title="Sistema Métrico (cm / kg)"
              >
                cm/kg
              </button>
              <button
                onClick={() => setUnitSystem("imperial")}
                className={`flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-bold transition ${
                  unitSystem === "imperial"
                    ? "bg-white text-sky-700 shadow-xs border border-slate-200/80"
                    : "text-slate-500 hover:text-slate-900"
                }`}
                title="Imperial System (ft / lbs)"
              >
                ft/lbs
              </button>
            </div>

          </div>

        </div>
      </header>
    </>
  );
}
