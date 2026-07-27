# ADR-0017 — FLB-1 gate: the favorite–longshot bias clears the abort threshold, but the paper's own cut says it is absent from the markets WP-0 leaves us

- **Status:** Accepted
- **Date:** 2026-07-26
- **Resolves:** the pre-condition in
  [docs/research/2026-07-25-kalshi-category-expansion.md](../../research/2026-07-25-kalshi-category-expansion.md)
  Part 8 — *"Retrieving that table is a 30-minute task that should precede
  FLB-1, and if the real bias in the 0.90–0.99 bucket is under ~0.5 points,
  FLB-1 should not be built at all."*
- **Amends:** [ADR-0016](0016-wp0-history-ceiling-is-a-venue-property.md) — see
  "A threat to ADR-0016" below.

## Decision

**FLB-1 is not retired on magnitude grounds. The bias is roughly 3 points at
95c, six times the abort threshold, and it is statistically significant post-fee
above 70c.**

**But do not build FLB-1 on the sample WP-0 leaves reachable without first
testing the ladder question.** The paper's own structural cut finds the bias
**absent** in mutually-exclusive numerical contracts — which is exactly what
Kalshi weather and econ strike ladders are, and those ladders are essentially
the entire population WP-0 found retrievable.

## The source, finally read

Bürgi, Deng & Whelan, *Makers and Takers: The Economics of the Kalshi Prediction
Market*, University College Dublin, January 2026. Retrieved 2026-07-26 from the
author's own PDF (`karlwhelan.com/Papers/Kalshi.pdf`, HTTP 200) and read
directly — the previous session's blocker was a missing PDF text extractor, not
access. Sample: **transaction-level data from Kalshi's inception in 2021 through
April 2025**, 46,282 contracts from 12,403 events, 313,972 Yes+No price
observations, restricted to contracts closing with ≥$1,000 volume.

**The 10 tables contain no returns-by-price-bucket table.** Those are Figures 5
and 6 — charts, unreadable as text, which is why the 2026-07-25 research doc
could not extract a number even from summaries. The magnitude is instead
recoverable three other ways, and they agree.

## The magnitude, three independent ways

**1. The paper's own worked illustration.** Quoted verbatim: *"A 95c contract
that wins 98% of the time has a pre-fee average return of 3.1%."* That is
**exactly** the 3-point bias the research doc assumed at 95c and flagged as its
single load-bearing unverified assumption. Recomputed independently:
`(0.98 − 0.95) / 0.95 = +3.16%`. The assumption was right.

**2. The measured maker return.** Verbatim: *"On average, Makers who buy
contracts costing 50c and over earn a 2.6% rate of return."* Measured, post-fee,
across 156,986 maker contracts.

**3. The Mincer-Zarnowitz regression, evaluated ourselves.** Equation 3 is
`Y − P = α + ψP` with prices and profit **in cents**. Table 4 column 1 gives
`α = −1.736***`, `ψ = 0.034***` over 156,986 Yes contracts, standard errors
clustered at the event *and* contract level.

The unit reading is validated rather than assumed: the implied break-even price
is `1.736 / 0.034 = 51.1c`, and the paper's prose independently says *"there are
small positive returns for contracts above 50c."* They match, so the cents
reading is right.

Evaluating at 95c and applying our own `fees.py`:

| sub-sample (Table 4) | n | break-even | pre-fee @95c | taker post-fee @95c |
|---|---|---|---|---|
| **All** | 156,986 | 51.1c | +1.57% | **+1.21%** |
| Single-outcome events | 16,433 | 13.2c | +3.87% | **+3.50%** |
| Non-Exclusive | 58,602 | 51.1c | +1.66% | **+1.30%** |
| **Exclusive Numerical** | 46,674 | **116.9c — never** | −0.32% | **−0.68%** |
| Exclusive Other | 35,277 | 95.8c | −0.02% | −0.37% |
| All Exclusive | 81,951 | 103.3c — never | −0.15% | −0.50% |

The linear fit understates the extremes badly — at 5c it implies −31% where the
paper measures *"over 60%"* loss — so treat these as conservative lower bounds
on the true bucket means, not point estimates.

**Verdict on the gate: 3 points ≫ 0.5 points. FLB-1 survives the magnitude
test.**

## Why that verdict does not translate into a build

Read the same table by contract structure and the picture inverts.
**`Exclusive Numerical` — mutually exclusive outcomes over a numerical variable,
i.e. a strike ladder — has no profitable price anywhere in the tradeable
range.** Break-even is 116.9c, off the top of the scale. The bias that is worth
3 points on the full sample is worth *nothing* there.

That matters because of what [ADR-0016](0016-wp0-history-ceiling-is-a-venue-property.md)
found: the retrievable, traded, non-sports population is ~16,000 daily
temperature ladders plus a few hundred econ ladders. **It is almost entirely
`Exclusive Numerical`.** The categories where the bias is strong — single-outcome
events (break-even 13.2c), crypto, "other" — are either out of scope or have no
retrievable history.

This is also the quantitative form of the ladder trap ADR-0016 recorded
independently. The paper handles it the way ADR-0016 demanded: standard errors
clustered at the event level *"because there are negative correlations within
observations on the same event (if one contract wins a mutually exclusive event,
then the others did not)."* Same discipline, arrived at from opposite
directions, which is reassuring about both.

### The one unresolved tension, and it is the crux

