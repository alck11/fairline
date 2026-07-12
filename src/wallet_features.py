"""
wallet_features.py — turn raw resolved trades into copyability features.

Input: a DataFrame of RESOLVED wallet_trade rows with columns:
    wallet, category, size, entry_price, entry_ts, resolve_ts,
    resolved_value (1/0 for the outcome held), fee_paid

Output: one feature row per (wallet, as_of) computed with NO future leakage —
only trades resolved strictly before `as_of` are used.

Realized PnL model (hold-to-resolution):
    pnl = size * (resolved_value - entry_price) - fee_paid
    roi_trade = pnl / (size * entry_price)
(For early exits you'd swap resolved_value for exit price; resolved trades only
here, which is what you want for scoring.)
"""
from __future__ import annotations
import numpy as np
import pandas as pd

REQUIRED = ["wallet", "category", "size", "entry_price", "entry_ts",
            "resolve_ts", "resolved_value", "fee_paid"]


def _prep(trades: pd.DataFrame) -> pd.DataFrame:
    df = trades.copy()
    missing = set(REQUIRED) - set(df.columns)
    if missing:
        raise ValueError(f"missing columns: {missing}")
    df["entry_ts"] = pd.to_datetime(df["entry_ts"], utc=True)
    df["resolve_ts"] = pd.to_datetime(df["resolve_ts"], utc=True)
    df["pnl"] = df["size"] * (df["resolved_value"] - df["entry_price"]) - df["fee_paid"]
    df["stake"] = df["size"] * df["entry_price"]
    df["roi"] = np.where(df["stake"] > 0, df["pnl"] / df["stake"], 0.0)
    df["hold_h"] = (df["resolve_ts"] - df["entry_ts"]).dt.total_seconds() / 3600.0
    return df


def _max_drawdown(pnl_series: pd.Series) -> float:
    """Max peak-to-trough drop of cumulative realized PnL (absolute USDC)."""
    cum = pnl_series.cumsum()
    peak = cum.cummax()
    return float((cum - peak).min()) if len(cum) else 0.0


def _longest_loss_streak(win_flags: pd.Series) -> int:
    streak = best = 0
    for w in win_flags:
        streak = 0 if w else streak + 1
        best = max(best, streak)
    return best


def _hhi(category_counts: pd.Series) -> float:
    """Herfindahl concentration of trade categories, 0 (diverse)..1 (one cat)."""
    p = category_counts / category_counts.sum()
    return float((p ** 2).sum())


def _dominant_category(hist: pd.DataFrame) -> tuple[str, float, int]:
    """The category with the most resolved trades in `hist`, deterministically
    tie-broken (highest total stake, then lexical) so the panel is
    reproducible run-to-run. Returns (category, share, n)."""
    counts = hist["category"].value_counts()
    top_n = int(counts.max())
    candidates = sorted(counts[counts == top_n].index)
    if len(candidates) > 1:
        stakes = hist[hist["category"].isin(candidates)].groupby("category")["stake"].sum()
        top_stake = stakes.max()
        candidates = sorted(stakes[stakes == top_stake].index)
    category = candidates[0]
    return category, float(top_n / len(hist)), top_n


def features_for_wallet(df: pd.DataFrame, as_of: pd.Timestamp) -> dict | None:
    """Compute one feature dict from a single wallet's prepped trades,
    using only trades resolved before `as_of`. Returns None if too sparse."""
    hist = df[df["resolve_ts"] < as_of].sort_values("resolve_ts")
    if len(hist) < 5:                       # need a real sample, not noise
        return None

    pnl = hist["pnl"]
    wins = hist["pnl"] > 0
    roi = hist["roi"]
    sharpe = float(roi.mean() / roi.std(ddof=1)) if roi.std(ddof=1) > 0 else 0.0

    def _recent(days: int) -> float:
        cut = as_of - pd.Timedelta(days=days)
        return float(hist.loc[hist["resolve_ts"] >= cut, "pnl"].sum())

    dom_category, dom_share, dom_n = _dominant_category(hist)

    return {
        "as_of": as_of,
        "wallet": hist["wallet"].iloc[0],
        "n_resolved": int(len(hist)),
        "win_rate": float(wins.mean()),
        "realized_pnl": float(pnl.sum()),
        "roi": float(pnl.sum() / hist["stake"].sum()),
        "sharpe": sharpe,                                    # per-trade, unannualized
        "max_drawdown": _max_drawdown(pnl),
        "avg_hold_hours": float(hist["hold_h"].mean()),
        "hhi_category": _hhi(hist["category"].value_counts()),
        "pnl_7d": _recent(7),
        "pnl_30d": _recent(30),
        "pnl_90d": _recent(90),
        "longest_loss_streak": _longest_loss_streak(wins.tolist()),
        # Selection metadata for baskets (ADR-0007) — NOT model features:
        # dominant_category is a string and would break the regressor.
        "dominant_category": dom_category,
        "dominant_category_share": dom_share,
        "dominant_category_n": dom_n,
    }


