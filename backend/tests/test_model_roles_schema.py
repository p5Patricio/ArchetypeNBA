"""Schema-level rules of the model registry: roles, the evaluation audit table and per-model Elo rows."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.models import ModelEvaluation, ModelVersion, Season, Team, TeamEloRating


def _model(session, name, version="1", **kw):
    row = ModelVersion(name=name, version=version, **kw)
    session.add(row)
    session.commit()
    return row


def test_a_new_model_version_is_a_challenger_by_default(db_session):
    row = _model(db_session, "elo_538")

    assert row.role == "challenger"
    assert row.promoted_at is None and row.retired_at is None and row.parent_id is None and row.notes is None


def test_only_one_champion_is_allowed(db_session):
    _model(db_session, "elo_538", "1.1", role="champion")

    db_session.add(ModelVersion(name="elo_538", version="2.0", role="champion"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # challengers and retired models are unlimited
    for i in range(3):
        _model(db_session, "elo_538", f"c{i}", role="challenger")
        _model(db_session, "elo_538", f"r{i}", role="retired")
    assert len(db_session.exec(select(ModelVersion)).all()) == 7


def test_a_new_champion_is_possible_once_the_old_one_is_demoted(db_session):
    old = _model(db_session, "elo_538", "1.1", role="champion")
    new = _model(db_session, "elo_538", "2.0", role="challenger", parent_id=old.id)

    old.role = "challenger"
    db_session.add(old)
    db_session.commit()
    new.role = "champion"
    new.promoted_at = datetime(2026, 10, 20, tzinfo=timezone.utc)
    db_session.add(new)
    db_session.commit()

    champions = db_session.exec(select(ModelVersion).where(ModelVersion.role == "champion")).all()
    assert [c.version for c in champions] == ["2.0"]
    assert champions[0].parent_id == old.id


def test_an_unknown_role_is_rejected(db_session):
    db_session.add(ModelVersion(name="x", version="1", role="boss"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_benchmark_role_is_accepted(db_session):
    row = _model(
        db_session,
        "market_pinnacle",
        "1",
        role="benchmark",
        notes="Pinnacle's de-vigged probability, not a forecasting model",
    )
    assert row.role == "benchmark"
    assert row.notes == "Pinnacle's de-vigged probability, not a forecasting model"
    assert row.id is not None


def test_migration_downgrade_check_raises_when_benchmark_rows_exist(db_session):
    from unittest.mock import MagicMock, patch
    import importlib.util
    import os
    import sqlalchemy as sa

    _model(db_session, "market_pinnacle", "1", role="benchmark")
    with db_session.get_bind().connect() as conn:
        count = conn.execute(sa.text("SELECT count(*) FROM model_version WHERE role = 'benchmark'")).scalar()
    assert count == 1

    # Load the migration module dynamically and test downgrade() with mocked op
    mig_path = os.path.join(
        os.path.dirname(__file__),
        "../alembic/versions/a2c4e6f8b1d3_add_benchmark_model_role.py",
    )
    spec = importlib.util.spec_from_file_location("mig_a2c4e6f8b1d3", mig_path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    mock_conn = MagicMock()
    mock_conn.execute.return_value.scalar.return_value = 1
    with patch.object(mig.op, "get_bind", return_value=mock_conn):
        with pytest.raises(RuntimeError, match="Cannot downgrade: 1 model_version row\\(s\\) with role='benchmark' exist"):
            mig.downgrade()

    mock_conn.execute.return_value.scalar.return_value = 0
    with patch.object(mig.op, "get_bind", return_value=mock_conn), \
         patch.object(mig.op, "drop_constraint") as mock_drop, \
         patch.object(mig.op, "create_check_constraint") as mock_create:
        mig.downgrade()
        mock_drop.assert_called_once_with('ck_model_version_role', 'model_version', type_='check')
        mock_create.assert_called_once()


def test_the_single_champion_index_is_partial_and_unique(db_session):
    indexes = {ix["name"]: ix for ix in inspect(db_session.get_bind()).get_indexes("model_version")}
    assert indexes["uq_model_version_single_champion"]["unique"]


def test_a_model_evaluation_round_trips_with_its_metrics(db_session):
    champion = _model(db_session, "elo_538", "1.1", role="champion")
    challenger = _model(db_session, "elo_538", "2.0")
    metrics = {"seed": 7, "log_loss_diff": {"mean": 0.004, "ci_low": -0.001, "ci_high": 0.009}, "n_boot": 2000}

    db_session.add(
        ModelEvaluation(
            champion_id=champion.id,
            challenger_id=challenger.id,
            n_games=212,
            n_market_games=60,
            metrics=metrics,
            decision="keep",
            reason="lower CI bound is not above zero",
        )
    )
    db_session.commit()

    row = db_session.exec(select(ModelEvaluation)).one()
    assert row.id is not None and row.evaluated_at is not None
    assert (row.champion_id, row.challenger_id, row.n_games, row.n_market_games) == (champion.id, challenger.id, 212, 60)
    assert row.metrics == metrics and row.decision == "keep" and row.reason.startswith("lower CI")


def test_a_model_evaluation_rejects_an_unknown_decision(db_session):
    champion = _model(db_session, "elo_538", "1.1", role="champion")
    db_session.add(ModelEvaluation(champion_id=champion.id, challenger_id=champion.id, decision="maybe"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def _rating_row(model_id, team, season, game_id="0022500001"):
    return TeamEloRating(model_version_id=model_id, team_id=team.id, season_id=season.id, game_id=game_id,
                         game_date=date(2026, 1, 1))


def test_rating_rows_are_unique_per_model_not_across_models(db_session):
    season = Season(season_label="2025-26")
    team = Team(abbreviation="AAA", full_name="AAA", city="A", conference="East", division="Atlantic")
    db_session.add_all([season, team])
    first, second = _model(db_session, "elo_538", "1.1"), _model(db_session, "elo_538", "2.0")

    db_session.add_all([_rating_row(first.id, team, season), _rating_row(second.id, team, season)])
    db_session.commit()
    assert len(db_session.exec(select(TeamEloRating)).all()) == 2

    db_session.add(_rating_row(first.id, team, season))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_a_rating_row_needs_a_model(db_session):
    season = Season(season_label="2025-26")
    team = Team(abbreviation="AAA", full_name="AAA", city="A", conference="East", division="Atlantic")
    db_session.add_all([season, team])
    db_session.commit()

    db_session.add(TeamEloRating(team_id=team.id, season_id=season.id, game_id="0022500001"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