Table 8 cuts by *category* instead of structure, and **Climate & Weather is the
second-largest category at 29,924 observations with `α = −0.997***`,
`ψ = 0.031***` — break-even 32.2c, +1.69% post-fee taker at 95c.** Favourable.

Weather daily-temperature ladders are simultaneously **Climate & Weather**
(favourable, break-even 32c) and **Exclusive Numerical** (unprofitable at every
price). The paper does not report the interaction, and the two cuts cannot both
be describing our population.

**This is not resolvable from the paper, and it is precisely the question that
decides FLB-1.** It is, however, resolvable from data we already hold: ADR-0016
established ~16,000 retrievable resolved weather-ladder markets, and ADR-0014
already ingested 408 KXHIGHNY markets with prices and resolutions. Measuring the
0.90–0.99 bucket's realized NO-side return on our *own* ladder population — with
families netted as single observations — answers it directly and needs no
external data.

## Two corrections this forces on earlier documents

**1. The paper's fee regime is not today's.** Verbatim: *"Under the pre-2025 fee
regime, only Takers pay fees… γ … equal to 0.07 during the period we have
examined. **Makers pay no fee.**"* So the measured +2.6% maker return was earned
with maker fees at **zero**. Under the schedule verified in
[ADR-0015](0015-kalshi-fee-schedule-verified-maker-path.md), a maker on a
maker-fee-enabled series now pays the 0.0175 coefficient. The drag is small
exactly where FLB-1 would trade and large where it would not:

| price | maker fee as % of notional | +2.6% becomes |
|---|---|---|
| 0.50 | 0.876% | +1.72% |
| 0.80 | 0.350% | +2.25% |
| 0.95 | **0.088%** | **+2.51%** |
| 0.99 | 0.018% | +2.58% |

So the new maker fee costs FLB-1 roughly **0.09 points at 95c** — immaterial.
This is the one place the news is unambiguously good.

**2. The paper independently reaches the research doc's capacity conclusion.**
Verbatim: *"someone who wanted to invest substantial capital as a Maker seeking
to buy high-price contracts may have to post prices that are less advantageous
to Makers than the typical trades that we recorded here… Furthermore, some of
the attempts to trade as a Maker would not be matched, again reducing the
overall amount actually invested."* That is the research doc's Part 7 capacity
finding and ADR-0015's adverse-selection note, from the authors of the anomaly
itself. The measured returns are an **upper bound** on what a real book earns.

## A threat to ADR-0016, found while doing this

Recorded prominently because it cuts against a conclusion this project reached
one commit ago, and I would rather flag it than defend the ADR.

**The authors pulled contracts spanning 2021 through April 2025 from Kalshi's
API.** Verbatim: *"we registered with Kalshi to get access to their Application
Programming Interface (API). We used Python scripts to get transaction-level
data from the API for contracts from Kalshi's inception in 2021 through April
2025."* ADR-0016 measured a hard ~68-day ceiling on settled markets.

Three readings are consistent with both facts, and I cannot distinguish them:

1. **They were authenticated; WP-0 was not.** ADR-0016's probe used the public
   unauthenticated API throughout. Registered access may expose deeper history.
2. **They collected prospectively** over four years rather than pulling
   retrospectively. Supported by their per-contract lookback being capped at
   **10 days** before close (Table 1, and footnote 3's description of walking
   back day by day from the last trade) — a limit that looks like live sampling,
   not archive access.
3. **Kalshi's retention changed** between April 2025 and July 2026.

**If reading 1 is right, ADR-0016's central conclusion is wrong and MRAIN-1,
HURSEAS-1 and DROUGHT-1 all come back.** The test is cheap and specific:
**register for a Kalshi API key and re-run `scripts/wp0_history_probe.py`
authenticated.** Until that is done, ADR-0016 should be read as *"the public
unauthenticated API has a ~68-day ceiling"* — which is what it actually
measured — rather than as a statement about the venue.

## What this does NOT establish

- **Nothing here measures the bias on our own data.** Every number is the
  paper's, on a 2021–April-2025 sample that ends 15 months before today.
- **The 0.90–0.99 bucket return is still not a directly quoted figure.** It is
  bounded three ways that agree on ~1–3 points, but the paper's own chart was
  never read.
- **Sample selection differs from ours.** They required ≥$1,000 closing volume
  and dropped wide-spread contracts, which is a more liquid population than the
  full retrievable set.
- **It says nothing about whether the bias persists.** Table 9's by-year
  coefficient is weakest in 2025 (`ψ = 0.021*`, only 10% significant, against
  `0.048***` in 2024) — consistent with a bias that is being competed away,
  though one partial year is not a trend.

## Recommended next step

Not "build FLB-1". Two cheaper things, in order:

1. **Re-run the WP-0 probe with an authenticated API key.** It is the only item
   that could reopen three dead candidates, and it costs a registration.
2. **Run the decile study on the weather-ladder data already ingested**
   (408 KXHIGHNY markets from ADR-0014, extensible to ~16,000), families netted,
   to resolve the Climate-&-Weather-vs-Exclusive-Numerical contradiction on our
   actual population. This is FLB-1's gate restricted to the only markets we can
   reach, and it needs no new data source at all.

If (2) reproduces the `Exclusive Numerical` result, FLB-1 is finished and so is
the last candidate — at which point the forward-paper-or-stop fork in ADR-0016
is the only remaining decision.
