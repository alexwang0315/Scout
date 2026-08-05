from __future__ import annotations

import ast
import builtins
import fcntl
import os
import sqlite3
import socket
import subprocess
import tempfile
import urllib.request
from contextlib import ExitStack
from pathlib import Path
from typing import Sequence
from collections.abc import Callable
from unittest.mock import patch

from tests.qualification.contracts import (
    EffectAttempt,
    EffectCallsiteSpec,
    EffectClassAuditResult,
    EffectSurfaceManifest,
    Finding,
    finding,
)


_PATH_EFFECT_METHODS = {
    "mkdir",
    "open",
    "read_bytes",
    "read_text",
    "write_bytes",
    "write_text",
    "replace",
    "rename",
    "unlink",
    "glob",
    "rglob",
    "iterdir",
    "is_file",
    "is_dir",
    "exists",
    "stat",
    "resolve",
}

_MODULE_EFFECT_CALLS = {
    "os.fdopen",
    "os.fsync",
    "os.link",
    "os.open",
    "os.remove",
    "os.rename",
    "os.replace",
    "os.unlink",
    "tempfile.mkstemp",
    "tempfile.NamedTemporaryFile",
    "fcntl.flock",
    "socket.socket",
    "subprocess.run",
    "subprocess.Popen",
    "requests.get",
    "requests.post",
    "httpx.get",
    "httpx.post",
    "sqlite3.connect",
    "urllib.request.urlopen",
}

_STORE_EFFECT_METHODS = {
    "_write_new_json",
    "_write_new_or_validate_json",
    "_write_replace_json",
}

_SENSITIVE_IMPORT_PREFIXES = (
    "aiohttp",
    "boto3",
    "httpx",
    "psycopg",
    "redis",
    "requests",
    "socket",
    "sqlite3",
    "sqlalchemy",
    "subprocess",
    "urllib.request",
)

_READ_PATH_METHODS = {
    "read_bytes",
    "read_text",
    "glob",
    "rglob",
    "iterdir",
    "is_file",
    "is_dir",
    "exists",
    "stat",
}

_WRITE_PATH_METHODS = {
    "write_bytes",
    "write_text",
}


def _call_name(node: ast.Call) -> str | None:
    function = node.func
    if isinstance(function, ast.Name):
        return function.id
    if not isinstance(function, ast.Attribute):
        return None
    parts = [function.attr]
    value = function.value
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts))


def _signature_operation(signature: str) -> tuple[str, str]:
    if signature.startswith("store."):
        return "store.write", "canonical_store"
    if signature in {"sqlite3.connect"}:
        return "database.connect", "external_store_database"
    if signature.startswith(("requests.", "httpx.", "urllib.request.")):
        return "http.request", "http_client"
    if signature == "socket.socket":
        return "network.socket", "network_socket"
    if signature.startswith("subprocess."):
        return signature, "subprocess"
    if signature == "path.mkdir":
        return "fs.mkdir", "filesystem_store"
    if signature in {
        "path.read_bytes",
        "path.read_text",
        "path.glob",
        "path.rglob",
        "path.iterdir",
        "path.is_file",
        "path.is_dir",
        "path.exists",
        "path.stat",
        "path.resolve",
    }:
        return "fs.read", "filesystem_store"
    if signature in {"path.write_bytes", "path.write_text"}:
        return "fs.write", "filesystem_store"
    if signature in {"path.replace", "path.rename", "os.replace", "os.rename"}:
        return "fs.replace", "filesystem_store"
    if signature in {"path.unlink", "os.remove", "os.unlink"}:
        return "fs.delete", "filesystem_store"
    if signature in {"path.open", "builtin.open", "os.open", "os.fdopen"}:
        return "fs.open", "filesystem_store"
    if signature in {"tempfile.mkstemp", "tempfile.NamedTemporaryFile"}:
        return "fs.temp_create", "filesystem_store"
    if signature == "file.flush":
        return "fs.flush", "filesystem_store"
    if signature == "os.fsync":
        return "fs.fsync", "filesystem_store"
    if signature == "os.link":
        return "fs.link", "filesystem_store"
    if signature == "fcntl.flock":
        return "fs.lock", "filesystem_store"
    return "unclassified", "unclassified"


