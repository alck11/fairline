# Venue landscape refresh — what changed since 2026-07-17, and does it move the venue call?

> Commissioned **2026-07-28**. This is a **refresh**, not a survey: it re-checks
> only the facts that could reopen a venue closed by
> [`2026-07-17-polymarket-edge-landscape.md`](2026-07-17-polymarket-edge-landscape.md)
> Parts 6–7, which chose **Kalshi, direct API, directional-EV on weather/econ**.
>
> **Date verification (per the brief).** Today's date was checked against live
> sources rather than assumed: DeFi Rate's volume tracker reports figures
> "current as of **July 27, 2026** at 1:59 AM PDT"; CNBC published "Stock market
> next week: Outlook for **July 27–31, 2026**"; multiple venues list contracts
> expiring **July 28, 2026**; the FOMC meets **July 28–29, 2026**. **Confirmed:
> the current date is 2026-07-28.**
>
> **Evidence discipline** (inherited from the two prior research docs): every
> load-bearing claim carries **Confirmed** (verified this session against a
> source I fetched, a file I read, or arithmetic I performed), **Likely
> (unverified)**, or **Assuming**.
>
> **Scope rule, honoured.** Kalshi-internal *strategy* questions — weather
> (ADR-0014), FLB-1 (ADR-0019/0020/0021), econ v0.3 sizing (ADR-0022) — are
> closed in this repo's decision records and are **not** re-litigated here. This
> document proposes no MVP and touches no roadmap. Kalshi's **data-availability
> and API properties** are in scope because the brief asks for them explicitly
> (item 2), and because they are venue properties, not strategy claims.
>
> **Carried forward, not re-derived** (ADR-0015): Kalshi's real fee schedule is
> **taker 0.07, maker 0.0175 (only on maker-fee-enabled series, else zero),
> 0.035 on S&P/Nasdaq index markets, ceil to the next cent, no per-contract
> cap.** The "$0.035 cap" in the 2026-07-17 doc is wrong and stale.

---

## Part 0 — Verdict

**Does anything found here change the Part 6/7 venue recommendation? No — the
venue stays Kalshi. But the recommendation now stands on different legs than the
ones Part 7 gave, two of which have rotted, and there are two cheap probes that
could flip it.** Detail in Part 6; the four findings that drive it:

1. **Polymarket US is no longer sports-only — item 1 changed, as predicted.**
   **Likely (unverified, four independent secondary sources against one stale
   primary):** politics and economics launched **2026-04-08**, off 16 contract
   certifications filed with the CFTC on **2026-03-31**. `docs.polymarket.us`
   still says "coming soon"; it is stale. This is the single biggest delta.

2. **The Polymarket US maker side is a *rebate*, Kalshi's is a *fee*.**
   **Confirmed** from both venues' current schedules. At mid, the swing is
   **1.5 percentage points of notional** on Kalshi's maker-fee-enabled series.
   That is larger than every edge this project has measured to date.

3. **The most consequential finding is about Kalshi, and it is not a change —
   it is a gap in this repo's own measurement.** **Confirmed** from
   `docs.kalshi.com`: Kalshi partitions data into a **live tier ("target window
   for live data is 3 months")** and a **historical tier**, and settled markets
   older than the cutoff are *"only available via `GET /historical/markets`"*.
   **Confirmed** by reading `scripts/wp0_history_probe.py` and ADR-0018: every
   probe that established the "~68-day ceiling" queried **live-tier endpoints
   only**. The ceiling this project measured is exactly where the documented
   live/historical boundary sits. **It has never been tested against the
   historical tier.**

4. **Regulation moved from "signal" to "concrete but unfinished."** **Confirmed:**
   a Notice of Proposed Rulemaking published **2026-06-12**, comments closed
   **2026-07-27** (yesterday) — proposed, not final — plus **CFTC Staff Advisory
   26-22 on 2026-07-24** warning Kalshi, Polymarket, Coinbase and Crypto.com
   against blanket template self-certifications. Neither restricts weather or
   economics contracts. Directionally *restrictive* on sports micro-props, which
   this project does not trade.

**The one thing to do next**, if anything: a ~1-hour, zero-risk read-only probe
of `GET /historical/cutoff` + `GET /historical/markets?series_ticker=KXHIGHNY`.
It costs less than reading this document and it is the only known test that could
reopen the candidates ADR-0016 killed.

---

## Part 1 — Item 1: Polymarket US categories

**Question:** still sports-only, or have politics/finance/economics launched?

**Answer: launched.** **Likely (unverified)** — the evidence is four independent
secondary sources plus indirect primary corroboration, against one stale primary
page. I could not obtain a clean primary listing, so this is not marked
Confirmed; see "how to close it" below.

### The evidence, weighed

**For the launch:**

- **DeFi Rate, published 2026-04-08 (updated 2026-04-20), with filing-level
  specificity:** Polymarket US launched politics and economics markets on
  **2026-04-08**, after filing **16 new contract certifications with the CFTC on
  2026-03-31**. First batch named: **April Fed decision, April CPI year-over-year,
  US House Midterm winner, US Senate Midterm winner**. The 16 certifications are
  broken out as five election/political, three macroeconomic, two AI-native,
  three entertainment, one sports-props, one crypto-price, **one weather**. The
  article attributes this to **Polymarket US, "operated by QCX LLC, a
  CFTC-regulated Designated Contract Market,"** explicitly distinguishing it from
  Polymarket Global. Same article: catalog grew from 1,372 to **4,100+ markets in
  one calendar month**; **$255.9M** March notional; **$5,000/day per eligible
  politics market** set aside in liquidity rewards.
- **A primary artifact exists at the matching date.** **Confirmed:** a product
  certification PDF is published on the DCM's own filing site —
  `polymarketexchange.com/files/products/PMUS - CFDVC - (2026.04.03).pdf`,
  titled *"PMUS - CFDVC - (2026.04.03) - Product Certification.docx"*, filed by
  **QCX LLC d/b/a Polymarket US** via the CFTC portal, dated **2026-04-03**. I
  retrieved the file but its content stream did not extract to readable text, so
  the product list inside it is **not** verified — only its existence, filer, and
  date are.
- **The venue's own marketing copy.** **Confirmed** (fetched `polymarket.us`
  this session): the landing page reads **"Trade on sports, politics, and more"**
  and surfaces a **"Presidential election market."** A second fetch of
  `polymarket.us/markets` surfaced politics and tech references. Thin, but it is
  the venue's own site and it directly contradicts "sports only."
