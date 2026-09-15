# FastAPI warning-context compatibility patch

This optional local wheel repairs a reproduced concurrency failure in FastAPI
0.141.1 with Pydantic 2.13.5 on Python 3.12/3.13. FastAPI builds each ModelField
inside `warnings.catch_warnings()`. Those Python versions share warning filters
between threads. Overlapping contexts can restore another thread's filters while
its TypeAdapter is still running. With strict warnings this interrupts app
construction or deferred routing on the first request.

The patch locks the existing ModelField warning context, covering both initial
and deferred field construction. It does not change FastAPI's warning categories,
validation, aliases, route selection, or Scout acceptance expectations. Scout's
test runner retains `-W error`. This is a local compatibility patch, not an
official FastAPI release.

Build from the SHA-verified official wheel:

```bash
python qualification/dependencies/fastapi-warning-context/rebuild_fastapi.py \
  --source /path/to/fastapi-0.141.1-py3-none-any.whl \
  --output-dir /path/to/isolated-wheelhouse --download
```

Install the resulting `0.141.1+scout.warningcontext1` wheel only into the intended
isolated virtual environment with `python -m pip install --no-deps --no-index`.
Then run its `fresh_import.py` with that interpreter and run
`tests/test_fastapi_warning_context.py`, the API lifecycle and concurrency tests,
and the complete affected regression scope. Installation alone is not acceptance.

The regression deliberately interleaves two real field constructions and checks
value validation, aliases, restored warning filters, and continued enforcement of
the warning category. The original wheel must fail that same test. The API
regression also exercises concurrent application creation and first requests.

Official references:

- https://github.com/fastapi/fastapi/blob/0.141.1/fastapi/_compat/v2.py
- https://docs.python.org/3/library/warnings.html#concurrent-safety-of-context-managers

The wheel contains a `scout-build.json` provenance record and recomputed RECORD
hashes. The build uses fixed timestamps and sorted entries. Existing dependency
requirements remain in place; they are not silently rewritten by this recipe.
