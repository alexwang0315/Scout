"""Attest the explicitly installed local compatibility wheel in a fresh process."""
from pathlib import Path
import hashlib
import importlib.metadata
import json
import sys

import fastapi
from fastapi._compat import v2

VERSION = '0.141.1+scout.warningcontext1'
CODE_SHA256 = '3813054e7d89139ad572659f8745dc66df316741ca36d1ea44d4bcd597bd24b3'

source = Path(v2.__file__).resolve()
assert importlib.metadata.version('fastapi') == VERSION
assert fastapi.__version__ == VERSION
assert source.is_relative_to(Path(sys.prefix).resolve())
assert hashlib.sha256(source.read_bytes()).hexdigest() == CODE_SHA256
print(json.dumps({'fastapi': VERSION, 'source': str(source), 'source_sha256': CODE_SHA256,
                  'python': sys.version, 'prefix': sys.prefix, 'local_patch_not_official_release': True}))
