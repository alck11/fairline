# Cross-venue sameness is a link, not an entity

When the same real-world question is listed on both venues, fairline models it as
**two markets joined by a pairwise `market_link`** — not as one canonical "event"
entity that both markets reference. There is deliberately no events table and no
global identity for a real-world question.

This is surprising: the obvious data model gives the shared event its own row and
points both markets at it. We rejected that because it demands a global
identity-resolution authority — something that decides "these N listings across
both venues are all the same event" and names it canonically. That is a strictly
harder problem than the one the matcher actually solves, which is **pairwise**:
"do outcome A and outcome B settle identically?" (see ADR-0002). Keeping sameness
as a link lets the matcher stay local, incremental, and confidence-scored — a new
listing is compared to existing ones one pair at a time, with no canonical
registry to keep consistent.

## Consequences

- The same event can be linked redundantly (A–B and A–C and B–C); that is
  acceptable and cheaper than maintaining canonical identity.
- Anyone tempted to "normalize" `market_link` into an `event` entity should read
  this first: the pairwise model is deliberate, not an oversight.
- If a future need for canonical events arises (e.g. cross-event analytics), it
  can be added *on top of* links without removing them — links stay the source of
  truth for arb assembly.
