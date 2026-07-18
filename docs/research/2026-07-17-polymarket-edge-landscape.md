# Polymarket edge landscape (2026): where can THIS stack make money?

> Commissioned 2026-07-17 after the goal was sharpened to: *"the ultimate goal is
> to use this tool to trade and make money — this is the only goal."* The
> backtester is instrumental, not the deliverable. This doc asks the real
> question: **where can fairline's stack (single developer, snapshot-based,
> non-HFT, paper-first, modest bankroll) plausibly hold durable edge on Polymarket
> in 2026, and what should be built to capture it?**
>
> Evidence discipline (inherited from `2026-07-11-...references.md`): an X-thread
> PnL claim is an **anecdote**; a vendor blog is **reported-unverified**; a
> Polymarket/Kalshi doc / academic paper / on-chain study is **verified**. Every
> load-bearing claim below carries a marker.
>
> **UPDATE 2026-07-17 (later same day):** the user answered the four open
> decisions — **venue = Polymarket US, bankroll < $10k**, copy-trade-first
> accepted, and asked for a direct MM recommendation. Those answers knock out
> both of Part 4's top-two strategies as originally framed. **See Part 5.**
> **FURTHER UPDATE 2026-07-17:** the user then chose **"reconsider venue first."**
> **Part 6 is the US-accessible venue comparison and supersedes the venue choice
> in Part 5.** Working assumption (user is **US-based**, inferred from choosing
> Polymarket US): this research evaluates **only venues legally accessible to a US
> retail trader.** The offshore/international Polymarket is treated as **not
> accessible for this user (execution)**; its *public data* remains usable as a
> signal-research input only. No offshore-access workarounds are considered.

## Assumed stack constraints and bankroll

- One developer, part-time-to-full-time, Python, no co-located/HFT infra, no
  sub-100ms execution path. Snapshot/replay cadence (ADR-0006), paper-first
  (ADR-0001).
- **Assumed bankroll: $10k–$25k.** Stated because every ranking below is
  bankroll-sensitive; if the real number is very different, re-read Part 4. This
  band is chosen because it is the floor at which market-making is viable
  (below) and comfortable for directional/copy sizing into liquid books.
  **[Superseded: actual bankroll is < $10k — see Parts 5 and 6.]**

---

## Part 1 — Structural facts that gate profitability

### 1.1 Fees — Polymarket is no longer fee-free (this is the biggest 2026 change)
**Verified** (help.polymarket.com/trading-fees, docs). Since ~March 2026 Polymarket
charges **taker** fees; **makers are never charged.** Formula:
`fee = shares × feeRate × p × (1−p)` — dynamic, peaks at p=0.50, decays toward
0/1. This is *exactly* the formula already in fairline's `fees.py`, so the code is
current. Per-category `feeRate`:

| Category | feeRate | Max taker fee @ p=0.50 |
|---|---|---|
| Crypto | 0.07 | ~$1.75 / 100 shares (1.75%) |
| Sports | 0.05 | ~$1.25 / 100 |
| Economics / Culture / Weather / Other | 0.05 | ~$1.25 / 100 |
| Finance / Politics / Tech / Mentions | 0.04 | ~$1.00 / 100 |
| Geopolitics / world events | 0 | fee-free |

(One search summary reported sports at 0.03; the help-center doc I fetched says
0.05 — I use the doc. **Reported-unverified:** short-horizon crypto markets carry
a higher dynamic taker fee, said to reach ~3.15% on 50-cent contracts, introduced
explicitly to curb latency arb.) **Note:** this is the *international* venue.
Polymarket US and Kalshi have their own schedules — Parts 5.1 and 6.

**Consequence that reorders everything:** taker strategies now pay a real,
category-varying toll; makers are subsidized. Copy-trading and directional bets
are usually takers; market-making is the maker. This tilts the landscape toward
maker-side strategies. **Kalshi (Part 6) shares this same `rate·p·(1−p)` shape**,
so `fees.py` generalizes across all three venues with a per-venue coefficient.

- **Deposit/withdrawal:** no Polymarket fee to move USDC; Polygon gas negligible
  and abstracted by proxy wallets (**verified**, docs). External ramps may charge.

### 1.2 Two Polymarket venues exist — not interchangeable (jurisdiction gate)
**Verified** (Wikipedia, CFTC Order of Designation, KuCoin/CoinDesk):
- **Polymarket (international / offshore CLOB):** on-chain on Polygon, USDC,
  **no KYC**, public wallet-level trade history — the venue fairline's stack is
  built around. **Geoblocked for US IPs.** → **Not accessible for this user
  (execution).** Public data usable as signal input only (Part 6).
