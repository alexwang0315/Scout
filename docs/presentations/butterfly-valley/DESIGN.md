# Butterfly Valley Briefing Design System

## 1. Atmosphere & Identity

This presentation should feel like a field safety briefing beside a shaded creek: cool, alert, and practical. The signature is a split between forest calm and closure discipline, using contour lines, stream bands, and decision charts to make route status impossible to miss.

## 2. Color

### Palette

| Role | Token | Light | Dark | Usage |
|------|-------|-------|------|-------|
| Surface/primary | --surface-primary | #F3F0E7 | #14201D | Main background |
| Surface/secondary | --surface-secondary | #E5E1D2 | #1D2B27 | Slide bands and chart grounds |
| Surface/elevated | --surface-elevated | #FFFDF5 | #273833 | Panels and route cards |
| Text/primary | --text-primary | #152722 | #F8F3E6 | Headings and body |
| Text/secondary | --text-secondary | #546961 | #C5D3CD | Secondary copy |
| Text/tertiary | --text-tertiary | #74847E | #91A39B | Captions and metadata |
| Border/default | --border-default | #C7B993 | #55665E | Main outlines |
| Border/subtle | --border-subtle | #DED2AE | #3B4C45 | Soft dividers |
| Accent/primary | --accent-primary | #C0603F | #E79A78 | Route marks and active controls |
| Accent/forest | --accent-forest | #497D62 | #87C6A5 | Forest, safe route, open option |
| Accent/water | --accent-water | #477A8E | #8DC4D6 | Creek and waterfall visuals |
| Accent/sun | --accent-sun | #C79B34 | #E2C45D | Timing and daylight |
| Status/closed | --status-closed | #A23E34 | #E2766D | Closure and no-go |
| Status/warning | --status-warning | #996B18 | #E0BD5B | Caution and unstable terrain |
| Status/info | --status-info | #3E6F8F | #8DBADA | Official data and logistics |

### Rules

- Closure status must use `--status-closed` and be visually dominant.
- Water and forest colors are descriptive, not decorative.
- No purple-blue gradients or neon effects.

## 3. Typography

### Scale

| Level | Size | Weight | Line Height | Tracking | Usage |
|-------|------|--------|-------------|----------|-------|
| Display | 48px | 800 | 1.08 | 0 | Title slide |
| H1 | 40px | 760 | 1.12 | 0 | Slide titles |
| H2 | 28px | 720 | 1.25 | 0 | Section headers |
| H3 | 20px | 700 | 1.35 | 0 | Panel titles |
| Body/lg | 18px | 450 | 1.65 | 0 | Lead paragraphs |
| Body | 16px | 430 | 1.65 | 0 | Default text |
| Body/sm | 14px | 440 | 1.5 | 0 | Supporting copy |
| Caption | 12px | 650 | 1.4 | 0 | Labels and tags |

### Font Stack

- Primary: Noto Sans TC, PingFang TC, Microsoft JhengHei, system-ui, sans-serif
- Mono: SFMono-Regular, Menlo, Consolas, monospace
- Serif: Not used

### Rules

- Keep Chinese letter spacing at 0.
- Body text remains at least 14px.
- Use weight and spacing rather than huge type.

## 4. Spacing & Layout

### Base Unit

All spacing derives from a base of 4px.

| Token | Value | Usage |
|-------|-------|-------|
| --space-1 | 4px | Compact inline gaps |
| --space-2 | 8px | Tags and controls |
| --space-3 | 12px | Dense list rhythm |
| --space-4 | 16px | Default blocks |
| --space-5 | 20px | Panel inner padding |
| --space-6 | 24px | Slide groups |
| --space-8 | 32px | Major content groups |
| --space-10 | 40px | Header to content |
| --space-12 | 48px | Slide separation |
| --space-16 | 64px | Large slide breathing room |

### Grid

- Max content width: 1240px
- Column system: 12-column desktop grid, single-column mobile collapse
- Breakpoints: sm 640px, md 768px, lg 1024px, xl 1280px

### Rules

- Route schematics and charts require stable aspect ratios.
- Mobile must not have horizontal overflow.
- Do not nest cards inside cards.

## 5. Components

### Slide
- Structure: one `section.slide` with heading, content grid, and optional visual panel.
- Variants: hero, status, route, matrix, sources.
- Spacing: `--space-8` to `--space-16`.
- States: active shown, inactive hidden.
- Accessibility: slide labelled by heading.
- Motion: opacity and transform only.

### Status Tag
- Structure: compact evidence label with explicit status text.
- Variants: closed, official, open, warning.
- Spacing: `--space-1` and `--space-3`.
- States: focus visible for linked sources.
- Accessibility: status text is not color-only.
- Motion: micro transition only.

### Chart Panel
- Structure: heading, small metric label, inline SVG or CSS chart, one takeaway sentence.
- Variants: route schematic, pressure bars, season heatmap, decision matrix.
- Spacing: `--space-4` to `--space-6`.
- States: static with hover border clarity.
- Accessibility: `aria-label` plus text takeaway.
- Motion: no animated chart values.

### Observation Row
- Structure: location, context layer, pause reason, go/no-go note.
- Variants: stop, pass-fast, closed.
- Spacing: `--space-3` and `--space-4`.
- States: hover highlights row boundary.
- Accessibility: semantic table when tabular.
- Motion: micro transition only.

## 6. Motion & Interaction

### Timing

| Type | Duration | Easing | Usage |
|------|----------|--------|-------|
| Micro | 120ms | ease-out | Button press |
| Standard | 240ms | ease-in-out | Slide entry |
| Emphasis | 480ms | cubic-bezier(0.16, 1, 0.3, 1) | Hero route reveal |

### Rules

- Animate only transform and opacity.
- Respect `prefers-reduced-motion`.
- Keyboard navigation supports ArrowLeft and ArrowRight.

## 7. Depth & Surface

### Strategy

Use mixed depth: borders for safety information, tonal surface shifts for route grouping, restrained shadows for active panels.

| Level | Value | Usage |
|-------|-------|-------|
| Subtle | 0 8px 24px rgba(21, 39, 34, 0.07) | Panels |
| Default | 0 20px 52px rgba(21, 39, 34, 0.12) | Hero visual |

Rules:

- No glow effects.
- Closure content gets border and color priority before shadow.
- Shadows are never used to imply an option is safe.
