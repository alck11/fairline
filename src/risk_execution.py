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
  * basket-consensus gate for copy trades (>=80% agreement among
    *participants*, only valid once participation clears a floor — one
    wallet trading alone is not consensus, however it agrees with itself)
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
    min_participation: int = 3
    max_rearms_per_day: int = 1


@dataclass
class RiskState:
    open_exposure: float = 0.0
    realized_today: float = 0.0
    wallet_alloc: dict[str, float] = field(default_factory=dict)
    kill: bool = False
    rearms_today: int = 0
    _day: str = field(default_factory=lambda: datetime.now(timezone.utc).date().isoformat())

    def _roll_day(self, mode: str = "paper"):
        today = datetime.now(timezone.utc).date().isoformat()
        if today != self._day:
            self._day, self.realized_today, self.rearms_today = today, 0.0, 0
            # Auto-reset of the kill switch is paper-only: unattended historical
            # replays would otherwise starve on the first daily-loss trip. In
            # live mode the switch latches across the day roll -- a human must
            # call Engine.rearm() (see ADR-0001: "a kill switch that un-kills
            # itself is a daily loss budget, not a kill switch").
            if mode == "paper":
                self.kill = False


def consensus_gate(agree_count: int, participant_count: int, basket_size: int,
                    limits: RiskLimits) -> tuple[bool, float, str]:
    """Evaluate basket consensus for a copy trade.

    Consensus is agreement among *participants* (basket members who actually
    traded the market), never diluted by the silent rest of the basket. It is
    only meaningful once participation clears `limits.min_participation` — one
    wallet trading alone is not consensus, however much it agrees with itself.
    Returns (passed, agreement_fraction, reason).

    Raises `ValueError` if the counts are internally inconsistent (negative,
    `agree_count > participant_count`, or `participant_count > basket_size`)
    — those shapes can only come from an upstream counting bug and must not
    be silently gated as if they were a legitimate low-consensus basket.
    """
    if agree_count < 0 or participant_count < 0 or basket_size < 0:
        raise ValueError("agree_count, participant_count and basket_size must be >= 0")
    if participant_count > basket_size:
        raise ValueError(
            f"participant_count {participant_count} exceeds basket_size {basket_size}")
    if agree_count > participant_count:
        raise ValueError(
            f"agree_count {agree_count} exceeds participant_count {participant_count}")
    if participant_count == 0:
        return False, 0.0, f"no participants (0/{basket_size})"
    if participant_count < limits.min_participation:
        return False, 0.0, (
            f"participation {participant_count}/{basket_size} < floor "
            f"{limits.min_participation}")
    agreement = agree_count / participant_count
    if agreement < limits.basket_consensus:
        return False, agreement, (
            f"consensus {agreement:.0%} ({agree_count}/{participant_count} "
            f"participants) < {limits.basket_consensus:.0%}")
    return True, agreement, "ok"


