"""Slices of a city — the vinyl night, the trailhead, the reading room.

Fourteen `/seeding/*` endpoints promised curated local knowledge and all fourteen branched
on the word "munich" in the request: say it and you got a hand-written list of Isar river
swims and Krautrock nights, say anything else and you got Edinburgh's. Nothing was ingested,
nothing was curated, and the "editorial press scraper" scraped nothing.

They are one question asked fourteen ways — *what is here, of this kind?* — and the app now
has two real sources to answer it with: the OpenStreetMap places `city.places` seeds, and
the listings and meetups people and venue feeds actually put on the board. So there is one
function underneath, and the fourteen become named views over it.

Two rules hold everywhere here:

**A view never invents its category.** `trails` asks for the map categories that mean
trails; `vinyl` matches listings against music words. If a city has no trails mapped, the
answer is that it has none — not a plausible walk with a distance and a difficulty rating,
which is what the old version returned for every city on earth.

**Where there is no source, there is no view.** Two of the fourteen asked for data this app
cannot get: live footfall needs sensors nobody has installed, and "editorial press" means
scraping publications with no agreement to do so. Those report what they *can* see and say
plainly what they cannot, rather than shrinking the invention.
"""

from substrate.graph import Graph

from modules.city import chat, meetups, places

MODULE = "city.guide"

MAX_ITEMS = 20

#: Each view: which mapped categories it draws on, and which words in a listing's title mean
#: it. Kept as data rather than fourteen functions because they differ only here.
VIEWS = {
    "trails": {
        "label": "Trails, parks and wild swims",
        "categories": ["trail", "park", "swim"],
        "terms": ["hike", "hiking", "walk", "trail", "swim", "wild", "forest", "ridge"],
    },
    "vinyl": {
        "label": "Records and live music",
        "categories": [],
        "terms": ["vinyl", "record", "records", "dj", "techno", "jazz", "band", "gig",
                  "live", "music", "listening", "soundsystem"],
    },
    "food": {
        "label": "Food, markets and pop-ups",
        "categories": ["market"],
        "terms": ["dinner", "supper", "food", "market", "pop-up", "popup", "tasting",
                  "cook", "kitchen", "brunch", "feast"],
    },
    "literary": {
        "label": "Books, readings and quiet rooms",
        "categories": ["library"],
        "terms": ["book", "books", "reading", "poetry", "writing", "salon", "library",
                  "zine"],
    },
    "culture": {
        "label": "Galleries, viewpoints and markets",
        "categories": ["gallery", "viewpoint", "market"],
        "terms": ["exhibition", "gallery", "art", "film", "theatre", "museum", "talk"],
    },
    "wellness": {
        "label": "Saunas, swims and quiet",
        "categories": ["sauna", "swim"],
        "terms": ["sauna", "swim", "plunge", "yoga", "breathwork", "quiet"],
    },
}


class GuideError(ValueError):
    """A view that does not exist, or a city that was not named."""


def views() -> list[dict]:
    return [{"view": key, "label": spec["label"]} for key, spec in sorted(VIEWS.items())]


def _matches(text: str, terms: list[str]) -> list[str]:
    from modules.city import synergy

    hits = set()
    for term in terms:
        if synergy._shared(term, text):
            hits.add(term)
    return sorted(hits)


def _listings(graph: Graph, city: str, terms: list[str], viewer_id: str) -> tuple:
    """Meetups and published events whose titles actually mention this kind of thing."""
    from modules.ai import assist
    from modules.discover import discover

    room = chat.slug(city)
    board, listed = [], []
    try:
        for meetup in meetups.listing(graph, room, viewer_id=viewer_id).get("meetups", []):
            hits = _matches(f"{meetup.get('title', '')} {meetup.get('note', '')}", terms)
            if hits:
                board.append({**meetup, "matched_on": hits})
    except Exception:
        pass

    try:
        found = discover.find(graph, city=city, limit=40)
        if isinstance(found, dict):
            found = found.get("items", [])
        for item in found or []:
            hits = _matches(f"{item.get('title', '')} {item.get('topic', '')}", terms)
            if hits:
                listed.append({**item, "matched_on": hits})
    except Exception:
        pass

    return board[:MAX_ITEMS], listed[:MAX_ITEMS], assist


def view(graph: Graph, city: str, name: str, *, viewer_id: str = "") -> dict:
    """One slice of one city, from the map and the board.

    An empty answer is the true one for a city nobody has seeded and nobody has posted in,
    and it says which of the two is missing — because "no trails mapped here" and "nobody
    has proposed a walk" are different problems with different fixes.
    """
    if not str(city or "").strip():
        raise GuideError("which city?")
    spec = VIEWS.get(str(name or "").strip().lower())
    if spec is None:
        raise GuideError(f"unknown view {name!r} (known: {[v['view'] for v in views()]})")

    room = chat.slug(city)
    mapped = []
    for category in spec["categories"]:
        try:
            found = places.listing(graph, city, category=category, limit=MAX_ITEMS)
        except Exception:
            continue
        mapped.extend(found.get("places", []))
    mapped = mapped[:MAX_ITEMS]

    board, listed, _ = _listings(graph, city, spec["terms"], viewer_id)
    empty = not (mapped or board or listed)

    return {
        "view": name, "label": spec["label"], "city": room,
        "places": mapped, "meetups": board, "events": listed,
        "empty": empty,
        "attribution": "© OpenStreetMap contributors" if mapped else "",
        "suggestion": "" if not empty else (
            f"Nothing here for {spec['label'].lower()} yet. "
            + ("The map has nothing in these categories for this city — it may not be "
               "seeded, or OpenStreetMap may simply have none."
               if spec["categories"] else
               "Propose something and it becomes the first entry.")),
    }


def busiest(graph: Graph, city: str, *, viewer_id: str = "") -> dict:
    """Where people are actually going, by the only measure this app has: who said yes.

    `social-viral-pulse` reported trending venues with view counts and a "virality index".
    There is no view counting here and no social graph to be viral across. What there is, is
    a meetup with four people going and one with none, which is the honest version of the
    same question.
    """
    if not str(city or "").strip():
        raise GuideError("which city?")
    room = chat.slug(city)
    try:
        board = meetups.listing(graph, room, viewer_id=viewer_id).get("meetups", [])
    except Exception:
        board = []
    ranked = sorted(board, key=lambda m: (-int(m.get("going_count", 0)),
                                          str(m.get("starts_at", ""))))
    return {
        "city": room,
        "meetups": ranked[:MAX_ITEMS],
        "measure": "people who said they are going",
        "empty": not ranked,
        # Named because the endpoint used to report one.
        "no_virality_index": ("Nothing counts views or shares here, so there is no trend "
                              "score — only how many people said yes."),
        "suggestion": "" if ranked else "Nothing on the board in this city yet.",
    }


def unavailable(what: str, reason: str, *, alternative: dict | None = None) -> dict:
    """The honest shape for a view whose source does not exist.

    Two of the fourteen asked for data this app cannot get. Saying so — and handing back the
    nearest thing that *is* real — is the whole of the fix.
    """
    return {"available": False, "what": what, "reason": reason,
            "instead": alternative or {}}
