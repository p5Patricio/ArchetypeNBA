"""
Portable export/import of the whole PostgreSQL database (runbook: docs/DB_TRANSFER.md).

``export`` writes ``<name>.dump`` (``pg_dump -Fc``) plus ``<name>.manifest.json`` with the exact row count of every
table, the server and Alembic versions and the sha256 of the dump. ``verify`` checks a dump against its manifest
without any database. ``import`` verifies first, restores into an EMPTY database in a single transaction and then
compares the exact row count of every table with the manifest.

Design notes:
  * The pure logic (manifest, comparison, version rules, path guard, tool discovery) has no I/O beyond the files it is
    given. Everything that talks to the outside world goes through two seams that tests replace with fakes:
    ``ProcessRunner`` (pg_dump / pg_restore / git) and ``Inspector`` (SQL against one database).
  * The database password only ever travels in the subprocess environment (``PGPASSWORD``). It is never put in argv,
    logs, the manifest or an exception message; ``DbTarget.masked`` is the only way a URL is echoed.
  * The row counts and the dump come from the SAME snapshot (``pg_export_snapshot`` + ``pg_dump --snapshot``), so
    the manifest stays exact even if something writes to the database while the export runs.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, ContextManager, Dict, Iterator, List, Mapping, Optional, Protocol, Sequence, Tuple
from urllib.parse import quote

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, URL, make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.pool import NullPool

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
BACKUP_DIR_NAME = "ArchetypeNBA-backups"

MANIFEST_FORMAT_VERSION = 1
DUMP_SUFFIX = ".dump"
MANIFEST_SUFFIX = ".manifest.json"

# Names that end up in file names and (for databases) in libpq arguments: keep them boring on purpose. A database
# name containing "=" would make libpq read it as a connection string.
_DATABASE_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.$-]*$")
_DUMP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_ENCODING_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
_SNAPSHOT_ID = re.compile(r"^[0-9A-Fa-f-]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


# --------------------------------------------------------------------------------------------------------------------
# Errors. ``exit_code`` is what the CLI returns: 2 = refused or nothing was changed, 1 = an operation failed.
# --------------------------------------------------------------------------------------------------------------------
class TransferError(Exception):
    exit_code = 1


class PreconditionError(TransferError):
    """Refused before anything was changed (bad input, unmet precondition, failed integrity check)."""

    exit_code = 2


class IntegrityError(PreconditionError):
    """The dump does not match its manifest or cannot be read."""


class ManifestError(PreconditionError):
    """The manifest is missing, unreadable or does not follow the schema."""


class OperationError(TransferError):
    """A step failed after work started (pg_dump / pg_restore / SQL)."""

    exit_code = 1


def scrub(value: str, secrets: Sequence[str]) -> str:
    """Replaces every known secret (and its URL-encoded form) in ``value``; defence in depth for echoed output."""
    for secret in secrets:
        if secret:
            value = value.replace(secret, "***").replace(quote(secret, safe=""), "***")
    return value


def _tail(output: str, secrets: Sequence[str], max_lines: int = 12, max_chars: int = 2000) -> str:
    lines = [line for line in output.strip().splitlines() if line.strip()]
    return scrub("\n".join(lines[-max_lines:]), secrets)[-max_chars:] or "(no output)"


def format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{num_bytes} B"  # unreachable; keeps type checkers calm


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


# --------------------------------------------------------------------------------------------------------------------
# Connection target
# --------------------------------------------------------------------------------------------------------------------
def validate_database_name(name: str) -> str:
    if not _DATABASE_NAME.match(name or ""):
        raise PreconditionError(
            "unsupported database name (use letters, digits, '_', '.', '$' or '-', not starting with '-'): "
            f"{name!r}"
        )
    return name


@dataclass(frozen=True)
class DbTarget:
    """One PostgreSQL database. Built from a URL; the password is only reachable through ``libpq_env``."""

    url: URL

    @classmethod
    def from_url(cls, raw: str) -> "DbTarget":
        try:
            url = make_url(raw)
        except ArgumentError:
            # never echo ``raw``: SQLAlchemy's own message would include the password
            raise PreconditionError(
                "not a valid database URL (expected postgresql://USER:PASSWORD@HOST:PORT/DBNAME)"
            ) from None
        if not url.drivername.startswith("postgres"):
            raise PreconditionError(f"only PostgreSQL URLs are supported, got the '{url.drivername}' driver")
        if not url.database:
            raise PreconditionError("the database URL has no database name (postgresql://USER:PASSWORD@HOST:PORT/DBNAME)")
        validate_database_name(url.database)
        return cls(url.set(drivername="postgresql+psycopg"))

    @property
    def database(self) -> str:
        return self.url.database or ""

    @property
    def secrets(self) -> List[str]:
        return [self.url.password] if self.url.password else []

    def with_database(self, name: str) -> "DbTarget":
        return DbTarget(self.url.set(database=validate_database_name(name)))

    def masked(self) -> str:
        return self.url.render_as_string(hide_password=True)

    def libpq_args(self) -> List[str]:
        """host/port/user/dbname as separate argv entries; never the password."""
        args: List[str] = []
        if self.url.host:
            args += ["--host", self.url.host]
        if self.url.port:
            args += ["--port", str(self.url.port)]
        if self.url.username:
            args += ["--username", self.url.username]
        return args + ["--dbname", self.database]

    def libpq_env(self) -> Dict[str, str]:
        env: Dict[str, str] = {}
        if self.url.password:
            env["PGPASSWORD"] = self.url.password
        sslmode = self.url.query.get("sslmode")
        if isinstance(sslmode, str):
            env["PGSSLMODE"] = sslmode
        return env


# --------------------------------------------------------------------------------------------------------------------
# Process seam
# --------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class ProcessRunner(Protocol):
    def run(self, argv: Sequence[str], env: Optional[Mapping[str, str]] = None) -> ProcessResult: ...


class SubprocessRunner:
    """Runs a command with the current environment plus ``env``; stdin is closed so nothing can prompt."""

    def run(self, argv: Sequence[str], env: Optional[Mapping[str, str]] = None) -> ProcessResult:
        full_env = dict(os.environ)
        if env:
            full_env.update(env)
        try:
            done = subprocess.run(
                list(argv),
                env=full_env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except FileNotFoundError:
            raise PreconditionError(f"cannot run {Path(argv[0]).name}: file not found") from None
        except OSError as exc:
            raise OperationError(f"cannot run {Path(argv[0]).name}: {exc.strerror or exc}") from None
        return ProcessResult(done.returncode, done.stdout or "", done.stderr or "")


# --------------------------------------------------------------------------------------------------------------------
# PostgreSQL client tools discovery
# --------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class PgTools:
    bin_dir: Path
    major: int
    pg_dump: Path
    pg_restore: Path
    version_text: str


def parse_pg_version(output: str) -> Optional[Tuple[str, int]]:
    """("18.0", 18) from ``pg_dump (PostgreSQL) 18.0``; handles ``17devel`` and ``18beta1``; None if unparseable."""
    marker = output.find("(PostgreSQL)")
    tail = output[marker + len("(PostgreSQL)"):] if marker >= 0 else output
    match = re.search(r"\b(\d+)(?:\.\d+)*", tail)
    return (match.group(0), int(match.group(1))) if match else None


def default_search_patterns(environ: Optional[Mapping[str, str]] = None) -> List[str]:
    """Glob patterns of the usual PostgreSQL ``bin`` directories (Windows, Homebrew, Postgres.app, Debian, RHEL)."""
    env = os.environ if environ is None else environ
    roots: List[str] = []
    for root in (env.get("ProgramFiles"), env.get("ProgramFiles(x86)"), r"C:\Program Files"):
        if root and root not in roots:
            roots.append(root)
    patterns = [os.path.join(root, "PostgreSQL", "*", "bin") for root in roots]
    patterns += [
        "/opt/homebrew/opt/postgresql@*/bin",
        "/usr/local/opt/postgresql@*/bin",
        "/opt/homebrew/opt/libpq/bin",
        "/usr/local/opt/libpq/bin",
        "/Applications/Postgres.app/Contents/Versions/*/bin",
        "/usr/lib/postgresql/*/bin",
        "/usr/pgsql-*/bin",
    ]
    return patterns


def _find_executable(directory: Path, name: str) -> Optional[Path]:
    for candidate in (name, f"{name}.exe"):
        path = directory / candidate
        if path.is_file():
            return path
    return None


def _probe_tools(directory: Path, runner: ProcessRunner) -> Optional[PgTools]:
    pg_dump = _find_executable(directory, "pg_dump")
    pg_restore = _find_executable(directory, "pg_restore")
    if pg_dump is None or pg_restore is None:
        return None
    try:
        result = runner.run([str(pg_dump), "--version"])
    except TransferError:
        return None
    parsed = parse_pg_version(result.stdout) if result.returncode == 0 else None
    if parsed is None:
        return None
    return PgTools(directory, parsed[1], pg_dump, pg_restore, parsed[0])


def _install_hint(required_major: Optional[int]) -> str:
    version = str(required_major) if required_major else "the latest major"
    return (
        f"Install the PostgreSQL {version} client tools (a full server install includes them) or point --pg-bin at "
        "the folder that contains pg_dump and pg_restore:\n"
        "  Windows:       the EnterpriseDB installer from https://www.postgresql.org/download/windows/ "
        "(keep 'Command Line Tools' ticked); tools land in C:\\Program Files\\PostgreSQL\\<major>\\bin\n"
        f"  macOS:         brew install postgresql@{required_major or '<major>'}\n"
        f"  Debian/Ubuntu: sudo apt install postgresql-client-{required_major or '<major>'} "
        "(older releases need https://apt.postgresql.org)"
    )


def discover_pg_tools(
    runner: ProcessRunner,
    *,
    required_major: Optional[int] = None,
    pg_bin: Optional[Path] = None,
    which: Callable[[str], Optional[str]] = shutil.which,
    search_patterns: Optional[Sequence[str]] = None,
    glob_fn: Callable[[str], List[str]] = glob.glob,
) -> PgTools:
    """
    Finds pg_dump + pg_restore. ``--pg-bin`` wins outright; otherwise PATH and then the common install locations are
    probed and the highest major >= ``required_major`` is used (ties go to the earlier source, so PATH beats a
    location scan). pg_dump refuses servers newer than itself, hence the lower bound.
    """
    if pg_bin is not None:
        tools = _probe_tools(Path(pg_bin), runner)
        if tools is None:
            raise PreconditionError(f"--pg-bin {pg_bin} does not contain a working pg_dump and pg_restore")
        if required_major is not None and tools.major < required_major:
            raise PreconditionError(
                f"--pg-bin {pg_bin} holds PostgreSQL {tools.major} tools but major {required_major} or newer is "
                "required (pg_dump cannot dump a newer server and pg_restore cannot read a newer archive)"
            )
        return tools

    directories: List[Path] = []
    on_path = which("pg_dump")
    if on_path:
        directories.append(Path(on_path).parent)
    patterns = default_search_patterns() if search_patterns is None else search_patterns
    for pattern in patterns:
        directories.extend(Path(match) for match in sorted(glob_fn(pattern)))

    seen = set()
    found: List[PgTools] = []
    for directory in directories:
        key = os.path.normcase(os.path.realpath(directory))
        if key in seen:
            continue
        seen.add(key)
        tools = _probe_tools(directory, runner)
        if tools is not None:
            found.append(tools)

    eligible = [t for t in found if required_major is None or t.major >= required_major]
    if eligible:
        best = max(t.major for t in eligible)
        return next(t for t in eligible if t.major == best)  # first of the best major = highest-precedence source

    seen_text = ", ".join(f"{t.bin_dir} (PostgreSQL {t.major})" for t in found) or "none"
    needed = f"major {required_major} or newer" if required_major else "any version"
    raise PreconditionError(
        f"No usable PostgreSQL client tools found ({needed} required). Found: {seen_text}.\n"
        + _install_hint(required_major)
    )


# --------------------------------------------------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------------------------------------------------
def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True)
class Manifest:
    name: str
    created_at: str
    git_commit: Optional[str]
    pg_dump_version: str
    dump_file: str
    dump_size_bytes: int
    dump_sha256: str
    source_database: str
    source_server_version: str
    source_server_version_num: int
    source_timezone: str
    source_encoding: str
    source_lc_collate: Optional[str]
    alembic_database_version: Optional[str]
    alembic_code_head: Optional[str]
    tables: Dict[str, int]

    @property
    def source_major(self) -> int:
        return self.source_server_version_num // 10000

    @property
    def pg_dump_major(self) -> int:
        parsed = parse_pg_version(self.pg_dump_version)
        return parsed[1] if parsed else self.source_major

    @property
    def total_rows(self) -> int:
        return sum(self.tables.values())

    def to_dict(self) -> Dict[str, object]:
        return {
            "format_version": MANIFEST_FORMAT_VERSION,
            "name": self.name,
            "created_at": self.created_at,
            "git_commit": self.git_commit,
            "pg_dump_version": self.pg_dump_version,
            "dump": {"file": self.dump_file, "size_bytes": self.dump_size_bytes, "sha256": self.dump_sha256},
            "source": {
                "database": self.source_database,
                "server_version": self.source_server_version,
                "server_version_num": self.source_server_version_num,
                "timezone": self.source_timezone,
                "encoding": self.source_encoding,
                "lc_collate": self.source_lc_collate,
            },
            "alembic": {"database_version": self.alembic_database_version, "code_head": self.alembic_code_head},
            "total_rows": self.total_rows,
            "tables": dict(sorted(self.tables.items())),
        }

    def to_json(self) -> str:
        """Stable output: sorted keys at every level, UTF-8 friendly, newline-terminated."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    @classmethod
    def from_json(cls, raw: str) -> "Manifest":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ManifestError(f"manifest is not valid JSON: {exc.msg} (line {exc.lineno})") from None
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: object) -> "Manifest":
        if not isinstance(data, dict):
            raise ManifestError("manifest must be a JSON object")
        if data.get("format_version") != MANIFEST_FORMAT_VERSION:
            raise ManifestError(
                f"unsupported manifest format_version {data.get('format_version')!r} "
                f"(this tool reads version {MANIFEST_FORMAT_VERSION})"
            )

        def section(parent: Mapping[str, object], key: str, label: str) -> Mapping[str, object]:
            value = parent.get(key)
            if not isinstance(value, dict):
                raise ManifestError(f"manifest: '{label}' must be an object")
            return value

        def text_field(parent: Mapping[str, object], key: str, label: str, optional: bool = False) -> Optional[str]:
            value = parent.get(key)
            if value is None and optional:
                return None
            if not isinstance(value, str) or not value.strip():
                raise ManifestError(f"manifest: '{label}' must be a non-empty string")
            return value

        def int_field(parent: Mapping[str, object], key: str, label: str) -> int:
            value = parent.get(key)
            if not _is_int(value) or value < 0:  # type: ignore[operator]
                raise ManifestError(f"manifest: '{label}' must be a non-negative integer")
            return value  # type: ignore[return-value]

        dump = section(data, "dump", "dump")
        source = section(data, "source", "source")
        alembic = section(data, "alembic", "alembic")
        sha256 = text_field(dump, "sha256", "dump.sha256") or ""
        if not _SHA256.match(sha256):
            raise ManifestError("manifest: 'dump.sha256' must be 64 lowercase hex characters")
        created_at = text_field(data, "created_at", "created_at") or ""
        try:
            datetime.fromisoformat(created_at)
        except ValueError:
            raise ManifestError("manifest: 'created_at' must be an ISO 8601 timestamp") from None

        raw_tables = data.get("tables")
        if not isinstance(raw_tables, dict):
            raise ManifestError("manifest: 'tables' must be an object of table name -> row count")
        tables: Dict[str, int] = {}
        for table, count in raw_tables.items():
            if not _is_int(count) or count < 0:
                raise ManifestError(f"manifest: row count of table '{table}' must be a non-negative integer")
            tables[str(table)] = count

        return cls(
            name=text_field(data, "name", "name") or "",
            created_at=created_at,
            git_commit=text_field(data, "git_commit", "git_commit", optional=True),
            pg_dump_version=text_field(data, "pg_dump_version", "pg_dump_version") or "",
            dump_file=text_field(dump, "file", "dump.file") or "",
            dump_size_bytes=int_field(dump, "size_bytes", "dump.size_bytes"),
            dump_sha256=sha256,
            source_database=text_field(source, "database", "source.database") or "",
            source_server_version=text_field(source, "server_version", "source.server_version") or "",
            source_server_version_num=int_field(source, "server_version_num", "source.server_version_num"),
            source_timezone=text_field(source, "timezone", "source.timezone") or "",
            source_encoding=text_field(source, "encoding", "source.encoding") or "",
            source_lc_collate=text_field(source, "lc_collate", "source.lc_collate", optional=True),
            alembic_database_version=text_field(alembic, "database_version", "alembic.database_version", optional=True),
            alembic_code_head=text_field(alembic, "code_head", "alembic.code_head", optional=True),
            tables=tables,
        )