- **Two July 2026 platform reviews** independently list Polymarket US as
  covering **politics (2026 House/Senate midterms, policy outcomes), economics
  (Fed decisions, inflation, recession odds), culture, and weather (daily high
  and low temperatures for major cities)** alongside sports.

**Against:**

- **`docs.polymarket.us/getting-started/what-is-polymarket-us`, fetched this
  session, still reads verbatim:** available = *"NFL, NBA, NHL, MLB, MLS, CBB,
  Tennis, golf, and more"*; *"Politics, culture, finance, and economics coming
  soon."* **Confirmed** that the page says this. It is the same wording the
  2026-07-17 doc quoted, and it carries no last-updated date.

**Reading:** a static onboarding page that was not revised after the product
shipped. This is an extremely common failure mode and it is the *only* evidence
on the "against" side. Four sources — one of them the venue's own homepage, one
of them a dated CFTC filing artifact — beat one undated doc page.

**A search-summary artifact worth naming so it does not get re-quoted as
evidence.** A search engine paraphrased a DeFi Rate article as saying Polymarket
US "still only offers sports markets." I fetched that article
(**published 2026-06-08, updated 2026-07-04**): it says no such thing. It reports
that during World Cup week **nine of the top ten Polymarket US markets by volume
were soccer contracts** and that the NBA champion market was "the only non-soccer
contract in the top ten." That is a statement about *what traded*, not about
*what is listed* — and it is exactly what a sports-dominated venue with a young
non-sports catalog looks like. **Confirmed** by direct fetch.

### How to close this to Confirmed, cheaply

Open the app or hit the API and filter `GET /markets?categories=...`. **Five
minutes with an account.** Until then this stays **Likely (unverified)**, and
nothing in Part 6 depends on the *precise* category list — only on
"non-sports exists," which is now well past the balance of evidence.

### What Polymarket US now offers that Part 6's table recorded as absent

Part 6's table gave Polymarket US: *sports only; historical data "not evidenced";
maker/rewards "weak"; per-trader data "not evidenced."* Three of those four are
now wrong or materially understated.

**Fees — Confirmed**, fetched `docs.polymarket.us/fees` this session, effective
**12 AM ET Wednesday 2026-07-01** (i.e. **unchanged since the 2026-07-17 doc**):

```
fee = Θ × C × p × (1 − p)
taker   Θ = +0.06     → max $1.50 per 100 contracts at p = 0.50
maker   Θ = −0.0125   → max ≈ $0.31 CREDIT per 100 contracts at p = 0.50
taker volume rebates: $250k–$999k/mo → 10%; $1M–$9.99M → 25%; $10M+ → 50%
```

Note the accelerated-tier clause, which is new information rather than a change:
a trader may submit **verifiable proof of trailing-30-day notional volume on
another prediction market** to be placed in a higher rebate tier. Irrelevant
sub-$10k — every tier starts at $250k/month.

**The maker-side arithmetic, which is the real story.** All **Confirmed**, each
figure recomputed by the identity `fee / notional = Θ × (1 − p)`:

| side, at p = 0.50 | Kalshi | Polymarket US |
|---|---|---|
| taker, per contract | 0.07 × 0.25 = **1.750¢** | 0.06 × 0.25 = **1.500¢** |
| taker, % of notional | 0.07 × 0.5 = **3.50%** | 0.06 × 0.5 = **3.00%** |
| maker, per contract | **0.4375¢ charged** (maker-fee series) or **0** | **0.3125¢ credited** |
| maker, % of notional | **+0.875%** or **0** | **−0.625%** (paid to you) |

- Polymarket US taker is **14.3% cheaper** than Kalshi's (1 − 0.06/0.07).
- The maker swing at mid is **0.875% + 0.625% = 1.50 percentage points of
  notional** on Kalshi's maker-fee-enabled series, and **0.625 points** on the
  rest of Kalshi's catalog where makers pay nothing. For scale: ADR-0019's
  measured FLB edge was **+0.88% net**. **The venue choice on the maker side is
  worth more than the only edge this project has ever measured.**

**Data and incentives — Confirmed**, from `docs.polymarket.us/llms.txt` (the
documentation index) fetched this session. Polymarket US documents:

- `GET /v1/orderbook/{symbol}/bbo` and `GET /v1/orderbook/{symbol}` (full L2),
  described as **"Public market data available to all users"**, plus a gRPC
  market-data stream;
- `Get Market Settlement` — settlement price per market;
- `POST /v1beta1/report/trades/search`, `POST /v1beta1/report/trades/stats`
  (server-side **candlestick aggregation at 1m/5m/15m/1h/4h/1d**), and a
  **trades CSV download** stream;
- **three** incentive programs with API surface: **Liquidity Incentive**
  ("resting orders close to the best price"), **Market Maker**, and **Volume
  Incentive**.

