# Agent instructions — streak-app

- This is the Streak mobile app. Read the latest `docs/handoff-*.md` before
  you start.
- Check-ins are append-only: never delete one in sync code.
- The free tier limit lives in `src/limits.ts` (`FREE_HABITS = 3`).
- Prices are not hard-coded in the app; they come from the stores.
- Run the test suite before handing back, and say what you did not test.
- Do not commit, tag or release. Lucía does that.
