# Kalshi category expansion: do other cities, other regions, or "emotional" markets hold edge?

> Commissioned 2026-07-25, hours after the WP-7 calibration gate returned **NO-GO
> on real data** and ADR-0014 closed Track B. The user's question, verbatim:
> *"research other regions / cities and whats available in kalshi, i believe there
> are opportunities, specially something that are not well priced, there are
> events that people predict emotionally."*
>
> The implicit hypothesis is that the NO-GO was a **NYC artifact** and that other
> cities, or more emotionally-traded categories, are less efficient. This doc
> evaluates that hypothesis; it does not assume it. Per
> `docs/product/requirements.md`, a second "no edge here" verdict is a valid,
> capital-saving deliverable.
>
> **Evidence discipline** (inherited from the 2026-07-17 landscape study): every
> load-bearing claim carries **Confirmed** (verified this session against a source
> I fetched, a file I read, or arithmetic I performed), **Likely (unverified)**, or
> **Assuming**. Kalshi market data is from a live pull of
> `api.elections.kalshi.com/trade-api/v2` on 2026-07-25 (347 series with open
> markets, of ~5,244 KX series probed). Vocabulary follows `CONTEXT.md`:
> *market*, *outcome*, *directional*, *p_model*, *EV*, *edge* (per $1 payout),
> *ROI* (per $1 notional), *signal*, *notional*. Where Kalshi's or a paper's own
> word is quoted verbatim (they say "contract" for what CONTEXT calls an outcome),
> that is flagged.

---

## Part 0 — Verdict

**1. No — the NYC NO-GO is not a NYC artifact, and other cities do not fix it.**
The blocking mechanism ADR-0014 identified is Kalshi's **~38-hour listing window**
on daily temperature ladders, which is a property of the series template, not of
KNYC. Nineteen other cities inherit the same template. Do not spend dev-days
re-running the WP-7 gate on Boston or LA.

**2. Yes — the "emotional pricing" instinct points at something real, and it has
a name: the favorite–longshot bias.** It is the most robustly documented anomaly
in prediction markets, it has been measured *on Kalshi specifically* on 300,000+
outcomes, and — contrary to my own prior — **it survives Kalshi's fee formula
comfortably.** What it does not survive well is capacity, correlation, and the
fact that Kalshi already pays you ~3.25% APY on the same capital for zero risk.

**3. Next research dollar: WP-0, a one-day API feasibility probe**, then the
**favorite–longshot NO-side harvest study (FLB-1)**. Named first candidate:
**FLB-1** — 2–4 dev-days, needs *no external data source at all*, and tests a
whole class of markets at once. WP-0 comes first because ADR-0014 already found
that Kalshi served only ~68 rolling days of nested market data for KXHIGHNY, and
**if that ceiling generalizes, every backtest-gated candidate in this document is
dead on arrival** and the only remaining path is forward paper.

---

## Part 1 — The other-cities question, answered with the data

### 1.1 What the NYC result actually says (and why it is portable)

Two findings came out of WP-7, and they have very different generalization
properties.

**Finding A — the price beat the benchmark.** **Confirmed** (ADR-0014, read this
session): over 408 `KXHIGHNY` markets / 2,442 samples / 68 dates, Brier skill of
the public-forecast benchmark versus price was **-43.6%** (`tmax:between`),
**-107.8%** (`tmax:greater`), **-70.1%** (`tmax:less`). Negative skill means the
market price was *more accurate* than the benchmark, not merely close.

**Finding B — there is no tradeable window in which room could exist.**
**Confirmed** (ADR-0014 follow-up, commit 42487a3): every `KXHIGHNY` market's
price history begins **~37–38h before end-of-target-day**, verified across three
candle granularities (2 daily bars / 39 hourly / 1,383 minute bars over a 30-day
request, all agreeing on the same ~38h span — three granularities cannot be
truncated to an identical window). Forecast error σ at this station more than
doubles from 2.45°F at 12–24h lead to 5.76°F at 72–120h lead — but **the market
does not exist to trade at 72–120h lead.** By listing time the public forecast is
a short-lead nowcast the price has already absorbed.

**Finding A is a NYC/KNYC/summer-2026 claim.** Finding B is a **series-template
claim.** The user's hypothesis is a bet on Finding A being local. Even if it is —
even if Boston's forecasts are materially worse than New York's — **Finding B
still binds, because the ~38h listing schedule is set by Kalshi's series
definition, not by the station.** **Likely (unverified):** the ~38h window is
identical across all daily-temperature series; this is inferred from the shared
series template and identical ladder structure (12 open markets per city, see
1.2), not measured on a second city. Measuring it on one other city is a
**0.5 dev-day** check and is folded into WP-0 below.

### 1.2 The cross-city data

**Confirmed** (`WEATHER_SERIES.txt`, pulled 2026-07-25): **20 US cities carry
daily max-temperature ladders and 20 carry daily min-temperature ladders.** Every
one has **n = 12 open markets** — the identical 12-strike ladder. Range of
activity:

| series | city | size traded, 24h | open interest | median spread | markets w/ 2-sided quote |
|---|---|---|---|---|---|
| KXHIGHLAX | Los Angeles | 324,842 | 254,117 | $0.02 | 10 / 12 |
| KXHIGHNY | New York (the studied series) | 70,829 | 49,438 | $0.01 | 9 / 12 |
| KXHIGHMIA | Miami | 66,248 | 48,982 | $0.02 | 7 / 12 |
| KXHIGHCHI | Chicago | 39,478 | 26,206 | $0.02 | 10 / 12 |
| KXHIGHTSEA | Seattle | 16,543 | 13,756 | $0.02 | 10 / 12 |
| KXHIGHTBOS | Boston | 9,474 | 8,950 | $0.02 | 8 / 12 |
| KXLOWTBOS | Boston (low) | 1,354 | 1,834 | $0.04 | 6 / 12 |

