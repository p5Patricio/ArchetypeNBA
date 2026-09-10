"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { Search, ArrowRight, X } from "lucide-react";
import { getPlayers, type PlayerListItem } from "@/lib/api";
import { PlayerAvatar } from "./PlayerAvatar";
import { usePreferences } from "@/context/PreferencesContext";

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  seasonId?: number | null;
}

export function CommandPalette({ isOpen, onClose, seasonId }: CommandPaletteProps) {
  const router = useRouter();
  const { t } = usePreferences();
  const [query, setQuery] = useState("");
  const [players, setPlayers] = useState<PlayerListItem[]>([]);
  const [filtered, setFiltered] = useState<PlayerListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        onClose();
      }
      if (e.key === "Escape" && isOpen) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  useEffect(() => {
    if (isOpen) {
      setLoading(true);
      getPlayers(undefined, seasonId || undefined)
        .then((data) => {
          setPlayers(data);
          setFiltered(data.slice(0, 10));
        })
        .catch(console.error)
        .finally(() => setLoading(false));

      setTimeout(() => {
        inputRef.current?.focus();
      }, 50);
    } else {
      setQuery("");
    }
  }, [isOpen, seasonId]);

  useEffect(() => {
    if (!query.trim()) {
      setFiltered(players.slice(0, 10));
    } else {
      const q = query.toLowerCase();
      const res = players.filter(
        (p) =>
          p.player_name.toLowerCase().includes(q) ||
          (p.team_name && p.team_name.toLowerCase().includes(q)) ||
          (p.team_abbreviation && p.team_abbreviation.toLowerCase().includes(q)) ||
          (p.role_name && p.role_name.toLowerCase().includes(q))
      );
      setFiltered(res.slice(0, 15));
    }
  }, [query, players]);

  if (!isOpen) return null;

  const handleSelect = (playerName: string) => {
    onClose();
    router.push(`/player/${encodeURIComponent(playerName)}`);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-20 px-4 bg-slate-900/40 backdrop-blur-xs animate-in fade-in duration-150"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search Bar */}
        <div className="relative flex items-center border-b border-slate-100 px-4 py-3.5 bg-slate-50/50">
          <Search className="h-5 w-5 text-orange-500 mr-3 shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("cmd_placeholder")}
            className="w-full bg-transparent text-sm font-medium text-slate-900 placeholder:text-slate-400 outline-none"
          />
          {query && (
            <button
              onClick={() => setQuery("")}
              className="rounded-lg p-1 text-slate-400 hover:text-slate-600"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        {/* Results List */}
        <div className="max-h-96 overflow-y-auto p-2 space-y-1">
          {loading ? (
            <div className="py-8 text-center text-xs text-slate-500">
              {t("cmd_loading")}
            </div>
          ) : filtered.length === 0 ? (
            <div className="py-8 text-center text-xs text-slate-500">
              {t("cmd_no_results", { query })}
            </div>
          ) : (
            filtered.map((player) => (
              <button
                key={player.player_id}
                onClick={() => handleSelect(player.player_name)}
                className="group flex w-full items-center justify-between rounded-xl px-3 py-2 text-left transition hover:bg-orange-50/70"
              >
                <div className="flex items-center gap-3">
                  <PlayerAvatar
                    playerId={player.player_id}
                    playerName={player.player_name}
                    headshotUrl={player.headshot_url}
                    size={36}
                  />
                  <div>
                    <div className="text-sm font-bold text-slate-900 group-hover:text-orange-600 transition">
                      {player.player_name}
                    </div>
                    <div className="flex items-center gap-2 text-xs text-slate-500">
                      <span>{player.team_name || player.team_abbreviation || "NBA"}</span>
                      {player.role_name && (
                        <>
                          <span>•</span>
                          <span className="text-sky-600 font-semibold">{player.role_name}</span>
                        </>
                      )}
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <div className="text-right font-mono text-xs">
                    <span className="text-slate-900 font-bold">{player.pts ? player.pts.toFixed(1) : 0}</span>{" "}
                    <span className="text-slate-400 font-semibold">PPG</span>
                  </div>
                  <ArrowRight className="h-4 w-4 text-slate-300 group-hover:text-orange-500 transition" />
                </div>
              </button>
            ))
          )}
        </div>

        {/* Footer info */}
        <div className="flex items-center justify-between border-t border-slate-100 bg-slate-50 px-4 py-2 text-[11px] text-slate-500">
          <span>{t("cmd_hint")}</span>
          <kbd className="rounded border border-slate-200 bg-white px-1.5 py-0.5 font-mono text-[10px] shadow-xs">
            {t("cmd_close")}
          </kbd>
        </div>
      </div>
    </div>
  );
}
