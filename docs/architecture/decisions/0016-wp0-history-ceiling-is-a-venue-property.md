# ADR-0016 — WP-0 result: Kalshi's ~68-day history ceiling is a venue property; three of five candidates are dead on arrival

- **Status:** Accepted
- **Date:** 2026-07-26
- **Gates:** every backtest-shaped candidate in
  [docs/research/2026-07-25-kalshi-category-expansion.md](../../research/2026-07-25-kalshi-category-expansion.md)
  Part 5. **Confirms and generalizes** [ADR-0014](0014-wp7-gate-result-no-go.md).

> **AMENDED 2026-07-26 by [ADR-0017](0017-flb1-gate-bias-is-real-but-not-in-reachable-markets.md):**
> everything below was measured against the public, unauthenticated API, and
> ADR-0017 flagged that Bürgi–Deng–Whelan (2026) pulled 2021–April 2025 history
> after registering for API access — raising the question of whether
> authenticated access reaches deeper.
>
> **RESOLVED 2026-07-28 by [ADR-0018](0018-authenticated-access-confirms-the-history-ceiling.md):
> no.** The probe was re-run authenticated (RSA-PSS signed, real Kalshi API
> key) and returned the identical ~66–68 day window and identical zero
> markets for the long-dated series — confirmed three independent ways,
> including two that bypass pagination entirely. This ADR's conclusions stand
> without qualification; the escape hatch is closed.

## Decision

**The retrievable-history ceiling is a property of the venue, not of the query
path. It cannot be worked around.** Therefore:

- **HURSEAS-1 (seasonal hurricane) is dead.** Not underpowered — there are
  **zero** retrievable resolved seasonal outcomes.
- **DROUGHT-1 is dead** on the same mechanism.
- **MRAIN-1 (monthly precipitation) is underpowered** and should not be built:
  one resolved monthly cycle per station exists, against a gate needing three.
- **FLB-1 survives, but only on fast markets** — and its named "emotional"
  target basket has **4 resolved markets across 3 series** in all of retrievable
  history, so the basket cannot be studied at all.
- **Do not build any new ingestion adapter.** The 2026-07-25 doc made this
  conditional on WP-0's answer. The answer is in.

## How this was tested

`scripts/wp0_history_probe.py`, run 2026-07-27 02:56 UTC against the live public
API (`external-api.kalshi.com/trade-api/v2`, no auth). Read-only. The probe
answers the three questions empirically rather than from documentation, which
was the point of commissioning it.

## Q1 — Does a different endpoint reach deeper history? No. Identically not.

ADR-0014 hit its ceiling through `GET /events?with_nested_markets=true`. The
hypothesis worth a dev-day was that `GET /markets?series_ticker=…&status=settled`
— a different query path — might not share it. Run head to head on the same
series:

| series | `GET /markets` | `GET /events` | oldest close | span |
|---|---|---|---|---|
| KXHIGHNY | 414 resolved | 414 resolved | 2026-05-19 | 68 d |
| KXHIGHLAX | 414 resolved | 414 resolved | 2026-05-19 | 68 d |
| KXNOBELPEACE | **0** | **0** | — | — |
| KXHURCTOT | **0** | **0** | — | — |
| KXRAINNYCM | 8 | 8 | 2026-06-01 | 30 d |

**The two paths agree to the market.** Neither hit the probe's page cap, so both
exhausted their result sets. ADR-0014's symptom reproduces on the second path
too: 1,742 of 1,811 KXHIGHNY events and 498 of 567 KXHIGHLAX events return no
nested markets.

Two independent confirmations that this is a real data boundary and not a
pagination or default-window artifact:

1. **`max_close_ts` is honoured and finds nothing behind the ceiling.** Asking
   for KXHIGHNY settled markets closing in 2024 or 2025 returns **0 markets**,
   while the unfiltered query returns 414 from 2026-05-19 on. The filter works;
   there is simply nothing there.
2. **Prior-year long-dated events exist as empty shells.** `KXNOBELPEACE-25`,
   `KXHURCTOT-25DEC01`, `HURCTOT-24DEC01`, `HURCTOT-23DEC01`, `HURCTOT-22NOV30`
   are all listed and all carry **0 nested markets**. Only the current, still-open
   2026 events carry markets (KXNOBELPEACE-26: 21, KXHURCTOT-26DEC01: 9).