- **Polymarket US (QCX LLC):** launched **Dec 3, 2025**, CFTC-regulated,
  **full KYC**, **USD via FCMs (not crypto)**. Details in Part 5.1.

### 1.3 Liquidity and depth — shallow outside the top names
**Reported-unverified / verified-mixed** (MetaMask Jan 2026; Kaiko Feb 2026;
arXiv microstructure paper 2604.24366):
- Top political/crypto/major-news markets: spreads **$0.005–0.01**, real depth.
- Outside the top ~20 markets: **5-cent spreads common**; thin **$0.08–0.10+**.
- **Books are shallow in absolute terms:** a single Deribit BTC option strike
  regularly exceeds *total* Polymarket market depth by 20–40× (Kaiko).
- Capacity per market is small — which *suits* a modest bankroll, *penalizes* size.

### 1.4 Minimum viable bankroll by strategy (reported-unverified, corroborated)
- **Market-making / reward-farming:** **$10k–$50k** floor — below it you can't
  absorb adverse inventory and must quote wide (killing reward score).
- **Copy-trade / directional:** workable from low four figures in liquid books;
  edge, not capital, is the binding constraint.

---

## Part 2 — Strategy landscape: who wins each niche now

### 2.1 Market making / liquidity rewards (MAKER-side)
- **Edge source:** the **$5M+/month liquidity-rewards pool** (daily, scored on
  1-min random snapshots of resting orders near mid), **maker rebates**, and the
  spread. **Not a latency game** — fits a snapshot stack. (**Verified** program;
  profitability **reported-unverified**.)
- **Real risk — adverse selection:** informed takers pick off stale quotes; can
  "vaporize months of rebate income," worst near resolution. The load-bearing
  **unverified** thesis: *"a maker at flat mid is still net-positive on rebates
  alone."* Must be forward-paper-tested.
- **Build:** a quoting/inventory/fair-value engine fairline lacks; **cannot be
  backtested on historical depth.** **[This describes the INTERNATIONAL program.]**

### 2.2 Copy-trading (scored wallet baskets)
- **Edge source:** a persistent minority of skilled wallets, **fully public
  on-chain** on the offshore venue — auditable P&L (**verified** mechanism).
- **Against:** **weak persistence** — of ~6,600 traders averaging >$5k/mo, only
  **2.6% stayed active >1 year** (**verified**); plus follower latency, taker
  fees, and deliberate exploitation of copiers (reported-unverified).
- **Build:** already built. Cheapest edge test that exists. **[But the data lives
  on the venue this user cannot execute on — see Parts 5–6.]**

### 2.3 Directional EV — weather / niche / longer-horizon (MODEL-based)
- **Edge source:** your forecast model vs. a slow crowd on thin markets.
- **Competitive picture:** real but **compressing** (10pts 2023 → ~3pts 2026);
  **5-min crypto is a lost latency game**, but **longer-horizon (daily/multi-day)
  weather is not** and fits the snapshot stack (reported-unverified/anecdote).
- **Build:** needs a credible `prob_fn` — the hard part (ADR-0005 keeps it
  injected). **[Part 6: these markets are Kalshi's home turf and are backtestable
  there — this strategy is the one the venue switch unlocks.]**

### 2.4 Arbitrage — all forms (TAKER-side, latency-bound)
- Complete-set: rare, fee-gated, gone in seconds, not backtestable.
- Cross-venue (Poly↔Kalshi): **lost to HFT** — windows **12.3s (2024) → 2.7s
  (Q1 2026)**; sub-100ms bots capture ~73% (reported-unverified, consistent).
- **Verdict: deprioritize all of it;** keep the detector as a monitor only.

### 2.5 Sports — largest volume, sharpest competition
- Tight/efficient (1-cent spreads on marquee games); poor directional fit. Good
  *MM* venue, not a directional edge. **[This is exactly — and currently only —
  what Polymarket US lists, Part 5.]**

---

## Part 3 — The competition and the honest base rate

**Verified** (SSRN *Who Wins and Who Loses in Prediction Markets?*, Akey et al.;
on-chain analysis via The Defiant/CoinDesk/Slashdot/Yahoo, Apr–May 2026):

