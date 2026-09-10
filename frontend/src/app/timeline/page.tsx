"use client";

import React, { useEffect, useState, useMemo } from "react";
import {
  History,
  Trophy,
  Flame,
  Shirt,
  Swords,
  Crown,
  Scale,
  Search,
  Sparkles,
  Calendar,
  AlertTriangle,
  ChevronRight,
  Info,
  X,
  ExternalLink,
  BookOpen,
  Filter,
} from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { CommandPalette } from "@/components/CommandPalette";
import { usePreferences } from "@/context/PreferencesContext";
import { getTimeline, type TimelineEra, type TimelineEvent, type TimelineResponse } from "@/lib/api";

export default function TimelinePage() {
  const { t, language } = usePreferences();
  const [timelineData, setTimelineData] = useState<TimelineResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedEra, setSelectedEra] = useState<string>("all");
  const [selectedCategory, setSelectedCategory] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [activeModalEvent, setActiveModalEvent] = useState<TimelineEvent | null>(null);
  const [isCommandOpen, setIsCommandOpen] = useState<boolean>(false);

  useEffect(() => {
    setLoading(true);
    getTimeline()
      .then((data) => {
        setTimelineData(data);
        setError(null);
      })
      .catch((err) => {
        console.error("Failed to load timeline:", err);
        setError(err.message || "Failed to load timeline data");
      })
      .finally(() => setLoading(false));
  }, []);

  // Filter events locally for speed
  const filteredEvents = useMemo(() => {
    if (!timelineData) return [];
    let list = timelineData.events;

    if (selectedEra !== "all") {
      list = list.filter((e) => e.era_id === selectedEra);
    }

    if (selectedCategory !== "all") {
      list = list.filter((e) => e.category === selectedCategory);
    }

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim();
      list = list.filter((e) => {
        const title = (language === "es" ? e.title_es : e.title_en).toLowerCase();
        const headline = (language === "es" ? e.headline_es : e.headline_en).toLowerCase();
        const desc = (language === "es" ? e.description_es : e.description_en).toLowerCase();
        const actors = e.key_actors.some((a) => a.toLowerCase().includes(q));
        const tags = e.tags.some((tg) => tg.toLowerCase().includes(q));
        const year = String(e.year);
        return title.includes(q) || headline.includes(q) || desc.includes(q) || actors || tags || year.includes(q);
      });
    }

    return list;
  }, [timelineData, selectedEra, selectedCategory, searchQuery, language]);

  // Group filtered events by era
  const groupedEventsByEra = useMemo(() => {
    if (!timelineData) return [];
    const erasMap = new Map<string, { era: TimelineEra; events: TimelineEvent[] }>();

    timelineData.eras.forEach((era) => {
      erasMap.set(era.id, { era, events: [] });
    });

    filteredEvents.forEach((evt) => {
      const group = erasMap.get(evt.era_id);
      if (group) {
        group.events.push(evt);
      }
    });

    // Only return eras that have matching events
    return Array.from(erasMap.values()).filter((g) => g.events.length > 0);
  }, [timelineData, filteredEvents]);

  // Icon resolver
  const renderCategoryIcon = (iconType: string, className: string = "h-4 w-4") => {
    switch (iconType) {
      case "flame":
        return <Flame className={className} />;
      case "shirt":
        return <Shirt className={className} />;
      case "sword":
        return <Swords className={className} />;
      case "crown":
        return <Crown className={className} />;
      case "scale":
        return <Scale className={className} />;
      case "trophy":
      default:
        return <Trophy className={className} />;
    }
  };

  // Severity & category badge color mapping
  const getSeverityBadge = (event: TimelineEvent) => {
    if (event.severity === "suspension") {
      return (
        <span className="inline-flex items-center gap-1 rounded-md border border-rose-300 bg-rose-50 px-2 py-0.5 text-[11px] font-black text-rose-700 uppercase tracking-wider">
          <AlertTriangle className="h-3 w-3" />
          {event.media_badge || (language === "es" ? "Suspensión Histórica" : "Historic Suspension")}
        </span>
      );
    }
    if (event.severity === "fine") {
      return (
        <span className="inline-flex items-center gap-1 rounded-md border border-amber-300 bg-amber-50 px-2 py-0.5 text-[11px] font-black text-amber-800 uppercase tracking-wider">
          <Scale className="h-3 w-3" />
          {event.media_badge || (language === "es" ? "Multa Oficial" : "Official Fine")}
        </span>
      );
    }
    if (event.severity === "controversy") {
      return (
        <span className="inline-flex items-center gap-1 rounded-md border border-orange-300 bg-orange-50 px-2 py-0.5 text-[11px] font-black text-orange-800 uppercase tracking-wider">
          <Flame className="h-3 w-3" />
          {event.media_badge || (language === "es" ? "Controversia" : "Controversy")}
        </span>
      );
    }
    if (event.severity === "revolution") {
      return (
        <span className="inline-flex items-center gap-1 rounded-md border border-purple-300 bg-purple-50 px-2 py-0.5 text-[11px] font-black text-purple-800 uppercase tracking-wider">
          <Sparkles className="h-3 w-3" />
          {event.media_badge || (language === "es" ? "Revolución de Reglas" : "Rule Revolution")}
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-blue-200 bg-blue-50 px-2 py-0.5 text-[11px] font-black text-blue-700 uppercase tracking-wider">
        <Trophy className="h-3 w-3" />
        {event.media_badge || (language === "es" ? "Hito Histórico" : "Historic Feat")}
      </span>
    );
  };

  const getCategoryLabel = (catId: string) => {
    switch (catId) {
      case "scandals_brawls":
        return language === "es" ? "Peleas & Sanciones" : "Brawls & Fines";
      case "culture_rules":
        return language === "es" ? "Cultura & Reglas" : "Culture & Rules";
      case "legendary_games":
        return language === "es" ? "Partidos Míticos" : "Legendary Games";
      case "dynasties":
        return language === "es" ? "Dinastías" : "Dynasties";
      case "milestones":
      default:
        return language === "es" ? "Hazañas & Récords" : "Feats & Records";
    }
  };

  return (
    <div className="min-h-screen bg-[#F8FAFC] text-slate-900 selection:bg-orange-100 selection:text-orange-900">
      <Navbar onOpenSearch={() => setIsCommandOpen(true)} />
      <CommandPalette isOpen={isCommandOpen} onClose={() => setIsCommandOpen(false)} />

      <main className="md:pl-64">
        {/* HERO SECTION */}
        <section className="relative border-b border-slate-200 bg-gradient-to-b from-blue-50/50 via-white to-white py-12 lg:py-16 shadow-xs">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="flex flex-col items-center text-center space-y-4">
              
              {/* Top Historical Badge */}
              <div className="inline-flex items-center gap-2 rounded-full border border-blue-200 bg-white/80 px-4 py-1.5 text-xs font-black tracking-wide text-blue-800 shadow-2xs">
                <History className="h-3.5 w-3.5 text-blue-600 animate-pulse" />
                <span>1946 — 2026 • 80 AÑOS DE HISTORIA OFICIAL NBA</span>
              </div>

              {/* Main Headline */}
              <h1 className="max-w-4xl text-3xl sm:text-5xl font-black tracking-tight text-slate-900 leading-tight">
                {t("timeline_page_title")}
              </h1>

              {/* Subtitle */}
              <p className="max-w-3xl text-sm sm:text-base text-slate-600 font-normal leading-relaxed">
                {t("timeline_page_subtitle")}
              </p>

              {/* Search Bar */}
              <div className="w-full max-w-xl pt-2">
                <div className="relative flex items-center rounded-2xl border-2 border-slate-200 bg-white p-1.5 shadow-sm transition focus-within:border-blue-500 focus-within:ring-4 focus-within:ring-blue-500/10">
                  <Search className="ml-3 h-5 w-5 text-blue-500 shrink-0" />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder={t("timeline_search_placeholder")}
                    className="w-full bg-transparent px-3 py-2 text-sm font-medium text-slate-900 placeholder:text-slate-400 outline-none"
                  />
                  {searchQuery && (
                    <button
                      onClick={() => setSearchQuery("")}
                      className="mr-2 rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  )}
                </div>
              </div>

              {/* Live Count Indicator */}
              <div className="text-xs font-bold text-slate-500 pt-1">
                {t("timeline_events_found", { count: filteredEvents.length })}
              </div>
            </div>
          </div>
        </section>

        {/* CONTROLS BAR: ERAS & CATEGORIES */}
        <section className="sticky top-16 z-20 border-b border-slate-200 bg-white/95 backdrop-blur-md px-4 py-3 sm:px-6 lg:px-8 shadow-xs">
          <div className="mx-auto max-w-7xl space-y-3">
            
            {/* Category Tabs Pill Bar */}
            <div className="flex items-center gap-2 overflow-x-auto pb-1 scrollbar-none">
              <span className="text-xs font-black uppercase text-slate-400 shrink-0 flex items-center gap-1 pl-1">
                <Filter className="h-3 w-3" />
                {t("timeline_category_label")}:
              </span>

              {timelineData?.categories.map((cat) => {
                const isSelected = selectedCategory === cat.id;
                return (
                  <button
                    key={cat.id}
                    onClick={() => setSelectedCategory(cat.id)}
                    className={`rounded-xl px-3.5 py-1.5 text-xs font-extrabold whitespace-nowrap transition shadow-2xs ${
                      isSelected
                        ? "bg-slate-900 text-white shadow-xs scale-102"
                        : "bg-slate-100 text-slate-600 hover:bg-slate-200 hover:text-slate-900"
                    }`}
                  >
                    {language === "es" ? cat.label_es : cat.label_en}
                  </button>
                );
              })}
            </div>

            {/* Eras Scrubber Bar */}
            <div className="flex items-center gap-2 overflow-x-auto pb-1 scrollbar-none border-t border-slate-100 pt-2">
              <span className="text-xs font-black uppercase text-slate-400 shrink-0 flex items-center gap-1 pl-1">
                <Calendar className="h-3 w-3" />
                {t("timeline_era_label")}:
              </span>

              <button
                onClick={() => setSelectedEra("all")}
                className={`rounded-lg px-3 py-1 text-xs font-bold whitespace-nowrap transition ${
                  selectedEra === "all"
                    ? "bg-blue-600 text-white font-black shadow-xs"
                    : "bg-slate-50 text-slate-600 hover:bg-slate-100"
                }`}
              >
                {t("timeline_all_eras")}
              </button>

              {timelineData?.eras.map((era) => {
                const isSelected = selectedEra === era.id;
                return (
                  <button
                    key={era.id}
                    onClick={() => setSelectedEra(era.id)}
                    className={`rounded-lg px-3 py-1 text-xs whitespace-nowrap transition border ${
                      isSelected
                        ? "bg-blue-50 border-blue-300 text-blue-900 font-black shadow-xs"
                        : "bg-white border-slate-200 text-slate-600 hover:border-slate-300 hover:text-slate-900"
                    }`}
                  >
                    <span className="font-mono font-bold mr-1 opacity-70">[{era.year_range}]</span>
                    {language === "es" ? era.name_es.split(":")[0] : era.name_en.split(":")[0]}
                  </button>
                );
              })}
            </div>

          </div>
        </section>

        {/* MAIN TIMELINE VIEW */}
        <section className="mx-auto max-w-5xl px-4 py-10 sm:px-6 lg:px-8">
          {loading && (
            <div className="flex flex-col items-center justify-center py-24 space-y-4">
              <div className="h-10 w-10 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
              <p className="text-sm font-bold text-slate-500">Cargando crónica histórica de la NBA...</p>
            </div>
          )}

          {error && !loading && (
            <div className="rounded-2xl border border-red-200 bg-red-50 p-6 text-center text-red-700">
              <p className="font-bold">Error al cargar datos históricos: {error}</p>
            </div>
          )}

          {!loading && !error && groupedEventsByEra.length === 0 && (
            <div className="rounded-2xl border border-slate-200 bg-white p-12 text-center shadow-xs">
              <History className="mx-auto h-12 w-12 text-slate-300 mb-3" />
              <h3 className="text-base font-bold text-slate-800">No se encontraron sucesos históricos</h3>
              <p className="text-xs text-slate-500 mt-1">
                Intentá ajustar los filtros de categoría o borrar el término de búsqueda.
              </p>
              <button
                onClick={() => {
                  setSelectedCategory("all");
                  setSelectedEra("all");
                  setSearchQuery("");
                }}
                className="mt-4 inline-flex items-center gap-1.5 rounded-xl bg-blue-600 px-4 py-2 text-xs font-bold text-white hover:bg-blue-700 shadow-2xs"
              >
                Restablecer todos los filtros
              </button>
            </div>
          )}

          {!loading && !error && groupedEventsByEra.map(({ era, events }) => (
            <div key={era.id} className="mb-16">
              
              {/* Era Header Marker */}
              <div className="sticky top-36 z-10 mb-8 rounded-2xl border-2 border-slate-200 bg-white/90 backdrop-blur-md p-4 sm:p-5 shadow-sm">
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 border-b border-slate-100 pb-3">
                  <div className="flex items-center gap-2.5">
                    <span
                      className="h-3.5 w-3.5 rounded-full ring-4 ring-blue-100"
                      style={{ backgroundColor: era.color }}
                    />
                    <h2 className="text-lg sm:text-xl font-black text-slate-900 tracking-tight">
                      {language === "es" ? era.name_es : era.name_en}
                    </h2>
                  </div>
                  <span className="inline-block rounded-lg bg-slate-100 px-3 py-1 font-mono text-xs font-black text-slate-700 self-start sm:self-auto">
                    {era.year_range}
                  </span>
                </div>
                <p className="text-xs sm:text-sm text-slate-600 mt-2 font-normal">
                  {language === "es" ? era.summary_es : era.summary_en}
                </p>
              </div>

              {/* Era Events Timeline Spine */}
              <div className="relative pl-6 sm:pl-8 border-l-2 border-slate-200 space-y-8 ml-3 sm:ml-6">
                {events.map((evt) => (
                  <div
                    key={evt.id}
                    className="relative group transition-all"
                  >
                    {/* Node Dot on spine */}
                    <div
                      className="absolute -left-[31px] sm:-left-[39px] top-4.5 flex h-6 w-6 items-center justify-center rounded-full border-2 border-white bg-slate-900 text-white shadow-xs group-hover:scale-120 group-hover:bg-blue-600 transition"
                      style={{ borderColor: "#ffffff" }}
                    >
                      {renderCategoryIcon(evt.icon_type, "h-3 w-3")}
                    </div>

                    {/* Event Card */}
                    <div className="rounded-2xl border border-slate-200 bg-white p-5 sm:p-6 shadow-xs hover:shadow-md hover:border-slate-300 transition duration-200">
                      
                      {/* Card Top Metadata */}
                      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-mono text-sm font-black text-blue-700 bg-blue-50 border border-blue-200/80 px-2.5 py-0.5 rounded-md">
                            {evt.year}
                          </span>
                          {evt.exact_date && (
                            <span className="text-xs font-bold text-slate-500">
                              • {evt.exact_date}
                            </span>
                          )}
                          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                            [{getCategoryLabel(evt.category)}]
                          </span>
                        </div>

                        {getSeverityBadge(evt)}
                      </div>

                      {/* Event Banner Image with Headshot Overlay */}
                      {evt.image_url && (
                        <div className="relative mt-3.5 mb-3 h-48 sm:h-56 w-full overflow-hidden rounded-xl border border-slate-200 bg-slate-950 shadow-inner group/img">
                          <img
                            src={evt.image_url}
                            alt={language === "es" ? evt.title_es : evt.title_en}
                            referrerPolicy="no-referrer"
                            className="h-full w-full object-cover opacity-90 transition-transform duration-500 ease-out group-hover/img:scale-105 group-hover/img:opacity-100"
                            onError={(e) => {
                              (e.currentTarget.parentElement as HTMLElement).style.display = "none";
                            }}
                          />
                          <div className="absolute inset-0 bg-gradient-to-t from-slate-950/80 via-transparent to-black/20" />
                          
                          {/* Caption Badge at bottom-left */}
                          {evt.image_caption && (
                            <div className="absolute bottom-2.5 left-3 right-20 line-clamp-1 text-[11px] font-medium text-slate-200 drop-shadow-md">
                              {evt.image_caption}
                            </div>
                          )}

                          {/* Protagonist Headshot Cutout overlapping bottom-right */}
                          {evt.player_headshot && (
                            <div className="absolute -bottom-1 right-2 h-20 w-20 sm:h-24 sm:w-24 drop-shadow-xl transition-transform duration-300 group-hover:scale-110">
                              <img
                                src={evt.player_headshot}
                                alt={evt.key_actors[0] || "Player"}
                                referrerPolicy="no-referrer"
                                className="h-full w-full object-contain filter drop-shadow-[0_4px_8px_rgba(0,0,0,0.5)]"
                                onError={(e) => {
                                  (e.currentTarget as HTMLElement).style.display = "none";
                                }}
                              />
                            </div>
                          )}
                        </div>
                      )}

                      {/* Title & Headline */}
                      <div className="mt-2 space-y-1.5">
                        <h3 className="text-base sm:text-lg font-black text-slate-900 group-hover:text-blue-700 transition">
                          {language === "es" ? evt.title_es : evt.title_en}
                        </h3>
                        <p className="text-xs sm:text-sm font-semibold text-blue-900/80 italic">
                          "{language === "es" ? evt.headline_es : evt.headline_en}"
                        </p>
                      </div>

                      {/* Main Narrative */}
                      <p className="mt-3 text-xs sm:text-sm text-slate-600 leading-relaxed font-normal">
                        {language === "es" ? evt.description_es : evt.description_en}
                      </p>

                      {/* Modern Impact / Highlight Box */}
                      <div className="mt-4 rounded-xl border border-amber-200/80 bg-amber-50/50 p-3 text-xs">
                        <div className="flex items-center gap-1.5 font-bold text-amber-900 mb-1">
                          <Info className="h-3.5 w-3.5 text-amber-600 shrink-0" />
                          <span>{t("timeline_impact_label")}:</span>
                        </div>
                        <p className="text-slate-700 leading-snug">
                          {language === "es" ? evt.impact_summary_es : evt.impact_summary_en}
                        </p>
                      </div>

                      {/* Footer: Key Actors, Tags & Expand Action */}
                      <div className="mt-4 pt-3 border-t border-slate-100 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                        {/* Actors & Tags */}
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="text-[11px] font-bold text-slate-400 mr-1">
                            {t("timeline_actors_label")}:
                          </span>
                          {evt.key_actors.map((actor, idx) => (
                            <span
                              key={idx}
                              className="rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-bold text-slate-700"
                            >
                              {actor}
                            </span>
                          ))}
                        </div>

                        {/* Open Modal Button */}
                        <button
                          onClick={() => setActiveModalEvent(evt)}
                          className="inline-flex items-center justify-center gap-1 rounded-xl bg-slate-100 px-3 py-1.5 text-xs font-black text-slate-800 hover:bg-slate-200 hover:text-slate-900 transition shadow-2xs self-end sm:self-auto"
                        >
                          <BookOpen className="h-3.5 w-3.5 text-blue-600" />
                          <span>{t("timeline_view_details")}</span>
                          <ChevronRight className="h-3.5 w-3.5 text-slate-400" />
                        </button>
                      </div>

                    </div>
                  </div>
                ))}
              </div>

            </div>
          ))}
        </section>

        {/* MODAL: FULL EVENT DEEP DIVE */}
        {activeModalEvent && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-xs p-4 sm:p-6 animate-in fade-in duration-150"
            onClick={() => setActiveModalEvent(null)}
          >
            <div
              className="relative w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-3xl border border-slate-200 bg-white p-6 sm:p-8 shadow-2xl"
              onClick={(e) => e.stopPropagation()}
            >
              {/* Close Button */}
              <button
                onClick={() => setActiveModalEvent(null)}
                className="absolute right-5 top-5 rounded-full p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition"
              >
                <X className="h-5 w-5" />
              </button>

              {/* Modal Header */}
              <div className="flex flex-wrap items-center gap-2 mb-3">
                <span className="font-mono text-base font-black text-blue-700 bg-blue-50 border border-blue-200 px-3 py-0.5 rounded-lg">
                  {activeModalEvent.year}
                </span>
                {activeModalEvent.exact_date && (
                  <span className="text-xs font-bold text-slate-500">
                    {activeModalEvent.exact_date}
                  </span>
                )}
                {getSeverityBadge(activeModalEvent)}
              </div>

              {/* Modal Hero Image */}
              {activeModalEvent.image_url && (
                <div className="relative mb-5 h-56 sm:h-72 w-full overflow-hidden rounded-2xl border border-slate-200 bg-slate-950 shadow-md group/modalimg">
                  <img
                    src={activeModalEvent.image_url}
                    alt={language === "es" ? activeModalEvent.title_es : activeModalEvent.title_en}
                    referrerPolicy="no-referrer"
                    className="h-full w-full object-cover"
                    onError={(e) => {
                      (e.currentTarget.parentElement as HTMLElement).style.display = "none";
                    }}
                  />
                  <div className="absolute inset-0 bg-gradient-to-t from-slate-950/85 via-slate-950/20 to-transparent" />
                  
                  {activeModalEvent.image_caption && (
                    <div className="absolute bottom-3 left-4 right-24 text-xs font-semibold text-white drop-shadow-md">
                      {activeModalEvent.image_caption}
                    </div>
                  )}

                  {activeModalEvent.player_headshot && (
                    <div className="absolute -bottom-2 right-4 h-28 w-28 sm:h-36 sm:w-36 drop-shadow-2xl">
                      <img
                        src={activeModalEvent.player_headshot}
                        alt={activeModalEvent.key_actors[0] || "Legend"}
                        referrerPolicy="no-referrer"
                        className="h-full w-full object-contain filter drop-shadow-[0_8px_16px_rgba(0,0,0,0.6)]"
                        onError={(e) => {
                          (e.currentTarget as HTMLElement).style.display = "none";
                        }}
                      />
                    </div>
                  )}
                </div>
              )}

              {/* Modal Title */}
              <h2 className="text-xl sm:text-2xl font-black text-slate-900 leading-snug">
                {language === "es" ? activeModalEvent.title_es : activeModalEvent.title_en}
              </h2>

              <p className="mt-1 text-sm font-semibold text-blue-900 italic">
                "{language === "es" ? activeModalEvent.headline_es : activeModalEvent.headline_en}"
              </p>

              {/* Narrative Content */}
              <div className="mt-5 space-y-4 text-sm text-slate-700 leading-relaxed border-t border-slate-100 pt-4">
                <p>
                  {language === "es" ? activeModalEvent.description_es : activeModalEvent.description_en}
                </p>

                {/* Key Fact / Trivia Callout */}
                {(activeModalEvent.trivia_es || activeModalEvent.trivia_en) && (
                  <div className="rounded-2xl border border-amber-300 bg-gradient-to-br from-amber-50 to-orange-50/40 p-4 shadow-2xs">
                    <div className="flex items-center gap-2 font-black text-amber-900 text-xs uppercase tracking-wider mb-1">
                      <Sparkles className="h-4 w-4 text-amber-600" />
                      <span>{t("timeline_trivia_label")}</span>
                    </div>
                    <p className="text-xs sm:text-sm text-slate-800 font-medium italic">
                      "{language === "es" ? activeModalEvent.trivia_es : activeModalEvent.trivia_en}"
                    </p>
                  </div>
                )}

                {/* Game Impact */}
                <div className="rounded-2xl border border-blue-200 bg-blue-50/50 p-4">
                  <h4 className="font-black text-blue-950 text-xs uppercase tracking-wider mb-1 flex items-center gap-1.5">
                    <Scale className="h-4 w-4 text-blue-700" />
                    <span>{t("timeline_impact_label")}</span>
                  </h4>
                  <p className="text-xs sm:text-sm text-slate-700">
                    {language === "es" ? activeModalEvent.impact_summary_es : activeModalEvent.impact_summary_en}
                  </p>
                </div>

                {/* Protagonists & Tags */}
                <div className="space-y-2 pt-2">
                  <div className="text-xs font-bold text-slate-500">
                    {t("timeline_actors_label")}:
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {activeModalEvent.key_actors.map((actor, i) => (
                      <span
                        key={i}
                        className="rounded-lg bg-slate-100 border border-slate-200 px-2.5 py-1 text-xs font-bold text-slate-800"
                      >
                        {actor}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="flex flex-wrap gap-1 pt-2">
                  {activeModalEvent.tags.map((tag, i) => (
                    <span
                      key={i}
                      className="rounded-full bg-slate-50 border border-slate-200 px-2.5 py-0.5 text-[11px] font-medium text-slate-500"
                    >
                      #{tag}
                    </span>
                  ))}
                </div>
              </div>

              {/* Close Action */}
              <div className="mt-6 pt-4 border-t border-slate-100 flex justify-end">
                <button
                  onClick={() => setActiveModalEvent(null)}
                  className="rounded-xl bg-slate-900 px-5 py-2 text-xs font-black text-white hover:bg-slate-800 transition shadow-xs"
                >
                  {t("timeline_close_modal")}
                </button>
              </div>

            </div>
          </div>
        )}

      </main>
    </div>
  );
}
