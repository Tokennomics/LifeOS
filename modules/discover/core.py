"""Discover — the pure matcher (no graph, no I/O, deterministic).

item = {"id", "kind": "event"|"crew", "title", "topic", "city", "start", "visibility"}

Two invariants, in this order:
  1. **Only public items are ever returned.** Privacy is a filter applied before scoring,
     never a ranking penalty — an invite-only pool evening cannot surface at any score.
  2. If a city is given, the item must be in that city. "Local" means local.

Scoring is interest overlap plus a nudge toward what's happening soonest, so declaring
"sushi" in Lisbon ranks the sushi night above the generic meetup the same week.
"""

TOPIC_HIT = 3.0      # the item's topic IS one of your interests
TITLE_HIT = 2.0      # an interest word shows up in the title
TOPIC_IN_TITLE = 1.0 # the item's own topic echoes in its title (a well-named event)
SOONER = 0.5         # tie-break nudge toward the nearest date


def _key(s) -> str:
    return str(s or "").strip().lower()


def _words(s) -> set[str]:
    return {w for w in _key(s).replace("/", " ").replace(",", " ").split() if w}


def score_item(item: dict, interests) -> float:
    """How well one item matches a set of interests (0 = no signal)."""
    wanted = {_key(i) for i in (interests or []) if _key(i)}
    if not wanted:
        return 0.0
    topic = _key(item.get("topic"))
    title_words = _words(item.get("title"))
    title = _key(item.get("title"))

    score = 0.0
    topic_wanted = bool(topic) and topic in wanted
    if topic_wanted:
        score += TOPIC_HIT
        # A well-named event only earns this on top of a topic you actually asked for —
        # otherwise unrelated-but-tidy listings would score above zero and leak into search.
        if topic in title_words:
            score += TOPIC_IN_TITLE
    for want in wanted:
        # whole-word match on the title, or a multi-word interest appearing verbatim
        if want in title_words or (" " in want and want in title):
            score += TITLE_HIT
    return score


def rank_matches(items, interests=None, city: str = "", now: str = "", limit: int = 20,
                 min_score: float = 0.0) -> list[dict]:
    """Filter to public (+ city, + upcoming) and rank by interest match, soonest first.

    `min_score=0` is BROWSE — everything public and local, best matches first, so landing
    somewhere new still shows you what's on. `min_score>0` is SEARCH — only things that
    actually match what you asked for.
    """
    wanted_city = _key(city)
    out = []
    for item in items or []:
        if item.get("visibility") != "public":
            continue                                   # invariant 1 — never leaks
        if wanted_city and _key(item.get("city")) != wanted_city:
            continue                                   # invariant 2 — local means local
        start = item.get("start") or ""
        if now and start and start < now:
            continue                                   # don't offer the past
        score = score_item(item, interests)
        if score < min_score:
            continue
        out.append({**item, "score": score})

    # Best match first; then soonest (undated crews after dated events); then stable by title.
    out.sort(key=lambda i: (-i["score"], i.get("start") or "9999", _key(i.get("title"))))
    return out[:max(0, limit)]
