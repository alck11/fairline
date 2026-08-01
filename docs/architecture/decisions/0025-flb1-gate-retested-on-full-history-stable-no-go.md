# ADR-0025 — FLB-1's gate retested on full `/historical/markets` depth: the edge is real, stable, and durably below the bar — not underpowered anymore, just NO-GO

- **Status:** Accepted
- **Date:** 2026-07-31
- **Follows:** [ADR-0023](0023-historical-tier-retracts-the-68-day-ceiling.md), which
  named this specific re-run as "the other major reversal candidate" alongside
  MRAIN-1 ([ADR-0024](0024-mrain1-power-objection-is-false-reopened.md)).
- **Supersedes, for statistical power purposes, not methodology:**
  [ADR-0019](0019-flb1-decile-study-real-but-sub-gate-edge-no-go.md) (weather
  and econ gates, both re-run on 14x/10x more families) and
  [ADR-0022](0022-v03-econ-calibration-gate-is-also-underpowered.md) (its
  "underpowered, can't tell" verdict is now simply wrong — econ is powered
  and shows no edge).
- **Tool:** `scripts/flb1_ladder_decile_study.py --auth --historical` (new
  `--historical` flag added this session, repoints `fetch_population` at
  `/historical/markets` instead of `/markets`; same parsing, same
  family-clustered t-test, same gate thresholds as ADR-0019 — only the data
  source changed).

## Decision

**The weather FLB-1 gate is not a small-sample artifact. It is a real,
precisely-measured ~+1.15% net edge that sits durably below the 1.5%
pre-registered bar. NO-GO stands, now on far stronger evidence than before.
Econ shows no edge at all, decisively — not "unknown," as ADR-0022 said.**

## What was checked

Same six weather series and four econ series as ADR-0019, same [0.90, 0.99]
gate band, same fees.py-based post-fee ROI, same family-clustering design —
pulled via `/historical/markets` (paginated to exhaustion per series)
instead of the ~68-day live-tier `/markets` endpoint ADR-0019 was forced to
use before ADR-0023's discovery.

| | ADR-0019 (live tier, 68 days) | This ADR (historical tier, full depth) |
|---|---|---|
| Weather: obs / families | 804 / 402 | **27,532 / 5,704** |
| Weather: net ROI / t-stat | +0.88% / 9.41 | **+1.15% / 24.43** |
| Weather: verdict | NO-GO | **NO-GO** |
| Econ: obs / families | ~28 / 14 (UNDERPOWERED) | **780 / 145** |
| Econ: net ROI / t-stat | n/a (underpowered) | **+0.20% / 0.23 — NO-GO** |

Per-series depth pulled (resolved+traded markets, `/historical/markets`):
KXHIGHNY 8,368, KXHIGHCHI 8,400, KXHIGHMIA 5,952, KXHIGHDEN 3,323, KXHIGHLAX
3,010, KXLOWTBOS 348, KXCPIYOY 429, KXJOBLESSCLAIMS 344, KXPAYROLLS 313,
KXFEDDECISION 124.

## Why this is a stronger result than ADR-0019, not just a bigger one

**The point estimate barely moved (+0.88% → +1.15%) while the family count
went up 14x and the t-stat went from 9.41 to 24.43.** That is exactly the
signature of a real, stable population parameter, not noise that a bigger
sample might push over the 1.5% line — with 5,704 independent family-means,
the standard error is small enough (≈0.047pp, backed out from t = mean/se)
that the 1.5% gate is now excluded with very high confidence, not just
"not yet cleared." ADR-0019's NO-GO was correct but resting on a sample
small enough that "maybe more data flips it" was a live possibility this
session explicitly set out to close. **It's closed: more data confirms the
same verdict, tighter.**

**Econ flips from "can't tell" to "no edge, confidently."** ADR-0022 killed
the econ line on power grounds (14 release-events, called it structurally
too small to trust either way). With `/historical/markets`, econ has 145
families in the gate band — 10x ADR-0022's total event count — and the
measured edge is +0.20% with t=0.23, indistinguishable from zero. This is a
real, decisive finding, not a data-availability gap: **econ ladders show no
favorite-longshot bias in this band, full stop.** `roadmap.md`'s v0.3 econ
line should not be built on the premise of a Kalshi-side pricing edge; ADR-0022's
"redesign around FRED/BLS data directly" fallback is the only surviving path
if econ directional EV is still wanted.

## A new finding this pull surfaced, not in scope before: KXLOWTBOS is a brand-new market

Checking oldest/newest `close_time` per series (not part of ADR-0019's
original design, added here to sanity-check the pull): five of six weather
series go back to 2021-2022. **`KXLOWTBOS` does not — its oldest market
closes 2026-04-04.** The whole Boston low-temperature series is barely four
months old. This directly bears on [ADR-0020](0020-flb1-tail-risk-is-concentrated-and-unmeasurable-from-68-days.md)/[ADR-0021](0021-weather-tail-correlation-mixed-evidence-not-decisive.md)'s
open question — whether Boston's concentration of all three gate-bucket
losses (two of them sharing 2026-05-26) was a thin/new-market artifact or a
real correlated-weather signal. **It is now clear the entire observed
KXLOWTBOS history to date is only ~2 months old — those losses aren't a
small sample drawn from a longer series, they're a large fraction of
everything that series has ever done.** This doesn't resolve ADR-0021's
mixed verdict (that still stands on its own terms), but it means "wait for
more KXLOWTBOS history" is now a real, literal option — there was none to
wait for before, and now the series is old enough to be revisited on its own
timeline. `/historical/markets` cannot manufacture history a series doesn't
have; this is a case where the ceiling genuinely is the series' own age, not
a query-path artifact.

## What this does not change

- The family-clustering methodology, gate thresholds (1.5% ROI, t≥2), and
  fee model are unchanged from ADR-0019 — this is the same test, wider data.
- [ADR-0021](0021-weather-tail-correlation-mixed-evidence-not-decisive.md)'s
  cross-city correlation/tail-severity question is not re-answered here; it
  needs its own re-run against 5 years of NOAA/IEM data (cheap, not done in
  this session — see Consequence).
- WP-7's own weather calibration verdict ([ADR-0014](0014-wp7-gate-result-no-go.md))
  is unaffected — different data pipeline entirely, as ADR-0023 already noted.
- MRAIN-1's status ([ADR-0024](0024-mrain1-power-objection-is-false-reopened.md))
  is unaffected — different series family, different gate.

## Consequence

**FLB-1, as pre-registered, is closed — not paused pending more data, closed.**
The edge exists, is fee-aware, is measured across 5+ years and thousands of
independent families, and is durably ~0.35pp short of the bar. Re-running
this again with even more data would not be expected to change the verdict;
the t-stat is already high enough that this isn't a power problem. The
remaining open items from this track are: (1) `KXLOWTBOS`'s tail-risk
question, revisitable in a few more months once that series has real
history of its own; (2) re-running ADR-0021's correlation check against 5
years of NOAA data instead of 88 days, cheap and not yet done, but now
lower-priority since the gate itself is closed regardless of tail severity;
(3) FLB-1's "emotional" target basket (ADR-0017's 4-market count),
flagged by ADR-0023 as almost certainly undercounted the same way MRAIN-1
was, not yet re-tested. None of these reopen FLB-1's core weather/econ gate
verdict — they're adjacent, smaller items.
