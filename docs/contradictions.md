# Contradictions

```sh
cerebro contradictions "price"
cerebro contradictions "launch date" --across-sources --limit 5 --json
```

The MCP tool is `contradictions(topic, across_sources?, limit?)`.

## The problem it solves

Facts drift. You decide something in a note; an agent remembered the old
version; a handoff in another repo was written in between. Each source is
internally fine. Together they disagree, and nothing tells you.

`contradictions` looks for that disagreement on one topic at a time.

## What counts as a contradiction

A pair of fragments, from **different notes**, that are about the same topic
and state **different values** of a comparable kind:

| Kind | Example pair |
|---|---|
| Price | "$4.99/month" vs "$5.99 al mes" |
| Number with a unit | "7-day free trial" vs "14 days" |
| Version | "Current version: 0.8.5" vs "Current version: 0.9.3" |
| Date | "Launch: December 1, 2026" vs "Launch: 2027-01-12" |
| Yes / no | "The free tier shows a banner ad" vs "No ads, ever" |

How it works, roughly:

1. Find fragments on the topic with the same hybrid search as `search`
   (private notes and hidden scopes are filtered out first, as always).
2. Pair fragments from different notes that are similar to each other.
3. Extract comparable values (prices, numbers with units, versions, dates,
   yes/no statements) from both sides.
4. Keep pairs whose values differ. Rank them; return both snippets, both
   sources, both dates and the differing values.

`--across-sources` keeps only pairs whose sides come from different sources (or
different projects), which is usually what you want: your notes against an
agent's memory, or one repo's handoff against another's.

## Examples from the demo vault

The demo (`cerebro demo`) is built so these show up:

- **Price**: an agent memory says Pro is $4.99/month; the decision note
  (in Spanish) says $5.99 al mes.
- **Trial**: the website agent remembers a 7-day trial; the pricing page spec
  says 14 days.
- **Reversed decision**: the app agent remembers an ad-supported free tier; the
  decision note, the landing copy and the latest handoff all say no ads.
- **Launch date**: an old roadmap and an agent memory say 2026-12-01; the
  launch plan and the website agent say 2027-01-12.
- **Version**: an agent memory says 0.8.5; the latest handoff says 0.9.3.

## Limits

This is a **heuristic that proposes candidates**. It does not decide what is
true.

- **The source of truth wins, not the newest note.** If the code, the live
  pricing page or the store listing says $5.99, that is the price, whatever any
  note says. Use the pair to find what to fix, then check the real thing.
- **Newer is usually right, not always.** A fresh note can repeat an old fact.
  Both dates are shown so you can judge.
- **Change is not contradiction.** "0.9.2 shipped on Nov 3" and "0.9.3 shipped
  on Nov 18" are both true. They will still be paired, because the tool cannot
  tell "was" from "is".
- **Quoting is not claiming.** A changelog line "was $4.99, now $5.99" mentions
  the old value on purpose.
- **Different things with the same shape.** "$39/year" and "$5.99/month" are
  both prices of the same product and are not in conflict. Units help; they do
  not always save it.
- **Hedged text.** Brainstorms ("maybe $35/year?") state possibilities, not
  facts.
- **Missing dates.** Agent memories often have no date in frontmatter. Pairs
  still show, but ordering by date is weaker.
- **Recall depends on search.** If a fragment does not rank for the topic, it is
  never compared. Try a few phrasings ("price", "precio", "pricing").

When a client like Claude calls the tool, it should treat each pair as a lead:
quote both sides, say which looks stale and why, and point to the source of
truth to check. Never "fix" a note automatically from a pair; cerebro is
read-only, and `propose` exists for writing suggestions down.
