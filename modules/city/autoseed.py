"""A city seeds itself the first time somebody lands in it.

Seeding was operator-only: somebody with the gateway token had to POST for each city, which
means the first person to arrive anywhere new sees an empty screen and the operator finds
out too late to help them. The whole point of pulling third places from OpenStreetMap was
that a city can have something in it before it has users — and that only works if nobody has
to be asked first.

So arriving in an unseeded city queues it, and the seed runs after the response has already
been sent.

**The guardrails are the design here, not a footnote.** This is the only place in the app
where ordinary user input causes the server to make outbound requests to a third party, and
that third party is a volunteer-run service with no contract and no billing. Somebody typing
five hundred city names must not turn into five hundred Overpass queries.

- **Only cities that geocode.** A name that resolves to nothing is recorded as a dead end,
  not retried on every future arrival.
- **A cooldown per city**, applied to failures too — a bogus name is asked about once, and a
  real city is refreshed at most every `COOLDOWN_DAYS`.
- **A global ceiling per hour**, so a burst of arrivals queues rather than fans out.
- **One at a time.** Requests are drained sequentially, never in parallel — the etiquette
  that keeps a free service free.
- **A claim before the work**, so two simultaneous arrivals in the same city do not both
  seed it.

The queue is durable, and `drain` is safe to call from a cron job as well. That matters
because the background task runs in-process: a deploy or a restart mid-seed loses the
attempt, and the row it left behind is what lets the next drain pick it up.
"""

import datetime

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

from modules.city import chat, places

MODULE = "city.autoseed"
SCOPES = {"content:read", "content:write"}
RECORD = "city_seed_request"

COOLDOWN_DAYS = 30           # a real city is refreshed at most this often
FAILED_COOLDOWN_DAYS = 7     # a name that went nowhere is not retried tomorrow
MAX_PER_HOUR = 6             # global ceiling on outbound seeding
CLAIM_MINUTES = 10           # an in-flight claim older than this is assumed dead
MAX_QUEUE = 100


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse(stamp: str):
    try:
        return datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _rows(graph: Graph, room: str = ""):
    query = {"type": RECORD}
    if room:
        query["city"] = room
    return _sys(graph).find_entities("content", query, limit=MAX_QUEUE * 4)


def _recent_attempts(graph: Graph, since) -> int:
    return sum(1 for row in _rows(graph)
               if (at := _parse(row["attrs"].get("attempted_at", ""))) and at > since)


def status_for(graph: Graph, city: str) -> dict:
    """Whether this city would be seeded right now, and why not if not.

    Separate from `request` so a caller — or a test — can ask without causing anything.
    """
    if not str(city or "").strip():
        return {"eligible": False, "reason": "no city"}
    room = chat.slug(city)
    now = _now()

    for row in _rows(graph, room):
        attrs = row["attrs"]
        state = attrs.get("state", "")
        attempted = _parse(attrs.get("attempted_at", ""))
        if state == "claimed":
            claimed = _parse(attrs.get("claimed_at", ""))
            if claimed and now - claimed < datetime.timedelta(minutes=CLAIM_MINUTES):
                return {"eligible": False, "reason": "already being seeded", "city": room}
            return {"eligible": True, "reason": "a previous attempt did not finish",
                    "city": room, "row_id": row["id"]}
        if state == "pending":
            return {"eligible": False, "reason": "already queued", "city": room,
                    "row_id": row["id"]}
        if state == "done" and attempted:
            if now - attempted < datetime.timedelta(days=COOLDOWN_DAYS):
                return {"eligible": False, "reason": "seeded recently", "city": room}
        if state == "failed" and attempted:
            if now - attempted < datetime.timedelta(days=FAILED_COOLDOWN_DAYS):
                # Includes "this city does not exist". Asking Overpass again tomorrow about
                # a typo is exactly the traffic this module exists to not generate.
                return {"eligible": False, "reason": attrs.get("detail", "recently failed"),
                        "city": room}
        return {"eligible": True, "reason": "cooldown expired", "city": room,
                "row_id": row["id"]}

    return {"eligible": True, "reason": "never seeded", "city": room}


