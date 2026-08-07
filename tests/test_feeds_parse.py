"""Parsing one venue feed — pure, no network.

The load-bearing case is the last section: RSS `pubDate` must never become an event date.
"""

import pytest

from modules.feeds import parse

ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:lux-2026-08-07
SUMMARY:Warehouse party
DTSTART:20260807T230000Z
DTEND:20260808T060000Z
LOCATION:Lux Frágil\\, Cais do Sodré
URL:https://lux.example/e/1
DESCRIPTION:Techno all night\\nDoors 23:00
END:VEVENT
BEGIN:VEVENT
UID:lux-2026-08-09
SUMMARY:Sunday session
DTSTART;VALUE=DATE:20260809
DTEND;VALUE=DATE:20260810
END:VEVENT
END:VCALENDAR
"""

RSS = """<?xml version="1.0"?>
<rss version="2.0" xmlns:ev="http://purl.org/rss/1.0/modules/event/">
  <channel>
    <item>
      <title>Sushi night</title>
      <link>https://venue.example/sushi</link>
      <pubDate>Tue, 04 Aug 2026 09:00:00 GMT</pubDate>
      <ev:startdate>2026-08-08T20:00</ev:startdate>
      <location>Bairro Alto</location>
    </item>
    <item>
      <title>Climb 2026-08-09T10:00</title>
      <link>https://venue.example/climb</link>
      <pubDate>Mon, 03 Aug 2026 09:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Some announcement with no date at all</title>
      <link>https://venue.example/news</link>
      <pubDate>Mon, 03 Aug 2026 09:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Gallery opening</title>
    <link href="https://gal.example/open"/>
    <id>tag:gal.example,2026:1</id>
    <updated>2026-08-01T12:00:00Z</updated>
    <summary>Opens 2026-08-08T18:30 at the old foundry</summary>
  </entry>
</feed>
"""


# ---- ICS ---------------------------------------------------------------------

def test_ics_events_come_through_with_place_and_url():
    items = parse.parse_feed(ICS)
    assert len(items) == 2
    first = items[0]
    assert first["title"] == "Warehouse party"
    assert first["start"].startswith("2026-08-07T23:00")
    assert first["place"] == "Lux Frágil, Cais do Sodré", "RFC 5545 escapes must be undone"
    assert first["url"] == "https://lux.example/e/1"
    assert first["format"] == "ics"


def test_an_all_day_ics_event_still_lands():
    assert parse.parse_feed(ICS)[1]["start"].startswith("2026-08-09")


def test_ics_is_detected_without_being_told():
    assert parse.looks_like_ics(ICS) is True
    assert parse.looks_like_ics(RSS) is False


# ---- RSS / Atom --------------------------------------------------------------

def test_an_explicit_event_start_element_wins():
    sushi = [i for i in parse.parse_feed(RSS) if i["title"] == "Sushi night"][0]
    assert sushi["start"] == "2026-08-08T20:00"
    assert sushi["place"] == "Bairro Alto"
    assert sushi["format"] == "rss"


def test_an_iso_date_in_the_title_is_used_when_there_is_no_element():
    climb = [i for i in parse.parse_feed(RSS) if i["title"].startswith("Climb")][0]
    assert climb["start"] == "2026-08-09T10:00"


def test_a_date_lifted_out_of_the_title_is_taken_off_the_title():
    """Found by reading the digest, not by a test: `Late tour 2026-08-09T21:00` reads like
    a machine wrote it, because one did."""
    climb = [i for i in parse.parse_feed(RSS) if i["title"].startswith("Climb")][0]
    assert climb["title"] == "Climb"


@pytest.mark.parametrize("raw,clean", [
    ("Late tour 2026-08-09T21:00", "Late tour"),
    ("Late tour - 2026-08-09", "Late tour"),
    ("Late tour — 2026-08-09T21:00", "Late tour"),
    ("2026-08-09: Late tour", "Late tour"),
    ("Late 2026-08-09 tour", "Late tour"),
])
def test_the_gap_the_date_left_is_closed(raw, clean):
    feed = f"""<rss><channel><item><title>{raw}</title><link>x</link></item></channel></rss>"""
    assert parse.parse_feed(feed)[0]["title"] == clean


def test_a_title_with_no_date_is_left_alone():
    feed = """<rss><channel><item><title>Nina Kraviz</title><link>x</link>
    <ev:startdate xmlns:ev="e">2026-08-07T23:30</ev:startdate></item></channel></rss>"""
    item = parse.parse_feed(feed)[0]
    assert item["title"] == "Nina Kraviz" and item["start"] == "2026-08-07T23:30"


def test_atom_entries_and_href_links_work():
    items = parse.parse_feed(ATOM)
    assert len(items) == 1
    assert items[0]["start"] == "2026-08-08T18:30"
    assert items[0]["url"] == "https://gal.example/open"


def test_markup_is_stripped_out_of_titles():
    feed = """<rss><channel><item><title>&lt;b&gt;Loud&lt;/b&gt;   night</title>
    <ev:start xmlns:ev="x">2026-08-08</ev:start></item></channel></rss>"""
    assert parse.parse_feed(feed)[0]["title"] == "Loud night"


# ---- the refusal that matters ------------------------------------------------

def test_pubdate_is_never_used_as_an_event_date():
    """RSS `pubDate` is when the listing was POSTED. Treating it as the event date files
    'Warehouse party' under the Tuesday it was announced — confidently, on the wrong day,
    with no way for a reader to tell. Dropping it is visible; a wrong date is not."""
    dateless = [i for i in parse.parse_feed(RSS) if i["title"].startswith("Some announcement")]
    assert len(dateless) == 1
    assert dateless[0]["start"] == ""
    assert dateless[0]["skipped"] == "no_date"
    assert "2026-08-04" not in str(dateless[0]), "the pubDate must not have leaked in"


def test_an_ambiguous_date_format_is_not_guessed_at():
    """08/07/2026 is the 8th of July to half the world and the 7th of August to the other
    half. An aggregator that guesses is the thing this module must not become."""
    feed = """<rss><channel><item><title>Party 08/07/2026</title>
    <link>x</link></item></channel></rss>"""
    assert parse.parse_feed(feed)[0]["start"] == ""


# ---- a feed must not be able to take the sync down ---------------------------

@pytest.mark.parametrize("junk", ["", "   ", "not xml at all", "<rss><unclosed>",
                                  "<html><body>502 Bad Gateway</body></html>"])
def test_unparseable_input_is_an_empty_list_not_an_exception(junk):
    assert parse.parse_feed(junk) == []


def test_a_broken_vevent_does_not_lose_the_good_ones():
    broken = ICS.replace("DTSTART:20260807T230000Z", "DTSTART:whenever")
    assert [i["title"] for i in parse.parse_feed(broken)] == ["Sunday session"]
