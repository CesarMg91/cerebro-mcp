---
name: Site stack
description: How the Streak site is built and deployed, and where the launch countdown points
metadata:
  type: project
---
- Static site: plain HTML, a little JavaScript, built by a small script.
  Deploys on every push to `main`.
- Pages: home, pricing, privacy, press.
- The countdown banner on the home page points at **2027-01-12** (launch day).

**How to apply:** if the launch date moves, change `LAUNCH_AT` in
`src/countdown.js` and the "Available January 12" line in both languages.

_Last updated: 2026-10-22._
