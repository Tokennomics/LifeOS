"""Your calendar and LifeOS, both ways, without OAuth.

Two directions, both by URL, because a URL is the one thing every calendar app (Google,
Apple, Outlook, Proton, Fastmail) accepts with no developer account and no review:

**Out: LifeOS in your phone's calendar.** A personal subscribe link carries your own LifeOS
events — plan stops you approved, things you added — so they sit next to everything else
in the calendar you already look at. The crew links (`calendars.feeds`) could only carry a
crew. This is the same design for one person: the token is shown once, stored only as a
SHA-256, read-only, expiring and revocable; an unknown token gets an empty calendar, so the
URL space cannot be probed. Busy blocks imported *from* your calendar are left out of it, or
every meeting would come back to you as a second copy.

**In: your busy times in LifeOS.** You paste your calendar's secret iCal address (Google:
Settings → your calendar → "Secret address in iCal format"). The refresh loop reads it on
every pass. The owner-only `calendar.ics_url` config did this for one person; this does it
for each account. Privacy default: **free/busy only** — a block's time is kept, its title is
not, unless you ask. A meeting cancelled upstream is removed here, instead of staying busy
forever. The day planner reads these blocks, so it stops planning over your meetings.

The pasted address is a credential to your calendar, so it is never returned whole: reads
show the host and the last four characters.
"""

import datetime
import hashlib
import secrets
import urllib.parse

from substrate import SYSTEM_OWNER, now_iso, safefetch
from substrate.graph import Graph

MODULE = "calendars.personal"
SCOPES = {"content:read", "content:write", "events:read", "events:write"}
LINK_RECORD = "personal_calendar_link"
SOURCE_RECORD = "calendar_source"
IMPORTED = "calendar_import"

TOKEN_BYTES = 32
DEFAULT_DAYS = 365
MAX_LINKS = 5
MAX_SOURCES = 5
WINDOW_PAST_DAYS = 1
WINDOW_DAYS = 30


class CalendarError(ValueError):
    """A link or a source that cannot be made or used."""


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse(stamp):
    try:
        value = datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo else value.replace(tzinfo=datetime.timezone.utc)


# ---- out: a subscribe link -----------------------------------------------------------

def mint_link(graph: Graph, *, days: int = DEFAULT_DAYS, source: str = MODULE) -> dict:
    owner = graph.default_owner
    if not owner:
        raise CalendarError("sign in first")
    session = _sys(graph)
    live = [r for r in session.find_entities("content", {"type": LINK_RECORD, "owner": owner},
                                             limit=50) if not r["attrs"].get("revoked")]
    if len(live) >= MAX_LINKS:
        raise CalendarError("that is a lot of calendar links — revoke one first")
    days = max(1, min(int(days or DEFAULT_DAYS), DEFAULT_DAYS * 2))
    token = secrets.token_urlsafe(TOKEN_BYTES)
    link_id = session.create_entity("content", {
        "type": LINK_RECORD, "owner": owner, "token_hash": _hash(token),
        "created_at": now_iso(), "revoked": False,
        "expires_at": (_now() + datetime.timedelta(days=days)).isoformat(),
    }, source=source, owner_id=SYSTEM_OWNER)
    return {"link_id": link_id, "token": token, "path": f"/calendar/me/{token}.ics",
            "expires_in_days": days, "read_only": True,
            "warning": ("Anyone with this link can read your LifeOS events. Revoke it here "
                        "if it goes somewhere it should not.")}


def links(graph: Graph) -> list[dict]:
    rows = _sys(graph).find_entities("content", {"type": LINK_RECORD,
                                                 "owner": graph.default_owner}, limit=50)
    return [{"link_id": r["id"], "created_at": r["attrs"].get("created_at", ""),
             "expires_at": r["attrs"].get("expires_at", ""),
             "revoked": bool(r["attrs"].get("revoked"))} for r in rows]


def revoke_link(graph: Graph, link_id: str, *, source: str = MODULE) -> dict:
    session = _sys(graph)
    row = session.get_entity(link_id)
    if not row or row["attrs"].get("type") != LINK_RECORD or \
            row["attrs"].get("owner") != graph.default_owner:
        raise CalendarError("no such link")
    session.update_entity(link_id, {"revoked": True}, source=source)
    return {"link_id": link_id, "revoked": True}


def owner_for(graph: Graph, token: str) -> str:
    """The owner a token opens, or "" — never a reason why not."""
    if not token:
        return ""
    for row in _sys(graph).find_entities("content", {"type": LINK_RECORD,
                                                     "token_hash": _hash(token)}, limit=1):
        a = row["attrs"]
        expires = _parse(a.get("expires_at"))
        if a.get("revoked") or not expires or expires < _now():
            return ""
        return a.get("owner", "")
    return ""


def feed(graph: Graph, token: str) -> str:
    """The ICS a calendar app receives. Empty for any token that does not open a calendar."""
    from modules.calendars import export

    owner = owner_for(graph, token)
    if not owner:
        return export.generate_ics([], calendar_name="LifeOS")
    mine = Graph(graph.conn, graph.bus, default_owner=owner).session(MODULE, SCOPES)
    events = [e for e in mine.find_entities("event", limit=2000)
              if e["attrs"].get("source") not in ("ics", IMPORTED)
              and e["attrs"].get("origin") != "feed"]
    return export.generate_ics(events, calendar_name="LifeOS")


