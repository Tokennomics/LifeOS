"""City seed packs — subscribe to a whole city's venues in one call.

The cold-start problem stated plainly: someone who downloads the app in Lisbon and sees an
empty weekend has no reason to open it again, and no amount of good architecture fixes that.
A seed pack is the list of venue websites for one city, committed to the repo, so arriving
somewhere that already has a pack means arriving to a populated weekend rather than to a
data-entry task.

**Packs hold websites, not feed URLs.** `discover` resolves the feed, because the entire
reason that exists is that nobody knows their favourite bar's `.ics` link. A pack a human
can assemble by copying addresses out of their browser is a pack that gets assembled; one
that needs page-source archaeology per venue is not.

**No real packs are committed yet, deliberately** — see `seeds/README.md`. Verifying a URL
requires reaching it, and a pack of guessed addresses is a list of 404s that would read as
"this feature is broken" rather than "this city is unseeded". The loader is here so that a
verified pack is a commit rather than a project.

Loading is subscription, not fetching: `apply` adds feeds and returns, unless asked to sync.
It never *removes* feeds that have dropped out of a pack, because unsubscribing is a
decision and not a side effect of an update.
"""

import json
import pathlib

from modules.feeds import ingest
from substrate import ROOT
from substrate.graph import Graph

MODULE = "feeds"
SEEDS_DIR = ROOT / "seeds"
MAX_VENUES = 200


class SeedError(ValueError):
    """A pack that cannot be trusted to be what it claims."""


def _slug(city: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in " -_" else "" for c in str(city or ""))
    return "-".join(cleaned.lower().split())[:60]


def available(directory: pathlib.Path | None = None) -> list[dict]:
    """Every pack on disk, with its city and how many venues it carries."""
    base = pathlib.Path(directory or SEEDS_DIR)
    if not base.is_dir():
        return []
    out = []
    for path in sorted(base.glob("*.json")):
        try:
            pack = load(path.stem, directory=base)
        except (SeedError, OSError):
            continue                    # a broken pack is not a reason to hide the good ones
        out.append({"slug": path.stem, "city": pack["city"],
                    "venues": len(pack["venues"]), "note": pack.get("note", "")})
    return out


def load(city: str, directory: pathlib.Path | None = None) -> dict:
    """Read and validate one pack. Raises `SeedError` rather than returning junk."""
    base = pathlib.Path(directory or SEEDS_DIR)
    path = base / f"{_slug(city)}.json"
    # `_slug` strips separators, so a crafted city cannot walk out of the seeds directory.
    if not path.is_file():
        raise SeedError(f"no seed pack for {city!r}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SeedError(f"{path.name} is not valid JSON: {exc}")
    if not isinstance(raw, dict):
        raise SeedError(f"{path.name} must be a JSON object")

    venues, seen = [], set()
    for entry in (raw.get("venues") or [])[:MAX_VENUES]:
        if not isinstance(entry, dict):
            continue
        url = str(entry.get("url") or "").strip()
        if not url.lower().startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        venues.append({"url": url, "venue": str(entry.get("venue") or "").strip()[:80],
                       "topic": str(entry.get("topic") or "").strip()[:40]})
    if not venues:
        raise SeedError(f"{path.name} lists no usable venues")
    return {"slug": _slug(city), "city": str(raw.get("city") or city).strip()[:60],
            "note": str(raw.get("note") or "").strip()[:300], "venues": venues}


def apply(graph: Graph, city: str, sync: bool = False, resolve: bool = True,
          directory: pathlib.Path | None = None, source: str = MODULE) -> dict:
    """Subscribe to every venue in a pack.

    `resolve=True` runs each website through `discover` to find its feed — the normal path,
    and the reason packs can hold plain addresses. `resolve=False` treats each entry as
    already being a feed URL, which is what an offline import wants.

    Nothing here raises on one bad venue: a pack is a long list assembled by a human, and
    one dead site must not cost the other forty.
    """
    pack = load(city, directory=directory)
    added, skipped, failed = [], [], []

    for entry in pack["venues"]:
        try:
            if resolve and not ingest.discover.looks_like_feed_url(entry["url"]):
                found = ingest.discover_feeds(
                    graph, entry["url"], add=True, city=pack["city"],
                    venue=entry["venue"], topic=entry["topic"], source=source)
                if not found.get("added"):
                    failed.append({"url": entry["url"],
                                   "reason": found.get("status") if found.get("status") != "ok"
                                   else "no feed advertised"})
                    continue
                result = found["added"]
            else:
                result = ingest.add_feed(graph, entry["url"], city=pack["city"],
                                         venue=entry["venue"], topic=entry["topic"],
                                         source=source)
            (added if result["added"] else skipped).append(result["url"])
        except Exception as exc:        # one dead venue must not cost the other forty
            failed.append({"url": entry["url"], "reason": f"{type(exc).__name__}: {exc}"})

    result = {"city": pack["city"], "slug": pack["slug"], "venues": len(pack["venues"]),
              "added": added, "already_had": skipped, "failed": failed}
    if sync:
        result["sync"] = ingest.sync_all(graph, source=source)
    return result
