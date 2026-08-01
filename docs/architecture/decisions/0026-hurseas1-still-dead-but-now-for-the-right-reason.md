# ADR-0026 — HURSEAS-1 re-checked on full history: the "zero markets" reason was false, but the verdict stays dead — annual cadence is a structural cap, not a query-path gap

- **Status:** Accepted
- **Date:** 2026-07-31
- **Follows:** [ADR-0023](0023-historical-tier-retracts-the-68-day-ceiling.md), which
  flagged HURSEAS-1 as "reopens, but weakly" pending a cheap re-check, using
  only a single-series spot-check (`KXHURCTOT`, 28 resolved, 4 events).
- **Candidate:** HURSEAS-1 from
  [docs/research/2026-07-25-kalshi-category-expansion.md](../../research/2026-07-25-kalshi-category-expansion.md)
  Part 5, item 3 — killed outright by
  [ADR-0016](0016-wp0-history-ceiling-is-a-venue-property.md) on the (now
  known false) claim that seasonal Kalshi hurricane series had **zero**
  resolved history.

## Decision

**HURSEAS-1 stays dead. Not on ADR-0016's original reason (which was false —
there is real history), but on the reason the research doc itself flagged as
the top risk from the start: hurricane seasons happen once a year, and no
API tier changes that.** Confirmed empirically across all five candidate
tickers: the maximum reachable independent-season count is **4** (2022,
2023, 2024, 2025) — one draw per calendar year, structurally, not an
artifact of `/markets` vs `/historical/markets`.

## What was checked

All five HURSEAS-1 tickers from the 2026-07-25 research doc, pulled via
`/historical/markets` (paginated to exhaustion):

| series | total | resolved | traded | distinct seasons | oldest close | newest close |
|---|---|---|---|---|---|---|
| KXHURCTOT | 28 | 28 | 28 | 4 (2022–2025) | 2022-11-02 | 2025-12-02 |
| KXHURCTOTMAJ | 24 | 24 | 22 | 3 (2022, 2024, 2025) | 2022-09-20 | 2025-12-02 |
| KXTROPSTORM | 24 | 24 | 22 | 3 (2023–2025) | 2023-09-07 | 2025-12-02 |
| KXNAMEDSTORM | 0 | 0 | 0 | 0 | — | — |
| KXFIRSTHURRICANE | 0 | 0 | 0 | 0 | — | — |

**KXNAMEDSTORM and KXFIRSTHURRICANE are not a data-access gap — they're a
different situation entirely.** Checked directly against the live tier:
both have real currently-open/recently-settled 2026-season markets (`GET
/markets?series_ticker=KXFIRSTHURRICANE&status=settled` returns 5 real
2026-season results right now), but nothing yet in `/historical/markets` —
consistent with this session's earlier finding (ADR-0025) that the
historical tier's newest data caps around 2026-05-31, months before hurricane
season (June–November) produces anything to archive. These two series may
simply be new products with no prior-season history at all (unlike
KXHURCTOT/MAJ/TROPSTORM, nothing from 2022–2024 shows up for them anywhere,
live or historical) — not confirmed either way, and not load-bearing for the
verdict below since they're structurally different products anyway (see
next section).

## Why more history does not fix this the way it fixed MRAIN-1

**The three series that matter (HURCTOT, HURCTOTMAJ, TROPSTORM) are not
independent data sources — they are three threshold-ladder views of the
same single Atlantic-basin count for the same calendar year.** Checked
directly: every market title reads "...Atlantic hurricanes in `<year>`"
with an identical Jan 1–Dec 31 window across all three series. Pooling them
the way MRAIN-1 pooled 11 geographically-distinct rain series would be the
exact "ladder trap" this project's own methodology (ADR-0016, ADR-0019) was
built to catch — three correlated observations of one season's storm count
is one data point, not three.

**This is the structural difference from MRAIN-1.** MRAIN-1's fix was
real because monthly rainfall is a new independent draw every month —
`KXRAINNYCM` alone yielded 27 independent station-months from one series
because the series itself resolves monthly. Hurricane seasons resolve
**once a year**, so even with Kalshi's full 2021-inception archive, the
hard ceiling is roughly one independent draw per year the exchange has
offered the product — **4 confirmed, matching the research doc's own
upfront estimate ("~5 seasons since Kalshi launched") almost exactly.**
`/historical/markets` cannot manufacture seasons that haven't happened;
this is a case ADR-0023's own framing already anticipated but is worth
stating plainly: **not every "zero" finding from ADR-0016 was a query-path
bug. Some were correctly-shaped conclusions resting on an incorrectly-small
number. HURSEAS-1 is the latter — the number was 0, should have been 4, and
4 is still not enough.**

## What a powered gate would actually need

Per-season PIT resampling (the WP-7/MRAIN-1 trick of evaluating
`P(storms-to-date + climatological residual ∈ strike)` at many points
across a 6-month season) can generate many *samples* per season, but the
independence unit for any honest significance test is still the season
itself — exactly the same family-clustering discipline this project applies
everywhere else (ADR-0019's t-test, ADR-0024's "don't pool 82 months as if
independent"). Thousands of within-season samples do not substitute for
more seasons. **n=4 clustered seasons is not a powered gate under any
resampling scheme**, and won't be until Kalshi has offered the product for
several more years — a genuine calendar constraint, not an engineering one.

## Consequence

**No further engineering work is justified on HURSEAS-1** — this isn't a
"needs new infrastructure" verdict like MRAIN-1's; it's "wait for more
hurricane seasons to happen," which is not actionable on any timeline this
project can act on. Re-checking KXNAMEDSTORM/KXFIRSTHURRICANE's true origin
year would not change this conclusion (they're structurally per-storm or
per-name bets, not the seasonal-count ladders the pre-registered gate needs)
and is not worth the API calls. This closes HURSEAS-1 for the same
practical reason FLB-1's weather/econ gate closed in
[ADR-0025](0025-flb1-gate-retested-on-full-history-stable-no-go.md): real
data, correctly measured, confirms the original "no" rather than reversing
it — unlike MRAIN-1, where correct measurement reversed the verdict. Both
outcomes are legitimate results of the same discipline; this session should
not be read as "more history always reopens things."

**Remaining unresolved candidate from ADR-0023's list:** FLB-1's
"emotional" target basket (ADR-0017, reported 4 resolved markets from the
live-tier probe) — not yet re-tested against `/historical/markets`.
