from sqlmodel import Session

from app.models import Player, PlayerSeasonStats, Season, Team
from app.services.financial import FinancialService


def _seed(session: Session, with_empty_newer_season: bool):
    team = Team(abbreviation="AAA", full_name="Team A", city="A", conference="East", division="Atlantic")
    player = Player(full_name="Test Player")
    played = Season(season_label="2025-26", is_active=True)
    session.add_all([team, player, played])
    session.commit()
    session.add(PlayerSeasonStats(player_id=player.id, team_id=team.id, season_id=played.id, gp=40, pts=800.0))
    if with_empty_newer_season:
        session.add(Season(season_label="2026-27", is_active=False))
    session.commit()
    return played


def test_financial_analytics_ignores_newer_season_without_stats(db_session: Session):
    played = _seed(db_session, with_empty_newer_season=True)

    result = FinancialService(db_session).get_financial_analytics()

    assert result.top_salary_contracts, "the season with stats must be used even if a newer empty season exists"
    assert played.season_label == "2025-26"


def test_financial_analytics_without_empty_season_is_unchanged(db_session: Session):
    _seed(db_session, with_empty_newer_season=False)

    assert FinancialService(db_session).get_financial_analytics().top_salary_contracts
