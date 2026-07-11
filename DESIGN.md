# Scout Fusion Design System

## 1. Atmosphere & Identity

Scout is a quiet field-operations console: dense, direct, and evidence-first. Its
signature is restrained dark instrumentation with cyan interaction cues and
explicit status language. Safety, provenance, and failure state must remain
visible without turning the interface into a marketing surface.

## 2. Color

The dashboard is dark-only. Tokens are extracted from
`docs/admin/scout-dashboard-v0.1.html`.

| Role | Token | Value | Usage |
|---|---|---|---|
| Background | `--bg` | `#11161a` | Application canvas |
| Surface | `--surface` | `#161d22` | Header and primary panels |
| Surface secondary | `--surface-2` | `#1d252b` | Controls and messages |
| Surface tertiary | `--surface-3` | `#253039` | Selected or raised content |
| Border | `--line` | `#33404a` | Dividers and outlines |
| Border strong | `--line-strong` | `#4a5b67` | Emphasized boundaries |
| Text | `--text` | `#edf3f5` | Primary content |
| Text muted | `--muted` | `#a8b5bd` | Metadata and secondary labels |
| Text subtle | `--subtle` | `#75858f` | Disabled and tertiary text |
| Accent | `--accent` | `#62b5c4` | Interaction and focus |
| Accent secondary | `--accent-2` | `#bba15e` | Secondary emphasis |
| Success | `--ok` | `#78bf75` | Healthy and completed state |
| Warning | `--warn` | `#d5a642` | Review-needed state |
| Error | `--bad` | `#d06363` | Failure and rejected state |
| Candidate | `--candidate` | `#8fb7d7` | Candidate evidence |
| Reviewed | `--reviewed` | `#7fc18b` | Human-reviewed evidence |

New colors must first be added here and then exposed as CSS custom properties.
Accent colors are semantic, not decorative.

## 3. Typography

| Level | Size | Weight | Line height | Usage |
|---|---:|---:|---:|---|
| Page heading | 18px | 700 | 1.2 | Main dashboard view title |
| Panel heading | 17px | 700 | 1.2 | Sidebar brand and major panel titles |
| Body | 14px | 400 | 1.45 | Default UI and conversation text |
| Body strong | 14px | 700 | 1.45 | Labels and evidence emphasis |
| Metadata | 12px | 500 | 1.45 | Status, model, latency, provenance |

- Sans: `ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`
- Mono: `ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`
- Letter spacing is `0`.
- Conversation text may wrap naturally; metadata may use mono.

## 4. Spacing & Layout

The base unit is 4px. Existing spacing maps to multiples or near multiples of
that unit: 4, 8, 12, 16, 20, 24, 32, and 40px. The desktop dashboard uses a
272px navigation rail and a `minmax(0, 1fr)` work area. Full-page surfaces use
the viewport without body scrolling; the active work frame owns overflow.

- Compact inline gap: 4-8px
- Control padding: 8-12px
- Message and panel padding: 12-16px
- Section padding: 16-24px
- Major separation: 32-40px
- Responsive breakpoints: 640, 768, 1024, and 1280px

## 5. Components

### Navigation Item

- Structure: button with a compact status mark and one-line label.
- States: default, hover, focus-visible, active, disabled.
- Spacing: 8px internal rhythm; labels truncate rather than resize layout.
- Accessibility: semantic button and visible focus border.

### Status Chip

- Structure: short semantic label with optional model or readiness metadata.
- Variants: neutral, healthy, warning, error, candidate, reviewed.
- Accessibility: color is reinforced by text; status is never color-only.

### Agent Message

- Structure: answer text followed by compact provenance and runtime metadata.
- Variants: user, model answer, deterministic safety fallback, system failure.
- States: pending, complete, grounding-failed, disconnected.
- Contract: a rejected model output is shown as untrusted diagnostic text; the
  accepted user-facing answer and its source must be labeled separately.
- Accessibility: preserved line breaks, readable wrap, and no fixed content
  height.

### Agent Runtime Toggle

- Structure: native checkbox with visible label.
- States: unchecked cloud mode, checked AI HAT+2 request, disabled/unavailable.
- Accessibility: label remains associated with the native control.

## 6. Motion & Interaction

| Type | Duration | Easing | Usage |
|---|---:|---|---|
| Micro | 120ms | ease-out | Button, focus, and toggle feedback |
| Standard | 240ms | ease-in-out | Panel and tab state changes |

Only `transform`, `opacity`, and color/border transitions may animate. Respect
`prefers-reduced-motion`. Every interactive control must expose hover,
focus-visible, active, disabled, and pending behavior where applicable.

## 7. Depth & Surface

Strategy: borders-only. Surfaces are separated by tokenized tonal changes and
1px borders. Do not introduce decorative shadows, gradients, or floating page
sections. Individual repeated items and functional panels may be framed; page
sections remain part of the work surface.
