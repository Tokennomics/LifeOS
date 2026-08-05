"""Find a venue's calendar feed from its website — the pure part.

Tier 1 works, but it has an adoption problem: it asks for a feed URL, and almost nobody
knows their favourite bar's `.ics` link. Populating a city meant hunting through page
source, venue by venue, which is the kind of task that quietly never happens. Autodiscovery
turns "find the feed URL" into "paste the website".

The mechanism is the standard one, not a heuristic: browsers and readers have looked for
`<link rel="alternate" type="application/rss+xml">` in the document head since RSS existed,
and publishers put it there on purpose. Anything found that way is *advertised* by the site
as its feed, so reading it is exactly what it is for.

**Candidates are proposed, never added.** `discover` returns a ranked list and stops. That
matches how the rest of this codebase behaves — Reconnect drafts, Steward asks, the coach
proposes and accepting is the write — and it matters more here than usual, because a page
can advertise a dozen feeds and only the human knows which one is the gig calendar rather
than the blog.
"""

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

FEED_TYPES = {
    "text/calendar": "ics",
    "application/rss+xml": "rss",
    "application/atom+xml": "atom",
    "application/xml": "xml",
    "text/xml": "xml",
    "application/json": "json",
}
FEED_RELS = {"alternate", "feed", "calendar"}
FEED_SUFFIXES = (".ics", ".ical", ".rss", ".atom", ".xml")

# Words that suggest a feed is the EVENTS one rather than the blog. Ranking only; a feed
# is never excluded for lacking them, because plenty of venues just call it "calendar".
EVENTY = ("event", "calendar", "agenda", "gig", "programme", "program", "schedule",
          "whatson", "what-on", "shows", "lineup", "concert")
NOT_EVENTY = ("comment", "blog", "news", "press", "podcast", "job", "newsletter")

MAX_CANDIDATES = 12


class _Links(HTMLParser):
    """Collects <link> and <a> hrefs. Deliberately tolerant — venue sites are not valid
    HTML and a strict parser would find nothing on half the web."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[dict] = []
        self._depth_title = False

    def handle_starttag(self, tag, attrs):
        if tag not in ("link", "a"):
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        href = a.get("href", "").strip()
        if not href:
            return
        self.links.append({
            "tag": tag, "href": href,
            "rel": " ".join(a.get("rel", "").lower().split()),
            "type": a.get("type", "").split(";")[0].strip().lower(),
            "title": a.get("title", "").strip(),
        })


SUFFIX_KIND = {".ics": "ics", ".ical": "ics", ".rss": "rss", ".atom": "atom", ".xml": "xml"}

# Feeds selected by query string rather than path — Squarespace's `?format=rss`, The Events
# Calendar's `?ical=1`, WordPress's `?feed=rss2`. Missed by a path-only check, and common
# enough that missing them means missing whole platforms.
QUERY_KIND = {"rss": "rss", "rss2": "rss", "atom": "atom", "ical": "ics", "ics": "ics",
              "icalendar": "ics", "feed": "rss"}
QUERY_KEYS = ("format", "feed", "ical", "ics", "type", "output")


def _kind(link: dict) -> str:
    if link["type"] in FEED_TYPES:
        return FEED_TYPES[link["type"]]
    parsed = urlparse(link["href"])
    path = parsed.path.lower()
    for suffix in FEED_SUFFIXES:
        if path.endswith(suffix):
            return SUFFIX_KIND[suffix]
    if re.search(r"(^|/)(feed|rss|ical|ics|calendar\.ics)/?$", path):
        return "rss"
    return _query_kind(parsed.query)


def _query_kind(query: str) -> str:
    for pair in (query or "").lower().split("&"):
        key, _, value = pair.partition("=")
        if key not in QUERY_KEYS:
            continue
        if value in QUERY_KIND:
            return QUERY_KIND[value]
        # `?ical=1` names the format in the KEY and puts a flag in the value.
        if key in QUERY_KIND and value in ("1", "true", "yes", ""):
            return QUERY_KIND[key]
    return ""


def _score(link: dict, kind: str) -> float:
    """ICS beats RSS because it states when an event is; RSS only sometimes does."""
    score = {"ics": 3.0, "atom": 1.5, "rss": 1.5, "xml": 0.8, "json": 0.4}.get(kind, 0.0)
    if link["tag"] == "link" and link["rel"] in FEED_RELS:
        score += 1.0                     # advertised in the head, not just a link on the page
    haystack = f"{link['href']} {link['title']}".lower()
    if any(word in haystack for word in EVENTY):
        score += 1.5
    if any(word in haystack for word in NOT_EVENTY):
        score -= 2.0
    return round(score, 2)


def find_feeds(html: str, base_url: str = "") -> list[dict]:
    """Ranked feed candidates advertised by one page. Never raises."""
    parser = _Links()
    try:
        parser.feed(str(html or ""))
    except Exception:                    # a malformed page yields what it managed to yield
        pass

    seen, out = set(), []
    for link in parser.links:
        kind = _kind(link)
        if not kind:
            continue
        url = urljoin(base_url, link["href"]) if base_url else link["href"]
        if urlparse(url).scheme not in ("http", "https"):
            continue                     # javascript:, data:, mailto: are not feeds
        if url in seen:
            continue
        seen.add(url)
        out.append({"url": url, "kind": kind, "title": link["title"],
                    "advertised": link["tag"] == "link" and link["rel"] in FEED_RELS,
                    "score": _score(link, kind)})

    out.sort(key=lambda c: (-c["score"], c["url"]))
    return out[:MAX_CANDIDATES]


def looks_like_feed_url(url: str) -> bool:
    """Someone who already has the .ics link should not be made to paste a homepage."""
    path = urlparse(str(url or "")).path.lower()
    return path.endswith(FEED_SUFFIXES) or bool(
        re.search(r"(^|/)(feed|rss|ical|ics)/?$", path))
