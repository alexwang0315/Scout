#!/usr/bin/env python3
"""Build an attested FastAPI wheel that serializes its warning contexts."""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

BASE_VERSION = '0.141.1'
VERSION = '0.141.1+scout.warningcontext1'
SOURCE_URL = 'https://files.pythonhosted.org/packages/cb/03/10388a42375ee7e4ac9b94eb2c5c569c8b5795e377e701c9ac3ad63de890/fastapi-0.141.1-py3-none-any.whl'
SOURCE_SHA256 = 'bfb91aa2d334c61cb35ba9a116fc123b3d3df31640b801cf57a7a78ec3f603b3'
SOURCE_CODE_SHA256 = 'b031b28b588a4855bd2ee27b9f807ad7ed72ad0235347452c2c15144bb8527c9'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def build(source, output_dir, download=False):
    if not source.exists() and download:
        with urllib.request.urlopen(SOURCE_URL, timeout=30) as response:
            data = response.read()
        if digest(data) != SOURCE_SHA256:
            raise ValueError('Official wheel hash mismatch')
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(data)
    data = source.read_bytes()
    if digest(data) != SOURCE_SHA256:
        raise ValueError('Official wheel hash mismatch')
    old_info = f'fastapi-{BASE_VERSION}.dist-info'
    new_info = f'fastapi-{VERSION}.dist-info'
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        contents = {name.replace(old_info+'/', new_info+'/', 1): z.read(name)
                    for name in z.namelist() if not name.endswith('/')}
    path = 'fastapi/_compat/v2.py'
    original = contents[path]
    if digest(original) != SOURCE_CODE_SHA256:
        raise ValueError('Unexpected ModelField source')
    code = original.decode()
    before = '    def __post_init__(self) -> None:\n        with warnings.catch_warnings():'
    after = '    def __post_init__(self) -> None:\n        with _model_field_warning_lock, warnings.catch_warnings():'
    if code.count(before) != 1 or code.count('import warnings\n') != 1:
        raise ValueError('Unexpected warning context structure')
    code = code.replace('import warnings\n', 'import warnings\nfrom threading import RLock\n', 1)
    code = code.replace('@dataclass\nclass ModelField:',
        '# Python 3.12/3.13 warning contexts share process-global filters.\n'
        '# Serialize every field build, including deferred request routing.\n'
        '_model_field_warning_lock = RLock()\n\n\n@dataclass\nclass ModelField:', 1)
    contents[path] = code.replace(before, after).encode()
    version_marker = f'__version__ = "{BASE_VERSION}"'.encode()
    if contents['fastapi/__init__.py'].count(version_marker) != 1:
        raise ValueError('Unexpected FastAPI version declaration')
    contents['fastapi/__init__.py'] = contents['fastapi/__init__.py'].replace(
        version_marker, f'__version__ = "{VERSION}"'.encode())
    contents[f'{new_info}/METADATA'] = contents[f'{new_info}/METADATA'].replace(
        f'\nVersion: {BASE_VERSION}\n'.encode(), f'\nVersion: {VERSION}\n'.encode(), 1)
    provenance = {'base_version': BASE_VERSION, 'version': VERSION,
                  'source_url': SOURCE_URL, 'source_wheel_sha256': SOURCE_SHA256,
                  'original_code_sha256': digest(original), 'candidate_code_sha256': digest(contents[path]),
                  'local_patch_not_official_release': True,
                  'scope': 'Serialize existing ModelField warning contexts; no warning policy, alias, validation or routing changes'}
    contents[f'{new_info}/scout-build.json'] = (json.dumps(provenance, indent=2, sort_keys=True)+'\n').encode()
    record_name = f'{new_info}/RECORD'
    contents.pop(record_name)
    buf = io.StringIO(newline='')
    writer = csv.writer(buf, lineterminator='\n')
    for name, payload in sorted(contents.items()):
        encoded = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b'=').decode()
        writer.writerow((name, 'sha256='+encoded, len(payload)))
    writer.writerow((record_name, '', ''))
    contents[record_name] = buf.getvalue().encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_STORED) as z:
        for name, payload in sorted(contents.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            z.writestr(info, payload)
    payload = buffer.getvalue()
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f'fastapi-{VERSION}-py3-none-any.whl'
    if output.exists() and output.read_bytes() != payload:
        raise ValueError('Refuse to replace a different wheel')
    output.write_bytes(payload)
    return {'wheel': str(output), 'sha256': digest(payload), **provenance}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--download', action='store_true')
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output_dir, args.download), indent=2))
