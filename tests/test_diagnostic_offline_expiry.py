"""Actual offline sync service in disposable workspaces; no live effects."""
from datetime import timedelta
import json

import pytest
from test_scout_contextual_permission_workbench import (
    NOW, _workspace, ContextualPermissionWorkbench, OfflineEmergencyReviewIntent,
)


@pytest.mark.parametrize('case', ['fresh', 'exact_expiry', 'expired', 'unknown', 'generation', 'hash'])
def test_offline_sync_freshness_receipt_boundary(tmp_path, case):
    project, store = _workspace(tmp_path)
    if case == 'unknown':
        path = project / 'outputs/contextual_permission/workbench_seed.json'
        seed = json.loads(path.read_text())
        seed['daily_review']['alternatives'][0]['freshness_inputs'][0]['valid_until'] = None
        path.write_text(json.dumps(seed))
    clock = [NOW]
    workbench = ContextualPermissionWorkbench(project_root=project, store_root=store, now_factory=lambda: clock[0])
    packet = workbench.daily_emergency_review('D1.instance.001').alternatives[0]
    intent = OfflineEmergencyReviewIntent(
        intent_id='diagnostic-expiry', idempotency_key='diagnostic-expiry',
        packet_id=packet.packet_id, packet_sha256=packet.sha256,
        mission_day_instance_id=packet.mission_day_instance_id,
        review_generation=packet.review_generation, reviewed_sequence=packet.reviewed_sequence,
        decision='select_hold_or_bivy', reviewer_alias='fixture', device_instance_id='fixture', pending_sync=True,
    )
    if case in {'exact_expiry', 'expired'}:
        clock[0] = packet.expires_at + timedelta(seconds=case == 'expired')
    elif case == 'generation':
        intent = intent.model_copy(update={'review_generation': packet.review_generation + 1})
    elif case == 'hash':
        intent = intent.model_copy(update={'packet_sha256': '0' * 64})
    result = workbench.sync_offline_intent(intent)
    assert result.runtime_authorization_performed is False
    assert result.outbound_action_performed is False
    if case == 'fresh':
        assert result.status == 'receipt_appended'
        assert result.receipt_ref
    else:
        assert result.status == 'rejected_sync_audit'
        assert result.receipt_ref is None and result.receipt_sha256 is None
        assert result.audit_ref
        events = workbench._load_group_events(packet.movement_group_id)
        matching = [event for event in events if event.idempotency_key == intent.idempotency_key]
        assert len(matching) == 1
        assert matching[0].event_kind == 'offline_intent_sync_rejected'
        assert matching[0].payload['canonical_receipt_appended'] is False
        assert result.reasons[0] in {'packet_expired', 'packet_ineligible', 'packet_replaced', 'packet_invalidated'}
        repeated = workbench.sync_offline_intent(intent)
        assert repeated.status == 'rejected_sync_audit'
        assert repeated.receipt_ref is None
        assert len(workbench._load_group_events(packet.movement_group_id)) == len(events)
