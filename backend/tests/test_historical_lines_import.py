from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Tuple

import pytest
from sqlalchemy import func, select
from sqlmodel import Session

from app.analytics import historical_lines as hl
from app.models import HistoricalGameLine, Team
from app.services import historical_lines as service
from app.services.elo_service import HistoricalGame
from tests.synthetic_league import insert_league, make_league


@pytest.fixture
def league_setup(db_session: Session) -> Tuple[List[HistoricalGame], Dict[int, str], Dict[int, str]]:
    games = make_league(n_seasons=2, n_teams=4, seed=3)
    rekeyed = insert_league(db_session, games)
    team_abbr = {team_id: abbr for abbr, team_id in service.canonical_team_ids(db_session).items()}
    season_labels = service.season_labels(db_session)
    return rekeyed, team_abbr, season_labels


def _build_line(
    game: HistoricalGame,
    team_abbr: Dict[int, str],
    season_labels: Dict[int, str],
    source: str = hl.SOURCE_SBRO,
    source_row_key: str = "row-1",
    close_spread: float = -4.0,
    open_spread: float = -3.5,
    close_total: float = 210.0,
    open_total: float = 209.0,
    neutral_site: bool = False,
    home_score: int = None,
    away_score: int = None,
    game_date: date = None,
    home_abbr: str = None,
    away_abbr: str = None,
) -> hl.ParsedLine:
    h_abbr = home_abbr if home_abbr is not None else team_abbr[game.home_team_id]
    a_abbr = away_abbr if away_abbr is not None else team_abbr[game.away_team_id]
    return hl.ParsedLine(
        source=source,
        source_row_key=source_row_key,
        season_label=season_labels[game.season_id],
        game_date=game_date if game_date is not None else game.game_date,
        home_abbr=h_abbr,
        away_abbr=a_abbr,
        home_name_raw=h_abbr or "unknown",
        away_name_raw=a_abbr or "unknown",
        neutral_site=neutral_site,
        open_spread_home=open_spread,
        close_spread_home=close_spread,
        open_total=open_total,
        close_total=close_total,
        close_moneyline_home=-150,
        close_moneyline_away=130,
        home_score=game.home_pts if home_score is None else home_score,
        away_score=game.away_pts if away_score is None else away_score,
    )


def test_import_lines_dry_run(db_session: Session, league_setup):
    rekeyed, team_abbr, season_labels = league_setup
    lines = [
        _build_line(rekeyed[0], team_abbr, season_labels, source_row_key="key-0"),
        _build_line(rekeyed[1], team_abbr, season_labels, source_row_key="key-1"),
        _build_line(rekeyed[2], team_abbr, season_labels, source_row_key="key-2"),
    ]

    report = service.import_lines(db_session, lines, {}, dry_run=True)

    count = db_session.execute(select(func.count(HistoricalGameLine.id))).scalar_one()
    assert count == 0
    assert report.rows_to_write == 3
    assert report.matched_to_log[hl.SOURCE_SBRO] == 3


def test_import_lines_upsert_idempotent(db_session: Session, league_setup):
    rekeyed, team_abbr, season_labels = league_setup
    lines = [
        _build_line(rekeyed[0], team_abbr, season_labels, source_row_key="key-0", close_spread=-3.0),
        _build_line(rekeyed[1], team_abbr, season_labels, source_row_key="key-1", close_spread=-4.0),
        _build_line(rekeyed[2], team_abbr, season_labels, source_row_key="key-2", close_spread=-5.0),
    ]

    report1 = service.import_lines(db_session, lines, {}, dry_run=False)
    db_session.commit()

    assert report1.rows_written == 3
    count1 = db_session.execute(select(func.count(HistoricalGameLine.id))).scalar_one()
    assert count1 == 3

    # check nba_game_id stored equals the game's game_id
    stored_rows = db_session.execute(select(HistoricalGameLine).order_by(HistoricalGameLine.source_row_key)).scalars().all()
    assert stored_rows[0].nba_game_id == rekeyed[0].game_id

    # call again with one line's close_spread_home changed -> still 3 rows, stored value updated
    lines_updated = [
        lines[0],
        lines[1],
        replace(lines[2], close_spread_home=-8.5),
    ]
    report2 = service.import_lines(db_session, lines_updated, {}, dry_run=False)
    db_session.commit()

    count2 = db_session.execute(select(func.count(HistoricalGameLine.id))).scalar_one()
    assert count2 == 3

    updated_row = db_session.execute(
        select(HistoricalGameLine).where(HistoricalGameLine.source_row_key == "key-2")
    ).scalar_one()
    assert updated_row.close_spread_home == Decimal("-8.5")


def test_import_lines_score_mismatch(db_session: Session, league_setup):
    rekeyed, team_abbr, season_labels = league_setup
    line = _build_line(rekeyed[0], team_abbr, season_labels, home_score=rekeyed[0].home_pts + 10)

    report = service.import_lines(db_session, [line], {}, dry_run=False)
    db_session.commit()

    assert report.score_mismatch[hl.SOURCE_SBRO] == 1
    assert report.rows_written == 1


