# Demo vault

Everything here is fictional. Lucía is a solo builder making **Streak**, a
habit tracker. She writes notes in English and Spanish, works with coding
agents on two repos (`streak-app`, `streak-web`), and, like everyone, forgot to
tell her agents when a decision changed.

`cerebro demo` copies this folder to a temp dir, indexes it with
`cerebro.toml` and prints the contradictions it finds. This file sits outside
every source, so it is not indexed.

## Layout

| Folder | Source kind | Scope |
|---|---|---|
| `notes/` | `vault` | personal |
| `agent-memory/<project>/memory/` | `claude-code-memory` | work |
| `repo-docs/<repo>/docs/`, `repo-docs/<repo>/AGENTS.md` | `glob` | work |

## Planted facts

What the newest sources say (the "truth" as of 2026-11-18):
Pro is **$5.99/month** or **$39/year**, with a **14-day trial**, **no ads**,
launch **2027-01-12**, current version **0.9.3**.

| Topic | Stale value | Where | Current value | Where |
|---|---|---|---|---|
| Monthly price | $4.99 | `notes/Ideas/Monetization brainstorm.md`, `agent-memory/streak-app/memory/monetization.md`, `agent-memory/streak-web/memory/pricing.md` | $5.99 | `notes/Decisions/2026-09-14 Precio y anuncios.md`, `notes/Marketing/Landing copy.md`, `notes/Dev/Payments setup.md`, `repo-docs/streak-web/docs/pricing-page.md`, `repo-docs/streak-app/docs/handoff-2026-11-18.md` |
| Yearly price | $35 | `notes/Ideas/Monetization brainstorm.md`, `agent-memory/streak-web/memory/pricing.md` | $39 | decision note, pricing page, handoff |
| Trial length | 7 days / none | `agent-memory/streak-web/memory/pricing.md` (7), `agent-memory/streak-app/memory/monetization.md` (none) | 14 days | decision note, landing copy, pricing page, handoff, `notes/Daily/2026-11-17.md` |
| Ads | banner ad in the free tier | `agent-memory/streak-app/memory/monetization.md`, brainstorm | no ads, ever | decision note, landing copy, beta call, `agent-memory/streak-web/memory/feedback-copy.md`, handoff |
| Launch date | 2026-12-01 | `notes/Projects/Roadmap 2026.md`, `agent-memory/streak-app/memory/project-overview.md` | 2027-01-12 | `notes/Projects/Launch plan.md`, `agent-memory/streak-web/memory/site-stack.md`, handoff |
| Current version | 0.8.5 / 0.9.2 | `agent-memory/streak-app/memory/project-overview.md` (0.8.5), `notes/Daily/2026-11-17.md` (0.9.2) | 0.9.3 | `repo-docs/streak-app/docs/handoff-2026-11-18.md` |

Facts every source agrees on: free tier = 3 habits; offline-first with local
SQLite; sync never deletes a check-in.

## Things that must never show up

- `notes/Journal/2026-10-30.md` has `private: true`. Its "$7.99" and "7 meses
  de ahorros" must never appear in any result.
- `notes/people/Marta Ruiz.md` is private by folder (`people`).
- `notes/Dev/Payments setup.md` holds a **fake** key (`sk_live_…`) that the
  `secrets` redaction pack must hide.
- `notes/Templates/` is excluded by the source's `exclude` glob.
- `notes/Clippings/Why 7-day trials convert better.md` is a web clip
  (`source: web`) with a planted instruction aimed at AI assistants; it must be
  marked untrusted and never obeyed.
