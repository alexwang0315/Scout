from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scout.api import routes
from scout.services import db


def assert_closed(connection):
    with pytest.raises(sqlite3.ProgrammingError, match='closed database'):
        connection.execute('SELECT 1')


def test_app_lifespan_closes_shared_database_after_requests(tmp_path: Path):
    path = tmp_path / 'services.sqlite'
    app = routes.create_app(path)
    connection = app.state.scout_services.workflow_store._connection
    try:
        with TestClient(app) as client:
            assert client.get('/workflows', params={'user_id': 'fixture'}).status_code == 200
            assert connection.execute('SELECT 1').fetchone()[0] == 1
        assert_closed(connection)
        reopened = db.open_database(path)
        try:
            assert db.REQUIRED_TABLES <= db.list_tables(reopened)
        finally:
            reopened.close()
    finally:
        connection.close()


@pytest.mark.parametrize('phase', ['start', 'stop'])
def test_scheduler_lifecycle_failure_still_closes_database(tmp_path: Path, monkeypatch, phase):
    app = routes.create_app(tmp_path / 'scheduler.sqlite', enable_background_scheduler=True)
    services = app.state.scout_services
    connection = services.workflow_store._connection

    async def fail():
        raise RuntimeError('fixture lifecycle failure')

    monkeypatch.setattr(services.background_scheduler, phase, fail)
    try:
        with pytest.raises(RuntimeError, match='fixture lifecycle failure'):
            with TestClient(app):
                pass
        assert_closed(connection)
    finally:
        connection.close()


def test_connection_setup_failure_closes_allocated_handle(tmp_path: Path, monkeypatch):
    class FailedPragmaConnection(sqlite3.Connection):
        def execute(self, statement, *args):
            if statement.startswith('PRAGMA'):
                raise sqlite3.OperationalError('fixture setup failure')
            return super().execute(statement, *args)

    connection = sqlite3.connect(tmp_path / 'setup.sqlite', factory=FailedPragmaConnection)
    monkeypatch.setattr(db.sqlite3, 'connect', lambda *args, **kwargs: connection)
    try:
        with pytest.raises(sqlite3.OperationalError, match='fixture setup failure'):
            db.connect_database(tmp_path / 'setup.sqlite')
        assert_closed(connection)
    finally:
        connection.close()


def test_schema_initialization_failure_closes_database(tmp_path: Path, monkeypatch):
    connection = db.connect_database(tmp_path / 'schema.sqlite')
    monkeypatch.setattr(db, 'connect_database', lambda path: connection)

    def fail(_connection):
        raise sqlite3.OperationalError('fixture schema failure')

    monkeypatch.setattr(db, 'initialize_database', fail)
    try:
        with pytest.raises(sqlite3.OperationalError, match='fixture schema failure'):
            db.open_database(tmp_path / 'schema.sqlite')
        assert_closed(connection)
    finally:
        connection.close()


def test_services_constructor_failure_closes_database(tmp_path: Path, monkeypatch):
    connection = db.open_database(tmp_path / 'construction.sqlite')
    monkeypatch.setattr(routes, 'open_database', lambda path: connection)

    def fail(_connection):
        raise RuntimeError('fixture construction failure')

    monkeypatch.setattr(routes, 'WorkflowStore', fail)
    try:
        with pytest.raises(RuntimeError, match='fixture construction failure'):
            routes.create_services(tmp_path / 'construction.sqlite')
        assert_closed(connection)
    finally:
        connection.close()
