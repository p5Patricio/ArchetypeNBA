# Moving the database to another PC

This is the runbook for moving the ArchetypeNBA PostgreSQL database from one PC to another without losing data. It is written for someone (a person or an AI agent) who has never seen the project. Read sections 1 and 2 first; they explain why the order of the steps in section 4 matters.

## 1. What you are moving

- **The database `nba_platform`** (PostgreSQL). It was 229 MB on 2026-10-26; the dump is compressed (`pg_dump -Fc`), so the file is smaller than that.
- **Why it cannot simply be rebuilt.** It holds odds captured every few minutes since 2026-10-06 (closing lines cannot be backfilled on the free Odds API tier), recorded predictions, paper bets and their settlement, and the model registry and evaluations. It also holds 23 seasons of game logs and Elo ratings; those are rebuildable, but slowly.
- **The tool.** `backend/scripts/db_transfer.py` (logic in `backend/app/services/db_transfer.py`) wraps `pg_dump` and `pg_restore` and adds integrity checks on both ends:

| Command | What it does |
| --- | --- |
| `export` | Dumps the whole database and writes `<name>.manifest.json` next to it (exact row count of every table, server and Alembic versions, timezone, sha256, git commit). |
| `verify DUMP` | Checks the dump against its manifest (sha256, size) and that `pg_restore` can read it. Needs no database. |
| `import --dump FILE` | Verifies, restores into an EMPTY database in one transaction, runs `ANALYZE`, then compares the exact row count of every table and the Alembic revision with the manifest. |
| `manifest DUMP` | Prints a manifest. |

The dump and the manifest travel together by USB, private cloud storage or `scp`. They are never committed to git (the `.gitignore` blocks `*.dump`, `*.manifest.json` and `backups/`, and `export` refuses to write inside the repository).

## 2. The golden rule: one PC captures at a time

The capture tick (`backend/scripts/run_tick.py`) spends credits of a single The Odds API key (free tier: 500 credits per month) and writes to the database it is configured with. If two PCs run it:

- both burn the same credit quota, and
- each database gets different captures, predictions and bets. There is no way to merge two diverged databases.

So the procedure is always: pause the tick on the old PC, take the final export, restore on the new PC, start the tick there, and only then remove it from the old PC. The order in section 4 is deliberate; do not reorder it.

## 3. Preparation (can be done days before the cutover)

On the **new** PC:

1. Clone the repository and check out the same commit as the old PC (`git log -1` on both; the manifest records the commit of the export).
2. Install Python 3.12, create the virtual environment and install the dependencies:

   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate          # Windows PowerShell: .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   pip install "psycopg[binary]"      # see the note below
   ```

   > `requirements.txt` lists `psycopg2-binary`, but the application connects with the psycopg 3 driver (`postgresql+psycopg://`, see `backend/app/deps.py`). On a fresh virtual environment you must install `psycopg[binary]` yourself, otherwise every script fails with `No module named 'psycopg'`.

3. Install PostgreSQL, its command line tools (`pg_dump`, `pg_restore`, `psql`) and create the role as described in section 4, step 4 (the database itself can wait). The tool finds the tools on `PATH` or in the usual install folders; if it cannot, pass `--pg-bin <folder>`.
4. **Rehearse the import** with an older export, so that cutover day holds no surprises:

   ```bash
   python scripts/db_transfer.py import --dump <old export>.dump \
     --target-url "postgresql://nba:PASSWORD@localhost:5432/nba_platform_rehearsal" --create-db
   ```

   Drop the rehearsal database afterwards (`DROP DATABASE nba_platform_rehearsal;`).

## 4. The cutover, in order

Paths use `<repo>` for the repository folder. Run the commands from the `backend/` folder unless stated otherwise. Backups go to `<repo>/../ArchetypeNBA-backups/` by default (a sibling folder of the repository, outside git).

### Step 1. Old PC: pause the tick and take the final export

Pause the scheduled task and make sure no tick is running right now (disabling a task does not stop a run that is already in progress):

```powershell
Disable-ScheduledTask -TaskName NBA-Odds-Tick
Get-ScheduledTask -TaskName NBA-Odds-Tick | Select-Object TaskName, State   # State must not be Running
Test-Path <repo>\logs\tick.lock                                             # False = no tick in progress
```

Take the export:

```powershell
python scripts\db_transfer.py export
```

It prints the paths of `nba_platform_<YYYYmmdd_HHMM>.dump` and `nba_platform_<YYYYmmdd_HHMM>.manifest.json`, the sha256 and the table and row totals. Warnings (for example "the database is at Alembic revision X but the code head is Y") do not fail the export; read them. Useful flags: `--out-dir DIR`, `--name NAME`, `--database-url URL` (default: `DATABASE_URL` from `backend/.env`), `--pg-bin DIR`.

