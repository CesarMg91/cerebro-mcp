---
type: reference
date: 2026-10-05
tags: [payments, dev]
---
# Payments setup

<!-- Demo data: the key below is FAKE. It is here so you can watch cerebro redact it. -->

Products in the payment provider dashboard:

- `streak_pro_monthly`: $5.99/month, 14-day trial
- `streak_pro_yearly`: $39/year, 14-day trial

Server env (these are my private notes, never paste this anywhere):

PAYMENTS_SECRET_KEY=sk_live_DEMOfake0000NOTREAL
WEBHOOK_URL=https://api.streak.example/webhooks/payments

- [x] Create both products
- [x] Webhook for `subscription.renewed`
- [ ] Rotate the key after launch

Related: [[2026-09-14 Precio y anuncios]]