**Data-reading caveat, mandatory before comparing any two rows in these files.**
The `vol` column is lifetime size summed over *currently open* markets. For a
**daily** series the open markets are today's, so lifetime ≈ one day: KXHIGHLAX
`v24/vol` = 324,842 / 337,562 = **96%**; KXHIGHNY = 70,829 / 74,371 = **95%**
(**Confirmed**, arithmetic on the data file). For a **long-dated** series it
accumulates over months: KXTRUMPRESIGN = 262 / 298,451 = **0.09%**. So
cross-city comparison *within* the daily ladders is apples-to-apples; comparing a
daily series to a monthly or annual one on `vol` is meaningless. Several obvious
"KXRAINSEAM has 3× KXHIGHNY's volume" readings are this error.

### 1.3 Does thinness imply mispricing? No — it implies untradeability

This is the crux of the user's hypothesis, and the data answers it directly.

**Confirmed** (arithmetic on `WEATHER_SERIES.txt`): KXHIGHLAX trades **178×** the
size of KXLOWTBOS (337,562 / 1,900). For that 178-fold difference in flow, the
thin series gives up **two quoted strikes** (6/12 vs 10/12) and **two cents** of
median spread ($0.04 vs $0.02). The quote does not disappear. It barely degrades.

The natural reading: an **automated quoter is present across the whole ladder set
regardless of retail flow** — one model, twenty stations, same NWS inputs. Price
quality on the thin ladders is set by that quoter, not by the volume of emotional
retail flow, and the quoter is running the same public data that WP-7 showed
already beats a naive forecast benchmark. **Likely (unverified):** I did not
identify the quoter; this is inference from the uniformity of the ladder
structure and spread, not from any market-maker disclosure.

The honest counter-evidence in the same file, which I will not suppress: at
*extreme* thinness the quote does collapse. **Confirmed:** KXTEMPDCH (Hourly
Directional DC Temperature) has 700 lifetime size and a **$0.84** median spread;
KXTEMPCHIH has 1,636 and **$0.39**; KXTXURI has **zero** size traded, 3/3 markets
"quoted", and a **$0.88** median spread. So there *is* a thinness threshold below
which quoting degenerates — but "quoted 88 cents wide" is untradeable, not
mispriced. You cannot harvest a mispricing you must pay 44 cents of half-spread
to enter.

**One more caution on the spread column:** the median is taken across a whole
ladder, so it is dominated by far-out-of-the-money strikes nobody quotes tightly.
KXHURCAT shows a **$0.68** median on 191,861 size traded — that does not mean the
at-the-money strike is 68 cents wide. Do not use the spread column to rank
tradeability without re-pulling per-strike books.

### 1.4 Do the observed spreads leave room after fees? No, on daily temperature

Take the honest base case. **Confirmed** (ADR-0014): the resolved-YES fraction on
KXHIGHNY was **0.167 ≈ 1/6**, exactly what must hold if one of six mutually
exclusive strike buckets settles YES per date. So the typical bucket prices near
**$0.167**.

Entry cost to take a directional position on such a bucket (**Confirmed**,
arithmetic, using the Part 2 fee formula):

- Taker fee at price 0.167: `0.07 × 0.167 × 0.833 = $0.00974` → **0.97¢**
- Half-spread at the observed $0.02 median: **1.0¢**
- **Total entry cost ≈ 1.97¢ per unit of size**

To break even, `p_model` must exceed price by ~**2.0 percentage points** — a
**~12% relative** edge over a 16.7% base rate (0.02 / 0.167 = 11.98%). At the
thin cities' $0.04 spread it is ~3.0¢, a **~18% relative** edge.

WP-7 measured the sign of that edge as **negative**: the naive public-forecast
benchmark was 43–108% *worse* than price by Brier. So the requirement is not "find
2 points of edge" — it is "find 2 points of edge in a direction the measurement
says does not exist." **Verdict: daily temperature ladders are dead in every city,
not just NYC.**

### 1.5 What would have to be true for another city to differ

Stated so it is falsifiable rather than rhetorical. **All three** must hold:

1. The station's public forecast must be materially worse than KNYC's at
   **0–38h lead** — not at 3-day lead, where the market does not exist.
2. The quoter must **not already be pricing that worse forecast correctly** —
   i.e. the quoter's model must be station-naive while the true error structure is
   station-specific.
3. The resulting mispricing must exceed **~2–3¢ per unit of size** (1.4) to clear
   spread and fee.

Condition 1 is plausible for high-variance continental stations (Denver, Chicago,
Minneapolis) versus a maritime-moderated one. Condition 2 is where it dies: a
quoter sophisticated enough to run 20 stations is calibrating σ per station,
because that is the cheapest possible refinement. Condition 3 then requires the
residual to be big, which contradicts 2.

**Recommendation: do not re-run the WP-7 gate on other cities.** The only
cross-city check worth its cost is the 0.5-dev-day listing-window measurement in
WP-0, and its purpose is to *confirm the NO-GO generalizes*, not to look for edge.

---

## Part 2 — Kalshi's fee formula, verified, and what it costs where

**Confirmed this session** from three independent secondary sources that each cite
the official schedule, and cross-checked against `src/fees.py` in this repo. The
primary PDF (`kalshi.com/docs/kalshi-fee-schedule.pdf`) returned **HTTP 429** on
two attempts this session, so the primary document itself is **unverified**; the
search index surfaced its title as *"Fee Schedule for July 2026 - 7.7.26 Update."*

