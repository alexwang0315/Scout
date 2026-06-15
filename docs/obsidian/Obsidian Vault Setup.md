---
title: Obsidian Vault Setup
type: guide
scope: scout-docs
status: active
---

# Obsidian Vault Setup

## Recommended Setup

Open this directory as the Obsidian vault:

```text
/Users/alexwang0315/scout-fusion/docs
```

Start from:

```text
obsidian/Scout Index.md
```

This keeps the repository docs as the source of truth while giving Obsidian a
stable reading and knowledge-map layer.

## What To Use As Notes

Good Obsidian notes:

- `specs/*.md`
- `admin/*.md`
- `ideas/*.md`
- `case_studies/**/*.md`
- `obsidian/*.md`

Treat as attachments or generated artifacts:

- `admin/screenshots/**`
- `assets/**`
- `*.html`
- `*.json`
- `*.jsonl`
- `*.geojson`

## Ignore Guidance

`docs/.obsidianignore` lists generated and attachment-heavy paths that should
not dominate search or graph views. If the local Obsidian installation does not
honor that file directly, copy the same patterns into:

```text
Settings -> Files and links -> Excluded files
```

## Editing Rule

- Edit specs and runbooks in their original locations.
- Use MOC notes only as indexes, reading orders, and cross-topic maps.
- Do not paste raw PII, secrets, or full generated logs into Obsidian notes.
- Keep runtime truth in code/tests/fixtures, not in personal notes.

## Main Entry Points

- [[obsidian/Scout Index|Scout Index]]
- [[obsidian/Runtime MOC|Runtime MOC]]
- [[obsidian/Pretrip And Maps MOC|Pretrip And Maps MOC]]
- [[obsidian/Hardware MOC|Hardware MOC]]
- [[obsidian/Admin Runbooks MOC|Admin Runbooks MOC]]
- [[obsidian/AI Assistant And Skills MOC|AI Assistant And Skills MOC]]
- [[obsidian/Case Studies MOC|Case Studies MOC]]