def manifest_path_for(dump: Path) -> Path:
    """``backups/x.dump`` -> ``backups/x.manifest.json`` (same stem, same folder)."""
    return dump.with_name(f"{dump.stem}{MANIFEST_SUFFIX}")


def load_manifest(path: Path) -> Manifest:
    if not path.is_file():
        raise ManifestError(f"manifest not found: {path} (it must sit next to the dump, with the same name)")
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise ManifestError(f"cannot read the manifest {path}: {exc}") from None
    return Manifest.from_json(raw)


def write_manifest(path: Path, manifest: Manifest) -> None:
    """Writes through a temp file so a crash never leaves a half-written manifest next to a good dump."""
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_text(manifest.to_json(), encoding="utf-8", newline="\n")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def hash_file(path: Path) -> Tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


# --------------------------------------------------------------------------------------------------------------------
# Row counts, versions, paths
# --------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class CountRow:
    table: str
    expected: Optional[int]  # None = the table is not in the manifest
    actual: Optional[int]  # None = the table is missing from the database

    @property
    def ok(self) -> bool:
        return self.expected is not None and self.expected == self.actual


def compare_counts(expected: Mapping[str, int], actual: Mapping[str, int]) -> List[CountRow]:
    """One row per table in either side, sorted by name. Missing, extra and different counts are all mismatches."""
    return [CountRow(name, expected.get(name), actual.get(name)) for name in sorted(set(expected) | set(actual))]


