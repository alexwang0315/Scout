"""Run the shipped isolated Diagnostic probe and ensure real regressions fail it."""
from pathlib import Path
import re
import subprocess

import pytest

PAGE = Path(__file__).resolve().parents[1] / 'docs/admin/scout-dashboard-v0.1.html'
NAMES = ['projectId', 'apiBase', 'resolvedPretripProjectId', 'pretripDataProjectIds',
         'fetchFirstPretripJson', 'diagnosticCaseScopeKey', 'diagnosticResult',
         'diagnosticRequire', 'diagnosticProjectIsolationReplay']


def sources():
    page = PAGE.read_text()
    return '\n'.join(re.search(rf'(?ms)^    (?:async )?function {name}\(.*?^    }}', page).group()
                     for name in NAMES)


def execute(source, assertion):
    result = subprocess.run(['node'], input=source + '''
const assert = require('node:assert/strict');
// Deliberately hostile live bindings: any accidental reference fails the probe.
const state = new Proxy({}, {get(){throw Error('live state read');}, set(){throw Error('live state write');}});
const window = new Proxy({}, {get(){throw Error('live window read');}});
const localStorage = new Proxy({}, {get(){throw Error('live storage read');}});
const fetchJson = () => {throw Error('live network used');};
(async()=>{''' + assertion + '''})().catch(error=>{console.error(error);process.exitCode=1;});
''', text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_shipped_probe_replays_production_functions_without_live_effects():
    execute(sources(), '''
const result = await diagnosticProjectIsolationReplay();
assert.match(result, /非實際 UI 切換/);
assert.match(result, /A→B/);
''')


@pytest.mark.parametrize(('original', 'broken', 'message'), [
    ('if (resolvedPretripProjectId() !== candidateProjectId)', 'if (false)', 'late A response was accepted'),
    ('if (data?.project_id && data.project_id !== candidateProjectId)', 'if (false)', 'foreign-project response was accepted'),
    ('return result && !changed ? result : {', 'return result ? result : {', 'A result remained valid'),
    ('return [resolvedPretripProjectId()];', 'return [resolvedPretripProjectId(), "old_demo"];', 'alias fallback was enabled'),
    ('state.pretripDataProjectId = candidateProjectId;', 'state.pretripDataProjectId = "wrong";', 'B data binding was not adopted'),
])
def test_probe_detects_production_regressions(original, broken, message):
    source = sources()
    assert original in source
    execute(source.replace(original, broken, 1),
            f'await assert.rejects(diagnosticProjectIsolationReplay(), error=>error.message.includes({message!r}));')


def test_check003_invokes_probe_in_real_diagnostic_entrypoint():
    page = PAGE.read_text()
    check = re.search(r'(?ms)^    async function diagnosticCheck003\(.*?^    }', page).group()
    assert 'await diagnosticProjectIsolationReplay()' in check
    assert '${replay}' in check
