"""City seed packs — loading, validating, and refusing to trust junk."""

import json

import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from modules.feeds import ingest, seeds

PAGE = """<html><head>
<link rel="alternate" type="text/calendar" title="Events" href="/events.ics">
</head></html>"""


@pytest.fixture
def packs(tmp_path):
    (tmp_path / "lisbon.json").write_text(json.dumps({
        "city": "Lisbon", "note": "test pack",
        "venues": [
            {"url": "https://lux.example/", "venue": "Lux", "topic": "techno"},
            {"url": "https://gal.example/whats-on", "venue": "Galeria", "topic": "art"},
            {"url": "https://direct.example/e.ics", "venue": "Direct"},
        ]}), encoding="utf-8")
    return tmp_path


@pytest.fixture
def offline(monkeypatch):
    """Discovery must not touch the network in tests — every venue serves the same page."""
    monkeypatch.setattr(ingest, "_fetch", lambda url: PAGE)


# ---- reading a pack ----------------------------------------------------------

def test_a_pack_loads_with_its_venues(packs):
    pack = seeds.load("lisbon", directory=packs)
    assert pack["city"] == "Lisbon" and len(pack["venues"]) == 3
    assert pack["venues"][0]["venue"] == "Lux"


@pytest.mark.parametrize("asked", ["lisbon", "Lisbon", "LISBON", " lisbon "])
def test_the_city_name_is_slugged(packs, asked):
    assert seeds.load(asked, directory=packs)["slug"] == "lisbon"


def test_a_two_word_city_becomes_a_hyphenated_slug(tmp_path):
    (tmp_path / "new-york.json").write_text(json.dumps({
        "city": "New York", "venues": [{"url": "https://a.example/"}]}), encoding="utf-8")
    assert seeds.load("New York", directory=tmp_path)["city"] == "New York"


def test_available_lists_every_pack(packs):
    listed = seeds.available(directory=packs)
    assert [p["slug"] for p in listed] == ["lisbon"]
    assert listed[0]["venues"] == 3 and listed[0]["note"] == "test pack"


def test_the_committed_example_pack_is_valid():
    """The format file has to actually parse, or it documents nothing."""
    pack = seeds.load("example")
    assert pack["venues"] and all(v["url"].startswith("http") for v in pack["venues"])


def test_no_invented_city_packs_are_committed():
    """A pack of guessed URLs is a list of 404s that reads as 'this feature is broken'
    rather than 'this city is unseeded'. See seeds/README.md."""
    assert [p["slug"] for p in seeds.available()] == ["example"]


# ---- refusing junk -----------------------------------------------------------

def test_an_unknown_city_is_an_error_not_an_empty_pack(packs):
    with pytest.raises(seeds.SeedError):
        seeds.load("berlin", directory=packs)


def test_a_pack_that_is_not_json_is_refused(tmp_path):
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(seeds.SeedError, match="valid JSON"):
        seeds.load("broken", directory=tmp_path)


def test_a_pack_with_no_usable_venues_is_refused(tmp_path):
    (tmp_path / "empty.json").write_text(json.dumps({
        "city": "Empty", "venues": [{"url": "ftp://x"}, {"nope": 1}, "string"]}),
        encoding="utf-8")
    with pytest.raises(seeds.SeedError, match="no usable venues"):
        seeds.load("empty", directory=tmp_path)


def test_duplicate_urls_collapse(tmp_path):
    (tmp_path / "dup.json").write_text(json.dumps({"city": "D", "venues": [
        {"url": "https://a.example/"}, {"url": "https://a.example/"}]}), encoding="utf-8")
    assert len(seeds.load("dup", directory=tmp_path)["venues"]) == 1


def test_a_pack_cannot_be_unbounded(tmp_path):
    (tmp_path / "big.json").write_text(json.dumps({"city": "B", "venues": [
        {"url": f"https://v{i}.example/"} for i in range(seeds.MAX_VENUES + 40)]}),
        encoding="utf-8")
    assert len(seeds.load("big", directory=tmp_path)["venues"]) == seeds.MAX_VENUES


@pytest.mark.parametrize("nasty", ["../secrets", "..%2Fsecrets", "/etc/passwd",
                                   "lisbon/../../etc/passwd"])
def test_a_crafted_city_cannot_walk_out_of_the_seeds_directory(packs, nasty):
    with pytest.raises(seeds.SeedError):
        seeds.load(nasty, directory=packs)


def test_a_broken_pack_does_not_hide_the_good_ones(packs):
    (packs / "broken.json").write_text("{{{", encoding="utf-8")
    assert [p["slug"] for p in seeds.available(directory=packs)] == ["lisbon"]


# ---- applying a pack ---------------------------------------------------------

def test_applying_a_pack_subscribes_to_every_venue(graph, packs, offline):
    result = seeds.apply(graph, "lisbon", directory=packs)
    assert len(result["added"]) == 3 and result["failed"] == []
    assert {f["venue"] for f in ingest.feeds(graph)} == {"Lux", "Galeria", "Direct"}


def test_a_website_is_resolved_to_its_feed(graph, packs, offline):
    """Packs hold websites, not feed URLs — nobody knows their favourite bar's .ics link."""
    seeds.apply(graph, "lisbon", directory=packs)
    urls = {f["url"] for f in ingest.feeds(graph)}
    assert "https://lux.example/events.ics" in urls
    assert "https://lux.example/" not in urls