Two caveats that keep this from being a straight upgrade. **Confirmed:** the
market-data guide shows `Authorization: Bearer YOUR_ACCESS_TOKEN` with scopes
`read:marketdata` / `read:l2marketdata`, so even the "public" data appears to sit
behind an account token — a KYC'd account is a prerequisite to *evaluating* the
venue. **Confirmed:** neither the market-data guide nor the candlestick guide
states **any retention period or archive depth**. So Polymarket US's history
depth is **completely unknown** — it could be better than Kalshi's live tier or
worse, and the venue is only ~8 months old, which caps it regardless.

**Size, for calibration. Confirmed:** Kalshi did **$17.91B** in May 2026 and
**$4.46B** in the week of June 1. Polymarket US's **record** week was **$882M**
(week of June 1, World Cup). Polymarket's own volume tracker states plainly that
Polymarket US "is a separate platform and represents a small fraction of
Polymarket's total activity." Polymarket US is roughly **an order of magnitude
smaller than Kalshi** in weekly notional.

---

## Part 2 — Item 2: Kalshi fee schedule, API policy, historical-data retention

### 2.1 Fees — no change since 2026-07-17

**Likely (unverified):** the current schedule remains the *"Fee Schedule for July
2026 – 7.7.26 Update"* — the same version ADR-0015 already flagged and which
**predates** the 2026-07-17 doc by ten days. The search index still surfaces that
exact title; the PDF itself still 429s to non-browser clients, exactly as ADR-0015
recorded. Secondary sources this session restate the same structure (maker = 25%
of taker; taker peaks at 1.75¢ per contract at 50¢; no ACH fees; no account,
inactivity, data or overnight-holding fees; card deposits up to 2%). **Nothing
found suggests a coefficient change.** ADR-0015's coefficients carry forward
unamended, including its open question 1 (one real fill receipt settles the
July-revision question outright).

### 2.2 API — real changes since 2026-07-17, two of which matter

**Confirmed**, fetched `docs.kalshi.com/changelog` this session. Filtering to
entries dated after 2026-07-17, and to what could touch this project:

| date | change | why it matters here |
|---|---|---|
| **2026-07-09** | **New `price_level_structure` values**: seven structures with **center ticks of 1¢, 0.5¢ or 0.2¢ and edge ticks to 0.1¢**. "Consume the `price_ranges` array on the market object to determine valid order prices." Pilot markets **week of July 27**, expansion **week of August 3**. | **Kalshi is going sub-penny.** Every spread and rounding figure in the 2026-07-25 doc's Part 2 assumes a 1¢ grid. The `≥ ~98 units / ~$100 notional` minimum economic order size derived there comes from the ceil-to-the-cent *fee* rounding, which is unchanged — but half-spread costs on edge-priced contracts can now fall to 0.05¢, which improves exactly the high-price NO trades that project cared about. Any future price-grid assumption must read `price_ranges`, not assume cents. |
| **2026-07-02** | **Multivariate lookup history endpoints fully deprecated** — "no longer function as a historical data resource." | ADR-0016 found 97% of the settled-market population was `KXMVE*` sports-parlay combinations. That population is now partly unqueryable historically. No loss — sports was already out of scope. |
| **2026-06-25** | **API usage tier qualification requirements halved** — volume thresholds for all tiers cut to half. | Rate-limit tiers are now cheaper to reach for a small account. Marginally improves the "medium-frequency OK" assessment in Part 6's table. |
| **2026-07-23** | `GET /historical/positions` added (authenticated, settled positions). | Confirms the historical tier is under **active development** — see 2.3. |
| **2026-07-22** | `GET /incentive_programs` now excludes programs on hidden events. | Housekeeping for the parked LIP track. |
| **2026-07-04** | `GET /exchange/announcements` **removed**. | Breaking, if anything had depended on it. Nothing here does. |

Also visible across June–July 2026: subaccount-restricted API keys, RFQ/quote
lifecycle over FIX with post-only support, per-index exchange status and balances,
and a `/margin/*` surface. **Kalshi is building out professional maker
infrastructure at pace.** Read alongside ADR-0019's finding that Kalshi makers
outperform takers by ~22 points, that is a directionally relevant venue fact even
though the MM track is parked.

**Dating caveat, stated because I noticed it:** the changelog carried an entry
dated **2026-07-30**, two days ahead of today. Either entries are post-dated on
publication or the page's dating is unreliable at the margin. I have not relied
on that entry; the July 2–23 entries above are consistent with the rest of the
timeline and with the July 23 entry that search independently surfaced.

### 2.3 Historical data — the finding that matters most in this document

**This is not a change since 2026-07-17. It is a gap in this repo's own
measurement, and it is the most consequential thing I found.**

**Confirmed**, from `docs.kalshi.com/getting_started/historical_data` fetched
this session:

> Kalshi partitions exchange data into **live** and **historical** tiers.
> `GET /historical/cutoff` returns the boundary timestamps (`market_settled_ts`,
> `trades_created_ts`, `orders_updated_ts`, `market_positions_last_updated_ts`).
> **"The target window for live data is 3 months."** Records older than the
> relevant cutoff **"must be queried through the corresponding historical
> endpoint"**:
> - `GET /historical/markets` — *"settled markets older than the cutoff"*
> - `GET /historical/trades` — *"all trades older than the cutoff"* (the
>   changelog entry of **2026-03-06** describes this as **a public endpoint**)
> - `GET /historical/markets/{ticker}/candlesticks` — candles for historical
>   markets
>
> Historical endpoints support the same cursor pagination as their live
> counterparts. The `/historical/*` family was introduced **2026-02-19**;
> `series_ticker` filtering was added to `GET /historical/markets` on
> **2026-04-10**.

Now set that against what this project actually measured. **Confirmed** by
reading the code and the ADRs this session:

