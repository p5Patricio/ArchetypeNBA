"""
Behavior tests for the database export/import tool (app/services/db_transfer.py and scripts/db_transfer.py).

Nothing here needs PostgreSQL: the process seam (pg_dump / pg_restore / git) is a FakeRunner and the SQL seam is a
FakeInspector over a FakeServer, so the tests check what the tool decides and what it would have run.
"""
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

import pytest

from app.services import db_transfer as dt
from app.services.db_transfer import (
    DbTarget,
    IntegrityError,
    Manifest,
    ManifestError,
    OperationError,
    PgTools,
    PreconditionError,
    ProcessResult,
    ServerInfo,
    TransferService,
)

PASSWORD = "s3cr3t-P@ss"
SOURCE_URL = f"postgresql://nba:{quote(PASSWORD, safe='')}@localhost:5432/nba_platform"
HEAD = "d7a2f5b81c39"
NAME = "nba_platform_20261026_1530"
NOW = datetime(2026, 10, 26, 21, 30, tzinfo=timezone.utc)
SOURCE_TABLES = {"public.alembic_version": 1, "public.game_log": 1200, "public.jugadores_ñ": 450, "public.players": 0}


# --------------------------------------------------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------------------------------------------------
@dataclass
class Call:
    argv: Tuple[str, ...]
    env: Dict[str, str]


class FakeDatabase:
    def __init__(self, tables: Optional[Dict[str, int]] = None, alembic: Optional[str] = None):
        self.tables = dict(tables or {})
        self.alembic = alembic


class FakeServer:
    """One PostgreSQL server: the databases it holds plus an ordered log of the effects that happened."""

    def __init__(self, version_num: int = 180000, timezone_name: str = "America/Mexico_City", encoding: str = "UTF8"):
        self.info = ServerInfo(f"{version_num // 10000}.{version_num % 10000}", version_num, timezone_name, encoding, "C")
        self.databases: Dict[str, FakeDatabase] = {}
        self.events: List[str] = []
        self.connected: List[DbTarget] = []
        self.no_maintenance = False
        self.analyze_fails = False


class FakeInspector:
    def __init__(self, server: FakeServer, target: DbTarget):
        self.server = server
        self.name = target.database
        server.connected.append(target)

    def _db(self) -> FakeDatabase:
        if self.name in ("postgres", "template1") and not self.server.no_maintenance:
            return self.server.databases.setdefault(self.name, FakeDatabase())
        if self.name not in self.server.databases:
            raise PreconditionError(f"connecting to database '{self.name}' failed: it does not exist")
        return self.server.databases[self.name]

    def server_info(self) -> ServerInfo:
        self._db()
        return self.server.info

    def database_exists(self, name: str) -> bool:
        return name in self.server.databases or name in ("postgres", "template1")

    def table_names(self) -> List[str]:
        return sorted(self._db().tables)

    def table_counts(self) -> Dict[str, int]:
        return dict(self._db().tables)

    def alembic_version(self) -> Optional[str]:
        return self._db().alembic

    @contextmanager
    def snapshot(self):
        self.server.events.append("snapshot-open")
        try:
            yield "00000003-0000001B-1"
        finally:
            self.server.events.append("snapshot-close")

    def create_database(self, name: str, encoding: str) -> None:
        self.server.events.append(f"create:{name}:{encoding}")
        self.server.databases[name] = FakeDatabase()

    def reset_public_schema(self) -> None:
        self.server.events.append(f"reset:{self.name}")
        db = self._db()
        db.tables.clear()
        db.alembic = None

    def analyze(self) -> None:
        self.server.events.append(f"analyze:{self.name}")
        if self.server.analyze_fails:
            raise OperationError("analyze failed")


class FakeRunner:
    """Stands in for pg_dump / pg_restore / git. Records every call (argv + env) for the secrecy assertions."""

    def __init__(self, server: FakeServer):
        self.server = server
        self.calls: List[Call] = []
        self.bin_versions: Dict[str, str] = {}
        self.default_version = "18.0"
        self.dump_payload = b"PGDMP fake archive contents " * 64
        self.dump_returncode = 0
        self.dump_stderr = ""
        self.list_returncode = 0
        self.list_stdout = ";\n; Archive created at 2026-10-26\n1259; 1259 16400 TABLE public players nba\n2615; 0 2200 SCHEMA - public\n"
        self.restore_returncode = 0
        self.restore_stderr = ""
        self.restore_tables: Dict[str, int] = dict(SOURCE_TABLES)
        self.restore_alembic: Optional[str] = HEAD

    def run(self, argv, env=None) -> ProcessResult:
        argv = tuple(argv)
        self.calls.append(Call(argv, dict(env or {})))
        tool = Path(argv[0]).stem
        if tool == "git":
            return ProcessResult(0, "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678\n")
        if "--version" in argv:
            version = self.bin_versions.get(str(Path(argv[0]).parent), self.default_version)
            return ProcessResult(0, f"{tool} (PostgreSQL) {version}\n")
        if tool == "pg_dump":
            self.server.events.append("pg_dump")
            if self.dump_returncode == 0:
                Path(argv[argv.index("--file") + 1]).write_bytes(self.dump_payload)
            return ProcessResult(self.dump_returncode, "", self.dump_stderr)
        if tool == "pg_restore" and "--list" in argv:
            if self.list_returncode != 0:
                return ProcessResult(self.list_returncode, "", "pg_restore: error: unsupported version (1.16) in file header")
            return ProcessResult(0, self.list_stdout)
        if tool == "pg_restore":
            self.server.events.append("pg_restore")
            if self.restore_returncode == 0:
                database = self.server.databases[argv[argv.index("--dbname") + 1]]
                database.tables = dict(self.restore_tables)
                database.alembic = self.restore_alembic
            return ProcessResult(self.restore_returncode, "", self.restore_stderr)
        raise AssertionError(f"unexpected command {argv}")

    def calls_of(self, tool: str) -> List[Call]:
        return [c for c in self.calls if Path(c.argv[0]).stem == tool and "--version" not in c.argv]


