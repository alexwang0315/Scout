# Phase 2 Artifact ID Convention

Phase 2 Brain artifacts use deterministic file-backed node IDs. Remote-status
JSON artifacts must use one stable ID shape regardless of whether the artifact
was seeded from a fixture or generated during replay.

## Remote-Status JSON IDs

Remote-status JSON artifact IDs use:

```text
artifact.remote_status_json.<mission_or_timestamp>
```

The suffix is a sanitized mission or timestamp token derived from the related
`RemoteStatusArtifact` ID. For example:

- `remote_status.20260513T100000` becomes
  `artifact.remote_status_json.20260513T100000`
- `remote_status.ridge_loop_20260513T100800` becomes
  `artifact.remote_status_json.ridge_loop_20260513T100800`

The artifact kind remains `remote_status_json`. Do not encode whether an
artifact is a fixture or generated replay output by changing the artifact kind
or by dropping `_json` from the artifact ID prefix.

## Origin Metadata

Fixture-vs-generated origin belongs in artifact metadata, not in the ID shape.
Generated persisted remote-status JSON artifacts set:

```json
{"artifact_origin":"generated","remote_status_ref":"<remote_status_id>"}
```

Fixture artifacts may keep their existing IDs, such as
`artifact.remote_status_json.20260513T100800`, and can add origin metadata later
without changing references.

## Compatibility Rule

Phase 1 safety runtime behavior is not part of this convention. This rule only
applies to Phase 2 Brain artifact node IDs and persisted remote-status JSON
files.

## Runtime Enforcement

Phase 2 artifact manifest generation validates every `remote_status_json`
Artifact ID before emitting a manifest. Generated persisted remote-status JSON
files under `artifacts/remote-status/` must also carry
`{"artifact_origin":"generated"}` metadata. Fixture artifacts are not renamed by
this validation path.