The export is read-only for the database and consistent (the row counts and the dump come from the same snapshot), but only a paused tick guarantees that the dump contains everything captured so far.

Then save a baseline report to compare with after the restore (the tick is paused, so the numbers will not move; the folder exists now):

```powershell
python scripts\paper_report.py | Out-File -Encoding utf8 ..\..\ArchetypeNBA-backups\paper_report_old_pc.txt
```

### Step 2. Old PC: verify the export

```powershell
python scripts\db_transfer.py verify ..\..\ArchetypeNBA-backups\nba_platform_<stamp>.dump
```

Expected: `VERIFIED: ... is intact and matches ...` and exit code 0. Do not move on if it fails; export again.

### Step 3. Transfer the files and check the hash

Copy BOTH files (same folder, same names) to the new PC:

```bash
scp ArchetypeNBA-backups/nba_platform_<stamp>.dump ArchetypeNBA-backups/nba_platform_<stamp>.manifest.json user@new-pc:ArchetypeNBA-backups/
```

or with a USB drive or private cloud storage (delete the cloud copy afterwards; the dump contains odds-provider data and your paper-trading records).

On the new PC check the hash independently of the tool and compare it with `dump.sha256` in the manifest:

```powershell
Get-FileHash -Algorithm SHA256 nba_platform_<stamp>.dump          # Windows
```
```bash
sha256sum nba_platform_<stamp>.dump                               # Linux
shasum -a 256 nba_platform_<stamp>.dump                           # macOS
```

