# Optional Starlette / AnyIO qualification overlay

This is an explicitly selected QA dependency, not a mandatory Scout runtime
dependency. It does not modify `pyproject.toml`, the shared venv, running
Dashboard processes, or the Navigation freeze baseline.

Starlette 1.6.0 uses the deprecated `anyio.abc.BlockingPortal` alias in three
TestClient annotations. This recipe applies only the corresponding replacement
from [official main commit 03f12b7](https://github.com/Kludex/starlette/blob/03f12b7fcf0a3e21a8da648ca0900c79472e9efe/starlette/testclient.py)
to the hash-pinned [official 1.6.0 wheel](https://pypi.org/project/starlette/1.6.0/).
`1.6.0+scout.anyioportal1` is a **local backport, not an official release**.
The builder also updates local package metadata and wheel RECORD. No warnings
are suppressed, no import monkeypatch is installed, and no other runtime code
is copied from main.

## Rebuild and verify

Use the Python interpreter of the environment being qualified. Run the build
and pip commands from this directory; choose a new absolute overlay directory
so an existing installation is never overwritten.

```sh
SCOUT_QA_PY=/path/to/existing/venv/bin/python
SCOUT_QA_OVERLAY=/absolute/path/to/new-starlette-overlay
"$SCOUT_QA_PY" -B rebuild_starlette.py --download
"$SCOUT_QA_PY" -B -m pip install --no-index --no-deps --no-compile --require-hashes \
  --target "$SCOUT_QA_OVERLAY" -r requirements-overlay.txt
"$SCOUT_QA_PY" -B verify.py --target "$SCOUT_QA_OVERLAY"
```

The source download is opt-in. If `upstream/starlette-1.6.0-py3-none-any.whl`
already exists, omit `--download` to rebuild offline. The builder requires its
fixed SHA-256 and produces deterministic sorted, fixed-timestamp wheel bytes.
Generated wheel and source cache directories are ignored; no wheel is committed.
`provenance.json` contains the official source URL and both expected hashes.

`verify.py` launches fresh child processes with the specified overlay first in
`PYTHONPATH`. It checks that imports and distribution metadata resolve to the
intended local backport and runs all 16 behavioral compatibility cases with
warnings treated as errors **only in those child processes**. It accepts
`--junitxml /absolute/path/results.xml` for a test receipt. It does not alter the
parent environment or apply warning policy to an unpatched shared runtime.

The cases cover lifespan, API validation, headers/cookies, redirect/root_path,
ContextVar and threadpool propagation, concurrent requests, streamed request and
response content, background tasks, exception recovery, startup/shutdown failure
cleanup, WebSocket close, and ASGI2 wrapping. They use in-process ASGI transport:
streaming assertions do not prove real network chunk timing.
`compatibility_cases.py` is deliberately invoked by path; its filename is not
part of pytest's automatic `test_*.py` discovery.

## Scope and adoption

`compatibility-versions.txt` records the existing dependency combination used
for the 2026-09-14 isolated compatibility proof. It is a receipt, not a command
to upgrade or downgrade all packages. The original package passed the same 16
behavior cases with one deprecation warning; the backport passed with no
warnings. The original strict fresh import failed on that warning.

For a cumulative Scout run, prepend the verified overlay to the existing
`PYTHONPATH` while retaining all prior source/test paths and affected tests.
A clean 16-case result alone is not Dashboard, Diagnostic, map, or product
qualification. Record source and package hashes, run the full affected suite,
and qualify the actual service/UI version separately. This optional source
recipe does not install the backport into live services.
