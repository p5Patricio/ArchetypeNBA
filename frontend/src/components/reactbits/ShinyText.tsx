"use client";

import React from "react";

interface ShinyTextProps {
  text: string;
  disabled?: boolean;
  speed?: number;
  className?: string;
}

export function ShinyText({
  text,
  disabled = false,
  speed = 4,
  className = "",
}: ShinyTextProps) {
  const animationDuration = `${speed}s`;

  return (
    <span
      className={`inline-block bg-clip-text text-transparent ${
        disabled
          ? "text-slate-400"
          : "bg-gradient-to-r from-orange-400 via-white to-sky-400 animate-shine"
      } ${className}`}
      style={{
        backgroundSize: "200% 100%",
        animationDuration: animationDuration,
      }}
    >
      {text}
    </span>
  );
}
