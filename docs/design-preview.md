# Temporary design studio

Open `/design-preview` after signing in. To apply a theme to the real app, use
**Settings → Appearance** (`/appearance`) or the Appearance shortcut on Home.

Four isolated, illustrative dashboard previews: Conservatory (deep green/parchment),
Porcelain (white/blue), Atelier (ivory/plum), and Midnight (ink/lilac). Typography, corner styles
and contrast vary; the information hierarchy and continuous pill navigation stay
consistent so the choices are comparable. Conservatory uses classic serif typography
and a compact outlined navigation pill, without background ornament or a navigation
tagline. Atelier uses book-like rules, ivory paper and plum accents.
Both use a single menu outline; Atelier has no divider below its menu.
Every preview reads broker sizes, units and source links from the same public
catalog as Home. Only the preview's progress counts and outcomes are illustrative;
switching styles never changes or hides the broker content.
Grove and Clay are retired; saved choices for either fall back to Conservatory.

**Choose this direction** saves only `erasure-design-preview-choice` in the current
browser’s local storage. It does not apply a live theme, call an API, access the
mailbox, alter account settings or send requests. All displayed outcomes are fake
examples, explicitly labelled. No external fonts, images or analytics are used.

To remove the studio, remove its route in `app.py`, and
`design_preview.html`, `design-preview.css` and
`design-preview.js`. The production pill navigation and compact dashboard are
independent in `base.html` and `app-layout.css`.
