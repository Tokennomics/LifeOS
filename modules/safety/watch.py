"""SafeWalk — someone knows where you are going and when you should have arrived.

Three endpoints claimed to do this and none of them told anybody anything. `/safety/escort`
returned `escort_code: "SAFE-8921"` — the same code for every walk in the world — and said
the crew had been notified. `/safety/squad-beacon` broadcast a location to four trusted crew
members. `/safety/emergency-sos` returned `recipients_notified: 4` and an
`emergency_pin: "SOS-9911-GPS"`.

This is the most dangerous class of prop in the repo. Every other one wasted somebody's
time; this one could get somebody hurt, because a person who believes their crew is
watching behaves differently from a person who knows nobody is.

So the design is small and the claims are exact:

- **A watch is a real row with a real deadline.** You say where you are going and when you
  should be there. Your named watchers can see it, and `overdue` lists the ones that passed
  their ETA without an arrival.
- **Nothing is claimed about delivery.** The app cannot send an SMS, so it does not say it
  did. `notified` reports how many watchers *can read the watch*, and `push_delivered` is
  explicitly false. Telling somebody "your crew has been notified" when no message left the
  building is the exact failure this replaces.
- **No location.** A watch carries a destination you typed, not a coordinate. There is no
  background location in a PWA, and a safety feature that quietly implies live tracking is
  worse than one that says plainly what it does.
- **Arriving is one tap and clears it.** A safety feature nobody cancels is a safety feature
  everybody ignores.
"""

import datetime

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

MODULE = "safety.watch"
SCOPES = {"content:read", "content:write"}
RECORD = "safe_walk"

MAX_TEXT = 200
MAX_MINUTES = 720
DEFAULT_MINUTES = 30
MAX_WATCHERS = 20
MAX_LISTED = 50

DISCLAIMER = ("This app cannot call anyone. It records where you said you were going and "
              "shows your watchers when you are overdue — nothing more. In an emergency, "
              "call your local emergency number.")


class WatchError(ValueError):
    """A walk that cannot be started or ended."""


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse(stamp: str):
    try:
        return datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _open(row: dict) -> bool:
    return not (row["attrs"].get("arrived") or row["attrs"].get("cancelled"))


def start(graph: Graph, destination: str, *, account_id: str, handle: str = "",
          eta_minutes: int = DEFAULT_MINUTES, watchers=None, severity: str = "walk",
          note: str = "", source: str = MODULE) -> dict:
    """Start a watch. Returns who can actually see it, not who was notified."""
    if not account_id:
        raise WatchError("sign in first")
    destination = str(destination or "").strip()[:MAX_TEXT]
    if not destination:
        raise WatchError("where are you going?")

    if eta_minutes is None:
        eta_minutes = DEFAULT_MINUTES
    try:
        eta_minutes = int(eta_minutes)
    except (TypeError, ValueError):
        raise WatchError("eta must be a number of minutes")
    if eta_minutes < 1 or eta_minutes > MAX_MINUTES:
        raise WatchError(f"pick between 1 and {MAX_MINUTES} minutes")

    watch_list = [str(w).strip() for w in (watchers or []) if str(w).strip()][:MAX_WATCHERS]
    severity = "sos" if str(severity).lower() == "sos" else "walk"

    session = _sys(graph)
    # One open walk at a time: two overlapping ETAs is how a watcher stops trusting the list.
    for row in session.find_entities("content", {"type": RECORD, "account_id": account_id},
                                     limit=50):
        if _open(row):
            session.update_entity(row["id"], {"cancelled": True}, source=source)

    walk_id = session.create_entity("content", {
        "type": RECORD, "account_id": account_id, "handle": str(handle or "")[:80],
        "destination": destination, "note": str(note or "").strip()[:MAX_TEXT],
        "severity": severity, "watchers": watch_list,
        "started_at": now_iso(),
        "due_at": (_now() + datetime.timedelta(minutes=eta_minutes)).isoformat(),
        "arrived": False, "cancelled": False,
    }, source=source, owner_id=SYSTEM_OWNER)

    return {
        "watching": True, "walk_id": walk_id, "destination": destination,
        "severity": severity, "eta_minutes": eta_minutes,
        # The honest replacement for `recipients_notified: 4`.
        "watchers": watch_list, "can_see_it": len(watch_list),
        "push_delivered": False,
        "delivery_note": ("Nobody has been messaged. Your watchers see this when they open "
                          "the app." if watch_list else
                          "You named no watchers, so nobody can see this."),
        "disclaimer": DISCLAIMER,
    }


def arrive(graph: Graph, *, account_id: str, walk_id: str = "",
           source: str = MODULE) -> dict:
    """Say you got there. Clears the watch."""
    if not account_id:
        raise WatchError("sign in first")
    session = _sys(graph)
    closed = 0
    for row in session.find_entities("content", {"type": RECORD, "account_id": account_id},
                                     limit=50):
        if walk_id and row["id"] != walk_id:
            continue
        if _open(row):
            session.update_entity(row["id"], {"arrived": True,
                                              "arrived_at": now_iso()}, source=source)
            closed += 1
    return {"arrived": True, "closed": closed}


def cancel(graph: Graph, *, account_id: str, source: str = MODULE) -> dict:
    """Call it off — you changed your mind, not that you arrived."""
    if not account_id:
        raise WatchError("sign in first")
    session = _sys(graph)
    closed = 0
    for row in session.find_entities("content", {"type": RECORD, "account_id": account_id},
                                     limit=50):
        if _open(row):
            session.update_entity(row["id"], {"cancelled": True}, source=source)
            closed += 1
    return {"cancelled": True, "closed": closed}


def _render(row: dict, now) -> dict:
    attrs = row["attrs"]
    due = _parse(attrs.get("due_at", ""))
    return {
        "walk_id": row["id"], "handle": attrs.get("handle") or "someone",
        "account_id": attrs.get("account_id", ""),
        "destination": attrs.get("destination", ""), "note": attrs.get("note", ""),
        "severity": attrs.get("severity", "walk"),
        "started_at": attrs.get("started_at", ""), "due_at": attrs.get("due_at", ""),
        "overdue": bool(due and due < now),
        "overdue_minutes": (int((now - due).total_seconds() // 60)
                            if due and due < now else 0),
    }


def mine(graph: Graph, *, account_id: str) -> dict:
    now = _now()
    open_walks = [_render(row, now) for row in
                  _sys(graph).find_entities("content",
                                            {"type": RECORD, "account_id": account_id},
                                            limit=MAX_LISTED)
                  if _open(row)]
    return {"walks": open_walks, "empty": not open_walks, "disclaimer": DISCLAIMER}


def watching(graph: Graph, *, account_id: str, limit: int = MAX_LISTED) -> dict:
    """Walks you were named on. The read that makes the feature real.

    Overdue first, because that is the only reason anybody opens this screen.
    """
    if not account_id:
        raise WatchError("sign in first")
    now = _now()
    walks = []
    for row in _sys(graph).find_entities("content", {"type": RECORD}, limit=500):
        if not _open(row):
            continue
        if account_id not in (row["attrs"].get("watchers") or []):
            continue
        walks.append(_render(row, now))
    walks.sort(key=lambda w: (not w["overdue"], w["due_at"]))
    overdue = [w for w in walks if w["overdue"]]
    return {
        "walks": walks[:limit], "overdue": overdue, "overdue_count": len(overdue),
        "empty": not walks,
        "suggestion": "" if walks else (
            "Nobody has named you as a watcher. Somebody has to add you before you can see "
            "their walks."),
        "disclaimer": DISCLAIMER,
    }
