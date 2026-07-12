"""
market_matcher.py — decide when two markets are the SAME real-world event.

This is the highest-leverage correctness problem in cross-venue arb: a wrong
match isn't a missed trade, it's a guaranteed loss when the venues resolve
differently. Embeddings can't reliably distinguish negation or three-way
outcomes ("cut" vs "hold" vs "raise" embed as near-identical but are NOT
complements), so the embedding tier only TRIAGES — it never writes a link.
Only the LLM (reading both resolution rule-sets) or a human may write one.
See ADR-0002.

    1. embed both questions locally (Ollama) -> cosine similarity
       low  sim  -> discard, not a match
       otherwise -> escalate to Claude API to read BOTH resolution rule-sets
                    and return {same: bool, polarity: +1/-1, confidence}

Only the routing logic is implemented here; the two model calls are marked
with TODO and isolated behind small functions so you can wire in your own
Ollama endpoint and Anthropic key. Mirrors a local/remote split: trivial
judgments (discard) stay local, every judgment that could become a link goes
to the strong model.
"""
from __future__ import annotations
from dataclasses import dataclass

ESCALATE = 0.70       # >= this cosine -> ask Claude ; below -> discard


@dataclass
class MatchResult:
    same: bool
    polarity: int          # +1: a==b ; -1: a == NOT b
    confidence: float
    method: str            # 'llm' | 'manual' (embeddings never write a link)


def embed(text: str) -> list[float]:
    """TODO: call your local Ollama embedding model, e.g. nomic-embed-text.
    Returning a stub keeps the module importable for the routing tests."""
    raise NotImplementedError("wire up Ollama embeddings")


def cosine(a: list[float], b: list[float]) -> float:
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-9
    nb = math.sqrt(sum(y * y for y in b)) or 1e-9
    return dot / (na * nb)


def confirm_with_llm(q_a: str, rules_a: str, q_b: str, rules_b: str) -> MatchResult:
    """TODO: call the Anthropic API (claude-...) with both questions AND both
    resolution rule-sets, asking for strict-JSON:
        {"same": bool, "polarity": 1|-1, "confidence": 0..1, "why": str}
    Parse it and map onto MatchResult. The rule-sets — not the titles — are
    what determine true equivalence (settlement source, timing, edge cases)."""
    raise NotImplementedError("wire up Claude confirmation call")


def match(q_a: str, rules_a: str, q_b: str, rules_b: str,
          *, embedder=embed, confirmer=confirm_with_llm) -> MatchResult | None:
    """Route a candidate pair. Returns a MatchResult to persist into
    market_link, or None to discard. `embedder`/`confirmer` are injectable
    so you can unit-test the routing with fakes.

    Triage only: embeddings decide discard-vs-escalate, never same/polarity.
    Any pair that clears the floor is escalated to the LLM (or, eventually,
    a human) to read both resolution rule-sets — that is the only path
    allowed to write a link. See ADR-0002."""
    sim = cosine(embedder(q_a), embedder(q_b))
    if sim < ESCALATE:
        return None
    return confirmer(q_a, rules_a, q_b, rules_b)


if __name__ == "__main__":
    # test the ROUTING with deterministic fakes (no model calls needed)
    vectors = {"a": [1, 0, 0], "b": [0.99, 0.14, 0], "c": [0, 1, 0]}
    fake_embed = lambda t: vectors[t]
    fake_confirm = lambda *_: MatchResult(True, +1, 0.81, "llm")

    print("near-identical ->", match("a", "", "b", "",
          embedder=fake_embed, confirmer=fake_confirm))   # escalated to the LLM fake
    print("orthogonal     ->", match("a", "", "c", "",
          embedder=fake_embed, confirmer=fake_confirm))   # discarded (None)
