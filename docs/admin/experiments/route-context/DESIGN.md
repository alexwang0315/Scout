# Route Context Field Atlas

Experimental, local-only interpretation of the root DESIGN.md. This page is
isolated from Dashboard Navigation and reads one explicitly selected workspace.

- Primary experience: an unframed historical-map / orthophoto comparison with
  the real bound GPX. A compact side panel holds stories, source references,
  culturally restricted place names, research readiness and local observations.
- Use the root dark instrumentation tokens, 4px spacing grid, system sans/mono,
  18px page heading, 14px body and 12px metadata. No hero, decorative cards,
  gradients, shadows or negative letter spacing.
- Desktop: flexible map plus 360px context column. Mobile: map above context;
  all controls remain operable without horizontal page scrolling.
- Visual assets: existing workspace tiles only. Historical map edition dates
  are not GPX dates; an orthophoto cache timestamp is not an acquisition date.
- Historical editions: gold. Recorded GPX: cyan. Human annotation classes:
  green, yellow, pink, blue and gray, always paired with text.
- Icons: locally vendored Lucide 0.468.0, ISC license. MapLibre navigation
  controls retain their own familiar symbols.
- All local drafts are explicit saves, unreviewed and not independent ground
  truth. Source evidence and model inference remain visibly separate.
- Restricted cultural coordinates are removed at the API boundary, not merely
  hidden in the interface. The historical closure snapshot is never presented
  as a freshly checked operational state.
- Verification: real cached raster rendering, comparison changes, public place
  selection, independent local draft save/export/delete, desktop/mobile layout,
  reload persistence, no external browser requests and no workspace writes.
