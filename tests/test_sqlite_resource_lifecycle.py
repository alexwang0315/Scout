from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

import pytest

import scout_agent_kb as kb
from scout.nextgen.background_job_store import SQLiteBackgroundIntelligenceJobStore
from scout.nextgen.dashboard_telemetry import SQLiteBackgroundIntelligenceTelemetryReader


PROJECT_ROOT = (
    Path(__file__).resolve().parents[1]
    / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)


@pytest.fixture
def observed_connections(monkeypatch):
    """Keep native connections observable without relying on GC timing."""
    connect = sqlite3.connect
    connections = []
    events = []

    class Connection(sqlite3.Connection):
        def close(self):
            events.append((self, "close", self.in_transaction))
            super().close()

        def __exit__(self, error_type, error, traceback):
            result = super().__exit__(error_type, error, traceback)
            events.append((self, "transaction_exit", error_type, self.in_transaction))
            return result

    def observe(*args, **kwargs):
        kwargs["factory"] = Connection
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", observe)
    yield connections, events
    # Release an old-version failure's handle as test cleanup, after assertions.
    for connection in connections:
        try:
            connection.in_transaction
        except sqlite3.ProgrammingError:
            pass
        else:
            connection.close()


def assert_closed(connection):
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")


def test_kb_writer_closes_before_atomic_publication_and_can_reopen(
    tmp_path, observed_connections, monkeypatch
):
    connections, events = observed_connections
    destination = tmp_path / "index.sqlite3"
    replace = Path.replace

    def publish(path, target):
        if path == destination.with_name(destination.name + ".tmp"):
            assert len(connections) == 1
            assert_closed(connections[0])
            assert events[-1][1] == "close"
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", publish)
    index = kb.write_local_evidence_sqlite_index(PROJECT_ROOT, destination)
    result = kb.query_local_evidence_sqlite_index(destination, query="黑水塘", limit=3)
    assert result.result_count > 0
    assert result.index_record_count == index.record_count
    assert result.boundary.runtime_safety_truth is False
    assert len(connections) == 2
    assert all(any(e[0] is connection and e[1] == "close" for e in events)
               for connection in connections)
    for connection in connections:
        assert_closed(connection)


def test_kb_writer_rolls_back_closes_and_preserves_previous_index(
    tmp_path, observed_connections, monkeypatch
):
    connections, events = observed_connections
    destination = tmp_path / "index.sqlite3"
    kb.write_local_evidence_sqlite_index(PROJECT_ROOT, destination)
    previous = destination.read_bytes()

    def fail_during_write(connection, index):
        assert connection.in_transaction
        connection.execute(
            "INSERT INTO metadata (key, value) VALUES (?, ?)", ("fault", "uncommitted")
        )
        raise sqlite3.DatabaseError("injected index write failure")

    monkeypatch.setattr(kb, "_write_sqlite_records", fail_during_write)
    with pytest.raises(sqlite3.DatabaseError, match="injected index write failure"):
        kb.write_local_evidence_sqlite_index(PROJECT_ROOT, destination)

    failed_connection = connections[-1]
    assert_closed(failed_connection)
    assert (failed_connection, "transaction_exit", sqlite3.DatabaseError, False) in events
    assert destination.read_bytes() == previous
    assert not destination.with_name(destination.name + ".tmp").exists()
    result = kb.query_local_evidence_sqlite_index(destination, query="黑水塘")
    assert result.result_count > 0
    assert_closed(connections[-1])


@pytest.mark.parametrize("query,limit", [("黑水塘", 8), ("黑水塘", 0), ("!!!", 8), ("absent-needle-6ea08e", 8)])
def test_kb_query_closes_on_results_and_empty_branches(
    tmp_path, observed_connections, query, limit
):
    connections, _ = observed_connections
    destination = tmp_path / "index.sqlite3"
    kb.write_local_evidence_sqlite_index(PROJECT_ROOT, destination)
    before = destination.read_bytes()
    result = kb.query_local_evidence_sqlite_index(destination, query=query, limit=limit)
    assert result.retrieval_engine == "sqlite_fts5_bm25"
    assert_closed(connections[-1])
    assert destination.read_bytes() == before