def format_comparison(rows: Sequence[CountRow], alembic_expected: Optional[str], alembic_actual: Optional[str]) -> str:
    width = max([len("table")] + [len(row.table) for row in rows])

    def cell(value: Optional[int]) -> str:
        return "-" if value is None else f"{value:,}"

    lines = [f"{'table':<{width}}  {'expected':>14}  {'actual':>14}  status"]
    for row in rows:
        lines.append(f"{row.table:<{width}}  {cell(row.expected):>14}  {cell(row.actual):>14}  {'OK' if row.ok else 'MISMATCH'}")
    revision_ok = alembic_expected == alembic_actual
    lines.append(
        f"alembic version: expected {alembic_expected or 'none'}, actual {alembic_actual or 'none'}: "
        f"{'OK' if revision_ok else 'MISMATCH'}"
    )
    return "\n".join(lines)


def check_target_version(manifest: Manifest, target_major: int, target_version: str) -> None:
    """A dump restores into the same PostgreSQL major or a newer one, never an older one."""
    if target_major < manifest.source_major:
        raise PreconditionError(
            f"The target server runs PostgreSQL {target_version} but the dump comes from PostgreSQL "
            f"{manifest.source_server_version}. A dump can only be restored into the same major version or a newer "
            f"one. Install PostgreSQL {manifest.source_major} (or newer) on the target and retry."
        )


