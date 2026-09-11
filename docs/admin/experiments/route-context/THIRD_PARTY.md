# Third-Party Assets

This isolated experiment uses the existing tracked MapLibre GL JS 6.2.0 under
`docs/admin/vendor/maplibre-gl/6.2.0`, including its BSD license. No shared vendor
file or production dependency manifest was changed.

Lucide 0.468.0 is vendored only for this page:

- Distribution: https://cdn.jsdelivr.net/npm/lucide@0.468.0/dist/umd/lucide.min.js
- License: https://cdn.jsdelivr.net/npm/lucide@0.468.0/LICENSE
- Documentation: https://lucide.dev/guide/lucide
- Local license: `LUCIDE-LICENSE.txt` (ISC).
- JS SHA-256: `3411692820cb8d47543f69496aa25fd603a358f4498046f41c508a5a3342210e`.
- License SHA-256: `1e7290b35280a048667bbf0ebabac1c7fd52a75300e8b2946ac165715997f2bc`.

Map images remain in the explicitly selected workspace, not in this repository.
Provider attribution is read from each existing tile manifest and displayed next
to the map. Those source licenses are not replaced by the code's license. This
local demonstration does not grant redistribution or public-hosting permission.
No remote tile requests or third-party image downloads occur in the browser.