- **~84% of Polymarket traders lose money** (Apr 2026; Dec 2025 study said ~70%).
- **Profits brutally concentrated:** top 1% capture **76.5%**; **<0.04% of
  addresses capture >70%** of realized profit (~$3.7B).
- **Only ~2%** ever cleared **$1,000** profit; **<1%** cleared $10,000.
- **Winners rarely persist** (2.6% of high-earners active >1yr); **~3% of
  traders** drive market accuracy. Winners look **informed/algorithmic** (bots
  ~89 trades/active day vs 2.2 for humans, reported-unverified).

**Reading:** edge is real but scarce, concentrated in an informed/algo minority,
and not durable at the individual level. A systematic, survivorship-safe,
fee-aware process is the right shape; any strategy assuming a specific winner
*keeps* winning is fighting the persistence data.

---

## Part 4 — Verdict (original, bankroll $10–25k, venue-agnostic)

> **Superseded by Parts 5–6 for the confirmed US-retail / <$10k user.** Retained
> for the international-venue-at-≥$10k scenario.

### 4.1 Strategy ranking for THIS stack (single dev, non-HFT, ~$10–25k)

| Rank | Strategy | Survives competition? | fairline build |
|---|---|---|---|
| **1** | Market-making / liquidity rewards | Yes, structurally (not a latency game) | Large — quoter fairline lacks; forward-paper only |
| **2** | Copy-trade (scored baskets) | Partly — real but eroding | None new — already built |
| **3** | Directional EV (longer-horizon weather/niche) | Marginally — compressing | Medium — needs a real `prob_fn` |
| — | Arbitrage (all) | No — latency-lost, fee-gated | Monitor only |
| — | Sports directional | No — sharp/efficient | Avoid |

### 4.2–4.3 (original verdict + proposed edits)
Kept copy-trade-first as cheapest evidence; proposed promoting MM and demoting
arb. **These are superseded by Parts 5–6 for the confirmed constraints.**

---

## Part 5 — US venue + sub-$10k constraints (Polymarket US specifics)

The user confirmed **venue = Polymarket US, bankroll < $10k.** Key facts drove the
"reconsider venue" decision that Part 6 now answers.

### 5.1 What Polymarket US actually is (verified — docs.polymarket.us)
- **Fiat, intermediated, USD, CFTC-regulated DCM.** Not on-chain. KYC mandatory.
- **Markets listed today: sports only** — NFL, NBA, NHL, MLB, MLS, CBB, tennis,
  golf. *"Politics, culture, finance, and economics coming soon."* **No weather,
  crypto, or niche markets.** (**Verified.**)
- **Fee (verified, eff. July 1 2026):** `fee = Θ·C·p·(1−p)`. **Taker Θ=0.06** →
  max **$1.50/100 (1.5%)** at mid. **Maker rebate Θ=−0.0125** → ~**$0.31/100
  (0.31%)** at mid. Volume rebates start at **$250k/mo** — irrelevant sub-$10k.
- **Separate books from international.** **No evidenced public per-trader feed**
  (intermediated/KYC DCM; the public leaderboard/trades Data API is the
  *international* on-chain feed). (**Reported/inferred.**)
- **fairline ingestion is international-only;** Polymarket US has a separate Retail
  API — a new adapter would be required. (Reported/inferred.)

### 5.2–5.4 Conclusion carried into Part 6
No retail maker/rewards path at <$10k here; native copy-trade impossible (no
public per-trader data); directional-EV niche markets **not listed**. **At <$10k
on Polymarket US (sports-only today), there is no strong algorithmic edge path** —
which is why the user chose to reconsider the venue. Part 6 does that.

*(Prior §5.5 recommendation and §5.6 proposed edits are retained in git history;
they are moot now that the venue is being reconsidered.)*

---

## Part 6 — US-accessible venue comparison (supersedes the venue choice above)

**Hard scope rule:** only venues a US retail trader can legally use in July 2026.
The international Polymarket is **not accessible for execution**; its public
on-chain data is retained only as a *signal-research input*.

### 6.1 Comparison table

