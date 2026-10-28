from fastapi import APIRouter
from pydantic import BaseModel
import subprocess
import sys
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["system"])


class ShutdownResponse(BaseModel):
    status: str
    message: str


@router.post("/shutdown", response_model=ShutdownResponse)
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