def make_tools(major: int = 18) -> PgTools:
    bin_dir = Path(f"/pg{major}/bin")
    return PgTools(bin_dir, major, bin_dir / "pg_dump", bin_dir / "pg_restore", f"{major}.0")


class Harness:
    """A TransferService wired to fakes, with a repository folder and a backups folder under ``root``."""

    def __init__(
        self,
        root: Path,
        *,
        server: Optional[FakeServer] = None,
        with_source: bool = True,
        code_head: Optional[str] = HEAD,
        find_tools: Optional[Callable[[Optional[int]], PgTools]] = None,
    ):
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self.repo = root / "repo"
        self.repo.mkdir(exist_ok=True)
        self.backups = root / "backups"
        self.server = server or FakeServer()
        if with_source:
            self.server.databases["nba_platform"] = FakeDatabase(SOURCE_TABLES, HEAD)
        self.runner = FakeRunner(self.server)
        self.logs: List[str] = []
        self.requested_majors: List[Optional[int]] = []

        def default_find(required: Optional[int]) -> PgTools:
            self.requested_majors.append(required)
            return make_tools(18)

        self.service = TransferService(
            self.runner,
            lambda target: FakeInspector(self.server, target),
            find_tools or default_find,
            repo_root=self.repo,
            code_head=lambda: code_head,
            now=lambda: NOW,
            log=self.logs.append,
        )

    def export(self, **kwargs):
        kwargs.setdefault("out_dir", self.backups)
        kwargs.setdefault("name", NAME)
        return self.service.export_database(DbTarget.from_url(SOURCE_URL), **kwargs)


def target_url(database: str = "nba_platform") -> str:
    return f"postgresql://nba:{quote(PASSWORD, safe='')}@localhost:5432/{database}"


@pytest.fixture
def exported(tmp_path):
    """A real dump + manifest written by the service from the fake source server."""
    source = Harness(tmp_path / "src")
    return source.export()


def importer(tmp_path, *, version_num: int = 180000, existing: Optional[Dict[str, int]] = None, **kwargs) -> Harness:
    server = FakeServer(version_num=version_num)
    if existing is not None:
        server.databases["nba_platform"] = FakeDatabase(existing, None)
    return Harness(tmp_path / "dst", server=server, with_source=False, **kwargs)


def do_import(harness: Harness, exported, **kwargs):
    return harness.service.import_dump(exported.dump_path, DbTarget.from_url(target_url()), **kwargs)


