"use client";

import React from "react";
import { useRouter } from "next/navigation";
import { usePreferences } from "@/context/PreferencesContext";
import { APP_MODES, MODE_THEME, homeForMode, type AppMode } from "@/lib/modes";

interface ModeToggleProps {
  className?: string;
  /** Fill the available width (mobile drawer). */
  fullWidth?: boolean;
  /** Called after a switch, e.g. to close the mobile drawer. */
  onSwitched?: () => void;
}

/**
 * Segmented control that switches between NBA Analytics and Betting (paper trading).
 * Switching always navigates to the home of the chosen mode.
 */
export function ModeToggle({ className = "", fullWidth = false, onSwitched }: ModeToggleProps) {
  const router = useRouter();
  const { mode, setMode, language, t } = usePreferences();

  const handleSelect = (next: AppMode) => {
    setMode(next);
    router.push(homeForMode(next));
    if (onSwitched) onSwitched();
  };

  return (
    <div
      role="group"
      aria-label={t("mode_switch_label")}
      className={`inline-flex items-center rounded-xl border border-slate-200 bg-slate-100 p-0.5 shadow-2xs ${
        fullWidth ? "flex w-full" : ""
      } ${className}`}
    >
      {APP_MODES.map((m) => {
        const theme = MODE_THEME[m];
        const Icon = theme.icon;
        const active = mode === m;
        return (
          <button
            key={m}
            type="button"
            onClick={() => handleSelect(m)}
            aria-pressed={active}
            title={theme.label[language]}
            className={`flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-black transition cursor-pointer outline-none focus-visible:ring-2 ${theme.focusRing} ${
              fullWidth ? "flex-1" : ""
            } ${active ? theme.activeSegment : "text-slate-500 hover:text-slate-900"}`}
          >
            <Icon className="h-3.5 w-3.5 shrink-0" />
            <span className="whitespace-nowrap">{theme.shortLabel[language]}</span>
          </button>
        );
      })}
    </div>
  );
}
