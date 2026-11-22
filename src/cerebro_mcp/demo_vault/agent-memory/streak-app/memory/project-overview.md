---
name: Project overview
description: What Streak is, the stack, the current version and the launch date
metadata:
  type: project
---
Streak is Lucía's habit tracker (iOS and Android, one codebase). Offline-first:
the local SQLite file is the source of truth; sync is optional and Pro-only.

- **Current version: 0.8.5** (beta channel).
- **Launch date: December 1, 2026.**
- Free tier: 3 habits (`FREE_HABITS = 3` in `src/limits.ts`).

**Why:** she wants the app to work with zero network, and she has seen people
lose streaks to sync bugs in other apps.

**How to apply:** never write sync code that deletes a check-in; sync only adds.

_Last updated: 2026-08-21._
