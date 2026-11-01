"use client";

import React from "react";
import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { usePreferences } from "@/context/PreferencesContext";
import { X, Layers, Power, ShieldAlert } from "lucide-react";
import { ModeToggle } from "./ModeToggle";
import { MODE_THEME, navRoutesForMode, routeForPathname } from "@/lib/modes";

interface SidebarProps {
  isOpen?: boolean;
  onClose?: () => void;
  onOpenShutdown?: () => void;
}

export function Sidebar({ isOpen = false, onClose, onOpenShutdown }: SidebarProps) {
  const pathname = usePathname();
  const { t, language, mode } = usePreferences();
  const theme = MODE_THEME[mode];
  const navItems = navRoutesForMode(mode);
  const activeHref = routeForPathname(pathname)?.href;

  return (
    <>
      {/* Mobile Backdrop Overlay */}
      {isOpen && (
        <div
          onClick={onClose}
          className="fixed inset-0 z-40 bg-slate-900/40 backdrop-blur-xs md:hidden transition-opacity"
        />
      )}

      {/* Main Sidebar Aside */}
      <aside
        className={`fixed top-0 bottom-0 left-0 z-50 flex w-64 flex-col justify-between border-r border-slate-200 bg-white transition-transform duration-300 ease-in-out md:translate-x-0 ${
          isOpen ? "translate-x-0 shadow-2xl" : "-translate-x-full md:translate-x-0"
        }`}
      >
        <div className="flex min-h-0 flex-col space-y-6 overflow-y-auto p-5">
          {/* Mode colour bar: orange = analytics, emerald = betting */}
          <div className={`absolute inset-x-0 top-0 h-1 ${theme.topBar}`} aria-hidden="true" />

          {/* Brand Header */}
          <div className="flex items-center justify-between">
            <Link href="/" className="group flex items-center gap-3 transition" onClick={onClose}>
              <div className="relative h-10 w-10 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xs transition group-hover:border-orange-500">
                <Image
                  src="/archetypenba-logo.jpg"
                  alt="ArchetypeNBA Logo"
                  fill
                  className="object-cover"
                  priority
                />
              </div>
              <div className="flex flex-col">
                <div className="flex items-center gap-1.5">
                  <span className="text-base font-black tracking-tight text-slate-900">
                    Archetype<span className="text-orange-600">NBA</span>
                  </span>
                  <span className="rounded-md border border-orange-200 bg-orange-50 px-1.5 py-0.2 text-[9px] font-black text-orange-700">
                    PRO
                  </span>
                </div>
                <span className="text-[10px] font-medium text-slate-400 truncate max-w-[140px]">
                  {t("brand_tagline")}
                </span>
              </div>
            </Link>

            {/* Mobile Close Button */}
            <button
              onClick={onClose}
              className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 md:hidden"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Mode switch (mobile drawer; desktop has it in the top navbar) */}
          <div className="md:hidden">
            <ModeToggle fullWidth onSwitched={onClose} />
          </div>

          {/* Navigation Links (current mode only) */}
          <nav className="space-y-1.5 pt-2" aria-label={theme.label[language]}>
            <div className="flex items-center justify-between px-2 pb-2">
              <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                {theme.section[language]}
              </span>
              <span className={`rounded-md border px-1.5 py-0.5 text-[9px] font-black ${theme.badgeClass}`}>
                {theme.badge[language]}
              </span>
            </div>
            {navItems.map((item) => {
              const Icon = item.icon;
              const active = activeHref === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={onClose}
                  className={`group flex items-center gap-3 rounded-2xl border px-3.5 py-2.5 text-xs font-semibold transition-all ${
                    active
                      ? `${theme.linkActive} shadow-2xs`
                      : "border-transparent text-slate-600 hover:border-slate-200 hover:bg-slate-50 hover:text-slate-900"
                  }`}
                >
                  <Icon
                    className={`h-4 w-4 shrink-0 transition-transform group-hover:scale-110 ${
                      active ? theme.linkIcon : "text-slate-400 group-hover:text-slate-600"
                    }`}
                  />
                  <span className="truncate">{item.label[language]}</span>
                </Link>
              );
            })}
          </nav>

          {mode === "analysis" ? (
            <div className="rounded-2xl border border-slate-100 bg-slate-50/70 p-3.5 space-y-1.5">
              <div className="flex items-center gap-1.5 text-[10px] font-extrabold uppercase tracking-wide text-slate-500">
                <Layers className="h-3.5 w-3.5 text-orange-600" />
                <span>{language === "es" ? "Motor Táctico 7D" : "7D Tactical Engine"}</span>
              </div>
              <p className="text-[11px] text-slate-600 leading-tight">
                {language === "es"
                  ? "Clustering K-Means Per-36 + Soft GMM y Reducción 2D UMAP."
                  : "Per-36 K-Means Clustering + Soft GMM & 2D UMAP Projections."}
              </p>
            </div>
          ) : (
            <div className="rounded-2xl border border-emerald-200 bg-emerald-50/70 p-3.5 space-y-1.5">
              <div className="flex items-center gap-1.5 text-[10px] font-extrabold uppercase tracking-wide text-emerald-800">
                <ShieldAlert className="h-3.5 w-3.5 text-emerald-600" />
                <span>{language === "es" ? "Solo paper trading" : "Paper trading only"}</span>
              </div>
              <p className="text-[11px] text-emerald-900/80 leading-tight">
                {language === "es"
                  ? "Dinero ficticio. Sin apuestas reales. El modelo aún no supera al mercado."
                  : "Virtual funds. No real bets. The model does not beat the market yet."}
              </p>
            </div>
          )}

        </div>

        {/* Sidebar Footer: System Status & Shutdown Action */}
        <div className="border-t border-slate-100 p-4 space-y-3 bg-slate-50/40">
          <div className="flex items-center justify-between text-[11px] text-slate-500 font-medium">
            <div className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
              <span className="font-semibold text-slate-700">PostgreSQL 18</span>
            </div>
            <span className="font-mono font-bold text-slate-600">23 SEASONS</span>
          </div>
          <p className="text-[10px] text-slate-400 leading-none">
            {language === "es" ? "2003-04 a 2025-26 • 11.7k Registros" : "2003-04 to 2025-26 • 11.7k Records"}
          </p>

          {/* Stop Platform Services Trigger */}
          {onOpenShutdown && (
            <button
              type="button"
              onClick={() => {
                if (onClose) onClose();
                onOpenShutdown();
              }}
              className="w-full flex items-center justify-center gap-2 rounded-xl border border-rose-200 bg-rose-50/70 px-3 py-2 text-xs font-bold text-rose-700 hover:bg-rose-100 hover:border-rose-300 transition-all cursor-pointer shadow-2xs group"
            >
              <Power className="h-3.5 w-3.5 text-rose-600 transition-transform group-hover:scale-110" />
              <span>{language === "es" ? "Detener Servicios" : "Stop Services"}</span>
            </button>
          )}
        </div>

      </aside>
    </>
  );
}
