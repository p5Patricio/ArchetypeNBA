import os
from fastapi.testclient import TestClient
from sqlmodel import Session
import pytest
from fastapi import HTTPException

from app.models import Player, PlayerSeasonStats, Season, Team
from app.services.report import ReportService


def _seed_report_data(db_session: Session):
    season = Season(season_label="2024-25", is_active=True)
    team = Team(
        abbreviation="LAL",
        full_name="Los Angeles Lakers",
        city="Los Angeles",
        conference="West",
        division="Pacific",
    )
    db_session.add(season)
    db_session.add(team)
    db_session.commit()

    player1 = Player(full_name="LeBron James")
    player2 = Player(full_name="Anthony Davis")
    db_session.add(player1)
    db_session.add(player2)
    db_session.commit()

    stats1 = PlayerSeasonStats(
        player_id=player1.id,
        team_id=team.id,
        season_id=season.id,
        cluster_id=1,
        gp=60,
        gs=60,
        min=2000,
        pts=25.0,
        reb=7.5,
        ast=8.0,
        stl=1.2,
        blk=0.6,
        tov=3.1,
        pf=1.8,
        fgm=9.5,
        fga=18.0,
        fg_pct=0.528,
        fg3m=2.2,
        fg3a=5.5,
        fg3_pct=0.400,
        ftm=3.8,
        fta=5.0,
        ft_pct=0.760,
        oreb=1.0,
        dreb=6.5,
    )
    stats2 = PlayerSeasonStats(
        player_id=player2.id,
        team_id=team.id,
        season_id=season.id,
        cluster_id=1,
        gp=55,
        gs=55,
        min=1800,
        pts=23.0,
        reb=11.0,
        ast=3.0,
        stl=1.0,
        blk=2.2,
        tov=2.0,
        pf=2.5,
        fgm=8.5,
        fga=16.0,
        fg_pct=0.531,
        fg3m=0.5,
        fg3a=1.5,
        fg3_pct=0.333,
        ftm=5.5,
        fta=7.0,
        ft_pct=0.785,
        oreb=2.5,
        dreb=8.5,
    )
    db_session.add(stats1)
    db_session.add(stats2)
    db_session.commit()
    return season, player1, player2


def test_generate_report_pdf_file_created(db_session: Session):
    season, player, _ = _seed_report_data(db_session)
    service = ReportService(db_session)

    pdf_path = service.generate_report(player.full_name, season.id)
    try:
        assert os.path.exists(pdf_path)
        assert os.path.getsize(pdf_path) > 1000
        with open(pdf_path, "rb") as f:
            header = f.read(5)
            assert header == b"%PDF-"
    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)


def test_player_report_endpoint_success(client: TestClient, db_session: Session):
    season, player, _ = _seed_report_data(db_session)

    resp = client.get(f"/api/v1/player/{player.full_name}/report?season_id={season.id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF-")


def test_player_report_not_found(client: TestClient, db_session: Session):
    resp = client.get("/api/v1/player/Unknown Player/report")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_player_report_no_clustering(client: TestClient, db_session: Session):
    season = Season(season_label="2024-25", is_active=True)
    player = Player(full_name="Rookie Player")
    db_session.add(season)
    db_session.add(player)
    db_session.commit()

    stats = PlayerSeasonStats(
        player_id=player.id,
        team_id=1,
        season_id=season.id,
        cluster_id=None,  # Clustering not initialized
    )
    db_session.add(stats)
    db_session.commit()

    resp = client.get(f"/api/v1/player/{player.full_name}/report?season_id={season.id}")
    assert resp.status_code == 400
    assert "clustering not initialized" in resp.json()["detail"].lower()
