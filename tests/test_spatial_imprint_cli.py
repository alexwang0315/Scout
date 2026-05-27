from __future__ import annotations

import json

from spatial_imprint_cli import run_spatial_imprint_cli
from tests.test_spatial_imprint_trigger import _context, _imprint


def test_trigger_dry_run_cli_outputs_json_report(tmp_path) -> None:
    imprint_set_path = tmp_path / "spatial_imprint_set.json"
    context_path = tmp_path / "trigger_context.json"
    imprint_set_path.write_text(
        json.dumps(
            {
                "artifact_kind": "spatial_imprint_set",
                "trip_id": "chilai_nanhua_day1",
                "imprints": [_imprint().model_dump(mode="json")],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    context_path.write_text(
        _context().model_dump_json(),
        encoding="utf-8",
    )

    exit_code, payload = run_spatial_imprint_cli(
        [
            "trigger-dry-run",
            "--imprint-set",
            str(imprint_set_path),
            "--context",
            str(context_path),
        ]
    )

    assert exit_code == 0
    assert payload["artifact_kind"] == "spatial_imprint_trigger_dry_run"
    assert payload["counts"]["triggered"] == 1
    assert payload["events"][0]["queued_payload"]["payload_type"] == "voice_cue"
    assert payload["boundary"]["phase1_safety_mutation_allowed"] is False


def test_trigger_dry_run_cli_reports_validation_errors(tmp_path) -> None:
    imprint_set_path = tmp_path / "bad.json"
    context_path = tmp_path / "trigger_context.json"
    imprint_set_path.write_text("{}", encoding="utf-8")
    context_path.write_text(_context().model_dump_json(), encoding="utf-8")

    exit_code, payload = run_spatial_imprint_cli(
        [
            "trigger-dry-run",
            "--imprint-set",
            str(imprint_set_path),
            "--context",
            str(context_path),
        ]
    )

    assert exit_code == 2
    assert payload["status"] == "error"
    assert payload["live_safety_api_calls_allowed"] is False
