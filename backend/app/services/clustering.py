from typing import Dict, Any, List, Optional
from fastapi import HTTPException
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from app.repositories.stats import StatsRepository


ROLE_METADATA = {
    0: {
        "name_es": "Interior Facilitador & Unicornio",
        "name_en": "Playmaking Hub & Unicorn Big",
        "desc_es": "Pivots y aleros modernos con impacto global: facilitación ofensiva desde poste alto, rebote y anotación multidimensional.",
        "desc_en": "Modern bigs with global impact: high-post playmaking hubs, elite rebounding, and multi-dimensional scoring.",
        "color": "#8B5CF6",  # Indigo/Purple
    },
    1: {
        "name_es": "Perro de Presa Perimetral (POA Stopper)",
        "name_en": "Point-of-Attack Lockdown Stopper",
        "desc_es": "Especialistas defensivos perimetrales en el punto de ataque con alta tasa de intercepciones y presión al manejador.",
        "desc_en": "Perimeter point-of-attack defensive stoppers with elite deflection rates and ball-pressure disturbance.",
        "color": "#10B981",  # Emerald
    },
    2: {
        "name_es": "Ancla Interior & Rim Protector Puro",
        "name_en": "Traditional Rim Protector & Roll Big",
        "desc_es": "Pivots dominantes en la pintura, finalizadores verticales en pick & roll, intimidación de aro y dominio de rebote.",
        "desc_en": "Paint anchor centers, vertical lob threats in pick-and-roll dive, rim deterrence, and rebounding dominance.",
        "color": "#0284C7",  # Blue
    },
    3: {
        "name_es": "Alero Conector & Versátil (Glue Guy)",
        "name_en": "Versatile Connecting Wing & Glue Guy",
        "desc_es": "Aleros polivalentes que conectan rotaciones ofensivas, espacian la cancha con tiros oportunos y defienden múltiples puestos.",
        "desc_en": "Multi-positional wings that connect offense, space the floor with timely shooting, and switch across positions.",
        "color": "#64748B",  # Slate
    },
    4: {
        "name_es": "Motor Ofensivo Heliocéntrico",
        "name_en": "Heliocentric Primary Scorer & Creator",
        "desc_es": "Generadores primarios de volumen estelar, alto uso ofensivo (USG% > 28%), anotación desde pick & roll y creación élite.",
        "desc_en": "Superstar primary engines, high usage (USG% > 28%), pick-and-roll scoring mastery, and elite floor vision.",
        "color": "#EA580C",  # Orange
    },
    5: {
        "name_es": "Francotirador Perimetral & 3&D Puro",
        "name_en": "Pure 3&D & Perimeter Sniper",
        "desc_es": "Especialistas perimetrales de alto volumen en triples catch-and-shoot (>60% de sus tiros) con defensa exterior.",
        "desc_en": "High-volume perimeter specialists in catch-and-shoot threes (>60% 3P rate) with switchable perimeter defense.",
        "color": "#06B6D4",  # Cyan
    },
    6: {
        "name_es": "General de Piso & Creador Puro",
        "name_en": "Floor General & Pure Playmaker",
        "desc_es": "Bases organizadores con visión de pase élite, control de ritmo y máxima relación de Asistencias por Pérdida.",
        "desc_en": "Floor generals with elite floor vision, pace control, and industry-leading Assist-to-Turnover ratios.",
        "color": "#F59E0B",  # Amber
    },
}


class ClusteringService:
    def __init__(self, stats_repo: StatsRepository):
        self.stats_repo = stats_repo

    def init_clusters(self, season_id: int, k: int = 7) -> Dict[str, Any]:
        stats = self.stats_repo.find_by_season(season_id)
        if not stats:
            raise HTTPException(status_code=404, detail=f"No player stats found for season {season_id}")

        rows = []
        stat_ids = []
        for s in stats:
            gp = max(s.gp or 1, 1)
            mpg = max((s.min or 0) / gp, 4.0)
            scale_36 = 36.0 / mpg

            pts_36 = ((s.pts or 0.0) / gp) * scale_36
            reb_36 = ((s.reb or 0.0) / gp) * scale_36
            ast_36 = ((s.ast or 0.0) / gp) * scale_36
            stl_36 = ((s.stl or 0.0) / gp) * scale_36
            blk_36 = ((s.blk or 0.0) / gp) * scale_36
            fg3m_36 = ((s.fg3m or 0.0) / gp) * scale_36
            fg_pct = s.fg_pct or 0.45
            three_pt_rate = (s.fg3a or 0.0) / max(s.fga or 1.0, 1.0)

            rows.append([pts_36, reb_36, ast_36, stl_36, blk_36, fg3m_36, fg_pct, three_pt_rate])
            stat_ids.append(s.id)

        feature_cols = ["pts_36", "reb_36", "ast_36", "stl_36", "blk_36", "fg3m_36", "fg_pct", "three_pt_rate"]
        df = pd.DataFrame(rows, columns=feature_cols)

        scaler = StandardScaler()
        scaled = scaler.fit_transform(df)

        kmeans = KMeans(n_clusters=k, random_state=42, n_init=15)
        clusters = kmeans.fit_predict(scaled)

        assignments = {stat_ids[i]: int(clusters[i]) for i in range(len(stat_ids))}
        self.stats_repo.update_clusters(season_id, assignments)

        roles_dict = {cid: ROLE_METADATA.get(cid, {}).get("name_en", f"Archetype {cid}") for cid in range(k)}

        return {
            "season_id": season_id,
            "k": k,
            "players": len(stats),
            "clusters": k,
            "roles": roles_dict,
        }

    @staticmethod
    def calculate_soft_probabilities(
        player_vec: List[float],
        centroids: np.ndarray,
        temperature: float = 1.2
    ) -> List[Dict[str, Any]]:
        """
        Calculates Gaussian Softmax probability distribution across all 7 archetypes.
        """
        dists = np.linalg.norm(centroids - np.array(player_vec), axis=1)
        weights = np.exp(-dists * temperature)
        probs = weights / np.sum(weights)

        breakdown = []
        for cid, prob in enumerate(probs):
            meta = ROLE_METADATA.get(cid, {})
            breakdown.append({
                "cluster_id": cid,
                "role_name_es": meta.get("name_es", f"Arquetipo {cid}"),
                "role_name_en": meta.get("name_en", f"Archetype {cid}"),
                "percentage": round(float(prob) * 100, 1),
                "color": meta.get("color", "#EA580C"),
                "description_es": meta.get("desc_es", ""),
                "description_en": meta.get("desc_en", ""),
            })

        return sorted(breakdown, key=lambda x: x["percentage"], reverse=True)