def link_directory(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    if sys.platform == "win32":  # a junction needs no privilege and resolves like a symlink
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        if done.returncode == 0:
            return
    pytest.skip("cannot create a directory link on this machine")


# --------------------------------------------------------------------------------------------------------------------
# Connection target
# --------------------------------------------------------------------------------------------------------------------
def test_database_target_keeps_the_password_out_of_argv_and_echoes():
    target = DbTarget.from_url(SOURCE_URL)

    assert target.libpq_args() == ["--host", "localhost", "--port", "5432", "--username", "nba", "--dbname", "nba_platform"]
    assert target.libpq_env() == {"PGPASSWORD": PASSWORD}  # the URL's %40 is decoded for libpq
    assert PASSWORD not in target.masked() and "***" in target.masked()
    assert PASSWORD not in repr(target)
    assert target.with_database("postgres").database == "postgres"


def test_database_target_accepts_driver_variants_and_omits_missing_parts():
    for raw in ("postgres://u@h/db", "postgresql+psycopg2://u@h/db", "postgresql+psycopg://u@h/db"):
        assert DbTarget.from_url(raw).url.drivername == "postgresql+psycopg"

    bare = DbTarget.from_url("postgresql:///nba_platform?sslmode=require")
    assert bare.libpq_args() == ["--dbname", "nba_platform"]
    assert bare.libpq_env() == {"PGSSLMODE": "require"}


@pytest.mark.parametrize(
    "raw", ["sqlite:///x.db", "postgresql://u:p@h:5432/", "postgresql://u:p@h/bad=name", "postgresql://u:p@h/-oops", "not a url"]
)
def test_database_target_rejects_bad_urls_without_echoing_secrets(raw):
    with pytest.raises(PreconditionError) as excinfo:
        DbTarget.from_url(raw)

    assert excinfo.value.exit_code == 2
    assert ":p@" not in str(excinfo.value)


def test_unparseable_url_error_never_contains_the_input():
    with pytest.raises(PreconditionError) as excinfo:
        DbTarget.from_url(f"this is not a url but has {PASSWORD}")

    assert PASSWORD not in str(excinfo.value)


def test_a_failing_connection_reports_the_reason_without_the_password():
    inspector = dt.SqlInspector(DbTarget.from_url(f"postgresql://nba:{quote(PASSWORD, safe='')}@127.0.0.1:1/nba_platform?connect_timeout=2"))

    with pytest.raises(PreconditionError) as excinfo:
        inspector.server_info()

    assert PASSWORD not in str(excinfo.value)
    assert "127.0.0.1" in str(excinfo.value) or "nba_platform" in str(excinfo.value)


# --------------------------------------------------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------------------------------------------------
def test_export_writes_a_complete_manifest_with_stable_key_order(tmp_path):
    h = Harness(tmp_path)

    result = h.export()

    text = result.manifest_path.read_text(encoding="utf-8")
    data = json.loads(text)
    assert list(data) == sorted(data)  # sorted keys at the top level
    assert list(data["tables"]) == sorted(SOURCE_TABLES)  # and for the table list
    assert data["format_version"] == 1
    assert data["name"] == NAME
    assert data["created_at"] == "2026-10-26T21:30:00+00:00"
    assert data["git_commit"] == "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
    assert data["pg_dump_version"] == "18.0"
    assert data["source"] == {
        "database": "nba_platform",
        "server_version": "18.0",
        "server_version_num": 180000,
        "timezone": "America/Mexico_City",
        "encoding": "UTF8",
        "lc_collate": "C",
    }
    assert data["alembic"] == {"database_version": HEAD, "code_head": HEAD}
    assert data["tables"] == SOURCE_TABLES
    assert data["total_rows"] == sum(SOURCE_TABLES.values())
    dump_bytes = result.dump_path.read_bytes()
    assert data["dump"] == {
        "file": f"{NAME}.dump",
        "size_bytes": len(dump_bytes),
        "sha256": hashlib.sha256(dump_bytes).hexdigest(),
    }
    assert "ñ" in text  # UTF-8, not \u escapes
    assert text.endswith("}\n")


def test_manifest_round_trips_to_identical_text(tmp_path):
    result = Harness(tmp_path).export()
    original = result.manifest_path.read_text(encoding="utf-8")

    assert Manifest.from_json(original).to_json() == original


def _manifest_dict(tmp_path) -> dict:
    return json.loads(Harness(tmp_path).export().manifest.to_json())


BAD_MANIFESTS = {
    "unsupported format": lambda d: d.update(format_version=99),
    "missing dump section": lambda d: d.pop("dump"),
    "short sha": lambda d: d["dump"].update(sha256="abc123"),
    "uppercase sha": lambda d: d["dump"].update(sha256=d["dump"]["sha256"].upper()),
    "negative size": lambda d: d["dump"].update(size_bytes=-1),
    "negative count": lambda d: d["tables"].update({"public.players": -1}),
    "fractional count": lambda d: d["tables"].update({"public.players": 1.5}),
    "boolean count": lambda d: d["tables"].update({"public.players": True}),
    "tables not an object": lambda d: d.update(tables=["public.players"]),
    "bad timestamp": lambda d: d.update(created_at="yesterday"),
    "empty name": lambda d: d.update(name=""),
    "version number as text": lambda d: d["source"].update(server_version_num="180000"),
    "missing source timezone": lambda d: d["source"].pop("timezone"),
}


@pytest.mark.parametrize("case", sorted(BAD_MANIFESTS))
def test_manifest_schema_violations_are_rejected(tmp_path, case):
    data = _manifest_dict(tmp_path)
    BAD_MANIFESTS[case](data)

    with pytest.raises(ManifestError) as excinfo:
        Manifest.from_json(json.dumps(data))

    assert excinfo.value.exit_code == 2


def test_manifest_that_is_not_json_or_not_an_object_is_rejected():
    for raw in ("{not json", "[]", "null"):
        with pytest.raises(ManifestError):
            Manifest.from_json(raw)


def test_error_classes_map_to_documented_exit_codes():
    assert PreconditionError("x").exit_code == IntegrityError("x").exit_code == ManifestError("x").exit_code == 2
    assert OperationError("x").exit_code == 1


# --------------------------------------------------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------------------------------------------------
def test_export_counts_and_dumps_inside_one_snapshot(tmp_path):
    h = Harness(tmp_path)

    h.export()

    assert h.server.events == ["snapshot-open", "pg_dump", "snapshot-close"]
    argv = h.runner.calls_of("pg_dump")[0].argv
    assert "--snapshot=00000003-0000001B-1" in argv


def test_pg_dump_command_shape_and_password_channel(tmp_path):
    h = Harness(tmp_path)

    h.export()

    call = h.runner.calls_of("pg_dump")[0]
    argv = call.argv
    assert argv[0].replace("\\", "/") == "/pg18/bin/pg_dump"
    assert {"-Fc", "--no-owner", "--no-privileges", "--no-password"} <= set(argv)
    assert argv[argv.index("--host") + 1] == "localhost"
    assert argv[argv.index("--port") + 1] == "5432"
    assert argv[argv.index("--username") + 1] == "nba"
    assert argv[argv.index("--dbname") + 1] == "nba_platform"
    assert call.env == {"PGPASSWORD": PASSWORD}
    assert argv[argv.index("--file") + 1].endswith(".dump.part")  # written aside, renamed only when complete


def test_export_is_written_atomically_and_leaves_no_partial_file(tmp_path):
    h = Harness(tmp_path)

    h.export()

    assert sorted(p.name for p in h.backups.iterdir()) == [f"{NAME}.dump", f"{NAME}.manifest.json"]


def test_export_asks_for_tools_at_least_as_new_as_the_server(tmp_path):
    h = Harness(tmp_path, server=FakeServer(version_num=170005))

    h.export()

    assert h.requested_majors == [17]


def test_export_defaults_to_the_sibling_backups_folder_and_a_timestamped_name(tmp_path):
    h = Harness(tmp_path)

    result = h.service.export_database(DbTarget.from_url(SOURCE_URL))

    assert result.dump_path.parent == (tmp_path / dt.BACKUP_DIR_NAME).resolve()  # <repo>/../ArchetypeNBA-backups
    assert re.fullmatch(r"nba_platform_\d{8}_\d{4}\.dump", result.dump_path.name)


@pytest.mark.parametrize("where", ["inside", "repo_root", "dotdot"])
def test_export_refuses_to_write_inside_the_repository(tmp_path, where):
    h = Harness(tmp_path)
    out = {
        "inside": h.repo / "backups",
        "repo_root": h.repo,
        "dotdot": h.backups / ".." / "repo" / "dumps",  # looks outside, resolves inside
    }[where]

    with pytest.raises(PreconditionError, match="inside the repository"):
        h.export(out_dir=out)

    assert h.server.connected == [] and h.runner.calls == []  # refused before touching the database
    assert not h.backups.exists() and list(h.repo.iterdir()) == []


def test_export_refuses_a_symlinked_path_into_the_repository(tmp_path):
    h = Harness(tmp_path)
    (h.repo / "data").mkdir()
    link = tmp_path / "innocent"
    link_directory(link, h.repo / "data")

    with pytest.raises(PreconditionError, match="inside the repository"):
        h.export(out_dir=link / "dumps")

    assert list((h.repo / "data").iterdir()) == []


def test_export_accepts_a_sibling_folder_that_merely_shares_the_repo_prefix(tmp_path):
    h = Harness(tmp_path)

    result = h.export(out_dir=tmp_path / "repo-backups")

    assert result.dump_path.exists()


def test_export_never_overwrites_an_existing_backup(tmp_path):
    h = Harness(tmp_path)
    h.export()

    with pytest.raises(PreconditionError, match="already exists"):
        h.export()


@pytest.mark.parametrize("name", ["../evil", "a/b", "/", ".hidden", "with space"])
def test_export_rejects_unsafe_names(tmp_path, name):
    h = Harness(tmp_path)

    with pytest.raises(PreconditionError):
        h.export(name=name)


def test_failed_pg_dump_leaves_no_files_and_scrubs_the_password(tmp_path):
    h = Harness(tmp_path)
    h.runner.dump_returncode = 1
    h.runner.dump_stderr = f"pg_dump: error: connection failed for password {PASSWORD}"

    with pytest.raises(OperationError) as excinfo:
        h.export()

    assert excinfo.value.exit_code == 1
    assert PASSWORD not in str(excinfo.value) and "pg_dump failed" in str(excinfo.value)
    assert list(h.backups.iterdir()) == []
    assert h.server.events[-1] == "snapshot-close"  # the snapshot is released even on failure


def test_unreadable_dump_is_discarded(tmp_path):
    h = Harness(tmp_path)
    h.runner.list_returncode = 1

    with pytest.raises(OperationError, match="discarded"):
        h.export()

    assert list(h.backups.iterdir()) == []


def test_export_warns_when_the_database_is_not_at_the_code_head(tmp_path):
    h = Harness(tmp_path, code_head="ffffffffffff")

    result = h.export()

    assert len(result.warnings) == 1 and "ffffffffffff" in result.warnings[0] and HEAD in result.warnings[0]
    assert result.dump_path.exists()  # a warning, not a failure


def test_export_without_warnings_when_versions_agree(tmp_path):
    assert Harness(tmp_path).export().warnings == []


# --------------------------------------------------------------------------------------------------------------------
# Verify
# --------------------------------------------------------------------------------------------------------------------
def test_verify_accepts_an_intact_dump(tmp_path, exported):
    h = Harness(tmp_path / "other", with_source=False)

    result = h.service.verify_dump(exported.dump_path)

    assert result.manifest.name == NAME and result.archive_entries == 2
    assert result.warnings == []
    assert h.runner.calls_of("pg_restore")[0].argv[-2:] == ("--list", str(exported.dump_path))
    assert h.server.connected == []  # no database needed


def test_verify_detects_a_flipped_byte(tmp_path, exported):
    data = bytearray(exported.dump_path.read_bytes())
    data[10] ^= 0x01
    exported.dump_path.write_bytes(bytes(data))

    with pytest.raises(IntegrityError, match="sha256") as excinfo:
        Harness(tmp_path / "other", with_source=False).service.verify_dump(exported.dump_path)

    assert excinfo.value.exit_code == 2
    assert exported.manifest.dump_sha256 in str(excinfo.value)


def test_verify_detects_a_truncated_copy(tmp_path, exported):
    exported.dump_path.write_bytes(exported.dump_path.read_bytes()[:-5])

    with pytest.raises(IntegrityError, match="does not match"):
        Harness(tmp_path / "other", with_source=False).service.verify_dump(exported.dump_path)


def test_verify_fails_for_a_missing_dump(tmp_path):
    with pytest.raises(PreconditionError, match="dump file not found") as excinfo:
        Harness(tmp_path, with_source=False).service.verify_dump(tmp_path / "nope.dump")

    assert excinfo.value.exit_code == 2


def test_verify_fails_for_a_missing_manifest(tmp_path, exported):
    exported.manifest_path.unlink()

    with pytest.raises(ManifestError, match="manifest not found"):
        Harness(tmp_path / "other", with_source=False).service.verify_dump(exported.dump_path)


def test_verify_fails_for_a_corrupt_manifest(tmp_path, exported):
    exported.manifest_path.write_text("{ definitely not json", encoding="utf-8")

    with pytest.raises(ManifestError, match="not valid JSON"):
        Harness(tmp_path / "other", with_source=False).service.verify_dump(exported.dump_path)


def test_verify_fails_when_pg_restore_cannot_list_the_archive(tmp_path, exported):
    h = Harness(tmp_path / "other", with_source=False)
    h.runner.list_returncode = 1

    with pytest.raises(IntegrityError, match="cannot read the archive"):
        h.service.verify_dump(exported.dump_path)


def test_verify_fails_when_the_archive_lists_nothing(tmp_path, exported):
    h = Harness(tmp_path / "other", with_source=False)
    h.runner.list_stdout = ";\n; just comments\n"

    with pytest.raises(IntegrityError, match="no entries"):
        h.service.verify_dump(exported.dump_path)


def test_verify_asks_for_tools_that_can_read_the_dump_and_fails_clearly_without_them(tmp_path, exported):
    def no_tools(required):
        raise PreconditionError(f"No usable PostgreSQL client tools found (major {required} or newer required)")

    h = Harness(tmp_path / "other", with_source=False, find_tools=no_tools)

    with pytest.raises(PreconditionError, match="major 18"):
        h.service.verify_dump(exported.dump_path)


def test_verify_warns_about_a_renamed_dump(tmp_path, exported):
    renamed = exported.dump_path.with_name("renamed.dump")
    exported.dump_path.rename(renamed)
    exported.manifest_path.rename(renamed.with_name("renamed.manifest.json"))

    result = Harness(tmp_path / "other", with_source=False).service.verify_dump(renamed)

    assert any("renamed.dump" in w for w in result.warnings)


def test_manifest_path_sits_next_to_the_dump_with_the_same_stem():
    assert dt.manifest_path_for(Path("/b/x.dump")) == Path("/b/x.manifest.json")


# --------------------------------------------------------------------------------------------------------------------
# Row-count comparison and version rules
# --------------------------------------------------------------------------------------------------------------------
def test_compare_counts_reports_match_missing_extra_and_different():
    rows = dt.compare_counts({"public.a": 1, "public.b": 2, "public.c": 3}, {"public.a": 1, "public.c": 4, "public.z": 9})
    by_table = {row.table: row for row in rows}

    assert [row.table for row in rows] == ["public.a", "public.b", "public.c", "public.z"]
    assert by_table["public.a"].ok
    assert not by_table["public.b"].ok and by_table["public.b"].actual is None  # missing from the database
    assert not by_table["public.c"].ok and (by_table["public.c"].expected, by_table["public.c"].actual) == (3, 4)
    assert not by_table["public.z"].ok and by_table["public.z"].expected is None  # not in the manifest


def test_compare_counts_of_identical_sides_is_all_ok_even_with_empty_tables():
    assert all(row.ok for row in dt.compare_counts({"public.a": 0}, {"public.a": 0}))


def test_comparison_table_lists_every_table_and_marks_mismatches():
    rows = dt.compare_counts({"public.a": 1200, "public.b": 2}, {"public.a": 1200, "public.b": 3})

    text = dt.format_comparison(rows, "rev1", "rev2")

    assert re.search(r"public\.a\s+1,200\s+1,200\s+OK", text)
    assert re.search(r"public\.b\s+2\s+3\s+MISMATCH", text)
    assert "alembic version: expected rev1, actual rev2: MISMATCH" in text


@pytest.mark.parametrize(("target", "allowed"), [(170000, False), (179999, False), (180000, True), (180003, True), (190000, True)])
def test_a_dump_restores_into_the_same_major_or_newer_only(tmp_path, exported, target, allowed):
    h = importer(tmp_path, version_num=target)

    if allowed:
        assert do_import(h, exported, create_db=True).ok
    else:
        with pytest.raises(PreconditionError, match="Install PostgreSQL 18") as excinfo:
            do_import(h, exported, create_db=True)
        assert excinfo.value.exit_code == 2
        assert h.server.events == []  # refused before creating or restoring anything


def test_check_target_version_message_names_both_versions(exported):
    with pytest.raises(PreconditionError) as excinfo:
        dt.check_target_version(exported.manifest, 16, "16.4")

    assert "16.4" in str(excinfo.value) and "18.0" in str(excinfo.value)


# --------------------------------------------------------------------------------------------------------------------
# Import
# --------------------------------------------------------------------------------------------------------------------
def test_import_creates_the_database_restores_analyzes_and_matches_every_table(tmp_path, exported):
    h = importer(tmp_path)

    result = do_import(h, exported, create_db=True)

    assert result.ok and result.created_database
    assert [row.table for row in result.rows] == sorted(SOURCE_TABLES)
    assert result.alembic_expected == result.alembic_actual == HEAD
    assert h.server.events == ["create:nba_platform:UTF8", "pg_restore", "analyze:nba_platform"]


def test_import_into_an_existing_empty_database_does_not_create_anything(tmp_path, exported):
    h = importer(tmp_path, existing={})

    result = do_import(h, exported)

    assert result.ok and not result.created_database
    assert h.server.events == ["pg_restore", "analyze:nba_platform"]


def test_pg_restore_command_is_a_single_guarded_transaction(tmp_path, exported):
    h = importer(tmp_path, existing={})

    do_import(h, exported)

    call = h.runner.calls_of("pg_restore")[-1]
    argv = call.argv
    assert {"--no-owner", "--no-privileges", "--exit-on-error", "--single-transaction", "--no-password"} <= set(argv)
    assert argv[argv.index("--dbname") + 1] == "nba_platform"
    assert argv[-1] == str(exported.dump_path)
    assert call.env == {"PGPASSWORD": PASSWORD}


def test_import_refuses_a_missing_database_without_create_db(tmp_path, exported):
    h = importer(tmp_path)

    with pytest.raises(PreconditionError, match="--create-db") as excinfo:
        do_import(h, exported)

    assert excinfo.value.exit_code == 2
    assert h.server.events == []


def test_import_reports_an_unreachable_maintenance_database_when_it_must_create(tmp_path, exported):
    h = importer(tmp_path)
    h.server.no_maintenance = True

    with pytest.raises(PreconditionError, match="connecting"):
        do_import(h, exported, create_db=True)

    assert h.server.events == []


def test_import_refuses_a_non_empty_target_without_replace(tmp_path, exported):
    h = importer(tmp_path, existing={"public.players": 5, "public.games": 7})

    with pytest.raises(PreconditionError, match="not empty") as excinfo:
        do_import(h, exported)

    assert "public.games" in str(excinfo.value) and "--replace" in str(excinfo.value)
    assert h.server.events == []  # no wipe, no restore


def test_create_db_does_not_bypass_the_non_empty_check(tmp_path, exported):
    h = importer(tmp_path, existing={"public.players": 5})

    with pytest.raises(PreconditionError, match="not empty"):
        do_import(h, exported, create_db=True)

    assert h.server.events == []


@pytest.mark.parametrize("confirm", [None, "", "nba_platfor", "NBA_PLATFORM", "other_db"])
def test_replace_needs_the_exact_database_name_as_confirmation(tmp_path, exported, confirm):
    h = importer(tmp_path, existing={"public.players": 5})

    with pytest.raises(PreconditionError, match="--confirm-database nba_platform"):
        do_import(h, exported, replace=True, confirm_database=confirm)

    assert h.server.events == [] and h.runner.calls == []  # not even the integrity check ran
    assert h.server.databases["nba_platform"].tables == {"public.players": 5}


def test_confirm_database_without_replace_is_a_usage_error(tmp_path, exported):
    h = importer(tmp_path, existing={})

    with pytest.raises(PreconditionError, match="--replace"):
        do_import(h, exported, confirm_database="nba_platform")


def test_replace_with_the_exact_confirmation_wipes_then_restores(tmp_path, exported):
    h = importer(tmp_path, existing={"public.players": 5, "public.leftover": 1})

    result = do_import(h, exported, replace=True, confirm_database="nba_platform")

    assert result.ok
    assert h.server.events == ["reset:nba_platform", "pg_restore", "analyze:nba_platform"]
    assert "public.leftover" not in h.server.databases["nba_platform"].tables


def test_import_verifies_the_dump_before_touching_anything(tmp_path, exported):
    data = bytearray(exported.dump_path.read_bytes())
    data[0] ^= 0xFF
    exported.dump_path.write_bytes(bytes(data))
    h = importer(tmp_path)

    with pytest.raises(IntegrityError):
        do_import(h, exported, create_db=True)

    assert h.server.events == [] and h.server.connected == []
    assert h.runner.calls_of("pg_restore") == []


def test_import_reports_a_row_count_mismatch_instead_of_trusting_the_restore(tmp_path, exported):
    h = importer(tmp_path, existing={})
    h.runner.restore_tables = {**SOURCE_TABLES, "public.game_log": 1199}

    result = do_import(h, exported)

    assert not result.ok
    assert [(r.table, r.expected, r.actual) for r in result.mismatches] == [("public.game_log", 1200, 1199)]


def test_import_reports_missing_and_extra_tables(tmp_path, exported):
    h = importer(tmp_path, existing={})
    h.runner.restore_tables = {"public.alembic_version": 1, "public.game_log": 1200, "public.surprise": 3}

    result = do_import(h, exported)

    bad = {r.table: (r.expected, r.actual) for r in result.mismatches}
    assert bad == {"public.jugadores_ñ": (450, None), "public.players": (0, None), "public.surprise": (None, 3)}


def test_import_reports_an_alembic_revision_mismatch(tmp_path, exported):
    h = importer(tmp_path, existing={})
    h.runner.restore_alembic = "000000000000"

    result = do_import(h, exported)

    assert not result.ok and all(row.ok for row in result.rows)


def test_a_failed_restore_is_an_operation_error_that_says_what_state_the_database_is_in(tmp_path, exported):
    h = importer(tmp_path)
    h.runner.restore_returncode = 1
    h.runner.restore_stderr = f"pg_restore: error: could not execute query for {PASSWORD}"

    with pytest.raises(OperationError, match="rolled back") as excinfo:
        do_import(h, exported, create_db=True)

    assert excinfo.value.exit_code == 1
    assert "exists but is empty" in str(excinfo.value)
    assert PASSWORD not in str(excinfo.value)
    assert "analyze:nba_platform" not in h.server.events


def test_a_failed_restore_after_replace_says_the_database_is_now_empty(tmp_path, exported):
    h = importer(tmp_path, existing={"public.players": 5})
    h.runner.restore_returncode = 1

    with pytest.raises(OperationError, match="now empty"):
        do_import(h, exported, replace=True, confirm_database="nba_platform")


def test_skip_analyze_leaves_statistics_alone(tmp_path, exported):
    h = importer(tmp_path, existing={})

    do_import(h, exported, skip_analyze=True)

    assert not any(event.startswith("analyze") for event in h.server.events)


def test_a_failing_analyze_is_only_a_warning(tmp_path, exported):
    h = importer(tmp_path, existing={})
    h.server.analyze_fails = True

    result = do_import(h, exported)

    assert result.ok and any("ANALYZE failed" in w for w in result.warnings)


def test_import_warns_when_the_target_timezone_or_checkout_differs(tmp_path, exported):
    h = importer(tmp_path, existing={}, code_head="aaaaaaaaaaaa")
    h.server.info = ServerInfo("18.0", 180000, "UTC", "UTF8", "C")

    result = do_import(h, exported)

    assert result.ok
    assert any("timezone" in w and "UTC" in w and "America/Mexico_City" in w for w in result.warnings)
    assert any("aaaaaaaaaaaa" in w and HEAD in w for w in result.warnings)


def test_import_uses_tools_at_least_as_new_as_the_target_server(tmp_path, exported):
    requested: List[Optional[int]] = []

    def find_tools(required):
        requested.append(required)
        return make_tools(max(required or 0, 18))

    h = importer(tmp_path, version_num=190000, existing={}, find_tools=find_tools)

    do_import(h, exported)

    assert requested == [18, 19]  # 18 to read the dump, then 19 for the newer server
    assert h.runner.calls_of("pg_restore")[-1].argv[0].replace("\\", "/") == "/pg19/bin/pg_restore"


# --------------------------------------------------------------------------------------------------------------------
# Secrets
# --------------------------------------------------------------------------------------------------------------------
def test_the_password_appears_only_in_the_subprocess_environment(tmp_path):
    source = Harness(tmp_path / "src")
    result = source.export()
    target = importer(tmp_path)
    do_import(target, result, create_db=True)
    needles = {PASSWORD, quote(PASSWORD, safe=""), SOURCE_URL}

    for harness in (source, target):
        for call in harness.runner.calls:
            assert not any(needle in arg for arg in call.argv for needle in needles), call.argv
            assert call.env in ({}, {"PGPASSWORD": PASSWORD}), call.env
        assert not any(needle in line for line in harness.logs for needle in needles)
    assert not any(PASSWORD in line for line in source.logs + target.logs)
    assert PASSWORD not in result.manifest_path.read_text(encoding="utf-8")
    assert "nba:***@localhost" in "\n".join(source.logs)  # the URL echo is masked


# --------------------------------------------------------------------------------------------------------------------
# Binary discovery
# --------------------------------------------------------------------------------------------------------------------
class Tree:
    """A fake set of PostgreSQL installs: <root>/<label>/bin holding pg_dump/pg_restore reporting a version."""

    def __init__(self, root: Path):
        self.root = root
        self.runner = FakeRunner(FakeServer())

    def install(self, label: str, version: str, *, restore: bool = True, suffix: str = ".exe") -> Path:
        bin_dir = self.root / label / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / f"pg_dump{suffix}").write_bytes(b"")
        if restore:
            (bin_dir / f"pg_restore{suffix}").write_bytes(b"")
        self.runner.bin_versions[str(bin_dir)] = version
        return bin_dir

    @property
    def pattern(self) -> str:
        return str(self.root / "*" / "bin")

    def discover(self, **kwargs):
        import glob

        kwargs.setdefault("which", lambda name: None)
        kwargs.setdefault("search_patterns", [self.pattern])
        return dt.discover_pg_tools(self.runner, glob_fn=glob.glob, **kwargs)


