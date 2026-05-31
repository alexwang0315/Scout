# Scout Case Studies

This directory stores Scout case-study review artifacts that sit above runtime fixtures and below formal Phase 1/2 spec patches.

Case-study drafts preserve source provenance, short evidence quotes, normalized `sidecar.json` data, Scout taxonomy keys, and discussion prompts. They are not runtime MissionGraph, route-progress, or Phase 2 team replay fixtures.

## Layout

```text
docs/case_studies/
  drafts/<case_slug>/
    draft.md
    sidecar.json
  accepted/
  sources/
```

## Promotion Rule

Keep accepted case studies separate from Phase 1 and Phase 2 specs until a human explicitly approves promotion. A case-study finding can support a later spec patch, but it must not silently change Scout runtime behavior or safety thresholds.

## Validation

Use the Scout case-study skill validator before accepting a draft:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python \
  /Users/alexwang0315/.codex/skills/Scout_case-study-addition/scripts/validate_sidecar.py \
  docs/case_studies/drafts/<case_slug>/sidecar.json
```
