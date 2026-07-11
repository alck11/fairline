"""
market_matcher.py — decide when two markets are the SAME real-world event.

This is the highest-leverage correctness problem in cross-venue arb: a wrong
match isn't a missed trade, it's a guaranteed loss when the venues resolve
differently. So the design is cheap-local-first, escalate-the-ambiguous:

    1. embed both questions locally (Ollama) -> cosine similarity
    2. high sim  -> auto-link (confidence from similarity)
       low  sim  -> discard
       middle    -> escalate to Claude API to read BOTH resolution rule-sets
                    and return {same: bool, polarity: +1/-1, confidence}

Only the routing logic is implemented here; the two model calls are marked
with TODO and isolated behind small functions so you can wire in your own
Ollama endpoint and Anthropic key. Mirrors a local/remote split: trivial
judgments stay local, hard ones go to the strong model.
"""
from __future__ import annotations
from dataclasses import dataclass

AUTO_LINK = 0.92      # >= this cosine -> link without asking the LLM
ESCALATE = 0.70       # [ESCALATE, AUTO_LINK) -> ask Claude ; below -> discard


@dataclass
class MatchResult:
    same: bool
    polarity: int          # +1: a==b ; -1: a == NOT b
    confidence: float
    method: str            # 'embedding' | 'llm'


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
    so you can unit-test the routing with fakes."""
    sim = cosine(embedder(q_a), embedder(q_b))
    if sim >= AUTO_LINK:
        return MatchResult(True, +1, sim, "embedding")
    if sim < ESCALATE:
        return None
    return confirmer(q_a, rules_a, q_b, rules_b)


if __name__ == "__main__":
    # test the ROUTING with deterministic fakes (no model calls needed)
    vectors = {"a": [1, 0, 0], "b": [0.99, 0.14, 0], "c": [0, 1, 0]}
    fake_embed = lambda t: vectors[t]
    fake_confirm = lambda *_: MatchResult(True, +1, 0.81, "llm")

    print("near-identical ->", match("a", "", "b", "",
          embedder=fake_embed, confirmer=fake_confirm))   # auto-link via embedding
    print("orthogonal     ->", match("a", "", "c", "",
          embedder=fake_embed, confirmer=fake_confirm))   # discarded (None)
