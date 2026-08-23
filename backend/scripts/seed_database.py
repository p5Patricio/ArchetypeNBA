import sys
import os
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from sqlmodel import Session, select
from app.deps import engine, create_db_and_tables
from app.models import Season, Player, Team, PlayerSeasonStats
from app.etl.pipeline import ETLPipeline
from app.repositories.stats import StatsRepository
from app.services.clustering import ClusteringService


DATASETS = [
    ("nba_active_player_stats_2023-24_Regular_Season_100min.xlsx", "2023-24"),
    ("nba_active_player_stats_2024-25_Regular_Season_100min.xlsx", "2024-25"),
    ("nba_active_player_stats_2025-26_Regular_Season_100min.xlsx", "2025-26"),
]


def resolve_file(filename: str) -> str:
    root_path = backend_dir.parent / filename
    if root_path.exists():
        return str(root_path)
    backend_path = backend_dir / filename
    if backend_path.exists():
        return str(backend_path)
    raise FileNotFoundError(f"Cannot find dataset file: {filename}")


def run_seed():
    print("=== 1. Creando tablas en la base de datos ===")
    create_db_and_tables()
    print("Tablas creadas y verificadas correctamente.")

    print("\n=== 2. Ejecutando ETL de todas las temporadas ===")
    with Session(engine) as session:
        pipeline = ETLPipeline(session)
        stats_repo = StatsRepository(session)
        clustering_service = ClusteringService(stats_repo)

        for filename, season_label in DATASETS:
            try:
                filepath = resolve_file(filename)
                print(f"\nProcesando temporada {season_label} ({filename})...")
                result = pipeline.run(filepath, season_label)
                print(f" -> Filas procesadas: {result['rows_processed']}, Insertados: {result['inserted']}, Actualizados: {result['updated']}, Fallidos: {result['failed']}")

                # Buscar season para correr clustering
                season = session.exec(select(Season).where(Season.season_label == season_label)).first()
                if season and season.id:
                    print(f" -> Ejecutando K-Means clustering para temporada {season_label} (ID: {season.id})...")
                    cluster_res = clustering_service.init_clusters(season.id, k=5)
                    print(f" -> Clustering listo: {cluster_res['players']} jugadores agrupados en {cluster_res['clusters']} clusters.")
            except Exception as e:
                print(f"Error procesando {filename}: {e}")

        # Resumen general
        total_players = len(session.exec(select(Player)).all())
        total_teams = len(session.exec(select(Team)).all())
        total_stats = len(session.exec(select(PlayerSeasonStats)).all())
        seasons = session.exec(select(Season)).all()

        print("\n================ RESUMEN DE BASE DE DATOS ================")
        print(f"Engine activo: {engine.url}")
        print(f"Jugadores totales unicos: {total_players}")
        print(f"Equipos totales: {total_teams}")
        print(f"Registros de estadisticas de temporada: {total_stats}")
        print("Temporadas disponibles:")
        for s in seasons:
            count = len(session.exec(select(PlayerSeasonStats).where(PlayerSeasonStats.season_id == s.id)).all())
            print(f" - [{s.id}] {s.season_label}: {count} jugadores con stats y clusters asignados")
        print("==========================================================")


if __name__ == "__main__":
    run_seed()