def test_discovery_picks_the_highest_major_when_nothing_is_required(tmp_path):
    tree = Tree(tmp_path)
    tree.install("16", "16.4")
    tree.install("18", "18.1")
    tree.install("17", "17.2")

    tools = tree.discover()

    assert tools.major == 18 and tools.bin_dir == tmp_path / "18" / "bin"
    assert tools.pg_dump.name == "pg_dump.exe" and tools.pg_restore.name == "pg_restore.exe"
    assert tools.version_text == "18.1"


def test_discovery_skips_installs_older_than_the_server(tmp_path):
    tree = Tree(tmp_path)
    tree.install("15", "15.8")
    tree.install("17", "17.2")

    assert tree.discover(required_major=17).major == 17


def test_discovery_prefers_path_over_a_location_scan_on_equal_majors(tmp_path):
    tree = Tree(tmp_path / "scan")
    tree.install("18", "18.0")
    on_path = Tree(tmp_path / "onpath")
    path_dir = on_path.install("custom", "18.2", suffix="")
    tree.runner.bin_versions.update(on_path.runner.bin_versions)

    tools = tree.discover(required_major=18, which=lambda name: str(path_dir / "pg_dump"))

    assert tools.bin_dir == path_dir and tools.version_text == "18.2"


def test_discovery_still_takes_a_newer_scanned_install_over_an_older_path_one(tmp_path):
    tree = Tree(tmp_path / "scan")
    tree.install("19", "19.0")
    on_path = Tree(tmp_path / "onpath")
    path_dir = on_path.install("old", "17.4", suffix="")
    tree.runner.bin_versions.update(on_path.runner.bin_versions)

    tools = tree.discover(required_major=17, which=lambda name: str(path_dir / "pg_dump"))

    assert tools.major == 19


