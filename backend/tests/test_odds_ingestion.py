from datetime import date, datetime, timezone

import pytest
from sqlmodel import select

from app.models import BetSide, Game, MarketType, OddsHistory, Player, Season, Sportsbook, Team
from app.services.odds_api_service import GameQuote, OddsQuote
from app.services.odds_ingestion import (
    IngestResult,
    OddsIngestionService,
    canonical_team_name,
    parse_api_datetime,
)

CAPTURED = datetime(2026, 10, 20, 20, 30, tzinfo=timezone.utc)


@pytest.fixture
def world(db_session):
    db_session.add(Season(season_label="2025-26", start_date=date(2025, 10, 21), end_date=date(2026, 6, 30)))
    db_session.add(Season(season_label="2026-27", start_date=date(2026, 10, 20), end_date=date(2027, 6, 30), is_active=True))
    for abbr, full in [("BOS", "Boston Celtics"), ("LAC", "LA Clippers"), ("LAL", "Los Angeles Lakers")]:
        db_session.add(Team(abbreviation=abbr, full_name=full, city="", conference="", division=""))
    db_session.add(Player(id=1, full_name="Luka Doncic"))
    db_session.add(Player(id=2, full_name="Jaylen Brown"))
    db_session.commit()
    return OddsIngestionService(db_session)


def _gq(book="pinnacle", market="h2h", side="home", line=None, price=-150, event="e1",
        home="Boston Celtics", away="Los Angeles Clippers", updated="2026-10-20T20:00:00Z"):
    return GameQuote(
        event_id=event, commence_time="2026-10-21T00:00:00Z", home_team=home, away_team=away,
        bookmaker_key=book, bookmaker_title=book.title(), market_key=market, side=side, line=line,
        price_american=price, book_last_update=updated,
    )


def _pq(player="Luka Dončić", side="over", line=27.5, price=-115, book="draftkings", event="e1",
        market="player_points", updated="2026-10-20T20:00:00Z"):
    return OddsQuote(
        event_id=event, bookmaker_key=book, market_key=market, stat_type="PTS", player_name=player,
        side=side, line=line, price_american=price, book_last_update=updated,
    )


def _count(session):
    return len(session.exec(select(OddsHistory)).all())


# --- teams ---------------------------------------------------------------------

def test_team_aliases_resolve_to_the_same_franchise():
    assert canonical_team_name("LA Clippers") == "Los Angeles Clippers"
    assert canonical_team_name("Los Angeles Clippers") == "Los Angeles Clippers"
    assert canonical_team_name("los angeles lakers") == "Los Angeles Lakers"
    assert canonical_team_name("Springfield Isotopes") is None


def test_clippers_resolve_whether_the_db_says_la_or_los_angeles(world):
    # DB row is "LA Clippers"; the API may use either spelling.
    assert world.resolve_team("Los Angeles Clippers").abbreviation == "LAC"
    assert world.resolve_team("LA Clippers").abbreviation == "LAC"
    assert world.resolve_team("Atlantis Dolphins") is None


def test_team_resolves_by_name_when_abbreviation_is_nonstandard(db_session):
    db_session.add(Season(season_label="2026-27", is_active=True))
    db_session.add(Team(abbreviation="PHO", full_name="Phoenix Suns", city="", conference="", division=""))
    db_session.add(Team(abbreviation="XXX", full_name="Los Angeles Clippers", city="", conference="", division=""))
    db_session.commit()
    service = OddsIngestionService(db_session)

    assert service.resolve_team("Phoenix Suns").abbreviation == "PHO"
    assert service.resolve_team("LA Clippers").abbreviation == "XXX"


# --- games, seasons, sportsbooks ---------------------------------------------------

def test_upsert_game_uses_active_season_and_is_idempotent(world, db_session):
    when = datetime(2026, 10, 21, 0, 0, tzinfo=timezone.utc)
    game = world.upsert_game("e1", when, "Boston Celtics", "LA Clippers")

    assert game is not None
    season = db_session.get(Season, game.season_id)
    assert season.season_label == "2026-27"
    assert world.upsert_game("e1", when, "Boston Celtics", "LA Clippers").id == game.id
    assert len(db_session.exec(select(Game)).all()) == 1


