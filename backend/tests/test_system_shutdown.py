from fastapi.testclient import TestClient

from app.api.v1 import system

VALID_HEADERS = {
    "Origin": "http://localhost:38920",
    "Host": "localhost:38921",
}


def test_shutdown_spawns_detached_stop_script_on_linux(client: TestClient, monkeypatch):
    calls = []
    monkeypatch.setattr(system.sys, "platform", "linux")
    monkeypatch.setattr(system.subprocess, "Popen", lambda cmd, **kwargs: calls.append((cmd, kwargs)))
    response = client.post("/api/v1/system/shutdown", headers=VALID_HEADERS)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    (cmd, kwargs), = calls
    assert cmd[0] == "bash" and cmd[1].endswith("stop_services_wsl.sh")
    assert kwargs["start_new_session"] is True


def test_shutdown_reports_error_when_script_is_missing(client: TestClient, monkeypatch):
    monkeypatch.setattr(system.sys, "platform", "linux")
    monkeypatch.setattr(system.Path, "exists", lambda self: False)
    response = client.post("/api/v1/system/shutdown", headers=VALID_HEADERS)
    assert response.status_code == 200
    assert response.json()["status"] == "error"


def test_shutdown_allowed_origin_and_host_succeeds(client: TestClient, monkeypatch):
    calls = []
    monkeypatch.setattr(system.sys, "platform", "linux")
    monkeypatch.setattr(system.subprocess, "Popen", lambda cmd, **kwargs: calls.append((cmd, kwargs)))
    response = client.post(
        "/api/v1/system/shutdown",
        headers={"Origin": "http://127.0.0.1:38920", "Host": "127.0.0.1:38921"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert len(calls) == 1


def test_shutdown_allowed_referer_when_origin_missing(client: TestClient, monkeypatch):
    calls = []
    monkeypatch.setattr(system.sys, "platform", "linux")
    monkeypatch.setattr(system.subprocess, "Popen", lambda cmd, **kwargs: calls.append((cmd, kwargs)))
    response = client.post(
        "/api/v1/system/shutdown",
        headers={"Referer": "http://localhost:38920/props", "Host": "localhost:38921"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert len(calls) == 1


def test_shutdown_rejects_missing_origin(client: TestClient, monkeypatch):
    calls = []
    monkeypatch.setattr(system.subprocess, "Popen", lambda cmd, **kwargs: calls.append((cmd, kwargs)))
    response = client.post(
        "/api/v1/system/shutdown",
        headers={"Host": "localhost:38921"},
    )
    assert response.status_code == 403
    assert len(calls) == 0


def test_shutdown_rejects_foreign_origin(client: TestClient, monkeypatch):
    calls = []
    monkeypatch.setattr(system.subprocess, "Popen", lambda cmd, **kwargs: calls.append((cmd, kwargs)))
    response = client.post(
        "/api/v1/system/shutdown",
        headers={"Origin": "https://evil.com", "Host": "localhost:38921"},
    )
    assert response.status_code == 403
    assert len(calls) == 0


def test_shutdown_rejects_foreign_referer_when_origin_missing(client: TestClient, monkeypatch):
    calls = []
    monkeypatch.setattr(system.subprocess, "Popen", lambda cmd, **kwargs: calls.append((cmd, kwargs)))
    response = client.post(
        "/api/v1/system/shutdown",
        headers={"Referer": "https://evil.com/phishing", "Host": "localhost:38921"},
    )
    assert response.status_code == 403
    assert len(calls) == 0


def test_shutdown_rejects_foreign_host(client: TestClient, monkeypatch):
    calls = []
    monkeypatch.setattr(system.subprocess, "Popen", lambda cmd, **kwargs: calls.append((cmd, kwargs)))
    response = client.post(
        "/api/v1/system/shutdown",
        headers={"Origin": "http://localhost:38920", "Host": "attacker.com:38921"},
    )
    assert response.status_code == 403
    assert len(calls) == 0

