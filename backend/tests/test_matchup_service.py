import pytest
from sqlmodel import Session
from app.models import Player, Season, PlayerMatchupStats
from app.services.matchup_service import MatchupService


def test_matchup_service_baseline_and_classification(db_session: Session):
    # Setup players
    luka = Player(id=1629029, full_name="Luka Doncic")
    caruso = Player(id=1627936, full_name="Alex Caruso")
    gobert = Player(id=203497, full_name="Rudy Gobert")
    normal_def = Player(id=1630162, full_name="Average Defender")
    db_session.add_all([luka, caruso, gobert, normal_def])

    # Setup season
    season = Season(id=1, season_label="2023-24")
    db_session.add(season)
    db_session.commit()

    # Matchup 1: Alex Caruso (Lockdown / Kryptonite)
    # 50 possessions, 10 pts, 10 FGA, 0 FTA -> TS% = 50.0%, PTS/75 = 15.0
    m_caruso = PlayerMatchupStats(
        season_id=season.id,
        off_player_id=luka.id,
        def_player_id=caruso.id,
        gp=4,
        matchup_min=15.0,
        partial_poss=50.0,
        player_pts=10.0,
        matchup_ast=2.0,
        matchup_tov=3.0,
        matchup_fga=10.0,
        matchup_fta=0.0,
        matchup_fgm=4.0,
        pts_per_75=15.0,
        ast_per_75=3.0,
        tov_per_75=4.5,
        ts_pct=50.0,
    )

    # Matchup 2: Rudy Gobert (Mismatch Exploited / Switched Big)
    # 50 possessions, 45 pts, 20 FGA, 8 FTA -> TS% = 95.7%, PTS/75 = 67.5
    m_gobert = PlayerMatchupStats(
        season_id=season.id,
        off_player_id=luka.id,
        def_player_id=gobert.id,
        gp=4,
        matchup_min=15.0,
        partial_poss=50.0,
        player_pts=45.0,
        matchup_ast=8.0,
        matchup_tov=2.0,
        matchup_fga=20.0,
        matchup_fta=8.0,
        matchup_fgm=16.0,
        pts_per_75=67.5,
        ast_per_75=12.0,
        tov_per_75=3.0,
        ts_pct=95.7,
    )

    # Matchup 3: Normal Defender (Neutral)
    # 50 possessions, 20 pts, 15 FGA, 2 FTA -> TS% = 62.9%, PTS/75 = 30.0
    m_normal = PlayerMatchupStats(
        season_id=season.id,
        off_player_id=luka.id,
        def_player_id=normal_def.id,
        gp=4,
        matchup_min=15.0,
        partial_poss=50.0,
        player_pts=20.0,
        matchup_ast=4.0,
        matchup_tov=2.0,
        matchup_fga=15.0,
        matchup_fta=2.0,
        matchup_fgm=7.0,
        pts_per_75=30.0,
        ast_per_75=6.0,
        tov_per_75=3.0,
        ts_pct=62.9,
    )

    db_session.add_all([m_caruso, m_gobert, m_normal])
    db_session.commit()

    service = MatchupService(db_session)
    analysis = service.analyze_player_matchups(player_id=luka.id, min_possessions=10.0)

    # Baseline should aggregate all 150 possessions, 75 pts -> 37.5 PTS/75
    assert analysis.player_id == luka.id
    assert analysis.baseline.total_possessions == 150.0
    assert analysis.baseline.pts_per_75 == 37.5

    # Check classifications
    stopper_names = [s.defender_name for s in analysis.top_stoppers]
    assert "Alex Caruso" in stopper_names

    target_names = [t.defender_name for t in analysis.top_targets]
    assert "Rudy Gobert" in target_names

    # Check item details for Caruso
    caruso_item = next(i for i in analysis.matchups if i.defender_name == "Alex Caruso")
    assert caruso_item.classification == "kryptonite"
    assert caruso_item.delta_pts < 0  # significantly below baseline

    # Check item details for Gobert
    gobert_item = next(i for i in analysis.matchups if i.defender_name == "Rudy Gobert")
    assert gobert_item.classification == "mismatch_exploited"
    assert gobert_item.delta_pts > 0  # significantly above baseline


def test_matchup_api_endpoints(client, db_session: Session):
    # Setup player and matchup
    luka = Player(id=1629029, full_name="Luka Doncic")
    caruso = Player(id=1627936, full_name="Alex Caruso")
    season = Season(id=1, season_label="2023-24")
    db_session.add_all([luka, caruso, season])
    db_session.commit()

    matchup = PlayerMatchupStats(
        season_id=season.id,
        off_player_id=luka.id,
        def_player_id=caruso.id,
        gp=3,
        matchup_min=12.0,
        partial_poss=40.0,
        player_pts=12.0,
        matchup_ast=3.0,
        matchup_tov=1.0,
        matchup_fga=10.0,
        matchup_fta=2.0,
        matchup_fgm=4.0,
        pts_per_75=22.5,
        ast_per_75=5.6,
        tov_per_75=1.9,
        ts_pct=55.1,
    )
    db_session.add(matchup)
    db_session.commit()

    # 1. Test get by player_id
    response = client.get(f"/api/v1/matchups/player/{luka.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["player_name"] == "Luka Doncic"
    assert "baseline" in data
    assert len(data["matchups"]) == 1
    assert data["matchups"][0]["defender_name"] == "Alex Caruso"

    # 2. Test search by name
    response_search = client.get("/api/v1/matchups/search?name=Luka")
    assert response_search.status_code == 200
    data_search = response_search.json()
    assert data_search["player_id"] == luka.id

    # 3. Test non-existent player
    response_not_found = client.get("/api/v1/matchups/player/999999")
    assert response_not_found.status_code == 404

    # 4. Test non-existent search name
    response_search_missing = client.get("/api/v1/matchups/search?name=UnknownSuperstar")
    assert response_search_missing.status_code == 404
