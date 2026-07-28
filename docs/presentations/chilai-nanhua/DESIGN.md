# Chilai Nanhua Briefing Design System

## 1. Atmosphere & Identity

This presentation should feel like a field briefing for a mountain team: calm, precise, and grounded in terrain. The signature is a layered contour motif, using route lines, elevation bands, and compact evidence labels to make the hike feel legible before anyone steps on trail.

## 2. Color

### Palette

| Role | Token | Light | Dark | Usage |
|------|-------|-------|------|-------|
| Surface/primary | --surface-primary | #F7F3EA | #17211C | Main slide background |
| Surface/secondary | --surface-secondary | #EFE8D7 | #213028 | Section bands and quiet panels |
| Surface/elevated | --surface-elevated | #FFFDF6 | #2B3A31 | Route details and repeated items |
| Text/primary | --text-primary | #1A2B24 | #F8F3E7 | Headlines and body |
| Text/secondary | --text-secondary | #586B61 | #C6D3CA | Secondary body |
| Text/tertiary | --text-tertiary | #7C8B82 | #91A197 | Captions and metadata |
| Border/default | --border-default | #CDBF9D | #526359 | Slide separators |
| Border/subtle | --border-subtle | #E1D6B8 | #3B4A42 | Soft separations |
| Accent/primary | --accent-primary | #B45D35 | #E59D73 | Active controls and route marks |
| Accent/secondary | --accent-secondary | #4F7F71 | #8EC7B5 | Nature and safe observation marks |
| Accent/tertiary | --accent-tertiary | #D4A63A | #E6C66C | Sunrise and grassland emphasis |
| Status/warning | --status-warning | #9A6A16 | #E0BC58 | Caution and exposed terrain |
| Status/error | --status-error | #A23E34 | #E0786F | Avoid-stopping warnings |
| Status/info | --status-info | #3E6F8F | #8DBBDA | Permit and logistics notes |

### Rules

- Use warm alpine neutrals as the base and reserve accents for meaning.
- Route, summit, and warning colors must come from the semantic accent tokens.
- Do not add decorative purple, blue-violet, or neon gradients.

## 3. Typography

### Scale

| Level | Size | Weight | Line Height | Tracking | Usage |
|-------|------|--------|-------------|----------|-------|
| Display | 48px | 800 | 1.08 | 0 | Title slide |
| H1 | 40px | 760 | 1.12 | 0 | Slide titles |
| H2 | 28px | 720 | 1.25 | 0 | Section headers |
| H3 | 20px | 700 | 1.35 | 0 | Item titles |
| Body/lg | 18px | 450 | 1.65 | 0 | Lead paragraphs |
| Body | 16px | 430 | 1.65 | 0 | Main text |
| Body/sm | 14px | 440 | 1.5 | 0 | Supporting copy |
| Caption | 12px | 650 | 1.4 | 0 | Labels and source tags |

### Font Stack

- Primary: Noto Sans TC, PingFang TC, Microsoft JhengHei, system-ui, sans-serif
- Mono: SFMono-Regular, Menlo, Consolas, monospace
- Serif: Not used

### Rules

- Use clear hierarchy through weight and spacing, not oversized type.
- Body text must remain at least 14px.
- Keep letter spacing at 0 for Chinese readability.

## 4. Spacing & Layout

### Base Unit

All spacing derives from a base of 4px.

| Token | Value | Usage |
|-------|-------|-------|
| --space-1 | 4px | Compact inline gaps |
| --space-2 | 8px | Tags and small controls |
| --space-3 | 12px | Dense list rhythm |
| --space-4 | 16px | Default block spacing |
| --space-5 | 20px | Panel inner padding |
| --space-6 | 24px | Slide group gaps |
| --space-8 | 32px | Major groups |
| --space-10 | 40px | Slide header to content |
| --space-12 | 48px | Section separation |
| --space-16 | 64px | Large slide breathing room |

### Grid

- Max content width: 1240px
- Column system: 12-column desktop grid with single-column mobile collapse
- Breakpoints: sm 640px, md 768px, lg 1024px, xl 1280px

### Rules

- Use CSS grid for route and context comparisons.
- Fixed-format route diagrams need stable aspect ratios.
- Mobile must collapse to one column without horizontal scrolling.

## 5. Components

### Slide
- Structure: `section.slide` with a header region and one content grid.
- Variants: hero, route, matrix, sources.
- Spacing: `--space-8` to `--space-16`.
- States: active slide is shown, inactive slides are hidden.
- Accessibility: each slide is labelled by its heading and navigation buttons expose text labels.
- Motion: opacity and transform only.

### Evidence Tag
- Structure: short inline source marker.
- Variants: official, field-report, dynamic.
- Spacing: `--space-1` and `--space-2`.
- States: hover and focus show clear outline on linked sources.
- Accessibility: never use color as the only meaning.
- Motion: micro transition only.

### Observation Row
- Structure: location, context layer, why to pause, caution.
- Variants: stop, pass-fast, optional.
- Spacing: `--space-3` and `--space-4`.
- States: hover highlights row background.
- Accessibility: semantic table for matrix slide.
- Motion: micro transition only.

### Chart Panel
- Structure: panel heading, optional evidence label, inline SVG or CSS chart, concise reading note.
- Variants: elevation profile, workload bars, context radar, season heatmap.
- Spacing: `--space-4` to `--space-6`.
- States: static by default; hover only clarifies panel boundary.
- Accessibility: every chart needs an `aria-label` plus a text note that states the takeaway.
- Motion: no animated chart values; slide entry handles motion.

## 6. Motion & Interaction

### Timing

| Type | Duration | Easing | Usage |
|------|----------|--------|-------|
| Micro | 120ms | ease-out | Button press |
| Standard | 240ms | ease-in-out | Slide entry |
| Emphasis | 480ms | cubic-bezier(0.16, 1, 0.3, 1) | Hero contour reveal |

### Rules

- Animate only `transform` and `opacity`.
- Respect `prefers-reduced-motion`.
- Keyboard navigation must support ArrowLeft and ArrowRight.

## 7. Depth & Surface

### Strategy

Use mixed depth: subtle borders for structure, tonal shifts for slide bands, and one restrained shadow token for active panels.

| Level | Value | Usage |
|-------|-------|-------|
| Subtle | 0 8px 24px rgba(26, 43, 36, 0.07) | Repeated item panels |
| Default | 0 20px 52px rgba(26, 43, 36, 0.12) | Hero visual block |

Rules:

- Avoid nested cards.
- Use borders and route-line graphics before adding shadow.
- Shadows are never glow effects.
