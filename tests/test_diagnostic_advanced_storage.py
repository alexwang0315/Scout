"""Exercise production storage functions through isolated Diagnostic replays."""
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "docs/admin/scout-diagnostic-advanced.js"
HTML = ROOT / "docs/admin/scout-dashboard-v0.1.html"


def production_sources():
    html = HTML.read_text()
    names = ["emergencyOfflineEncryptionKey", "storeEncryptedEmergencyIntent", "decryptEmergencyOfflineRecord", "refreshEmergencyOfflineIntentCount", "validateDashboardSettings", "saveDashboardSettings"]
    sources = {}
    for name in names:
        match = re.search(r"^    (?:async )?function " + name + r"\(.*?^    }", html, re.M | re.S)
        assert match, name
        sources[name] = match.group(0).strip()
    return sources


def replay(extra=""):
    script = f"""
const fs = require('node:fs');
globalThis.crypto = require('node:crypto').webcrypto;
(0, eval)(fs.readFileSync({json.dumps(str(MODULE))}, 'utf8'));
const sources = {json.dumps(production_sources())};
{extra}
(async () => {{
const storage = await ScoutDiagnosticAdvanced.runStorage({{sources}});
const settings = await ScoutDiagnosticAdvanced.runSettings({{sources}});
console.log(JSON.stringify({{storage, settings}}));
}})().catch(error => {{console.error(error.message); process.exit(1);}});
"""
    return subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, timeout=30)


def test_production_replay_crypto_settings_and_current_project_gap():
    result = replay()
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert {c["id"]: c["status"] for c in payload["settings"]["checks"]}["partialWriteRollback"] == "passed"
    assert {c["id"]: c["status"] for c in payload["settings"]["checks"]}["invalidRejected"] == "passed"
    checks = {c["id"]: c["status"] == "passed" for c in payload["storage"]["checks"]}
    assert checks["encryptedSaveReadback"] and checks["corruptionRejected"]
    assert checks["intentBindingRejected"] and checks["nonExtractableKey"]
    # The Diagnostic must expose the actual cross-project overlay behavior, not
    # pretend that an injected isolation policy is production evidence.
    assert checks["projectOverlayIsolation"]
    assert payload["storage"]["status"] == "warning"
    assert not payload["storage"]["userStorageTouched"]
    assert payload["storage"]["networkRequests"] == 0
    assert any("expiry" in text for text in payload["storage"]["limitations"])


def test_probe_rejects_readback_corruption_regression():
    result = replay("sources.decryptEmergencyOfflineRecord = 'async function decryptEmergencyOfflineRecord(database, record) { return {}; }';")
    assert result.returncode != 0
    assert "readback differs" in result.stderr


def test_probe_rejects_lost_settings_rollback():
    result = replay("sources.saveDashboardSettings = sources.saveDashboardSettings.replace('localStorage.setItem(\"scout.dashboardApiBase\", previousApi);', 'void previousApi;');")
    assert result.returncode != 0
    assert "not rolled back" in result.stderr


def test_storage_probe_reports_cross_project_overlay_instead_of_green():
    result = replay("sources.refreshEmergencyOfflineIntentCount = 'async function refreshEmergencyOfflineIntentCount() { state.emergencyOfflineFieldOverlay = {same_group: {pending_sync: true}}; }';")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)["storage"]
    assert payload["status"] == "failed"
    assert {c["id"]: c["status"] for c in payload["checks"]}["projectOverlayIsolation"] == "failed"
    assert any("Cross-project" in finding for finding in payload["findings"])
