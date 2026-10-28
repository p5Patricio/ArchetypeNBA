import logging
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["system"])

ALLOWED_HOSTNAMES = {"localhost", "127.0.0.1"}


def _extract_origin(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    return raw.rstrip("/")


def verify_shutdown_safety(request: Request) -> None:
    """
    Enforces origin and host safety on the shutdown endpoint:
    (a) Rejects with 403 when the Origin header is missing or not in settings.CORS_ORIGINS
        (falling back to Referer only if Origin is absent).
    (b) Rejects with 403 when the Host header's hostname is not localhost or 127.0.0.1
        (DNS-rebinding guard).
    """
    # (a) Origin / Referer check
    raw_origin = request.headers.get("origin")
    if not raw_origin:
        raw_origin = request.headers.get("referer")

    if not raw_origin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: missing Origin or Referer header",
        )

    origin = _extract_origin(raw_origin)
    allowed_origins = {o.rstrip("/") for o in settings.CORS_ORIGINS}
    if not origin or origin not in allowed_origins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: invalid origin",
        )

    # (b) Host header hostname check
    host_header = request.headers.get("host")
    if not host_header:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: missing Host header",
        )

    hostname = urlparse(f"//{host_header}").hostname
    if not hostname or hostname.lower() not in ALLOWED_HOSTNAMES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: invalid host",
        )


class ShutdownResponse(BaseModel):
    status: str
    message: str


@router.post(
    "/shutdown",
    response_model=ShutdownResponse,
    dependencies=[Depends(verify_shutdown_safety)],
)
def shutdown_services():
    """
    Shuts down both frontend (port 38920) and backend (port 38921) services cleanly.
    Spawns a detached script that waits 1.5 s (so this HTTP response returns to the client)
    before stopping the listeners: scripts/delayed_stop.ps1 on Windows (hidden PowerShell),
    scripts/stop_services_wsl.sh on Linux/WSL.
    """
    # system.py is at backend/app/api/v1/system.py -> parents[4] is repo root
    on_windows = sys.platform == "win32"
    script_name = "delayed_stop.ps1" if on_windows else "stop_services_wsl.sh"
    project_root = Path(__file__).resolve().parents[4]
    stop_script = project_root / "scripts" / script_name
    if not stop_script.exists():
        stop_script = Path(__file__).resolve().parents[3] / "scripts" / script_name

    if not stop_script.exists():
        logger.error(f"Stop script not found at {stop_script}")
        return ShutdownResponse(
            status="error",
            message=f"Stop script not found at {stop_script}"
        )

    try:
        if on_windows:
            subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-WindowStyle",
                    "Hidden",
                    "-File",
                    str(stop_script),
                ],
                creationflags=subprocess.CREATE_NO_WINDOW,
                close_fds=True,
            )
        else:
            subprocess.Popen(
                ["bash", str(stop_script)],
                start_new_session=True,  # survives the backend process it is about to stop
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        logger.info("Platform shutdown scheduled successfully.")
        return ShutdownResponse(
            status="ok",
            message="Services are stopping. Ports 38920 and 38921 will be released."
        )
    except Exception as e:
        logger.error(f"Failed to schedule platform shutdown: {e}")
        return ShutdownResponse(
            status="error",
            message=f"Failed to initiate shutdown: {str(e)}"
        )