class Engine:
    def __init__(self, limits: RiskLimits | None = None, mode: str = "paper"):
        self.limits = limits or RiskLimits()
        self.mode = mode
        self.state = RiskState()
        self.blotter: list[dict] = []

    # -- gating ------------------------------------------------------------
    def _check(self, notional: float, wallet: str | None) -> tuple[bool, str]:
        self.state._roll_day(self.mode)
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
    def execute_copy(self, wallet: str, leg: dict, agree_count: int,
                      participant_count: int, basket_size: int) -> dict:
        ok, _agreement, why = consensus_gate(agree_count, participant_count,
                                              basket_size, self.limits)
        if not ok:
            return self._record("rejected", [leg], 0.0, why)
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
        self.state._roll_day(self.mode)
        self.state.realized_today += pnl
        if self.state.realized_today <= -self.limits.daily_loss_limit:
            self.state.kill = True

    def rearm(self) -> dict:
        """Explicit human re-arm of the kill switch (the live/manual path).

        Clears `kill` and resets `realized_today` to 0.0, regardless of mode.
        In live mode this is the *only* way to clear a tripped kill switch --
        `_roll_day` deliberately will not do it. Allowed in paper too, for
        consistency and so the state machine is testable without depending on
        mode. A human re-arming is implicitly declaring "start the day's loss
        accounting fresh from here" -- the same semantic `_roll_day` applies
        at the UTC day roll, just manually triggered instead of waiting for
        midnight. Without the `realized_today` reset, the stale deeply-negative
        value that tripped the switch would still be sitting there, so the
        very next `settle()` call -- even one settling a brand-new profit --
        would immediately re-latch `kill`.

        Every call -- successful or blocked -- is logged to the blotter
        (status `"rearm"` / `"rearm_blocked"`) recording the `realized_today`
        value being zeroed (the masked loss) and whether `kill` was actually
        set, per WP-5's follow-up: nothing previously made a rearm's masked
        loss visible after the fact.

        `RiskLimits.max_rearms_per_day` (default 1) caps how many times this
        can succeed per calendar day, resetting at the same day roll that
        resets `realized_today`. Looping `settle(loss)` + `rearm()` would
        otherwise let a human absorb unbounded daily loss past
        `daily_loss_limit` one rearm at a time -- the same "a kill switch
        that un-kills itself is a daily loss budget, not a kill switch"
        problem ADR-0001 raised for the automatic paper-mode reset, just via
        repeated manual calls instead. Once the cap is hit, `rearm()` raises
        `RuntimeError` rather than silently no-op'ing, so a human hitting the
        cap in a real emergency notices immediately instead of assuming the
        switch cleared. Only the kill-switch/daily-loss-counter/rearm-counter
        triple is touched here; exposure, wallet allocation and every other
        risk-state field are left exactly as they were.
        """
        self.state._roll_day(self.mode)
        S, L = self.state, self.limits
        masked_loss, was_tripped = S.realized_today, S.kill
        note = (f"masked loss ${masked_loss:.2f}; kill was "
                f"{'set' if was_tripped else 'NOT set'}")
        if S.rearms_today >= L.max_rearms_per_day:
            row = self._record(
                "rearm_blocked", [], 0.0,
                f"rearm() blocked: {S.rearms_today}/{L.max_rearms_per_day} "
                f"rearm(s) already used today; {note}")
            raise RuntimeError(row["notes"])
        S.rearms_today += 1
        S.kill = False
        S.realized_today = 0.0
        return self._record(
            "rearm", [], 0.0,
            f"rearm() #{S.rearms_today}/{L.max_rearms_per_day} today; {note}")

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

    copy_leg = {"venue": "polymarket", "side": "yes", "price": 0.30, "size": 100}

    # (a) 1-of-1: a single wallet agreeing with itself is 100% "agreement" but
    # is not consensus -- below the participation floor, must reject.
    r = eng.execute_copy("0xabc", copy_leg, agree_count=1, participant_count=1,
                          basket_size=10)
    print("copy a (1-of-1, floor breach)  :", r["status"], "->", r["notes"])

    # (b) 4-of-5: well above the floor and above the consensus gate -> passes.
    r = eng.execute_copy("0xabc", copy_leg, agree_count=4, participant_count=5,
                          basket_size=10)
    print("copy b (4-of-5)                :", r["status"], "->", r["notes"])

    # (c) 3-of-8: only 3 of the 8-member basket traded, but 3 clears the floor
    # and all 3 agree -- consensus is evaluated on participants (3), not
    # diluted by the 5 silent members (which would fail 3/8 < 0.80 under the
    # old whole-basket denominator).
    r = eng.execute_copy("0xabc", copy_leg, agree_count=3, participant_count=3,
                          basket_size=8)
    print("copy c (3-of-8 basket, 3-of-3 participants):", r["status"], "->", r["notes"])

    eng.settle(-350.0)
    print("after big loss, kill switch:", eng.state.kill)

    # -- WP-5: kill switch latches in live mode --------------------------
    # A day roll is simulated by back-dating RiskState._day rather than
    # sleeping past UTC midnight; _roll_day() only reacts to _day changing.

    paper_eng = Engine(RiskLimits(daily_loss_limit=100), mode="paper")
    paper_eng.settle(-150.0)
    print("\npaper: kill after big loss           :", paper_eng.state.kill)
    paper_eng.state._day = "2000-01-01"          # force the next roll to fire
    paper_eng.settle(0.0)                        # any call that rolls the day
    print("paper: kill after day roll (auto-reset):", paper_eng.state.kill)

    live_eng = Engine(RiskLimits(daily_loss_limit=100), mode="live")
    live_eng.settle(-150.0)
    print("\nlive : kill after big loss           :", live_eng.state.kill)
    live_eng.state._day = "2000-01-01"           # force the next roll to fire
    live_eng.settle(0.0)
    print("live : kill after day roll (latched)   :", live_eng.state.kill)
    live_eng.rearm()
    print("live : kill after rearm()              :", live_eng.state.kill)
