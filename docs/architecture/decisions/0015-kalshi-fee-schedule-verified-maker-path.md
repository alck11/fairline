# ADR-0015 — Kalshi fee schedule verified against the primary source; maker path added, cent-rounding corrected

- **Status:** Accepted
- **Date:** 2026-07-26
- **Supersedes:** nothing. **Corrects** two beliefs recorded in
  [docs/research/2026-07-17-polymarket-edge-landscape.md](../../research/2026-07-17-polymarket-edge-landscape.md)
  and one defect in `src/fees.py`.

## Decision

`src/fees.py` now prices Kalshi maker fills at the **0.0175** coefficient
(25% of taker) on maker-fee-enabled series and at **zero** elsewhere, and its
ceil-to-the-cent rounds at the cent scale rather than the dollar scale. Both
changes are pinned by `tests/test_fees.py`, which reproduces **all 84 cells** of
the two fee tables Kalshi publishes.

## Why now

[docs/research/2026-07-25-kalshi-category-expansion.md](../../research/2026-07-25-kalshi-category-expansion.md)
Part 2 flagged that `kalshi_fee()` had no maker path, and could not verify the
formulas because the primary PDF returned HTTP 429 on two attempts. Every
candidate in that document's shortlist is fee-sensitive — FLB-1's entire gate is
"net ROI ≥ +1.5% after fees" — so the fee formula is load-bearing for a capital
decision and could not stay on secondary sources.

## The primary source, and how it was obtained

`kalshi.com/docs/kalshi-fee-schedule.pdf` answers non-browser clients with HTTP
429 (reproduced 2026-07-26 via both WebFetch and curl with a browser
user-agent), and **every Wayback capture after 2026-04 archived that 429 rather
than the document**. The document itself was retrieved from the Wayback snapshot
of **2026-02-18**, which carries "Last updated and effective: **Feb 5, 2026**".

Quoted verbatim from it:

```
fees = round up(0.07   x C x P x (1-P))     general, taker
fees = round up(0.0175 x C x P x (1-P))     maker
fees = round up(0.035  x C x P x (1-P))     S&P500 and Nasdaq-100
P = the price of a contract in dollars (50 cents is 0.5)
C = the number of contracts being traded
round up = rounds to the next cent
```

Also confirmed from the same document: **no settlement fee**, **no membership
fee**, free ACH deposit and withdrawal, and — see below — **no per-contract fee
cap of any kind**.

**Version caveat, stated plainly.** The current schedule is titled "Fee Schedule
for July 2026 - 7.7.26 Update" (surfaced by search index; the document itself is
unreachable). Secondary sources describing that July update report the same
three coefficients unchanged. So the coefficients are **Confirmed** as of
2026-02-05 primary and **Likely (unverified)** as of the July revision. The one
thing that would falsify this cheaply is a single real fill: Kalshi's own fill
receipt is the ground truth, and one live order settles the version question
outright.

## What was wrong, and what it cost

### 1. `Leg.fee()` silently dropped `maker` on the Kalshi branch

`Leg` has carried a `maker` field since WP-0-era, documented "only meaningful
for polymarket", and `Leg.fee()` called `kalshi_fee()` without forwarding it.
`kalshi_fee()` had no parameter to receive it. So **every Kalshi resting fill
was billed the full taker rate** — a 4x overstatement on maker-fee series, and
an infinite one on the rest of the catalog, where makers pay nothing.

Direction of the error is conservative (it overstates cost, so it cannot have
manufactured edge), which is why nothing downstream broke. It matters now
because the one study still standing after WP-0 (ADR-0016) is a *maker* strategy
in its realistic implementation: the only paper separating the two sides finds
Kalshi makers do ~22 points better than takers, so a maker-side backtest priced
at the taker rate would understate the strategy by exactly the margin that
decides it.

### 2. Maker fees are not universal, and modelling them as universal is also wrong

