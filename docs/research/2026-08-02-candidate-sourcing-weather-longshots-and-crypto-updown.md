# Candidate sourcing after ADR-0029: two external leads, and where the next candidate actually comes from

> Commissioned **2026-08-02**, hours after [ADR-0029](../architecture/decisions/0029-mrain1-gate-result-no-go-and-this-one-is-powered.md)
> closed MRAIN-1 with a powered NO-GO and observed that *"the next decision is a
> sourcing decision rather than an engineering one."* This document answers that.
>
> **Two user-supplied leads are evaluated in full** (Part 1: cheap YES on extreme
> temperature; Part 2: Polymarket crypto Up/Down bots), then ranked against
> in-repo alternatives (Parts 3–6).
>
> **Date verification.** Not assumed. **Confirmed** live this session: Kalshi
> served an *open* market `KXBTC15M-26AUG021100-00` with
> `open_time = 2026-08-02T14:45:00Z` and `close_time = 2026-08-02T15:00:00Z`;
> `GET /historical/cutoff` returned `market_settled_ts = 2026-06-03T00:00:00Z`
> (60 days back, consistent with Kalshi's documented ~3-month live window); a
> Polymarket country-availability page carried "Last updated July 29, 2026".
> **The current date is 2026-08-02.**
>
> **Evidence discipline** (inherited from the three prior research docs): every
> load-bearing claim carries **Confirmed** (verified this session against a source
> I fetched, a repo file I read, or arithmetic I performed and re-derived by a
> second route), **Likely (unverified)**, or **Assuming**.
>
> **Both primary sources for Lead A are unreadable.** `x.com/PolyDekos/status/2082754710314922360`
> and `x.com/RetroValix/status/2080699000919843157` both returned **HTTP 402** to
> the commissioning session. **Every performance figure attributed to Lead A in
> this document is an unverified third-party claim relayed through a brief.** The
> same applies to the five-account teardown in Lead B, which was pasted text with
> no retrievable source. Nothing in either lead is marked Confirmed except
> arithmetic I performed on the claimed numbers themselves.
>
> **Carried forward, not re-derived** ([ADR-0015](../architecture/decisions/0015-kalshi-fee-schedule-verified-maker-path.md)):
> Kalshi taker `0.07·C·P·(1−P)`, maker `0.0175` on maker-fee-enabled series and
> **zero** elsewhere, `0.035` on S&P/Nasdaq index markets, **ceil to the next
> cent**, **no per-contract cap**. Polymarket US taker `Θ = +0.06`, maker
> `Θ = −0.0125` (**a rebate, paid to you**).
>
> **Scope rule.** This document proposes no MVP, writes no ADR, and edits no
> existing file. It reopens nothing closed by an ADR; where it touches a closed
> candidate it says so explicitly and hands the decision back.

---

## Part 0 — Verdict

**Both external leads are NO-GO for this user, and neither fails for an
interesting reason: both live on venues a US person cannot legally trade. But the
work of checking them surfaced three things that are worth more than either lead,
and one of them is a candidate the project believes it closed and did not.**

**1. Lead A is unreachable, and its reachable analog is already measured at
−90%.** **Confirmed:** six of the seven cities named (London, Paris, Amsterdam,
Milan, Munich, Madrid) exist as temperature markets only on
**polymarket.com — Polymarket Global**, which **Confirmed** from Polymarket's own
help centre (modified 2026-07-28) and its own API geoblock documentation is
**closed to US persons** (help centre: `US` appears in the blocked-countries
table; API docs: `US` is *close-only* — "users can close existing positions but
cannot open new ones, on both the frontend and the API"). **Confirmed:** Kalshi
lists **zero** non-US city temperature series. **Confirmed:** Polymarket US lists
temperature contracts for exactly **five US cities** — NYC (KNYC), San Francisco
(KSFO), Miami (KMIA), Chicago (KMDW), Los Angeles (KLAX) — settled on the NWS
Daily Climate Report. The strategy as described cannot be executed by this user
anywhere. Separately, the repo has **already measured this exact trade shape on
the reachable venue**: [ADR-0019](../architecture/decisions/0019-flb1-decile-study-real-but-sub-gate-edge-no-go.md)'s
mirror check, `[0.01, 0.10]` price band on Kalshi weather ladders, **net ROI
−90.31%, t = −11.31 across 402 families**. Buying cheap contracts on temperature
ladders is the single worst-performing thing this project has ever measured.

**2. Lead B is unreachable, and its central claim is false as an identity.**
**Likely (unverified):** the five `0x…` accounts are Polygon wallets, i.e.
Polymarket Global. **Confirmed:** every 5-minute and hourly crypto Up/Down URL
that surfaced is `polymarket.com`, the geoblocked venue. But the more useful
finding is arithmetic, and it does not depend on the venue at all. On a binary
market, **buying NO at price `q` is identically selling YES at `1 − q`**.
Therefore a pair assembled at prices `p` (YES) and `q` (NO) has
`profit = 1 − p − q = (1 − q) − p`, i.e. **the profit on a "sub-$1 pair" is
exactly and only the directional round-trip P&L on the first leg.** The
teardown's headline — *"the edge is position structure, timing and inventory
management, not direction-calling"* — is **false as stated**: the "protected
base" is real as a *risk* property and irrelevant as a *P&L* property. There is
no structural profit hiding in the pairing.

**3. DROUGHT-1 was never re-checked after ADR-0023, and the project believes it
was.** [ADR-0023](../architecture/decisions/0023-historical-tier-retracts-the-68-day-ceiling.md)
explicitly listed DROUGHT-1 as needing a re-check against `/historical/*`;
[ADR-0027](../architecture/decisions/0027-flb1-emotional-basket-more-data-still-underpowered.md)
then declared *"every candidate ADR-0023 flagged as unconfirmed is now checked"*
and named four candidates, **not including DROUGHT-1**; ADR-0029's six-row
closing table does not list it either. **I checked it live this session and it
stays dead, for a reason nobody had:** `KXDROUGHTLEVEL` has
`frequency: "one_off"`, **1 distinct event ticker** and **16 markets** in all of
Kalshi's history (`/historical/markets` returns zero; the live tier returns 16
across one event). The 2026-07-25 doc's premise — *"the weekly US Drought
Monitor… ~9–10 independent updates inside a 68-day window"* — was **wrong about
the product**. It is a one-off multi-month state-level window, not a weekly
ladder. Cross-state markets on one drought episode are one cluster, not fifty.
**Closed on a correct reason; the bookkeeping gap is now closed too.**

**4. The recommendation: stop sourcing candidates from forecastable phenomena and
start sourcing them from venue mechanics — beginning with the maker side, which
this project has never costed on either venue.** All six closed candidates were
**taker** strategies whose thesis was "my public-data model beats the price."
Every one competed against an automated quoter running the same free public data,
and every one lost or came in too small. Meanwhile the single largest unevaluated
number in the repo sits on the other side of the book. **Confirmed arithmetic,
re-derived two ways below:** on a two-legged binary trade at mid, a **Kalshi
taker** needs the implied probability to move **+4.50 points** in their favour to
break even; a **Polymarket US maker** breaks even at **−1.625 points**, i.e. can
be wrong by 1.6 points and still profit. **The side of the book is worth 6.125
percentage points of probability. The venue is worth 0.625–1.5.** The 2026-07-28
refresh found the venue half of that and correctly called it *"larger than
ADR-0019's entire measured edge."* The side half is four times larger again and
nobody has costed it.

**The one thing to do next:** a **1–2 dev-day, zero-capital, read-only
measurement of resting-order reward yield**, starting on Kalshi because
`GET /incentive_programs` is reachable **unauthenticated today** (**Confirmed** —
I called it this session; it returned **102 live liquidity programs**), then on
Polymarket US once an account exists. Unlike every prior candidate, this one has
**no statistical power problem at all**: the reward is a *published deterministic
formula*, and the only unknown input — competing resting size — is directly
observable from the order book in days, not months.

Full ranking in Part 6. What not to build in Part 8. The honest case against this
document in Part 9.

---

## Part 1 — Lead A: "cheap YES on near-certain temperature extremes"

**The claim, restated so it can be attacked:** a trader made **+$48,213 over ~2
months across 1,546 trades** buying temperature-market contracts at **1.6–50¢**
and holding to $1 settlement, in **London, Paris, Amsterdam, Milan, Munich,
Madrid and New York**, entering "only when the forecast is almost certain."
**Unverified third-party claim** — both source URLs returned HTTP 402 to the
commissioning session and are not retrievable.

### 1.1 Venue reachability — this closes it, and everything below is diagnostic

**Six of the seven cities do not exist on any venue this user can trade.**

| venue | European city temperature markets? | reachable by a US person? |
|---|---|---|
| **Polymarket Global** (`polymarket.com`) | **Yes** — **Confirmed:** a third-party tracker enumerating Polymarket weather markets lists **44 cities across 27 countries**, naming **London, Paris, Amsterdam, Milano, Munich, Madrid**, plus Helsinki, Warsaw, Istanbul. Every temperature-market URL returned by search this session was `polymarket.com/...`. | **No.** See below. |
| **Polymarket US** (`polymarket.us`, QCX LLC) | **No** — **Confirmed** from `docs.polymarket.us/faqs/weather-faqs`: **five US cities only** — NYC `KNYC` (Central Park), San Francisco `KSFO`, Miami `KMIA`, Chicago `KMDW` (Midway), Los Angeles `KLAX`. Settlement is *"the official NWS Daily Climate Report (CLI) published by the local Weather Forecast Office"* at 08:00 ET the following day. NWS is a US agency; the settlement source itself forecloses non-US cities. | Yes |
| **Kalshi** | **No** — **Confirmed** by a live pull of `GET /series?category=Climate and Weather`: 28 city-temperature series, **all US** (Dallas, Miami, Minneapolis, Phoenix, DC, Houston, LA, Austin, Las Vegas, Denver, NYC, Chicago, Boston, Philadelphia, Seattle, San Antonio, New Orleans). **Zero** non-US city temperature series. | Yes |

**Polymarket Global is closed to US persons, confirmed from two Polymarket
primary sources this session:**

- `help.polymarket.com/en/articles/13364163-geographic-restrictions`, structured
  modification date **2026-07-28**: the **US appears in the blocked-countries
  table** (country code `US`), alongside 38 others including France and Germany.
- `docs.polymarket.com/api-reference/geoblock`: the US is classed **close-only** —
  *"Users can close existing positions but cannot open new ones, on both the
  frontend and the API."*

**Likely (unverified):** the underlying condition is the 2022 CFTC settlement
($1.4M, geoblock + a ToS prohibition on US persons), and the **2026-04-28
petition to the CFTC to lift it has not been granted** — a country-availability
page updated **2026-07-29** states the restriction "applies to the global crypto
platform, not the regulated US exchange." No approval has been reported. The
2026-07-28 refresh's Part 5 conclusion carries forward unchanged, now with a
fresher check.

> **Verdict on reachability: Lead A is unreachable for this user.** No VPN or
> workaround is contemplated (2026-07-17 doc, hard scope rule). The remaining
> sub-sections exist because the *mechanism* claim is portable to the two
> reachable venues even though the *markets* are not.

### 1.2 The favourite–longshot contradiction, and which reading I believe

Lead A is a strategy of **systematically buying contracts at 1–34¢**. That is the
side the favourite–longshot bias says is expensive, and this project has measured
that bias on its own data twice.

**What the repo already knows, all Confirmed by reading the ADRs:**

| measurement | source | result |
|---|---|---|
| `[0.00, 0.10)` price bucket, Kalshi weather ladders, 2,406 observations, mean price **0.011** | ADR-0019 | win rate **0.001**, pre-fee ROI **−88.25%** |
| Mirror gate `[0.01, 0.10]`, family-clustered on 402 dates | ADR-0019 | **net ROI −90.31%, t = −11.31** |
| Same population re-run on 5 years / 5,704 families | ADR-0025 | high-price band stable at +1.15%, t=24.43; population confirmed, mirror band not re-quoted |
| Bürgi–Deng–Whelan, 2021–Apr 2025, 313,972 price observations | ADR-0017 | *"average loss rates for contracts costing 10c and under are over 60%"* |

**The break-even arithmetic that makes this concrete. Confirmed, computed here:**
at a mean traded price of **1.1¢** the break-even win rate is **1.1%**; the
observed win rate was **0.1%**. The population is **~11× overpriced**. Adding
Kalshi's taker fee at a 2¢ entry (Part 1.4) raises the required win rate to
**2.154%** against a population base rate of 0.1% — a **~21× selection factor**
before the first dollar of profit.

**The four candidate explanations, ranked, with the one I believe first:**

1. **(d) Structural — repricing lag, not forecasting skill. This is what I
   believe, and there is direct evidence for it.** **Confirmed:** a
   widely-circulated how-to for exactly this strategy (Medium, "People Are Making
   Millions on Polymarket Betting on the Weather") describes the mechanism in its
   own words: trade **NYC and London** daily-high markets, act **"when 3 or more
   models agree"** (GFS/ECMWF via Tropical Tidbits and Windy), buy **YES below
   $0.15** or **NO above $0.45**, and exploit a *"window of opportunity"* where
   market prices lag model updates by **"minutes or maybe hours."** That is a
   **freshness race**, and it is the exact thing the 2026-07-25 doc's Part 8
   already examined and declined: *"it is a freshness race against the same
   automated quoter… Losing a freshness race more slowly is not an edge."* This
   stack has explicitly given up latency (ADR-0006 snapshot cadence).
2. **(c) Selection / survivorship.** The account was found *because* it won. 1,546
   trades reported by an observer with no denominator. **The base rate of accounts
   that ran a buy-cheap-longshots strategy and lost is unknown and unknowable from
   the post** — and the population statistic in ADR-0019 says the modal outcome of
   that strategy is −90%. I rank this second only because explanation (d) has
   direct textual evidence and this one has none either way.
3. **(a) Genuine forecast skill exceeding the bias.** Possible, and it is what the
   post claims. Against it: ADR-0014 measured the Kalshi price as **more accurate
   than a public-forecast benchmark at every lead that exists to trade**
   (Brier skill −15.0% to −967.6%), and the gap was **flattening, not closing**,
   at the oldest lead. Beating a market that already beats the public forecast
   requires private information or a better model than ECMWF/GFS consensus —
   which is precisely what the strategy description says it does *not* have.
4. **(b) European venues have a different bias sign.** No evidence either way, and
   **untestable from here** because the venue is unreachable. Note that Polymarket
   Global also geoblocks France and Germany (**Confirmed**, same help-centre
   table), so "European markets priced by Europeans" is not a safe assumption.

### 1.3 Does ADR-0014 kill this, or reopen it? — Neither, on Kalshi; **partially reopen** on Polymarket US

ADR-0014's "What would justify revisiting" names exactly three conditions:
**(i) a series listed further ahead of resolution**, **(ii) a station with
materially worse public forecasts**, **(iii) a cold-season sample.** Taken in
order:

**(i) Listing lead time — the binding constraint, and the only one that matters.**
**Confirmed** (ADR-0016): Kalshi's daily-temperature listing window is
**42.0 hours on all 414 KXHIGHLAX markets, zero variance** — a series-template
constant. **Confirmed** (ADR-0014): the forecast-error σ at KNYC only balloons
past 72h (2.45°F at 12–24h → 3.25°F at 48–72h → 5.76°F at 72–120h), and the
window where a forecast edge could exist is a window in which the Kalshi market
does not exist.

**Likely (unverified): Polymarket lists daily temperature markets "for the next 1
to 3 days."** Two independent secondary sources this session say so (a
strategy write-up and a search synthesis). If that holds on **Polymarket US** —
which is reachable, and whose five stations are `KNYC`, `KSFO`, `KMIA`, `KMDW`,
`KLAX`, of which **four already exist in `weather_ingest.STATIONS`** — then a
**72-hour** listing window satisfies ADR-0014's condition (i) on a venue this
user can trade, with an ingestion pipeline that is already built and tested.
**This is the single most valuable thing Lead A produced, and it is a
consequence of checking the lead rather than of the lead itself.** It is
measured, not assumed, in the pre-registered gate in Part 7.2 — with an abort
condition, because 72h is only 30h more than Kalshi's 42h and ADR-0014's own
Brier-by-lead table was **flattening** (−15.8% at 24–30h → −15.0% at 30–36h), not
converging.

**(ii) Worse public forecasts — this cuts the wrong way and the brief is right to
flag it.** ADR-0014's logic is that edge room requires the **market** to be
uninformed, not the forecast to be bad. European public forecasts are if anything
**better** than the US MOS baseline this project used (ECMWF is the reference
global model; the datapolymarket tracker itself advertises a *"5-model ensemble
(ECMWF, GFS, ICON, JMA, UKMO)"* — **Confirmed** from its own page). Better public
forecasts **reduce** edge room, because the quoter reads them too. Condition (ii)
is not satisfied by European cities; if anything it is anti-satisfied.

**(iii) Cold season.** Untested, and unaffected by either lead. Kalshi's
`/historical/markets` now reaches 2021 (ADR-0023), so a cold-season re-run of
ADR-0014 is *possible*. It is not recommended — see Part 8.

### 1.4 Bankroll arithmetic, and a correction to the brief

**The claimed trades, checked. Confirmed arithmetic, each figure computed two
ways:**

| claimed | stake → proceeds | claimed return | my check | implied entry price |
|---|---|---|---|---|
| trade 1 | $73.76 → $3,659.68 | +4,861% | `(3659.68 − 73.76)/73.76 = 48.6106` → **+4,861.1%** ✓ | `73.76/3659.68 = ` **2.015¢** |
| trade 2 | $76.89 → $2,976.00 | +3,770% | `(2976.00 − 76.89)/76.89 = 37.7047` → **+3,770.5%** ✓ | `76.89/2976.00 = ` **2.584¢** |
| trade 3 | $45.00 → $2,056.37 | +4,470% | `(2056.37 − 45.00)/45.00 = 44.6971` → **+4,469.7%** ✓ | `45.00/2056.37 = ` **2.188¢** |

The three return percentages are internally consistent. **The headline "1.6¢" is
not:** the implied entries are **2.02–2.58¢**, 26–61% above it. Small, but it is
the only internal check available on an unverifiable post, and it fails. Trade 1
implies **3,659 contracts** — not 4,610 as a 1.6¢ entry would give.

**Position sizing at <$10k.** At a ~2¢ entry, $73.76 buys ~3,659 contracts and a
full $8,000 deployment buys **~397,000 contracts**. **Confirmed** from the live
Kalshi pull: a single daily-temperature ladder city trades on the order of
**70,000–338,000 units of lifetime size** (2026-07-25 doc, `WEATHER_SERIES.txt`).
So $8,000 at 2¢ is **more than an entire city-day's turnover**. Depth, not
capital, is the constraint — the same conclusion the 2026-07-25 doc reached for
FLB-1 (Part 7). Sizing at 2¢ is only viable in small tickets across many
markets, which is exactly where the fee rounding used to bite.

**The ceil-to-cent tax at low prices — and the brief's hypothesis that it "may be
decisive on its own" is wrong.** **Confirmed arithmetic.** Raw fee per contract at
`P = 0.02` is `0.07 × 0.02 × 0.98 = $0.0013720`.

| order size | raw fee | charged (ceil to cent) | rounding uplift | fee as % of the order's notional |
|---|---|---|---|---|
| 1 | $0.001372 | $0.01 | +629% | **50.0%** |
| 10 | $0.013720 | $0.02 | +45.8% | **10.0%** |
| 100 | $0.137200 | $0.14 | +2.0% | **7.00%** |
| 146 | $0.200312 | $0.21 | +4.8% | 7.19% |
| 1,000 | $1.372000 | $1.38 | +0.58% | **6.90%** |
| 3,659 | $5.020148 | $5.03 | +0.20% | **6.87%** |

**The rounding stops mattering above ~146 contracts (~$2.92 of notional).** It is
brutal only on sub-$1 tickets, which nobody would place. **The decisive number is
the flat coefficient, not the rounding:**

```
fee / notional  =  0.07 × (1 − P)          (re-derived: 0.07·P·(1−P) / P)

P = 0.016  →  6.888%      P = 0.10  →  6.300%
P = 0.020  →  6.860%      P = 0.20  →  5.600%
P = 0.050  →  6.650%      P = 0.34  →  4.620%
```

**A 2¢ entry on Kalshi pays 6.86% of notional in fees.** Against a 49× payoff
that is immaterial to a winner (+4,861% becomes +4,443%). Against the *hit rate*
it is not: the break-even win rate rises from **2.0155%** to **2.1538%**, a
**6.86% relative increase in the accuracy required**. On Polymarket Global's
weather `feeRate = 0.05` the same figure is **4.90%** (**Likely (unverified)** —
carried from the 2026-07-17 doc, not re-fetched this session).

**Read plainly: the fee is not what kills Lead A. The venue is, and the ~21×
selection factor is.**

---

## Part 2 — Lead B: Polymarket crypto Up/Down bots

### 2.1 Venue reachability — lead with it, because it is probably fatal

**Likely (unverified):** the three hex accounts (`0xb55f…`, `0x50f7…`,
`0xce25…`) are **Polygon wallet addresses**, which exist only on **Polymarket
Global**. `powerwinner` and `mo-money` are Polymarket Global display names.
**Confirmed:** every 5-minute, 15-minute, hourly and 4-hour crypto Up/Down URL
surfaced this session is on `polymarket.com` — the geoblocked venue (Part 1.1).

**What each reachable venue actually lists. Confirmed by live API pulls this
session:**

| venue | short-horizon crypto Up/Down | evidence |
|---|---|---|
| **Kalshi** | **Yes — 15-minute binary Up/Down across at least 8 coins.** `GET /series?category=Crypto` returned **`KXBTC15M` "Bitcoin price up down"**, **`KXETH15M` "ETH 15M price up down"**, `KXXRP15M`, `KXDOGE15M`, `KXBCH15M`, `KXTON15M`, `KXNEAR15M`, `KXCRYPTOLEAD15M` — all `frequency: "fifteen_min"`. Also **hourly**, but hourly is a *strike ladder* (`KXBTCD`, tickers like `-T72299.99`), not a binary. **No 5-minute product exists.** | live API |
| **Polymarket US** | **Unresolved — probably yes as a category, granularity unknown.** **Confirmed:** `polymarket.us/rewards` lists **74 liquidity-reward programs across 16,893 markets**, and its category list includes **"Crypto: Coins"** alongside Sports, Politics, Macro/Economics, Tech & Finance, Geopolitics, Culture and **Climate/Weather**. **Confirmed:** an August-2026 platform review that *does* correctly distinguish the two venues lists Sports, Politics, Economics, Culture and Weather for the US app and **does not mention crypto price markets**. I could not resolve this: `gateway.polymarket.us/v1/markets` is documented `security: []` (unauthenticated) but returned **HTTP 403** to this session's fetcher — plausibly a bot filter rather than auth. | mixed |

**Kalshi `KXBTC15M`, live, 2026-08-02T~15:00Z. Confirmed:**

```
ticker        KXBTC15M-26AUG021100-00    "BTC price up in next 15 mins?"
open_time     2026-08-02T14:45:00Z       close_time  2026-08-02T15:00:00Z
yes_bid 0.36  yes_ask 0.37   no_bid 0.63  no_ask 0.64
volume 200,368 (mid-life)   open_interest 85,619
price_ranges  [0.000–0.100 step 0.001] [0.100–0.900 step 0.010] [0.900–1.000 step 0.001]
```

Two facts worth recording independently of Lead B:

- **`yes_ask + no_ask = 1.01`, `yes_bid + no_bid = 0.99`.** A simultaneous
  complete-set purchase costs **$1.01 plus ~$0.032 of fees** — 4.2% underwater.
  There is no static arb.
- **Kalshi's sub-penny tick rollout has reached crypto.** Ticks are **0.1¢ below
  10¢ and above 90¢**, still 1¢ in the middle. This closes **open question 3 of
  the 2026-07-28 refresh** for at least one series: the rollout is real and
  live, and any future price-grid assumption must read `price_ranges`. Note the
  centre of the book is *unaffected*, so the 1¢ minimum spread at mid stands.

**Settled 15-minute markets are retrievable with full data. Confirmed:** a live
`status=settled` pull returned markets with results and volumes of
**777,000–1,790,000 units each**, and
`GET /series/KXBTC15M/markets/{ticker}/candlesticks?period_interval=1` returned
**15 one-minute candles** for a settled market, each carrying **`yes_bid` and
`yes_ask` OHLC in dollars** plus price, volume and open interest. Everything a
pair-cost study needs is already served by an endpoint `KalshiSource` already
implements.

> **Verdict on reachability: archetypes 1, 2, 4 and 5 have a structural analog on
> Kalshi's 15-minute binaries. Archetype 3 does not exist on Kalshi at all** — see
> 2.2.

### 2.2 Honest capability assessment, archetype by archetype

**Archetype 3 (`0x50f7`, >93% of capital deployed at 98–99.9¢ a few seconds after
the interval ends but before settlement) is not expressible on Kalshi.**
**Confirmed:** `KXBTC15M-26AUG021100-00` has `close_time = 15:00:00Z`, which is
the interval end. Kalshi markets stop trading at `close_time`. **Likely
(unverified):** there is therefore **no post-interval, pre-settlement trading
window** on Kalshi's 15-minute binaries, and the entire archetype-3 edge — buying
a known outcome in the gap between determination and settlement — has no gap to
live in. Even where it exists, it is a race measured in seconds against other
bots, and this repo is a **snapshot-based research stack with no live execution
path whatsoever** (`place_live` raises, ADR-0001). **Do not build this.**

**Archetypes 2 and 5 (temporal arbitrage, "combined pair cost below $1") are
directional scalps.** This is the section's main finding and it is an identity,
not an opinion.

```
On a binary market, one YES + one NO pays exactly $1 at settlement.
Buying NO at price q is economically identical to selling YES at price (1 − q).

Let p = the YES price you bought at, q = the NO price you bought at,
    s = 1 − q = the YES price you effectively sold at.

    profit = 1 − (p + q)  =  1 − p − (1 − s)  =  s − p

    ⇒  pair cost < $1   ⟺   s > p   ⟺   you bought YES low and sold it high.
```

**Confirmed** on real data. The settled market `KXBTC15M-26JUL021930-30` (15
one-minute candles, pulled live) had `min(yes_ask) = 0.4600` in minute 1 and
`max(yes_bid) = 0.9990` in minute 14. Perfect-hindsight pair cost:
`0.4600 + (1 − 0.9990) = 0.4610`, apparently a 53.9¢ "structural" profit. It is
nothing of the sort: it is `0.9990 − 0.4600 = 0.5390` of directional round-trip
P&L on a market whose implied probability marched monotonically from 46% to 100%.
The pairing added **zero** dollars. It added only the property that once paired
you cannot lose — which is a statement about the *variance* of a position you
have already closed, not about its *mean*.

**Two consequences:**

- The perfect-hindsight bound on pair cost is **useless as a gate** — it will pass
  on essentially every market that moved, and it is pure lookahead. Any honest
  test must use a **causal rule**. Part 7.3 pre-registers one.
- The claimed common thread — *"the edge is position structure, timing, relative
  pricing, execution quality and inventory management, not direction"* — **is
  wrong on the first and last items and right on the middle three.** Timing,
  relative pricing and execution quality are exactly what determines `s − p`.
  Structure and inventory management determine the risk profile and nothing else.

**Archetypes 1 and 4 (directional trading on an arbitrage base; hedged
directional accumulation) are described accurately by their authors** —
both explicitly say the imbalance is the directional bet. Under the identity
above, so is the "balanced" part. These are directional traders with a particular
risk-management style, and there is no strategy in them to copy that is not
"be right about 15-minute BTC direction."

**Bankroll and infrastructure.** `powerwinner`'s standardised blocks (120 BTC
contracts, 10–20 ETH) are ~$60 and ~$5–10 of notional at mid — trivially within
<$10k. **Capacity is genuinely not the constraint here**, which is a first for
this project: **Confirmed**, a single settled 15-minute BTC market carried
**777k–1.79M units of volume**, i.e. hundreds of thousands of dollars of turnover
per fifteen minutes. The constraint is that this is a venue where the marginal
participant is a bot, the quoted spread at mid is the 1¢ tick floor, and the
project chose Kalshi partly *because* its rate limits "fit a non-latency snapshot
stack" (2026-07-17 doc Part 6). Trading here at all is a change of stack, not a
change of candidate.

### 2.3 The one that might survive — and its fee arithmetic, done explicitly

The measurable claim is: **does a mechanical rule that buys each side when it is
cheap end up with pairs costing less than $1 net of fees, often enough to
matter?** This is testable from stored 1-minute candles at **zero capital risk**
and with **no execution stack**. Whether it survives fees is arithmetic.

**Confirmed, computed two ways.** Model a quoted market with mid `m` and
half-spread `h`. Buy YES as taker at `m₁ + h` at time 1, buy NO as taker at
`1 − m₂ + h` at time 2:

```
outlay = 1 + 2h + (m₁ − m₂) + fee₁ + fee₂        payout = 1
profit = (m₂ − m₁) − 2h − fee₁ − fee₂
```

At `m = 0.50`, `h = 0.005` (the observed 1¢ book), Kalshi taker:

```
fee₁ = 0.07 × 0.505 × 0.495 = $0.0174983
fee₂ = 0.07 × 0.505 × 0.495 = $0.0174983      Σ = $0.0349965  ≈ 3.50% of pair notional
2h                          = $0.0100000

break-even:  m₂ − m₁  ≥  0.0100 + 0.0350  =  +0.0450
```

**Second route (component sum, no algebra): 2 × 0.07 × 0.25 = 0.035 of fee, plus
1¢ of round-trip spread = 4.5¢.** Agrees.

**The Kalshi taker needs the implied probability to move 4.5 points in his favour
between the two legs, before he has made a cent.** Since (2.2) `pair cost < $1`
is identically a profitable YES round trip, this is the same statement as "you
must be right by 4.5 points." A 15-minute BTC binary certainly *moves* 4.5 points
routinely — but a mechanical rule has to catch the moves in the right order, and
the price is a near-martingale, so the prior that any fixed rule does so
systematically is **poor**. That is precisely why the test is worth running: it is
cheap, it has abundant power for once, and a NO-GO retires the whole class.

**The same trade on the other three (side, venue) combinations. Confirmed:**

| side / venue | fee on the pair at mid | round-trip spread | required move `m₂ − m₁` |
|---|---|---|---|
| **Kalshi taker** | −$0.03500 (2 × 0.07 × 0.25) | pay 1.0¢ | **+4.500 pts** |
| **Polymarket US taker** | −$0.03000 (2 × 0.06 × 0.25) | pay 1.0¢ | **+4.000 pts** |
| **Kalshi maker**, series not maker-fee-enabled | $0 | **earn** 1.0¢ | **−1.000 pts** |
| **Polymarket US maker** | **+$0.00625** (2 × 0.0125 × 0.25, a rebate) | **earn** 1.0¢ | **−1.625 pts** |

**The taker-to-maker swing is 6.125 percentage points of probability** (`+4.500 −
(−1.625)`), re-derived as `0.035 + 0.00625` of fee plus `0.02` of spread-sign
flip = `0.06125`. **The Kalshi-to-Polymarket-US swing among makers is 0.625
points.** This is Part 4's headline in miniature: **the side of the book is worth
ten times the venue.**

The maker version is not free — it converts fee risk into **fill risk and adverse
selection** (you are filled precisely when someone informed wants the other
side), and paper mode assumes full fills (`CONTEXT.md` → Mode), so *a paper
backtest of a maker strategy systematically overstates it* — a warning the
2026-07-25 doc already issued (Part 3.4.5) and which nothing here softens.

### 2.4 Selection bias, stated once and clearly

**The five accounts were chosen because they were the most profitable in July.**
Reconstructing behaviour from winners and inferring strategy is textbook
survivorship: the same position structure was plausibly run by hundreds of
accounts that lost, and none of them appear in the teardown. **None of the
claimed profitability transfers.** The base rate this project already holds is
unkind: **Confirmed** (2026-07-17 doc, Part 3, sourced to an SSRN study and
on-chain analyses) **~84% of Polymarket traders lose money; the top 1% capture
76.5% of profits; only ~2% ever cleared $1,000.** A teardown of five winners from
that distribution is a description of the right tail, not a strategy.

What *is* informative is the **structure**, because structure is checkable
independently of who ran it — and Part 2.2 checked it and found the central
structural claim to be an identity that says the opposite of what was claimed.

---

## Part 3 — What ADR-0023 unlocked that nobody re-checked

ADR-0023 retracted the ~68-day ceiling and listed what reopened. ADR-0024/0025/
0026/0027 worked that list. **One item on it was never done, and ADR-0027's
closing sentence asserts that it was.**

ADR-0023, verbatim: *"DROUGHT-1 (not directly re-tested here, same series-shape as
MRAIN-1's weekly cadence) should be re-checked the same way before assuming
ADR-0016's verdict still holds."*

ADR-0027, verbatim: *"With this, every candidate ADR-0023 flagged as unconfirmed
is now checked"* — then names MRAIN-1, FLB-1 weather/econ, HURSEAS-1 and the
emotional basket. **DROUGHT-1 is absent.** ADR-0029's six-row closing table does
not list it either; it was folded into ADR-0016's "dead" on the retracted premise
and never came back out.

**Checked live this session. Confirmed:**

```
GET /series/KXDROUGHTLEVEL
  -> title "Drought level", category "Climate and Weather",
     frequency "one_off", settlement source "U.S. Drought Monitor",
     fee_type "quadratic", fee_multiplier 1

GET /historical/markets?series_ticker=KXDROUGHTLEVEL&limit=200
  -> {"cursor":"","markets":[]}          0 markets

GET /markets?series_ticker=KXDROUGHTLEVEL&limit=200
  -> 16 markets, 1 distinct event_ticker (KXDROUGHTLEVEL-26JULLD4),
     1 settled with a result,
     e.g. "Will North Carolina have a maximum drought category of at least D4
           during June 4-July 30, 2026?"
```

**DROUGHT-1 stays dead, and the reason in the 2026-07-25 doc was wrong.** That
doc described *"the weekly US Drought Monitor… ~9–10 independent updates inside a
68-day window."* The product is **not weekly**: it is a `one_off` two-month
state-level window, with **one distinct event in all of Kalshi's history**. The 16
state markets on that event are **one cluster**, not sixteen — the same ladder
trap ADR-0016 and ADR-0026 both warned about. This is the ADR-0026 pattern again:
*correct verdict, incorrect reason, corrected here.*

**Nothing else on ADR-0023's list is outstanding.** MRAIN-1 (ADR-0029), FLB-1
weather/econ (ADR-0025), HURSEAS-1 (ADR-0026), the emotional basket (ADR-0027),
KXNOBELPEACE (structurally annual) are all closed. **ADR-0029's table should read
seven closed candidates, not six.** That is a documentation observation, not an
ADR — the decision belongs to whoever writes the next one.

---

## Part 4 — The maker side: the largest un-evaluated number in the repo

This is the section the 2026-07-28 refresh's Part 6.2 asked for and nobody has
costed.

### 4.1 The number, sharpened

The refresh found that **Polymarket US pays makers (`Θ = −0.0125`) where Kalshi
charges them (`0.0175`, on maker-fee-enabled series)** — a **1.5 percentage point
of notional** swing at mid, and correctly observed that this is *larger than
ADR-0019's entire measured edge (+0.88%)*.

**That is the smaller half of the finding.** **Confirmed, Part 2.3's table
re-derived:** on a two-legged binary trade at mid, the **taker-to-maker** swing is
**6.125 points of probability** and the **Kalshi-to-Polymarket-US** swing among
makers is **0.625 points**. Even on a single leg the comparison is stark:

| single leg at `p = 0.50`, per contract | Kalshi | Polymarket US |
|---|---|---|
| taker fee | **1.750¢ charged** (3.50% of notional) | **1.500¢ charged** (3.00%) |
| maker fee, maker-fee-enabled series | 0.4375¢ charged (0.875%) | — |
| maker fee, everything else | **0** | **0.3125¢ credited** (0.625%) |
| plus: half-spread at a 1¢ book | **pay 0.5¢** | **earn 0.5¢** |

(Each recomputed by `fee/notional = Θ(1−p)`; the Kalshi figures are ADR-0015's
primary-verified coefficients, the Polymarket US figures were fetched from
`docs.polymarket.us/fees` in the 2026-07-28 refresh and are unchanged.)

**Every one of the six closed candidates was a taker strategy.** FLB-1's gate
priced a taker fill; WP-7/MRAIN-1 measured fee-free edge room; the econ line was
never built. **The project has never once evaluated the other side of the book.**
That is not a small oversight in a stack whose largest measured edge to date is
+1.15% and whose taker fee at mid is 3.50%.

### 4.2 Both venues run live, retail-accessible reward programmes — Confirmed

**Kalshi, `GET /incentive_programs`, called unauthenticated this session:**

```
102 live liquidity-incentive programs
common structure:  discount_factor_bps 5000 (0.50)
                   target_size_fp      1000.00
                   period_reward       1000000       (units unresolved)
                   incentive_type      "liquidity"
all 102 sit on KXEARNINGSMENTION* series
  (KXEARNINGSMENTIONDKNG, ...LLY, ...HIMS, ...CAVA, ...AC, ...WEN, ...NBIS, ...CELH)
no crypto series, no weather series
```

> **CORRECTION, 2026-08-02, added after this document was written.** The block
> above is **wrong on both counts**, and the errors run in the project's favour.
> It was produced by a single unpaginated call; paginating to exhaustion gives a
> different catalogue.
>
> **1. `period_reward` is in centi-cents — Confirmed**, from Kalshi's own API
> reference (`docs.kalshi.com/api-reference/incentive-programs/get-incentives`),
> which describes the field verbatim as *"Total reward for the period in
> centi-cents"* (`int64`). So `1000000` = **$100.00**, not $10,000. This closes
> open question 3. Cross-checked by a second route: Kalshi's Liquidity Incentive
> Program help page states reward amounts of **"$10–$1,000 per day"**, and the
> observed pools ($15–$1,000 per period) sit inside that band, where the
> cents reading ($1,500–$100,000/day) does not.
>
> **2. The catalogue is ~28x larger and is not earnings-mentions-only —
> Confirmed**, `GET /incentive_programs?status=active` paginated to exhaustion:
> **2,864 active programmes, $177,313.33 of live pool**, all `incentive_type:
> "liquidity"`, all `discount_factor_bps: 5000`. Families include
> **weather (`KXTEMP{AUS,CHI,DC,LAX,NYC}H`, `KXRAIN`)**, **crypto
> (`KX{BTC,ETH,SOL,XRP,DOGE,BNB,HYPE,ZEC}{MAX,MIN}MON`)**, **econ (`KXGDP`,
> `KXGDPNOM`, `KXGDPYEAR`)**, GPU-price series, and earnings-mentions.
>
> **This materially improves MAKER-1**, because it lands the candidate on the
> exact domain the project already has infrastructure for: five years of
> `/historical/*` weather data, an IEM ingestion path, and station mappings
> verified 595/595 against Kalshi's own settlements (ADR-0029). Four of the five
> `KXTEMP` cities (NYC, Chicago, LAX, Austin) are already in
> `weather_ingest.STATIONS`; only DC is new.
>
> **The weather programmes, measured live — Confirmed:** 50 active `KXTEMP`
> programmes, each **$120.00**, `target_size_fp 1000.00`, `DF 0.50`,
> `incentive_description: "new_event"`, over a **58-minute** window
> (`00:02:08Z → 01:00:00Z`) on newly-listed **hourly** temperature markets
> (10 strikes x 5 cities).
>
> **Competing resting size, the one unobserved input this document said would
> resolve the candidate — measured, 14 incentivized markets, live L2:**
> mean **1,042** contracts of YES-side bids and **1,427** of NO-side bids, with
> several strikes showing **zero** resting size on one side entirely.
>
> **And the naive yield that falls out is not credible, which is the actual
> finding.** Resting 1,000 contracts at best price against ~1,042 of competing
> size is a ~49% score share → **~$59 per 58-minute period** on roughly **$500**
> of committed capital at `p = 0.50`. That is ~12% per hour. **No persistent,
> publicly-documented, unauthenticated-API yield of that size survives
> competition**, so the naive model is missing a dominant term — displacement
> from the best price, the per-side scoring normalisation, realised payout
> mechanics, or (most likely) **adverse selection**, which §4.3 already named as
> the unmeasurable half and which is at its worst on a one-hour weather market
> whose outcome is nearly determined. Note several strikes quoting `0.99` with a
> one-sided book: that is a near-settled outcome, and resting size there is
> capital at risk of exactly the fill you do not want.
>
> **The correction does not change MAKER-1's rank; it sharpens its gate.** The
> Part 7.1 study should now be run on `KXTEMP*` rather than `KXEARNINGSMENTION*`,
> and its primary deliverable is **realised payout per unit of committed capital,
> net of fills** — not the gross reward-share arithmetic above, which this
> correction has just demonstrated is optimistic by an unknown but large factor.

Spot-checking that population (**Confirmed**, live): `KXEARNINGSMENTIONDKNG`
markets quote **5–7¢ wide** (`0.87/0.92`, `0.50/0.55`, `0.25/0.32`) on volumes
around **600–1,500 units**, on a 1¢ tick, open since 2026-07-23 with a
2026-12-31 close. **That is a thin, wide, low-information category that Kalshi is
paying people to quote — and this project has never looked at it.**

**Polymarket US, `polymarket.us/rewards` and `docs.polymarket.us/incentives/*`,
fetched this session — Confirmed:**

```
74 liquidity-reward programs across 16,893 markets
scoring:  Score = DiscountFactor ^ (ticks from best price) x OrderSize, every second
          bid side and ask side each independently normalised to 1.0 per snapshot
          no earning cap; payouts proportional to score share
          paid within 5 business days; $1.00 minimum payout
categories include Climate/Weather and Crypto ("Coins") alongside Sports,
          Politics, Macro, Tech & Finance, Geopolitics, Culture

representative programs:  Climate       $1,000 pool   DF 0.30   target 10,000
                          Politics High   $300 pool   DF 0.20   target 10,000
                          Macro           $150 pool   DF 0.15   target  5,000
                          MLB ML Live   $2,500 pool   DF 0.30   target 25,000
                          PGA Round 1  $15,000 pool   DF 0.40   target 10,000
pools are per time period (early / day-of / live / daily) and "never summed per market"
```

Also documented and **open** (not application-gated): a **Volume Incentive
Program** (taker volume) and retail **Deposit** / **Referral** programmes; the
**Market Maker Program** requires an application.

### 4.3 Why this is the *only* candidate class with no power problem

Every prior candidate needed a **statistical estimate of an unknown effect**, and
five of six died because Kalshi could not supply enough independent events to
estimate it. **A liquidity-reward yield is not an estimate. It is a published
deterministic formula** — `Score = DF^ticks × Size`, normalised per snapshot,
share-of-pool payout — **with exactly one unobserved input: the competing resting
size.** That input is **directly observable from the L2 book, right now, at zero
capital risk, in days.**

**Assuming** the Climate program's `$1,000` pool and a `$2,000` resting position
(2,000 contracts at ~$0.50, a realistic slice of a <$10k bankroll) quoted at the
best price with `DF = 0.30`: if total competing score is 30,000 the share is
~6.3% → ~$63/period; if it is 500,000 the share is 0.4% → ~$4/period. **The
answer spans two orders of magnitude and the whole spread is resolved by
measuring one observable quantity.** That asymmetry — one observable unknown, a
published formula for everything else — is why this ranks first in Part 6, and it
is why the study's deliverable is a *number*, not a *verdict about nature*.

**The honest cost, stated plainly:** the reward is only half the economics. The
other half is **adverse selection on the fills**, which is *not* observable
without trading, and which the paper Engine will overstate because it assumes
full fills. The pre-registered gate in Part 7.1 therefore measures the reward
yield **before** adverse selection and sets the bar high enough (Part 7.1) that
there is room for it to be wrong.

---

## Part 5 — Is the candidate-generation process itself the problem?

**Yes. Six candidates, six deaths, and the deaths are not independent.**

### 5.1 The pattern

| candidate | closed by | proximate cause | shared structure |
|---|---|---|---|
| Track B weather model | ADR-0014 | price beats public forecast; 38h listing window | taker, public-data model vs. price |
| FLB-1 weather | ADR-0025 | real edge, +1.15%, below a 1.5% bar | taker, statistical prior vs. price |
| FLB-1 econ | ADR-0025 | +0.20%, t=0.23 | taker |
| FLB-1 emotional basket | ADR-0027 | 7 families | taker |
| HURSEAS-1 | ADR-0026 | 4 seasons | taker |
| v0.3 econ calibration | ADR-0022→0025 | no edge | taker, public-data model |
| MRAIN-1 | ADR-0029 | price beats climatology, powered | taker, public-data model |
| *DROUGHT-1* | *ADR-0016, corrected in Part 3* | *1 event* | *taker* |

**Three structural biases produced this list, and all three are fixable.**

**(1) Every candidate was a taker.** Part 4. The project has spent ~40 dev-days
measuring edges smaller than the fee it never questioned paying, on the side of
the book that pays it.

**(2) Every candidate was "my public-data model beats the price."** In every case
the counterparty is an automated quoter running **the same free public data** —
ADR-0014 (MOS), ADR-0029 (climatology and QPF), the 2026-07-25 doc's inference of
a single quoter across 20 weather ladders. The best possible outcome of that
contest is a tie, and the measured outcomes were −15% to −967% Brier skill. **A
model-vs-price thesis on public data is structurally a losing framing** unless
the model is genuinely better than the professional consensus, which a solo
developer's weekend climatology is not.

**(3) Selection on measurability.** The requirement to *prove* an edge with a
powered backtest selects for markets with many independent, high-cadence, resolved
outcomes — which are exactly the liquid, tightly-quoted, well-arbitraged markets
where edge is smallest. The 2026-07-25 doc found the same trap from the other
end: thin markets are *untradeable* (KXTXURI, 88¢ spreads), not mispriced. **The
project has been systematically searching the intersection of "measurable" and
"tradeable", and that intersection is where edge goes to die.**

### 5.2 The proposed change of sourcing axis

**Stop sourcing candidates from forecastable phenomena. Source them from venue
mechanics.** A venue mechanic is a property of the exchange's *rules*, published
in advance, not competed away by better modelling, and often *deterministic*
rather than statistical — which dissolves the power problem that killed five of
the eight.

Five concrete axes, each of which produced a real candidate this session:

- **Fee and rebate asymmetries.** → Part 4. Produced **MAKER-1** (ranked #1).
- **Published incentive-programme formulas.** → the reward is a known function;
  only the competing-size input is unknown. Also **MAKER-1**.
- **Listing schedules.** ADR-0014 died on a 42-hour listing window that is a
  *series-template constant*. A different venue's template is a different number,
  knowable in one API call. → produced **PMUS-TEMP-1** (ranked #3).
- **Settlement and timing mechanics.** Archetype 3's entire edge was the gap
  between determination and settlement; Kalshi appears to have no such gap
  (Part 2.2). The inverse question — where *does* a US-legal venue leave such a
  gap — is a rules question, not a modelling one.
- **Cross-venue listings of an identical settlement source.** **Confirmed this
  session:** Polymarket US temperature contracts settle on the **NWS Daily Climate
  Report (CLI)** at `KNYC`/`KSFO`/`KMIA`/`KMDW`/`KLAX`; Kalshi's daily temperature
  ladders settle on the same NWS CLI stations, and **four of the five cities
  overlap** (NYC, Miami, Chicago-Midway, LA — Kalshi lists no San Francisco daily
  temperature series). **The single largest risk in this repo's cross-venue
  machinery — match risk, the reason ADR-0002/0004 and `market_matcher.py` exist —
  is zero here, because both venues cite the same government report.** That
  produced **XVENUE-WX-1** (ranked #4), the only genuinely new candidate in this
  document.

### 5.3 What this does not claim

It does **not** claim the machinery was wasted: the ingest, PIT store, fee model,
family clustering and clustered gate runner are the reason six candidates cost
days rather than capital, and MAKER-1/PMUS-TEMP-1/XVENUE-WX-1 all reuse them. It
does **not** claim venue mechanics are easy money — Part 9 attacks that. It claims
only that **the sourcing filter has been "what does a venue list that I have data
for", and it should be "what does a venue's rulebook pay me for, or fail to
price."**

---

## Part 6 — Ranked shortlist, by expected edge per dev-day

Format follows the 2026-07-25 doc's Part 5. NO-GO recommendations are ranked
alongside the rest, with reasons, because a documented NO-GO is a deliverable.

### 1. MAKER-1 — resting-order reward yield, measured (GO)

- **Venues/tickers:** Phase A, Kalshi `GET /incentive_programs` (102 live
  programs, all `KXEARNINGSMENTION*`). Phase B, Polymarket US Climate / Macro /
  Politics-High liquidity programmes.
- **Why the edge might exist:** **Confirmed** — both venues *pay* for resting
  orders, Polymarket US additionally *credits* the maker fee (`Θ = −0.0125`), and
  the only paper that separates the sides finds **Kalshi makers do ~22 points
  better than takers** (ADR-0017). The taker-to-maker swing is **6.125 points of
  probability** on a two-legged trade (Part 2.3), against a project record edge of
  **+1.15%**.
- **Why it is ranked first despite being unbacktestable:** it is the **only**
  candidate whose principal unknown is *observable rather than estimable*. There
  is no power problem, no history-depth problem, and no capital at risk during the
  study. Phase A needs **no new venue, no account and no auth** — the endpoint
  answered an unauthenticated call this session.
- **Pre-registered gate:** Part 7.1.
- **Dev-days: 1–2 (Phase A) + 2–3 (Phase B).** Phase B additionally needs a
  user-side KYC'd Polymarket US account — start it on day 1, in parallel.
- **Top risk:** adverse selection is unmeasurable without trading, and the paper
  Engine will overstate a maker strategy (assumes full fills). Handled by setting
  the bar high (Part 7.1), not by pretending it away.

### 2. KXCRYPTO-PAIR-1 — the sub-$1 pair claim, tested causally (MAYBE)

- **Tickers:** `KXBTC15M`, `KXETH15M`, `KXXRP15M`, `KXDOGE15M` (+`KXBCH15M`,
  `KXTON15M`, `KXNEAR15M` as robustness).
- **Why it might exist:** the archetype-2/5 claim, cleaned of its false framing —
  does a fixed dip-buying rule on both sides of a 15-minute binary systematically
  end with pairs below $1 net of a 3.50% round-trip fee?
- **Why it is worth 2–3 days despite a poor prior:** **for the first time in this
  project's history, power and capacity are both abundant.** **Confirmed:** 96
  markets per day per series, ~8 series, settled markets retrievable with
  **1-minute `yes_bid`/`yes_ask` OHLC candles**, and volumes of 0.8–1.8M units per
  15-minute market. The live tier alone (3 months) holds **~8,600 BTC markets**. A
  decisive NO-GO retires an entire class of short-horizon crypto strategies —
  including the ones the user will be shown next month.
- **Why not ranked first:** the prior is genuinely bad (Part 2.3 — the price is a
  near-martingale and the required move is 4.5 points), and even a GO would point
  at a latency arena this stack cannot enter.
- **Pre-registered gate:** Part 7.3.
- **Dev-days: 2–3** (ingest one month of 15-minute markets + candles; the rule and
  the clustered t-test reuse `scripts/mrain1_gate.py`'s shape).

### 3. PMUS-TEMP-1 — Polymarket US temperature re-gate, behind a hard abort (MAYBE)

- **Tickers:** Polymarket US temperature contracts, `KNYC`/`KSFO`/`KMIA`/`KMDW`/
  `KLAX`.
- **Why it might exist:** it is **ADR-0014's own named reopen condition #1** — *"a
  series listed further ahead of resolution… this is the only high-value check
  left, and it is a venue/series question, not a modelling one"* — on a **US-legal
  venue**, with **four of five stations already in `weather_ingest.STATIONS`**,
  the same NWS CLI settlement source, and `calibration.evaluate()` reusable
  unchanged.
- **Why it is ranked third:** the entire case rests on **Likely (unverified)**
  secondary reports of a "1 to 3 day" listing window. 72h is only 30h more than
  Kalshi's 42h, and ADR-0014's Brier-by-lead table was **flattening** (−15.8% →
  −15.0%), not converging. The candidate is therefore gated behind a **0.5-day
  measurement with a hard abort** before any modelling work.
- **Pre-registered gate + abort:** Part 7.2.
- **Dev-days: 0.5 to the abort check; 3–5 beyond it** (a `PolymarketUSSource`
  read-only adapter is the bulk; ADR-0016's "build no new ingestion adapter" ruling
  was conditional on WP-0 and is superseded by ADR-0023 — but it should be
  honoured until the abort check passes).

### 4. XVENUE-WX-1 — same NWS report, two US venues, zero match risk (MAYBE, newest and least evidenced)

- **What it is:** Kalshi and Polymarket US both list daily temperature for NYC,
  Miami, Chicago (Midway) and LA, **both settling on the same NWS CLI report**
  (**Confirmed** for Polymarket US this session; **Likely (unverified)** that
  Kalshi's station mapping matches exactly — ADR-0021 flagged `KMDW`-for-Chicago
  as an unconfirmed proxy, and ADR-0029 later confirmed Midway for the *rain*
  series).
- **Why it might exist:** two US-legal venues, **separate order books, separate
  and non-overlapping user bases**, an order-of-magnitude size difference (Kalshi
  ~$4.46B/week vs Polymarket US's ~$882M record week), and a **settlement source
  that is byte-identical**. The 2026-07-17 doc killed cross-venue arb on latency
  (2.7s windows) — but that was politics/crypto against Polymarket Global. Daily
  weather ladders are not a 2.7-second game.
- **Fee reality, Confirmed:** a cross-venue complete set at mid costs
  `3.50% + 3.00% = 6.50%` taker/taker — dead. At the ladder extremes (`p = 0.95`)
  it costs `0.35% + 0.30% = 0.65%`, and taker-on-Kalshi/maker-on-Polymarket-US
  costs `0.35% − 0.06% = 0.29%`. **If this trade exists it lives at the ladder
  extremes, on the maker side, which is the same place Part 4 points.**
- **The first check, and it is cheap:** do the two venues' **strike grids
  align**? If Polymarket US uses different buckets, there is no complete set and
  the candidate dies in an hour. **Unverified** — I could not read Polymarket US
  market structure (`gateway.polymarket.us` returned 403).
- **Dev-days: 0.5 for the strike-grid check; 3–4 beyond it.** Shares the
  `PolymarketUSSource` cost with PMUS-TEMP-1 — **build them together or neither.**

### 5. LEADA-1 — buy cheap extreme-temperature contracts (**NO-GO**)

- **Reason 1, decisive: unreachable.** Six of seven cities are Polymarket Global
  only; the US is blocked/close-only there (Part 1.1, two Polymarket primary
  sources).
- **Reason 2, independent: the reachable analog is already measured at −90.31%
  net, t = −11.31** (ADR-0019), and the selection factor required to profit at a
  2¢ entry is **~21×** over the population base rate (Part 1.2).
- **Reason 3: the mechanism is a freshness race**, per the strategy's own
  published how-to, which the 2026-07-25 doc's Part 8 already ruled out for this
  stack.
- **Dev-days saved: ~6–10** (a European-city weather adapter plus a re-run of the
  WP-7 gate).

### 6. LEADB-EXEC — implement archetypes 2/3/5 as described (**NO-GO**)

- **Reason 1: unreachable** (Polymarket Global).
- **Reason 2: archetype 3 has no window on Kalshi** — `close_time` is the interval
  end (Part 2.2).
- **Reason 3: the central claim is false as an identity** — a sub-$1 pair is
  exactly a profitable directional round trip (Part 2.2), so there is no
  structural edge to implement.
- **Reason 4: archetypes 2, 3 and 5 are latency- and execution-bound**, and this
  repo has **no live execution path at all** and a snapshot cadence chosen
  deliberately.
- **Dev-days saved: 15–30** (a live execution stack).

### 7. DROUGHT-1 (**NO-GO — closed here, Part 3**)

`frequency: "one_off"`, 1 distinct event, 16 state markets that are one cluster.
Closed on a correct reason for the first time. **Dev-days saved: 4–7.**

---

## Part 7 — Pre-registered gates

Written now, before any data is looked at, per ADR-0012's discipline. **ADR-0029
is the exemplar: cluster on the event, not the sample; state the minimum cluster
count; report the CI and say explicitly whether a GO-sized effect is excluded. An
unpowered gate is not a gate — ADR-0022 and ADR-0027 produced two useless nulls
that way.**

### 7.1 MAKER-1

- **Statistic:** `reward_yield = (period_reward × my_score_share) /
  my_resting_notional`, annualised, computed **ex ante** from observed book state
  and the published formula, for a **fixed $2,000 of resting notional** quoted at
  the best price. `my_score_share = my_score / (my_score + observed_competing_score)`
  where `my_score = my_size × DF^0` and `observed_competing_score =
  Σ_levels size × DF^(ticks from best)` from the L2 book, sampled every 60 seconds
  during the programme's reward period.
- **Threshold:** **GO iff the mean annualised reward yield ≥ 15%, before adverse
  selection**, with a cluster-clustered `t ≥ 2`. Rationale for 15%: it must clear
  Kalshi's ~3.25% APY on the same idle capital (2026-07-25 doc, primary source)
  by a wide enough margin to absorb an adverse-selection cost nobody can measure
  without trading. Below 15% the programme is not paying enough to be worth
  discovering what that cost is.
- **Clustering unit: one programme-day.** Not one 60-second snapshot. Snapshots
  within a day are a single book state observed repeatedly; testing on snapshots
  would inflate `t` by roughly `√(snapshots per day)` ≈ `√1,440` = **38×**. This
  is the same ladder trap, wearing a clock.
- **Minimum cluster count: 20 programme-days across ≥ 2 distinct programmes.**
  Reachable in 10 calendar days on Kalshi with zero capital.
- **Mandatory third verdict:** `UNDERPOWERED` if the 95% CI on the cluster mean
  covers 15%. Report the CI and the sentence *"a GO-sized effect is/is not
  excluded"* verbatim, as ADR-0029 does.
- **Diagnostic that must ship with it:** the **fraction of reward periods in which
  the programme's `target_size` was met on both sides**. A reward you cannot
  qualify for is not a reward — the direct analog of MRAIN-1's mandatory
  two-sided-quote diagnostic.
- **Pre-registered kill:** if `period_reward`'s units resolve such that the pool
  is under **$50/period**, stop. A <$10k bankroll cannot extract a meaningful
  share of a pool that small at any yield.

### 7.2 PMUS-TEMP-1

**Phase 0 — abort check, 0.5 dev-days, run before anything else.**
Measure `close_time − open_time` (or `endDate − createdAt`) across **≥ 30 resolved
temperature markets per city, all five cities**.

- **ABORT if the median listing lead time < 60 hours.** Rationale, stated before
  looking: ADR-0014's forecast-error σ at KNYC is 2.84°F at 36–48h and 3.25°F at
  48–72h — barely different from the 2.45°F the market already prices at 12–24h —
  and only reaches 5.76°F past 72h. A venue that lists 50 hours out has bought
  ~0.4°F of extra σ and nothing else. **Do not build a `PolymarketUSSource` before
  this check passes.**

**Phase 1 — the gate, only on a pass.**

- **Statistic:** `skill = (Brier_price − Brier_forecast) / Brier_price`, per
  market type, using `calibration.evaluate()` **unchanged** and the existing
  IEM MOS/ASOS pipeline (`weather_ingest.py`), PIT-honest via `store.py`'s
  `< as_of` readers.
- **Threshold: GO iff skill ≥ +5%** — the same margin as ADR-0012/ADR-0014/
  ADR-0029, deliberately, so the numbers are directly comparable to the Kalshi
  result they are meant to overturn.
- **Clustering unit: one station-date.** One city's full strike ladder on one
  target date, sampled at multiple `as_of` steps, is **one cluster**. Not one
  market, and emphatically not one sample. ADR-0014's 2,442 samples came from 68
  dates; testing on samples would have inflated `t` by ~`√36` = **6×**.
- **Minimum cluster count: 300 station-dates**, i.e. 60 calendar days × 5 cities,
  with **≥ 3 cities individually agreeing in sign** as a robustness condition
  (ADR-0029 reported 8 of 10; ADR-0019 reported 5 of 6).
- **Mandatory third verdict:** `UNDERPOWERED` if the 95% CI on the cluster-mean
  Brier gap covers the GO threshold. Report the interval.
- **Mandatory pre-check, non-negotiable, before any result is trusted:** reproduce
  Polymarket US's own settlements from IEM data for ≥ 30 resolved markets per
  city, exactly as `scripts/mrain1_settlement_check.py` does. ADR-0029 named this
  as *"the single most expensive place to be wrong, because it fails silently."*
  Polymarket US settles at 08:00 ET on the **following** day from the NWS CLI; IEM
  ASOS daily is a different pipeline for the same observation and the two can
  disagree.
- **Diagnostic that must ship with it:** two-sided-quote fraction per
  (market, `as_of`). Polymarket US is ~an order of magnitude smaller than Kalshi;
  a GO on markets nobody quotes is not a GO.

### 7.3 KXCRYPTO-PAIR-1

- **The rule, fixed now, no fitting:** at each 1-minute bar `t` of a 15-minute
  market, using only bars strictly before `t`: buy **one** unit of YES the first
  time `yes_ask.close ≤ θ`, and **one** unit of NO the first time
  `(1 − yes_bid.close) ≤ θ`. Never sell. Settle at close. `θ = 0.45`,
  pre-registered. Report `θ ∈ {0.40, 0.45, 0.50}` as a sensitivity; **the gate is
  decided on 0.45 only**, and a GO that appears at only one `θ` is reported as a
  failure, not a success.
- **Statistic:** mean **net P&L per market as a fraction of pair notional**, with
  Kalshi taker fees applied per leg *including* `ceil_cents` at a realistic order
  size (use 100 contracts; `fees.py` unchanged), and unpaired legs settled
  directionally.
- **Threshold: GO iff mean net ROI ≥ +0.25% of pair notional with cluster
  `t ≥ 2`.** Rationale for a bar so much lower than FLB-1's 1.5%: the holding
  period is fifteen minutes, so capital turns over ~96×/day; 0.25% per market is
  already an implausibly large annualised number, and setting it higher would make
  the gate untestable rather than strict.
- **Clustering unit: one calendar day.** One 15-minute market is the natural
  independence unit for the *price path*, but strategy P&L is
  volatility-regime-dependent and volatility clusters within a day. **Report both
  market-clustered and day-clustered standard errors; gate on the day-clustered
  one** (conservative). Do **not** cluster on minute-bars: ~15 bars per market
  would inflate `t` by ~`√15` = **3.9×**.
- **Minimum cluster count: 60 distinct calendar days and ≥ 2,000 markets across
  ≥ 3 coin series.** All three are reachable from Kalshi's live tier today
  (3 months of history × 96 markets/day/series × 8 series).
- **Mandatory third verdict:** `UNDERPOWERED` if the 95% CI on the day-clustered
  mean covers +0.25%.
- **Mandatory honesty condition:** the study **must** report the
  perfect-hindsight bound `min_t(yes_ask) + (1 − max_t(yes_bid))` alongside the
  causal result, and state the gap. Part 2.2 already showed the bound is
  uselessly loose (0.461 on one real market). Reporting it prevents anyone later
  mistaking the bound for the finding.
- **Pre-registered kill:** if the causal rule's fill rate on the *second* leg is
  below 50% of markets, the strategy is a naked directional bet in half its
  instances and should be reported as such, not as a pair strategy.

---

## Part 8 — What to NOT build

*At least as valuable as Part 6, and for the same reason the 2026-07-25 doc said
so: this project's returns to date have come from things it did not build.*

- **Any European-city weather ingestion, or any Polymarket Global adapter for
  execution purposes.** The venue is closed to US persons, confirmed from two
  Polymarket primary sources. Its public data remains a signal-research input only
  (2026-07-17 doc's standing rule). *Saves ~6–10 dev-days.*
- **A live/low-latency execution path for 5- or 15-minute crypto.** Archetype 3 is
  a seconds-scale race with no window on Kalshi; archetypes 2 and 5 are
  execution-quality-bound. The stack gave up latency deliberately (ADR-0006) and
  the venue was chosen partly because its rate limits suit a snapshot stack.
  *Saves 15–30 dev-days, and probably capital.*
- **A "buy longshots at 1–34¢" line on Kalshi, in any category.** Already measured:
  **−90.31% net, t = −11.31** (ADR-0019). This is not an untested idea; it is a
  tested and decisively rejected one. *Saves 2–4 dev-days and a bankroll.*
- **Any further re-run of the WP-7 temperature gate on Kalshi** — another city,
  another season, a better model. The 42.0-hour listing window is a series-template
  constant with zero variance across 414 markets, and ADR-0014's own follow-up
  established there is no tradeable window in which room could exist. **The
  cold-season variant is now *possible* via `/historical/markets` and is still not
  worth it.** *Saves ~10–15 dev-days.*
- **Any Polymarket US ingestion adapter before the 0.5-day listing-lead abort
  check in Part 7.2.** If the answer is 42 hours, PMUS-TEMP-1 and XVENUE-WX-1 both
  die and the adapter is sunk cost. *Saves 3–5 dev-days on a coin flip.*
- **A "freshness race" model that ingests intraday observations to beat the
  quoter's repricing lag.** The 2026-07-25 doc's Part 8 raised this as the honest
  test of "the market is slow", then declined it, and the Medium write-up
  confirms this is exactly the mechanism Lead A is describing. Losing a freshness
  race more slowly is not an edge. *Saves 6–10 dev-days.*
- **Another forecastable-phenomenon calibration gate of any kind, until Part 5's
  sourcing question is answered by the user.** Eight for eight is not bad luck.
- **A cross-venue arb line before the strike-grid alignment check (Part 6, item
  4).** If the ladders do not align there is no complete set, and the check is one
  hour. *Saves 3–4 dev-days.*

---

## Part 9 — The strongest argument against this document

Stated as its own section so it cannot be buried.

**1. I never read either source, so I may be demolishing a straw man.** Both X
URLs returned HTTP 402 to the commissioning session, and the Lead B teardown was
relayed as pasted text with no origin. My venue verdict on Lead A does not depend
on the post being accurate — European cities are simply not listed anywhere this
user can trade — but **my reasoning about *why* the strategy would fail is built
entirely on a brief's paraphrase.** If the actual thread describes something
materially different from "buy cheap contracts when models agree," Part 1.2's
ranking of explanations is unfounded. The one internal consistency check available
(the trade multiples, Part 1.4) **failed** on the headline entry price, which
argues for less trust in the source, not more — but "the summary is imprecise" is
weaker evidence than "the strategy is wrong."

**2. My top recommendation is the one thing this project cannot backtest, on a
project whose entire discipline is pre-registered backtests.** MAKER-1's evidence
comes from **forward observation**, which is the fork ADR-0016 framed and the user
has repeatedly not taken. I claim this is different in kind — the reward is a
published deterministic formula and the only unknown is observable in ten days,
not six months — but that claim is *itself* the load-bearing assumption of Part 4,
and if the programme parameters turn out to be undocumented, unstable, or
retroactively changed, MAKER-1 degenerates into exactly the forward-paper
commitment the project has avoided. **The falsifiable version: if Kalshi's
`period_reward` units cannot be resolved, or if the programme list churns week to
week, MAKER-1 is not the cheap deterministic study I am selling.**

**3. The maker recommendation ignores the reason makers get paid.** They are paid
because they are adversely selected. Every number in Part 4 is a *gross* reward
yield, and the cost that offsets it is **structurally unmeasurable without
trading** — and the paper Engine will not surface it, because it assumes full
fills (`CONTEXT.md` → Mode). The 2026-07-25 doc flagged this explicitly and I
have not solved it; I have only set the bar at 15% to leave room. If the true
adverse-selection cost is 20%, a 15% gate produces a confident, well-clustered,
losing GO. **That is the single most dangerous failure mode in this document.**

**4. Polymarket US may simply be too small.** It is **eight months old** and did
~$882M in its record week against Kalshi's ~$4.46B (2026-07-28 refresh,
**Confirmed** there). Its Climate reward pool is **$1,000** and its Macro pool
**$150** per period. Even a generous share of $150 is not a business. Three of my
four ranked candidates route through this venue. **If the answer to "how big are
these pools really" is "small," Part 6 collapses to KXCRYPTO-PAIR-1, which has a
bad prior.**

**5. Part 5's sourcing argument is unfalsified, not verified.** "Six candidates
died because they were all takers running public-data models" is a coherent story
that explains the data, and coherent stories that explain data are cheap. The
alternative story — **there is no retail edge on US-legal prediction markets at
<$10k, and the sourcing method was fine** — explains the same eight deaths equally
well and is not addressed anywhere in this document. **Confirmed** base rates
support it: ~84% of Polymarket traders lose money; the top 1% take 76.5% of
profits. **Nothing here rules out the possibility that the correct answer is
"stop," and this document should not be read as evidence against that.**

---

## Open questions for the user

> **ANSWERED 2026-08-02 by the user, same day.** **(1) Forward observation is
> acceptable evidence.** **(2) Yes — a KYC'd Polymarket US account will be
> opened.** **(3) Resolved by measurement, not by the user** — see the
> correction block in §4.2: `period_reward` is in **centi-cents**, and the
> earnings-mention programmes are **not** representative. The shortlist in Part 6
> therefore stands in full, with none of the three abort conditions triggered.
> Question 4 (amending ADR-0029's table to seven) remains open.

1. **Is a forward-observation study acceptable evidence, or must every candidate
   be provable from history?** *(Assuming: forward observation is acceptable when
   the unknown is an observable quantity rather than an unknown effect size — that
   distinction is what separates MAKER-1's ten-day book-watching study from the
   6–12-month forward-paper commitment ADR-0016 framed.)* **If the answer is "must
   be historical," MAKER-1, PMUS-TEMP-1 and XVENUE-WX-1 all fail and only
   KXCRYPTO-PAIR-1 survives — at which point "stop" is the honest recommendation.**
   This is the highest-value unresolved item in the project and it displaces the
   historical-tier probe, which is now done.

2. **Will you open a KYC'd Polymarket US account?** *(Assuming: yes, and that it
   is a user-side task with lead time — start it on day 1 in parallel, exactly as
   the IBKR task was handled.)* Three of the four ranked candidates need it, and
   even the venue's documented-public market-data endpoint returned **403** to this
   session's fetcher, so the venue may not be evaluable at all without one.

3. **What are Kalshi's `period_reward` units, and are the 102 earnings-mention
   programmes representative or a one-off promotion?** *(Assuming: `period_reward`
   is denominated in cents, i.e. $10,000 per programme-period, because Kalshi's
   API uses integer minor units elsewhere — but this is a guess and the number
   swings MAKER-1's conclusion by four orders of magnitude.)* Resolvable in five
   minutes by an authenticated call or by reading `kalshi.com/incentives`, which
   returned **HTTP 429** to this session.

4. **Should ADR-0029's closing table be amended to seven closed candidates?**
   *(Assuming: yes — DROUGHT-1 is closed as of Part 3 of this document, on
   confirmed live data, and the record currently implies it was closed by ADR-0016
   on a premise ADR-0023 retracted.)* This is a documentation decision, not a
   strategy one, and it belongs in whoever writes the next ADR — not here.

---

## Sources

Fetched or searched this session (2026-08-02). **Failed fetches are marked.**

**The two primary sources for Lead A — both unreadable**
- `https://x.com/PolyDekos/status/2082754710314922360` — **HTTP 402, not
  retrieved.** Every figure attributed to it is an unverified relay.
- `https://x.com/RetroValix/status/2080699000919843157` — **HTTP 402, not
  retrieved.** Same.
- The five-account Polymarket crypto teardown (Lead B) was supplied as **pasted
  text with no source URL** and could not be verified at all.

**Kalshi — live API, `api.elections.kalshi.com/trade-api/v2`, all unauthenticated**
- `GET /series?category=Climate and Weather` — 28 city-temperature series, all US, **zero** non-US cities
- `GET /series?category=Crypto&limit=200` — full series list; `KXBTC15M`, `KXETH15M`, `KXXRP15M`, `KXDOGE15M`, `KXBCH15M`, `KXTON15M`, `KXNEAR15M`, `KXCRYPTOLEAD15M` all `fifteen_min`
- `GET /series/KXBTC15M`, `GET /series/KXETH15M` — `fee_type "quadratic"`, `fee_multiplier 1`, CF Benchmarks settlement
- `GET /markets?series_ticker=KXBTC15M&status=open` — live quote, `price_ranges` showing 0.1¢ edge ticks, `yes_ask+no_ask = 1.01`
- `GET /markets?series_ticker=KXBTC15M&status=settled&max_close_ts=…` — settled markets with results, 777k–1.79M volume each
- `GET /series/KXBTC15M/markets/KXBTC15M-26JUL021930-30/candlesticks?period_interval=1` — **15 one-minute candles with `yes_bid`/`yes_ask` OHLC**
- `GET /markets?series_ticker=KXBTCD&status=open` — hourly product is a *strike ladder*, 60-minute open→close
- `GET /series/KXDROUGHTLEVEL`, `GET /historical/markets?series_ticker=KXDROUGHTLEVEL` (**0 markets**), `GET /markets?series_ticker=KXDROUGHTLEVEL` (16 markets, 1 event) — **Part 3**
- `GET /historical/cutoff` — `market_settled_ts 2026-06-03T00:00:00Z`
- `GET /incentive_programs` — **102 live liquidity programs**, all `KXEARNINGSMENTION*`
- `GET /markets?series_ticker=KXEARNINGSMENTIONDKNG` — 5–7¢ spreads, ~600–1,500 volume
- `GET /series/KXINXD`, `GET /series/list?...` — **HTTP 404**, not retrieved
- [`kalshi.com/fee-schedule`](https://kalshi.com/fee-schedule) — **HTTP 429, not retrieved.** ADR-0015's open question 2 (which series are maker-fee-enabled) **remains open**; note that `fee_type` and `fee_multiplier` *are* exposed per series on the API and may be the machine-readable answer.

**Polymarket US**
- [Weather FAQs — docs.polymarket.us](https://docs.polymarket.us/faqs/weather-faqs) — **five US cities**, `KNYC`/`KSFO`/`KMIA`/`KMDW`/`KLAX`, NWS CLI settlement, 08:00 ET next-day
- [Liquidity Incentive — docs.polymarket.us](https://docs.polymarket.us/incentives/liquidity.md) — `Score = DF^ticks × Size`, per-second scoring, per-side normalisation, no cap, $1 minimum payout
- [Incentives overview — docs.polymarket.us](https://docs.polymarket.us/incentives/overview.md) — Liquidity / Volume / Market-Maker / Deposit / Referral programmes and their gating
- [polymarket.us/rewards](https://polymarket.us/rewards) — **74 programs / 16,893 markets**; Climate $1,000 / DF 0.30 / target 10,000; Macro $150; Politics High $300; **Crypto ("Coins") and Climate categories both present**
- [docs.polymarket.us/llms.txt](https://docs.polymarket.us/llms.txt) — documentation index
- [Get Markets API reference](https://docs.polymarket.us/api-reference/markets/get-markets.md) — documented `security: []` (**unauthenticated**), base URL `gateway.polymarket.us/v1/markets`
- `https://gateway.polymarket.us/v1/markets` (with and without params) — **HTTP 403, not retrieved.** Contradicts the documented public status; plausibly a bot filter. **This is why Polymarket US market structure is unverified throughout.**
- [polymarket.us](https://polymarket.us/markets) — landing page only; no category inventory
- [Polymarket Prediction Market Review — WSN, updated August 2026](https://www.wsn.com/prediction-markets/polymarket/) — correctly distinguishes US from Global; lists Sports/Politics/Economics/Culture/**Weather** for the US app; **no crypto price markets mentioned**

**Polymarket Global — US access**
- [Geographic Restrictions — help.polymarket.com](https://help.polymarket.com/en/articles/13364163-geographic-restrictions) — structured modification date **2026-07-28**; **`US` in the blocked-countries table**
- [Geoblock — docs.polymarket.com](https://docs.polymarket.com/api-reference/geoblock) — **US is close-only**: *"Users can close existing positions but cannot open new ones, on both the frontend and the API."*
- [Polymarket Supported and Restricted Countries — datawallet, updated 2026-07-29](https://www.datawallet.com/crypto/polymarket-restricted-countries) — US restricted on the global platform; regulated US exchange is the only lawful route
- [Polymarket seeks CFTC approval to reopen main exchange — CoinDesk, 2026-04-28](https://www.coindesk.com/policy/2026/04/28/polymarket-seeks-cftc-approval-to-reopen-main-exchange-to-u-s-traders) — petition pending; **no approval reported**
- `https://polymarket.com/tos` — fetched, body not extractable

**Polymarket Global — weather catalog (the venue Lead A actually trades)**
- [Polymarket Weather Markets — All 44 Cities, datapolymarket](https://datapolymarket.com/markets) — 44 cities / 27 countries incl. **London, Paris, Amsterdam, Milano, Munich, Madrid**; ECMWF/GFS/ICON/JMA/UKMO ensemble
- [High Temp — polymarket.com](https://polymarket.com/weather/high-temperature), [Temperature — polymarket.com](https://polymarket.com/climate-science/temperature) — the listings; **Global venue**
- [5-Minute Crypto — polymarket.com](https://polymarket.com/crypto/5M), [Hourly Crypto — polymarket.com](https://polymarket.com/crypto/hourly) — the Lead B markets; **Global venue**
- ["People Are Making Millions on Polymarket Betting on the Weather" — Medium](https://medium.com/mountain-movers/people-are-making-millions-on-polymarket-betting-on-the-weather-and-i-will-teach-you-how-24c9977b277c) — NYC + London, markets "for the next 1 to 3 days", buy YES below $0.15, act "when 3 or more models agree", prices lag model updates by **"minutes or maybe hours"**. **This is the clearest available statement of Lead A's actual mechanism.**

**Kalshi crypto product background**
- [Kalshi Bitcoin Markets by Frequency — predictionmarketspicks](https://predictionmarketspicks.com/articles/kalshi-bitcoin-markets-by-frequency) — 15-min/hourly/daily/weekly/monthly/yearly, **no 5-minute product**, CF Benchmarks BRTI 60-second average
- [Hourly Crypto Markets — kalshi.com](https://kalshi.com/category/crypto/frequency/hourly)

**In-repo, read in full this session**
`README.md`, `CONTEXT.md`, `docs/product/requirements.md`,
`docs/product/roadmap.md`,
`docs/research/2026-07-17-polymarket-edge-landscape.md`,
`docs/research/2026-07-25-kalshi-category-expansion.md`,
`docs/research/2026-07-28-venue-landscape-refresh.md`,
and ADRs 0014, 0015, 0016, 0017, 0019, 0020, 0021, 0022, 0023, 0024, 0025, 0026,
0027, 0028, 0029.

> **Evidence caveat.** Four claims carry this document and they are of different
> quality. **(a)** The **venue reachability facts** — European temperature markets
> are Global-only, Kalshi lists no non-US cities, Polymarket US lists five US
> cities, the US is blocked/close-only on Global — are **Confirmed** from live API
> pulls and two Polymarket primary pages fetched this session. They are the load
> bearing claims and they were checked hardest. **(b)** The **fee arithmetic**
> throughout (Part 1.4, Part 2.3, Part 4.1) is **Confirmed**: Kalshi's
> coefficients come from ADR-0015's primary-verified schedule, Polymarket US's
> from the refresh's fetch of `docs.polymarket.us/fees`, and **every derived
> figure was recomputed by a second route** — by the identity `fee/notional =
> Θ(1−p)` and again by component sum. **(c)** The **Polymarket US market
> structure** — listing lead time, temperature ladder grid, whether crypto
> Up/Down exists — is **unverified**, because `gateway.polymarket.us` returned 403.
> Every candidate that routes through it is gated behind a cheap measurement for
> exactly this reason. **(d)** The **Lead A and Lead B performance claims** are
> **unverified third-party assertions from sources that returned HTTP 402**, and
> the one internal consistency check available to me **failed**. No figure in this
> document should move capital on its own, and nothing here reopens a candidate
> closed by an ADR — those are decisions the ADRs own.
