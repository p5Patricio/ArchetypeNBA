"use client";

import React from "react";
import Image from "next/image";
import { Plus, X, Star, Swords } from "lucide-react";
import type { LineupSlotDetail } from "@/lib/api";

interface HorizontalCourtProps {
  team1Slots: (LineupSlotDetail | null)[];
  team2Slots: (LineupSlotDetail | null)[];
  team1Name: string;
  team2Name: string;
  onSlotClick: (teamIndex: 1 | 2, position: string, currentSlot: LineupSlotDetail | null) => void;
  onRemovePlayer: (teamIndex: 1 | 2, position: string) => void;
  language: "es" | "en";
}

// Tactical coordinates on a 940 x 500 court (exact percentage positioning)
const POSITIONS_T1 = [
  { pos: "PG", labelEs: "Base", labelEn: "Point Guard", x: 34, y: 50 },
  { pos: "SG", labelEs: "Escolta", labelEn: "Shooting Guard", x: 25, y: 16 },
  { pos: "SF", labelEs: "Alero", labelEn: "Small Forward", x: 25, y: 84 },
  { pos: "PF", labelEs: "Ala-Pívot", labelEn: "Power Forward", x: 18, y: 32 },
  { pos: "C", labelEs: "Pívot", labelEn: "Center", x: 11, y: 62 },
];

const POSITIONS_T2 = [
  { pos: "PG", labelEs: "Base", labelEn: "Point Guard", x: 66, y: 50 },
  { pos: "SG", labelEs: "Escolta", labelEn: "Shooting Guard", x: 75, y: 16 },
  { pos: "SF", labelEs: "Alero", labelEn: "Small Forward", x: 75, y: 84 },
  { pos: "PF", labelEs: "Ala-Pívot", labelEn: "Power Forward", x: 82, y: 32 },
  { pos: "C", labelEs: "Pívot", labelEn: "Center", x: 89, y: 62 },
];