@pytest.mark.parametrize("fault", ["missing_schema", "invalid_metadata"])
def test_kb_query_closes_on_sql_and_metadata_errors(
    tmp_path, observed_connections, fault
):
    connections, _ = observed_connections
    destination = tmp_path / "index.sqlite3"
    if fault == "missing_schema":
        with closing(sqlite3.connect(destination)):
            pass
        error = sqlite3.OperationalError
    else:
        kb.write_local_evidence_sqlite_index(PROJECT_ROOT, destination)
        with closing(sqlite3.connect(destination)) as connection, connection:
            connection.execute("UPDATE metadata SET value = ? WHERE key = ?", ("invalid", "record_count"))
        error = ValueError

    with pytest.raises(error):
        kb.query_local_evidence_sqlite_index(destination, query="黑水塘")

    assert_closed(connections[-1])


def test_kb_blank_query_does_not_open_a_connection(tmp_path, observed_connections):
    connections, _ = observed_connections
    with pytest.raises(ValueError, match="must not be blank"):
        kb.query_local_evidence_sqlite_index(tmp_path / "unused.sqlite3", query=" ")
    assert connections == []
    assert not (tmp_path / "unused.sqlite3").exists()


@pytest.mark.parametrize("fault", [None, "schema", "typed_projection", "sql"])
def test_telemetry_closes_on_ready_and_degraded_projection(
    tmp_path, observed_connections, monkeypatch, fault
):
    connections, _ = observed_connections
    destination = tmp_path / "jobs.sqlite3"
    with SQLiteBackgroundIntelligenceJobStore(destination):
        pass
    reader = SQLiteBackgroundIntelligenceTelemetryReader(destination)
    if fault:
        def fail_validation(connection):
            if fault == "sql":
                raise sqlite3.DatabaseError("injected read error")
            if fault == "schema":
                raise ValueError("schema incomplete")
            raise TypeError("invalid projection")
        monkeypatch.setattr(reader, "_validate_schema", fail_validation)

    before = destination.read_bytes()
    result = reader.snapshot()
    assert result.status == ("ready" if fault is None else "degraded")
    assert result.read_only is True
    assert result.candidate_only is True
    assert result.runtime_safety_truth is False
    assert_closed(connections[-1])
    assert destination.read_bytes() == before


def test_telemetry_enforces_read_only_and_releases_setup_failure(tmp_path, monkeypatch):
    destination = tmp_path / "jobs.sqlite3"
    with SQLiteBackgroundIntelligenceJobStore(destination):
        pass
    connect = sqlite3.connect
    connections = []
    class BrokenSetupConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql == "PRAGMA query_only=ON":
                raise sqlite3.DatabaseError("injected query-only setup failure")
            return super().execute(sql, *args, **kwargs)

    def observe(*args, **kwargs):
        assert args[0].endswith("?mode=ro")
        assert kwargs["uri"] is True
        kwargs["factory"] = BrokenSetupConnection
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection
    monkeypatch.setattr(sqlite3, "connect", observe)
    try:
        result = SQLiteBackgroundIntelligenceTelemetryReader(destination).snapshot()
        assert result.status == "degraded"
        assert result.status_reason == "store_unreadable"
        assert len(connections) == 1
        assert_closed(connections[0])
    finally:
        for connection in connections:
            connection.close()


def test_telemetry_live_connection_rejects_writes(tmp_path):
    destination = tmp_path / "jobs.sqlite3"
    with SQLiteBackgroundIntelligenceJobStore(destination):
        pass
    reader = SQLiteBackgroundIntelligenceTelemetryReader(destination)
    with closing(reader._connect()) as connection:
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("CREATE TABLE forbidden_write (value TEXT)")
