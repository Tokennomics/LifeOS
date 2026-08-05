"""Tier 2 — official event APIs, behind one interface.

ROADMAP's condition on this tier, carried into code: **a missing key degrades to the
feed-and-crew list, it never errors.** "Every feature works with no API key and improves
with one" is the oldest rule in this repo, and Tier 2 is the first thing to test it. So a
provider that is not configured reports `not_configured` and contributes nothing, exactly
as if the city had no listings — which is the truth, not a failure.

The second condition is the labelling one: every event a provider produces carries
`origin: "feed"` and a `provider`, so an API listing reads as `· listed` in the digest
alongside a venue's own ICS and stays visibly different from a crew night.

Adding a provider is a `search()` that returns the normalised item shape and a name. It is
not a new architecture — that was the whole point of getting Tier 1's ingest shape right
first.
"""

from modules.feeds.providers import ticketmaster

REGISTRY = {ticketmaster.NAME: ticketmaster}


def get(name: str):
    provider = REGISTRY.get(str(name or "").strip().lower())
    if provider is None:
        raise ValueError(f"unknown provider {name!r} (known: {sorted(REGISTRY)})")
    return provider


def status() -> list[dict]:
    """Which providers exist and which are switched on. Configuration only — never a key."""
    return [{"name": name, "configured": mod.configured(), "env_var": mod.ENV_VAR}
            for name, mod in sorted(REGISTRY.items())]
