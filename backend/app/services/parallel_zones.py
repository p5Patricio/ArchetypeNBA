import os
import json
from typing import Dict, Any, List, Optional
from app.schemas import (
    ParallelShotZonesResponse,
    ParallelPlayerItem,
    LeagueAveragesMap,
    LeagueAverageZone,
    ShotZonePreset,
    PlayerZones,
    ZoneMetric,
)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

PRESETS: List[Dict[str, Any]] = [
    {
        "id": "curry_vs_giannis",
        "title": "Stephen Curry vs Giannis Antetokounmpo",
        "subtitle": "El francotirador legendario (#1 en Triple) vs La fuerza imparable (#1 en Pintura)",
        "player_ids": [201939, 203507],
    },
    {
        "id": "elite_all_zones",
        "title": "Anthony Edwards vs Jalen Brunson vs Donovan Mitchell",
        "subtitle": "Especialistas completos de élite en las 4 zonas de anotación (Top 30 general)",
        "player_ids": [1630162, 1628973, 1628378],
    },
    {
        "id": "westbrook_vs_derozan",
        "title": "Russell Westbrook vs DeMar DeRozan",
        "subtitle": "Equilibrio en la media de la liga vs Maestro absoluto de la media distancia (#1)",
        "player_ids": [201566, 201942],
    },
    {
        "id": "clippers_duo",
        "title": "Kawhi Leonard vs James Harden",
        "subtitle": "Efectividad quirúrgica desde las 4 distancias",
        "player_ids": [202695, 201935],
    },
    {
        "id": "pistons_duo",
        "title": "Jalen Duren vs Cade Cunningham",
        "subtitle": "Amenaza interior pura vs Generador perimetral de Detroit",
        "player_ids": [1631105, 1630595],
    },
    {
        "id": "butler_vs_green",
        "title": "Jimmy Butler vs Draymond Green",
        "subtitle": "Perfiles ofensivos opuestos e impacto táctico",
        "player_ids": [202710, 203110],
    },
]


class ParallelZonesService:
    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}

    def _load_season_data(self, season: str = "2023-24") -> Dict[str, Any]:
        normalized_season = season.replace("/", "-")
        if normalized_season in self._cache:
            return self._cache[normalized_season]

        file_name = f"parallel_shot_zones_{normalized_season.replace('-', '_')}.json"
        file_path = os.path.join(DATA_DIR, file_name)

        if not os.path.exists(file_path):
            # Fallback to 2023-24 if requested season does not exist
            fallback_file = os.path.join(DATA_DIR, "parallel_shot_zones_2023_24.json")
            if os.path.exists(fallback_file):
                file_path = fallback_file
            else:
                raise FileNotFoundError(f"Parallel shot zones data not found for season {season}")

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            self._cache[normalized_season] = data
            return data

    def get_parallel_shot_zones(
        self,
        season: str = "2023-24",
        player_ids: Optional[List[int]] = None,
        search: Optional[str] = None,
    ) -> ParallelShotZonesResponse:
        raw_data = self._load_season_data(season)

        lg_avg = raw_data["league_averages"]
        league_averages = LeagueAveragesMap(
            paint=LeagueAverageZone(**lg_avg["paint"]),
            mid=LeagueAverageZone(**lg_avg["mid"]),
            ft=LeagueAverageZone(**lg_avg["ft"]),
            three=LeagueAverageZone(**lg_avg["three"]),
        )

        all_players: List[ParallelPlayerItem] = []
        for p in raw_data["players"]:
            zones_dict = p["zones"]
            player_zones = PlayerZones(
                paint=ZoneMetric(**zones_dict["paint"]),
                mid=ZoneMetric(**zones_dict["mid"]),
                ft=ZoneMetric(**zones_dict["ft"]),
                three=ZoneMetric(**zones_dict["three"]),
            )
            item = ParallelPlayerItem(
                id=p["id"],
                name=p["name"],
                team=p["team"],
                headshot_url=p["headshot_url"],
                minutes=p["minutes"],
                gp=p["gp"],
                pts=p["pts"],
                zones=player_zones,
            )
            all_players.append(item)

        # Filter by player_ids if provided
        filtered_players = all_players
        if player_ids:
            target_ids = set(player_ids)
            filtered_players = [p for p in all_players if p.id in target_ids]

        if search:
            query = search.strip().lower()
            filtered_players = [p for p in filtered_players if query in p.name.lower() or query in p.team.lower()]

        presets = [ShotZonePreset(**pr) for pr in PRESETS]

        return ParallelShotZonesResponse(
            season=raw_data.get("season", season),
            total_players=len(all_players),
            league_averages=league_averages,
            players=filtered_players,
            presets=presets,
        )

    def get_presets(self) -> List[ShotZonePreset]:
        return [ShotZonePreset(**pr) for pr in PRESETS]
