> **Status: PARKED, not active (2026-07-17).** This governs the copy-trade/matcher
> subsystem, which is parked out of the Kalshi directional-EV MVP (see
> [`requirements.md`](../../product/requirements.md) → *Parked*). Kept in-repo and
> demo-green; **not enforced against the current plan.** Revive with the copy-trade
> stack only under the requirements doc's revival conditions.

# Embeddings only triage; only the LLM or a human writes a market link

The cross-venue matcher uses local embeddings (Ollama) **only to triage** a
candidate pair — low cosine similarity discards it, otherwise it escalates. The
embedding tier is explicitly **forbidden from writing a link**. Every link that
gets persisted comes from the LLM (Claude) reading *both resolution rule-sets*,
or from a human.

This reverses the obvious design — auto-linking a pair whose titles are nearly
identical (the earlier code auto-linked at cosine ≥ 0.92 with hardcoded
polarity +1). We rejected it because a wrong cross-venue match is not a missed
trade, it is a **guaranteed loss**: the detector will "buy a complete set" that
isn't one. Embedding models are unreliable exactly where it costs the most —
negation and multi-way outcomes. "Will the Fed **cut** in March?" and "Will the
Fed **hold** in March?" embed as near-identical, are *not* complements (a
**raise** loses both legs), and would auto-link with the wrong polarity. Only the
resolution rule-sets — settlement source, timing, edge cases — determine true
equivalence, and only the LLM/human reads them.

The cost is negligible: pairs clearing the escalation band are rare, and one LLM
call is far cheaper than one poisoned arb.

## Consequences

`market_link.method` is `'llm'` or `'manual'` for written links; embedding
similarity is triage input, not evidence. `verified` (human-confirmed) is the
gate between paper and live for cross-venue execution — see ADR-0001.