def test_explicit_pg_bin_wins_over_path_and_scans(tmp_path):
    tree = Tree(tmp_path)
    explicit = tree.install("17", "17.2")
    tree.install("19", "19.0")

    tools = tree.discover(pg_bin=explicit, which=lambda name: str(tmp_path / "19" / "bin" / "pg_dump.exe"))

    assert tools.bin_dir == explicit and tools.major == 17


def test_explicit_pg_bin_must_be_new_enough_and_complete(tmp_path):
    tree = Tree(tmp_path)
    old = tree.install("16", "16.4")
    broken = tree.install("broken", "18.0", restore=False)

    with pytest.raises(PreconditionError, match="major 18 or newer is required"):
        tree.discover(pg_bin=old, required_major=18)
    with pytest.raises(PreconditionError, match="does not contain"):
        tree.discover(pg_bin=broken)
    with pytest.raises(PreconditionError, match="does not contain"):
        tree.discover(pg_bin=tmp_path / "does-not-exist")


def test_discovery_ignores_folders_without_both_tools_and_deduplicates(tmp_path):
    tree = Tree(tmp_path)
    tree.install("18", "18.0", restore=False)  # pg_dump only
    good = tree.install("17", "17.2")

    tools = tree.discover(search_patterns=[tree.pattern, tree.pattern])

    assert tools.bin_dir == good


