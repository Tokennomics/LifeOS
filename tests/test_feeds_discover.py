"""Finding a venue's calendar feed from its website.

Tier 1 asked for a feed URL, and almost nobody knows their favourite bar's `.ics` link —
which made populating a city a page-source safari, i.e. a task that quietly never happens.
These cover the standard `<link rel="alternate">` mechanism plus the messiness of real
venue sites, which are not valid HTML and never will be.
"""

import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.feeds import discover, ingest

PAGE = """<!doctype html>
<html><head>
  <title>Lux Frágil</title>
  <link rel="alternate" type="application/rss+xml" title="Lux — blog" href="/blog/feed">
  <link rel="alternate" type="text/calendar" title="Lux — event calendar" href="/events.ics">
  <link rel="alternate" type="application/rss+xml" title="Comments" href="/comments/feed">
  <link rel="stylesheet" href="/style.css">
</head><body>
  <a href="/programme.rss">Programme feed</a>
  <a href="/about">About</a>
  <a href="javascript:void(0)">Menu</a>
</body></html>
"""


def _urls(candidates):
    return [c["url"] for c in candidates]


# ---- the standard mechanism --------------------------------------------------

def test_the_advertised_calendar_wins():
    """ICS beats RSS because it states when an event is; RSS only sometimes does."""
    found = discover.find_feeds(PAGE, base_url="https://lux.example/")
    assert found[0]["url"] == "https://lux.example/events.ics"
    assert found[0]["kind"] == "ics" and found[0]["advertised"] is True


def test_relative_hrefs_are_resolved_against_the_page():
    for url in _urls(discover.find_feeds(PAGE, base_url="https://lux.example/whats-on/")):
        assert url.startswith("https://lux.example/")


def test_the_blog_and_the_comments_rank_below_the_calendar():
    ranked = _urls(discover.find_feeds(PAGE, base_url="https://lux.example/"))
    assert ranked.index("https://lux.example/events.ics") < ranked.index(
        "https://lux.example/blog/feed")
    assert ranked[-1] == "https://lux.example/comments/feed", \
        "a comments feed is never the gig calendar"


def test_a_plain_link_on_the_page_is_found_too():
    """Plenty of venues link the feed in the footer and never touch the head."""
    assert "https://lux.example/programme.rss" in _urls(
        discover.find_feeds(PAGE, base_url="https://lux.example/"))


def test_non_feeds_are_ignored():
    found = _urls(discover.find_feeds(PAGE, base_url="https://lux.example/"))
    assert "https://lux.example/style.css" not in found
    assert "https://lux.example/about" not in found


@pytest.mark.parametrize("href", ["javascript:alert(1)", "data:text/xml,<rss/>",
                                  "mailto:x@y.z", "file:///etc/passwd"])
def test_only_http_urls_are_ever_returned(href):
    page = f'<link rel="alternate" type="application/rss+xml" href="{href}">'
    assert discover.find_feeds(page, base_url="https://lux.example/") == []


def test_duplicates_collapse():
    page = ('<link rel="alternate" type="text/calendar" href="/e.ics">'
            '<a href="/e.ics">cal</a><a href="https://lux.example/e.ics">cal</a>')
    assert len(discover.find_feeds(page, base_url="https://lux.example/")) == 1


def test_conventional_paths_count_as_feeds():
    page = '<a href="/feed">Feed</a><a href="/events/rss/">RSS</a><a href="/ical">iCal</a>'
    assert len(discover.find_feeds(page, base_url="https://v.example/")) == 3


@pytest.mark.parametrize("href,kind", [
    ("/whats-on?format=rss", "rss"),          # Squarespace
    ("/whats-on?format=ical", "ics"),
    ("/events/?ical=1", "ics"),               # The Events Calendar
    ("/?feed=rss2", "rss"),                   # WordPress
    ("/cal?output=ical", "ics"),
])
def test_feeds_selected_by_query_string_are_found(href, kind):
    """Found by simulation: a path-only check misses whole platforms. Squarespace links
    its feed as `?format=rss` from the footer with no type attribute at all."""
    page = f'<a href="{href}">Subscribe</a>'
    found = discover.find_feeds(page, base_url="https://v.example/")
    assert found and found[0]["kind"] == kind


@pytest.mark.parametrize("href", ["/search?q=rss", "/page?id=ical", "/x?format=json-ld",
                                  "/about?ref=feedly"])
def test_an_unrelated_query_string_is_not_mistaken_for_a_feed(href):
    assert discover.find_feeds(f'<a href="{href}">x</a>', base_url="https://v.example/") == []


# ---- real venue sites are not valid HTML -------------------------------------