- `scripts/wp0_history_probe.py` queries `GET /markets?series_ticker=…&status=settled`,
  `GET /events?with_nested_markets=true&status=settled`,
  `GET /series/{s}/markets/{t}/candlesticks`, and `GET /markets/trades`.
  **The string `historical` does not appear in the file.**
- ADR-0018's three "independent" authenticated confirmations were
  `GET /events/{ticker}`, `GET /markets?event_ticker=…`, and the paginated
  listing. **All three are live-tier endpoints.**
- ADR-0016's two "independent confirmations" — `max_close_ts` filtering finding
  nothing in 2024/2025, and prior-year events existing as **empty shells with
  zero nested markets** — were both run against `GET /markets` and `GET /events`.
  **Both are live-tier endpoints.**
- `src/ingest_kalshi.py` lines 32–36 document the boundary from the *other*
  side: the module deliberately avoids `/historical/markets/{ticker}/candlesticks`
  because it **"404s for markets that haven't crossed Kalshi's historical-archive
  cutoff yet — confirmed live."** The repo has already observed the tier
  boundary in the one direction that does not help it.

**The measured ceiling was 66–68 days. The documented live-tier target window is
3 months. Every ADR-0016/0018 observation is exactly what a tier boundary looks
like, and is equally consistent with deletion.** The two hypotheses have never
been separated, because the discriminating query was never run.

**Likely (unverified): the ~68-day ceiling is a live/historical tier boundary,
not data retention.** I mark this Likely, not Confirmed, because I have no
execution environment in this session and could not run the API. Supporting it:
the documented 3-month live window matches the measured span's order of
magnitude; the historical tier is documented as serving precisely "settled
markets older than the cutoff"; `/historical/trades` is documented public; the
tier has been shipping features as recently as five days ago; and Bürgi–Deng–Whelan
demonstrably obtained 2021–2025 Kalshi history, which ADR-0018 could only explain
by speculating about prospective collection or a since-tightened policy — a third
explanation (they queried the archive) now exists and is simpler than both.

**Against it — stated so this is not one-sided.** ADR-0018's finding that
`GET /events/KXHIGHNY-25JUL27` returns 200 with **zero nested markets** is real
and is not explained away by tiering *unless* nested-market expansion is itself
live-tier-only — which is likely but unproven. Kalshi may also have separately
purged data older than the archive's own horizon, in which case the archive
depth is short and the ADR-0016 conclusions survive intact. And the archive may
prove authenticated-only despite `/historical/trades` being documented public.
**One probe settles all of this.**

**The exact falsifying test — read-only, unauthenticated first, ~1 hour:**

```
GET /historical/cutoff                                  → read market_settled_ts
GET /historical/markets?series_ticker=KXHIGHNY&limit=200 → does it return markets
                                                           older than that ts?
GET /historical/markets?series_ticker=KXNOBELPEACE       → the long-dated series
GET /historical/markets?series_ticker=KXHURCTOT            that returned 0/0
GET /historical/markets/{an old ticker}/candlesticks     → do candles survive?
GET /historical/trades?ticker={an old ticker}            → does the trade feed?
```

If it returns nothing, ADR-0016 and ADR-0018 stand and this note costs one hour.
If it returns markets behind the cutoff, then **HURSEAS-1 and DROUGHT-1 are not
dead, MRAIN-1 is not underpowered, FLB-1's "emotional" basket is not
unstudiable, and the econ-v0.3 power problem in ADR-0022 (14 independent releases
in ~68 days) may be an artifact of querying the wrong endpoint.** ADR-0016 itself
named this: *"It does not prove the ceiling is exactly 68 days or permanent… It is
what the venue served on 2026-07-26… Re-running the probe is cheap and is the
correct check before reopening any candidate killed here."*

**I am not reopening those candidates.** Each is closed by its own decision
record and that is out of this document's scope. I am reporting a **venue
data-availability fact** — item 2 of the brief — and the fact is that the
project's most load-bearing venue measurement was taken on the endpoints Kalshi
documents as *not* serving the data in question.

---

## Part 3 — Item 3: did the CFTC's March signal produce anything concrete?

**Yes, three concrete things. None of them changes what this project can trade;
one adds a small listing-stability risk to sports, which is already out of scope.**

**1. A staff advisory, 2026-03-12 — Confirmed** (CFTC press release 9193-26,
fetched this session; CFTC Staff Letter 26-08). The Division of Market Oversight
reminded DCMs of obligations under **CEA §5(d), Part 38, DCM Core Principle 3 and
Appendix C**, and of product-submission requirements, while stating it "seeks to
encourage growth and innovation." Framing is pro-market with a compliance
reminder. Sports contracts get special attention.

**2. A Notice of Proposed Rulemaking — Confirmed** (Greenberg Traurig analysis
fetched this session; Federal Register page itself blocked cross-host redirects).
*"Prediction Markets; Public Interest Determinations,"* amending **Rule 40.11**:

- Proposed **2026-06-10**, published in the Federal Register **2026-06-12**,
  comments closed **2026-07-27**. **Status: proposed, not final.** (Confirmed
  independently by two law-firm alerts and a CRS product.)
- Establishes a **three-step framework**: is it an event contract in an excluded
  commodity → does it "involve" an enumerated activity (unlawful activity,
  terrorism, assassination, war, gaming) → is it contrary to the public interest.
- Category effects as analysed: **economics contracts (CPI, GDP, unemployment)
  generally excluded from the restrictive scope**; **elections fall outside scope**
  (treated as contests, not gaming); **broad sports outcomes generally permitted**
  but **player injuries, officiating decisions and discrete in-game actions
  disfavoured**; **weather is not specifically addressed.**
