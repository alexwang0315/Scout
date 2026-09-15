from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient

import pytest

from scout.api import routes
from scout.services import db


@pytest.mark.parametrize('phase', ['FastAPI', 'create_router', 'include_router'])
def test_app_construction_exception_closes_services_database(tmp_path, monkeypatch, phase):
    connection = db.open_database(tmp_path / 'construction.sqlite')
    monkeypatch.setattr(routes, 'open_database', lambda path: connection)

    def fail(*args, **kwargs):
        raise RuntimeError('fixture app construction failure')

    if phase == 'include_router':
        monkeypatch.setattr(routes.FastAPI, 'include_router', fail)
    else:
        monkeypatch.setattr(routes, phase, fail)
    try:
        with pytest.raises(RuntimeError, match='fixture app construction failure'):
            routes.create_app(tmp_path / 'construction.sqlite')
        with pytest.raises(sqlite3.ProgrammingError, match='closed database'):
            connection.execute('SELECT 1')
    finally:
        connection.close()


def test_concurrent_app_construction_keeps_schema_and_database_ownership(tmp_path):
    def exercise(index):
        app = routes.create_app(tmp_path / f"parallel-{index}.sqlite")
        connection = app.state.scout_services.workflow_store._connection
        try:
            with TestClient(app) as client:
                response = client.get('/workflows', params={'user_id': f'fixture-{index}'})
                assert response.status_code == 200
                assert response.json()['workflows'] == []
            with pytest.raises(sqlite3.ProgrammingError, match='closed database'):
                connection.execute('SELECT 1')
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(exercise, range(20)))