def request(graph: Graph, city: str, *, source: str = MODULE) -> dict:
    """Queue a city, if it is worth queueing. Idempotent and cheap — safe on a hot path."""
    state = status_for(graph, city)
    if not state.get("eligible"):
        return {"queued": False, **state}

    room = state["city"]
    session = _sys(graph)
    if state.get("row_id"):
        session.update_entity(state["row_id"], {"state": "pending",
                                                "requested_at": now_iso()}, source=source)
        row_id = state["row_id"]
    else:
        pending = sum(1 for r in _rows(graph) if r["attrs"].get("state") == "pending")
        if pending >= MAX_QUEUE:
            return {"queued": False, "reason": "queue is full", "city": room}
        row_id = session.create_entity("content", {
            "type": RECORD, "city": room, "city_label": str(city).strip()[:80],
            "state": "pending", "requested_at": now_iso(),
            "attempted_at": "", "claimed_at": "", "detail": "",
        }, source=source, owner_id=SYSTEM_OWNER)

    return {"queued": True, "city": room, "row_id": row_id}


def _claim(session, row, source: str) -> bool:
    """Take a pending row, so two arrivals in the same city do not both seed it."""
    fresh = session.get_entity(row["id"])
    if fresh is None or fresh["attrs"].get("state") not in ("pending", "claimed"):
        return False
    claimed = _parse(fresh["attrs"].get("claimed_at", ""))
    if fresh["attrs"].get("state") == "claimed" and claimed and \
            _now() - claimed < datetime.timedelta(minutes=CLAIM_MINUTES):
        return False
    session.update_entity(row["id"], {"state": "claimed", "claimed_at": now_iso()},
                          source=source)
    return True


def drain(graph: Graph, *, limit: int = 1, source: str = MODULE, **seed_kwargs) -> dict:
    """Seed up to `limit` queued cities, one at a time.

    Called both from the background task after a request and from a cron job. Sequential on
    purpose: parallel Overpass queries from one host is how a free service stops being free.
    """
    now = _now()
    done_this_hour = _recent_attempts(graph, now - datetime.timedelta(hours=1))
    room_left = max(0, MAX_PER_HOUR - done_this_hour)
    if room_left <= 0:
        return {"seeded": 0, "skipped": "hourly ceiling reached",
                "ceiling": MAX_PER_HOUR}

    session = _sys(graph)
    queued = [r for r in _rows(graph) if r["attrs"].get("state") in ("pending", "claimed")]
    queued.sort(key=lambda r: str(r["attrs"].get("requested_at", "")))

    results = []
    for row in queued[:min(limit, room_left)]:
        if not _claim(session, row, source):
            continue
        label = row["attrs"].get("city_label") or row["attrs"].get("city", "")
        try:
            outcome = places.seed(graph, label, **seed_kwargs)
        except Exception as exc:
            session.update_entity(row["id"], {
                "state": "failed", "attempted_at": now_iso(),
                "detail": f"{type(exc).__name__}"}, source=source)
            results.append({"city": label, "state": "failed", "detail": type(exc).__name__})
            continue

        ok = outcome.get("status") == "ok"
        session.update_entity(row["id"], {
            "state": "done" if ok else "failed",
            "attempted_at": now_iso(),
            "detail": "" if ok else str(outcome.get("status", "")),
            "added": outcome.get("added", 0),
        }, source=source)
        results.append({"city": label, "state": "done" if ok else "failed",
                        "added": outcome.get("added", 0),
                        "detail": outcome.get("status", "")})

    return {"seeded": sum(1 for r in results if r["state"] == "done"),
            "attempted": len(results), "results": results,
            "remaining": max(0, len(queued) - len(results))}


def queue(graph: Graph) -> dict:
    """What is waiting, and what has been tried. The operator's view."""
    items = []
    for row in _rows(graph):
        attrs = row["attrs"]
        items.append({"city": attrs.get("city", ""), "state": attrs.get("state", ""),
                      "requested_at": attrs.get("requested_at", ""),
                      "attempted_at": attrs.get("attempted_at", ""),
                      "added": attrs.get("added", 0),
                      "detail": attrs.get("detail", "")})
    items.sort(key=lambda i: i["requested_at"], reverse=True)
    pending = [i for i in items if i["state"] in ("pending", "claimed")]
    return {"queue": items[:MAX_QUEUE], "pending": len(pending),
            "seeded_last_hour": _recent_attempts(
                graph, _now() - datetime.timedelta(hours=1)),
            "hourly_ceiling": MAX_PER_HOUR}