- Introduces a **90-day heightened-review path** that could block listings.

**Read for this project:** net **restrictive** for retail generally, but the
restriction lands on sports micro-props. **Weather and economics — the only
categories Part 7's thesis needs — are untouched, and economics is explicitly
carved out.** The March 2026 "comprehensive rules" signal the old doc recorded as
a tailwind has materialised as a real NPRM that leaves this project's categories
alone.

**3. A second staff advisory, 2026-07-24 — Likely (unverified; Bloomberg is the
originating report and is paywalled, but five independent outlets carry
consistent detail).** **CFTC Staff Advisory No. 26-22** targets **blanket
template self-certifications** — filings bundling many contract permutations
under one submission without per-permutation terms and conditions or compliance
analysis. Named recipients: **Kalshi, Coinbase, Polymarket, Crypto.com.**
Self-certification without prior approval survives; the boilerplate shortcut does
not. This is the second such warning in 2026.

**Read for this project:** a **listing-cadence risk, not an access risk.** Venues
that mass-certify templated ladders may have to file more granularly, which could
slow new series listings. Kalshi's daily weather ladders and econ series are
long-established individual products. **No US-legal access changes; no new legal
venue created; nothing reopened.**

---

## Part 4 — Item 4: new venues, and changes at IBKR / ForecastEx / CME / Robinhood

**Summary: the category grew a lot, but every new name is either a sports venue,
a front-end for a venue already in Part 6's table, or both. Nothing new is a
directional-EV research venue.**

**Confirmed / Likely (unverified) as marked:**

| Venue | What it is now | Relevance here |
|---|---|---|
| **Railbird Exchange, d/b/a DKeX** (DraftKings) | **Likely (unverified):** Railbird approved as a DCM **June 2025**, acquired by DraftKings **Oct 2025**, launched as DKeX **2026-06-26**; first product certifications are **six binary templates** for game winners, spreads, game/player props, head-to-head. | **Sports-only exchange.** Out of scope by the 2026-07-17 doc's own sports ruling, which nothing here reopens. |
| **Crypto.com / OG Prediction Markets (CDNA)** | **Likely (unverified):** Crypto.com's affiliate **North American Derivatives Exchange (Nadex)** is a CFTC-registered **DCM and DCO**, trading as **OG Prediction Markets / Crypto.com Derivatives North America**; OG launched **Feb 2026**. Supplies contracts to **DraftKings Predictions** (Feb 2026) and **FanDuel Predicts** (2026-06-09). | The 2026-07-17 doc listed Crypto.com event contracts as unverified and unassessed. Now verified to exist as a real DCM — **but its visible catalog is sports and player props**, and it is a wholesale supplier to sportsbooks. No weather/econ research case. |
| **Coinbase** | **Likely (unverified):** launched US prediction markets **2026-01-27/28**, **powered by Kalshi**; crypto price contracts on BTC/ETH/SOL/XRP/BNB/DOGE/HYPE, 15-minute to one-year horizons, $1 minimum; also acquiring "The Clearing Company." | **A Kalshi front-end, not a venue.** Same liquidity pool. Its only relevance is that Kalshi's retail flow is being fed by Coinbase and Robinhood — more uninformed flow into the venue this project already uses. |
| **FanDuel Predicts** | **Likely (unverified):** expanded event contracts via Crypto.com's OG, announced **2026-06-09**, timed to the World Cup. | Sports. Front-end. Out of scope. |
| **IBKR Prediction Markets** | **Confirmed unchanged:** still aggregates **Kalshi + CME + ForecastEx** in one account. No material change found since 2026-07-17. | Part 6's assessment stands verbatim: an access path, not a strategy unlock. |
| **ForecastEx** | **Confirmed unchanged:** tradable only via its two broker partners, **IBKR and Robinhood**; contracts cover economic indicators, weather, climate and some political events. **Likely (unverified):** $0 maker fee. | Still thin, still an extra integration layer. The $0-maker claim is the one thing here worth a later look if a maker track is ever unparked. |
| **CME event contracts** | No change found. | Unchanged. |
| **Robinhood** | **Confirmed** it now runs branded prediction-market pages (FX, crypto, and other event contracts, e.g. USD/JPY and BTC price events dated 2026-07-28), sourced from **Kalshi/ForecastEx**. | Still **no real algo API**. Front-end. Unchanged conclusion. |

**Market context, Confirmed:** total prediction-market volume grew from under
**$1B in June 2024** to nearly **$24B in April 2026**. Kalshi alone did **$17.91B
in May 2026**. The sector's growth is real and is overwhelmingly sports-driven.

**The structural pattern worth naming:** the 2026 wave is **distribution**, not
new liquidity venues. DraftKings, FanDuel, Coinbase and Robinhood are all
front-ends routing into **three** clearing venues — Kalshi, Crypto.com/Nadex, and
Railbird/DKeX — plus ForecastEx and CME. For a research stack, **the number of
places to look for a directional-EV edge did not increase.**

---

## Part 5 — Item 5: Polymarket international's US accessibility

**Changed from "static" to "a live pending petition," but the operative fact is
unchanged: still geoblocked, still not legally usable for execution by this
user.**

**Confirmed:**
- The international exchange (Polygon, USDC, no KYC) **remains geoblocked for US
  IP addresses** as a condition of the **2022 CFTC settlement** ($1.4M, cease and
  desist).
- On **2026-04-28**, Polymarket **petitioned the CFTC to lift the US block** on
  the main exchange (Bloomberg, via CoinDesk). **The CFTC would have to vote**
  before the block could be removed; the process may be affected by **four vacant
  Commission seats**. **No approval has been reported as of 2026-07-28.**
