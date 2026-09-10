"use client";

import { useEffect, useState } from "react";
import { getSeasons, type SeasonItem } from "@/lib/api";

interface SeasonSelectProps {
  value?: number | null;
  onChange: (seasonId: number, seasonLabel?: string) => void;
  className?: string;
}

export function SeasonSelect({ value, onChange, className = "" }: SeasonSelectProps) {
  const [seasons, setSeasons] = useState<SeasonItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    getSeasons()
      .then((data) => {
        if (mounted && data && data.length > 0) {
          setSeasons(data);
          const active = data.find((s) => s.is_active) || data[0];
          // If value is not yet set or not in list, select active or first
          if (!value || !data.some((s) => s.id === value)) {
            onChange(active.id, active.season_label);
          }
        }
      })
      .catch((err) => {
        console.error("Error loading seasons:", err);
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  return (
    <div className={`inline-flex items-center gap-2 ${className}`}>
      <label className="text-xs font-semibold uppercase tracking-wider text-slate-400">
        Temporada:
      </label>
      <select
        value={value ?? ""}
        onChange={(e) => {
          const sId = Number(e.target.value);
          const item = seasons.find((s) => s.id === sId);
          onChange(sId, item?.season_label);
        }}
        disabled={loading || seasons.length === 0}
        className="rounded-lg border border-sky-500/30 bg-slate-900/90 px-3 py-1.5 text-sm font-medium text-sky-300 shadow-inner outline-none transition hover:border-sky-400 focus:border-sky-400 focus:ring-1 focus:ring-sky-400 disabled:opacity-50"
      >
        {loading ? (
          <option value="">Cargando temporadas...</option>
        ) : seasons.length === 0 ? (
          <option value="">Sin temporadas</option>
        ) : (
          seasons.map((s) => (
            <option key={`${s.id}-${s.season_label}`} value={s.id} className="bg-slate-900 text-white">
              {s.season_label} ({s.players_count} jugadores)
            </option>
          ))
        )}
      </select>
    </div>
  );
}
