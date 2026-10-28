import functools
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "register_tick_task.ps1"
NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")

# The script reads the Windows identity and builds Task Scheduler XML, so it only runs on Windows: pwsh on a Linux
# runner (GitHub ubuntu images ship it) fails on [Security.Principal.WindowsIdentity]::GetCurrent().
pytestmark = pytest.mark.skipif(
    POWERSHELL is None or sys.platform != "win32", reason="needs Windows PowerShell (Task Scheduler APIs)"
)


@functools.lru_cache(maxsize=None)  # PowerShell start-up is slow; the output is deterministic
def _what_if(*extra):
    """Runs the registration script with -WhatIf: nothing is registered or removed."""
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), "-WhatIf",
         "-PythonExe", sys.executable, *extra],
        capture_output=True, text=True, timeout=120,
    )
    return result


def _extract_xml(stdout):
    begin = stdout.index("----- TASK XML BEGIN -----") + len("----- TASK XML BEGIN -----")
    end = stdout.index("----- TASK XML END -----")
    return stdout[begin:end].strip()


def test_what_if_prints_a_well_formed_logon_task_definition():
    result = _what_if()

    assert result.returncode == 0, result.stderr
    root = ET.fromstring(_extract_xml(result.stdout))
    assert root.tag == f"{{{NS['t']}}}Task"

    trigger = root.find("t:Triggers/t:LogonTrigger", NS)
    assert trigger is not None
    assert trigger.findtext("t:Repetition/t:Interval", namespaces=NS) == "PT15M"
    assert trigger.find("t:Repetition/t:Duration", NS) is None  # indefinite repetition
    assert trigger.findtext("t:Repetition/t:StopAtDurationEnd", namespaces=NS) == "false"
    # a TimeTrigger starts the repetition right away and keeps it going between sessions
    timed = root.find("t:Triggers/t:TimeTrigger", NS)
    assert timed is not None
    assert timed.findtext("t:Repetition/t:Interval", namespaces=NS) == "PT15M"
    assert timed.find("t:Repetition/t:Duration", NS) is None
    assert timed.findtext("t:StartBoundary", namespaces=NS)
    user = trigger.findtext("t:UserId", namespaces=NS)
    assert user and "\\" in user  # DOMAIN\user

    principal = root.find("t:Principals/t:Principal", NS)
    assert principal.findtext("t:UserId", namespaces=NS) == user
    assert principal.findtext("t:LogonType", namespaces=NS) == "InteractiveToken"
    assert principal.findtext("t:RunLevel", namespaces=NS) == "LeastPrivilege"

    settings = {child.tag.split("}")[1]: (child.text or "").strip() for child in root.find("t:Settings", NS)}
    assert settings["MultipleInstancesPolicy"] == "IgnoreNew"
    assert settings["StartWhenAvailable"] == "true"
    assert settings["RunOnlyIfNetworkAvailable"] == "true"
    assert settings["DisallowStartIfOnBatteries"] == "false"
    assert settings["StopIfGoingOnBatteries"] == "false"
    assert settings["ExecutionTimeLimit"] == "PT10M"
    assert settings["Hidden"] == "true" and settings["Enabled"] == "true"


def test_what_if_action_runs_the_tick_script_from_the_backend_directory():
    root = ET.fromstring(_extract_xml(_what_if().stdout))

    action = root.find("t:Actions/t:Exec", NS)
    arguments = action.findtext("t:Arguments", namespaces=NS)
    # no console is ever created: the action is the GUI-subsystem interpreter, never powershell/cmd/python.exe
    command = action.findtext("t:Command", namespaces=NS)
    assert Path(command).name.lower() == "pythonw.exe"
    assert "powershell" not in command.lower() and "powershell" not in arguments.lower()
    assert "WindowStyle" not in arguments  # hiding after creation still flashes a window
    assert "run_tick.py" in arguments
    assert ">>" not in arguments and "Out-File" not in arguments  # the tick writes its own rotating log
    assert Path(action.findtext("t:WorkingDirectory", namespaces=NS)).name == "backend"


def test_what_if_honours_the_interval_and_names_the_legacy_tasks_it_would_remove():
    result = _what_if("-IntervalMinutes", "20")

    assert "<Interval>PT20M</Interval>" in result.stdout
    assert "NBA-Odds-Opening" in result.stdout and "NBA-Odds-Closing" in result.stdout
    assert "Register-ScheduledTask" in result.stdout  # reported as an action, not performed


def _task_names():
    probe = subprocess.run(
        [POWERSHELL, "-NoProfile", "-Command", "(Get-ScheduledTask -TaskName 'NBA-Odds-*' -ErrorAction SilentlyContinue).TaskName"],
        capture_output=True, text=True, timeout=60,
    )
    if probe.returncode != 0:
        pytest.skip("ScheduledTasks module unavailable")
    return sorted(probe.stdout.split())


def test_what_if_neither_registers_nor_removes_any_task():
    before = _task_names()  # the real tasks may or may not exist; -WhatIf must leave them as they are

    _what_if.cache_clear()  # force a real run between the two probes
    assert _what_if().returncode == 0

    assert _task_names() == before