def test_an_entry_that_is_already_a_feed_url_is_used_as_is(graph, packs, offline):
    seeds.apply(graph, "lisbon", directory=packs)
    assert "https://direct.example/e.ics" in {f["url"] for f in ingest.feeds(graph)}


def test_applying_twice_is_a_no_op(graph, packs, offline):
    seeds.apply(graph, "lisbon", directory=packs)
    again = seeds.apply(graph, "lisbon", directory=packs)
    assert again["added"] == [] and len(again["already_had"]) == 3
    assert len(ingest.feeds(graph)) == 3


def test_one_dead_venue_does_not_cost_the_other_forty(graph, packs, monkeypatch):
    def fetch(url):
        if "gal" in url:
            raise OSError("no route to host")
        return PAGE
    monkeypatch.setattr(ingest, "_fetch", fetch)

    result = seeds.apply(graph, "lisbon", directory=packs)
    assert len(result["added"]) == 2
    assert [f["url"] for f in result["failed"]] == ["https://gal.example/whats-on"]


def test_a_venue_advertising_no_feed_is_reported_not_silently_dropped(graph, packs,
                                                                     monkeypatch):
    monkeypatch.setattr(ingest, "_fetch", lambda url: "<html>Follow us on Instagram</html>")
    result = seeds.apply(graph, "lisbon", directory=packs)
    assert "no feed advertised" in {f["reason"] for f in result["failed"]}


def test_applying_can_sync_straight_away(graph, packs, monkeypatch):
    ics = ("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:a\nSUMMARY:Night\n"
           "DTSTART:20260807T230000Z\nDTEND:20260808T060000Z\nEND:VEVENT\nEND:VCALENDAR\n")
    monkeypatch.setattr(ingest, "_fetch", lambda url: PAGE if url.endswith("/") or
                        "whats-on" in url else ics)
    result = seeds.apply(graph, "lisbon", directory=packs, sync=True)
    assert result["sync"]["added"] >= 1


# ---- the gateway -------------------------------------------------------------

def test_the_endpoints_work(cfg):
    client = TestClient(create_app(cfg))
    packs = client.get("/v1/feeds/seeds").json()["packs"]
    assert [p["slug"] for p in packs] == ["example"]
    assert client.post("/v1/feeds/seeds/nowhere", json={}).status_code == 400


# ---- seeding on boot ---------------------------------------------------------

def test_boot_seeding_is_off_unless_asked(cfg, monkeypatch):
    from gateway import main
    monkeypatch.delenv(main.SEED_CITY_VAR, raising=False)
    client = TestClient(main.create_app(cfg))
    assert client.get("/v1/feeds").json()["feeds"] == []


def test_boot_seeding_loads_a_pack(cfg, monkeypatch, tmp_path):
    """An empty app loses a new user in the first ten seconds, and asking them to paste
    twenty venue websites first is not an onboarding flow."""
    from gateway import main
    monkeypatch.setattr(seeds, "SEEDS_DIR", tmp_path)
    (tmp_path / "lisbon.json").write_text(json.dumps({"city": "Lisbon", "venues": [
        {"url": "https://lux.example/e.ics", "venue": "Lux"},
        {"url": "https://gal.example/f.ics", "venue": "Galeria"}]}), encoding="utf-8")
    monkeypatch.setenv(main.SEED_CITY_VAR, "lisbon")

    client = TestClient(main.create_app(cfg))
    feeds = client.get("/v1/feeds").json()["feeds"]
    assert {f["venue"] for f in feeds} == {"Lux", "Galeria"}


def test_boot_seeding_does_not_fetch(cfg, monkeypatch, tmp_path):
    """A boot that waits on twenty venue servers is a boot that fails its health check."""
    from gateway import main
    monkeypatch.setattr(seeds, "SEEDS_DIR", tmp_path)
    (tmp_path / "lisbon.json").write_text(json.dumps({"city": "Lisbon", "venues": [
        {"url": "https://lux.example/e.ics"}]}), encoding="utf-8")
    monkeypatch.setenv(main.SEED_CITY_VAR, "lisbon")
    monkeypatch.setattr(ingest, "_fetch",
                        lambda url: pytest.fail("boot must not fetch a feed"))
    assert TestClient(main.create_app(cfg)).get("/v1/feeds").status_code == 200


def test_a_bad_pack_never_stops_the_gateway_starting(cfg, monkeypatch, tmp_path):
    from gateway import main
    monkeypatch.setattr(seeds, "SEEDS_DIR", tmp_path)
    (tmp_path / "broken.json").write_text("{{{ not json", encoding="utf-8")
    monkeypatch.setenv(main.SEED_CITY_VAR, "broken")
    assert TestClient(main.create_app(cfg)).get("/health").status_code == 200


def test_seeding_twice_does_not_double_the_city(cfg, monkeypatch, tmp_path):
    from gateway import main
    monkeypatch.setattr(seeds, "SEEDS_DIR", tmp_path)
    (tmp_path / "lisbon.json").write_text(json.dumps({"city": "Lisbon", "venues": [
        {"url": "https://lux.example/e.ics", "venue": "Lux"}]}), encoding="utf-8")
    monkeypatch.setenv(main.SEED_CITY_VAR, "lisbon")
    first = TestClient(main.create_app(cfg))
    TestClient(main.create_app(cfg))          # a redeploy re-runs create_app
    assert len(first.get("/v1/feeds").json()["feeds"]) == 1
