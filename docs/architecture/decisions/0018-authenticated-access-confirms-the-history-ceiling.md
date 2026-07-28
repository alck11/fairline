# ADR-0018 — Kalshi RSA-PSS auth added; authenticated access confirms the history ceiling, closing ADR-0017's open threat

- **Status:** **PARTIALLY RETRACTED 2026-07-28 by [ADR-0023](0023-historical-tier-retracts-the-68-day-ceiling.md)** — the auth mechanism (`KalshiCredentials`) is sound and stands; the "ceiling confirmed" conclusion does not
- **Date:** 2026-07-27/28
- **Resolves:** the "threat to ADR-0016" in
  [ADR-0017](0017-flb1-gate-bias-is-real-but-not-in-reachable-markets.md) —
  whether Bürgi-Deng-Whelan's 2021–2025 Kalshi history came from registered API
  access that reaches deeper than the public tier ADR-0016 tested.
- **Adds:** `KalshiCredentials` to `src/ingest_kalshi.py`; `--auth` to
  `scripts/wp0_history_probe.py`.

> **PARTIALLY RETRACTED 2026-07-28 — see [ADR-0023](0023-historical-tier-retracts-the-68-day-ceiling.md).**
> This ADR correctly showed that *authentication* doesn't change live-tier
> depth — that finding stands. It incorrectly concluded from that result that
> the ~68-day ceiling was a fixed venue property with "no remaining
> technical escape hatch." The escape hatch was a different endpoint family
> (`/historical/*`) that this ADR's re-run never queried, because it re-ran
> the same live-tier query shape with auth headers attached rather than
> trying a genuinely different route. `KalshiCredentials` itself (the RSA-PSS
> signing mechanism) is correct and unaffected — only the "ceiling confirmed"
> conclusion below is retracted.

## Decision

**Authenticated access changes nothing. The ~68-day settled-history ceiling is
confirmed as a genuine venue-wide data-retention limit, not an
unauthenticated-tier restriction.** ADR-0016's conclusions (HURSEAS-1 and
DROUGHT-1 dead, MRAIN-1 underpowered, FLB-1 restricted per ADR-0017) stand
without the caveat ADR-0017 raised. The user generated a Kalshi API key
specifically to run this test; both halves of the credential (key ID, RSA
private key) were verified working via a live signed call to
`GET /portfolio/balance` (200, confirming the pairing is genuine) before being
used for anything data-bearing.

## What was built

Kalshi's API is signature-based, not a bearer token: every authenticated
request carries `KALSHI-ACCESS-KEY` / `-TIMESTAMP` / `-SIGNATURE` headers,
where the signature is RSA-PSS (SHA-256, MGF1-SHA256, salt length = digest
size) over `f"{timestamp_ms}{method}{path}"` — confirmed against
`docs.kalshi.com` and validated by the balance call actually succeeding.

`KalshiCredentials` (`src/ingest_kalshi.py`) holds a key ID and an
`rsa.RSAPrivateKey`, loaded via `.from_env()` from `KALSHI_API_KEY_ID` /
`KALSHI_PRIVATE_KEY_PATH` — the same "export from `.env`" convention
`store.py` already uses for `DATABASE_URL`; this module does not auto-source
`.env`. **The private key file never left the local filesystem and its
contents were never read into this conversation** — only its existence,
permissions, PEM header, and `openssl rsa -check` validity were checked before
use, and the key material is referenced by path everywhere in code.
`KalshiSource(credentials=...)` signs every request when set; every endpoint
this project uses is also reachable unauthenticated, so this is purely
additive — `tests/test_ingest_kalshi*.py` (which monkeypatch
`urllib.request.urlopen` and never pass `credentials`) pass unchanged.

**One correctness point worth recording:** the signature must be recomputed on
every retry attempt, inside `_get`'s retry loop, not once before it. Kalshi
checks the timestamp against a freshness window, and a retry after exponential
backoff can land seconds after the first attempt — a signature computed
up-front would go stale and every retry would then fail authentication
instead of retrying the original transient error. Caught and fixed before the
authenticated probe ran, not after.

## The test, and what it found

`scripts/wp0_history_probe.py --auth`, run 2026-07-28 04:02 UTC, identical
Q1/Q2/Q3 to the unauthenticated run in ADR-0016 one day earlier — directly
diffable:

| | unauth (07-27) | auth (07-28) |
|---|---|---|
| KXHIGHNY resolved markets | 414 | 402 |
| KXHIGHNY oldest close | 2026-05-19 | 2026-05-22 |
| KXHIGHNY span | 68 d | 66 d |
| KXNOBELPEACE / KXHURCTOT resolved | **0 / 0** | **0 / 0** |
| KXHIGHLAX listing window | 42.0h (zero variance, n=414) | 42.0h (zero variance, n=402) |

The count and oldest-close drift is exactly what a rolling window looks like a
day later — not evidence of anything. **The two rows that matter are
identical: the long-dated series return zero either way, and the window depth
is the same order of magnitude.** Authentication bought nothing.

Two further checks, deliberately bypassing pagination entirely so the result
cannot be a listing-endpoint artifact:

- **`GET /events/KXHIGHNY-25JUL27`** (a guessed ticker for a KXHIGHNY event
  from roughly a year before this test, looked up directly by ticker, not
  discovered via `/events?...&cursor=...`) returns **200 OK with 0 nested
  markets.** The event exists in Kalshi's system; the market data under it does
  not. This is not a pagination or page-cap artifact — there was no pagination
  involved.
- **`GET /markets?event_ticker=HURCTOT-24DEC01`** (and `HURCTOT-23DEC01`,
  `KXNOBELPEACE-25`) — querying the markets endpoint directly by the exact
  event ticker already known to exist as an empty shell — returns **0
  markets**, matching the nested-events result via an independent code path.

Three independent lookups (paginated listing, direct event lookup, direct
markets-by-event-ticker query), authenticated, agree: **the data genuinely is
not retained**, not merely hidden from one query shape or one auth tier.

## What this resolves, and what it leaves open

**Resolves:** ADR-0017's reading 1 — "they were authenticated; WP-0 was not."
Falsified. Authenticated access to the same public API reaches the same
ceiling.

**Still open, and now the only two readings left:** ADR-0017's readings 2
(Bürgi-Deng-Whelan collected prospectively over 2021–2025 rather than pulling
archival history in one shot — supported by their per-contract lookback being
capped at 10 days before close, which looks like live sampling) and 3
(Kalshi's retention policy changed between their April 2025 cutoff and this
project's July 2026 access). **Neither is actionable for this project.**
Whether the paper's authors had it easier by starting four years ago or by a
retention policy since tightened, this project cannot retroactively acquire
data that is not currently served, by any access tier available to it.

## Consequence

The strategic fork ADR-0016 identified is no longer conditional on an
untested escape hatch. **Forward paper (6–12 months to a verdict) or stop** is
the actual choice, not "forward paper, unless authenticated access changes the
picture" — that clause is now closed. The decile study on already-ingested
weather-ladder data (ADR-0017's recommended next step, to resolve the
Exclusive-Numerical-vs-Climate-and-Weather contradiction) is unaffected by any
of this and remains the cheapest thing left to do before that decision.
