# example_scout_skill Telemetry Spec

## Event: scout_skill_invoked
Required fields:
- event_name
- skill_name
- skill_version
- schema_version
- request_id
- user_hash
- latency_ms
- success
- error_code
- risk_level
- hitl_required

## Privacy
- 不記錄 raw PII
- user identifier 必須 hash
- prompt/input 必須脫敏或只記 digest
