from __future__ import annotations

from tools.scout_ai_failure_review import build_failure_review


def test_failure_review_preserves_trace_answer_and_continuation() -> None:
    case_id = "workspace-032"
    source_refs = [
        "candidates/route_mileage_k_anchors.json",
        "candidates/checkpoints.json",
    ]
    deterministic_report = {
        "samples": [
            {
                "case_id": case_id,
                "question": "15K 座標與最近 CP？",
                "expected_operations": ["filter", "nearest"],
                "expected_artifact_keys": ["route_mileage", "checkpoints"],
                "returned_source_refs": source_refs,
                "deterministic_fact_grade": {"passed": True},
                "responses": [
                    {
                        "results": [
                            {
                                "source_ref": source_refs[0],
                                "data": {
                                    "normalized_mileage_k": "15K",
                                    "lat": 24.034234788,
                                    "lon": 121.280180449,
                                },
                            }
                        ]
                    },
                    {
                        "results": [
                            {
                                "source_ref": source_refs[1],
                                "data": {
                                    "candidate_id": "cp.128",
                                    "distance_m": 268.21364698744236,
                                },
                            }
                        ]
                    },
                ],
            }
        ]
    }
    live_report = {
        "model": "openrouter:cohere/north-mini-code:free",
        "samples": [
            {
                "case_id": case_id,
                "error": "model_run_UsageLimitExceeded",
                "l5_attempt_count": 2,
                "l5_attempt_receipts": [{"status": "fail_closed"}],
                "l5_semantic_grade": {"failed_assertions": ["nearest"]},
            }
        ],
    }

    review = build_failure_review(
        case_id=case_id,
        live_reports=[live_report],
        deterministic_report=deterministic_report,
        additional_models=["openrouter:poolside/laguna-m.1:free"],
    )

    assert review["codex_review"]["primary_root_cause"] == "Model Weakness"
    assert "cp.128" in review["candidate_answer"]
    assert review["known_issue"] is None
    assert review["continuation"]["status"] == "checkpointed"
    assert review["continuation"]["checkpoint_refs"] == source_refs
    assert "fresh 10/10" in review["continuation"]["resume_condition"]