def discover_python_effect_callsites(
    path: Path,
    *,
    source_ref: str | None = None,
) -> tuple[EffectCallsiteSpec, ...]:
    source_path = Path(path)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    discovered: list[EffectCallsiteSpec] = []
    ref = source_ref or source_path.as_posix()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name is None:
            continue
        final = name.rsplit(".", 1)[-1]
        signatures: set[str] = set()
        if final in _PATH_EFFECT_METHODS:
            signatures.add(f"path.{final}")
        if name in _MODULE_EFFECT_CALLS:
            signatures.add(name)
        if name == "open":
            signatures.add("builtin.open")
        if final == "flush":
            signatures.add("file.flush")
        if final in _STORE_EFFECT_METHODS:
            signatures.add(f"store.{final}")
        for signature in sorted(signatures):
            operation, effect_class = _signature_operation(signature)
            discovered.append(
                EffectCallsiteSpec(
                    callsite_id=(
                        f"{ref}:{node.lineno}:{node.col_offset}:{signature}"
                    ),
                    source_ref=ref,
                    line=node.lineno,
                    signature=signature,
                    operation=operation,
                    effect_class=effect_class,
                )
            )
    return tuple(sorted(discovered, key=lambda item: item.callsite_id))


def discover_python_effect_calls(path: Path) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                item.signature
                for item in discover_python_effect_callsites(path)
            }
        )
    )


def discover_python_sensitive_imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return tuple(
        sorted(
            f"import:{module}"
            for module in modules
            if module.startswith(_SENSITIVE_IMPORT_PREFIXES)
        )
    )


class _AuditedHandle:
    def __init__(
        self,
        handle: object,
        *,
        audit: "EffectAudit",
        scope: str,
        ref: str,
    ) -> None:
        self._handle = handle
        self._audit = audit
        self._scope_name = scope
        self._ref = ref

    def __enter__(self) -> "_AuditedHandle":
        self._handle.__enter__()  # type: ignore[union-attr]
        return self

    def __exit__(self, *args: object) -> object:
        return self._handle.__exit__(*args)  # type: ignore[union-attr]

    def __iter__(self) -> object:
        return iter(self._handle)  # type: ignore[arg-type]

    def __next__(self) -> object:
        return next(self._handle)  # type: ignore[arg-type]

    def __getattr__(self, name: str) -> object:
        return getattr(self._handle, name)

    def write(self, value: object) -> object:
        self._audit._record_known_scope(
            "fs.write",
            self._scope_name,
            self._ref,
        )
        return self._handle.write(value)  # type: ignore[union-attr]

    def flush(self) -> object:
        self._audit._record_known_scope(
            "fs.flush",
            self._scope_name,
            self._ref,
        )
        return self._handle.flush()  # type: ignore[union-attr]