- **Likely (unverified):** Polymarket also applied for a **margin-trading
  licence in July 2026**, and the **CFTC opened an investigation into Polymarket
  in June 2026** (CNBC, 2026-06-26) — reportedly concerning **influencer
  marketing practices**, not the legality of trading on the regulated US venue.

**Read:** the hard scope rule from Part 6 holds unchanged — **international
Polymarket is not accessible for execution; its public on-chain data remains a
signal-research input only.** But this is now a **watch item with a named
trigger** rather than a permanent closure: *a CFTC vote granting the April 28
petition*. If that lands, the venue that this repo's entire ingestion stack was
originally built around — with public per-trader data, the parked wallet-scoring
subsystem, and a fee schedule with **fee-free geopolitics markets** — becomes
legally available in one step. **No workaround is contemplated here; VPN access
is not a path and is not considered.**

Also worth recording, **Likely (unverified)**, because it changes a number in the
old doc's §1.1 table: the international taker `feeRate` for **sports** is now
reported at **0.03**, not the 0.05 the help-centre doc gave in July. Crypto 0.07,
finance/politics/mentions/tech 0.04, economics/culture/weather/other 0.05,
geopolitics/world events **fee-free** — otherwise unchanged. Immaterial while the
venue is inaccessible; noted so a future refresh does not treat 0.05 as settled.

---

## Part 6 — Does this change the Part 6/7 recommendation?

### 6.1 The verdict

**No. The venue recommendation stays Kalshi. But two of Part 7's four stated
reasons are void, and the decision is much closer than it was.**

Part 7's exact words were that Kalshi is *"the only US-legal venue that gives
this specific stack a backtestable, non-latency, model-based edge path,"* resting
on four legs. Their status today:

| Part 7's reason | Status on 2026-07-28 |
|---|---|
| **"Exclusive weather and economics markets"** | **Void as stated.** Polymarket US lists economics (Fed, CPI) since April, and one July review says it lists daily city high/low temperature. ForecastEx also lists economics and weather. Exclusivity is gone; **leadership is not** — Kalshi's weather ladders run 20 cities × high/low with two-sided quotes on 6–11 of 12 strikes (ADR-0016 / 2026-07-25 doc). |
| **"Public API with free historical trades + candlesticks so the edge can be backtested"** | **Broken by this repo's own ADRs (0014/0016/0018) at the ~68-day live tier — and now, per Part 2.3, plausibly not broken at all.** This leg is currently *unknown*, which is worse than either answer. |
| **"Fee formula is the same `rate·p·(1−p)` shape `fees.py` already models"** | **Still true, and now true of Polymarket US too** — same shape, coefficient 0.06 taker / −0.0125 maker. `fees.py` generalises to it with a per-venue coefficient, exactly as the 2026-07-17 doc predicted. **This leg no longer discriminates between the two venues.** |
| **"Rate limits fit a non-HFT snapshot stack; retail-accessible maker incentive programme"** | **Still true, and improved** — tier qualification thresholds halved 2026-06-25. But Polymarket US now documents **three** incentive programmes with API surface and **pays** its makers rather than charging them. |

**So why does the recommendation still stand?** Four reasons, in order of weight:

1. **The switching cost is real and the benefit is unproven.** ADR-0016 ruled
   "do not build any new ingestion adapter." A `PolymarketUSSource` is a fresh
   adapter against an auth-gated API of **entirely unknown history depth**, on a
   venue **eight months old** — so its archive cannot exceed ~8 months no matter
   how generous its retention, and Kalshi's *worst case* is already 2.2 months
   with a possible archive behind it.
2. **Size.** Kalshi ≈ **$4.46B/week**; Polymarket US's record week ≈ **$882M**,
   heavily sports. A venue an order of magnitude smaller with a young non-sports
   catalog is a worse place to find 400+ resolved non-sports markets.
3. **The binding constraint was never the venue.** Every candidate died on
   **statistical power or edge magnitude**, not on venue mechanics. Moving venues
   does not fix a power problem; **finding more retrievable history does**, which
   is why Part 2.3's probe outranks any venue switch.
4. **This project already has a working, tested, authenticated Kalshi adapter**
   with the fee model pinned cell-by-cell against the published tables
   (ADR-0015, `tests/test_fees.py`, 84 cells).

### 6.2 What genuinely did change, stated plainly

- **Polymarket US is promoted from "no strong algorithmic edge path exists here"
  (Part 5.2) to "the leading alternative venue, blocked on one unknown."** That
  unknown is its historical depth. Part 6's table should be read as stale on the
  Polymarket US row.
- **The maker-side venue ranking has flipped.** For any future market-making or
  resting-order strategy, **Polymarket US pays the maker and Kalshi charges it**
  (on maker-fee-enabled series). Worth **1.5 points of notional at mid** — larger
  than ADR-0019's entire measured edge. The MM track is parked, but when it is
  unparked, **the venue question must be re-opened rather than inherited**, and
  the LIP economics note in the 2026-07-25 doc's Part 6 should say so.
- **Regulation is a mild positive for this project's categories** and a mild
  negative for sports micro-props, which are out of scope.
- **International Polymarket has a named trigger to watch** rather than being
  permanently closed.

### 6.3 What would flip the recommendation

Stated falsifiably, so a future session can check rather than re-argue.

1. **`GET /historical/markets` returns nothing behind the cutoff** *and*
   **Polymarket US's trade/candlestick endpoints serve its full 8-month history
   for non-sports markets.** Then Polymarket US has strictly more retrievable
   history than Kalshi and the cheaper taker fee, and the venue should switch.
2. **A maker/LIP track is prioritised.** Then the 1.5-point maker swing plus
   three documented incentive programmes probably makes Polymarket US the venue
   on its own, subject to a depth check on its books.