def test_upsert_game_updates_a_rescheduled_tipoff(world, db_session):
    first = datetime(2026, 10, 21, 0, 0, tzinfo=timezone.utc)
    later = datetime(2026, 10, 21, 2, 0, tzinfo=timezone.utc)
    world.upsert_game("e1", first, "Boston Celtics", "LA Clippers")
    game = OddsIngestionService(db_session).upsert_game("e1", later, "Boston Celtics", "LA Clippers")

    assert game.commence_time.replace(tzinfo=timezone.utc) == later


def test_season_falls_back_to_date_range_when_active_season_does_not_cover_the_game(db_session):
    db_session.add(Season(season_label="2025-26", start_date=date(2025, 10, 21), end_date=date(2026, 6, 30), is_active=True))
    db_session.add(Season(season_label="2024-25", start_date=date(2024, 10, 22), end_date=date(2025, 6, 30)))
    db_session.commit()
    service = OddsIngestionService(db_session)

    sid = service.resolve_season_id(datetime(2025, 1, 15, tzinfo=timezone.utc))
    assert db_session.get(Season, sid).season_label == "2024-25"


def test_season_falls_back_to_latest_when_nothing_matches(db_session):
    db_session.add(Season(season_label="2023-24", start_date=date(2023, 10, 24), end_date=date(2024, 6, 30)))
    db_session.add(Season(season_label="2024-25", start_date=date(2024, 10, 22), end_date=date(2025, 6, 30)))
    db_session.commit()
    service = OddsIngestionService(db_session)

    sid = service.resolve_season_id(datetime(2030, 1, 1, tzinfo=timezone.utc))
    assert db_session.get(Season, sid).season_label == "2024-25"


def test_unresolvable_team_skips_the_game_without_crashing_the_batch(world, db_session):
    quotes = [
        _gq(event="bad", away="Atlantis Dolphins"),
        _gq(event="good", side="home", price=-150),
    ]

    result = world.ingest_game_quotes(quotes, CAPTURED)

    assert result.inserted == 1
    assert result.skipped_unmatched == 1
    assert [g.provider_event_id for g in db_session.exec(select(Game)).all()] == ["good"]


def test_sportsbook_flags_pinnacle_as_sharp_eu_and_others_as_us(world):
    pinnacle = world.upsert_sportsbook("pinnacle", "Pinnacle")
    dk = world.upsert_sportsbook("draftkings", "DraftKings")

    assert (pinnacle.is_sharp, pinnacle.region) == (True, "eu")
    assert (dk.is_sharp, dk.region) == (False, "us")
    assert world.upsert_sportsbook("pinnacle", "Pinnacle").id == pinnacle.id


# --- game line ingestion -----------------------------------------------------------------

def test_game_quotes_are_stored_with_enums_and_lines(world, db_session):
    quotes = [
        _gq(market="h2h", side="away", price=130),
        _gq(market="spreads", side="home", line=-3.5, price=-105),
        _gq(market="totals", side="over", line=221.5, price=-110),
    ]

    result = world.ingest_game_quotes(quotes, CAPTURED)

    assert result == IngestResult(inserted=3)
    rows = {(r.market, r.side): r for r in db_session.exec(select(OddsHistory)).all()}
    assert rows[(MarketType.h2h, BetSide.away)].line is None
    assert rows[(MarketType.h2h, BetSide.away)].player_id is None
    assert float(rows[(MarketType.spreads, BetSide.home)].line) == -3.5
    assert float(rows[(MarketType.totals, BetSide.over)].line) == 221.5
    assert rows[(MarketType.h2h, BetSide.away)].captured_at is not None


def test_ingesting_the_same_game_quotes_twice_inserts_nothing_the_second_time(world, db_session):
    quotes = [
        _gq(market="h2h", side="home", price=-150),
        _gq(market="h2h", side="away", price=130),
        _gq(market="spreads", side="home", line=-3.5, price=-105),
    ]

    first = world.ingest_game_quotes(quotes, CAPTURED)
    second = OddsIngestionService(db_session).ingest_game_quotes(quotes, CAPTURED)

    assert first.inserted == 3
    assert (second.inserted, second.skipped_duplicate) == (0, 3)
    assert _count(db_session) == 3


