import {
  Compass,
  Sparkles,
  Shield,
  Crown,
  Layers,
  Swords,
  Users,
  Dumbbell,
  ShieldAlert,
  History,
  Target,
  TrendingUp,
  Banknote,
  Calendar,
  Trophy,
  LayoutGrid,
  UserRound,
  type LucideIcon,
} from "lucide-react";

/**
 * Single source of truth for the two product modes and the route each page
 * belongs to. Sidebar, Navbar, ModeToggle and CommandPalette all read from here.
 */
export type AppMode = "analysis" | "betting";

export const APP_MODES: AppMode[] = ["analysis", "betting"];
export const DEFAULT_MODE: AppMode = "analysis";
export const MODE_STORAGE_KEY = "archetype_nba_mode";

export interface Bilingual {
  es: string;
  en: string;
}

export interface ModeRoute {
  href: string;
  mode: AppMode;
  label: Bilingual;
  icon: LucideIcon;
  /** Listed in the sidebar and the command palette (false for detail routes such as /player/[name]). */
  nav: boolean;
  /** "exact" only matches the path itself (used for "/"); "prefix" also matches nested paths. */
  match: "exact" | "prefix";
}

export const MODE_ROUTES: ModeRoute[] = [
  // ---- NBA Analytics -------------------------------------------------------
  { href: "/", mode: "analysis", label: { es: "Scouting Hub", en: "Scouting Hub" }, icon: Compass, nav: true, match: "exact" },
  { href: "/training", mode: "analysis", label: { es: "Campo de Entrenamiento", en: "Training Camp" }, icon: Dumbbell, nav: true, match: "prefix" },
  { href: "/versus", mode: "analysis", label: { es: "Coliseo 1 vs 1", en: "1 vs 1 Colosseum" }, icon: Swords, nav: true, match: "prefix" },
  { href: "/shot-zones", mode: "analysis", label: { es: "Zonas de Tiro (4 Ejes)", en: "Shot Zones (4 Axes)" }, icon: Target, nav: true, match: "prefix" },
  { href: "/matchups", mode: "analysis", label: { es: "Matchups 1v1 (¿Quién lo para?)", en: "1v1 Matchups" }, icon: ShieldAlert, nav: true, match: "prefix" },
  { href: "/lineup", mode: "analysis", label: { es: "Armador 5 vs 5", en: "5 vs 5 Lineup Builder" }, icon: Users, nav: true, match: "prefix" },
  { href: "/doppelgangers", mode: "analysis", label: { es: "Doppelgängers", en: "Doppelgängers" }, icon: Users, nav: true, match: "prefix" },
  { href: "/contracts", mode: "analysis", label: { es: "Contratos & Cap", en: "Contracts & Cap" }, icon: Layers, nav: true, match: "prefix" },
  { href: "/galaxy", mode: "analysis", label: { es: "Galaxia Táctica", en: "Tactical Galaxy" }, icon: Sparkles, nav: true, match: "prefix" },
  { href: "/hall-of-fame", mode: "analysis", label: { es: "Salón de la Fama", en: "Hall of Fame" }, icon: Crown, nav: true, match: "prefix" },
  { href: "/teams", mode: "analysis", label: { es: "Franquicias", en: "Franchises" }, icon: Shield, nav: true, match: "prefix" },
  { href: "/timeline", mode: "analysis", label: { es: "Línea del Tiempo", en: "Historical Timeline" }, icon: History, nav: true, match: "prefix" },
  { href: "/player", mode: "analysis", label: { es: "Scouting Lab de Jugador", en: "Player Scouting Lab" }, icon: UserRound, nav: false, match: "prefix" },

  // ---- Betting (paper trading) --------------------------------------------
  { href: "/betting", mode: "betting", label: { es: "Hub de Apuestas", en: "Betting Hub" }, icon: LayoutGrid, nav: true, match: "prefix" },
  { href: "/week", mode: "betting", label: { es: "Semana", en: "Week" }, icon: Calendar, nav: true, match: "prefix" },
  { href: "/paper", mode: "betting", label: { es: "Paper Trading", en: "Paper Trading" }, icon: Banknote, nav: true, match: "prefix" },
  { href: "/league", mode: "betting", label: { es: "Model League", en: "Model League" }, icon: Trophy, nav: true, match: "prefix" },
  { href: "/props", mode: "betting", label: { es: "Player Props (experimental)", en: "Player Props (experimental)" }, icon: TrendingUp, nav: true, match: "prefix" },
];

