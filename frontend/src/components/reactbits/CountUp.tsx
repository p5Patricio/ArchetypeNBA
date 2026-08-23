"use client";

import { useEffect, useRef, useState } from "react";

interface CountUpProps {
  to: number;
  from?: number;
  direction?: "up" | "down";
  delay?: number;
  duration?: number;
  className?: string;
  decimals?: number;
  prefix?: string;
  suffix?: string;
}

export function CountUp({
  to,
  from = 0,
  direction = "up",
  delay = 0,
  duration = 1.5,
  className = "",
  decimals = 0,
  prefix = "",
  suffix = "",
}: CountUpProps) {
  const [count, setCount] = useState<number>(from);
  const countRef = useRef<number>(from);
  const startTimeRef = useRef<number | null>(null);

  useEffect(() => {
    let animationFrameId: number;
    let timeoutId: any;

    const startAnimation = () => {
      const step = (timestamp: number) => {
        if (!startTimeRef.current) startTimeRef.current = timestamp;
        const progress = Math.min((timestamp - startTimeRef.current) / (duration * 1000), 1);
        
        // Ease out quad
        const easeOut = 1 - Math.pow(1 - progress, 3);
        const currentCount = from + (to - from) * easeOut;

        setCount(currentCount);
        countRef.current = currentCount;

        if (progress < 1) {
          animationFrameId = requestAnimationFrame(step);
        } else {
          setCount(to);
        }
      };

      animationFrameId = requestAnimationFrame(step);
    };

    timeoutId = setTimeout(() => {
      startTimeRef.current = null;
      startAnimation();
    }, delay * 1000);

    return () => {
      if (timeoutId) clearTimeout(timeoutId);
      if (animationFrameId) cancelAnimationFrame(animationFrameId);
    };
  }, [to, from, duration, delay]);

  const formattedCount = count.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });

  return (
    <span className={`inline-block tabular-nums ${className}`}>
      {prefix}
      {formattedCount}
      {suffix}
    </span>
  );
}
