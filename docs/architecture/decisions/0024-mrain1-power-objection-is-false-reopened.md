# ADR-0024 — MRAIN-1's power objection is false: reopened, pending the actual calibration-study build

- **Status:** Accepted
- **Date:** 2026-07-28
- **Confirms:** [ADR-0023](0023-historical-tier-retracts-the-68-day-ceiling.md)'s
  prediction that MRAIN-1 was the strongest candidate for reversal.
- **Reopens:** MRAIN-1 from
  [docs/research/2026-07-25-kalshi-category-expansion.md](../../research/2026-07-25-kalshi-category-expansion.md)
  Part 5, item 2 — killed by [ADR-0016](0016-wp0-history-ceiling-is-a-venue-property.md)
  on statistical power alone, mechanism explicitly called sound.

## Decision

**The power objection that killed MRAIN-1 is false. Reopened — but not yet
tested.** This ADR confirms *data availability* only; the actual
Brier-skill calibration gate (ADR-0012's methodology, reused per the
original pre-registration) has not been run. That is real, comparable-scope
engineering work — a new IEM precipitation-accumulation ingestion path and a
climatological residual benchmark — not a quick script, and is the next
piece, not done here.

## What was checked

All 11 rain series from the 2026-07-25 research doc's MRAIN-1 candidate,
pulled via `/historical/markets` (paginated to exhaustion):

| series | resolved | traded | distinct months | oldest | newest |
|---|---|---|---|---|---|
| KXRAINSEAM | 43 | 43 | 6 | 2025-12-01 | 2026-05-01 |
| KXRAINHOUM | 39 | 39 | 6 | 2025-12-01 | 2026-05-01 |
| KXRAINLAXM | 43 | 43 | 6 | 2025-12-01 | 2026-05-01 |
| KXRAINMIAM | 39 | 39 | 6 | 2025-12-01 | 2026-05-01 |
| KXRAINCHIM | 43 | 41 | 7 | 2025-07-01 | 2026-05-01 |
| **KXRAINNYCM** | **168** | **166** | **27** | **2024-03-01** | **2026-05-01** |
| KXRAINSFOM | 39 | 39 | 6 | 2025-12-01 | 2026-05-01 |
| KXRAINDENM | 39 | 38 | 6 | 2025-12-01 | 2026-05-01 |
| KXRAINDALM | 43 | 42 | 6 | 2025-12-01 | 2026-05-01 |
| KXRAINAUSM | 39 | 38 | 6 | 2025-12-01 | 2026-05-01 |
| KXRAINSTPM | 0 | 0 | 0 | — | — |
| **TOTAL** | **535** | — | **82 distinct station-months** | | |

The pre-registered gate ([ADR-0016](0016-wp0-history-ceiling-is-a-venue-property.md),
quoting the 2026-07-25 doc): *"GO iff Brier skill ≥ +5% on ≥1 series with
n ≥ 400 samples across ≥3 distinct station-months."* ADR-0016 estimated
**~18–22 station-months total** reachable and called that "very likely
underpowered." The real number is **82** — pooled across series — and even
**one series alone** (`KXRAINNYCM`) clears the ≥3-station-months bar by 9x
(27 vs. 3) with genuine multi-year spread. 535 resolved markets is itself
already above the 400-sample floor before accounting for the PIT-style
multi-snapshot sampling ADR-0012's actual methodology uses (WP-7 turned 408
markets into 2,442 samples via 6-hourly `as_of` steps — a similar multiplier
here would put the real sample count well into the thousands).

## The honest complication, not buried

**Two very different populations are being pooled, and that matters for how
any future study should be designed.** `KXRAINNYCM` has real seasonal depth —
27 months from March 2024 to May 2026, spanning multiple winters and
summers. **The other nine live series only go back to 2025-12-01 — six
identical calendar months, replicated across nine cities.** That is not nine
independent seasonal samples; it is one six-month window observed from nine
vantage points, and per [ADR-0021](0021-weather-tail-correlation-mixed-evidence-not-decisive.md)'s
finding that nearby-city weather anomalies correlate, precipitation across
these cities in the same months is unlikely to be fully independent either.
`KXRAINSTPM` has zero data and should be dropped. **`KXRAINCHIM`'s oldest
month (2025-07-01) doesn't fit the other eight's Dec-2025 start — worth
understanding before pooling it in, not assumed to be a clean series.**

**Recommendation for the actual study, when built:** treat `KXRAINNYCM` as
the primary, adequately-powered single-series test (satisfies the gate's
"≥1 series" clause on its own, with real seasonal diversity) rather than
leaning on the pooled 82-month count as if it were 82 independent draws —
the other ten series add confirmatory value and volume, not the same
statistical independence their raw event-count suggests.

## What this does not do

**Does not run the gate.** The pre-registered design (`calibration.evaluate()`
reused, benchmark = `P(accum_to_date + residual ∈ strike)` from
point-in-time IEM precipitation data) needs: (1) a precipitation-accumulation
ingestion path this project doesn't have yet (`weather_ingest.py` currently
carries temperature MOS/ASOS, not precipitation), (2) a climatological
residual model for the remaining-days uncertainty, (3) confirming Kalshi's
`resolution_text` for these series settles on the same accumulation source
IEM would provide (the 2026-07-25 doc flagged this as a mandatory 0.5-day
check before trusting any result, per ADR-0012's own mis-parsed-strike
caution). None of that exists yet. This ADR closes the "is there enough data"
question; it opens, rather than answers, "does the model beat the price."