| Venue | Access for US retail | Categories (algo-relevant) | Fees | Public API / algo policy | Historical data for backtest | Maker/rewards (small acct) | Per-trader public data |
|---|---|---|---|---|---|---|---|
| **Kalshi** | **Direct, KYC** | **Weather + economics (exclusive)**, politics, finance, crypto, sports, culture | Taker `ceil(0.07·p·(1−p)·100)/100`, cap $0.035/contract (~1.75% max at mid); **makers ~free** | **Yes** — public REST + WebSocket + FIX; rate limits make HFT impractical, **medium-freq OK** | **Yes** — trades + candlesticks via public historical endpoints since 2021 (live=last 3mo); **no** historical orderbook depth from official API (3rd parties persist it) | **Yes** — Liquidity Incentive Program (resting-order points, $10–$1,000/day), Volume Incentive (~$0.005/contract); DMM tier is institutional/invite | **Partial/unverified** — profile/positions extraction tools exist; no rich public leaderboard like on-chain Polymarket |
| **Polymarket US** | Direct, KYC | **Sports only today** (politics/finance/econ "soon") | Taker Θ=0.06 (~1.5% max); maker rebate ~0.31% | Separate Retail API (23 REST + 2 WS) | Not evidenced | Weak (0.31% at mid; volume rebates need $250k/mo) | Not evidenced |
| **IBKR Prediction Markets** | Direct (brokerage acct) | Aggregates **Kalshi + ForecastEx + CME** event contracts (econ, climate, policy) | Per-venue + IBKR commissions; smart-routes best price incl. fees | **Yes** — IBKR API (TWS/Client Portal); multi-venue from one account | Via underlying venues (Kalshi) | Inherits venue programs | No |
| **ForecastEx (IBKR-owned)** | Via IBKR | Economics / climate event contracts, longer-horizon | CFTC-registered venue fees | Via IBKR API | Thin/limited | Not evidenced | No |
| **Robinhood event contracts** | Direct (app) | Sourced from **Kalshi/ForecastEx** (router/front-end) | Retail | **No real algo API** | No | No | No |
| **CME Group event contracts** | Via IBKR/brokers | Macro/econ | Exchange fees | Institutional-oriented | Limited | N/A | No |

*(Crypto.com event contracts: exist as CFTC-registered event contracts but were
not strongly evidenced this session; **unverified**, and lower priority than
Kalshi for weather/econ — not assessed further.)*

**Regulatory tailwind (verified):** in March 2026 the CFTC signaled it would
**draft comprehensive rules** for prediction markets rather than ban them — a
pivot that de-risks building on US-regulated venues.

### 6.2 Strategy-fit scoring against fairline's three tracks (US-retail, <$10k)

| Track | Kalshi | Polymarket US | IBKR/ForecastEx |
|---|---|---|---|
| **Directional EV** (weather/econ, longer-horizon) | **Strong** — exclusive weather/econ markets = the exact ADR-0005 niche; not a latency game; **backtestable** (trades+candles); `fees.py` shape matches | None (markets not listed) | Moderate (ForecastEx econ/climate, but thinner + extra integration layer) |
| **Copy-trade** | **Weak** — no rich public per-trader feed; Kalshi markets barely overlap international Polymarket's (weather/econ are Kalshi-exclusive, so international wallet signals don't transfer to them) | None (no US per-trader data; only sports overlap) | None |
| **Maker / rewards** | **Moderate — the only real small-account path** — open Liquidity Incentive Program on resting orders ($10–$1,000/day), but adverse-selection risk remains and <$10k is still tight | Weak | Weak |

### 6.3 Ingestion cost — `KalshiSource` behind ADR-0006
- ADR-0006 **already anticipates** a future `KalshiSource` over Kalshi's REST API —
  this is planned-for, not a detour. Estimated **4–7 dev-days** for markets +
  live/historical trades + candlesticks + orderbook snapshot polling, behind the
  existing `MarketSource` Protocol. (**Lower risk than the 107GB-dataset spike:**
  official, documented, stable, free historical endpoints.)
- **Backtest data genuinely exists** for Kalshi (trades + candles free since 2021)
  — this is the single biggest structural advantage over every Polymarket path,
  where historical depth was unavailable and killed both arb and MM backtests.
  Caveat: full historical *orderbook depth* is not in the official API (only via
  third parties like Kalshi BackTest / Lychee), but a first-pass directional-EV
  backtest needs midprice/candles + settlement, which **are** free.

---

## Part 7 — Venue recommendation and revised-MVP sketch

### 7.1 Recommendation: **Kalshi, direct API, with a directional-EV-on-weather MVP**

