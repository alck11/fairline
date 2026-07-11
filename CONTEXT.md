# Fairline

A research stack for finding fee-aware, risk-gated edge in prediction markets.
Two co-equal, independent strategies — structural/cross-venue **arbitrage** and
**copy-trading** of scored wallets — share one storage layer, one market
matcher, and one risk/execution engine, plus one **experimental** third
strategy (**directional** EV betting) that must earn co-equal status on paper.
Everything runs on paper until an edge is proven; live order placement is
stubbed and gated.

## Language

### Markets

**Venue**:
A trading platform. Exactly two exist: `polymarket` and `kalshi`.
_Avoid_: exchange, platform, book (a "book" is the orderbook, not the venue).

**Market**:
One tradable event on **one venue**. The same real-world question listed on both
venues is **two markets**, joined by a `market_link` — there is no shared,
venue-independent "event" entity. A market holds one or more `outcome`s.
_Avoid_: event, contract (Kalshi's word for an outcome).

**Outcome**:
One tradable leg of a market — `YES`/`NO`, or a single candidate in a
multi-candidate market. Prices, orderbooks, and links all attach here, not to
the market ("one row per outcome"). One outcome resolves to $1, the rest to $0.
_Avoid_: leg (a `leg` is a position you take, not the thing you take it on),
contract, share.

**Side**:
The outcome a position buys. **Every position in fairline is a buy** — there
are no sells or shorts; selling YES in a binary market is normalized to buying
NO. Because everything is a buy, side is just the outcome reference, with no
buy/sell prefix.
_Avoid_: buy_yes/buy_no (redundant prefix), direction, long/short.

**Market link**:
An assertion that two `outcome`s (on different venues) resolve on the same
real-world event, with a `polarity` (+1 same, −1 inverted: a == NOT b) and a
`confidence`. It is a *relationship*, not an entity. Only the LLM or a human
may write one — never the embedding tier alone.
_Avoid_: mapping, equivalence, pair.
_Note_: the table is named `market_link` but it connects **outcomes** — a known
naming wart; read it as "outcome link."

### Matching

**Match**:
The judgment that two outcomes on different venues settle identically — made by
reading **both resolution rule-sets**, never titles alone. A wrong match is not
a missed trade; it is a guaranteed loss.
_Avoid_: mapping, dedupe.

**Triage**:
The embedding tier's only job: route a candidate pair by cosine similarity —
low → discard, otherwise → escalate. Triage can never write a link, because
embeddings cannot reliably distinguish negation or three-way outcomes
("cut" vs "hold" vs "raise").
_Avoid_: auto-link (retired — the embedding tier no longer links).

**Escalate**:
Send a candidate pair to the LLM to read both resolution rule-sets and return
same/polarity/confidence. The only automated path that writes a link.
_Avoid_: confirm (that is the human act), review.

**Verified**:
A human has confirmed the link by reading both rule-sets. **Live cross-venue
execution requires a verified link**; paper may trade unverified links (that is
how the review queue gets built without risk).
_Avoid_: confirmed, approved, trusted.

### Arbitrage

**Arbitrage**:
Buying a **complete set** of mutually-exclusive, collectively-exhaustive
outcomes for a total of less than $1, locking guaranteed profit regardless of
how the event resolves. Exactly two kinds exist, split by *where settlement is
guaranteed*:
_Avoid_: spread, mispricing (too vague).

**Complete set (arb)**:
An arbitrage assembled **within one venue** — every outcome of a single market
bought for less than $1. Riskless once fully filled, because the venue itself
guarantees exactly one outcome pays $1. Subsumes both binary (YES+NO) and
N-outcome cases; there is no separate "bundle" vs "multi" distinction.
_Avoid_: bundle, multi, dutch (former code names, now retired).

**Cross-venue (arb)**:
An arbitrage assembled **across two venues** via a `market_link` — e.g. buy YES
on Polymarket, NO on Kalshi. The only kind that carries **match risk**: a wrong
`market_link` turns it from riskless into a guaranteed loss. This is why the
matcher exists.
_Avoid_: cross-market, inter-venue.

**Leg**:
One position taken as part of an arbitrage — a (venue, side, size, price) tuple.
A complete set / opportunity is "all legs or none."
_Avoid_: order, fill (those are what happens *to* a leg), side.

**Opportunity**:
A detected, depth-sized, fee-aware arbitrage ready to act on — the profit-
*maximizing* size after slippage, not merely a positive top-of-book spread.
Persisted to `arb_opportunity`; acting on it produces an `execution`.
_Avoid_: signal, trade, edge (edge is the *number*, not the opportunity).

### Money

**Notional**:
The capital paid to enter a position: Σ price × size across its legs.
**Deliberately defined as cost-to-enter, not payout face value** — on a long
position cost is the max loss, which is what the risk caps care about.
_Avoid_: stake, deployed (retired synonyms), cost, capital.

**Payout**:
What a winning position returns: $1 × size. The denominator of `edge`.
_Avoid_: face value, settlement.

**Exposure**:
The sum of notional across currently **open** positions — capital at risk right
now. Bounded by `max_open_exposure`; released when a position resolves.
_Avoid_: position (a position is one holding; exposure is the aggregate).

**Edge**:
Profit **per $1 of payout** (denominator: size). `gross_edge` is pre-fee
(1 − Σ prices); `net_edge` is post-fee. Answers "how mispriced is this?"
_Avoid_: spread, margin.

**ROI**:
Profit **per $1 of notional** (denominator: capital paid). Answers "what return
on my money?" Never interchangeable with edge — different denominators.
_Avoid_: return, yield.

**PnL**:
Absolute dollars of profit or loss after fees, realized at resolution:
size × (resolved_value − entry_price) − fees. "Realized" always means
hold-to-resolution here — early exits are deliberately ignored, so scoring
rewards *selection* skill, not exit timing (the copier holds to resolution too).
_Avoid_: profit (alone), earnings.

### Copy-trading

**Wallet**:
An on-chain address whose resolved trades are observed and scored as a
candidate to copy. The unit of the copy-trade strategy.
_Avoid_: trader, user, account.

**Score**:
The transparent 0–100 composite: each feature percentile-ranked
cross-sectionally per `as_of`, then weighted. Point-in-time (uses only trades
resolved strictly before `as_of`) and persisted to `wallet_score`. **The only
thing called a score.** Ranks wallets today.
_Avoid_: rating, rank (rank is the mechanism, score is the result).

**Forecast**:
The model's predicted forward 30-day ROI for a wallet — a regression output,
**not a score**. Earns the right to replace the Score's ranking only by beating
it on out-of-time rank correlation. Predicts what a wallet does next.
_Avoid_: score, prediction (alone), model output.

**Basket**:
The top-k wallets **specialized in one category** whose Score clears a floor —
"the politics basket," "the crypto basket." Never a single wallet: copy signals
are taken from baskets, not heroes. There is one basket per category, not one
global basket.
_Avoid_: portfolio, watchlist, cohort.

**Consensus**:
The fraction of **participating** basket members agreeing on the same outcome
of the same market — participants are those who traded that market; silent
wallets are neutral, not dissenting. Only defined once participation clears a
minimum floor (guarding against one wallet reading as 100% consensus). A copy
trade fires only when consensus ≥ the gate, within the category-relevant basket.
_Avoid_: agreement (alone), quorum, majority.

**Participation**:
The number of basket members who traded a given market within the signal
window. The denominator of consensus; below the floor, no copy signal exists.
_Avoid_: turnout, activity.

### Directional (experimental)

**Directional**:
Backing **one side** of a market because your own model's probability disagrees
with the price. Not riskless (unlike arbitrage) and not derived from wallets
(unlike copy-trading) — a third, experimental strategy that is paper-only and
only as good as the injected model.
_Avoid_: EV strategy (EV is the number), speculation, punting.

**Model probability**:
The injected model's probability that an outcome pays $1 — always written
`p_model` to keep it visually distinct from `price` (the market's implied
probability). The model itself lives outside fairline and is injected.
_Avoid_: p (alone, ambiguous with price), estimate, forecast (that is the
wallet model's output).

**EV**:
Post-fee expected value **per share** of a directional buy:
p_model − price − fee_per_share. Positive EV is a necessary, never sufficient,
condition to bet — sizing and risk gates still apply.
_Avoid_: edge (arb-specific: guaranteed, per $1 payout — EV is probabilistic).

**Signal (directional)**:
A sized, fee-aware, Kelly-capped directional bet suggestion. **Not an
Opportunity** — that word is reserved for arbitrage — and never written to
`arb_opportunity`. Executed (paper) through the same Engine gates as
everything else.
_Avoid_: opportunity, tip, trade idea.

### Execution & risk

**Mode**:
Whether the engine simulates fills (`paper`) or places real orders (`live`).
A property of the engine, not of a trade. Paper assumes full fills and risks
nothing; the entire stack must prove its edge on paper before live exists.
_Avoid_: environment, dry-run, backtest (a backtest replays history; paper mode
runs forward in real time).

**Execution**:
The act of taking a detected opportunity or copy signal to the venue(s) —
recorded whether it fills, rejects, or aborts. The audit trail of intent.
_Avoid_: trade (ambiguous), order (one execution may place several).

**Rejected**:
An execution refused by a risk gate **before any order was placed**. Free —
nothing to unwind.
_Avoid_: failed, blocked.

**Aborted**:
An execution whose orders were placed but only partially filled, and whose
filled legs were then unwound. Costs fees and slippage on the way out. An arb
with one leg is not an arb — it is a naked directional bet.
_Avoid_: cancelled, failed.

**Partial**:
A terminal status valid **only for copy executions**: the order filled less
than its intended size and the position stands at the reduced size. Arbs can
never be partial — a partially-filled arb is `aborted` (all legs or none).
_Avoid_: partial fill as an arb status.

**Unwind**:
Submitting offsetting orders to exit the filled legs of a partial arb, rather
than carrying naked directional risk.
_Avoid_: hedge, close out, reverse.

**Kill switch**:
Trips when the daily loss limit is reached; halts all new entries. **In live
mode it latches — a human must re-arm it.** In paper mode it auto-resets at the
UTC day roll (unattended replays need this). A kill switch that un-kills itself
is a daily loss budget, not a kill switch.
_Avoid_: circuit breaker, daily loss budget (that is the limit, not the switch).
