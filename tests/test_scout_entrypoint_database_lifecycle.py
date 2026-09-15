from __future__ import annotations

import importlib.util
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import scout
from fastapi import FastAPI
from fastapi.testclient import TestClient


def load_entrypoint():
    path = Path(scout.__file__).resolve().with_name('main.py')
    spec = importlib.util.spec_from_file_location('scout_entrypoint_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def close_fixture_app(module):
    app = vars(module).get('app')
    if app is not None:
        app.state.scout_services.workflow_store._connection.close()


def test_importing_factory_does_not_create_default_database(tmp_path, monkeypatch):
    database_path = tmp_path / 'default.sqlite'
    monkeypatch.setenv('SCOUT_AI_OS_DATABASE_PATH', str(database_path))
    module = load_entrypoint()
    try:
        assert callable(module.create_default_app)
        assert not database_path.exists()
        assert 'app' not in vars(module)
    finally:
        close_fixture_app(module)


def test_app_lookup_preserves_fastapi_identity_and_lifespan(tmp_path, monkeypatch):
    monkeypatch.setenv('SCOUT_AI_OS_DATABASE_PATH', str(tmp_path / 'default.sqlite'))
    module = load_entrypoint()
    try:
        app = module.app
        assert isinstance(app, FastAPI)
        assert module.app is app
        connection = app.state.scout_services.workflow_store._connection
        with TestClient(app) as client:
            assert client.get('/workflows', params={'user_id': 'fixture'}).status_code == 200
        with pytest.raises(sqlite3.ProgrammingError, match='closed database'):
            connection.execute('SELECT 1')
    finally:
        close_fixture_app(module)


def test_concurrent_app_lookup_builds_only_one_application(tmp_path, monkeypatch):
    monkeypatch.setenv('SCOUT_AI_OS_DATABASE_PATH', str(tmp_path / 'default.sqlite'))
    module = load_entrypoint()
    created = []
    original = module.create_default_app

    def counted():
        app = original()
        created.append(app)
        return app

    monkeypatch.setattr(module, 'create_default_app', counted)
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            apps = list(pool.map(lambda _: module.app, range(10)))
        assert len(created) == 1
        assert all(app is created[0] for app in apps)
    finally:
        close_fixture_app(module)


def test_unknown_entrypoint_attribute_does_not_create_database(tmp_path, monkeypatch):
    database_path = tmp_path / 'default.sqlite'
    monkeypatch.setenv('SCOUT_AI_OS_DATABASE_PATH', str(database_path))
    module = load_entrypoint()
    try:
        with pytest.raises(AttributeError, match='missing_attribute'):
            module.missing_attribute
        assert not database_path.exists()
    finally:
        close_fixture_app(module)
