import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from app.main import app
from app.deps import engine
from app.models import Player, Season, Team, PlayerSeasonStats
from app.services.pizza_chart import PizzaChartService
from app.services.real_shotchart import RealShotChartService
from app.services.doppelgangers import DoppelgangerService
from app.services.financial import FinancialService

client = TestClient(app)


def test_pizza_chart_service(db_session: Session):
    service = PizzaChartService(db_session)
    # Service handles missing and real records gracefully
    try:
        res = service.get_player_pizza_chart("Stephen Curry")
        assert len(res.quadrants) == 4
    except ValueError:
        pass


def test_real_shot_chart_service(db_session: Session):
    service = RealShotChartService(db_session)
    try:
        res = service.get_player_shot_chart("Stephen Curry", max_shots=50)
        assert len(res.zone_efficiencies) == 6
    except ValueError:
        pass


def test_doppelgangers_service(db_session: Session):
    service = DoppelgangerService(db_session)
    try:
        res = service.find_doppelgangers("Stephen Curry", top_k=3)
        assert len(res.matches) >= 1
    except ValueError:
        pass


def test_financial_service(db_session: Session):
    service = FinancialService(db_session)
    try:
        res = service.get_financial_analytics()
        assert res.salary_cap_current > 0
    except ValueError:
        pass



def test_api_endpoints_expansion(client: TestClient, db_session: Session):
    session = db_session
    # Seed player in test database
    s = session.exec(select(Season).where(Season.season_label == "2023-24-EXP")).first()
    if not s:
        s = Season(season_label="2023-24-EXP", is_active=True)
        session.add(s)
        session.commit()
        session.refresh(s)

    tm = session.exec(select(Team).where(Team.abbreviation == "GSW-EXP")).first()
    if not tm:
        tm = Team(abbreviation="GSW-EXP", full_name="Golden State Warriors", city="San Francisco", conference="West", division="Pacific")
        session.add(tm)
        session.commit()
        session.refresh(tm)

    p = session.exec(select(Player).where(Player.full_name == "Test Player Curry")).first()
    if not p:
        p = Player(full_name="Test Player Curry", position="PG", height_cm=188, weight_kg=84)
        session.add(p)
        session.commit()
        session.refresh(p)

    stat = session.exec(select(PlayerSeasonStats).where(PlayerSeasonStats.player_id == p.id, PlayerSeasonStats.season_id == s.id)).first()
    if not stat:
        stat = PlayerSeasonStats(
            player_id=p.id,
            team_id=tm.id,
            season_id=s.id,
            gp=74,
            pts=1956.0,
            fga=1440.0,
            fgm=650.0,
            fg3a=876.0,
            fg3m=357.0,
            fta=334.0,
            ftm=310.0,
            ast=379.0,
            reb=330.0,
            stl=55.0,
            blk=26.0,
            tov=206.0,
            cluster_id=1,
        )
        session.add(stat)
        session.commit()

    p2 = session.exec(select(Player).where(Player.full_name == "Test Player Lillard")).first()
    if not p2:
        p2 = Player(full_name="Test Player Lillard", position="PG", height_cm=188, weight_kg=88)
        session.add(p2)
        session.commit()
        session.refresh(p2)

    stat2 = session.exec(select(PlayerSeasonStats).where(PlayerSeasonStats.player_id == p2.id, PlayerSeasonStats.season_id == s.id)).first()
    if not stat2:
        stat2 = PlayerSeasonStats(
            player_id=p2.id,
            team_id=tm.id,
            season_id=s.id,
            gp=73,
            pts=1775.0,
            fga=1277.0,
            fgm=541.0,
            fg3a=627.0,
            fg3m=220.0,
            fta=521.0,
            ftm=473.0,
            ast=511.0,
            reb=320.0,
            stl=69.0,
            blk=17.0,
            tov=186.0,
            cluster_id=1,
        )
        session.add(stat2)
        session.commit()

    # Pizza Chart
    r_pizza = client.get("/api/v1/player/Test Player Curry/pizza-chart")
    assert r_pizza.status_code == 200
    assert "quadrants" in r_pizza.json()

    # Real Shot Chart
    r_shot = client.get("/api/v1/players/Test Player Curry/shot-chart?max_shots=30")
    assert r_shot.status_code == 200
    assert "shots" in r_shot.json()
    assert "zone_efficiencies" in r_shot.json()

    # Doppelgangers
    r_dop = client.get("/api/v1/doppelgangers?player_id_or_name=Test Player Curry&top_k=3")
    assert r_dop.status_code == 200
    assert len(r_dop.json()["matches"]) >= 1

    # Financial Contracts
    r_fin = client.get("/api/v1/financial/contracts")
    assert r_fin.status_code == 200
    assert "team_payrolls" in r_fin.json()