def test_a_moved_line_or_new_book_update_is_a_new_row(world, db_session):
    world.ingest_game_quotes([_gq(market="spreads", side="home", line=-3.5, price=-105)], CAPTURED)
    moved = _gq(market="spreads", side="home", line=-4.0, price=-110, updated="2026-10-20T20:30:00Z")

    result = world.ingest_game_quotes([moved], CAPTURED)

    assert result.inserted == 1
    assert _count(db_session) == 2


def test_duplicates_inside_one_batch_count_as_duplicates(world, db_session):
    quote = _gq(market="h2h", side="home", price=-150)

    result = world.ingest_game_quotes([quote, quote], CAPTURED)

    assert (result.inserted, result.skipped_duplicate) == (1, 1)


def test_invalid_quotes_are_skipped_and_counted(world, db_session):
    quotes = [
        _gq(price=-50),  # between -100 and +100: not a valid American price
        _gq(market="player_points"),  # not a game market
        _gq(updated=None),  # no book timestamp: cannot build a trustworthy key
        _gq(side="home", price=-150),
    ]

    result = world.ingest_game_quotes(quotes, CAPTURED)

    assert (result.inserted, result.skipped_invalid) == (1, 3)


# --- prop ingestion --------------------------------------------------------------------------

def test_prop_quotes_match_players_ignoring_diacritics(world, db_session):
    world.ingest_game_quotes([_gq()], CAPTURED)

    result = world.ingest_prop_quotes("e1", [_pq(player="Luka Dončić"), _pq(player="Luka Dončić", side="under", price=-105)], CAPTURED)

    assert result.inserted == 2
    rows = [r for r in db_session.exec(select(OddsHistory)).all() if r.market == MarketType.player_points]
    assert {r.player_id for r in rows} == {1}
    assert {r.side for r in rows} == {BetSide.over, BetSide.under}


def test_unmatched_players_are_skipped_and_counted(world, db_session):
    world.ingest_game_quotes([_gq()], CAPTURED)

    result = world.ingest_prop_quotes("e1", [_pq(player="Jaylen Brown"), _pq(player="Rookie Nobody")], CAPTURED)

    assert (result.inserted, result.skipped_unmatched) == (1, 1)


def test_ambiguous_player_names_are_never_guessed(world, db_session):
    db_session.add(Player(id=3, full_name="Jaylen Brown"))
    db_session.commit()

    service = OddsIngestionService(db_session)
    service.ingest_game_quotes([_gq()], CAPTURED)
    result = service.ingest_prop_quotes("e1", [_pq(player="Jaylen Brown")], CAPTURED)
    assert (result.inserted, result.skipped_unmatched) == (0, 1)


def test_prop_quotes_for_an_unknown_event_are_skipped_not_fatal(world):
    result = world.ingest_prop_quotes("ghost", [_pq(event="ghost"), _pq(event="ghost", side="under")], CAPTURED)

    assert (result.inserted, result.skipped_unmatched) == (0, 2)


def test_ingesting_prop_quotes_twice_is_idempotent(world, db_session):
    world.ingest_game_quotes([_gq()], CAPTURED)
    quotes = [_pq(), _pq(side="under", price=-105)]

    first = world.ingest_prop_quotes("e1", quotes, CAPTURED)
    second = OddsIngestionService(db_session).ingest_prop_quotes("e1", quotes, CAPTURED)

    assert first.inserted == 2
    assert (second.inserted, second.skipped_duplicate) == (0, 2)


def test_parse_api_datetime_handles_zulu_naive_and_garbage():
    assert parse_api_datetime("2026-10-21T00:00:00Z") == datetime(2026, 10, 21, tzinfo=timezone.utc)
    assert parse_api_datetime("2026-10-21T00:00:00") == datetime(2026, 10, 21, tzinfo=timezone.utc)
    assert parse_api_datetime("not a date") is None
    assert parse_api_datetime(None) is None