3. **The CFTC grants the 2026-04-28 petition.** Then international Polymarket
   reopens with public per-trader data, the parked wallet-scoring subsystem, and
   fee-free geopolitics markets — a different and larger question than the one
   this refresh was asked.

None of the three is true today. **Kalshi stays.**

---

## Open questions

1. **Does `GET /historical/markets` reach behind the ~68-day live cutoff?**
   *(Assuming: it does, at least partially — the documented 3-month live window
   matches the measured span too closely to be coincidence.)* If the assumption
   is wrong, nothing changes and ADR-0016/0018 stand. If it is right, the
   data-availability premise under several closed decisions was measured on the
   wrong endpoints. **~1 hour, read-only, unauthenticated first.** This is the
   highest-value unresolved item in the project, displacing the IBKR-APY question
   from the 2026-07-25 doc.
2. **What is Polymarket US's actual non-sports catalog and its historical data
   depth?** *(Assuming: politics and economics are live per Part 1; depth is
   unknown and bounded above by ~8 months of venue age.)* Both answerable in
   under an hour with a KYC'd account, which the venue requires even for
   "public" market data.
3. **Does Kalshi's sub-penny tick rollout (pilot week of 2026-07-27, expansion
   week of 2026-08-03) reach the series this project studies?** *(Assuming: it
   reaches liquid series first, so weather ladders and econ series are likely
   in scope within weeks.)* If so, every 1¢-grid spread assumption in the
   2026-07-25 doc's Part 2 needs re-deriving from each market's `price_ranges`
   array. Fee **rounding** stays at the cent and is unaffected.

---

## Sources

Fetched or searched this session (2026-07-28):

