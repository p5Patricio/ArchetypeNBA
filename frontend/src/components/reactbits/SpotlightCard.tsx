"use client";

import React, { useRef, useState } from "react";

interface SpotlightCardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
  className?: string;
  spotlightColor?: string;
}

export function SpotlightCard({
  children,
  className = "",
  spotlightColor = "rgba(255, 107, 0, 0.12)",
  ...props
}: SpotlightCardProps) {
  const cardRef = useRef<HTMLDivElement>(null);
  const [isHovered, setIsHovered] = useState(false);

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!cardRef.current) return;
    const rect = cardRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    cardRef.current.style.setProperty("--mouse-x", `${x}px`);
    cardRef.current.style.setProperty("--mouse-y", `${y}px`);
  };

  return (
    <div
      ref={cardRef}
      onMouseMove={handleMouseMove}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      className={`group relative overflow-hidden rounded-2xl border border-white/[0.08] bg-[#0c0e12]/90 backdrop-blur-md shadow-xl transition-all duration-300 hover:border-orange-500/30 hover:shadow-2xl hover:shadow-orange-500/5 ${className}`}
      {...props}
    >
      {/* Dynamic Cursor Spotlight */}
      <div
        className="pointer-events-none absolute -inset-px opacity-0 transition-opacity duration-300 group-hover:opacity-100"
        style={{
          background: `radial-gradient(400px circle at var(--mouse-x, 50%) var(--mouse-y, 50%), ${spotlightColor}, transparent 50%)`,
        }}
      />
      {/* Top subtle highlight line */}
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/15 to-transparent" />
      
      <div className="relative z-10">{children}</div>
    </div>
  );
}
