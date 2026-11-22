---
type: reference
date: 2026-07-12
tags: [sync, dev]
---
# Sync architecture

- The local SQLite file on the phone is the source of truth. The app works
  fully offline.
- Optional sync to a tiny server (one small database, one API process).
  Last-write-wins per habit-day.
- Conflict rule: sync never deletes a check-in, it only adds. Losing a streak
  to a sync bug would kill the app.
- Sync is a Pro feature.

- [x] Schema v3 with `checkins(habit_id, day, created_at)`
- [ ] Load test with 10k fake users

Back to [[Streak]].
