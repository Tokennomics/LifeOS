"""What this instance actually is, right now — the three dashboard reads, made true.

Three props, all of the same shape: a screen that told the operator, or the user, that a
system was working.

- `/os/master-controller` reported `master_controller_online: True` and orchestration of
  "50+ subsystems": an "AI Butler v4", "220+ Verified Events Ingested (RA, Luma, Dice)",
  "Stripe + PayPal + Apple Pay 1-Tap Split Ready", "BLE 5.3 Mesh P2P + AirPods Spatial Audio
  Online", and a web of trust "Zero-Knowledge Community Verified (98/100)". It closed with
  `system_health: "100% Operational (898+ Unit/Integration Tests Verified)"`. Every line was
  a constant. None of those subsystems were consulted, several do not exist, and a status
  page that always says OK is worse than no status page — it is the one screen whose entire
  job is to be believed.
- `/city/live-globe` returned five hardcoded cities with coordinates, invented flare counts
  and invented weather ("24°C Sunny", in Lisbon, forever).
- `/feed/transparent-rules` claimed to *apply* a `real_world_weight` of 0.85 and a
  `proximity_bias` of 0.90, stored neither, and reported `ad_free: True` and
  `doomscroll_protection: "ACTIVE"` — a transparency feature that was itself opaque, and
  which described a ranking the code does not implement.

What replaces them is the same information, read from the thing it describes: configuration
for the status, rows for the globe, and the ranking constants themselves for the feed rules.
"""

import os

from substrate import SYSTEM_OWNER
from substrate.graph import Graph

MODULE = "platform.overview"
SCOPES = {"content:read", "events:read", "metrics:read"}

MAX_CITIES = 50


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _configured(var: str) -> bool:
    return bool(str(os.environ.get(var, "")).strip())


# ---- what is actually switched on ---------------------------------------------

def system(graph: Graph, *, account_id: str = "") -> dict:
    """Which capabilities are configured, and which are not, by asking.

    Every line here is derived: a key is present or it is not, a table has rows or it does
    not. Nothing reports itself as online because a dictionary said so.
    """
    capabilities = [
        {"name": "places and city seeding", "needs": None, "available": True,
         "detail": "OpenStreetMap — no key required"},
        {"name": "weather and conditions", "needs": None, "available": True,
         "detail": "Open-Meteo — no key required"},
        {"name": "ticketed listings", "needs": "LIFEOS_TICKETMASTER_KEY",
         "available": _configured("LIFEOS_TICKETMASTER_KEY"),
         "detail": "Tier 2 listings; without it, feeds carry only what was ingested here"},
        {"name": "assisted wording", "needs": "ANTHROPIC_API_KEY",
         "available": _configured("ANTHROPIC_API_KEY"),
         "detail": "Suggestions are assembled from your graph either way; a key only "
                   "changes the phrasing"},
        {"name": "email", "needs": "LIFEOS_RESEND_KEY",
         "available": _configured("LIFEOS_RESEND_KEY"),
         "detail": "Verification and password reset. Without it, those flows print the "
                   "link rather than sending it"},
        {"name": "dating surface", "needs": "LIFEOS_DATING_ENABLED",
         "available": _configured("LIFEOS_DATING_ENABLED"),
         "detail": "Off by default; answers 503 when off"},
    ]

    # Things the old controller claimed were online, that this app genuinely cannot do. They
    # are listed rather than omitted, because a status page that silently drops what it
    # cannot do reads as though it can.
    unavailable = [
        {"name": "push notifications",
         "why": "no VAPID key pair, no APNs certificate and no SMS provider in this repo"},
        {"name": "payments",
         "why": "no payment processor is connected; the shared tab records what is owed "
                "and moves no money"},
        {"name": "BLE mesh, wearables and spatial audio",
         "why": "a web app cannot reach that hardware"},
        {"name": "identity verification",
         "why": "nothing here checks a document; a vouch is one person's word"},
    ]

    session = _sys(graph)
    counts = {}
    for label, row_type in (("accounts", "account"), ("crews", "crew"),
                            ("places", "city_place"), ("cities seeded", "city_seed_request")):
        try:
            counts[label] = len(session.find_entities("content", {"type": row_type},
                                                      limit=5000))
        except Exception:
            counts[label] = 0

    return {
        "capabilities": capabilities,
        "unavailable": unavailable,
        "counts": counts,
        "configured": sum(1 for c in capabilities if c["available"]),
        "of": len(capabilities),
        # `system_health: "100% Operational (898+ Unit/Integration Tests Verified)"` was a
        # string. A running process cannot count its own test suite, and saying so beats
        # quoting a number from the day somebody typed it.
        "health": "reported by asking, not asserted",
        "note": ("Each line is derived — a key is set or it is not, a table has rows or it "
                 "does not. Nothing here reports itself as online."),
    }