def test_discovery_error_lists_what_was_found_and_how_to_install(tmp_path):
    tree = Tree(tmp_path)
    tree.install("15", "15.8")

    with pytest.raises(PreconditionError) as excinfo:
        tree.discover(required_major=18)

    message = str(excinfo.value)
    assert excinfo.value.exit_code == 2
    assert "major 18 or newer" in message and "(PostgreSQL 15)" in message
    assert "postgresql-client-18" in message and "brew install postgresql@18" in message and "--pg-bin" in message


def test_discovery_error_when_nothing_is_installed(tmp_path):
    with pytest.raises(PreconditionError, match="Found: none"):
        Tree(tmp_path).discover(required_major=18)


def test_default_search_patterns_cover_windows_homebrew_and_debian():
    patterns = dt.default_search_patterns({"ProgramFiles": r"D:\Programs"})

    assert os_join(r"D:\Programs", "PostgreSQL", "*", "bin") in patterns
    assert "/opt/homebrew/opt/postgresql@*/bin" in patterns
    assert "/usr/local/opt/postgresql@*/bin" in patterns
    assert "/usr/lib/postgresql/*/bin" in patterns


def os_join(*parts: str) -> str:
    return os.path.join(*parts)


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("pg_dump (PostgreSQL) 18.0\n", ("18.0", 18)),
        ("pg_restore (PostgreSQL) 17devel", ("17", 17)),
        ("pg_dump (PostgreSQL) 18beta1", ("18", 18)),
        ("pg_dump (PostgreSQL) 16.4 (Debian 16.4-1.pgdg120+1)", ("16.4", 16)),
        ("pg_dump (PostgreSQL) 9.6.24", ("9.6.24", 9)),
        ("no version here", None),
    ],
)
def test_parse_pg_version(output, expected):
    assert dt.parse_pg_version(output) == expected


