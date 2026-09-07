"""Isolated production workflow replays must expose regressions without live effects."""
from pathlib import Path
import re
import subprocess

import pytest

PAGE = Path(__file__).resolve().parents[1] / "docs/admin/scout-dashboard-v0.1.html"
HELPERS = ["diagnosticAdvancedAssistantReplay", "diagnosticAdvancedLivingReplay", "diagnosticAdvancedIntelligenceReplay"]
PRODUCTION = ["submitAgentQuestion", "formatAgentEvalAnswer", "displayAgentAnswer", "agentResponseMeta",
              "agentGroundingGuard", "agentAiHatGenerationMode", "agentAiHatSkillId", "agentAiHatTypedDecision",
              "agentAiHatActionToken", "agentAiHatTraceValue", "agentLimitations", "agentDeterministicFallbackOnly",
              "agentAnswerLooksLikeReferenceCopy", "agentToolUsing", "agentMissingTools", "agentMissingEvidence",
              "agentLooksLikeToolSource", "collectMissingEvidence", "formatMissingEvidenceItem", "dedupe", "performLivingAction"]


def source():
    page = PAGE.read_text()
    return "\n".join(re.search(rf"(?ms)^    (?:async )?function {name}\(.*?^    }}", page).group()
                     for name in PRODUCTION + HELPERS)


def execute(code, assertion):
    result = subprocess.run(["node"], input=code + """
const assert=require('node:assert/strict');
const state=new Proxy({}, {get(){throw Error('live state accessed');},set(){throw Error('live state mutated');}});
const postJson=()=>{throw Error('live POST called');};
const fetchJson=()=>{throw Error('live GET called');};
const keepAlive=setTimeout(()=>{console.error('replay did not settle');process.exit(1);},5000);
(async()=>{ """ + assertion + """ })().then(()=>clearTimeout(keepAlive)).catch(e=>{clearTimeout(keepAlive);console.error(e);process.exitCode=1;});
""", text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_workflow_replays_use_production_functions_with_isolated_effects():
    execute(source(), """
assert.equal((await diagnosticAdvancedAssistantReplay()).status,'warning');
assert.equal((await diagnosticAdvancedLivingReplay()).status,'passed');
assert.equal((await diagnosticAdvancedIntelligenceReplay()).status,'warning');
""")


@pytest.mark.parametrize(("original", "broken", "helper", "message"), [
    ('if (!input || state.agentBusy) return;', 'if (!input) return;', 'Assistant', 'duplicate busy'),
    ('project_id: projectId(),', 'project_id: "wrong",', 'Assistant', 'selected project'),
    ('response,\n          receivedAt:', 'response: {},\n          receivedAt:', 'Assistant', 'evidence response'),
    ('packet_sha256: packet.sha256,', 'packet_sha256: "wrong",', 'Living', 'packet/hash'),
    ('attempt_sha256: attempt.sha256,', 'attempt_sha256: "wrong",', 'Living', 'attempt/packet'),
    ('if (state.livingActionBusy) return;', 'if (false) return;', 'Living', 'busy guard'),
])
def test_replay_detects_real_handler_regression(original, broken, helper, message):
    code = source()
    assert original in code
    execute(code.replace(original, broken, 1),
            f"await assert.rejects(diagnosticAdvanced{helper}Replay(), e=>e.message.includes({message!r}));")
