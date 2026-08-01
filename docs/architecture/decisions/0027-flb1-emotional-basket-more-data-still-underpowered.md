# ADR-0027 — FLB-1's "emotional" target basket re-tested on full history: 21x more markets, still not a study

- **Status:** Accepted
- **Date:** 2026-07-31
- **Follows:** [ADR-0023](0023-historical-tier-retracts-the-68-day-ceiling.md), which
  flagged this as the last unconfirmed item from the venue-landscape refresh:
  "FLB-1's 'emotional' target basket — ADR-0017 reported 4 resolved markets
  across 3 series from the live-tier probe. Almost certainly undercounted the
  same way, not re-tested here."
- **Candidate:** the 10-series "emotional pricing" basket named in
  [docs/research/2026-07-25-kalshi-category-expansion.md](../../research/2026-07-25-kalshi-category-expansion.md)
  Part 3.2 and counted in [ADR-0016](0016-wp0-history-ceiling-is-a-venue-property.md):
  KXTRUMPRESIGN, KXIRANDEMOCRACY, KXOAIAGI, KXERUPTSUPER, KXTRUMPIRAN,
  KXGREENLANDPRICE, KXNOBELPEACE, KXTRUMPPARDONS, KXTRUMPPARDON, KXTRUMPCOUNTRIES.
- **Tool:** `scripts/flb1_ladder_decile_study.py`'s `fetch_population`/`gate_test`
  (unmodified — reused directly against this series list via `historical=True`).

## Decision

**The undercount was real (4 markets → 170), but the fix doesn't reach
"testable."** `/historical/markets` recovers 170 resolved+traded observations
across 7 independent families, up from ADR-0016's 4 markets / 3 series. That
is real signal that ADR-0016's live-tier count was an artifact, same pattern
as MRAIN-1 and FLB-1's weather gate. **But 7 families is still an order of
magnitude short of anything this project would otherwise trust, and — more
important than the count — the gate_test script's mechanical "NO-GO" verdict
on this population is not honest evidence and should not be read as
confirming FLB-1 doesn't work on emotional/political markets. It should be
read as UNDERPOWERED**, overriding the script's own output.

## What was checked

Same six now-populated series (four of the original ten remain genuinely
unresolved, see below), same `fetch_population`/`gate_test` code already
verified in [ADR-0025](0025-flb1-gate-retested-on-full-history-stable-no-go.md),
no new logic written:

| series | resolved+traded | distinct families (events) |
|---|---|---|
| KXOAIAGI | 2 | 1 |
| KXTRUMPIRAN | 2 | 1 |
| KXNOBELPEACE | 23 | 1 |
| KXTRUMPPARDONS | 1 | 1 |
| KXTRUMPPARDON | 55 | 3 |
| KXTRUMPCOUNTRIES | 2 | 1 |
| **TOTAL** | **85** | **7** |

Mechanical gate output: **170 obs (YES+NO), 85 in the [0.90, 0.99) gate band,
7 families, net_roi = +0.99%, t = 6.99 → NO-GO** (script's literal verdict,
since `n_families >= 5` is its only automatic UNDERPOWERED trigger).

## Why the mechanical NO-GO is not trustworthy, stated before it misleads anyone

**Self-attack finding, not visible from the summary numbers alone:** every
single one of the 85 in-band observations *won* — win_rate 1.000, zero
losses. The two other price buckets that got any observations at all were
[0.00, 0.10) (85 obs, win_rate 0.000) and nothing whatsoever in between —
every one of these ten series resolves at a price near certainty (0-2¢ or
98-100¢) or doesn't trade in a way that produces a mid-range quote at all.
That has two consequences the raw t-stat hides:

1. **The apparent significance is driven by between-family price variation,
   not by observed win/loss uncertainty.** With zero losses in the band,
   `net_roi`'s variance across the 7 family-means comes entirely from small
   differences in how close to 1.00 each family's price sat — not from any
   family actually losing. A t-test built to detect "does this band
   systematically outperform its price" cannot distinguish "structurally
   reliable" from "haven't yet observed the rare loss" when it has zero
   losses to anchor on.
