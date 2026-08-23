"use client";

import React, { useState } from "react";
import Image from "next/image";

interface TeamLogoProps {
  teamId?: number;
  abbreviation: string;
  teamName?: string;
  size?: number;
  className?: string;
}

export function TeamLogo({
  teamId,
  abbreviation,
  teamName = "NBA Team",
  size = 40,
  className = "",
}: TeamLogoProps) {
  const [srcIndex, setSrcIndex] = useState(0);

  const abbrLower = (abbreviation || "nba").toLowerCase();
  
  // High-resolution CDN sources in order of preference
  const sources = [
    // Official NBA SVG Vector CDN
    teamId ? `https://cdn.nba.com/logos/nba/${teamId}/primary/L/logo.svg` : null,
    // Official NBA Global SVG
    teamId ? `https://cdn.nba.com/logos/nba/${teamId}/global/L/logo.svg` : null,
    // ESPN 500x500 PNG CDN
    `https://a.espncdn.com/i/teamlogos/nba/500/${abbrLower}.png`,
    // Sports Illustrated / Wikipedia fallback
    `https://cdn.ssref.net/req/202404171/tlogo/bbr/${abbreviation.toUpperCase()}.png`,
  ].filter(Boolean) as string[];

  const currentSrc = sources[srcIndex] || null;

  if (!currentSrc || srcIndex >= sources.length) {
    return (
      <div
        className={`flex items-center justify-center rounded-xl bg-slate-100 font-mono font-black text-slate-700 select-none shadow-2xs ${className}`}
        style={{ width: size, height: size, fontSize: Math.max(size * 0.32, 10) }}
      >
        {abbreviation.toUpperCase()}
      </div>
    );
  }

  return (
    <div
      className={`relative shrink-0 flex items-center justify-center select-none overflow-hidden ${className}`}
      style={{ width: size, height: size }}
    >
      <Image
        src={currentSrc}
        alt={`${teamName} Logo`}
        width={size}
        height={size}
        className="object-contain w-full h-full transition-transform hover:scale-105"
        onError={() => setSrcIndex((prev) => prev + 1)}
        unoptimized
      />
    </div>
  );
}
