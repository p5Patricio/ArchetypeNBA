"use client";

import { useEffect, useState } from "react";
import { Navbar } from "@/components/Navbar";
import { CommandPalette } from "@/components/CommandPalette";
import { GalaxyMap } from "@/components/GalaxyMap";
import { getGalaxyMap, type GalaxyPlayerPoint } from "@/lib/api";
import { usePreferences } from "@/context/PreferencesContext";
import { Sparkles, Compass, Zap, Target } from "lucide-react";

export default function GalaxyPage() {
  const { language, seasonId, seasonLabel } = usePreferences();
  const [players, setPlayers] = useState<GalaxyPlayerPoint[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [isCommandOpen, setIsCommandOpen] = useState<boolean>(false);

  useEffect(() => {
    if (!seasonId) return;
    setLoading(true);
    getGalaxyMap(seasonId)
      .then((data) => setPlayers(data))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [seasonId]);

  return (
    <div className="min-h-screen bg-[#F8FAFC] text-slate-900 selection:bg-purple-100 selection:text-purple-900">
      
      {/* Navigation */}
      <Navbar onOpenSearch={() => setIsCommandOpen(true)} />

      <CommandPalette
        isOpen={isCommandOpen}
        onClose={() => setIsCommandOpen(false)}
        seasonId={seasonId}
      />

      <div className="md:pl-64">
        {/* Main Container (Wide Desktop Canvas) */}
        <main className="mx-auto max-w-[1700px] px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        
        {/* Galaxy Map Component */}
        {loading ? (
          <div className="h-[520px] rounded-3xl border border-slate-200 bg-white p-6 animate-pulse shadow-xs" />
        ) : (
          <GalaxyMap
            players={players}
            seasonLabel={seasonLabel}
          />
        )}

        {/* Scientific Methodology Explanatory Cards */}
        <section className="grid grid-cols-1 md:grid-cols-3 gap-5">
          
          <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-xs space-y-2.5">
            <div className="p-2 rounded-xl bg-purple-50 border border-purple-200 text-purple-600 w-fit">
              <Sparkles className="h-4 w-4" />
            </div>
            <h3 className="text-sm font-extrabold text-slate-900">
              {language === "es" ? "¿Cómo funciona el Mapa Galaxia?" : "How does the Galaxy Map work?"}
            </h3>
            <p className="text-xs text-slate-600 leading-relaxed font-medium">
              {language === "es"
                ? "Utiliza reducción dimensional PCA/UMAP para proyectar el espacio vectorial de 15 métricas de ritmo y volumen a un plano 2D sin perder la relación de proximidad táctica."
                : "It applies PCA/UMAP dimensionality reduction to project the 15-dimensional skill space onto a 2D plane while preserving tactical proximity relationships."}
            </p>
          </div>

          <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-xs space-y-2.5">
            <div className="p-2 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-600 w-fit">
              <Zap className="h-4 w-4" />
            </div>
            <h3 className="text-sm font-extrabold text-slate-900">
              {language === "es" ? "Clustering Blando (GMM Probabilístico)" : "Soft Clustering (Probabilistic GMM)"}
            </h3>
            <p className="text-xs text-slate-600 leading-relaxed font-medium">
              {language === "es"
                ? "Ningún jugador moderno pertenece al 100% a un único rol. El sistema calcula afinidades porcentuales continuas en los 7 arquetipos tácticos de la NBA."
                : "No modern player fits 100% into a single rigid role. The system calculates continuous percentage affinities across all 7 NBA tactical archetypes."}
            </p>
          </div>

          <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-xs space-y-2.5">
            <div className="p-2 rounded-xl bg-orange-50 border border-orange-200 text-orange-600 w-fit">
              <Target className="h-4 w-4" />
            </div>
            <h3 className="text-sm font-extrabold text-slate-900">
              {language === "es" ? "Filtrado por Arquetipo & Búsqueda" : "Archetype Filtering & Search"}
            </h3>
            <p className="text-xs text-slate-600 leading-relaxed font-medium">
              {language === "es"
                ? "Permite aislar constelaciones de roles específicos (ej. Francotiradores 3&D vs Protectores de Aro) y buscar a cualquier estrella con resaltado de anillo orbital."
                : "Isolate specific role constellations (e.g. 3&D Snipers vs Rim Protectors) and search any star with animated orbital highlight rings."}
            </p>
          </div>

        </section>

        </main>
      </div>

    </div>
  );
}
