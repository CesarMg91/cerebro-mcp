---
type: checklist
date: 2026-09-01
---
# Release checklist

Copy this list into the release issue and tick it there.

- [ ] Bump the version in `app.config.ts`
- [ ] Update `docs/CHANGELOG.md`
- [ ] Tag `vX.Y.Z`; CI uploads both builds to the beta channel
- [ ] Smoke test: create a habit, check in, kill the app, reopen, streak intact
- [ ] Smoke test with the device set to UTC+9 and to UTC-10
- [ ] It is not Friday