# ---- where anybody actually is ------------------------------------------------

def globe(graph: Graph, *, limit: int = MAX_CITIES) -> dict:
    """Cities this instance actually has activity in.

    Five cities with coordinates, flare counts and weather, identical on every deployment,
    including one installed a minute ago. This counts rows instead, and on a new instance
    the honest answer is that nobody is anywhere yet.
    """
    session = _sys(graph)
    tally: dict = {}
    for row_type, field in (("synergy_signal", "open intents"),
                            ("city_message", "messages"),
                            ("city_moment", "moments"),
                            ("city_place", "places")):
        for row in session.find_entities("content", {"type": row_type}, limit=4000):
            attrs = row["attrs"]
            if row_type == "synergy_signal" and attrs.get("withdrawn"):
                continue
            city = (attrs.get("city") or "").strip()
            if not city:
                continue
            entry = tally.setdefault(city, {"city": city,
                                            "label": attrs.get("city_label") or city,
                                            "counts": {}})
            entry["counts"][field] = entry["counts"].get(field, 0) + 1

    items = sorted(tally.values(), key=lambda c: -sum(c["counts"].values()))
    for item in items:
        item["total"] = sum(item["counts"].values())
    return {
        "cities": items[:limit],
        "count": len(items),
        "empty": not items,
        # There are no coordinates here: a city is a slug people typed, and the five sets
        # of lat/lon this replaces were decoration on numbers that were not real either.
        "coordinates": False,
        "suggestion": ("Nothing is happening anywhere on this instance yet. A city fills up "
                       "when somebody posts in it." if not items else ""),
    }


# ---- how the feed actually ranks ----------------------------------------------

def feed_rules() -> dict:
    """The ranking, read from the code that does the ranking.

    The prop accepted a `real_world_weight` and a `proximity_bias`, stored neither, and
    described a ranking this app does not implement — while calling itself transparency.
    Transparency is telling somebody how it really works, so these numbers are imported from
    `modules/discover/core` rather than restated here; if the ranking changes, this changes
    with it, which is the only way a page like this stays true.
    """
    from modules.discover import core

    return {
        "explanation": ("An item's score is the sum of three parts. Nothing else moves it, "
                        "and every item in your feed lists which parts it earned."),
        "parts": [
            {"part": "interest match",
             "how": "the item's topic is one of your interests, or an interest word appears "
                    "in its title",
             "weights": {"topic is your interest": core.TOPIC_HIT,
                         "interest word in the title": core.TITLE_HIT,
                         "the item's topic echoes in its own title": core.TOPIC_IN_TITLE}},
            {"part": "how many people are going",
             "how": "saturating, so the tenth person matters less than the second",
             "weights": {"most a crowd can add": core.POP_WEIGHT,
                         "headcount that earns half of it": core.POP_HALF}},
            {"part": "how soon it is",
             "how": f"full weight today, fading to nothing {core.SOON_DAYS:g} days out",
             "weights": {"most soonness can add": core.SOON_WEIGHT,
                         "days until it counts for nothing": core.SOON_DAYS}},
        ],
        "excluded": [
            "Anything not public. Private items are filtered before scoring, not after.",
            "Anything already finished.",
            "Anything that neither matches you nor has anybody going — that is just noise.",
        ],
        # These were reported as booleans by a handler that could not have known.
        "no_advertising": ("There is no ad system in this app — nothing is inserted into a "
                           "feed for money, because there is no mechanism to."),
        "no_engagement_optimisation": ("Nothing measures time in app, and nothing is ranked "
                                       "by it. There is no session length anywhere in the "
                                       "schema."),
        "settable": False,
        "why_not_settable": ("This is a description, not a control panel. The endpoint it "
                             "replaces accepted weights and stored none of them, which is "
                             "the opposite of transparency."),
    }
