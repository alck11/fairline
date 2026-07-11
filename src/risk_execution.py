"""
risk_execution.py — risk controls + a PAPER-TRADE execution engine.

Deliberately ships with NO live order placement. `place_live` raises until you
implement it, and even then it is gated behind every risk check below. Build
your whole stack on paper first: ingestion, detection, scoring and this engine
can run end-to-end and prove an edge exists before a cent is at risk.

Risk model
  * per-trade notional cap and per-wallet allocation cap
  * global max open exposure
  * daily loss limit -> trips the kill switch (no new entries)
  * basket-consensus gate for copy trades (>=80% agreement)
  * partial-fill handling: an arb that fills only ONE leg is NOT an arb;
    abort and unwind rather than carry naked directional risk.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class RiskLimits:
    max_trade_notional: float = 500.0
    max_wallet_alloc: float = 1_000.0
    max_open_exposure: float = 5_000.0
    daily_loss_limit: float = 300.0
    basket_consensus: float = 0.80


@dataclass
class RiskState:
    open_exposure: float = 0.0
    realized_today: float = 0.0
    wallet_alloc: dict[str, float] = field(default_factory=dict)
    kill: bool = False
    _day: str = field(default_factory=lambda: datetime.now(timezone.utc).date().isoformat())

    def _roll_day(self):
        today = datetime.now(timezone.utc).date().isoformat()
        if today != self._day:
            self._day, self.realized_today, self.kill = today, 0.0, False


class Engine:
    def __init__(self, limits: RiskLimits | None = None, mode: str = "paper"):
        self.limits = limits or RiskLimits()
        self.mode = mode
        self.state = RiskState()
        self.blotter: list[dict] = []

    # -- gating ------------------------------------------------------------
    def _check(self, notional: float, wallet: str | None) -> tuple[bool, str]:
        self.state._roll_day()
        L, S = self.limits, self.state
        if S.kill:
            return False, "kill switch active (daily loss limit hit)"
        if notional > L.max_trade_notional:
            return False, f"trade notional {notional:.0f} > cap {L.max_trade_notional:.0f}"
        if S.open_exposure + notional > L.max_open_exposure:
            return False, "would exceed max open exposure"
        if wallet is not None:
            used = S.wallet_alloc.get(wallet, 0.0)
            if used + notional > L.max_wallet_alloc:
                return False, f"wallet {wallet} alloc cap reached"
        return True, "ok"

    # -- arb execution -----------------------------------------------------
    def execute_arb(self, opp) -> dict:
        """Atomically take BOTH legs of an Opportunity, or neither."""
        notional = sum(l["price"] * l["size"] for l in opp.legs)
        ok, why = self._check(notional, wallet=None)
        if not ok:
            return self._record("rejected", opp.legs, 0.0, why)

        fills = [self._fill(l) for l in opp.legs]
        if not all(f["filled"] >= f["size"] for f in fills):
            # partial fill -> unwind the legs that did fill; never go naked
            self._unwind(fills)
            return self._record("aborted", fills, 0.0, "partial fill; unwound")

        self.state.open_exposure += notional
        return self._record("filled", fills, opp.net_profit, "paper arb filled")

    # -- copy execution ----------------------------------------------------
    def execute_copy(self, wallet: str, leg: dict, basket_agreement: float) -> dict:
        if basket_agreement < self.limits.basket_consensus:
            return self._record("rejected", [leg], 0.0,
                                 f"consensus {basket_agreement:.0%} < "
                                 f"{self.limits.basket_consensus:.0%}")
        notional = leg["price"] * leg["size"]
        ok, why = self._check(notional, wallet=wallet)
        if not ok:
            return self._record("rejected", [leg], 0.0, why)
        f = self._fill(leg)
        self.state.open_exposure += notional
        self.state.wallet_alloc[wallet] = self.state.wallet_alloc.get(wallet, 0.0) + notional
        return self._record("filled", [f], 0.0, f"copy of {wallet}")

    def settle(self, pnl: float):
        """Call when a position resolves; trips kill switch past the loss limit."""
        self.state._roll_day()
        self.state.realized_today += pnl
        if self.state.realized_today <= -self.limits.daily_loss_limit:
            self.state.kill = True

    # -- internals ---------------------------------------------------------
    def _fill(self, leg: dict) -> dict:
        if self.mode == "live":
            return self.place_live(leg)            # raises until implemented
        return {**leg, "filled": leg["size"]}      # paper: assume full fill

    def _unwind(self, fills: list[dict]):
        # paper: just drop them; live: submit offsetting orders for filled legs
        pass

    def place_live(self, leg: dict) -> dict:
        raise NotImplementedError(
            "Live placement intentionally unimplemented. Wire py-clob-client / "
            "Kalshi REST here ONLY after paper results justify it, keep custody, "
            "use a scoped revocable signature, and handle nonce/idempotency.")

    def _record(self, status: str, legs, pnl: float, notes: str) -> dict:
        row = {"ts": datetime.now(timezone.utc).isoformat(), "mode": self.mode,
               "status": status, "legs": legs, "realized_pnl": pnl, "notes": notes}
        self.blotter.append(row)
        return row


if __name__ == "__main__":
    from detector import cross_venue_edge
    eng = Engine(RiskLimits(max_trade_notional=200))

    opp = cross_venue_edge(100, yes_venue="polymarket", yes_price=0.42,
                           yes_cat="politics", no_venue="kalshi",
                           no_price=0.53, no_cat="politics")
    print("arb  :", eng.execute_arb(opp)["status"], "->",
          eng.execute_arb(opp)["notes"])              # rejected: notional 95 ok? 95<200 -> filled
    print("copy :", eng.execute_copy("0xabc",
          {"venue": "polymarket", "side": "yes", "price": 0.30, "size": 100},
          basket_agreement=0.9)["status"])
    eng.settle(-350.0)
    print("after big loss, kill switch:", eng.state.kill)