2. **Rule-of-three, applied the same way ADR-0020 applied it to FLB-1's
   weather losses:** zero losses in 85 observations bounds the *plausible*
   true loss rate at roughly 3/85 ≈ 3.5% per-observation — but the
   independent unit here is families, not observations (per this project's
   own standing family-clustering rule), and zero losses in **7** families
   bounds nothing usefully — 3/7 ≈ 43% is a plausible upper bound on a
   per-family bad outcome. A "confirmed" edge cannot coexist with a
   sample this thin at the level that actually matters statistically.

**Structural reason to expect this, not just a sampling accident:** unlike
the weather ladders (independent daily draws) or even HURSEAS-1 (independent
annual draws), most of these series are genuinely **one-off events** —
"will the Nobel committee award X," "will Trump pardon Y by date Z." There
is no meaningful sense in which more calendar time produces more
independent draws of the *same* underlying process the way another day of
weather does. `KXTRUMPPARDON`'s 3 families (grouped by pardon-announcement
date) is the closest this basket gets to a repeatable structure, and 3 is
not enough on its own either.

## The four series that stayed at zero — checked, not a data gap

`KXTRUMPRESIGN`, `KXIRANDEMOCRACY`, `KXERUPTSUPER`, `KXGREENLANDPRICE` still
show zero resolved history in `/historical/markets`. Checked directly
against the live tier (same discipline applied to HURSEAS-1's
KXNAMEDSTORM/KXFIRSTHURRICANE in [ADR-0026](0026-hurseas1-still-dead-but-now-for-the-right-reason.md)):
all four have real, currently-**open** markets with long-dated resolution —
`KXIRANDEMOCRACY-27MAR01-T6` (resolves 2027), `KXERUPTSUPER-0-50JAN01`
(resolves 2050), `KXGREENLANDPRICE-29JAN21-*` (resolves 2029). **These are
genuinely unresolved, not a query gap** — the venue simply hasn't reached
their resolution dates yet, and won't for years in some cases. No further
history exists to retrieve for these four at any API tier.

## Consequence

**FLB-1's emotional/political basket is not GO, not confidently NO-GO —
it stays exactly where ADR-0016 left it: a real thesis with a mechanism
(favorite-longshot bias, documented in the primary literature per ADR-0017)
that this venue's actual named target basket cannot currently test, now for
a sharper reason.** ADR-0016 undercounted the market total; that undercount
is fixed (170 vs. 4). It did not undercount the more important quantity —
independent families — nearly as much (7 vs. 3), and 7 was never going to
be enough regardless of which endpoint found it. **This basket needs
calendar time to produce more one-off political/cultural events, the same
structural limitation as HURSEAS-1, not a bigger API pull.** Unlike
HURSEAS-1's ~1/year cadence, there's no fixed clock here to estimate when
"enough" arrives — this stays parked, not scheduled for revisit.

**With this, every candidate ADR-0023 flagged as unconfirmed is now
checked**: MRAIN-1 reopened on data (gate unbuilt, [ADR-0024](0024-mrain1-power-objection-is-false-reopened.md)),
FLB-1's weather/econ gate closed decisively ([ADR-0025](0025-flb1-gate-retested-on-full-history-stable-no-go.md)),
HURSEAS-1 closed on a corrected reason ([ADR-0026](0026-hurseas1-still-dead-but-now-for-the-right-reason.md)),
and the emotional basket closed here on the same structural grounds as
HURSEAS-1. **No further "re-check against `/historical/markets`" items remain
open from this session's list.** The next real decision is whether to invest
in the MRAIN-1 calibration build (new engineering, comparable in scope to
WP-6/WP-7) or treat the Kalshi weather/econ/political line as fully explored
at current bankroll and revisit the venue-landscape question instead.