Per unit of size (Kalshi's word: per **contract**), at fill price `P` in dollars:

```
taker fee = 0.07  × C × P × (1 − P)
maker fee = 0.0175 × C × P × (1 − P)          (= 25% of taker)
order total rounded UP to the next whole cent
no settlement fee; free ACH deposit/withdrawal
coefficient 0.035 for a few index markets (per src/fees.py)
```

**Two discrepancies against this repo's existing beliefs, both actionable:**

- `src/fees.py` (read this session) implements the taker formula correctly —
  `ceil_cents(0.07 × contracts × price × (1 − price))`, coefficient 0.035 for
  index markets — but has **no Kalshi maker path at all**; `kalshi_fee()` charges
  the full taker rate regardless. The 2026-07-17 landscape doc records Kalshi
  makers as "~free." Both are wrong under the July 2026 schedule: makers pay 25%.
  **`fees.py` overstates maker cost by 4×.** Hand this to the architect.
- That doc also records a "$0.035/contract cap." Under a 0.07 coefficient the
  maximum possible fee is `0.07 × 0.25 = $0.0175`, so a $0.035 cap can never bind
  and is either stale or applies to a higher-coefficient category. **Unresolved**;
  flagged as an open question.

### 2.1 Two clean identities that should drive every scoping decision

Both **Confirmed** by algebra and spot-checked numerically:

```
fee as a fraction of notional (= P)         =  0.07 × (1 − P)
fee as a fraction of the max gain (= 1 − P) =  0.07 × P
```

Read them together and the whole fee landscape falls out: **cheap outcomes are
expensive relative to the capital you commit; expensive outcomes are expensive
relative to the profit you can make.** There is no fee-free corner.

| fill price P | taker fee / unit | % of notional | % of max gain | break-even edge needed |
|---|---|---|---|---|
| $0.50 | 1.750¢ | 3.50% | 3.50% | 1.75 pp |
| $0.80 | 1.120¢ | 1.40% | 5.60% | 1.12 pp |
| $0.90 | 0.630¢ | 0.70% | 6.30% | 0.63 pp |
| $0.95 | 0.333¢ | 0.35% | 6.65% | 0.33 pp |
| $0.97 | 0.204¢ | 0.21% | 6.79% | 0.20 pp |
| $0.99 | 0.069¢ | 0.07% | 6.93% | 0.07 pp |
| $0.167 (a temp bucket) | 0.974¢ | 5.83% | 1.17% | 0.97 pp |

(**Confirmed:** each row recomputed independently — e.g. `0.07 × 0.95 × 0.05 =
0.003325`; `0.003325 / 0.95 = 0.35%`; `0.003325 / 0.05 = 6.65%`.)

**A longshot NO bought at $0.97 is a genuinely different fee world from a
coin-flip at $0.50**, and not in the direction the raw cent figure suggests. In
cents it is 8.6× cheaper (0.204¢ vs 1.750¢). As a share of the money you can
actually make, it is **almost twice as expensive** (6.79% vs 3.50%).

### 2.2 The rounding rule is a real tax on a small bankroll

The ceil-to-the-next-cent applies to the **order**, not the unit. **Confirmed**
arithmetic at P = 0.97 (raw fee $0.002037 per unit):

| order size | raw fee | charged | uplift | fee as % of the order's max gain |
|---|---|---|---|---|
| 1 | $0.0020 | $0.01 | +391% | **33.3%** |
| 10 | $0.0204 | $0.03 | +47% | 10.0% |
| 100 | $0.2037 | $0.21 | +3.1% | 7.0% |
| 500 | $1.0185 | $1.02 | +0.1% | 6.8% |

**A one-unit NO at 97¢ pays a fee equal to one third of its entire upside.** To
hold the rounding uplift under 5% the raw fee must reach ~$0.20, which at P=0.97
means **≥ ~98 units (~$95 notional) per order**. For a sub-$10k bankroll spreading
across many small positions, this sets a hard **minimum economic order size of
~$100 notional** on any high-price strategy. Scattering $25 tickets across forty
markets would surrender a large multiple of the edge to rounding alone.

---

## Part 3 — The "emotional pricing" thesis, taken seriously

The user is describing a real, named, extensively-measured anomaly.

### 3.1 What the literature says — and it says it about Kalshi

**Confirmed** (abstract fetched verbatim this session from CESifo and RePEc):
*Makers and Takers: The Economics of the Kalshi Prediction Market*, Bürgi, Deng &
Whelan (CESifo WP 2026 / CEPR DP20631 / UCD WP2025_19), using **transaction-level
data on over 300,000 contracts** since 2021:

> "Kalshi's contract prices are informative and improve in accuracy as markets
> approach closing, but they display a clear favorite–longshot bias: low-price
> contracts win far less often than required to break even, while high-price
> contracts win more often and yield small positive returns."

Supporting figures, **Likely (unverified)** — these appeared consistently across
independent search summaries of the CEPR/VoxEU column and the paper, but I could
**not read the paper's tables directly** (the local PDF renderer is unavailable
and both HTML hosts returned 403):

- Buyers of contracts priced **below 10¢ lose over 60% of their money.**
- Contracts priced **above 50¢ earn a small, statistically significant positive
  rate of return.**
- Decomposed by side: **takers averaged a 32% loss, makers a 10% loss.** Makers
  do ~22 points better.
- Pre-fee, "the average rate of return on Kalshi contracts is minus 20%."