@pytest.mark.parametrize("junk", [
    "", "   ", "not html at all", "<html><head><link rel=alternate",
    "<<<>>>", "<html><body><p>unclosed", "{\"json\": true}",
])
def test_a_broken_page_yields_nothing_rather_than_raising(junk):
    assert discover.find_feeds(junk, base_url="https://v.example/") == []


def test_unquoted_and_uppercase_attributes_still_parse():
    page = '<LINK REL="ALTERNATE" TYPE="TEXT/CALENDAR" HREF=/e.ics>'
    found = discover.find_feeds(page, base_url="https://v.example/")
    assert found and found[0]["kind"] == "ics"


def test_a_content_type_with_charset_is_handled():
    page = '<link rel="alternate" type="application/rss+xml; charset=utf-8" href="/f">'
    assert discover.find_feeds(page, base_url="https://v.example/")


def test_a_page_cannot_flood_the_candidate_list():
    page = "".join(f'<a href="/f{i}.ics">f</a>' for i in range(50))
    assert len(discover.find_feeds(page, base_url="https://v.example/")) == discover.MAX_CANDIDATES


# ---- someone who already has the link ----------------------------------------

@pytest.mark.parametrize("url,expected", [
    ("https://v.example/events.ics", True),
    ("https://v.example/e.ical", True),
    ("https://v.example/feed", True),
    ("https://v.example/blog.rss", True),
    ("https://v.example/", False),
    ("https://v.example/whats-on", False),
])
def test_a_url_that_is_already_a_feed_is_recognised(url, expected):
    assert discover.looks_like_feed_url(url) is expected


# ---- the graph flow ----------------------------------------------------------

def test_discovery_proposes_and_does_not_add(graph):
    """Same posture as the rest of the codebase: propose, and let the human pick."""
    result = ingest.discover_feeds(graph, "https://lux.example/", html=PAGE)
    assert result["status"] == "ok"
    assert result["candidates"][0]["url"] == "https://lux.example/events.ics"
    assert result["added"] is None
    assert ingest.feeds(graph) == []


def test_you_can_ask_it_to_add_the_top_candidate(graph):
    result = ingest.discover_feeds(graph, "https://lux.example/", html=PAGE, add=True,
                                   city="Lisbon", venue="Lux")
    assert result["added"]["url"] == "https://lux.example/events.ics"
    assert ingest.feeds(graph)[0]["venue"] == "Lux"


def test_the_venue_name_defaults_to_the_host(graph):
    ingest.discover_feeds(graph, "https://www.lux.example/whats-on", html=PAGE,
                          add=True, city="Lisbon")
    assert ingest.feeds(graph)[0]["venue"] == "lux.example"


def test_pasting_a_feed_url_skips_discovery_entirely(graph):
    result = ingest.discover_feeds(graph, "https://lux.example/events.ics")
    assert _urls(result["candidates"]) == ["https://lux.example/events.ics"]
    assert result["candidates"][0]["kind"] == "ics"


def test_a_dead_site_is_reported_not_raised(graph, monkeypatch):
    monkeypatch.setattr(ingest, "_fetch",
                        lambda url: (_ for _ in ()).throw(OSError("no route to host")))
    result = ingest.discover_feeds(graph, "https://gone.example/")
    assert result["candidates"] == [] and "fetch failed" in result["status"]


def test_a_page_with_no_feed_says_so_rather_than_guessing(graph):
    result = ingest.discover_feeds(graph, "https://plain.example/",
                                   html="<html><body>We post on Instagram</body></html>")
    assert result["status"] == "ok" and result["candidates"] == []
    assert result["added"] is None


@pytest.mark.parametrize("bad", ["", "lux.example", "ftp://lux.example/e.ics"])
def test_discovery_needs_a_real_url(graph, bad):
    with pytest.raises(ValueError):
        ingest.discover_feeds(graph, bad)


# ---- the gateway -------------------------------------------------------------

def test_the_endpoint_works(cfg):
    client = TestClient(create_app(cfg))
    r = client.post("/v1/feeds/discover",
                    json={"url": "https://lux.example/", "html": PAGE})
    assert r.status_code == 200
    assert r.json()["candidates"][0]["kind"] == "ics"
    assert r.json()["added"] is None
    assert client.get("/v1/feeds").json()["feeds"] == []


def test_the_endpoint_can_add_when_asked(cfg):
    client = TestClient(create_app(cfg))
    r = client.post("/v1/feeds/discover", json={
        "url": "https://lux.example/", "html": PAGE, "add": True,
        "city": "Lisbon", "venue": "Lux", "topic": "techno"})
    assert r.json()["added"]["added"] is True
    assert client.get("/v1/feeds").json()["feeds"][0]["topic"] == "techno"


def test_a_bad_url_is_a_400(cfg):
    client = TestClient(create_app(cfg))
    assert client.post("/v1/feeds/discover", json={"url": "nope"}).status_code == 400