# ---- in: your busy times ----------------------------------------------------------------

def _mask(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.hostname}/…{url[-4:]}"


def add_source(graph: Graph, url: str, *, keep_titles: bool = False, source: str = MODULE) -> dict:
    url = str(url or "").strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    if not url.lower().startswith("https://"):
        raise CalendarError("paste the calendar's secret https:// (or webcal://) address")
    try:
        safefetch.check_url(url)
    except Exception as exc:
        raise CalendarError(f"that address cannot be fetched from here: {exc}")
    session = graph.session(MODULE, SCOPES)
    rows = session.find_entities("content", {"type": SOURCE_RECORD}, limit=50)
    for r in rows:
        if r["attrs"].get("url") == url:
            return {"source_id": r["id"], "calendar": _mask(url), "created": False}
    if len(rows) >= MAX_SOURCES:
        raise CalendarError("that is a lot of calendars — remove one first")
    sid = session.create_entity("content", {
        "type": SOURCE_RECORD, "url": url, "keep_titles": bool(keep_titles),
        "created_at": now_iso(), "last_status": "never synced"}, source=source)
    return {"source_id": sid, "calendar": _mask(url), "created": True}


def sources(graph: Graph) -> list[dict]:
    rows = graph.session(MODULE, SCOPES).find_entities("content", {"type": SOURCE_RECORD}, limit=50)
    return [{"source_id": r["id"], "calendar": _mask(r["attrs"]["url"]),
             "keep_titles": bool(r["attrs"].get("keep_titles")),
             "last_status": r["attrs"].get("last_status", ""),
             "last_synced_at": r["attrs"].get("last_synced_at", "")} for r in rows]


def remove_source(graph: Graph, source_id: str, *, source: str = MODULE) -> dict:
    session = graph.session(MODULE, SCOPES)
    row = session.get_entity(source_id)
    if not row or row["attrs"].get("type") != SOURCE_RECORD:
        raise CalendarError("no such calendar")
    removed = 0
    for ev in session.find_entities("event", {"source": IMPORTED, "calendar_source": source_id},
                                    limit=5000):
        session.delete_entity(ev["id"], source=source)
        removed += 1
    session.delete_entity(source_id, source=source)
    return {"source_id": source_id, "removed": True, "busy_blocks_removed": removed}


def sync_source(graph: Graph, source_id: str, *, text: str | None = None,
                now: datetime.datetime | None = None, source: str = MODULE) -> dict:
    """Read one calendar into busy blocks for the next WINDOW_DAYS. Upstream deletions are
    removed here; titles are kept only if the source says so."""
    from modules.calendars.freebusy import parse_ics

    session = graph.session(MODULE, SCOPES)
    row = session.get_entity(source_id)
    if not row or row["attrs"].get("type") != SOURCE_RECORD:
        raise CalendarError("no such calendar")
    a = row["attrs"]
    if text is None:
        try:
            text = safefetch.fetch_text(a["url"])
        except Exception as exc:
            session.update_entity(source_id, {"last_status": f"fetch failed: {type(exc).__name__}",
                                              "last_synced_at": now_iso()}, source=source)
            return {"source_id": source_id, "status": "fetch_failed", "busy_blocks": 0}

    now = now or _now()
    lo = now - datetime.timedelta(days=WINDOW_PAST_DAYS)
    hi = now + datetime.timedelta(days=WINDOW_DAYS)
    seen, written = set(), 0
    for ev in parse_ics(text):
        start = _parse(ev["start"])
        if not start or not (lo <= start <= hi):
            continue
        key = f"{source_id}:{ev['uid']}:{ev['start']}"
        seen.add(key)
        attrs = {"source": IMPORTED, "calendar_source": source_id, "import_key": key,
                 "start": ev["start"], "end": ev["end"], "busy": True, "visibility": "private",
                 "title": ev.get("title", "") if a.get("keep_titles") else "Busy"}
        existing = session.find_entities("event", {"import_key": key}, limit=1)
        if existing:
            session.update_entity(existing[0]["id"], attrs, source=source)
        else:
            session.create_entity("event", attrs, source=source)
        written += 1
    removed = 0
    for ev in session.find_entities("event", {"source": IMPORTED, "calendar_source": source_id},
                                    limit=5000):
        if ev["attrs"].get("import_key") not in seen:
            session.delete_entity(ev["id"], source=source)
            removed += 1
    session.update_entity(source_id, {"last_status": f"ok: {written} busy blocks",
                                      "last_synced_at": now_iso()}, source=source)
    return {"source_id": source_id, "status": "ok", "busy_blocks": written, "removed": removed}


def sync_all(graph: Graph, *, source: str = MODULE) -> dict:
    """Every account's calendars — for the refresh loop."""
    everyone = Graph(graph.conn, graph.bus, default_owner=None)
    rows = everyone.session(MODULE, SCOPES).find_entities("content", {"type": SOURCE_RECORD},
                                                          limit=5000)
    results = []
    for row in rows:
        owner = Graph(graph.conn, graph.bus, default_owner=row["owner_id"])
        try:
            results.append(sync_source(owner, row["id"], source=source))
        except Exception as exc:
            results.append({"source_id": row["id"], "status": f"error: {type(exc).__name__}"})
    return {"calendars": len(rows), "ok": sum(1 for r in results if r.get("status") == "ok"),
            "results": results}
