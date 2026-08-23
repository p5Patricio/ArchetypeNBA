"use client";

import { useEffect, useState, useRef } from "react";

interface DecryptedTextProps {
  text: string;
  speed?: number;
  maxIterations?: number;
  sequential?: boolean;
  revealDirection?: "start" | "end" | "center";
  useOriginalCharsOnly?: boolean;
  characters?: string;
  className?: string;
  parentClassName?: string;
  encryptedClassName?: string;
  animateOn?: "view" | "hover";
}

export function DecryptedText({
  text,
  speed = 50,
  maxIterations = 10,
  sequential = true,
  characters = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!@#$%^&*()_+",
  className = "",
  parentClassName = "",
  encryptedClassName = "text-sky-400 opacity-80",
  animateOn = "view",
}: DecryptedTextProps) {
  const [displayText, setDisplayText] = useState<string>(text);
  const [isHovering, setIsHovering] = useState<boolean>(false);
  const [isScrambling, setIsScrambling] = useState<boolean>(false);
  const [revealedIndices, setRevealedIndices] = useState<Set<number>>(new Set());
  const containerRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    let interval: any;
    let currentIteration = 0;

    const getNextChar = (char: string) => {
      if (char === " ") return " ";
      return characters[Math.floor(Math.random() * characters.length)];
    };

    const scramble = () => {
      setIsScrambling(true);
      interval = setInterval(() => {
        setDisplayText((prevText) => {
          const nextText = text
            .split("")
            .map((char, index) => {
              if (char === " ") return " ";
              if (revealedIndices.has(index)) return text[index];
              return getNextChar(char);
            })
            .join("");

          return nextText;
        });

        currentIteration++;

        if (sequential) {
          setRevealedIndices((prev) => {
            const next = new Set(prev);
            for (let i = 0; i <= currentIteration; i++) {
              next.add(i);
            }
            return next;
          });

          if (currentIteration >= text.length) {
            clearInterval(interval);
            setIsScrambling(false);
            setDisplayText(text);
          }
        } else {
          if (currentIteration >= maxIterations) {
            clearInterval(interval);
            setIsScrambling(false);
            setDisplayText(text);
          }
        }
      }, speed);
    };

    if (animateOn === "view") {
      setRevealedIndices(new Set());
      currentIteration = 0;
      scramble();
    } else if (animateOn === "hover" && isHovering) {
      setRevealedIndices(new Set());
      currentIteration = 0;
      scramble();
    } else {
      setDisplayText(text);
    }

    return () => {
      if (interval) clearInterval(interval);
    };
  }, [text, isHovering, animateOn, speed, maxIterations, sequential, characters]);

  return (
    <span
      ref={containerRef}
      className={`inline-block ${parentClassName}`}
      onMouseEnter={() => setIsHovering(true)}
      onMouseLeave={() => setIsHovering(false)}
    >
      <span className={className}>
        {displayText.split("").map((char, i) => {
          const isRevealed = revealedIndices.has(i) || !isScrambling;
          return (
            <span
              key={i}
              className={isRevealed ? "" : encryptedClassName}
            >
              {char}
            </span>
          );
        })}
      </span>
    </span>
  );
}
