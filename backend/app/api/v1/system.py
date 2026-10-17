from fastapi import APIRouter
from pydantic import BaseModel
import subprocess
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
    Uses WMI Win32_Process to spawn a detached hidden PowerShell process that
    waits 1200ms (allowing this HTTP response to return cleanly to the client)
    before executing scripts/stop_services.ps1.
    """
    # system.py is at backend/app/api/v1/system.py -> parents[4] is repo root
    project_root = Path(__file__).resolve().parents[4]
    delayed_script = project_root / "scripts" / "delayed_stop.ps1"
    if not delayed_script.exists():
        delayed_script = Path(__file__).resolve().parents[3] / "scripts" / "delayed_stop.ps1"

    if not delayed_script.exists():
        logger.error(f"Delayed stop script not found at {delayed_script}")
        return ShutdownResponse(
            status="error",
            message=f"Delayed stop script not found at {delayed_script}"
        )

    try:
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                str(delayed_script),
            ],
            creationflags=subprocess.CREATE_NO_WINDOW,
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
