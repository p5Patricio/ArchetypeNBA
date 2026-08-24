from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.v1 import (
    health, teams, players, cluster, data, player_extras, historical,
    seasons, hall_of_fame, analytics, versus, lineup, training,
    pizza_chart, shotchart, doppelgangers, financial
)

app = FastAPI(
    title="NBA Analytics Platform API",
    version="0.3.0",
    description="Next-Generation Sports Science, Tactical Scouting & AI Analytics Platform",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Versioned API routers
@app.get("/")
def root():
    return {
        "message": "ArchetypeNBA Analytics Platform API",
        "version": "0.3.0",
        "docs": "/docs",
    }

app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(seasons.router, prefix="/api/v1", tags=["seasons"])
app.include_router(teams.router, prefix="/api/v1", tags=["teams"])
app.include_router(players.router, prefix="/api/v1", tags=["players"])
app.include_router(cluster.router, prefix="/api/v1", tags=["cluster"])
app.include_router(data.router, prefix="/api/v1", tags=["data"])
app.include_router(historical.router, prefix="/api/v1", tags=["historical"])
app.include_router(player_extras.router, prefix="/api/v1", tags=["player-extras"])
app.include_router(hall_of_fame.router, prefix="/api/v1", tags=["hall-of-fame"])
app.include_router(analytics.router, prefix="/api/v1", tags=["analytics"])
app.include_router(versus.router, prefix="/api/v1", tags=["versus"])
app.include_router(lineup.router, prefix="/api/v1", tags=["lineup"])
app.include_router(training.router, prefix="/api/v1", tags=["training"])
app.include_router(pizza_chart.router, prefix="/api/v1", tags=["pizza-chart"])
app.include_router(shotchart.router, prefix="/api/v1", tags=["shot-chart"])
app.include_router(doppelgangers.router, prefix="/api/v1", tags=["doppelgangers"])
app.include_router(financial.router, prefix="/api/v1", tags=["financial"])