def test_import_lines_unmatched_teams(db_session: Session, league_setup):
    rekeyed, team_abbr, season_labels = league_setup
    line = _build_line(rekeyed[0], team_abbr, season_labels, home_abbr="XXX")

    report = service.import_lines(db_session, [line], {}, dry_run=False)
    db_session.commit()

    assert report.unmatched_teams[f"{hl.SOURCE_SBRO}:XXX"] == 1
    assert report.rows_to_write == 0
    assert report.rows_written == 0


def test_import_lines_date_shifted(db_session: Session, league_setup):
    rekeyed, team_abbr, season_labels = league_setup

    # dated one day after with identical score -> matched (report.date_shifted == 1)
    target = rekeyed[1]
    shifted_same_score = _build_line(
        target,
        team_abbr,
        season_labels,
        game_date=target.game_date + timedelta(days=1),
    )
    rep1 = service.import_lines(db_session, [shifted_same_score], {}, dry_run=True)
    assert rep1.date_shifted == 1
    assert rep1.matched_to_log[hl.SOURCE_SBRO] == 1

    # dated one day after with different score -> not matched (report.unmatched_to_log == 1)
    shifted_diff_score = _build_line(
        target,
        team_abbr,
        season_labels,
        game_date=target.game_date + timedelta(days=1),
        home_score=target.home_pts + 5,
    )
    rep2 = service.import_lines(db_session, [shifted_diff_score], {}, dry_run=True)
    assert rep2.unmatched_to_log[hl.SOURCE_SBRO] == 1


def test_import_lines_neutral_swapped(db_session: Session, league_setup):
    rekeyed, team_abbr, season_labels = league_setup
    target = rekeyed[0]

    # neutral_site=True with home/away swapped and spreads/scores from the swapped side
    swapped_line = hl.ParsedLine(
        source=hl.SOURCE_SBRO,
        source_row_key="key-neutral-swap",
        season_label=season_labels[target.season_id],
        game_date=target.game_date,
        home_abbr=team_abbr[target.away_team_id],
        away_abbr=team_abbr[target.home_team_id],
        home_name_raw=team_abbr[target.away_team_id],
        away_name_raw=team_abbr[target.home_team_id],
        neutral_site=True,
        open_spread_home=3.5,
        close_spread_home=4.5,
        open_total=210.0,
        close_total=212.0,
        close_moneyline_home=140,
        close_moneyline_away=-160,
        home_score=target.away_pts,
        away_score=target.home_pts,
    )

    report = service.import_lines(db_session, [swapped_line], {}, dry_run=False)
    db_session.commit()

    assert report.neutral_swapped == 1
    assert report.rows_written == 1

    stored = db_session.execute(
        select(HistoricalGameLine).where(HistoricalGameLine.source_row_key == "key-neutral-swap")
    ).scalar_one()

    # stored row has home_team_id == log's home team and close_spread_home sign flipped
    assert stored.home_team_id == target.home_team_id
    assert stored.away_team_id == target.away_team_id
    assert stored.close_spread_home == Decimal("-4.5")


def test_merge_lines(league_setup):
    rekeyed, team_abbr, season_labels = league_setup
    g = rekeyed[0]

    # same game from SBRO and Kaggle with equal close spreads -> one merged entry, SBRO chosen, agree_close_spread == 1
    line_sbro = _build_line(g, team_abbr, season_labels, source=hl.SOURCE_SBRO, close_spread=-3.0)
    line_kaggle = _build_line(g, team_abbr, season_labels, source=hl.SOURCE_KAGGLE, close_spread=-3.0)
    item_sbro = service.ResolvedLine(line_sbro, g.home_team_id, g.away_team_id)
    item_kaggle = service.ResolvedLine(line_kaggle, g.home_team_id, g.away_team_id)

    merged, cross_rep = service.merge_lines([item_sbro, item_kaggle])
    assert len(merged) == 1
    assert next(iter(merged.values())).line.source == hl.SOURCE_SBRO
    assert cross_rep.agree_close_spread == 1
    assert cross_rep.disagree_close_spread == 0

    # with different close spreads -> disagree_close_spread == 1 and still SBRO chosen
    line_kaggle_diff = _build_line(g, team_abbr, season_labels, source=hl.SOURCE_KAGGLE, close_spread=-4.5)
    item_kaggle_diff = service.ResolvedLine(line_kaggle_diff, g.home_team_id, g.away_team_id)

    merged2, cross_rep2 = service.merge_lines([item_sbro, item_kaggle_diff])
    assert len(merged2) == 1
    assert next(iter(merged2.values())).line.source == hl.SOURCE_SBRO
    assert cross_rep2.disagree_close_spread == 1


def test_canonical_team_ids(db_session: Session, league_setup):
    # insert an extra Team "NJN" and check it is absent
    extra_team = Team(
        abbreviation="NJN",
        full_name="New Jersey Nets",
        city="East Rutherford",
        conference="E",
        division="Atlantic",
    )
    db_session.add(extra_team)
    db_session.flush()

    teams = service.canonical_team_ids(db_session)
    assert "NJN" not in teams
    assert all(abbr in service.CURRENT_TEAMS for abbr in teams)


def test_import_report_format():
    report = service.ImportReport()
    formatted = report.format()
    assert "Historical lines import" in formatted
