"use client";

import React, { useState } from "react";
import Image from "next/image";
import { User } from "lucide-react";

interface PlayerAvatarProps {
  playerId?: number | string;
  playerName: string;
  headshotUrl?: string | null;
  className?: string;
  size?: number;
  priority?: boolean;
}

export function PlayerAvatar({
  playerId,
  playerName,
  headshotUrl,
  className = "",
  size = 56,
  priority = false,
}: PlayerAvatarProps) {
  const [srcIndex, setSrcIndex] = useState(0);

  // Compute initials
  const initials = playerName
    ? playerName
        .split(" ")
        .map((n) => n[0])
        .filter(Boolean)
        .slice(0, 2)
        .join("")
        .toUpperCase()
    : "NBA";

  // Tiered CDN sources for NBA headshots
  const sources = [
    headshotUrl || null,
    playerId ? `https://cdn.nba.com/headshots/nba/latest/1040x760/${playerId}.png` : null,
    playerId ? `https://cdn.nba.com/headshots/nba/latest/260x190/${playerId}.png` : null,
    playerId ? `https://ak-static.cms.nba.com/wp-content/uploads/headshots/nba/latest/260x190/${playerId}.png` : null,
  ].filter(Boolean) as string[];

  const currentSrc = sources[srcIndex] || null;

  if (!currentSrc || srcIndex >= sources.length) {
    return (
      <div
        className={`flex items-center justify-center rounded-2xl border border-slate-200 bg-gradient-to-br from-orange-100/70 via-slate-50 to-sky-100/70 text-slate-800 font-extrabold shadow-2xs shrink-0 select-none ${className}`}
        style={{ width: size, height: size }}
      >
        {initials ? (
          <span
            className="font-mono font-black tracking-tight text-slate-800"
            style={{ fontSize: Math.max(size * 0.36, 11) }}
          >
            {initials}
          </span>
        ) : (
          <User className="text-slate-400" style={{ width: size * 0.4, height: size * 0.4 }} />
        )}
      </div>
    );
  }

  return (
    <div
      className={`relative overflow-hidden rounded-2xl border border-slate-200/80 bg-slate-100/80 shadow-2xs shrink-0 select-none ${className}`}
      style={{ width: size, height: size }}
    >
      <Image
        src={currentSrc}
        alt={playerName}
        fill
        sizes={`${size}px`}
        priority={priority}
        className="object-cover object-top transition-transform hover:scale-105"
        onError={() => setSrcIndex((prev) => prev + 1)}
        unoptimized
      />
    </div>
  );
}
