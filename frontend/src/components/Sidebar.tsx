"use client";

import React from "react";
import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { usePreferences } from "@/context/PreferencesContext";
import {
  Compass,
  Sparkles,
  Shield,
  Crown,
  Database,
  Layers,
  X,
  Swords,
  Users,
  Dumbbell,
  ShieldAlert,
  History,
  Target,
  TrendingUp,
} from "lucide-react";

interface SidebarProps {
  isOpen?: boolean;
  onClose?: () => void;
}

export function Sidebar({ isOpen = false, onClose }: SidebarProps) {
  const pathname = usePathname();
  const { t, language } = usePreferences();

  const navItems = [
    {
      href: "/",
      label: t("nav_scouting_hub"),
      icon: Compass,
      active: pathname === "/",
      accent: "text-orange-600",
      activeBg: "bg-orange-50 text-orange-800 border-orange-200 font-extrabold",
    },
    {
      href: "/training",
      label: t("nav_training_camp") || "Campo de Entrenamiento",
      icon: Dumbbell,
      active: pathname.startsWith("/training"),
      accent: "text-cyan-600",
      activeBg: "bg-cyan-50 text-cyan-800 border-cyan-200 font-extrabold",
    },
    {
      href: "/versus",
      label: t("nav_versus") || "Coliseo 1 vs 1",
      icon: Swords,
      active: pathname.startsWith("/versus"),
      accent: "text-rose-600",
      activeBg: "bg-rose-50 text-rose-800 border-rose-200 font-extrabold",
    },
    {
      href: "/shot-zones",
      label: language === "es" ? "Zonas de Tiro (4 Ejes)" : "Shot Zones (4 Axes)",
      icon: Target,
      active: pathname.startsWith("/shot-zones"),
      accent: "text-orange-600",
      activeBg: "bg-orange-50 text-orange-800 border-orange-200 font-extrabold",
    },
    {
      href: "/matchups",
      label: language === "es" ? "Matchups 1v1 (¿Quién lo para?)" : "1v1 Matchups",
      icon: ShieldAlert,
      active: pathname.startsWith("/matchups"),
      accent: "text-red-600",
      activeBg: "bg-red-50 text-red-800 border-red-200 font-extrabold",
    },
    {
      href: "/props",
      label: language === "es" ? "Player Props & +EV" : "Player Props & +EV",
      icon: TrendingUp,
      active: pathname.startsWith("/props"),
      accent: "text-orange-600",
      activeBg: "bg-orange-50 text-orange-800 border-orange-200 font-extrabold",
    },
    {
      href: "/lineup",
      label: t("nav_lineup") || "Armador 5 vs 5",
      icon: Users,
      active: pathname.startsWith("/lineup"),
      accent: "text-emerald-600",
      activeBg: "bg-emerald-50 text-emerald-800 border-emerald-200 font-extrabold",
    },
    {
      href: "/doppelgangers",
      label: language === "es" ? "Doppelgängers" : "Doppelgängers",
      icon: Users,
      active: pathname.startsWith("/doppelgangers"),
      accent: "text-indigo-600",
      activeBg: "bg-indigo-50 text-indigo-800 border-indigo-200 font-extrabold",
    },
    {
      href: "/contracts",
      label: language === "es" ? "Contratos & Cap" : "Contracts & Cap",
      icon: Layers,
      active: pathname.startsWith("/contracts"),
      accent: "text-emerald-600",
      activeBg: "bg-emerald-50 text-emerald-800 border-emerald-200 font-extrabold",
    },
    {
      href: "/galaxy",
      label: t("nav_galaxy"),
      icon: Sparkles,
      active: pathname.startsWith("/galaxy"),
      accent: "text-purple-600",
      activeBg: "bg-purple-50 text-purple-800 border-purple-200 font-extrabold",
    },
    {
      href: "/hall-of-fame",
      label: t("nav_hall_of_fame"),
      icon: Crown,
      active: pathname.startsWith("/hall-of-fame"),
      accent: "text-amber-600",
      activeBg: "bg-amber-50 text-amber-800 border-amber-200 font-extrabold",
    },
    {
      href: "/teams",
      label: t("nav_franchises"),
      icon: Shield,
      active: pathname.startsWith("/teams"),
      accent: "text-sky-600",
      activeBg: "bg-sky-50 text-sky-800 border-sky-200 font-extrabold",
    },
    {
      href: "/timeline",
      label: t("nav_timeline"),
      icon: History,
      active: pathname.startsWith("/timeline"),
      accent: "text-blue-600",
      activeBg: "bg-blue-50 text-blue-800 border-blue-200 font-extrabold",
    },
  ];

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
        <div className="flex flex-col space-y-6 p-5">
          
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

          {/* Navigation Links */}
          <nav className="space-y-1.5 pt-2">
            <div className="px-2 pb-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">
              {language === "es" ? "Módulos de Analítica" : "Analytics Modules"}
            </div>
            {navItems.map((item) => {
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={onClose}
                  className={`group flex items-center gap-3 rounded-2xl border px-3.5 py-2.5 text-xs font-semibold transition-all ${
                    item.active
                      ? `${item.activeBg} shadow-2xs`
                      : "border-transparent text-slate-600 hover:border-slate-200 hover:bg-slate-50 hover:text-slate-900"
                  }`}
                >
                  <Icon
                    className={`h-4 w-4 shrink-0 transition-transform group-hover:scale-110 ${
                      item.active ? item.accent : "text-slate-400 group-hover:text-slate-600"
                    }`}
                  />
                  <span className="truncate">{item.label}</span>
                </Link>
              );
            })}
          </nav>

          {/* Quick Engine Methodology Badge */}
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

        </div>

        {/* Sidebar Footer: System Status */}
        <div className="border-t border-slate-100 p-4 space-y-2 bg-slate-50/40">
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
        </div>

      </aside>
    </>
  );
}