**Kalshi is the venue.** It is the only US-legal venue that gives this specific
stack a *backtestable, non-latency, model-based* edge path: its **exclusive
weather and economics markets** are precisely the longer-horizon, model-vs-price
niche fairline's `ev_detector.py` (ADR-0005, already built) was designed for; it
has a **public API with free historical trades + candlesticks** so the edge can
actually be backtested before a cent is risked (the capability every Polymarket
path lacked); its **fee formula is the same `rate·p·(1−p)`** shape `fees.py`
already models; its **rate limits fit a non-HFT snapshot stack**; and it offers a
**retail-accessible maker incentive program** as a secondary track. IBKR is a
reasonable *access* alternative (one account, Kalshi+ForecastEx+CME, smart
routing) but adds an integration layer; **direct Kalshi API is simpler for a
single dev** and is what ADR-0006 already anticipated.

### 7.2 What dies, what's unlocked

**Dies (relative to the paused copy-trade-first plan):**
- **Copy-trade as the MVP.** No US venue exposes a rich public per-trader feed, and
  Kalshi's best markets (weather/econ) don't exist on international Polymarket, so
  international wallet signals don't even transfer to them. The **already-built
  wallet-scoring subsystem becomes a parked asset**, usable later only as
  international-data *signal research* for the categories that do overlap
  (politics/crypto/macro) — not the lead strategy.
- The Polymarket-US-sports-overlap path and the market-making-as-lead idea.

**Unlocked:**
- **Directional EV on weather/econ as the MVP — and it is backtestable.** This
  flips the hardest prior blocker (no historical data) into a solved one. The core
  is `ev_detector.py` + `fees.py` (both built, both Kalshi-ready) + a new
  `KalshiSource` + a replay harness + a `prob_fn`.
- A **real** GO/KILL: does a weather/econ forecast model beat Kalshi's price after
  fees, out-of-sample? That is answerable with free data.

### 7.3 Revised MVP sketch (phases + deltas vs. the paused plan)

Assumes single dev, full-time (~6 hrs/day). Deltas are vs. the copy-trade MVP.

- **Phase 0 — Storage + persistence spine** — **3–5 dev-days.** ~unchanged.
- **Phase 1 — `KalshiSource` ingestion** (markets, trades, candlesticks, orderbook
  polling; historical endpoints) — **4–7 dev-days.** *Replaces* the 107GB-dataset
  spike; **lower risk** (official/free/documented).
- **Phase 2 — `prob_fn` v1 for weather** (NOAA/NWS/ECMWF forecast → temperature/
  hurricane outcome probability; calibration) — **6–12 dev-days.** **NEW** and the
  hard part — this is where the risk moved. *Replaces* the point-in-time
  wallet-scoring phase (that machinery is already built and now parked).
- **Phase 3 — Directional-EV backtest harness** (replay Kalshi candles/trades →
  `ev_detector` EV + quarter-Kelly → paper `Engine` → hold-to-resolution PnL) —
  **5–8 dev-days.** Same "missing harness" as before, retargeted to EV signals.
- **Phase 4 — Report + baseline + trust audit** (EV vs. a naive baseline, e.g.
  always-take-the-favorite or the raw forecast with no fee model; leakage/
  point-in-time audit on the forecast inputs) — **3–5 dev-days.**

**Revised MVP total: ~21–37 dev-days (~4.5–7.5 weeks)** — comparable to the paused
plan's 24–40, but the composition shifts: drops the copy-trade data-eval risk,
**adds the `prob_fn` model build as the new dominant risk**, and — critically —
**produces a backtest on real data**, which the Polymarket plans could not.

Secondary track (post-MVP): **Kalshi maker / Liquidity Incentive Program** as a
small-account income experiment, forward-paper first (still not historically
backtestable for depth). Rank it v0.2, above arbitrage (which stays monitor-only).

### 7.4 Blocking questions for the user (max 2)

1. **Venue access path — direct Kalshi API, or via IBKR?** Direct Kalshi is
   simpler for one dev and matches ADR-0006; IBKR gives Kalshi+ForecastEx+CME from
   one account if you already bank there. *Recommendation: direct Kalshi API for
   the MVP; keep IBKR as a later multi-venue option.*
2. **The MVP's hard part is a probability model.** Weather (temperature/hurricane,
   free NOAA/NWS data) is the most tractable first target. Do you want to
   **(a)** commit to weather-first and build/source the forecast inputs, or
   **(b)** de-risk plumbing first — stand up `KalshiSource` + the backtest harness
   against a *placeholder* model, then invest in the real `prob_fn`? *Recommendation:
   (b) — prove the pipeline on a trivial model, then build the weather model, so a
   modeling setback doesn't hide a working harness.*

---

## Sources