That second finding is what kills HURSEAS-1 outright. The research doc feared
"you get one season". The truth is **zero** — every prior season is a shell, and
the only hurricane markets carrying data are the ones that have not resolved yet.

## Q2 — On reachable markets, does anything survive besides the result? Yes, all of it.

| series | oldest reachable ticker | result | daily candles | public trades |
|---|---|---|---|---|
| KXHIGHNY | KXHIGHNY-26MAY18-T84 | yes | 3 | 12 |
| KXHIGHLAX | KXHIGHLAX-26MAY18-T76 | no | 3 | 79 |
| KXRAINNYCM | KXRAINNYCM-26MAY-4 | no | 35 | 100 (probe limit) |

`GET /markets/trades?ticker=…` serves the public trade feed with no error, so
FLB-1's data need — resolution plus traded price — is met **inside the window**.
There is no candle blackout on old-but-reachable markets. The constraint is
purely *which markets are reachable*, and that is Q1's answer.

## Q3 — Listing-to-resolution windows

Measured from `open_time`/`close_time` directly, which is both cheaper and more
precise than ADR-0014's candlestick-based estimate:

| series | n | min | median | max |
|---|---|---|---|---|
| KXHIGHLAX | 414 | **42.0 h** | 42.0 h | 42.0 h |
| KXRAINNYCM | 8 | **830.0 h** (34.6 d) | 830.0 h | 830.0 h |

**KXHIGHLAX is 42.0 hours on all 414 markets — zero variance.** This settles the
"Likely (unverified)" generalization in the research doc's §1.1: the short
listing window is a series-template constant and it holds on a second city. It
is a slightly wider number than ADR-0014's ~37–38 h, and both are right — that
figure was measured from first candle activity, this one from the listing
instant. Neither reaches the 72–120 h band where forecast σ balloons.

**KXRAINNYCM is 830.0 hours — also exactly constant.** So MRAIN-1's *mechanism*
is real and confirmed: monthly accumulation markets genuinely are listed five
weeks ahead, squarely in the long-lead band that daily temperature never
reaches. MRAIN-1 dies on sample size, not on thesis. That distinction matters if
the venue ever extends its history.

## What FLB-1 actually has to work with

The research doc ranked FLB-1 first because it "needs no external data source".
That is still true, and it is the only candidate WP-0 does not kill. But WP-0
reshapes it substantially.

**Its named target basket does not exist in resolved form.** All ten
"emotional" series, entire retrievable history:

| KXTRUMPRESIGN | KXIRANDEMOCRACY | KXOAIAGI | KXERUPTSUPER | KXTRUMPIRAN | KXGREENLANDPRICE | KXNOBELPEACE | KXTRUMPPARDONS | KXTRUMPPARDON | KXTRUMPCOUNTRIES |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 1 | 2 |

**4 resolved markets across 3 series**, against 143 currently open. The gate
required a t-stat ≥ 2 on series-clustered standard errors. Three clusters and
four observations is not a study. This is the same trap ADR-0014 identified,
arriving from the other direction: the markets whose slowness makes them
plausibly inefficient are exactly the markets whose slowness means no resolved
history exists.

**A viable study population does exist, and it is the fast markets.** Resolved,
traded, non-sports markets inside the window:

| series | resolved | traded | last px ≥ 0.90 | last px ≤ 0.10 |
|---|---|---|---|---|
| KXHIGHNY / LAX / CHI / MIA / DEN | 414 each | 414 each | 69 each | ~345 each |
| KXLOWTBOS | 414 | 414 | 66 | 344 |
| KXJOBLESSCLAIMS | 99 | 97 | 22 | 32 |
| KXCPIYOY | 48 | 48 | 28 | 14 |
| KXPAYROLLS | 32 | 32 | 9 | 0 |
| KXFEDDECISION | 5 | 5 | 1 | 4 |
| KXRAINNYCM | 8 | 8 | 6 | 2 |

Extrapolating the daily ladders across the 20 cities × 2 (high/low) the
2026-07-25 doc counted gives on the order of **16,000 resolved, fully-traded,
non-sports markets with ~2,800 in the ≥ 0.90 bucket** — a genuinely large
sample, across ~40 series-level clusters. This is precisely the conclusion
hiding in that doc's Part 7 ("you want the anomaly on *fast* markets"), now
promoted from preference to necessity: the fast markets are the only ones that
leave a trace.