# --------------------------------------------------------------------------------------------------------------------
# Environment probes
# --------------------------------------------------------------------------------------------------------------------
def test_code_head_matches_a_real_migration_revision():
    head = dt.get_code_head()

    assert head and "," not in head  # one head
    versions = dt.BACKEND_DIR / "alembic" / "versions"
    declared = [
        re.search(r"^revision(?::\s*str)?\s*=\s*['\"]([^'\"]+)['\"]", path.read_text(encoding="utf-8"), re.MULTILINE)
        for path in versions.glob("*.py")
    ]
    assert head in {match.group(1) for match in declared if match}


def test_code_head_is_none_when_the_script_directory_is_unreadable(tmp_path):
    assert dt.get_code_head(tmp_path) is None


def test_default_dump_name_pattern():
    assert re.fullmatch(r"nba_platform_\d{8}_\d{4}", dt.default_dump_name(NOW))


# --------------------------------------------------------------------------------------------------------------------
# CLI (scripts/db_transfer.py)
# --------------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def cli():
    path = Path(__file__).resolve().parents[1] / "scripts" / "db_transfer.py"
    spec = importlib.util.spec_from_file_location("db_transfer_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_help_lists_every_subcommand(cli, capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--help"])

    out = capsys.readouterr().out
    assert excinfo.value.code == 0
    assert all(word in out for word in ("export", "verify", "import", "manifest"))


