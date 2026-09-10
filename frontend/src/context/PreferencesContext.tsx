"use client";

import React, { createContext, useContext, useState, useEffect } from "react";
import { translations, type Language, type UnitSystem } from "@/lib/translations";
import { getSeasons, type SeasonItem } from "@/lib/api";

interface PreferencesContextType {
  language: Language;
  setLanguage: (lang: Language) => void;
  unitSystem: UnitSystem;
  setUnitSystem: (units: UnitSystem) => void;
  seasonId: number | null;
  seasonLabel: string;
  setSeason: (seasonId: number, seasonLabel?: string) => void;
  seasons: SeasonItem[];
  t: (key: keyof typeof translations.es, params?: Record<string, string | number>) => string;
  formatHeight: (heightStr?: string | null, heightCm?: number | null) => string;
  formatWeight: (weightStr?: string | number | null, weightKg?: number | null) => string;
}

const PreferencesContext = createContext<PreferencesContextType | undefined>(undefined);

export function PreferencesProvider({ children }: { children: React.ReactNode }) {
  const [language, setLanguageState] = useState<Language>("es");
  const [unitSystem, setUnitSystemState] = useState<UnitSystem>("metric");
  const [seasons, setSeasons] = useState<SeasonItem[]>([]);
  const [seasonId, setSeasonId] = useState<number | null>(3);
  const [seasonLabel, setSeasonLabel] = useState<string>("2025-26");

  useEffect(() => {
    try {
      const savedLang = localStorage.getItem("archetype_nba_lang") as Language;
      if (savedLang === "es" || savedLang === "en") {
        setLanguageState(savedLang);
      }
      const savedUnits = localStorage.getItem("archetype_nba_units") as UnitSystem;
      if (savedUnits === "metric" || savedUnits === "imperial") {
        setUnitSystemState(savedUnits);
      }
    } catch {
      // ignore storage errors
    }
  }, []);

  useEffect(() => {
    let attempts = 0;
    let cancelled = false;

    const fetchSeasons = () => {
      getSeasons()
        .then((data) => {
          if (cancelled) return;
          if (data && data.length > 0) {
            setSeasons(data);
            const active = data.find((s) => s.is_active) || data[0];
            setSeasonId(active.id);
            setSeasonLabel(active.season_label);
          }
        })
        .catch((err) => {
          if (cancelled) return;
          console.warn("Backend still warming up, retrying seasons load...", err);
          if (attempts < 5) {
            attempts++;
            setTimeout(fetchSeasons, 1500);
          }
        });
    };

    fetchSeasons();
    return () => {
      cancelled = true;
    };
  }, []);

  const setSeason = (sId: number, sLabel?: string) => {
    setSeasonId(sId);
    if (sLabel) {
      setSeasonLabel(sLabel);
    } else {
      const match = seasons.find((s) => s.id === sId);
      if (match) setSeasonLabel(match.season_label);
    }
  };

  const setLanguage = (lang: Language) => {
    setLanguageState(lang);
    try {
      localStorage.setItem("archetype_nba_lang", lang);
    } catch {}
  };

  const setUnitSystem = (units: UnitSystem) => {
    setUnitSystemState(units);
    try {
      localStorage.setItem("archetype_nba_units", units);
    } catch {}
  };

  const t = (key: keyof typeof translations.es, params?: Record<string, string | number>): string => {
    const dict = translations[language] || translations.es;
    let text = dict[key] || translations.es[key] || String(key);
    if (params) {
      Object.entries(params).forEach(([paramKey, paramVal]) => {
        text = text.replace(new RegExp(`\\{${paramKey}\\}`, "g"), String(paramVal));
      });
    }
    return text;
  };

  const formatHeight = (heightStr?: string | null, heightCm?: number | null): string => {
    if (!heightStr && !heightCm) return "-";

    // Parse feet and inches from heightStr (e.g. "6-7", "6'7\"", "6-11", "7-4")
    let totalInches = 0;
    if (heightStr) {
      const parts = heightStr.replace(/"/g, "").replace(/'/g, "-").split("-").map(Number);
      if (parts.length >= 2 && !isNaN(parts[0]) && !isNaN(parts[1])) {
        totalInches = parts[0] * 12 + parts[1];
      } else if (parts.length === 1 && !isNaN(parts[0])) {
        totalInches = parts[0] * 12;
      }
    }

    if (unitSystem === "metric") {
      if (heightCm && heightCm > 50) {
        return `${Math.round(heightCm)} cm`;
      }
      if (totalInches > 0) {
        const cm = Math.round(totalInches * 2.54);
        return `${cm} cm`;
      }
      return heightStr ? `${heightStr}` : "-";
    } else {
      // Imperial
      if (totalInches > 0) {
        const ft = Math.floor(totalInches / 12);
        const inc = totalInches % 12;
        return `${ft}'${inc}"`;
      }
      if (heightCm && heightCm > 50) {
        const inches = heightCm / 2.54;
        const ft = Math.floor(inches / 12);
        const inc = Math.round(inches % 12);
        return `${ft}'${inc}"`;
      }
      return heightStr || "-";
    }
  };

  const formatWeight = (weightStr?: string | number | null, weightKg?: number | null): string => {
    if (!weightStr && !weightKg) return "-";

    let lbs = 0;
    if (typeof weightStr === "number") {
      lbs = weightStr;
    } else if (typeof weightStr === "string") {
      lbs = parseFloat(weightStr.replace(/[^0-9.]/g, "")) || 0;
    }

    if (unitSystem === "metric") {
      if (weightKg && weightKg > 20) {
        return `${Math.round(weightKg)} kg`;
      }
      if (lbs > 0) {
        const kg = Math.round(lbs * 0.45359237);
        return `${kg} kg`;
      }
      return weightStr ? `${weightStr}` : "-";
    } else {
      // Imperial
      if (lbs > 0) {
        return `${Math.round(lbs)} lbs`;
      }
      if (weightKg && weightKg > 20) {
        const calculatedLbs = Math.round(weightKg / 0.45359237);
        return `${calculatedLbs} lbs`;
      }
      return weightStr ? `${weightStr} lbs` : "-";
    }
  };

  return (
    <PreferencesContext.Provider
      value={{
        language,
        setLanguage,
        unitSystem,
        setUnitSystem,
        seasonId,
        seasonLabel,
        setSeason,
        seasons,
        t,
        formatHeight,
        formatWeight,
      }}
    >
      {children}
    </PreferencesContext.Provider>
  );
}

export function usePreferences() {
  const context = useContext(PreferencesContext);
  if (!context) {
    throw new Error("usePreferences must be used within a PreferencesProvider");
  }
  return context;
}
