"""Reflection, purpose and the endpoints that scored a life out of 100.

`ikigai-compass` returned `fulfillment_score: 87`. `regret-minimization` returned
`life_vision_score: 92`. `vitality-circadian-flow` returned a `longevity_score`.
`wealth-value-optimizer` returned a "fulfillment ROI" per spending category. Every one was
a literal, identical for every account on the instance, including one created a second
earlier — the karma-98 bug wearing four more hats.

Those numbers are not recoverable, and not because the arithmetic is hard. A graph of
meetups cannot know whether somebody's life is aligned with their purpose, and printing a
92 next to the question is worse than leaving it blank: it looks like a measurement, it
will be believed, and there is nothing underneath it.

So the scores are gone and the features are not. What survives is the half that was always
real and was buried under the scoring:

- **Writing a reflection down.** `stoic-presence-mirror` claimed to log a peak moment and a
  gratitude anchor, and stored nothing — the "lifetime_gratitude_count" was a constant.
  Reflections are now actual owner-scoped rows, and the count is a count.
- **Seeing what you have actually been doing**, from `personal.recap`, which computes from
  the graph and reports emptiness honestly on a new account.
- **Your own goals**, which the horizon modules have held since Sprint 1 and which these
  endpoints never once read.

Reflections are private by construction: they live in the author's own slice, like the chat
mute list, and no function here takes a viewer other than the author.
"""

import datetime

from substrate import now_iso
from substrate.graph import Graph

MODULE = "ai.reflect"
SCOPES = {"content:read", "content:write"}
RECORD = "reflection"

MAX_NOTE = 1000
MAX_LISTED = 50


class ReflectError(ValueError):
    """A reflection that cannot be stored."""


def _session(graph: Graph):
    return graph.session(MODULE, SCOPES)


def log(graph: Graph, note: str, *, kind: str = "gratitude", source: str = MODULE) -> dict:
    """Write something down. Owner-scoped, so it is yours and nobody else can read it."""
    note = str(note or "").strip()[:MAX_NOTE]
    if not note:
        raise ReflectError("what would you like to remember?")
    kind = str(kind or "gratitude").strip()[:40]

    session = _session(graph)
    entry_id = session.create_entity("content", {
        "type": RECORD, "kind": kind, "note": note,
        "day": datetime.datetime.now(datetime.timezone.utc).date().isoformat(),
        "created_at": now_iso(),
    }, source=source)
    return {"logged": True, "reflection_id": entry_id, "kind": kind,
            "total": count(graph), "privacy": "yours only — never shared, never scored"}


def entries(graph: Graph, *, kind: str = "", limit: int = MAX_LISTED) -> list[dict]:
    query = {"type": RECORD}
    if kind:
        query["kind"] = kind
    rows = _session(graph).find_entities("content", query, limit=MAX_LISTED * 2)
    out = [{"reflection_id": r["id"], "kind": r["attrs"].get("kind", ""),
            "note": r["attrs"].get("note", ""), "day": r["attrs"].get("day", ""),
            "created_at": r["attrs"].get("created_at", "")} for r in rows]
    out.sort(key=lambda e: e["created_at"], reverse=True)
    return out[:limit]


def count(graph: Graph, *, kind: str = "") -> int:
    """A real total. `lifetime_gratitude_count` was 247 for everybody, forever."""
    query = {"type": RECORD}
    if kind:
        query["kind"] = kind
    return len(_session(graph).find_entities("content", query, limit=10000))


def purpose(graph: Graph, *, account_id: str = "", claude=None) -> dict:
    """What you have actually been doing, and what you said you wanted to do.

    This is the honest residue of `ikigai-compass` and `regret-minimization`: no score, no
    pillars invented on your behalf, no "fulfillment ROI". Your goals are yours — they come
    from the horizon modules, where you wrote them — and your activity comes from
    `personal.recap`, which counts real captures, tasks and outings.
    """
    from modules.ai import assist
    from modules.personal import recap

    standing = assist._safely(lambda: recap.standing(graph), {"empty": True})
    goals = assist._safely(lambda: _goals(graph), [])
    reflections = assist._safely(lambda: entries(graph, limit=5), [])

    empty = bool(standing.get("empty")) and not goals and not reflections
    return {
        "activity": standing,
        "goals": goals,
        "recent_reflections": reflections,
        "reflection_count": assist._safely(lambda: count(graph), 0),
        # Named explicitly so nobody re-adds one thinking it was an oversight.
        "no_score": ("This deliberately has no fulfilment, vision or longevity score. "
                     "A graph of meetups cannot measure any of those, and the numbers that "
                     "used to be here were the same for every account."),
        "empty": empty,
        **assist.available(claude),
        "suggestion": "" if not empty else (
            "Nothing to reflect on yet. Write down one thing worth remembering, or set a "
            "goal — this fills in from what you actually do."),
    }


def _goals(graph: Graph) -> list[dict]:
    """Goals as the horizon modules stored them. Read-only here: this surface reports, it
    does not quietly rewrite somebody's plan."""
    rows = graph.session(MODULE, {"content:read"}).find_entities(
        "content", {"type": "goal"}, limit=50)
    out = []
    for row in rows:
        attrs = row.get("attrs", {})
        if attrs.get("done") or attrs.get("archived"):
            continue
        out.append({"goal_id": row["id"], "title": attrs.get("title", ""),
                    "week": attrs.get("week", ""), "target_date": attrs.get("target_date", "")})
    return out[:MAX_LISTED]