**Do not over-read that last figure.** Every trade has a buyer of YES and a buyer
of NO; the aggregate cannot be −20% in dollars. It is −20% because *percentage*
returns are being averaged across wildly asymmetric prices: the 5¢ buyer loses 60%
of 5¢ (3¢), the 95¢ buyer gains ~3% of 95¢ (3¢). **In dollars they offset; in
percentages the cheap side dominates the average.** This matters because it tells
you the shape of the trade: **a small percentage on a large notional.**

**Confirmed** (search summaries of two further studies, direction only): the bias
is **not uniform by category** — present in Kalshi's Inflation and Employment
markets, **absent in Fed / interest-rate markets.** That is a directly actionable
steer given that KXFEDDECISION is by far the largest series in the pull
(**Confirmed:** 37,536,843 lifetime size, 65 open markets).

### 3.2 What the trade actually is

Systematically **buy the NO outcome of overpriced longshots** — equivalently, buy
the high-priced side. Under CONTEXT.md this is a **directional** signal, not
arbitrage: `p_model` here is not a weather model but a *statistical prior* that
the market's implied probability on cheap outcomes is biased high.

The catalog the user pointed at is exactly the right shape. **Confirmed**
(`ALL_ACTIVE_SERIES.txt`): KXGREENLANDPRICE (8 markets, spread $0.019),
KXTRUMPIRAN (2, $0.008), KXIRANDEMOCRACY (1, $0.011), KXNOBELPEACE (21, $0.02),
KXTRUMPRESIGN (1, $0.01), KXERUPTSUPER (1, $0.04), KXOAIAGI (3, $0.004),
KXTRUMPPARDONS (52, $0.03). Note how **tight** several of those spreads are —
KXOAIAGI at 0.4¢ and KXTRUMPIRAN at 0.8¢ are tighter than the daily weather
ladders. Emotional does not mean unquoted.

### 3.3 The arithmetic — the fee does not kill it

**Assuming** a 3-percentage-point bias: an outcome priced at $0.05 whose true
probability is $0.02, i.e. buy NO at $0.95 with `p_model = 0.98`. This is
extrapolated from the ">60% loss on sub-10¢ contracts" figure (a 5¢ mean price
with a 40% payback implies a ~2% realized win rate) and is **the single
load-bearing assumption in Part 3** — every dollar figure below scales linearly
with it.

**Confirmed** arithmetic (taker, fill exactly at $0.95, no spread paid):

```
fee/unit = 0.07 × 0.95 × 0.05          = $0.003325
EV/unit  = p_model − price − fee
         = 0.98 − 0.95 − 0.003325      = $0.026675
ROI      = EV / notional = 0.026675/0.95 = 2.81%
win  (p=0.98): +$0.046675 per unit
lose (p=0.02): −$0.953325 per unit      → 20.4 wins to fund one loss
```

Paying one full cent of spread (fill at $0.96 instead of $0.95):
`fee = 0.07 × 0.96 × 0.04 = $0.002688`; `EV = 0.98 − 0.96 − 0.002688 =
$0.017312`; **ROI = 1.80%.** So a 1¢ spread costs ~35% of the edge and the trade
is still positive.

Sensitivity, because the assumption is doing all the work: at a **1-point** bias
instead of 3, `EV = 0.96 − 0.95 − 0.003325 = $0.006675`, **ROI = 0.70%**, and the
fee is now **33% of the gross edge**. At a 0.5-point bias the trade is roughly
fee-neutral. The strategy's viability is a straight-line function of a number I
could not verify from the primary table.

**This overturns my own prior, and the brief's framing.** I expected "fee drag on
cheap contracts" to be the killer. It is not — because you are not buying the
cheap contract, you are buying the expensive one, and there the fee is only
**0.35% of notional.** The things that actually kill it are below.

### 3.4 What kills it (ranked by how much)

**1. Correlation and the impossibility of statistical power.** Per-position
outcome standard deviation is `√(0.98 × 0.02) × $1.00 = $0.140` against an EV of
$0.0267 — a per-position ratio of **0.19** (**Confirmed** arithmetic). Reaching a
t-statistic of 2 needs `(2/0.19)² ≈ 111` **independent** resolved positions. The
long-dated novelty markets resolve annually and are heavily correlated by
construction (every "Trump does X" market shares one factor; every Iran market
shares another). You will not accumulate 111 independent outcomes in this category
in a decade. **You can never prove this strategy works on the very markets the
user has in mind — you can only prove it on the short-dated, high-turnover ones.**