class EffectAudit:
    """Record applicable filesystem attempts before their primitive executes."""

    def __init__(
        self,
        *,
        transition_id: str,
        roots: Sequence[tuple[str, Path]],
        block_outside: bool = True,
    ) -> None:
        self.transition_id = transition_id
        self._roots = tuple(
            (name, Path(root).resolve()) for name, root in roots
        )
        self._attempts: list[EffectAttempt] = []
        self._fd_scopes: dict[int, tuple[str, str]] = {}
        self._stack = ExitStack()
        self._block_outside = block_outside
        self._active_canary_id: str | None = None

    @property
    def attempts(self) -> tuple[EffectAttempt, ...]:
        return tuple(self._attempts)

    def add_cleanup(self, callback: Callable[[], object]) -> None:
        """Run an inner patch cleanup before primitive patches are restored."""

        self._stack.callback(callback)

    def _scope(self, value: object) -> tuple[str, str]:
        try:
            resolved = Path(os.path.realpath(os.fspath(value)))
        except (OSError, TypeError, ValueError):
            return "outside", repr(value)
        for name, root in self._roots:
            if resolved == root or root in resolved.parents:
                return name, resolved.relative_to(root).as_posix() or "."
        return "outside", resolved.as_posix()

    def _record(
        self,
        operation: str,
        value: object,
        *,
        effect_class: str = "filesystem_store",
    ) -> tuple[str, str]:
        scope, ref = self._scope(value)
        self._attempts.append(
            EffectAttempt(
                transition_id=self.transition_id,
                operation=operation,
                effect_class=effect_class,
                scope=scope,
                ref=ref,
            )
        )
        return scope, ref

    def _record_known_scope(
        self,
        operation: str,
        scope: str,
        ref: str,
        *,
        effect_class: str = "filesystem_store",
        outcome: str = "attempted",
        canary_id: str | None = None,
    ) -> None:
        self._attempts.append(
            EffectAttempt(
                transition_id=self.transition_id,
                operation=operation,
                effect_class=effect_class,
                scope=scope,
                ref=ref,
                outcome=outcome,  # type: ignore[arg-type]
                canary_id=canary_id,
            )
        )

    def _block_external(
        self,
        *,
        operation: str,
        effect_class: str,
        ref: str,
    ) -> None:
        self._record_known_scope(
            operation,
            "outside",
            ref,
            effect_class=effect_class,
            outcome="blocked_before_invocation",
            canary_id=self._active_canary_id,
        )
        raise PermissionError(
            f"qualification blocks {effect_class} effect before invocation"
        )

    def run_absent_effect_canary(
        self,
        *,
        canary_id: str,
        effect_class: str,
        operation: str,
    ) -> None:
        self._active_canary_id = canary_id
        try:
            if effect_class == "external_store_database":
                sqlite3.connect(":memory:")
            elif effect_class == "http_client":
                urllib.request.urlopen("https://qualification.invalid")
            elif effect_class == "network_socket":
                socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            elif effect_class == "subprocess":
                subprocess.run(("qualification-forbidden",), check=False)
            else:
                self._block_external(
                    operation=operation,
                    effect_class=effect_class,
                    ref=f"canary:{canary_id}",
                )
        finally:
            self._active_canary_id = None

    def _deny_outside(self, scope: str, ref: str) -> None:
        if self._block_outside and scope == "outside":
            raise PermissionError(f"qualification effect escaped root: {ref}")

    def _patch_path_method(self, name: str, operation: str) -> None:
        original = getattr(Path, name)

        def wrapped(path: Path, *args: object, **kwargs: object) -> object:
            scope, ref = self._record(operation, path)
            self._deny_outside(scope, ref)
            return original(path, *args, **kwargs)

        self._stack.enter_context(patch.object(Path, name, wrapped))

    def _patch_path_move(self, name: str) -> None:
        original = getattr(Path, name)

        def wrapped(
            path: Path,
            target: object,
            *args: object,
            **kwargs: object,
        ) -> object:
            scope, ref = self._record("fs.replace", target)
            self._deny_outside(scope, ref)
            return original(path, target, *args, **kwargs)

        self._stack.enter_context(patch.object(Path, name, wrapped))

    def __enter__(self) -> "EffectAudit":
        for method in sorted(_READ_PATH_METHODS):
            self._patch_path_method(method, "fs.read")
        for method in sorted(_WRITE_PATH_METHODS):
            self._patch_path_method(method, "fs.write")
        self._patch_path_method("mkdir", "fs.mkdir")
        self._patch_path_method("unlink", "fs.delete")
        self._patch_path_move("replace")
        self._patch_path_move("rename")

        original_open = Path.open

        def path_open(
            path: Path,
            mode: str = "r",
            *args: object,
            **kwargs: object,
        ) -> object:
            operation = "fs.read" if not any(flag in mode for flag in "wax+") else "fs.open"
            scope, ref = self._record(operation, path)
            self._deny_outside(scope, ref)
            handle = original_open(path, mode, *args, **kwargs)
            try:
                self._fd_scopes[handle.fileno()] = self._scope(path)
            except (AttributeError, OSError):
                pass
            return _AuditedHandle(
                handle,
                audit=self,
                scope=scope,
                ref=ref,
            )

        self._stack.enter_context(patch.object(Path, "open", path_open))

        original_builtin_open = builtins.open

        def builtin_open(file: object, *args: object, **kwargs: object) -> object:
            mode = str(args[0]) if args else str(kwargs.get("mode", "r"))
            operation = (
                "fs.read"
                if not any(flag in mode for flag in "wax+")
                else "fs.open"
            )
            scope, ref = self._record(operation, file)
            self._deny_outside(scope, ref)
            handle = original_builtin_open(file, *args, **kwargs)
            try:
                self._fd_scopes[handle.fileno()] = (scope, ref)
            except (AttributeError, OSError):
                pass
            return _AuditedHandle(
                handle,
                audit=self,
                scope=scope,
                ref=ref,
            )

        self._stack.enter_context(patch.object(builtins, "open", builtin_open))

        original_os_open = os.open

        def os_open(path: object, *args: object, **kwargs: object) -> int:
            scope, ref = self._record("fs.open", path)
            self._deny_outside(scope, ref)
            descriptor = original_os_open(path, *args, **kwargs)
            self._fd_scopes[descriptor] = (scope, ref)
            return descriptor

        self._stack.enter_context(patch.object(os, "open", os_open))

        original_mkstemp = tempfile.mkstemp

        def mkstemp(*args: object, **kwargs: object) -> tuple[int, str]:
            directory = kwargs.get("dir")
            if directory is None and len(args) >= 3:
                directory = args[2]
            scope, ref = self._record(
                "fs.temp_create", directory or Path.cwd()
            )
            self._deny_outside(scope, ref)
            descriptor, raw_path = original_mkstemp(*args, **kwargs)
            self._fd_scopes[descriptor] = self._scope(raw_path)
            return descriptor, raw_path

        self._stack.enter_context(patch.object(tempfile, "mkstemp", mkstemp))

        original_fdopen = os.fdopen

        def fdopen(descriptor: int, *args: object, **kwargs: object) -> object:
            scope, ref = self._fd_scopes.get(
                descriptor,
                ("outside", f"fd:{descriptor}"),
            )
            self._attempts.append(
                EffectAttempt(
                    self.transition_id,
                    "fs.open",
                    "filesystem_store",
                    scope,
                    ref,
                )
            )
            self._deny_outside(scope, ref)
            return _AuditedHandle(
                original_fdopen(descriptor, *args, **kwargs),
                audit=self,
                scope=scope,
                ref=ref,
            )

        self._stack.enter_context(patch.object(os, "fdopen", fdopen))

        original_fsync = os.fsync

        def fsync(descriptor: int) -> None:
            scope, ref = self._fd_scopes.get(
                descriptor,
                ("outside", f"fd:{descriptor}"),
            )
            self._record_known_scope("fs.fsync", scope, ref)
            self._deny_outside(scope, ref)
            original_fsync(descriptor)

        self._stack.enter_context(patch.object(os, "fsync", fsync))

        original_link = os.link

        def link(source: object, destination: object, *args: object, **kwargs: object) -> None:
            scope, ref = self._record("fs.link", destination)
            self._deny_outside(scope, ref)
            original_link(source, destination, *args, **kwargs)

        self._stack.enter_context(patch.object(os, "link", link))

        def patch_os_path_call(
            name: str,
            operation: str,
            *,
            target_index: int = 0,
        ) -> None:
            original = getattr(os, name)

            def wrapped(*args: object, **kwargs: object) -> object:
                target = args[target_index]
                scope, ref = self._record(operation, target)
                self._deny_outside(scope, ref)
                return original(*args, **kwargs)

            self._stack.enter_context(patch.object(os, name, wrapped))

        patch_os_path_call("replace", "fs.replace", target_index=1)
        patch_os_path_call("rename", "fs.replace", target_index=1)
        patch_os_path_call("remove", "fs.delete")
        patch_os_path_call("unlink", "fs.delete")

        original_flock = fcntl.flock

        def flock(descriptor: int, operation: int) -> object:
            scope, ref = self._fd_scopes.get(
                descriptor,
                ("outside", f"fd:{descriptor}"),
            )
            self._attempts.append(
                EffectAttempt(
                    self.transition_id,
                    "fs.lock",
                    "filesystem_store",
                    scope,
                    ref,
                )
            )
            self._deny_outside(scope, ref)
            return original_flock(descriptor, operation)

        self._stack.enter_context(patch.object(fcntl, "flock", flock))

        original_sqlite_connect = sqlite3.connect

        def database_connect(*args: object, **kwargs: object) -> object:
            self._block_external(
                operation="database.connect",
                effect_class="external_store_database",
                ref=repr(args[0]) if args else "database",
            )
            return original_sqlite_connect(*args, **kwargs)

        self._stack.enter_context(
            patch.object(sqlite3, "connect", database_connect)
        )

        original_urlopen = urllib.request.urlopen

        def http_open(*args: object, **kwargs: object) -> object:
            self._block_external(
                operation="http.request",
                effect_class="http_client",
                ref=repr(args[0]) if args else "http",
            )
            return original_urlopen(*args, **kwargs)

        self._stack.enter_context(
            patch.object(urllib.request, "urlopen", http_open)
        )

        original_socket = socket.socket

        def create_socket(*args: object, **kwargs: object) -> object:
            family = (
                args[0]
                if args
                else kwargs.get("family", socket.AF_INET)
            )
            if family == socket.AF_UNIX:
                self._attempts.append(
                    EffectAttempt(
                        self.transition_id,
                        "ipc.local_socket",
                        "harness_ipc",
                        "workspace",
                        "in-process-testclient",
                    )
                )
                return original_socket(*args, **kwargs)
            self._block_external(
                operation="network.socket",
                effect_class="network_socket",
                ref="socket",
            )
            return original_socket(*args, **kwargs)

        self._stack.enter_context(patch.object(socket, "socket", create_socket))

        def patch_subprocess(name: str) -> None:
            def blocked(*args: object, **kwargs: object) -> object:
                self._block_external(
                    operation=f"subprocess.{name}",
                    effect_class="subprocess",
                    ref=repr(args[0]) if args else "subprocess",
                )
                return None

            self._stack.enter_context(patch.object(subprocess, name, blocked))

        patch_subprocess("run")
        patch_subprocess("Popen")
        return self

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        self._stack.close()