@pytest.mark.parametrize("command", ["export", "verify", "import", "manifest"])
def test_cli_subcommand_help(cli, capsys, command):
    with pytest.raises(SystemExit) as excinfo:
        cli.main([command, "--help"])

    assert excinfo.value.code == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_cli_verify_of_a_missing_dump_exits_2_without_a_traceback(cli, tmp_path, capsys):
    code = cli.main(["verify", str(tmp_path / "missing.dump")])

    captured = capsys.readouterr()
    assert code == 2
    assert "dump file not found" in captured.err and "Traceback" not in captured.err + captured.out


def test_cli_manifest_prints_the_manifest_from_the_dump_or_the_manifest_path(cli, exported, capsys):
    for path in (exported.dump_path, exported.manifest_path):
        assert cli.main(["manifest", str(path)]) == 0
        assert json.loads(capsys.readouterr().out)["name"] == NAME


def test_cli_manifest_of_garbage_exits_2(cli, tmp_path, capsys):
    bad = tmp_path / "x.manifest.json"
    bad.write_text("nope", encoding="utf-8")

    assert cli.main(["manifest", str(bad)]) == 2
    assert "ERROR:" in capsys.readouterr().err


def test_cli_export_prints_the_summary_and_exits_0(cli, tmp_path, capsys):
    h = Harness(tmp_path)

    code = cli.main(["export", "--database-url", SOURCE_URL, "--out-dir", str(h.backups), "--name", NAME], lambda pg_bin: h.service)

    out = capsys.readouterr().out
    assert code == 0
    assert NAME in out and "sha256" in out and "4 tables" in out and PASSWORD not in out


def test_cli_export_inside_the_repo_exits_2(cli, tmp_path, capsys):
    h = Harness(tmp_path)

    code = cli.main(["export", "--database-url", SOURCE_URL, "--out-dir", str(h.repo / "x")], lambda pg_bin: h.service)

    assert code == 2 and "inside the repository" in capsys.readouterr().err


def test_cli_import_exit_codes(cli, tmp_path, exported, capsys):
    base = ["import", "--dump", str(exported.dump_path), "--target-url", target_url()]

    ok = importer(tmp_path / "ok", existing={})
    assert cli.main(base, lambda pg_bin: ok.service) == 0
    out = capsys.readouterr().out
    assert "RESULT: OK" in out and "public.game_log" in out and PASSWORD not in out

    mismatch = importer(tmp_path / "mismatch", existing={})
    mismatch.runner.restore_tables = {**SOURCE_TABLES, "public.players": 1}
    assert cli.main(base, lambda pg_bin: mismatch.service) == 1
    out = capsys.readouterr().out
    assert "MISMATCH" in out and "RESULT: MISMATCH" in out

    restore_error = importer(tmp_path / "failure", existing={})
    restore_error.runner.restore_returncode = 1
    assert cli.main(base, lambda pg_bin: restore_error.service) == 1
    assert "pg_restore failed" in capsys.readouterr().err

    not_empty = importer(tmp_path / "busy", existing={"public.players": 1})
    assert cli.main(base, lambda pg_bin: not_empty.service) == 2
    assert "not empty" in capsys.readouterr().err

    older = importer(tmp_path / "older", version_num=160000, existing={})
    assert cli.main(base, lambda pg_bin: older.service) == 2
    assert "Install PostgreSQL 18" in capsys.readouterr().err


def test_cli_import_replace_requires_the_confirmation(cli, tmp_path, exported, capsys):
    h = importer(tmp_path, existing={"public.players": 5})
    base = ["import", "--dump", str(exported.dump_path), "--target-url", target_url(), "--replace"]

    assert cli.main(base, lambda pg_bin: h.service) == 2
    assert "--confirm-database nba_platform" in capsys.readouterr().err
    assert cli.main(base + ["--confirm-database", "nba_platform"], lambda pg_bin: h.service) == 0
    assert "reset:nba_platform" in h.server.events


def test_cli_verify_of_an_intact_dump_exits_0(cli, tmp_path, exported, capsys):
    h = Harness(tmp_path / "other", with_source=False)

    assert cli.main(["verify", str(exported.dump_path)], lambda pg_bin: h.service) == 0
    assert "VERIFIED" in capsys.readouterr().out


def test_cli_verify_of_a_corrupt_dump_exits_2(cli, tmp_path, exported, capsys):
    exported.dump_path.write_bytes(b"corrupt")
    h = Harness(tmp_path / "other", with_source=False)

    assert cli.main(["verify", str(exported.dump_path)], lambda pg_bin: h.service) == 2
    assert "integrity check failed" in capsys.readouterr().err