def default_backup_dir(repo_root: Path) -> Path:
    return repo_root.parent / BACKUP_DIR_NAME


def default_dump_name(now: datetime) -> str:
    local = now.astimezone() if now.tzinfo else now
    return f"nba_platform_{local:%Y%m%d_%H%M}"


def is_within(path: Path, root: Path) -> bool:
    """True when ``path`` is ``root`` or below it, after resolving symlinks and ``..`` (non-strict: path may not exist)."""
    resolved = os.path.normcase(os.path.realpath(path))
    base = os.path.normcase(os.path.realpath(root))
    try:
        return os.path.commonpath([resolved, base]) == base
    except ValueError:  # different drives on Windows
        return False


def ensure_outside_repo(path: Path, repo_root: Path) -> Path:
    """Dumps hold private data and odds-provider content: refuse to write them anywhere inside the working tree."""
    if is_within(path, repo_root):
        raise PreconditionError(
            f"Refusing to write inside the repository working tree ({repo_root}): {path}. A dump must never end up "
            "in git. Pick a directory outside the repository (the default is the sibling folder "
            f"'{BACKUP_DIR_NAME}')."
        )
    return Path(os.path.realpath(path))


# --------------------------------------------------------------------------------------------------------------------
# Environment probes
# --------------------------------------------------------------------------------------------------------------------
def get_code_head(backend_dir: Optional[Path] = None) -> Optional[str]:
    """Alembic head revision(s) of the checked-out code (comma separated if branched); None if unreadable."""
    base = backend_dir or BACKEND_DIR
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        config = Config()
        config.set_main_option("script_location", str(base / "alembic").replace("%", "%%"))
        heads = ScriptDirectory.from_config(config).get_heads()
    except Exception:  # noqa: BLE001 - the head is advisory; export must not fail because of it
        return None
    return ",".join(sorted(heads)) or None