def run_absent_effect_canaries(
    manifest: EffectSurfaceManifest,
    *,
    execution_root: Path,
    discovered_calls: Sequence[str],
) -> tuple[tuple[EffectClassAuditResult, ...], tuple[EffectAttempt, ...]]:
    root = Path(execution_root).resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("effect canaries require a unique empty execution root")
    root.mkdir(parents=True, exist_ok=True)
    results: list[EffectClassAuditResult] = []
    attempts: list[EffectAttempt] = []
    for index, spec in enumerate(manifest.class_audits):
        canary_root = root / f"canary-{index:02d}"
        canary_root.mkdir()
        audit = EffectAudit(
            transition_id=spec.runtime_canary_id or spec.effect_class,
            roots=(("workspace", canary_root),),
        )
        blocked = False
        detail = ""
        try:
            with audit:
                audit.run_absent_effect_canary(
                    canary_id=spec.runtime_canary_id or "",
                    effect_class=spec.effect_class,
                    operation=spec.runtime_canary_operation or "",
                )
        except PermissionError as error:
            blocked = True
            detail = str(error)
        except BaseException as error:
            detail = f"{type(error).__name__}: {error}"
        attempts.extend(audit.attempts)
        matching = tuple(
            item
            for item in audit.attempts
            if item.canary_id == spec.runtime_canary_id
            and item.effect_class == spec.effect_class
            and item.operation == spec.runtime_canary_operation
            and item.outcome == "blocked_before_invocation"
        )
        forbidden_static = tuple(
            sorted(
                item
                for item in discovered_calls
                if item.startswith(spec.forbidden_static_prefixes)
            )
        )
        results.append(
            EffectClassAuditResult(
                effect_class=spec.effect_class,
                static_status="passed" if not forbidden_static else "failed",
                runtime_status=(
                    "passed" if blocked and len(matching) == 1 else "failed"
                ),
                canary_id=spec.runtime_canary_id,
                observed_operation=(matching[0].operation if len(matching) == 1 else None),
                detail=detail or repr(forbidden_static),
            )
        )
    return tuple(results), tuple(attempts)