**2. Time to resolution, partly rescued by APY.** A NO at $0.95 on a year-dated
market earns ~2.8% *per resolution*, so ~2.8% annualized. **Confirmed**
(help.kalshi.com APY article, fetched this session, last updated 2026-03-17):
Kalshi pays **3.25% APY, variable**, accruing daily on the net portfolio value
*including* "the underlying collateral for your positions," $250 minimum, US users
only. (Secondary sources this session cite 3.75–4.05%; the rate is explicitly
variable — I use the primary figure.) So the classic "capital locked for months"
objection is **much weaker on Kalshi than in the general literature** — the
long-horizon problem is a live research topic (Maresca, arXiv:2602.21091,
2026-02-24, **Confirmed** abstract: platforms introduced interest-bearing
positions precisely for this, and it "eliminates approximately 83% of the horizon
effect on accuracy"). **But note the sting:** at a $8,000 deployment the APY pays
**$260/yr risklessly** versus the strategy's ~$225/yr of expected edge (Part 7).
**The interest Kalshi pays you to do nothing exceeds the anomaly you would work to
harvest.** They stack — you earn both — but that is the correct scale reference.
**Open question:** whether this APY survives holding Kalshi positions **through
IBKR**, which is this project's planned execution path. **Assuming** it does not
(it is described as a Kalshi-native, Kalshi-Klear-funded program), the IBKR route
costs ~3.25%/yr of carry on every long-dated position — which is larger than the
edge. That single fact may decide the venue-access question in `roadmap.md`.

**3. Tail risk expressed as year-level variance.** See Part 7 — a third of years
are losing years.

**4. Per-market capacity.** See Part 7.

**5. The one piece of evidence that points the wrong way.** The only study that
separates the two sides finds **takers lose 32% and makers lose 10%** — *both
negative*. Those are percentage-averaged returns dominated by the cheap side, so
they are not directly the NO-side number, but they do establish that on Kalshi
**the maker is 22 points better off than the taker.** Combined with the maker fee
being 25% of taker, the correct implementation is **posting resting orders, not
crossing the spread** — which introduces adverse selection (you get filled exactly
when someone informed wants out) and non-fills, neither of which the paper
backtest models. Flag for the architect: paper mode assumes full fills
(`CONTEXT.md` → Mode), so **a paper backtest of a maker strategy will
systematically overstate it.**

---

## Part 4 — WP-0: the precondition that gates every candidate below

**Do this before anything else. 1 dev-day. It can kill four of the five
candidates.**

**Confirmed** (ADR-0014): "Kalshi serves nested market data for ~68 rolling days
per series; the 1,171 older `HIGHNY-` events return no markets and are not
retrievable. This window cannot be extended backwards from the API."

The 2026-07-17 landscape doc assumed, and the whole Kalshi pivot rests on, "free
historical trades + candlesticks since 2021." ADR-0014 is the first real
encounter with that assumption and it came back at **68 days**. This creates a
structural trap that reorders everything:

> **The longer a market's horizon, the fewer independent resolved outcomes fit
> inside Kalshi's retrievable history.** A 68-day ceiling gives 68 daily
> outcomes, ~2 monthly outcomes, or **0 seasonal outcomes.** Every "longer horizon
> is less efficient, therefore more edge" thesis is, on this venue, **unbacktestable
> by exactly the mechanism that makes it attractive.**

WP-0 must answer three questions empirically, not by reading docs:

1. Does `/markets?status=settled` with a time filter return markets older than
   ~68 days, for a **long-dated** series (try KXNOBELPEACE, KXHURCTOT,
   KXRAINNYCM) and for a **daily** one? ADR-0014's failure was retrieving markets
   *nested under old events*; a different query path may not have the same ceiling.
2. For a settled market retrieved that way, are **trades** and/or **candlesticks**
   still served, or only the final `result`? (**FLB-1 needs only `result` + traded
   prices — it can survive a candle blackout that kills every other candidate.**)
3. Measure the **listing-to-resolution window** for one non-NYC temperature series
   and for one monthly-rain series. Confirms Part 1.1's generalization and prices
   candidate MRAIN-1.

**If WP-0 returns "~68 days everywhere, no deep settled history": stop building
backtests.** The only honest path left is forward paper accumulating its own
history, which is a 6–12 month exercise before any verdict — and that is a
strategic decision for the user, not a work-package.

---

## Part 5 — Ranked shortlist (ranked by expected edge per dev-day)

### 1. FLB-1 — favorite–longshot NO-side harvest, historical study

- **Tickers:** all settled Kalshi markets, any category; the *live* target basket
  is KXTRUMPRESIGN, KXIRANDEMOCRACY, KXOAIAGI, KXERUPTSUPER, KXTRUMPIRAN,
  KXGREENLANDPRICE, KXNOBELPEACE, KXTRUMPPARDONS, KXTRUMPPARDON, KXTRUMPCOUNTRIES.
- **Observed (Confirmed, `ALL_ACTIVE_SERIES.txt`):** spreads $0.004–$0.04 across
  the basket — several *tighter* than the weather ladders. Combined 24h size
  **6,693** units; combined open interest **1,866,748** units (both re-added by a
  second route). Deep open interest, near-zero turnover: **positions are parked,
  not traded.**
- **Why mispricing might exist:** documented on this exact venue over 300k+
  outcomes (Part 3.1); mechanism is a preference for lottery-shaped payoffs, which
  is exactly the user's "people predict emotionally."
- **Pre-registered gate (in ADR-0012's style):** partition all settled markets
  retrievable in WP-0 into price deciles by **volume-weighted average traded
  price**. For each decile compute realized NO-side ROI **net of the Part 2 taker
  fee including the ceil-to-cent at a $100 order size**. **GO iff** the
  `[0.90, 0.99]` decile shows net ROI ≥ **+1.5%** with a **t-stat ≥ 2** computed on
  **event-clustered** standard errors (cluster = series, so 52 KXTRUMPPARDONS
  markets count as ~1 observation, not 52). **NO-GO** otherwise. Pre-register the
  margin *before* looking. Report the same table for the taker-at-ask fill
  assumption as the primary result and the mid fill as a diagnostic only.
- **Dev-days: 2–4.** Needs **no external data source** — only Kalshi's own settled
  markets and their traded prices, which `KalshiSource` already targets. This is
  the cheapest falsifiable gate available to this project.
- **Why ranked first:** lowest cost, tests an anomaly with real prior probability,
  and — uniquely — a NO-GO here retires an entire *class* of markets rather than
  one series.

### 2. MRAIN-1 — monthly precipitation accumulation ladders

- **Tickers:** KXRAINSEAM, KXRAINHOUM, KXRAINLAXM, KXRAINMIAM, KXRAINCHIM,
  KXRAINNYCM, KXRAINSFOM, KXRAINDENM, KXRAINDALM, KXRAINAUSM, KXRAINSTPM.
- **Observed (Confirmed):** KXRAINSEAM 250,580 lifetime / 12,534 in 24h / spread
  $0.03 but only **2 of 7** markets two-sided; KXRAINHOUM 145,388 / 8,880 / $0.01 /
  **6 of 7**; KXRAINLAXM 140,983 / 309 / spread **None** / **0 of 7** quoted;
  KXRAINSFOM 48,501 / 182 / **0 of 7**; KXRAINDENM **3 of 7**; KXRAINDALM **2 of 7**.
- **Why mispricing might exist — and it is the *right* mechanism.** This is the
  **only** candidate that directly satisfies ADR-0014's own named revisit
  condition: *"A series listed further ahead of resolution... this is the only
  high-value check left."* A monthly market is listed weeks ahead, so samples land
  in the long-lead band where forecast σ balloons — the band WP-7 proved is
  untradeable on daily temperature. Better still, the outcome is
  **partially resolved**: on day 20, `total = known_accumulation + residual`, so
  the benchmark is arithmetic plus a short-range QPF, not a subseasonal forecast.
  And the quoting data says **nobody is continuously quoting most strikes** —
  0/7 on two series versus 8–11/12 on every daily temperature ladder.
- **Pre-registered gate:** reuse `calibration.evaluate()` unchanged. Benchmark
  `p_forecast = P(accum_to_date + residual ∈ strike)` where `accum_to_date` is IEM
  precipitation strictly before `as_of` and `residual` is the station's
  point-in-time climatological distribution over the remaining days. **GO iff**
  Brier skill ≥ **+5%** (same margin as ADR-0012, so the numbers are comparable) on
  ≥1 series with n ≥ 400 samples across ≥ 3 distinct station-months. **Mandatory
  third verdict: `UNDERPOWERED`** if the sample floor is not met — because it very
  likely will not be (see risk).
- **Diagnostic that must ship with it:** fraction of (market, `as_of`) pairs
  carrying a two-sided quote. A GO on markets nobody quotes is not a GO.
- **Dev-days: 4–6** (+0.5 up front, non-negotiable: read `resolution_text` and
  confirm Kalshi settles on the NWS CLI/CF6 report versus IEM hourly sums — a
  silent resolution-source mismatch would corrupt the whole study exactly as a
  mis-parsed strike would, per ADR-0012).
- **Top risk:** the WP-0 ceiling. At ~68 retrievable days you get ~2 monthly
  cycles × 11 stations ≈ **18–22 independent station-months.** That is very likely
  underpowered, which is why the third verdict is mandatory.

### 3. HURSEAS-1 — seasonal storm-count ladders

- **Tickers:** KXHURCTOT (34,924 / 9 markets / 8 quoted / $0.04), KXHURCTOTMAJ
  (55,779 / 8 / 8 / $0.02), KXTROPSTORM (32,169 / 8 / 6 / $0.04), KXNAMEDSTORM
  (8,304 / 14 / 14 / $0.03), KXFIRSTHURRICANE (335,331 / 53 / 8 / $0.02, open
  interest 215,815). **Confirmed** from the data file.
- **Why mispricing might exist:** same partially-resolved accumulation structure as
  MRAIN-1, over a 6-month window, against public NOAA/CSU seasonal forecasts; and
  hurricanes are the most emotionally-traded weather product there is.
- **Gate:** identical Brier-skill construction, benchmark = Poisson on
  storms-to-date + climatological rate for the remaining season.
- **Dev-days: 5–8** (new plumbing: NHC storm archive).
- **Why ranked third despite a good mechanism:** **one season per year.** Even
  with perfect history you get ~5 seasons since Kalshi launched, and WP-0 will very
  likely say you get **one**. You cannot pre-register a powered gate on n=1.
  Genuine edge here would be undemonstrable, which for a stack whose entire value
  proposition is evidence-gated verdicts makes it unbuildable.

### 4. DROUGHT-1 — US Drought Monitor level ladders

- **Ticker:** KXDROUGHTLEVEL — 14 open markets, 257,804 lifetime size, 759 in 24h,
  25,271 open interest, $0.06 median spread, **10 of 14** quoted (**Confirmed**).
- **Why mispricing might exist:** the underlying is the weekly **US Drought
  Monitor**, a published, rule-based, human-authored index with extremely strong
  week-to-week autocorrelation, resolving weeks-to-months out. Highly modellable
  from public data, and slow enough that a snapshot stack is not disadvantaged.
- **Gate:** Brier skill of a persistence-plus-precipitation-anomaly benchmark
  versus price, ≥ +5%, n ≥ 300.
- **Dev-days: 4–7.** Same power problem as MRAIN-1 (weekly outcomes, so ~9–10
  independent updates inside a 68-day window) plus a new data source.

### 5. ECON-1 — CPI / payrolls statistic ladders

- **Tickers:** KXCPIYOY (569,962 / 89 markets / spread $0.09 / 28 quoted),
  KXECONSTATCPIYOY (182,404 / 84 / $0.08 / 16), KXPAYROLLS (94,056 / 65 / $0.02 /
  **65 of 65** quoted), KXJOBLESSCLAIMS (3,757 / 9 / $0.05 / 9). **Confirmed.**
- **Why mispricing might exist:** this is the one category where the FLB literature
  *specifically* reports the bias present (Inflation, Employment) — and
  **specifically reports it absent in Fed / interest-rate markets.**
- **Dev-days: 6–12.** Already on `roadmap.md` as v0.3, gated on its own calibration
  study. Ranked last because you compete against professional nowcasters running
  public products (Cleveland Fed) on a monthly release cadence — one outcome per
  month means the same power problem, and the model is genuinely hard.

---

## Part 6 — What to NOT build (at least as valuable as the list above)

- **Daily temperature ladders in any other city.** Part 1. The blocking constraint
  is the ~38h listing window, which is a template property. Nineteen cities of the
  same dead thing is still dead. *Saves ~10–15 dev-days of re-running WP-7.*
- **Hourly directional temperature** (KXTEMPNYCH, KXTEMPLAXH, KXTEMPCHIH,
  KXTEMPDCH, KXTEMPAUSH, KXHIGHNYD). **Confirmed:** KXTEMPDCH shows $0.84 median
  spread on 700 lifetime size; KXTEMPCHIH $0.39 on 1,636. This is a nowcasting
  latency race with catastrophic spreads, against the exact constraint the stack
  rules out (non-HFT, snapshot cadence, ADR-0006).
- **KXFEDDECISION and all Fed / rate markets** — despite being the largest series
  on the venue (37.5M lifetime size). The FLB literature reports the bias
  **absent** here specifically. Big and liquid is not the same as exploitable; it
  is usually the opposite.
- **Tail-catastrophe markets as a directional line** (KXERUPTSUPER, KXEARTHQUAKE*,
  KXVEI4, KXTSUNAMI). They *look* like the purest FLB targets and they may well be,
  but you can never resolve enough of them to prove it, and the loss is 100% of
  notional in the one world where you are wrong. Include them in FLB-1's *study*
  population; do not build a line around them.
- **Sports and Entertainment.** Not probed in this pull, deliberately. 3,005 +
  2,524 series, sharpest competition on the venue, 1-cent spreads on marquee
  events, and the sweep is dominated by tens of thousands of parlay combinations.
  The 2026-07-17 doc already ruled these out; nothing here reopens it.
- **A market-making / Liquidity-Incentive line.** Still parked, still needs ~$10k+.
  But note the update: the maker fee is 25% of taker, not zero, so the LIP
  economics in `roadmap.md` v0.3 need re-deriving before that item is costed.
- **Any new ingestion adapter before WP-0 returns.** If the retrievable history is
  ~68 days, the correct next move is a strategic conversation about forward paper,
  not more plumbing.

---

## Part 7 — Capacity check for the top candidate (FLB-1)

Can a sub-$10k bankroll deploy meaningfully? **Yes in absolute size; no in a way
worth the effort.** All figures **Confirmed** arithmetic on the pulled data,
under the Part 3.3 assumption of a 3-point bias.

**Available flow.** Summed 24h size across the eight named "emotional" series:
`262 + 289 + 7 + 1,202 + 246 + 990 + 2,094 + 1,603 = 6,693` units/day. At ~$0.95
that is **~$6,358 of daily notional turnover across the entire basket.** Deploying
$8,000 means being ~100% of a full day's volume of every one of these markets at
once. At a realistic 10–20% participation rate: **6–12 trading days to build the
book**, pushing prices against yourself the whole way. Open interest is not the
constraint (**1.87M units parked**); **turnover is.**

**Portfolio outcome.** 20 positions × $400 notional = $8,000; 421 units each at
$0.95.

```
EV per position   = 421 × $0.026675  = $11.23      →  20 positions = $224.60 / yr
win  per position = 421 × $0.046675  = $19.65
loss per position = 421 × $0.953325  = $401.35     (one loss ≈ 20 wins)

P(0 losses) = 0.98^20 = 0.6676   → +$393.00
P(1 loss)   = 0.2725             → −$28.00
P(2 losses) = 0.0528             → −$449.00
P(at least one losing position)  = 33.2%
```

**Read that carefully.** The *best realistic case* is **+$393 on an $8,000
bankroll (+4.9%)**, and **roughly one year in three is a losing year.** Against
that: Kalshi's ~3.25% APY on the same $8,000 pays **$260 riskless** (they stack —
you would collect ~$485 total — but $260 of it requires no strategy, no code, and
no drawdown). If the true bias is 1 point rather than 3, expected edge falls to
**~$56/yr** and the fee becomes a third of it.

**Verdict on capacity: the edge, if real, is uncapturable at a size worth the
effort — on the long-dated markets.** It is *not* uncapturable in general: the
same anomaly on **short-dated, high-turnover markets** (which resolve weekly or
daily, so the same capital recycles 20–50× a year and the positions are far less
correlated) turns a 2.8%-per-resolution edge into a genuinely interesting
annualized number and simultaneously fixes the statistical-power problem. **That
is the actual recommendation hiding inside the user's question:** the FLB is real,
but you want it on *fast* markets, not on the emotionally-charged slow ones — and
the emotionally-charged slow ones are precisely where a retail trader's intuition
sends them. FLB-1's decile study should therefore report results **split by days
to resolution**, which costs nothing extra and is the most decision-relevant cut
in the whole exercise.

---

## Part 8 — The strongest argument against this document

Stated as its own section so it cannot be buried.

**The WP-7 benchmark never used same-day observations, and neither does anything
here.** ADR-0012's benchmark was a Gaussian over MOS forecast error. At the 0–38h
leads that actually trade, the dominant information is not the forecast at all —
it is *what the temperature has already done today*, plus the latest model run. A
model that ingests intraday ASOS observations would be a far stronger benchmark
than the one that produced the −43.6% skill, and it is entirely possible that WP-7
measured "a stale forecast loses to the market" rather than "no public information
beats the market."

I am not recommending that build, for one reason: it is a **freshness race**
against the same automated quoter that is already posting two-sided markets on 20
cities simultaneously, and this stack has explicitly given up latency (ADR-0006
snapshot cadence, non-HFT, `roadmap.md`). Losing a freshness race more slowly is
not an edge. But if the user's real belief is "the market is slow," this — not
another city — is the honest test of it, and it would cost ~6–10 dev-days.

**Second-strongest:** I could not read the Bürgi–Deng–Whelan tables directly. The
entire Part 3 dollar analysis rests on a 3-point bias I extrapolated from a
secondary summary. **Retrieving that table is a 30-minute task that should precede
FLB-1**, and if the real bias in the 0.90–0.99 bucket is under ~0.5 points, FLB-1
should not be built at all.

---

## Open questions for the user

1. **Does the ~3.25% Kalshi APY survive execution through IBKR?** *(Assuming: it
   does not — it reads as a Kalshi-native, Kalshi-Klear-funded program.)* If it
   does not, the IBKR path in `roadmap.md` costs ~3.25%/yr of carry on every
   long-dated position — **larger than the edge FLB-1 is chasing** — and the venue
   access decision should flip to direct Kalshi. This is now the highest-value
   unresolved item in the project.
2. **Is the goal an edge you can *prove*, or an edge you're willing to take on
   priors?** *(Assuming: prove — that is what ADR-0012 and this whole stack are
   built for.)* Every candidate in Part 5 is power-limited by Kalshi's retrievable
   history. If forward paper over 6–12 months is acceptable, the shortlist
   reorders toward MRAIN-1 and HURSEAS-1. If it is not, only FLB-1 survives.
3. **Confirm the $0.035/contract fee cap is stale.** *(Assuming: stale or
   category-specific — under a 0.07 coefficient the maximum fee is $0.0175, so a
   $0.035 cap cannot bind.)* Needs the primary fee-schedule PDF, which returned
   HTTP 429 twice this session.

---

## Sources

Fetched or searched this session (2026-07-25):

- [Fees — Kalshi Help Center](https://help.kalshi.com/en/articles/13823805-fees) — confirms maker/taker structure exists; refers formulas to the PDF
- [Kalshi Fee Schedule PDF (July 2026, 7.7.26 update)](https://kalshi.com/docs/kalshi-fee-schedule.pdf) — **HTTP 429, not retrieved**; title surfaced via search index
- [Kalshi Fees 2026: Fee Schedule, Maker & Taker Rates — pm.wiki](https://pm.wiki/learn/kalshi-fees-explained)
- [Kalshi Fees Explained (2026) — Market Math](https://marketmath.io/blog/kalshi-fees-guide-2026)
- [APY on Kalshi — Kalshi Help Center](https://help.kalshi.com/en/articles/13823847-apy-on-kalshi) — 3.25% variable, accrues on collateral for open positions, $250 minimum, US only
- [Makers and Takers: The Economics of the Kalshi Prediction Market — CESifo/ifo](https://www.ifo.de/en/cesifo/publications/2026/working-paper/makers-and-takers-economics-kalshi-prediction-market) — abstract fetched verbatim
- [Same paper — RePEc/MPRA 126350](https://ideas.repec.org/p/pra/mprapa/126350.html)
- [Same paper — author's PDF](https://www.karlwhelan.com/Papers/Kalshi.pdf) — tables **not** readable this session
- [The economics of the Kalshi prediction market — CEPR/VoxEU](https://cepr.org/voxeu/columns/economics-kalshi-prediction-market) — HTTP 403; figures via search summaries only
- [Pricing and Losses on the Kalshi Prediction Market — Karl Whelan](https://www.karlwhelan.com/sports-betting-kalshi-prediction-market/)
- [Zero-Price Contracts and the Favorite-Longshot Bias in CPI Prediction Markets — Krause, SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7087538)
- [Information Efficiency Across Macroeconomic Prediction Markets: Evidence from Kalshi](https://www.researchgate.net/publication/409472804_Information_Efficiency_Across_Macroeconomic_Prediction_Markets_Evidence_from_Kalshi)
- [Can Interest-Bearing Positions Solve the Long-Horizon Problem in Prediction Markets? — Maresca, arXiv:2602.21091](https://arxiv.org/abs/2602.21091)

In-repo, read this session: `CONTEXT.md`, `docs/product/requirements.md`,
`docs/product/roadmap.md`, `docs/research/2026-07-17-polymarket-edge-landscape.md`,
`docs/architecture/decisions/0012-calibration-edge-room-brier-skill-gate.md`,
`docs/architecture/decisions/0014-wp7-gate-result-no-go.md`, `src/fees.py`.

Live Kalshi pull, 2026-07-25 (`api.elections.kalshi.com/trade-api/v2`):
`ALL_ACTIVE_SERIES.txt` (347 series with open markets), `WEATHER_SERIES.txt` (83
active Climate-and-Weather series), `climate_catalog.txt` (214 KX Climate-and-
Weather series including dormant). **Caveat respected throughout:**
`liquidity_dollars` returned 0 across the board and is omitted as unreliable;
Sports and Entertainment were not probed; category totals from the series endpoint
include dormant series and are not used as evidence of anything tradeable.

> **Evidence caveat.** The load-bearing claims here are of three kinds. (a) The
> **Kalshi market data** — series, volumes, spreads, quote counts — is a live pull
> and is as good as the API. (b) The **fee arithmetic** in Part 2 and the
> **capacity arithmetic** in Part 7 I performed and re-derived by a second route;
> they are as good as the formula, and the formula is confirmed by three
> independent secondary sources plus this repo's own `fees.py`, but **not** by the
> primary PDF, which I could not retrieve. (c) The **favorite–longshot magnitudes**
> in Part 3.1 are secondary summaries of a paper whose tables I could not read, and
> the 3-point bias in Part 3.3 is my extrapolation from one of them. Part 8 names
> the consequence: **retrieve that table before spending a dev-day on FLB-1.** No
> single figure in this document should move capital on its own.
