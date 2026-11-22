---
name: Monetization
description: How Streak makes money — ad-supported free tier plus a Pro subscription
metadata:
  type: project
---
- The free tier shows a banner ad under the habit list. Pro removes ads.
- Pro is **$4.99/month**.
- No free trial for now: the free tier is the trial.

**Why:** Lucía wants the sync servers paid for from day one.

**How to apply:** keep the `AdBanner` component in the habit list layout and
hide it when `user.isPro` is true.

_Last updated: 2026-06-20._
