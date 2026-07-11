# Wallet scoring is leakage-safe and survivorship-safe by construction

Wallet copyability is scored under three disciplines that are non-negotiable,
because violating any of them silently corrupts every research conclusion
downstream — and each looks like a harmless "simplification" to someone who
doesn't know why it's there:

- **Point-in-time features, no leakage.** A feature row at time `t` uses only
  trades resolved strictly before `t`; the forward label uses only trades
  *entered* after `t`. Features and labels never share a trade.
- **Purged time-series CV, never random k-fold.** Splits are expanding-window
  and time-ordered with an embargo gap, so a label's forward horizon can never
  overlap the training window. Random k-fold would leak the future into the past
  and manufacture a phantom edge.
- **Survivorship-safe universe.** The full historical wallet universe is scored,
  including wallets that later went silent. A silent wallet gets forward-label
  `0` (you'd have copied nothing, made nothing) — it is **not dropped**. Feeding
  only currently-active wallets systematically overstates everyone's skill.

## Consequences

The transparent percentile composite `score` is the baseline; the XGBoost
`forecast` is adopted only if it beats that baseline on **out-of-time rank
correlation** (Spearman) — ordering wallets is the goal, not predicting exact
ROI. Non-stationarity is severe; expect decay and retrain on a rolling window.