- [Kalshi API docs — rate limits & tiers](https://docs.kalshi.com/getting_started/rate_limits)
- [Kalshi API docs — historical data](https://docs.kalshi.com/getting_started/historical_data)
- [Kalshi fee schedule (PDF)](https://kalshi.com/docs/kalshi-fee-schedule.pdf)
- [Kalshi fees explained 2026 — Market Math](https://marketmath.io/platforms/kalshi)
- [Kalshi Liquidity Incentive Program — Help Center](https://help.kalshi.com/en/articles/13823851-liquidity-incentive-program)
- [Kalshi Liquidity Provider Program — Help Center](https://help.kalshi.com/en/articles/15410219-liquidity-provider-program)
- [Kalshi Incentive Programs](https://kalshi.com/incentives)
- [Kalshi Liquidity Incentive Program — CFTC filing (PDF, Feb 2026)](https://www.cftc.gov/sites/default/files/filings/orgrules/26/02/rules02112639183.pdf)
- [Lychee — Kalshi historical data (36GB+, 72M+ trades)](https://lycheedata.com/kalshi-historical-data)
- [Kalshi BackTest — historical orderbook data](https://kalshibacktest.com/)
- [IBKR — Expands prediction markets (Kalshi, CME, ForecastEx), May 14 2026](https://www.interactivebrokers.com/en/general/about/mediaRelations/5-14-26.php)
- [IBKR Prediction Markets — home](https://www.interactivebrokers.com/predictionmarkets/en/home.php)
- [PredictionNews — Robinhood sources event contracts from Kalshi/ForecastEx](https://predictionnews.com/story/neil-paine-notes-kalshi-and-forecastex-event-contract-sourcing-on-robinhood-c78d80f7)
- [Polymarket Trading Fees — Help Center](https://help.polymarket.com/en/articles/13364478-trading-fees)
- [Fee Schedule — Polymarket US Docs](https://docs.polymarket.us/fees)
- [What is Polymarket US — Polymarket US Docs](https://docs.polymarket.us/getting-started/what-is-polymarket-us)
- [QCX/Polymarket US Market Incentive Program — CFTC notice (PDF)](https://www.polymarketexchange.com/files/notices/Market%20Incentive%20Program%20(2026.03.05).pdf)
- [Polymarket API introduction — Docs (Gamma/Data/CLOB/Subgraph)](https://docs.polymarket.com/api-reference/introduction)
- [Liquidity Rewards — Polymarket Docs](https://docs.polymarket.com/market-makers/liquidity-rewards)
- [Polymarket — Wikipedia (US access / QCEX / CFTC)](https://en.wikipedia.org/wiki/Polymarket)
- [CFTC — Polymarket US Amended Order of Designation](https://www.cftc.gov/media/12806/Polymarket%20US%20Amended%20Order%20of%20Designation/download)
- [SSRN — Who Wins and Who Loses in Prediction Markets? Evidence from Polymarket (Akey, Grégoire, Harvie, Martineau)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6443103)
- [The Defiant — 84% of Polymarket traders are losing money (Apr 2026)](https://thedefiant.io/news/research-and-opinion/polymarket-profitability-report-april-2026)
- [CoinDesk — Only 3% of traders drive prediction markets' accuracy](https://www.coindesk.com/markets/2026/04/26/only-3-of-traders-drive-prediction-markets-accuracy-not-the-crowd-study-finds)
- [Turbine — Prediction-market arbitrage latency (2.7s windows, HFT)](https://www.turbinefi.com/blog/prediction-market-arbitrage-latency-speed-2026)
- [Kaiko / MetaMask on depth & spreads](https://metamask.io/news/5-cent-spread-prediction-markets)
- [arXiv — Microstructure of the Polymarket order book](https://arxiv.org/html/2604.24366v1)
- [laikalabs — Polymarket weather trading bots](https://laikalabs.ai/prediction-markets/polymarket-weather-trading-bot)

> Evidence caveat: vendor-blog figures are **reported-unverified** and
> promotionally biased; used only where multiple independent sources agree and are
> consistent with the **verified** structural facts (fee schedules, venue models,
> the academic base-rate study, official API docs). The load-bearing venue-switch
> facts — **Kalshi's exclusive weather/econ markets, its public API, and its free
> historical trades/candles** — are **verified** from Kalshi docs/help center. The
> **absence of a rich public per-trader feed on US venues** and the **exact
> small-account economics of Kalshi's maker program** are the top items to verify
> before committing. No single PnL claim here should move capital on its own.
