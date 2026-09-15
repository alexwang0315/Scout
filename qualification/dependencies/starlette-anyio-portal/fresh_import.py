"""Verify the imported package identity before exercising the optional overlay."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import typing

import anyio.from_thread
import fastapi.testclient
import starlette
import starlette.testclient

expected_target = Path(sys.argv[1]).resolve(strict=True)
module = Path(starlette.testclient.__file__).resolve()
assert module.is_relative_to(expected_target), (str(module), str(expected_target))
expected_version = "1.6.0+scout.anyioportal1"
assert starlette.__version__ == expected_version
assert importlib.metadata.version("starlette") == expected_version
assert fastapi.testclient.TestClient is starlette.testclient.TestClient
source = module.read_bytes()
assert hashlib.sha256(source).hexdigest() == "1b1218ff0831e25fd660499062b743c00a3a35918f56f8bff1642535dbc1a616"
hints = typing.get_type_hints(starlette.testclient.TestClient)
assert anyio.from_thread.BlockingPortal in typing.get_args(hints["portal"])
print(json.dumps({
    "starlette_version": starlette.__version__,
    "metadata_version": importlib.metadata.version("starlette"),
    "file": str(module),
    "source_sha256": hashlib.sha256(source).hexdigest(),
    "typing_hints_evaluated": True,
    "fastapi_reexport_identical": True,
    "explicit_target_verified": True,
}))
