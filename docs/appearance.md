# Appearance

Porcelain, Conservatory, Atelier and Midnight are available throughout the app.
New users choose a look as the first setup step; existing users use Settings →
Appearance. Porcelain is the default. Onboarding previews each look immediately
on selection and saves it on Continue. In Settings, selection does not change
the app's appearance until Save. JavaScript is optional; without it, onboarding
also applies the look on Continue.

The preference is a validated, HTTP-only, SameSite=Lax cookie, lasting one year.
It is local to this browser, not synchronized between devices. Demo and real
installations use separate cookie names. Clearing browser cookies resets the look.
The server renders the selected theme on `<html>` before loading CSS, so a saved
dark theme does not first render light. Login retains the preference after logout.
Setup separately records that the appearance step is complete in its encrypted
draft, without creating a profile or granting permission to send.

`src/erasure/appearance.py` defines the four allowed choices. `static/themes.css`
holds palette/type/radius tokens and the shared component adapters for existing
styles. Base, login and setup templates load it last. Changing a theme never
selects different content, templates, workflow routes or broker records. Broker
size claims, units, outcomes and sources remain identical. Colors for success,
attention, errors and processing remain distinct in every palette. No remote
fonts, trackers or assets are added.

The temporary `/design-preview` gallery remains isolated: its local-storage
choice does not silently change the app. Its instructions link to Appearance.

Tests cover authorization/CSRF, invalid choices, browser persistence, unchanged
database state, resume and start consent, full setup with/without JavaScript, and
Chromium/WebKit rendering of every theme on dashboard, request tabs, settings,
forms and library at mobile/intermediate/desktop widths. Semantic foreground/
background pairs must meet 4.5:1 contrast.