export const MODE_HOME: Record<AppMode, string> = {
  analysis: "/",
  betting: "/betting",
};

export interface ModeTheme {
  label: Bilingual;
  /** Short label for the segmented toggle. */
  shortLabel: Bilingual;
  /** Badge text shown in headers. */
  badge: Bilingual;
  /** Sidebar section heading. */
  section: Bilingual;
  icon: LucideIcon;
  // Tailwind class strings are written out in full so the compiler can see them.
  activeSegment: string;
  badgeClass: string;
  accentText: string;
  topBar: string;
  linkActive: string;
  linkIcon: string;
  hoverRow: string;
  focusRing: string;
}

export const MODE_THEME: Record<AppMode, ModeTheme> = {
  analysis: {
    label: { es: "Análisis NBA", en: "NBA Analytics" },
    shortLabel: { es: "Análisis", en: "Analytics" },
    badge: { es: "ANÁLISIS NBA", en: "NBA ANALYTICS" },
    section: { es: "Módulos de Analítica", en: "Analytics Modules" },
    icon: Compass,
    activeSegment: "bg-orange-600 text-white shadow-sm",
    badgeClass: "border-orange-200 bg-orange-50 text-orange-800",
    accentText: "text-orange-600",
    topBar: "bg-orange-500",
    linkActive: "bg-orange-50 text-orange-800 border-orange-200 font-extrabold",
    linkIcon: "text-orange-600",
    hoverRow: "hover:bg-orange-50/70",
    focusRing: "focus-visible:ring-orange-500",
  },
  betting: {
    label: { es: "Apuestas (paper trading)", en: "Betting (paper trading)" },
    shortLabel: { es: "Apuestas", en: "Betting" },
    badge: { es: "APUESTAS • PAPER", en: "BETTING • PAPER" },
    section: { es: "Módulos de Apuestas", en: "Betting Modules" },
    icon: Banknote,
    activeSegment: "bg-emerald-600 text-white shadow-sm",
    badgeClass: "border-emerald-300 bg-emerald-50 text-emerald-800",
    accentText: "text-emerald-600",
    topBar: "bg-emerald-500",
    linkActive: "bg-emerald-50 text-emerald-800 border-emerald-200 font-extrabold",
    linkIcon: "text-emerald-600",
    hoverRow: "hover:bg-emerald-50/70",
    focusRing: "focus-visible:ring-emerald-500",
  },
};

function routeMatches(route: ModeRoute, pathname: string): boolean {
  if (route.match === "exact") return pathname === route.href;
  return pathname === route.href || pathname.startsWith(`${route.href}/`);
}

/** Returns the route entry owning `pathname`, or null for unclassified paths. */
export function routeForPathname(pathname: string | null | undefined): ModeRoute | null {
  if (!pathname) return null;
  const clean = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  return MODE_ROUTES.find((r) => routeMatches(r, clean)) ?? null;
}

/** Mode a pathname belongs to, or null when the path is not classified. */
export function modeForPathname(pathname: string | null | undefined): AppMode | null {
  return routeForPathname(pathname)?.mode ?? null;
}

export function homeForMode(mode: AppMode): string {
  return MODE_HOME[mode];
}

export function navRoutesForMode(mode: AppMode): ModeRoute[] {
  return MODE_ROUTES.filter((r) => r.mode === mode && r.nav);
}

export function isAppMode(value: unknown): value is AppMode {
  return value === "analysis" || value === "betting";
}