def build_feature_panel(trades: pd.DataFrame,
                        as_of_dates: list[pd.Timestamp]) -> pd.DataFrame:
    """Point-in-time feature panel across all wallets x as_of grid.

    IMPORTANT for avoiding survivorship bias: pass the FULL wallet universe
    that was active before each as_of, including wallets that later went
    silent. If you only feed currently-active wallets you will systematically
    overstate skill."""
    df = _prep(trades)
    rows = []
    for as_of in as_of_dates:
        for _, wdf in df.groupby("wallet"):
            f = features_for_wallet(wdf, as_of)
            if f:
                rows.append(f)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# transparent composite score (ship this before any ML)
# ---------------------------------------------------------------------------
# Percentile-rank each feature cross-sectionally per as_of, then weight.
# Robust to outliers and unit differences; higher = more copyable.
WEIGHTS = {
    "roi":              0.25,
    "sharpe":           0.25,
    "win_rate":         0.15,
    "pnl_30d":          0.15,   # recency: weight recent over all-time
    "n_resolved":       0.10,   # sample size / track record
    "max_drawdown":     0.10,   # higher (less negative) is better -> rank asc
}


def composite_score(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel.copy()
    out["score"] = 0.0
    for as_of, grp in out.groupby("as_of"):
        idx = grp.index
        s = pd.Series(0.0, index=idx)
        for col, w in WEIGHTS.items():
            # max_drawdown is negative; rank ascending so smaller drop scores higher
            r = grp[col].rank(pct=True)
            s += w * r
        out.loc[idx, "score"] = (s * 100).round(2)
    return out


if __name__ == "__main__":
    rng = np.random.default_rng(7)
    n = 600
    categories = ["politics", "sports", "crypto"]
    wallets = [f"0x{i:02x}" for i in range(40)]
    # Give each wallet a "home" category it trades most of the time, with some
    # cross-category noise mixed in — uniformly-random categories per trade
    # would make almost every wallet diversified and every basket empty
    # (ADR-0007 / plan.md WP-3 demo note).
    home_category = {w: categories[i % len(categories)] for i, w in enumerate(wallets)}
    wallet_col = rng.choice(wallets, n)
    home_col = np.array([home_category[w] for w in wallet_col])
    is_noise = rng.random(n) < 0.2
    category_col = np.where(is_noise, rng.choice(categories, n), home_col)

    demo = pd.DataFrame({
        "wallet": wallet_col,
        "category": category_col,
        "size": rng.integers(10, 500, n).astype(float),
        "entry_price": rng.uniform(0.2, 0.8, n).round(2),
        "entry_ts": pd.Timestamp("2026-01-01", tz="UTC") + pd.to_timedelta(rng.integers(0, 120, n), "D"),
        "resolved_value": rng.integers(0, 2, n).astype(float),
        "fee_paid": rng.uniform(0, 2, n).round(2),
    })
    demo["resolve_ts"] = demo["entry_ts"] + pd.to_timedelta(rng.integers(1, 240, n), "h")
    panel = build_feature_panel(demo, [pd.Timestamp("2026-05-01", tz="UTC")])
    scored = composite_score(panel).sort_values("score", ascending=False)
    print(scored[["wallet", "n_resolved", "win_rate", "roi", "sharpe", "score",
                  "dominant_category", "dominant_category_share", "dominant_category_n"]]
          .head(8).to_string(index=False))