The schedule is explicit that trading fees "are not charged for orders placed
that are not immediately matched and are instead left as resting orders on the
orderbook **unless they are included in our 'Maker Fees' section**", pointing at
`kalshi.com/fee-schedule` for the current list of which markets those are.
Secondary sources describe that list as a small minority of the catalog.

So "makers pay 25%" (the 2026-07-25 research doc) and "makers are ~free" (the
2026-07-17 landscape doc) are each right about a different subset. `kalshi_fee`
takes `maker_fee_enabled` to carry that per-market fact. **It defaults to True —
charge the fee.** The default must never invent edge that isn't there; a caller
who has checked the series list passes False and gets the true number.

### 3. `_ceil_cents` overcharged by a cent on exact boundaries

Found by checking our arithmetic against the published table rather than
re-deriving our own formula — the table disagreed.

`math.ceil(round(x, 10) * 100) / 100` tidies the value in *dollars*, then
multiplies by 100. The tidied dollar value is still not exactly representable,
so the product lands just above the integer and ceils up. For 100 contracts at
$0.20, `0.07 * 100 * 0.20 * 0.80` is `1.1200000000000003`; the old form billed
**$1.13**; Kalshi's table says **$1.12**.

Rounding at the cent scale — `math.ceil(round(x * 100, 9)) / 100` — fixes it.
Affected 8 of 891 `(contracts, price)` grid cells over
`C ∈ {1,10,25,50,100,200,421,500,1000}`, every one of them an exact cent
boundary. Small, but it is a disagreement with the venue's own published number,
and `tests/test_fees.py` now makes it impossible to reintroduce silently.

### 4. The "$0.035 per-contract cap" does not exist

The 2026-07-17 landscape doc records a `$0.035/contract` cap. **There is no cap
anywhere in the primary schedule.** The figure is the S&P500 / NASDAQ-100
*coefficient* garbled into a cap. The 2026-07-25 research doc reached the same
conclusion by algebra (under a 0.07 coefficient the maximum possible fee is
`0.07 × 0.25 = $0.0175`, so a $0.035 cap could never bind) and left it as an
open question; the primary document closes it. **Open question 3 of that
document is resolved: stale, and wrong.**

This also pins down what `index_market=True` means, which was previously
untethered: "all iterations of the S&P500 and Nasdaq-100 markets", i.e. Rulebook
tickers beginning `INX` (INXD/INXW/INXM/INXY/INXU/…) or `NASDAQ100`
(NASDAQ100D/W/M/Y/U/…).

## Consequences

- `kalshi_fee(contracts, price, *, maker=False, index_market=False,
  maker_fee_enabled=True)`. Purely additive: every existing call site
  (`backtest.py`, `ev_detector.py`, `tests/test_backtest.py`) passes neither new
  keyword and its behaviour is unchanged apart from the boundary-rounding fix.
- `Leg` gains `maker_fee_enabled` and now forwards `maker` on the Kalshi branch.
  `Leg.maker` is no longer Polymarket-only; its comment said otherwise and lied.
- `tests/test_fees.py` (11 tests, no DB, no network) pins both published tables
  cell by cell, the boundary case, the maker ratio, the free-maker path, and the
  `Leg` forwarding regression specifically.

## Open questions

1. **Does the July 2026 revision change any coefficient?** Unresolvable from
   here — the document 429s and the archive only has 429s after April.
   Settled definitively by one real fill receipt.
2. **Which series are maker-fee-enabled?** `kalshi.com/fee-schedule` carries the
   list and also 429s. Until it is read, `maker_fee_enabled=True` (conservative)
   is the right default and callers should not override it on a guess.
3. **What does an S&P500/NASDAQ-100 *maker* pay?** The schedule states the maker
   formula once, at 0.0175, and gives the index markets no maker table. We
   charge 0.0175 — both the literal reading and the conservative one, so the
   ambiguity cannot cost edge. Irrelevant unless the project ever trades INX or
   NASDAQ100, which nothing currently proposes.