**Venue-wide, the settled population is enormous but mostly unusable.** A
30-page probe (30,000 settled markets) covered barely one day and was 97%
sports-parlay combinations — `KXMVESPORTSMULTIGAMEEXTENDED` (21,667) and
`KXMVECROSSCATEGORY` (8,243) — with **75% carrying zero volume**, hence no
traded price. Sports is already out of scope (2026-07-17 doc; nothing here
reopens it), and a never-traded market has no price to be biased.

## A methodological trap FLB-1 must handle, or it will produce a spurious GO

Recorded because the viable sample turns out to be almost entirely
**mutually-exclusive strike ladders**, and a naive decile study on those is
actively misleading.

In a 6-bucket ladder exactly one bucket resolves YES (ADR-0014 measured the
resolved-YES fraction at 0.167 ≈ 1/6). So the NO side of every bucket wins 5/6
of the time **by construction**, and the ladder will hand a price-decile study a
large population of high-priced contracts that win often. That is the adding-up
constraint, not the favorite–longshot bias. Buying NO across all six buckets at
$0.90 pays $5.40 to collect $5.00 — a guaranteed 7.4% loss that a decile table
would score as a winning bucket.

**Any FLB-1 built on this sample must treat a ladder family as one observation
and net the family's positions**, not score its strikes independently. Without
that, the study returns GO on an arithmetic identity.

## What this does NOT establish

- **It does not test forward paper.** Everything above concerns *retrievable
  history*. Accumulating one's own history going forward is unaffected by this
  ceiling and remains open — at 6–12 months before any verdict.
- **It does not prove the ceiling is exactly 68 days or permanent.** It is what
  the venue served on 2026-07-26. It could move. Re-running the probe is cheap
  and is the correct check before reopening any candidate killed here.
- **It does not test authenticated access** on its own — every request above
  was unauthenticated. This was the amendment at the top of this ADR; it is
  now resolved by [ADR-0018](0018-authenticated-access-confirms-the-history-ceiling.md),
  which found the identical ceiling authenticated.
- **It says nothing about whether the favorite–longshot bias is real.** WP-0
  measured data availability, not returns. The bias magnitude is still the
  unverified extrapolation flagged in the research doc's Part 8 — and that
  30-minute paper-table retrieval should still precede any FLB-1 dev-day.
- **Sports was not probed for edge**, only counted. It remains out of scope.

## Recommended next step

Not a work package. The strategic question the research doc's open question 2
asked is now forced, and only the user can answer it: **every candidate that
needs provable historical edge is now either dead or underpowered, so the choice
is forward paper (6–12 months to a verdict) or stop.** The cheapest thing that
could still change the picture is retrieving the Bürgi–Deng–Whelan bias table,
because if the bias in the 0.90–0.99 bucket is under ~0.5 points, FLB-1 should
not be built even on the fast-market sample.

**Done same day — see [ADR-0017](0017-flb1-gate-bias-is-real-but-not-in-reachable-markets.md).**
The bias is ~3 points, six times the abort threshold, so FLB-1 is not retired on
magnitude. But the same paper finds it **absent in mutually-exclusive numerical
ladders**, which is almost exactly the population this ADR left reachable. And
it surfaced the authenticated-API threat at the top of this file.

**Authenticated re-test done 2026-07-28 — see [ADR-0018](0018-authenticated-access-confirms-the-history-ceiling.md).**
The threat did not materialize: authenticated access hits the identical
ceiling.

**Decile study also done 2026-07-28 — see [ADR-0019](0019-flb1-decile-study-real-but-sub-gate-edge-no-go.md).**
Resolved ADR-0017's Exclusive-Numerical-vs-Climate-and-Weather contradiction
(Climate & Weather side: real, statistically overwhelming edge) but the
measured magnitude (+0.88% net) misses FLB-1's own +1.5% gate. FLB-1 is
finished. Every candidate this ADR and its follow-ups considered is now
resolved. **The forward-paper-or-stop fork is the only decision left, and it
is the user's, not a work package.**
