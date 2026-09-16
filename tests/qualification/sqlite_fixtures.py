"""Exact synthetic SQLite read primitive allowed by Phase 3 specification 9.8."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, unquote, urlsplit


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reject_symlink_components(path: Path) -> None:
    for component in (path, *path.parents):
        if stat.S_ISLNK(os.lstat(component).st_mode):
            raise PermissionError("SQLite fixture has a symlink component")


@dataclass(frozen=True)
class ReadOnlySqliteFixture:
    path: Path
    execution_root: Path
    device: int
    inode: int
    content_sha256: str
    wal_identity: tuple[int, int, str] | None
    allow_empty_wal_coordination: bool = False

    @classmethod
    def seal(cls, path: Path, *, execution_root: Path, allow_empty_wal_coordination: bool = False) -> "ReadOnlySqliteFixture":
        path, root = Path(path).absolute(), Path(execution_root).absolute()
        if ".." in path.parts or ".." in root.parts:
            raise PermissionError("SQLite fixture paths must be canonical")
        _reject_symlink_components(path)
        _reject_symlink_components(root)
        if not path.is_relative_to(root) or not path.is_file():
            raise PermissionError("SQLite fixture is not a file inside its execution root")
        info = path.stat()
        if info.st_nlink != 1:
            raise PermissionError("SQLite fixture must have exactly one link")
        wal = Path(str(path) + "-wal")
        wal_identity = None
        if wal.exists():
            _reject_symlink_components(wal)
            wal_info = wal.stat()
            wal_identity = (wal_info.st_dev, wal_info.st_ino, _digest(wal))
        sealed = cls(path, root, info.st_dev, info.st_ino, _digest(path), wal_identity, allow_empty_wal_coordination)
        sealed.validate()
        return sealed

    def validate(self) -> None:
        _reject_symlink_components(self.path)
        if not self.path.is_relative_to(self.execution_root):
            raise PermissionError("SQLite fixture escaped its execution root")
        info = self.path.stat()
        if info.st_nlink != 1:
            raise PermissionError("SQLite fixture link count changed")
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(self.path) + suffix)
            if sidecar.exists():
                _reject_symlink_components(sidecar)
                if not sidecar.is_file() or sidecar.stat().st_nlink != 1:
                    raise PermissionError("SQLite coordination sidecar is not an exact local file")
        if (info.st_dev, info.st_ino, _digest(self.path)) != (self.device, self.inode, self.content_sha256):
            raise PermissionError("SQLite fixture changed after it was sealed")
        wal = Path(str(self.path) + "-wal")
        if self.wal_identity is None:
            if wal.exists() and not (self.allow_empty_wal_coordination and wal.stat().st_size == 0):
                raise PermissionError("SQLite fixture acquired an undeclared WAL")
        else:
            _reject_symlink_components(wal)
            wal_info = wal.stat()
            if (wal_info.st_dev, wal_info.st_ino, _digest(wal)) != self.wal_identity:
                raise PermissionError("SQLite fixture WAL changed after it was sealed")


def match_readonly_fixture(
    args: tuple[Any, ...], kwargs: dict[str, Any],
    fixtures: tuple[ReadOnlySqliteFixture, ...],
) -> ReadOnlySqliteFixture | None:
    if len(args) != 1 or not isinstance(args[0], str):
        return None
    if kwargs.get("uri") is not True or set(kwargs) - {"uri", "timeout"}:
        return None
    uri = urlsplit(args[0])
    if uri.scheme != "file" or uri.netloc or uri.fragment:
        return None
    if uri.query != "mode=ro" or parse_qsl(uri.query, keep_blank_values=True) != [("mode", "ro")]:
        return None
    path_text = unquote(uri.path, errors="strict")
    if "\0" in path_text:
        return None
    for fixture in fixtures:
        if path_text == str(fixture.path) and args[0] == "file:" + quote(str(fixture.path), safe="/") + "?mode=ro":
            fixture.validate()
            return fixture
    return None


def connect_readonly_fixture(
    native_connect: Any, args: tuple[Any, ...], kwargs: dict[str, Any],
    *, fixture: ReadOnlySqliteFixture, audit: Any,
) -> sqlite3.Connection:
    scope, ref = audit._scope(fixture.path)
    declared_roots = {name: root for name, root in audit._roots}
    if scope not in {"execution", "workspace"} or declared_roots.get(scope) != fixture.execution_root.resolve():
        raise PermissionError("SQLite fixture capability does not bind this execution root")
    fixture.validate()

    def record(operation: str, outcome: str = "attempted") -> None:
        audit._record_known_scope(operation, scope, ref, effect_class="synthetic_loopback_database", outcome=outcome)

    allowed_actions = {sqlite3.SQLITE_READ, sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_TRANSACTION}

    def authorizer(action: int, arg1: str | None, arg2: str | None, _database: str | None, _trigger: str | None) -> int:
        if action == sqlite3.SQLITE_PRAGMA:
            permitted = (arg1 or "").lower() == "query_only" and (arg2 or "").lower() in {"", "on", "1", "true"}
            if not permitted:
                record("database.forbidden_pragma", "blocked_before_invocation")
            return sqlite3.SQLITE_OK if permitted else sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION and (arg2 or arg1 or "").lower() == "load_extension":
            record("database.forbidden_extension", "blocked_before_invocation")
            return sqlite3.SQLITE_DENY
        if action in allowed_actions:
            return sqlite3.SQLITE_OK
        record("database.forbidden_statement", "blocked_before_invocation")
        return sqlite3.SQLITE_DENY

    class AuditedConnection(sqlite3.Connection):
        _qualification_closed = False

        def close(self) -> None:
            if self._qualification_closed:
                return
            try:
                actual_query_only = sqlite3.Connection.execute(self, "PRAGMA query_only").fetchone()[0]
                record("database.query_only_observed", "passed" if actual_query_only == 1 else "failed")
                if actual_query_only != 1:
                    raise PermissionError("Production SQLite reader did not enable query_only")
                fixture.validate()
                if fixture.allow_empty_wal_coordination:
                    for suffix in ("-wal", "-shm"):
                        if Path(str(fixture.path) + suffix).exists():
                            record("database.sqlite_coordination" + suffix, "observed")
            finally:
                self._qualification_closed = True
                sqlite3.Connection.close(self)
                record("database.close", "completed")

        def set_authorizer(self, _callback: Any) -> None:
            record("database.replace_authorizer", "blocked_before_invocation")
            raise PermissionError("SQLite fixture read authorizer cannot be replaced")

        def enable_load_extension(self, _enabled: bool) -> None:
            record("database.enable_extension", "blocked_before_invocation")
            raise PermissionError("SQLite fixture extensions are forbidden")

    record("database.connect.readonly")
    # Preserve every URI/flag supplied by real production code. The factory only
    # observes native SQLite and restricts extra-file SQL effects.
    connection = native_connect(*args, **kwargs, factory=AuditedConnection)
    sqlite3.Connection.set_authorizer(connection, authorizer)
    record("database.connect.readonly", "completed")
    return connection
