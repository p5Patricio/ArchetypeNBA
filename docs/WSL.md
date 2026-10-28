# Running ArchetypeNBA in WSL (current production setup)

Since 2026-10-27 the whole project lives in WSL2 (Ubuntu 24.04) on the owner's Windows PC. Nothing runs natively on Windows except one launcher stub. The Windows-specific procedures in the rest of `docs/` (PowerShell, Task Scheduler, `pythonw.exe`) describe the previous setup and still apply to a native Windows install.

## 1. Layout

| Piece | Where | Notes |
| --- | --- | --- |
| Repo | `~/proyectos/ArchetypeNBA` | The tick runs whatever is checked out here (rule 7 of `AGENTS.md`). |
| Python | `.venv/` in the repo root | `pip install -r backend/requirements.txt`. |
| PostgreSQL | native 18.x cluster `main`, port **5433** | Role `nba`, database `nba_platform`. Starts with the distro (systemd). |
| Secrets | `.env` in the repo root | Git-ignored. `DATABASE_URL=postgresql://nba:PASSWORD@localhost:5433/nba_platform`. |
| Backend / frontend | `127.0.0.1:38921` / `127.0.0.1:38920` | `scripts/start_services_wsl.sh`, `scripts/stop_services_wsl.sh`. |
| Tick | `nba-tick.timer` (systemd **user** unit, every 15 min) | Logs to `logs/tick.log`. |
| Backups | `nba-backup.timer`, daily 03:30, to `~/ArchetypeNBA-backups` | Keeps the newest 7 automatic dumps. |
| Lineups | `nba-lineups.timer` (systemd **user** unit, every 10 min) | Logs starters and inactives to `logs/lineups.jsonl`. |
| Unit files | `scripts/systemd/` (copy into `~/.config/systemd/user/`) | Then `systemctl --user daemon-reload && systemctl --user enable --now nba-tick.timer nba-backup.timer` and `loginctl enable-linger $USER`. |

## 2. What starts at boot

1. Windows logon runs `NBAAnalyticsWSL.vbs` from the Startup folder (source: `scripts/windows/NBAAnalyticsWSL.vbs`; copy it to `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`). It waits 15 s, keeps the distro alive with a hidden `wsl.exe -- sleep infinity` (WSL stops an idle distro otherwise), runs `start_services_wsl.sh` and opens `http://localhost:38920/props`.
2. systemd starts PostgreSQL and the two user timers. `Persistent=true` makes a timer that was missed while the PC was off fire once at start.

The tick and the backups only run while the distro is alive, that is, while the PC is on and the launcher ran. Closing lines of games that tip off while the PC is off cannot be recovered (`missed closing lines` in the tick log).

## 3. Everyday commands

```bash
systemctl --user list-timers nba-tick.timer nba-backup.timer   # next / last run
systemctl --user stop nba-tick.timer                           # pause capture (resume with start)
systemctl --user start nba-tick.service                        # run one tick now (spends credits)
journalctl --user -u nba-tick.service -n 50                    # tick output seen by systemd
bash scripts/backup_db_wsl.sh                                  # backup now
bash scripts/stop_services_wsl.sh                              # same as the "Detener Servicios" buttons
bash scripts/start_services_wsl.sh                             # start the web services
```

### Enabling the lineup logger (research item 6)

The lineup logger records starters and inactives before tip-off to measure empirical announcement timing:

```bash
cp scripts/systemd/nba-lineups.* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now nba-lineups.timer
systemctl --user list-timers nba-lineups.timer                 # verify next run
```

Dry-run test (prints to stdout without file append or network writes):
```bash
cd backend && ../.venv/bin/python scripts/log_lineups.py --dry-run
```

The "Detener Servicios" buttons call `POST /api/v1/system/shutdown`, which runs `stop_services_wsl.sh` on Linux and `delayed_stop.ps1` on Windows. After a code change restart the backend (stop, then start). The frontend is a production build: after editing `frontend/` run `NEXT_PUBLIC_API_BASE=http://localhost:38921 npm run build` in `frontend/` (the API base is baked in at build time).

## 4. Gotchas specific to this setup

- **Mirrored networking.** `%UserProfile%\.wslconfig` has `networkingMode=mirrored`, so Windows and WSL share `localhost`. A port busy on Windows is busy in WSL, and a Windows service on 5432 answers WSL's `localhost:5432`. That is why PostgreSQL in WSL uses **5433**. A `DATABASE_URL` that points at 5432 would silently hit the Windows server (if one is still installed). Check with `select version()`: it must say `linux`.
- **Run `python -m pytest tests -q`**, not a bare `pytest`. `backend/pytest.ini` has no `testpaths`, so a bare run also collects `backend/scripts/test_live_training.py`, which calls `127.0.0.1:8000` on import and hangs here (the SYN is dropped, there is no refusal).
- **CORS.** `.env` overrides shell variables (`override=True`) and lists the allowed origins: 38920, 38921, 3000, 8000 and 8001. Test servers on other ports are blocked by the browser.
- **Timezone.** The distro runs in `America/Mexico_City`, which the tick needs for its "today" boundaries.
- **`localhost:38920` from Windows works** because of mirrored networking; if it ever stops, check `.wslconfig` and `wsl --shutdown`.

## 5. Restore from a backup

```bash
cd backend
../.venv/bin/python scripts/db_transfer.py verify ~/ArchetypeNBA-backups/<name>.dump
bash ../scripts/stop_services_wsl.sh && systemctl --user stop nba-tick.timer
../.venv/bin/python scripts/db_transfer.py import --dump ~/ArchetypeNBA-backups/<name>.dump \
  --target-url "postgresql://nba:PASSWORD@localhost:5433/nba_platform" --replace --confirm-database nba_platform
systemctl --user start nba-tick.timer && bash ../scripts/start_services_wsl.sh
```

`--replace` wipes the target database first. Dumps hold odds-provider data and private paper-trading records: keep them out of git and out of cloud storage. The only copies live on this disk, so copy `~/ArchetypeNBA-backups` to an external drive from time to time.

## 6. History of the move

The cutover followed `docs/DB_TRANSFER.md`: tick paused on Windows, final export, verified restore into the WSL cluster (all 21 tables and the Alembic revision matched), tick registered in WSL, then the Windows task, repo and launchers were removed. Details are in `docs/DECISIONS.md` (D-55).
