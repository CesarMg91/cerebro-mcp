---
name: Release process
description: How to cut a beta build of streak-app
metadata:
  type: reference
---
1. Bump the version in `app.config.ts`.
2. Add an entry to `docs/CHANGELOG.md`.
3. Tag `vX.Y.Z`; CI builds both platforms and uploads them to the beta channel.
4. Smoke test in UTC+9 and UTC-10 (the midnight rollover bug lives there).

Never ship on a Friday. The full list is in `docs/release-checklist.md`.