def validate_static_effect_surface(
    manifest: EffectSurfaceManifest,
    discovered_calls: Sequence[str],
    discovered_callsites: Sequence[EffectCallsiteSpec] = (),
) -> tuple[Finding, ...]:
    missing = set(discovered_calls) - set(manifest.static_call_signatures)
    findings: list[Finding] = []
    if missing:
        findings.append(
            finding(
                "EFFECT-SURFACE-INCOMPLETE",
                f"Static effect calls are undeclared: {tuple(sorted(missing))}.",
                requirement="P2D-07",
                suffix="static-callsite",
            )
        )
    if discovered_callsites:
        manifest_callsites = {item.callsite_id: item for item in manifest.callsites}
        observed_callsites = {item.callsite_id: item for item in discovered_callsites}
        if manifest_callsites != observed_callsites:
            findings.append(
                finding(
                    "EFFECT-SURFACE-INCOMPLETE",
                    "Production effect callsite inventory does not match the manifest.",
                    requirement="P2D-07",
                    suffix="callsite-reconciliation",
                )
            )
        unclassified = tuple(
            sorted(
                item.callsite_id
                for item in discovered_callsites
                if item.operation == "unclassified"
                or item.effect_class == "unclassified"
            )
        )
        if unclassified:
            findings.append(
                finding(
                    "EFFECT-SURFACE-INCOMPLETE",
                    f"Production effect callsites are unclassified: {unclassified}.",
                    requirement="P2D-07",
                    suffix="unclassified-callsite",
                )
            )
    audits = {item.effect_class: item for item in manifest.class_audits}
    if set(audits) != set(manifest.absent_effect_classes):
        findings.append(
            finding(
                "EFFECT-SURFACE-INCOMPLETE",
                "Absent effect classes do not have a one-to-one static/canary audit declaration.",
                requirement="P2D-07",
                suffix="absent-class-audit",
            )
        )
    for effect_class in manifest.absent_effect_classes:
        audit = audits.get(effect_class)
        prefixes = (
            audit.forbidden_static_prefixes
            if audit is not None
            else {
                "network": ("socket.", "requests.", "httpx."),
                "subprocess": ("subprocess.",),
                "hardware": ("hardware.",),
            }.get(effect_class, ())
        )
        forbidden = {
            item for item in discovered_calls if item.startswith(prefixes)
        }
        if forbidden:
            findings.append(
                finding(
                    "FORBIDDEN-EFFECT",
                    f"Declared-absent {effect_class} calls exist: {tuple(sorted(forbidden))}.",
                    requirement="P2D-07",
                    suffix=f"static-{effect_class}",
                )
            )
    return tuple(findings)


