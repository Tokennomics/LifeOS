"""Discover — the pure matcher (no graph, no I/O, deterministic).

item = {"id", "kind": "event"|"crew", "title", "topic", "city", "start", "visibility"}

Two invariants, in this order:
  1. **Only public items are ever returned.** Privacy is a filter applied before scoring,
     never a ranking penalty — an invite-only pool evening cannot surface at any score.
  2. If a city is given, the item must be in that city. "Local" means local.

Scoring is interest overlap plus a nudge toward what's happening soonest, so declaring
"sushi" in Lisbon ranks the sushi night above the generic meetup the same week.
"""

import datetime

TOPIC_HIT = 3.0      # the item's topic IS one of your interests
TITLE_HIT = 2.0      # an interest word shows up in the title
TOPIC_IN_TITLE = 1.0 # the item's own topic echoes in its title (a well-named event)
SOONER = 0.5         # tie-break nudge toward the nearest date

# Feed blending. Popularity SATURATES: 40 people interested is better than 4, but not
# ten times better — otherwise one big event buries everything you'd actually enjoy.
POP_WEIGHT = 3.0     # ceiling a crowd can contribute
POP_HALF = 4.0       # headcount at which you get half of POP_WEIGHT
SOON_WEIGHT = 1.5    # bonus for "it's happening while you're around"
SOON_DAYS = 7.0


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


def matched_interests(item: dict, interests) -> list[str]:
    """Which of your interests this item actually hit — so a feed can say why."""
    wanted = [i for i in (interests or []) if _key(i)]
    topic = _key(item.get("topic"))
    title_words = _words(item.get("title"))
    title = _key(item.get("title"))
    hits = []
    for want in wanted:
        k = _key(want)
        if k == topic or k in title_words or (" " in k and k in title):
            if want not in hits:
                hits.append(want)
    return hits


def _dt(value: str):
    """Parse an ISO timestamp to a naive-UTC datetime, or None. Tolerant by design —
    a feed must not blow up on a hand-typed date."""
    try:
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return parsed


def popularity_score(count) -> float:
    """Saturating: more people is better, with diminishing returns."""
    try:
        n = max(0.0, float(count or 0))
    except (TypeError, ValueError):
        return 0.0
    return POP_WEIGHT * n / (n + POP_HALF)


def soon_score(start: str, now: str) -> float:
    """Full weight for today, fading to nothing at SOON_DAYS out."""
    start_dt, now_dt = _dt(start), _dt(now)
    if start_dt is None or now_dt is None:
        return 0.0
    days = (start_dt - now_dt).total_seconds() / 86400.0
    if days < 0 or days > SOON_DAYS:
        return 0.0
    return SOON_WEIGHT * (SOON_DAYS - days) / SOON_DAYS


def rank_feed(items, interests=None, now: str = "", limit: int = 20) -> list[dict]:
    """The feed: what's worth your evening, blending interest match, crowd and timing.

    Same privacy invariant as rank_matches — only public items, filtered before scoring.
    Each item carries `reasons`, because a feed you can't interrogate is a feed you
    can't trust.
    """
    out = []
    for item in items or []:
        if item.get("visibility") != "public":
            continue
        start = item.get("start") or ""
        if now and start and start < now:
            continue
        going = item.get("going_count", 0) or 0
        match = score_item(item, interests)
        pop = popularity_score(going)
        soon = soon_score(start, now) if start else 0.0
        if match <= 0 and pop <= 0:
            continue        # neither relevant nor happening — that's just noise

        hits = matched_interests(item, interests)
        reasons = []
        if hits:
            reasons.append("matches " + ", ".join(hits[:3]))
        if going:
            reasons.append(f"{int(going)} interested")
        if soon > 0:
            reasons.append("happening soon")
        out.append({**item, "score": round(match + pop + soon, 3), "match_score": match,
                    "popularity_score": round(pop, 3), "matched": hits, "reasons": reasons})

    out.sort(key=lambda i: (-i["score"], i.get("start") or "9999", _key(i.get("title"))))
    return out[:max(0, limit)]


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
