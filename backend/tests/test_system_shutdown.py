from fastapi.testclient import TestClient

from app.api.v1 import system


def test_shutdown_spawns_detached_stop_script_on_linux(client: TestClient, monkeypatch):
    calls = []
    monkeypatch.setattr(system.sys, "platform", "linux")
    monkeypatch.setattr(system.subprocess, "Popen", lambda cmd, **kwargs: calls.append((cmd, kwargs)))
    response = client.post("/api/v1/system/shutdown")
    assert response.json()["status"] == "ok"
    (cmd, kwargs), = calls
    assert cmd[0] == "bash" and cmd[1].endswith("stop_services_wsl.sh")
    assert kwargs["start_new_session"] is True


def test_shutdown_reports_error_when_script_is_missing(client: TestClient, monkeypatch):
    monkeypatch.setattr(system.sys, "platform", "linux")
    monkeypatch.setattr(system.Path, "exists", lambda self: False)
    assert client.post("/api/v1/system/shutdown").json()["status"] == "error"
