"""Own database handles opened directly by the importing test's fixtures.

This wraps only that test module's imported factory aliases. Production
factories and connections opened inside Scout services retain their own
lifecycle and remain observable by the native-resource regression tests.
"""

from contextlib import ExitStack

import pytest

from scout.services import db


@pytest.fixture
def owned_test_databases(request, monkeypatch):
    with ExitStack() as resources:
        for name in ('open_database', 'connect_database'):
            factory = getattr(request.module, name, None)
            if factory is not getattr(db, name):
                continue

            def owned_factory(*args, _factory=factory, **kwargs):
                connection = _factory(*args, **kwargs)
                resources.callback(connection.close)
                return connection

            monkeypatch.setattr(request.module, name, owned_factory)
        yield