def get_git_commit(runner: ProcessRunner, repo_root: Path) -> Optional[str]:
    try:
        result = runner.run(["git", "-C", str(repo_root), "rev-parse", "HEAD"])
    except TransferError:
        return None
    commit = result.stdout.strip()
    return commit if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{7,64}", commit) else None


# --------------------------------------------------------------------------------------------------------------------
# Database seam
# --------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ServerInfo:
    version: str
    version_num: int
    timezone: str
    encoding: str
    lc_collate: Optional[str] = None

    @property
    def major(self) -> int:
        return self.version_num // 10000


class Inspector(Protocol):
    """SQL against ONE database. ``snapshot`` pins a REPEATABLE READ transaction that later reads share."""

    def server_info(self) -> ServerInfo: ...

    def database_exists(self, name: str) -> bool: ...

    def table_names(self) -> List[str]: ...

    def table_counts(self) -> Dict[str, int]: ...

    def alembic_version(self) -> Optional[str]: ...

    def snapshot(self) -> ContextManager[str]: ...

    def create_database(self, name: str, encoding: str) -> None: ...

    def reset_public_schema(self) -> None: ...

    def analyze(self) -> None: ...


class SqlInspector:
    """``Inspector`` over SQLAlchemy + psycopg 3. One short-lived connection per call (NullPool)."""

    def __init__(self, target: DbTarget):
        self._target = target
        try:
            self._engine = create_engine(target.url, poolclass=NullPool)
        except ImportError:  # requirements.txt lists psycopg2 only, while the app talks to PostgreSQL through psycopg 3
            raise PreconditionError("the psycopg 3 driver is not installed; run: pip install \"psycopg[binary]\"") from None
        self._pinned: Optional[Connection] = None

    def _error(self, exc: SQLAlchemyError, what: str, kind: type = OperationError) -> TransferError:
        detail = str(getattr(exc, "orig", None) or exc).strip().splitlines()
        reason = scrub(detail[0] if detail else type(exc).__name__, self._target.secrets)[:300]
        return kind(f"{what}: {reason}")

    def _connect_error(self, exc: SQLAlchemyError) -> TransferError:
        return self._error(exc, f"cannot connect to {self._target.masked()}", PreconditionError)

    def _failed(self, exc: SQLAlchemyError, what: str) -> TransferError:
        return self._error(exc, f"{what} on database '{self._target.database}' failed")

    @contextmanager
    def _connection(self, autocommit: bool = False) -> Iterator[Connection]:
        """The pinned snapshot connection when one is open (reads only), else a fresh short-lived connection."""
        pinned = self._pinned is not None and not autocommit
        try:
            connection = self._pinned if pinned else self._engine.connect()
        except SQLAlchemyError as exc:
            raise self._connect_error(exc) from None
        try:
            if autocommit and not pinned:
                connection = connection.execution_options(isolation_level="AUTOCOMMIT")
            yield connection
        except SQLAlchemyError as exc:
            raise self._failed(exc, "a query") from None
        finally:
            if not pinned:
                connection.close()

    def server_info(self) -> ServerInfo:
        with self._connection() as conn:
            version = str(conn.execute(text("SHOW server_version")).scalar_one()).split()[0]
            version_num = int(conn.execute(text("SHOW server_version_num")).scalar_one())
            timezone_name = str(conn.execute(text("SHOW timezone")).scalar_one())
            encoding = str(conn.execute(text("SHOW server_encoding")).scalar_one())
            collate = conn.execute(
                text("SELECT datcollate FROM pg_database WHERE datname = current_database()")
            ).scalar_one_or_none()
        return ServerInfo(version, version_num, timezone_name, encoding, collate)

    def database_exists(self, name: str) -> bool:
        with self._connection() as conn:
            return conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}).first() is not None

    @staticmethod
    def _tables(conn: Connection) -> List[Tuple[str, str]]:
        rows = conn.execute(
            text(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_type = 'BASE TABLE' "
                "AND table_schema <> 'information_schema' AND table_schema !~ '^pg_' "
                "ORDER BY table_schema, table_name"
            )
        ).all()
        return [(str(schema), str(table)) for schema, table in rows]

    def table_names(self) -> List[str]:
        with self._connection() as conn:
            return [f"{schema}.{table}" for schema, table in self._tables(conn)]

    def table_counts(self) -> Dict[str, int]:
        """Exact ``count(*)`` of every user table, keyed ``schema.table``."""
        with self._connection() as conn:
            return {
                f"{schema}.{table}": int(
                    conn.execute(text(f"SELECT count(*) FROM {quote_ident(schema)}.{quote_ident(table)}")).scalar_one()
                )
                for schema, table in self._tables(conn)
            }

    def alembic_version(self) -> Optional[str]:
        with self._connection() as conn:
            if conn.execute(text("SELECT to_regclass('alembic_version')::text")).scalar_one() is None:
                return None
            revisions = [str(row[0]) for row in conn.execute(text("SELECT version_num FROM alembic_version ORDER BY 1"))]
        return ",".join(revisions) or None

    @contextmanager
    def snapshot(self) -> Iterator[str]:
        """Keeps one REPEATABLE READ transaction open and yields its exported snapshot id for ``pg_dump --snapshot``."""
        try:
            connection = self._engine.connect()
        except SQLAlchemyError as exc:
            raise self._connect_error(exc) from None
        try:
            connection = connection.execution_options(isolation_level="REPEATABLE READ", postgresql_readonly=True)
            snapshot_id = str(connection.execute(text("SELECT pg_export_snapshot()")).scalar_one())
            self._pinned = connection
            yield snapshot_id
        except SQLAlchemyError as exc:
            raise self._failed(exc, "exporting a snapshot") from None
        finally:
            self._pinned = None
            connection.close()

    def create_database(self, name: str, encoding: str) -> None:
        if not _ENCODING_NAME.match(encoding):
            raise PreconditionError(f"unsupported encoding name in the manifest: {encoding!r}")
        with self._connection(autocommit=True) as conn:
            conn.execute(text(f"CREATE DATABASE {quote_ident(validate_database_name(name))} ENCODING '{encoding}' TEMPLATE template0"))

    def reset_public_schema(self) -> None:
        try:
            with self._engine.begin() as conn:
                conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
                conn.execute(text("CREATE SCHEMA public"))
                conn.execute(text("GRANT USAGE ON SCHEMA public TO PUBLIC"))
        except SQLAlchemyError as exc:
            raise self._failed(exc, "resetting the public schema") from None

    def analyze(self) -> None:
        with self._connection(autocommit=True) as conn:
            conn.execute(text("ANALYZE"))