**Polymarket US**
- [What is Polymarket US — docs.polymarket.us](https://docs.polymarket.us/getting-started/what-is-polymarket-us) — fetched; still says "Politics, culture, finance, and economics coming soon"; **assessed as stale**
- [Fee Schedule — docs.polymarket.us](https://docs.polymarket.us/fees) — fetched; taker Θ=0.06, maker Θ=−0.0125, effective 2026-07-01, volume rebate tiers
- [docs.polymarket.us documentation index (llms.txt)](https://docs.polymarket.us/llms.txt) — fetched; candlestick/trades/settlement/incentive endpoint inventory
- [Market Data guide — docs.polymarket.us](https://docs.polymarket.us/data-guide/market-data.md) — Bearer-token auth, BBO + L2, no stated retention
- [Candlestick Data guide — docs.polymarket.us](https://docs.polymarket.us/data-guide/candlestick-data.md) — 1m/5m/15m/1h/4h/1d, no stated retention
- [polymarket.us](https://polymarket.us/) — "Trade on sports, politics, and more"
- [Polymarket US Posts $256M March, Launches Politics — DeFi Rate, 2026-04-08](https://defirate.com/news/polymarket-us-posts-256m-march-launches-politics-built-to-scale/) — launch date, 16 CFTC certifications filed 2026-03-31, first four markets, $5,000/day politics liquidity rewards
- [QCX LLC d/b/a Polymarket US product certification, 2026-04-03 (PDF)](https://www.polymarketexchange.com/files/products/PMUS%20-%20CFDVC%20-%20(2026.04.03).pdf) — retrieved; **content not extractable**, existence/filer/date only
- [Kalshi Sets $17.9B Record May… — DeFi Rate, 2026-06-08 (upd. 2026-07-04)](https://defirate.com/news/kalshi-sets-17-9b-record-may-world-cup-lifts-polymarket-us-weekly-high/) — Kalshi $17.91B May / $4.46B week; Polymarket US $882M record week; **does not claim sports-only**
- [Polymarket volume tracker — DeFi Rate](https://defirate.com/prediction-markets/volume/polymarket/) — "Polymarket US… is a separate platform and represents a small fraction"; page current 2026-07-27
- [Polymarket Prediction Market Review July 2026 — WSN](https://www.wsn.com/prediction-markets/polymarket/) — politics/economics/culture/weather categories

**Kalshi**
- [API Changelog — docs.kalshi.com](https://docs.kalshi.com/changelog) — historical tier (2026-02-19), `/historical/trades` public (2026-03-06), `series_ticker` filter (2026-04-10), sub-penny price levels (2026-07-09), MVE history deprecated (2026-07-02), tier thresholds halved (2026-06-25), `/historical/positions` (2026-07-23)
- [Historical Data — docs.kalshi.com](https://docs.kalshi.com/getting_started/historical_data) — **"The target window for live data is 3 months"**; older records "must be queried through the corresponding historical endpoint"
- [Kalshi Fee Schedule PDF (July 2026, 7.7.26 Update)](https://kalshi.com/docs/kalshi-fee-schedule.pdf) — **still HTTP 429**; title via search index only
- [Kalshi Fees — sailgp](https://sailgp.com/prediction-markets/kalshi/fees), [pm.wiki](https://pm.wiki/learn/kalshi-fees-explained) — secondary corroboration, no coefficient change

**Regulation**
- [CFTC Staff Issues Prediction Markets Advisory — press release 9193-26, 2026-03-12](https://www.cftc.gov/PressRoom/PressReleases/9193-26)
- [CFTC Staff Letter No. 26-08, 2026-03-12](https://www.cftc.gov/csl/26-08/download)
- [CFTC Proposes New Rules for Event Contracts — Greenberg Traurig, June 2026](https://www.gtlaw.com/en/insights/2026/6/cftc-proposes-new-rules-for-events-contracts-on-prediction-markets) — proposed 2026-06-10, FR 2026-06-12, comments closed 2026-07-27, three-step framework, category effects
- [Prediction Markets; Public Interest Determinations — Federal Register, 2026-06-12](https://www.federalregister.gov/documents/2026/06/12/2026-11854/prediction-markets-public-interest-determinations) — **blocked (302 to unblock.federalregister.gov)**; cited via law-firm summaries
- [CFTC Issues Proposed Rule Regarding Prediction Markets — CRS LSB11441](https://www.congress.gov/crs-product/LSB11441)
- [Rewriting the Rulebook — Ropes & Gray, June 2026](https://www.ropesgray.com/en/insights/alerts/2026/06/rewriting-the-rulebook-cftc-proposes-rule-changes-for-prediction-market-contracts) — **HTTP 403**, title/date only
- [Prediction Markets Face CFTC Advisory Over Blanket Self-Certified Contracts — Bloomberg, 2026-07-24](https://www.bloomberg.com/news/articles/2026-07-24/cftc-warns-prediction-markets-over-blanket-self-certifications) — paywalled; corroborated by [crypto.news](https://crypto.news/cftc-warns-prediction-markets-again-over-template-self-certifications/), [Crypto Times](https://www.cryptotimes.io/2026/07/27/cftc-tells-kalshi-polymarket-to-stop-blanket-filings/), [Mondaq](https://www.mondaq.com/unitedstates/commoditiesderivativesstock-exchanges/1823074/cftc-staff-clarifies-self-certification-rules-for-event-contract-series) — **Staff Advisory 26-22**

**Other venues**
- [DraftKings Launches DKeX — SBC Americas, 2026-06-26](https://sbcamericas.com/2026/06/26/draftkings-predictions-dkex-railbird/)
- [DraftKings Railbird Exchange Files First Sports Contracts — DeFi Rate](https://defirate.com/news/draftkings-railbird-exchange-files-first-sports-prediction-market-contracts/)
- [DraftKings Expands Prediction Markets Catalog in Deal With Crypto.com — 2026-02-06](https://www.globenewswire.com/news-release/2026/02/06/3234063/0/en/DraftKings-Expands-Prediction-Markets-Catalog-in-Deal-With-Crypto-com.html)
- [FanDuel Predicts to Expand via Crypto.com and OG Prediction Markets — 2026-06-09](https://www.fanduel.com/about/news/fanduel-predicts-to-expand-event-contract-offering-through-partnership-with-crypto-com-and-og-prediction-markets)
- [Coinbase rolls out prediction market to U.S. customers — CoinDesk, 2026-01-27](https://www.coindesk.com/markets/2026/01/27/coinbase-rolls-out-prediction-market-to-u-s-customers) — powered by Kalshi
- [IBKR Prediction Markets — home](https://www.interactivebrokers.com/predictionmarkets/en/home.php) — Kalshi + CME + ForecastEx, unchanged
- [ForecastEx Review (July 2026) — tech-insider](https://tech-insider.org/prediction-markets/platforms/forecastex-review/) — IBKR/Robinhood only, $0 maker claim
- [Robinhood prediction markets event pages](https://robinhood.com/us/en/prediction-markets/) — front-end, no algo API

**Polymarket international / US access**
- [Polymarket seeks CFTC approval to reopen main exchange to U.S. traders — CoinDesk, 2026-04-28](https://www.coindesk.com/policy/2026/04/28/polymarket-seeks-cftc-approval-to-reopen-main-exchange-to-u-s-traders) — requires a Commission vote; four vacant seats
- [CFTC is conducting an investigation into Polymarket — CNBC, 2026-06-26](https://www.cnbc.com/2026/06/26/cftc-is-conducting-an-investigation-into-polymarket-source-says)
- [Is Polymarket Legal in the U.S. and Europe? July 2026 — CryptoNews](https://cryptonews.com/cryptocurrency/is-polymarket-legal/) — geoblock still in force

**Date verification**
- [Stock market next week: Outlook for July 27–31, 2026 — CNBC](https://www.cnbc.com/2026/07/24/stock-market-next-week-outlook-for-july-27-31-2026.html)
- [Robinhood event contracts dated July 28, 2026](https://robinhood.com/us/en/prediction-markets/crypto/events/btc-price-on-jul-28-2026-at-1am-edt-jul-28-2026/)
- DeFi Rate volume tracker, "current as of July 27, 2026 at 1:59 AM PDT"

**In-repo, read this session:** `docs/research/2026-07-17-polymarket-edge-landscape.md`,
`docs/research/2026-07-25-kalshi-category-expansion.md`,
`docs/architecture/decisions/0015-kalshi-fee-schedule-verified-maker-path.md`,
`docs/architecture/decisions/0016-wp0-history-ceiling-is-a-venue-property.md`,
`docs/architecture/decisions/0018-authenticated-access-confirms-the-history-ceiling.md`,
`src/ingest_kalshi.py`, `scripts/wp0_history_probe.py`.

> **Evidence caveat.** Three claims carry the weight of this document and they
> are of different quality. (a) **Kalshi's live/historical partition and the
> "3 months" live window** are **Confirmed** from Kalshi's own documentation
> fetched this session, and the fact that this repo's probes never queried the
> historical tier is **Confirmed** by reading the code — but the *inference* that
> the archive contains the missing data is **Likely (unverified)** and I had no
> execution environment to settle it. (b) **Polymarket US's non-sports launch**
> is **Likely (unverified)**: four independent secondary sources plus the venue's
> own homepage against one stale primary doc page. Five minutes with an account
> closes it. (c) **The fee arithmetic in Part 1** is **Confirmed** — both
> schedules were fetched or carried from a primary-verified ADR, and every
> derived figure was recomputed via `fee/notional = Θ(1−p)` as a second route.
> No figure here should move capital on its own, and nothing here reopens a
> strategy closed by an ADR — that is a separate decision the ADRs own.