def validate_effect_class_results(
    manifest: EffectSurfaceManifest,
    results: Sequence[EffectClassAuditResult],
) -> tuple[Finding, ...]:
    result_by_class = {item.effect_class: item for item in results}
    incomplete: list[str] = []
    for audit in manifest.class_audits:
        result = result_by_class.get(audit.effect_class)
        if (
            audit.disposition != "absent"
            or not audit.runtime_canary_id
            or not audit.runtime_canary_operation
            or result is None
            or result.static_status != "passed"
            or result.runtime_status != "passed"
            or result.canary_id != audit.runtime_canary_id
            or result.observed_operation != audit.runtime_canary_operation
        ):
            incomplete.append(audit.effect_class)
    if not incomplete:
        return ()
    return (
        finding(
            "EFFECT-SURFACE-INCOMPLETE",
            f"Absent effect class audits are incomplete: {tuple(sorted(incomplete))}.",
            requirement="P2D-07",
            suffix="absent-class-results",
        ),
    )


def _is_read_operation(operation: str) -> bool:
    return operation in {
        "fs.read",
        "fs.read_text",
        "fs.read_bytes",
        "fs.glob",
        "fs.stat",
    } or operation.startswith("read.")


def validate_effect_attempts(
    manifest: EffectSurfaceManifest,
    attempts: Sequence[EffectAttempt],
) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    audit_by_class = {
        item.effect_class: item for item in manifest.class_audits
    }
    for index, attempt in enumerate(attempts):
        reasons: list[str] = []
        audit = audit_by_class.get(attempt.effect_class)
        expected_canary = bool(
            audit
            and audit.disposition == "absent"
            and attempt.outcome == "blocked_before_invocation"
            and attempt.canary_id == audit.runtime_canary_id
            and attempt.operation == audit.runtime_canary_operation
        )
        if attempt.operation not in manifest.operations:
            if not expected_canary:
                reasons.append("undeclared operation")
        if attempt.effect_class in manifest.absent_effect_classes and not expected_canary:
            reasons.append("declared-absent effect class")
        allowed_scopes = (
            manifest.allowed_read_roots
            if _is_read_operation(attempt.operation)
            else manifest.allowed_write_roots
        )
        if attempt.scope not in allowed_scopes and not expected_canary:
            reasons.append("root escape")
        if not reasons:
            continue
        findings.append(
            finding(
                "FORBIDDEN-EFFECT",
                f"Effect {attempt.operation} on {attempt.ref} is blocked: {', '.join(reasons)}.",
                requirement="P2D-07",
                evidence=(attempt.transition_id,),
                suffix=f"{index}.{attempt.operation.replace('.', '-')}",
            )
        )
    return tuple(findings)


__all__ = [
    "EffectAudit",
    "discover_python_effect_calls",
    "discover_python_effect_callsites",
    "discover_python_sensitive_imports",
    "run_absent_effect_canaries",
    "validate_effect_attempts",
    "validate_effect_class_results",
    "validate_static_effect_surface",
]