# --------------------------------------------------------------------------------------------------------------------
# Service
# --------------------------------------------------------------------------------------------------------------------
@dataclass
class ExportResult:
    dump_path: Path
    manifest_path: Path
    manifest: Manifest
    warnings: List[str] = field(default_factory=list)


@dataclass
class VerifyResult:
    dump_path: Path
    manifest_path: Path
    manifest: Manifest
    tools: PgTools
    archive_entries: int
    warnings: List[str] = field(default_factory=list)


@dataclass
class ImportResult:
    manifest: Manifest
    rows: List[CountRow]
    alembic_expected: Optional[str]
    alembic_actual: Optional[str]
    created_database: bool = False
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(row.ok for row in self.rows) and self.alembic_expected == self.alembic_actual

    @property
    def mismatches(self) -> List[CountRow]:
        return [row for row in self.rows if not row.ok]


class TransferService:
    def __init__(
        self,
        runner: ProcessRunner,
        inspector_factory: Callable[[DbTarget], Inspector],
        find_tools: Callable[[Optional[int]], PgTools],
        *,
        repo_root: Path = REPO_ROOT,
        code_head: Callable[[], Optional[str]] = get_code_head,
        git_commit: Optional[Callable[[], Optional[str]]] = None,
        now: Optional[Callable[[], datetime]] = None,
        log: Optional[Callable[[str], None]] = None,
    ):
        self._runner = runner
        self._inspector_factory = inspector_factory
        self._find_tools = find_tools
        self._repo_root = repo_root
        self._code_head = code_head
        self._git_commit = git_commit or (lambda: get_git_commit(runner, repo_root))
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._log = log or (lambda message: None)

    # -- export ----------------------------------------------------------------------------------------------------
    def export_database(
        self, source: DbTarget, *, out_dir: Optional[Path] = None, name: Optional[str] = None
    ) -> ExportResult:
        now = self._now()
        directory = ensure_outside_repo(
            Path(out_dir).expanduser() if out_dir else default_backup_dir(self._repo_root), self._repo_root
        )
        name = name or default_dump_name(now)
        if not _DUMP_NAME.match(name):
            raise PreconditionError(f"unsupported --name {name!r} (letters, digits, '_', '.', '-'; no path separators)")
        dump_path = directory / f"{name}{DUMP_SUFFIX}"
        manifest_path = directory / f"{name}{MANIFEST_SUFFIX}"
        partial_path = directory / f"{name}{DUMP_SUFFIX}.part"
        for existing in (dump_path, manifest_path):
            if existing.exists():
                raise PreconditionError(f"{existing} already exists; choose another --name (backups are never overwritten)")

        self._log(f"Source database: {source.masked()}")
        inspector = self._inspector_factory(source)
        info = inspector.server_info()
        tools = self._find_tools(info.major)
        self._log(f"PostgreSQL server {info.version}; using client tools {tools.version_text} from {tools.bin_dir}")
        code_head = self._code_head()
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PreconditionError(f"cannot create the output folder {directory}: {exc.strerror or exc}") from None

        try:
            with inspector.snapshot() as snapshot_id:
                self._log("Counting the rows of every table (exact counts, same snapshot as the dump) ...")
                counts = inspector.table_counts()
                database_revision = inspector.alembic_version()
                self._run_pg_dump(tools, source, snapshot_id, partial_path)
            digest, size = hash_file(partial_path)
            os.replace(partial_path, dump_path)
        finally:
            partial_path.unlink(missing_ok=True)

        manifest = Manifest(
            name=name,
            created_at=now.astimezone(timezone.utc).isoformat(timespec="seconds"),
            git_commit=self._git_commit(),
            pg_dump_version=tools.version_text,
            dump_file=dump_path.name,
            dump_size_bytes=size,
            dump_sha256=digest,
            source_database=source.database,
            source_server_version=info.version,
            source_server_version_num=info.version_num,
            source_timezone=info.timezone,
            source_encoding=info.encoding,
            source_lc_collate=info.lc_collate,
            alembic_database_version=database_revision,
            alembic_code_head=code_head,
            tables=counts,
        )
        write_manifest(manifest_path, manifest)

        try:
            self._check_archive(tools, dump_path)
        except TransferError as exc:
            dump_path.unlink(missing_ok=True)
            manifest_path.unlink(missing_ok=True)
            raise OperationError(f"the dump was written but is not readable, so it was discarded: {exc}") from None

        warnings: List[str] = []
        if code_head and database_revision != code_head:
            warnings.append(
                f"the database is at Alembic revision {database_revision or 'none'} but the code head is "
                f"{code_head}; the dump keeps the database revision (run 'alembic upgrade head' after importing "
                "if you want the code's schema)"
            )
        return ExportResult(dump_path, manifest_path, manifest, warnings)

    def _run_pg_dump(self, tools: PgTools, source: DbTarget, snapshot_id: str, output: Path) -> None:
        if not _SNAPSHOT_ID.match(snapshot_id):
            raise OperationError("the server returned an unexpected snapshot id")
        argv = [
            str(tools.pg_dump),
            "-Fc",
            "--no-owner",
            "--no-privileges",
            "--no-password",
            f"--snapshot={snapshot_id}",
            *source.libpq_args(),
            "--file",
            str(output),
        ]
        self._log("$ " + shlex.join(argv))
        result = self._runner.run(argv, env=source.libpq_env())
        if result.returncode != 0:
            raise OperationError(
                f"pg_dump failed (exit code {result.returncode}):\n{_tail(result.stderr or result.stdout, source.secrets)}"
            )

    # -- verify ----------------------------------------------------------------------------------------------------
    def verify_dump(self, dump: Path) -> VerifyResult:
        dump = Path(dump)
        manifest, manifest_path, warnings = self._check_integrity(dump)
        tools = self._find_tools(manifest.pg_dump_major)
        entries = self._check_archive(tools, dump)
        self._log(f"[ok] pg_restore {tools.version_text} reads the archive ({entries} entries)")
        return VerifyResult(dump, manifest_path, manifest, tools, entries, warnings)

    def _check_integrity(self, dump: Path) -> Tuple[Manifest, Path, List[str]]:
        if not dump.is_file():
            raise PreconditionError(f"dump file not found: {dump}")
        manifest_path = manifest_path_for(dump)
        manifest = load_manifest(manifest_path)
        self._log(
            f"[ok] manifest {manifest_path.name}: {manifest.name}, created {manifest.created_at}, PostgreSQL "
            f"{manifest.source_server_version}, {len(manifest.tables)} tables, {manifest.total_rows:,} rows"
        )
        warnings: List[str] = []
        if dump.name != manifest.dump_file:
            warnings.append(f"the dump is named {dump.name} but the manifest describes {manifest.dump_file}")
        digest, size = hash_file(dump)
        if size != manifest.dump_size_bytes or digest != manifest.dump_sha256:
            raise IntegrityError(
                "integrity check failed: the dump does not match its manifest.\n"
                f"  expected: {manifest.dump_size_bytes} bytes, sha256 {manifest.dump_sha256}\n"
                f"  actual:   {size} bytes, sha256 {digest}\n"
                "The file was corrupted or modified in transit; copy it again from the source."
            )
        self._log(f"[ok] size and sha256 match the manifest ({format_size(size)})")
        return manifest, manifest_path, warnings

    def _check_archive(self, tools: PgTools, dump: Path) -> int:
        result = self._runner.run([str(tools.pg_restore), "--list", str(dump)])
        if result.returncode != 0:
            raise IntegrityError(
                f"pg_restore cannot read the archive (exit code {result.returncode}):\n{_tail(result.stderr, [])}"
            )
        entries = [line for line in result.stdout.splitlines() if line.strip() and not line.startswith(";")]
        if not entries:
            raise IntegrityError("pg_restore lists no entries: the archive is empty or not a custom-format dump")
        return len(entries)

    # -- import ----------------------------------------------------------------------------------------------------
    def import_dump(
        self,
        dump: Path,
        target: DbTarget,
        *,
        create_db: bool = False,
        replace: bool = False,
        confirm_database: Optional[str] = None,
        skip_analyze: bool = False,
    ) -> ImportResult:
        database = target.database
        if confirm_database is not None and not replace:
            raise PreconditionError("--confirm-database only applies together with --replace")
        if replace and confirm_database != database:
            raise PreconditionError(
                f"--replace wipes EVERYTHING in database '{database}'. To confirm, pass --confirm-database {database} "
                "(the exact name of the target database)."
            )

        dump = Path(dump)
        verified = self.verify_dump(dump)
        manifest = verified.manifest
        warnings = list(verified.warnings)

        self._log(f"Target database: {target.masked()}")
        target_inspector = self._inspector_factory(target)
        created = False
        try:
            info = target_inspector.server_info()
        except PreconditionError as connect_error:
            if create_db and self._missing_database(target):
                maintenance = self._maintenance_inspector(target)
                info = maintenance.server_info()
                self._precheck_target(manifest, info)
                tools = self._restore_tools(verified.tools, manifest, info)
                self._log(f"Creating database '{database}' (encoding {manifest.source_encoding}) ...")
                maintenance.create_database(database, manifest.source_encoding)
                created = True
                info = target_inspector.server_info()
            elif create_db:
                raise
            else:
                raise PreconditionError(
                    f"{connect_error}\nIf the database does not exist yet, create it first or pass --create-db."
                ) from None
        else:
            self._precheck_target(manifest, info)
            tools = self._restore_tools(verified.tools, manifest, info)

        if info.timezone != manifest.source_timezone:
            warnings.append(
                f"the target timezone setting is '{info.timezone}' but the source used '{manifest.source_timezone}'. "
                "Stored timestamps are unaffected; only how psql-style sessions display them changes"
            )
        if info.encoding.upper() != manifest.source_encoding.upper():
            warnings.append(
                f"the target database encoding is {info.encoding} but the source used {manifest.source_encoding}; "
                "text that cannot be represented will make the restore fail"
            )
        current_head = self._code_head()
        if current_head and manifest.alembic_code_head and current_head != manifest.alembic_code_head:
            warnings.append(
                f"this checkout's Alembic head is {current_head} but the export was made at {manifest.alembic_code_head}"
                f" (git commit {manifest.git_commit or 'unknown'}); check out that commit or run 'alembic upgrade head'"
            )

        if not created:
            self._require_empty_or_replace(target_inspector, database, replace)
        if replace and not created:
            self._log(f"--replace confirmed: dropping and recreating the public schema of '{database}' ...")
            target_inspector.reset_public_schema()

        self._run_pg_restore(tools, target, dump, created=created, replaced=replace and not created)

        if not skip_analyze:
            self._log("Running ANALYZE ...")
            try:
                target_inspector.analyze()
            except TransferError as exc:
                warnings.append(f"ANALYZE failed (the data is restored; run ANALYZE manually): {exc}")

        self._log("Comparing the exact row count of every table with the manifest ...")
        actual_counts = target_inspector.table_counts()
        actual_revision = target_inspector.alembic_version()
        return ImportResult(
            manifest=manifest,
            rows=compare_counts(manifest.tables, actual_counts),
            alembic_expected=manifest.alembic_database_version,
            alembic_actual=actual_revision,
            created_database=created,
            warnings=warnings,
        )

    def _precheck_target(self, manifest: Manifest, info: ServerInfo) -> None:
        check_target_version(manifest, info.major, info.version)
        self._log(f"[ok] target server PostgreSQL {info.version} can restore a PostgreSQL {manifest.source_server_version} dump")

    def _restore_tools(self, current: PgTools, manifest: Manifest, info: ServerInfo) -> PgTools:
        required = max(manifest.pg_dump_major, info.major)
        return current if current.major >= required else self._find_tools(required)

    def _missing_database(self, target: DbTarget) -> bool:
        """True when a maintenance connection works and the target database is not in the catalog."""
        try:
            return not self._maintenance_inspector(target).database_exists(target.database)
        except TransferError:
            return False

    def _maintenance_inspector(self, target: DbTarget) -> Inspector:
        last: Optional[TransferError] = None
        for name in ("postgres", "template1"):
            inspector = self._inspector_factory(target.with_database(name))
            try:
                inspector.server_info()
                return inspector
            except TransferError as exc:
                last = exc
        raise PreconditionError(f"cannot connect to a maintenance database (postgres or template1) to create the target: {last}")

    def _require_empty_or_replace(self, inspector: Inspector, database: str, replace: bool) -> None:
        existing = sorted(inspector.table_names())
        if existing and not replace:
            shown = ", ".join(existing[:5]) + (", ..." if len(existing) > 5 else "")
            raise PreconditionError(
                f"The target database '{database}' is not empty: it already has {len(existing)} table(s) ({shown}). "
                "Import into a new, empty database, or add --replace --confirm-database "
                f"{database} to wipe it first."
            )

    def _run_pg_restore(self, tools: PgTools, target: DbTarget, dump: Path, *, created: bool, replaced: bool) -> None:
        argv = [
            str(tools.pg_restore),
            "--no-owner",
            "--no-privileges",
            "--exit-on-error",
            "--single-transaction",
            "--no-password",
            *target.libpq_args(),
            str(dump),
        ]
        self._log("$ " + shlex.join(argv))
        result = self._runner.run(argv, env=target.libpq_env())
        if result.returncode == 0:
            return
        if replaced:
            state = "The restore was rolled back, but the public schema had already been reset, so the database is now empty."
        elif created:
            state = f"The restore was rolled back; the new database '{target.database}' exists but is empty."
        else:
            state = "The restore ran in a single transaction and was rolled back; the database is unchanged."
        raise OperationError(
            f"pg_restore failed (exit code {result.returncode}). {state}\n{_tail(result.stderr or result.stdout, target.secrets)}"
        )
