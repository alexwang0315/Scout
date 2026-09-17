from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

import pytest

from scout.nextgen.dashboard_telemetry import SQLiteBackgroundIntelligenceTelemetryReader
from tests.qualification.effects import EffectAudit
from tests.qualification.sqlite_fixtures import ReadOnlySqliteFixture


def _fixture(tmp_path: Path):
    root = tmp_path / "execution"
    root.mkdir()
    path = root / "fixture.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE records(value INTEGER)")
        connection.execute("INSERT INTO records VALUES (7)")
    return root, path, ReadOnlySqliteFixture.seal(path, execution_root=root)


def _audit(root: Path, fixture: ReadOnlySqliteFixture):
    return EffectAudit(
        transition_id="fixture-read-negative",
        roots=(("execution", root),),
        readonly_sqlite_fixtures=(fixture,),
    )


def test_exact_fixture_uses_actual_production_native_connection_and_query_only(tmp_path: Path) -> None:
    root, path, fixture = _fixture(tmp_path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with _audit(root, fixture) as audit:
        with closing(SQLiteBackgroundIntelligenceTelemetryReader(path)._connect()) as connection:
            assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
            assert connection.execute("SELECT value FROM records").fetchone()[0] == 7
            with pytest.raises(sqlite3.DatabaseError):
                connection.execute("UPDATE records SET value=999")
            with pytest.raises(sqlite3.DatabaseError):
                connection.execute("ATTACH DATABASE ':memory:' AS escaped")
            with pytest.raises(sqlite3.DatabaseError):
                connection.execute("PRAGMA query_only=OFF")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert any(item.operation == "database.connect.readonly" and item.outcome == "completed" for item in audit.attempts)
    assert any(item.operation == "database.query_only_observed" and item.outcome == "passed" for item in audit.attempts)
    assert all(item.scope == "execution" for item in audit.attempts)


@pytest.mark.parametrize("query", ("", "?mode=rw", "?mode=rwc", "?mode=memory", "?mode=ro&immutable=1", "?mode=ro&vfs=unix", "?mode=ro&mode=ro", "?%6dode=ro", "?mode=%72o"))
def test_fixture_rejects_every_undeclared_uri_mode_before_native_connect(tmp_path: Path, query: str) -> None:
    root, path, fixture = _fixture(tmp_path)
    with _audit(root, fixture) as audit:
        with pytest.raises(PermissionError, match="external_store_database"):
            sqlite3.connect("file:" + quote(str(path)) + query, uri=True)
    assert any(item.effect_class == "external_store_database" and item.outcome == "blocked_before_invocation" for item in audit.attempts)
    assert not any(item.operation == "database.connect.readonly" for item in audit.attempts)


@pytest.mark.parametrize("case", ("outside", "memory", "authority", "symlink", "no-uri-flag"))
def test_fixture_rejects_unbound_paths_and_connection_forms(tmp_path: Path, case: str) -> None:
    root, path, fixture = _fixture(tmp_path)
    if case == "symlink":
        link = root / "alias.sqlite3"
        link.symlink_to(path)
        request = "file:" + quote(str(link)) + "?mode=ro"
    elif case == "outside":
        request = "file:" + quote(str(tmp_path / "outside.sqlite3")) + "?mode=ro"
    elif case == "memory":
        request = ":memory:"
    elif case == "authority":
        request = "file://remote" + str(path) + "?mode=ro"
    else:
        request = "file:" + quote(str(path)) + "?mode=ro"
    with _audit(root, fixture):
        with pytest.raises(PermissionError):
            sqlite3.connect(request, uri=case != "no-uri-flag")
    assert not (tmp_path / "outside.sqlite3").exists()


@pytest.mark.parametrize("mutation", ("bytes", "inode"))
def test_fixture_rejects_a_changed_seal_before_native_connect(tmp_path: Path, mutation: str) -> None:
    root, path, fixture = _fixture(tmp_path)
    if mutation == "bytes":
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("INSERT INTO records VALUES (8)")
    else:
        replacement = root / "replacement.sqlite3"
        replacement.write_bytes(path.read_bytes())
        replacement.replace(path)
    with _audit(root, fixture) as audit:
        with pytest.raises(PermissionError):
            SQLiteBackgroundIntelligenceTelemetryReader(path)._connect()
    assert not any(item.operation == "database.connect.readonly" for item in audit.attempts)


def test_fixture_requires_the_real_reader_to_set_query_only(tmp_path: Path) -> None:
    root, path, fixture = _fixture(tmp_path)
    with _audit(root, fixture):
        with pytest.raises(PermissionError, match="did not enable query_only"):
            with closing(sqlite3.connect("file:" + quote(str(path)) + "?mode=ro", uri=True)):
                pass


def test_fixture_seal_rejects_a_symlinked_ancestor(tmp_path: Path) -> None:
    root, path, _fixture_record = _fixture(tmp_path)
    link = tmp_path / "alias-root"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(PermissionError, match="symlink"):
        ReadOnlySqliteFixture.seal(link / path.name, execution_root=link)


def test_real_wal_commit_is_visible_with_writer_still_open(tmp_path: Path) -> None:
    root = tmp_path / "execution"
    root.mkdir()
    path = root / "wal.sqlite3"
    with closing(sqlite3.connect(path)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE records(value INTEGER)")
        writer.commit()
        before_main = hashlib.sha256(path.read_bytes()).hexdigest()
        for expected_count in (0, 1):
            if expected_count:
                writer.execute("INSERT INTO records VALUES (9)")
                writer.commit()
            fixture = ReadOnlySqliteFixture.seal(path, execution_root=root)
            assert fixture.wal_identity is not None
            with _audit(root, fixture):
                with closing(SQLiteBackgroundIntelligenceTelemetryReader(path)._connect()) as reader:
                    assert reader.execute("SELECT COUNT(*) FROM records").fetchone()[0] == expected_count
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before_main


def test_empty_wal_coordination_requires_explicit_fixture_contract(tmp_path: Path) -> None:
    root = tmp_path / "execution"
    root.mkdir()
    path = root / "fixture.sqlite3"
    with closing(sqlite3.connect(path)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE records(value INTEGER)")
        writer.commit()
    assert not Path(str(path) + "-wal").exists()
    fixture = ReadOnlySqliteFixture.seal(
        path, execution_root=root, allow_empty_wal_coordination=True
    )
    with _audit(root, fixture) as audit:
        with closing(SQLiteBackgroundIntelligenceTelemetryReader(path)._connect()) as reader:
            assert reader.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 0
    assert any(item.operation == "database.sqlite_coordination-wal" for item in audit.attempts)


def test_new_nonempty_wal_is_rejected_even_when_empty_coordination_is_declared(tmp_path: Path) -> None:
    root, path, sealed = _fixture(tmp_path)
    fixture = ReadOnlySqliteFixture.seal(
        path, execution_root=root, allow_empty_wal_coordination=True
    )
    Path(str(path) + "-wal").write_bytes(b"undeclared WAL content")
    with _audit(root, fixture) as audit:
        with pytest.raises(PermissionError):
            SQLiteBackgroundIntelligenceTelemetryReader(path)._connect()
    assert not any(item.operation == "database.connect.readonly" for item in audit.attempts)


def test_fixture_rejects_a_hardlinked_database(tmp_path: Path) -> None:
    import os
    root, path, fixture = _fixture(tmp_path)
    os.link(path, root / "other.sqlite3")
    with _audit(root, fixture):
        with pytest.raises(PermissionError):
            SQLiteBackgroundIntelligenceTelemetryReader(path)._connect()


@pytest.mark.parametrize("case", ("encoded-path", "malformed-utf8", "lexical-parent"))
def test_fixture_rejects_noncanonical_uri_before_native_connect(tmp_path: Path, case: str) -> None:
    root, path, fixture = _fixture(tmp_path)
    canonical = "file:" + quote(str(path), safe="/") + "?mode=ro"
    if case == "encoded-path":
        request = canonical.replace("fixture.sqlite3", "%66ixture.sqlite3")
    elif case == "malformed-utf8":
        request = canonical.replace("fixture.sqlite3", "%ffixture.sqlite3")
    else:
        request = "file:" + quote(str(root / ".." / root.name / path.name), safe="/") + "?mode=ro"
    with _audit(root, fixture) as audit:
        with pytest.raises(PermissionError, match="external_store_database"):
            sqlite3.connect(request, uri=True)
    assert not any(item.operation == "database.connect.readonly" for item in audit.attempts)
    assert audit.attempts[-1].outcome == "blocked_before_invocation"


@pytest.mark.parametrize("case", ("path", "root", "outside"))
def test_fixture_seal_rejects_noncanonical_or_outside_root(tmp_path: Path, case: str) -> None:
    root, path, fixture = _fixture(tmp_path)
    if case == "path":
        candidate, execution_root = root / ".." / root.name / path.name, root
    elif case == "root":
        candidate, execution_root = path, root / ".." / root.name
    else:
        candidate, execution_root = path, root / "unrelated"
        execution_root.mkdir()
    with pytest.raises(PermissionError):
        ReadOnlySqliteFixture.seal(candidate, execution_root=execution_root)


def test_duplicate_fixture_capabilities_are_rejected(tmp_path: Path) -> None:
    root, path, fixture = _fixture(tmp_path)
    with pytest.raises(ValueError, match="duplicate SQLite fixture capabilities"):
        EffectAudit(
            transition_id="duplicate-declaration",
            roots=(("execution", root),),
            readonly_sqlite_fixtures=(fixture, fixture),
        )
