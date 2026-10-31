from datetime import datetime, timezone
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models import InjuryEntry, InjuryReportSnapshot


def test_get_latest_injuries_not_found(client: TestClient):
    res = client.get("/api/v1/injuries/latest")
    assert res.status_code == 404
    assert res.json()["detail"] == "No injury report snapshot found"


def test_get_latest_injuries_grouped_and_filter_available(client: TestClient, db_session: Session):
    session = db_session
    now_utc = datetime(2026, 10, 31, 22, 45, 0, tzinfo=timezone.utc)

    snap = InjuryReportSnapshot(
        source="nba_official_pdf",
        report_url="https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-10-31_06_45PM.pdf",
        report_timestamp=now_utc,
        fetched_at=now_utc,
        sha256="abc123456789",
        entries_count=3,
    )
    session.add(snap)
    session.flush()

    e1 = InjuryEntry(
        snapshot_id=snap.id,
        game_date="10/31/2026",
        matchup="POR@UTA",
        team_name="Portland Trail Blazers",
        player_name_raw="Morant, Ja",
        status="Out",
        reason="Hamstring",
        availability_prob=Decimal("0.00"),
    )
    e2 = InjuryEntry(
        snapshot_id=snap.id,
        game_date="10/31/2026",
        matchup="POR@UTA",
        team_name="Portland Trail Blazers",
        player_name_raw="Williams III, Robert",
        status="Available",
        reason="Knee management",
        availability_prob=Decimal("1.00"),
    )
    e3 = InjuryEntry(
        snapshot_id=snap.id,
        game_date="10/31/2026",
        matchup="POR@UTA",
        team_name="Utah Jazz",
        player_name_raw="Castle, Stephon",
        status="Questionable",
        reason="Migraine",
        availability_prob=Decimal("0.50"),
    )
    session.add_all([e1, e2, e3])
    session.commit()

    # 1. Default: exclude Available
    res = client.get("/api/v1/injuries/latest")
    assert res.status_code == 200
    data = res.json()
    assert data["snapshot_id"] == snap.id
    assert data["total_entries_count"] == 3
    assert data["returned_entries_count"] == 2

    por_players = data["teams"].get("Portland Trail Blazers", [])
    assert len(por_players) == 1
    assert por_players[0]["player_name_raw"] == "Morant, Ja"
    assert por_players[0]["status"] == "Out"

    uta_players = data["teams"].get("Utah Jazz", [])
    assert len(uta_players) == 1
    assert uta_players[0]["player_name_raw"] == "Castle, Stephon"

    # 2. With include_available=true: includes Robert Williams III
    res_avail = client.get("/api/v1/injuries/latest?include_available=true")
    assert res_avail.status_code == 200
    data_avail = res_avail.json()
    assert data_avail["returned_entries_count"] == 3

    por_avail = data_avail["teams"].get("Portland Trail Blazers", [])
    assert len(por_avail) == 2
    statuses = {p["status"] for p in por_avail}
    assert statuses == {"Out", "Available"}