Then run `python scripts/db_transfer.py verify <dump>` on the new PC (this also proves that the new PC's `pg_restore` can read the archive).

### Step 4. New PC: install PostgreSQL, create the role and the database

Install the **same PostgreSQL major version as the source (18.x) or newer**. A dump cannot be restored into an older major version; the tool refuses to try. The version of the source is in the manifest (`source.server_version`).

- **Windows:** the installer from <https://www.postgresql.org/download/windows/>. Keep "Command Line Tools" ticked, remember the `postgres` superuser password, keep port 5432. Tools land in `C:\Program Files\PostgreSQL\<major>\bin`.
- **macOS:** `brew install postgresql@18 && brew services start postgresql@18`.
- **Debian/Ubuntu:** `sudo apt install postgresql-18` (add the PostgreSQL apt repository first if your release does not ship 18: <https://apt.postgresql.org>).

Create the role the application will use and an empty database owned by it. Connect as the administrator (`psql -U postgres -h localhost` on Windows, `sudo -u postgres psql` on Linux, `psql postgres` on macOS):

```sql
CREATE ROLE nba LOGIN CREATEDB;
\password nba
CREATE DATABASE nba_platform OWNER nba ENCODING 'UTF8' TEMPLATE template0;
```

Import with the role the application will use: the dump carries no owners (`--no-owner`) and no grants (`--no-privileges`), so the restoring role becomes the owner of every table. If you skip `CREATE DATABASE`, add `--create-db` to the import and the tool creates it (the role needs `CREATEDB`).

### Step 5. New PC: restore

```bash
python scripts/db_transfer.py import --dump ../../ArchetypeNBA-backups/nba_platform_<stamp>.dump \
  --target-url "postgresql://nba:PASSWORD@localhost:5432/nba_platform"
```

What it does, in order: verifies the dump, checks that the target server's major version is not older than the source's, refuses a target that already has tables, restores everything in a single transaction (all or nothing, `--exit-on-error`), runs `ANALYZE`, and prints a table with the expected and actual row count of every table plus the Alembic revision. The last line must be `RESULT: OK` and the exit code 0. Any `MISMATCH` means the data cannot be trusted (exit code 1): see section 9.

Flags: `--create-db`, `--replace --confirm-database NAME` (wipes a non-empty target; section 6), `--skip-analyze`, `--pg-bin DIR`.

About passwords: `--target-url` puts the password on this command's own command line, visible to other users of the machine and in your shell history. On a shared machine leave it out of the URL and use `PGPASSWORD` instead (`$env:PGPASSWORD = '...'` in PowerShell, `export PGPASSWORD=...` in bash) or a pgpass file. The tool never puts the password in the arguments of `pg_dump` or `pg_restore`; it hands it to them through the `PGPASSWORD` environment variable only.

### Step 6. New PC: bring `backend/.env` and set `DATABASE_URL`

`backend/.env` holds the API keys and the database password. It is not in git and not in the dump. Copy it from the old PC through a secure channel (a USB drive you control, an encrypted archive, a password manager attachment, `scp`). Never through git, a chat, an issue or an email.

1. Put it at `backend/.env` on the new PC.
2. Edit `DATABASE_URL` to the new database, for example `postgresql://nba:PASSWORD@localhost:5432/nba_platform` (percent-encode special characters in the password: `@` becomes `%40`).
3. If you have no `.env` to copy, start from `backend/.env.example`, which lists every setting with its default. `THE_ODDS_API_KEY` comes from <https://the-odds-api.com>.

The application also reads machine-level environment variables, and `backend/.env` overrides them. If the old PC keeps some secrets only as environment variables, you must recreate them in the new `.env`. List the **names** (never the values) of what is defined there:

```powershell
Get-ChildItem Env: | Where-Object { $_.Name -match '^(DATABASE_URL|REDIS_URL|CORS_ORIGINS|DEBUG|ETL_|GEMINI_|TELEGRAM_|THE_ODDS_|PROPS_|LEARNING_|PGPASSWORD)' } | Select-Object -ExpandProperty Name
```

### Step 7. New PC: check the application against the restored data

```bash
alembic current                      # must print the revision in the manifest (alembic.database_version)
python -m pytest -q                  # validates the Python environment (the tests use an in-memory SQLite, not your data)
python scripts/paper_report.py       # compare with paper_report_old_pc.txt: same strategies, bets, settled bets, bankroll
python scripts/run_tick.py --dry-run # reads the database, prints what each step would do; no network, no writes
```

If `alembic current` prints an older revision than the code head, run `alembic upgrade head` only if you intend to move to the schema of the checked-out code (the export warned about this in step 1 if it applied).

### Step 8. New PC: register the tick

**Check the timezone first.** The tick uses the machine's LOCAL timezone to decide what "today" is: the odds opening is captured once per local calendar day, and the prediction recorder's daily staking cap is counted per local day. A different timezone moves those day boundaries (an opening can be captured twice or skipped around the switch day, and the cap resets at a different hour). The old PC runs in `America/Mexico_City`; set the same zone on the new PC, or accept the shift:

```powershell
Set-TimeZone -Id "Central Standard Time (Mexico)"                 # Windows (administrator)
```
```bash
sudo timedatectl set-timezone America/Mexico_City                 # Linux
sudo systemsetup -settimezone America/Mexico_City                 # macOS
```

**Windows** (the task runs every 15 minutes, only while the user is logged on):

```powershell
cd <repo>
powershell -ExecutionPolicy Bypass -File .\scripts\register_tick_task.ps1 -WhatIf        # preview, changes nothing
powershell -ExecutionPolicy Bypass -File .\scripts\register_tick_task.ps1 -StartNow      # register and run one tick now
```

Without `-PythonExe` the script reuses the interpreter path hardcoded in `scripts/run_pipeline.bat`, which is a path from the old PC; on the new PC pass `-PythonExe <path to the venv's python.exe>` (the `-WhatIf` preview prints the interpreter it will use, and the script stops with an error if it does not exist). Check with `Get-ScheduledTask -TaskName NBA-Odds-Tick` and read `logs\tick.log` (the tick writes its own rotating log).

**Linux** (cron, every 15 minutes; the tick logs to `<repo>/logs/tick.log` by itself):

```cron
*/15 * * * * cd /path/to/repo/backend && /path/to/repo/backend/.venv/bin/python scripts/run_tick.py > /dev/null 2>&1
```

Or a systemd user timer. `~/.config/systemd/user/nba-tick.service`:

```ini
[Unit]
Description=ArchetypeNBA odds and prediction tick

[Service]
Type=oneshot
WorkingDirectory=/path/to/repo/backend
ExecStart=/path/to/repo/backend/.venv/bin/python scripts/run_tick.py
TimeoutStartSec=600
```

`~/.config/systemd/user/nba-tick.timer`:

```ini
[Unit]
Description=Run the ArchetypeNBA tick every 15 minutes

[Timer]
OnCalendar=*:0/15
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl --user daemon-reload && systemctl --user enable --now nba-tick.timer
loginctl enable-linger "$USER"        # keep running when you are logged out
```

**macOS:** cron works, but launchd is the native scheduler. `~/Library/LaunchAgents/com.archetypenba.tick.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.archetypenba.tick</string>
  <key>ProgramArguments</key>
  <array>
    <string>/path/to/repo/backend/.venv/bin/python</string>
    <string>scripts/run_tick.py</string>
  </array>
  <key>WorkingDirectory</key><string>/path/to/repo/backend</string>
  <key>StartInterval</key><integer>900</integer>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
```

```bash
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.archetypenba.tick.plist
```

### Step 9. Old PC: remove the tick

Only after the new PC has run at least one healthy tick (exit code 0 in `logs/tick.log`):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\register_tick_task.ps1 -Unregister
```

Do not enable the task on the old PC again. Keep the old database untouched for a few days as a fallback (section 6), then drop it when you are sure.

## 5. What is lost during the gap

The gap is the time between pausing the tick on the old PC (step 1) and the first tick on the new PC (step 8). During it nothing captures:

- **Closing lines** of games that tip off in the gap are gone for good: they cannot be backfilled on a free plan. The tick log reports them as `missed_closing`.
- **Opening lines** of a local day with no tick are not captured.
- **Predictions and paper bets** are recorded at decision time, for games that tip off soon after a tick; games that start inside the gap get none.
- Final scores and settlement are not lost: the `results` step catches up from the free NBA stats API for games that already finished.

Keep the gap short and put it in a quiet window. NBA games are in the evening (US time), so do the whole cutover in the morning, well before the first tip-off, and check the schedule first.

## 6. Rollback

- **The restore failed or looks wrong:** nothing on the old PC changed, because the export only reads. Drop the target database and import again into a fresh one (`DROP DATABASE nba_platform;`), or re-import over it with `import ... --replace --confirm-database nba_platform`. `--replace` runs `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` on the target and then restores; it destroys everything in that database, and it only runs when the confirmed name is exactly the target database name. If the restore fails after the wipe, the database is left empty; fix the cause and import again.
- **The new PC does not work and you want the old one back (before step 9):** `Enable-ScheduledTask -TaskName NBA-Odds-Tick` on the old PC, and disable or unregister the tick on the new PC first. Anything captured on the new PC in the meantime is not in the old database; if it matters, export from the new PC and import into the old one with `--replace --confirm-database <name>`.
- **After step 9** the old database is still intact until you drop it. The procedure is symmetric: export on the new PC, import on the old one.

## 7. Periodic backups

A single copy on one disk is not a backup. Take a weekly export and copy the two files somewhere else (an external drive, private cloud storage):

```bash
python backend/scripts/db_transfer.py export
```

It is safe while the tick runs (consistent snapshot). To automate it: on Linux/macOS a cron line such as `0 3 * * 0 cd /path/to/repo/backend && .venv/bin/python scripts/db_transfer.py export`; on Windows a weekly Task Scheduler task whose program is the Python executable, arguments `<repo>\backend\scripts\db_transfer.py export` and "start in" `<repo>\backend`. Old exports are never pruned or overwritten automatically; delete the old ones yourself, keeping the last few.

## 8. What is NOT in the dump

- `backend/.env` and any secret kept in environment variables (step 6).
- `logs/` (`tick.log`, `tick.lock`).
- The scheduled task registration (step 8; `scripts/register_tick_task.ps1` recreates it on Windows).
- The Engram memory of the AI agent that worked on the old PC.
- PostgreSQL roles, passwords, database owners and grants (the dump is made with `--no-owner --no-privileges`; create the role first, step 4) and the server configuration (the timezone of the server is only compared and warned about).
- The Python virtual environment, `node_modules`, the Redis cache.

## 9. Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `No usable PostgreSQL client tools found` | `pg_dump` or `pg_restore` is missing, or older than the server. Install the client tools of the right major version and pass `--pg-bin <folder>` if they are in an unusual place. The search order is `--pg-bin`, then `PATH`, then `C:\Program Files\PostgreSQL\*\bin`, Homebrew (`/opt/homebrew/opt/postgresql@*/bin`, `/usr/local/opt/postgresql@*/bin`), Postgres.app, and `/usr/lib/postgresql/*/bin`; the highest major that is at least the server's wins. |
| `The target server runs PostgreSQL X but the dump comes from PostgreSQL Y` | A dump restores only into the same major or a newer one. Install PostgreSQL Y or newer on the target. |
| `pg_dump: error: aborting because of server version mismatch` | The `pg_dump` in use is older than the server. The tool avoids this by picking tools at least as new as the server; point `--pg-bin` at the newer install. |
| `integrity check failed: the dump does not match its manifest` | The file was corrupted or changed in transit, or the dump and manifest belong to different exports. Copy both files again. |
| `manifest not found` | The manifest must sit next to the dump with the same name (`x.dump` and `x.manifest.json`). |
| `permission denied to create database` (with `--create-db`) | As the administrator: `ALTER ROLE nba CREATEDB;`, or create the database yourself (step 4). |
| `permission denied for schema public` when the application creates tables | In PostgreSQL 15+ only the database owner can create in `public`. `ALTER DATABASE nba_platform OWNER TO nba;` and restore with the `nba` role. |
| `The target database ... is not empty` | Import into a new empty database, or add `--replace --confirm-database <name>` to wipe it first. |
| `database "..." does not exist` / `cannot connect` | Create the database (step 4), add `--create-db`, or check host, port, user and password in the URL. |
| `password authentication failed` | Wrong password, or special characters not percent-encoded in the URL (`@` is `%40`), or `pg_hba.conf` does not allow the connection. |
| Collation or locale error when creating the database | Create it from `template0` with an explicit encoding; the tool does this for `--create-db`. On Linux, `encoding UTF8 does not match locale` means you must pass a UTF-8 locale, for example `CREATE DATABASE nba_platform OWNER nba ENCODING 'UTF8' LOCALE 'C.UTF-8' TEMPLATE template0;`. Indexes are rebuilt during the restore with the target's collation, so only the sort order of text can differ. |
| `character with byte sequence ... has no equivalent in encoding "WIN1252"` | The target database is not UTF-8 (player names such as Doncic or Jokic need UTF-8). Recreate it with `ENCODING 'UTF8'`. The import warns when the encodings differ. |
| `No module named 'psycopg'` | `pip install "psycopg[binary]"` in the virtual environment (step 3 of the preparation). |
| `RESULT: MISMATCH` | A table has a different row count, a table is missing or extra, or the Alembic revision differs. Do not use that database. Re-run the import into a fresh database; if it repeats, keep the output of the comparison table and the manifest and investigate before touching the old PC. |
| `Refusing to write inside the repository working tree` | `export --out-dir` pointed inside the repo. Choose a folder outside it. |
| A `*.dump.part` file in the backups folder | A previous export was interrupted. Delete it. |
| Warning: target timezone differs | The database `timezone` setting is not copied; stored timestamps are not affected. What matters is the operating system timezone for the tick (step 8). |

### Known limitations

Found by the native multi-lens review (approved, non-blocking) and by the author; they do not affect the standard local procedure above.

| Limitation | What to do |
|------------|------------|
| Query parameters of the database URL (for example `?sslmode=require`) are not forwarded to `pg_dump` / `pg_restore`. | For a remote or TLS server set the libpq environment variables instead (`PGSSLMODE`, `PGSSLROOTCERT`, ...). |
| `--replace` only drops and recreates the `public` schema, and the wipe is not atomic with the restore: if the restore fails afterwards, the database is left empty. | Keep the previous dump; use a fresh database (`--create-db`) whenever you can. Objects living in other schemas are not removed. |
| There is no process timeout and no lock: a hung `pg_dump` or `pg_restore` must be interrupted by hand. | Pause the tick before the final export (step 1) so nothing writes meanwhile. |
| The exit-code contract has two non-zero values (1 = operation failed or counts mismatch, 2 = refused before changing anything). | Trust the exit code and the final `RESULT:` line, not the wording of intermediate messages. |

## 10. Reference

```text
python scripts/db_transfer.py export [--out-dir DIR] [--name NAME] [--database-url URL] [--pg-bin DIR]
python scripts/db_transfer.py verify DUMP [--pg-bin DIR]
python scripts/db_transfer.py import --dump FILE [--target-url URL] [--create-db]
                                     [--replace --confirm-database NAME] [--skip-analyze] [--pg-bin DIR]
python scripts/db_transfer.py manifest DUMP_OR_MANIFEST
```

**Exit codes:** `0` ok. `1` an operation failed (`pg_dump`/`pg_restore` error) or a table did not match the manifest after the restore. `2` refused before anything was changed (bad input, failed integrity check, unmet precondition such as an older target server or a non-empty target).

**Manifest** (`<name>.manifest.json`, UTF-8, sorted keys): `created_at`, `git_commit`, `pg_dump_version`, `dump` (`file`, `size_bytes`, `sha256`), `source` (`database`, `server_version`, `server_version_num`, `timezone`, `encoding`, `lc_collate`), `alembic` (`database_version`, `code_head`), `total_rows` and `tables` (exact `count(*)` of every user table, keyed `schema.table`).

**Notes for an AI agent running this procedure**

- Every command is non-interactive and prints a final line (`VERIFIED`, `RESULT: OK` / `RESULT: MISMATCH`) plus an exit code; trust the exit code.
- Ask the human for confirmation before steps 1 (pausing the tick), 8 and 9, and before any `--replace`. Never run the tick on two machines.
- Never print, log or commit secrets: not the contents of `.env`, not environment variable values, not the password in a URL.