export function HorizontalCourt({
  team1Slots,
  team2Slots,
  team1Name,
  team2Name,
  onSlotClick,
  onRemovePlayer,
  language,
}: HorizontalCourtProps) {
  const isEs = language === "es";

  const getSlot = (slots: (LineupSlotDetail | null)[], pos: string) => {
    return slots.find((s) => s?.position === pos) || null;
  };

  return (
    <div className="relative w-full overflow-hidden rounded-3xl border border-slate-200/90 bg-white shadow-md">
      {/* Court Top Info Bar */}
      <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50/90 px-6 py-3.5 backdrop-blur-md">
        <div className="flex items-center gap-2.5">
          <span className="h-3 w-3 rounded-full bg-orange-500 shadow-xs" />
          <span className="font-mono text-xs font-black uppercase tracking-wider text-orange-950">
            {team1Name} <span className="text-orange-600 font-bold">({isEs ? "LOCAL" : "HOME"})</span>
          </span>
        </div>

        <div className="hidden sm:flex items-center gap-2 font-mono text-[11px] font-bold text-slate-500">
          <Swords className="h-3.5 w-3.5 text-orange-500" />
          <span>CANCHA NBA • VISTA CENITAL OFICIAL</span>
        </div>

        <div className="flex items-center gap-2.5">
          <span className="font-mono text-xs font-black uppercase tracking-wider text-blue-950">
            {team2Name} <span className="text-blue-600 font-bold">({isEs ? "VISITA" : "AWAY"})</span>
          </span>
          <span className="h-3 w-3 rounded-full bg-blue-600 shadow-xs" />
        </div>
      </div>

      {/* SVG Court Background Markings */}
      <div className="relative aspect-[1.88/1] w-full min-h-[460px] sm:min-h-[520px] bg-white">
        <svg
          viewBox="0 0 940 500"
          className="absolute inset-0 h-full w-full select-none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <defs>
            {/* Soft subtle grid/floor pattern */}
            <pattern id="floorGrid" width="40" height="40" patternUnits="userSpaceOnUse">
              <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#F1F5F9" strokeWidth="0.8" />
            </pattern>

            {/* Left Paint (Orange Gradient) */}
            <linearGradient id="paintOrange" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#EA580C" stopOpacity="0.18" />
              <stop offset="100%" stopColor="#FB923C" stopOpacity="0.08" />
            </linearGradient>

            {/* Right Paint (Blue Gradient) */}
            <linearGradient id="paintBlue" x1="100%" y1="0%" x2="0%" y2="0%">
              <stop offset="0%" stopColor="#2563EB" stopOpacity="0.18" />
              <stop offset="100%" stopColor="#60A5FA" stopOpacity="0.08" />
            </linearGradient>

            {/* Center Circle Glow */}
            <linearGradient id="centerGlow" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#EA580C" stopOpacity="0.15" />
              <stop offset="100%" stopColor="#2563EB" stopOpacity="0.15" />
            </linearGradient>
          </defs>

          {/* Clean White Court Base */}
          <rect width="940" height="500" fill="#FFFFFF" />
          <rect width="940" height="500" fill="url(#floorGrid)" />

          {/* Outer Boundary Line */}
          <rect
            x="20"
            y="20"
            width="900"
            height="460"
            fill="none"
            stroke="#94A3B8"
            strokeWidth="3"
            rx="4"
          />

          {/* Half-Court Line */}
          <line
            x1="470"
            y1="20"
            x2="470"
            y2="480"
            stroke="#94A3B8"
            strokeWidth="3"
          />

          {/* Center Circle */}
          <circle
            cx="470"
            cy="250"
            r="60"
            fill="url(#centerGlow)"
            stroke="#94A3B8"
            strokeWidth="2.5"
          />
          {/* Center Circle Dual Colors */}
          <path
            d="M 470,190 A 60,60 0 0,0 470,310"
            fill="none"
            stroke="#EA580C"
            strokeWidth="3"
          />
          <path
            d="M 470,190 A 60,60 0 0,1 470,310"
            fill="none"
            stroke="#2563EB"
            strokeWidth="3"
          />

          {/* Center Inner Dot / Mini Circle */}
          <circle
            cx="470"
            cy="250"
            r="16"
            fill="#FFFFFF"
            stroke="#94A3B8"
            strokeWidth="2"
          />

          {/* ========================================================================= */}
          {/* LEFT SIDE — TEAM 1 (ORANGE ACCENTS) */}
          {/* ========================================================================= */}
          {/* Key / Paint Area (190 x 160) */}
          <rect
            x="20"
            y="170"
            width="190"
            height="160"
            fill="url(#paintOrange)"
            stroke="#EA580C"
            strokeWidth="2.5"
          />

          {/* Free Throw Circle (Radius 60, Center at 210, 250) */}
          <path
            d="M 210,190 A 60,60 0 0,1 210,310"
            fill="none"
            stroke="#EA580C"
            strokeWidth="2.5"
          />
          <path
            d="M 210,190 A 60,60 0 0,0 210,310"
            fill="none"
            stroke="#EA580C"
            strokeWidth="2.5"
            strokeDasharray="6,6"
          />

          {/* Mathematically Correct NBA 3-Point Line: Corner lines to x=188 + Arc radius 237.5 from (60, 250) */}
          <path
            d="M 20,50 L 188,50 A 237.5,237.5 0 0,1 188,450 L 20,450"
            fill="none"
            stroke="#EA580C"
            strokeWidth="3"
          />

          {/* Restricted Area Arc (Radius 40 from Basket at 60, 250) */}
          <path
            d="M 60,210 A 40,40 0 0,1 60,290"
            fill="none"
            stroke="#EA580C"
            strokeWidth="2"
          />

          {/* Backboard & Rim */}
          <line x1="60" y1="220" x2="60" y2="280" stroke="#0F172A" strokeWidth="4" strokeLinecap="round" />
          <line x1="50" y1="250" x2="60" y2="250" stroke="#64748B" strokeWidth="3" />
          <circle cx="75" cy="250" r="9" fill="none" stroke="#EA580C" strokeWidth="3" />

          {/* ========================================================================= */}
          {/* RIGHT SIDE — TEAM 2 (BLUE ACCENTS) */}
          {/* ========================================================================= */}
          {/* Key / Paint Area (190 x 160) */}
          <rect
            x="730"
            y="170"
            width="190"
            height="160"
            fill="url(#paintBlue)"
            stroke="#2563EB"
            strokeWidth="2.5"
          />

          {/* Free Throw Circle (Radius 60, Center at 730, 250) */}
          <path
            d="M 730,190 A 60,60 0 0,0 730,310"
            fill="none"
            stroke="#2563EB"
            strokeWidth="2.5"
          />
          <path
            d="M 730,190 A 60,60 0 0,1 730,310"
            fill="none"
            stroke="#2563EB"
            strokeWidth="2.5"
            strokeDasharray="6,6"
          />

          {/* Mathematically Correct NBA 3-Point Line: Corner lines to x=752 + Arc radius 237.5 from (880, 250) */}
          <path
            d="M 920,50 L 752,50 A 237.5,237.5 0 0,0 752,450 L 920,450"
            fill="none"
            stroke="#2563EB"
            strokeWidth="3"
          />

          {/* Restricted Area Arc (Radius 40 from Basket at 880, 250) */}
          <path
            d="M 880,210 A 40,40 0 0,0 880,290"
            fill="none"
            stroke="#2563EB"
            strokeWidth="2"
          />

          {/* Backboard & Rim */}
          <line x1="880" y1="220" x2="880" y2="280" stroke="#0F172A" strokeWidth="4" strokeLinecap="round" />
          <line x1="880" y1="250" x2="890" y2="250" stroke="#64748B" strokeWidth="3" />
          <circle cx="865" cy="250" r="9" fill="none" stroke="#2563EB" strokeWidth="3" />
        </svg>

        {/* ========================================================================= */}
        {/* INTERACTIVE PLAYER POSITION NODES OVERLAY */}
        {/* ========================================================================= */}

        {/* TEAM 1 (LOCAL - ORANGE) NODES */}
        {POSITIONS_T1.map((p) => {
          const slot = getSlot(team1Slots, p.pos);
          return (
            <div
              key={`t1-${p.pos}`}
              className="absolute -translate-x-1/2 -translate-y-1/2 transform transition-all duration-300 z-10"
              style={{ left: `${p.x}%`, top: `${p.y}%` }}
            >
              {slot ? (
                /* Occupied Slot Card */
                <div className="group relative flex flex-col items-center">
                  <div
                    onClick={() => onSlotClick(1, p.pos, slot)}
                    className="relative flex h-14 w-14 sm:h-16 sm:w-16 cursor-pointer items-center justify-center rounded-2xl border-2 bg-white shadow-md transition-transform hover:scale-110 active:scale-95 overflow-hidden"
                    style={{ borderColor: slot.archetype_color || "#EA580C" }}
                  >
                    <Image
                      src={slot.headshot_url}
                      alt={slot.player_name}
                      fill
                      className="object-cover object-top"
                      unoptimized
                    />
                    <span className="absolute top-0.5 left-0.5 rounded bg-orange-600 px-1 text-[8px] font-mono font-black text-white shadow-xs">
                      {p.pos}
                    </span>
                    {slot.is_best_season && (
                      <span className="absolute top-0.5 right-0.5 rounded bg-amber-500 p-0.5 text-white shadow-xs" title="Peak Season">
                        <Star className="h-2.5 w-2.5 fill-white" />
                      </span>
                    )}
                  </div>

                  {/* Player mini label pill */}
                  <div className="mt-1 flex flex-col items-center">
                    <span className="max-w-[90px] truncate rounded-md bg-slate-900 px-1.5 py-0.5 text-[10px] font-black text-white shadow-xs">
                      {slot.player_name.split(" ").slice(-1)[0]}
                    </span>
                    <span className="text-[9px] font-mono font-bold text-orange-800">
                      {slot.season_label} • {slot.ppg}p
                    </span>
                  </div>

                  {/* Remove Button */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onRemovePlayer(1, p.pos);
                    }}
                    className="absolute -top-1.5 -right-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-rose-600 text-white shadow-md hover:bg-rose-700 transition"
                    title={isEs ? "Quitar jugador" : "Remove player"}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              ) : (
                /* Empty Slot Button */
                <button
                  onClick={() => onSlotClick(1, p.pos, null)}
                  className="group flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-orange-400/80 bg-orange-50/70 p-2 text-center shadow-xs backdrop-blur-xs transition hover:border-orange-600 hover:bg-white hover:scale-105 active:scale-95"
                >
                  <div className="flex h-10 w-10 sm:h-12 sm:w-12 items-center justify-center rounded-xl bg-orange-100 text-orange-700 transition group-hover:bg-orange-600 group-hover:text-white">
                    <Plus className="h-5 w-5" />
                  </div>
                  <span className="mt-0.5 text-[11px] font-mono font-black text-orange-950">
                    {p.pos}
                  </span>
                  <span className="hidden sm:block text-[9px] font-bold text-orange-700">
                    {isEs ? p.labelEs : p.labelEn}
                  </span>
                </button>
              )}
            </div>
          );
        })}

        {/* TEAM 2 (VISITANTE - BLUE) NODES */}
        {POSITIONS_T2.map((p) => {
          const slot = getSlot(team2Slots, p.pos);
          return (
            <div
              key={`t2-${p.pos}`}
              className="absolute -translate-x-1/2 -translate-y-1/2 transform transition-all duration-300 z-10"
              style={{ left: `${p.x}%`, top: `${p.y}%` }}
            >
              {slot ? (
                /* Occupied Slot Card */
                <div className="group relative flex flex-col items-center">
                  <div
                    onClick={() => onSlotClick(2, p.pos, slot)}
                    className="relative flex h-14 w-14 sm:h-16 sm:w-16 cursor-pointer items-center justify-center rounded-2xl border-2 bg-white shadow-md transition-transform hover:scale-110 active:scale-95 overflow-hidden"
                    style={{ borderColor: slot.archetype_color || "#2563EB" }}
                  >
                    <Image
                      src={slot.headshot_url}
                      alt={slot.player_name}
                      fill
                      className="object-cover object-top"
                      unoptimized
                    />
                    <span className="absolute top-0.5 left-0.5 rounded bg-blue-600 px-1 text-[8px] font-mono font-black text-white shadow-xs">
                      {p.pos}
                    </span>
                    {slot.is_best_season && (
                      <span className="absolute top-0.5 right-0.5 rounded bg-amber-500 p-0.5 text-white shadow-xs" title="Peak Season">
                        <Star className="h-2.5 w-2.5 fill-white" />
                      </span>
                    )}
                  </div>

                  {/* Player mini label pill */}
                  <div className="mt-1 flex flex-col items-center">
                    <span className="max-w-[90px] truncate rounded-md bg-slate-900 px-1.5 py-0.5 text-[10px] font-black text-white shadow-xs">
                      {slot.player_name.split(" ").slice(-1)[0]}
                    </span>
                    <span className="text-[9px] font-mono font-bold text-blue-800">
                      {slot.season_label} • {slot.ppg}p
                    </span>
                  </div>

                  {/* Remove Button */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onRemovePlayer(2, p.pos);
                    }}
                    className="absolute -top-1.5 -right-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-rose-600 text-white shadow-md hover:bg-rose-700 transition"
                    title={isEs ? "Quitar jugador" : "Remove player"}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              ) : (
                /* Empty Slot Button */
                <button
                  onClick={() => onSlotClick(2, p.pos, null)}
                  className="group flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-blue-400/80 bg-blue-50/70 p-2 text-center shadow-xs backdrop-blur-xs transition hover:border-blue-600 hover:bg-white hover:scale-105 active:scale-95"
                >
                  <div className="flex h-10 w-10 sm:h-12 sm:w-12 items-center justify-center rounded-xl bg-blue-100 text-blue-700 transition group-hover:bg-blue-600 group-hover:text-white">
                    <Plus className="h-5 w-5" />
                  </div>
                  <span className="mt-0.5 text-[11px] font-mono font-black text-blue-950">
                    {p.pos}
                  </span>
                  <span className="hidden sm:block text-[9px] font-bold text-blue-700">
                    {isEs ? p.labelEs : p.labelEn}
                  </span>
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
