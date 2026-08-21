"""A day's reflection, and taking your data with you.

`/journal/daily-reflection-synthesis` is the most brazen prop in the repo: it invented your
day. "Munich" got you dawn surfers on the Eisbach wave, sourdough pretzels with new local
friends, analog synths at Blitz Club, and gratitude to a man called Lukas for a speakeasy
passcode. A branch per city and nothing else — two people in the same city got the same
memories, and so did somebody who had spent the day in bed.

`/export/universal-markdown` reported 48 vault files and a `download_url` to a zip on
connectos.app that was never written. Nothing was exported, and somebody who clicked it
believed their data was safe. That one matters most: an export is the promise that using
this app is not a trap.
"""

import datetime

import pytest

from gateway import accounts
from modules.ai import reflect
from modules.personal import export, journal
from modules.social import signals

PW = "correct-horse-battery"

CITIES = ("munich", "münchen", "edinburgh", "eisbach", "blitz", "lukas",
          "typewronger", "arthur's seat", "monopteros", "obatzda", "pretzel")


@pytest.fixture
def account(graph):
    return accounts.register(graph, "ana", PW)["account_id"]


# ---- the reflection ----------------------------------------------------------

def test_a_day_with_nothing_in_it_says_so(graph, account):
    """It used to hand you three things you had done and a paragraph of travel writing."""
    out = journal.day(graph, account_id=account)
    assert out["empty"] is True
    assert out["did"] == [] and out["notes"] == []
    assert out["suggestion"]
    assert out["summary"] == ""


def test_a_city_no_longer_conjures_a_day(graph, account):
    """The whole prop was a branch on the city name. Passing one changes nothing now,
    because where you are does not tell anybody what they did."""
    out = journal.day(graph, account_id=account)
    text = str(out).lower()
    for invented in CITIES:
        assert invented not in text


def test_it_reads_what_you_actually_did(graph, account):
    signals.check_in(graph, account_id=account, place="Fabrica")
    reflect.log(graph, "slept badly, walked anyway")
    out = journal.day(graph, account_id=account)
    assert out["empty"] is False
    assert any("Fabrica" in line for line in out["did"])
    assert out["notes"] == ["slept badly, walked anyway"]
    assert "1 thing recorded" in out["summary"]


def test_every_line_points_at_a_row(graph, account):
    signals.check_in(graph, account_id=account, place="Fabrica")
    reflect.log(graph, "a note")
    out = journal.day(graph, account_id=account)
    kinds = {s["kind"] for s in out["sources"]}
    assert kinds == {"check-in", "reflection"}
    assert all(s["id"] for s in out["sources"])


def test_a_day_carries_no_score(graph, account):
    """The old export's frontmatter had `presence_score: 98.5%`."""
    signals.check_in(graph, account_id=account, place="Fabrica")
    out = journal.day(graph, account_id=account)
    assert out["no_score"]
    assert not [k for k in out if "score" in k and k != "no_score"]


def test_yesterday_is_not_today(graph, account):
    signals.check_in(graph, account_id=account, place="Fabrica")
    yesterday = (datetime.datetime.now(datetime.timezone.utc)
                 - datetime.timedelta(days=1)).date().isoformat()
    assert journal.day(graph, account_id=account, date=yesterday)["empty"] is True


def test_a_date_has_to_be_a_date(graph, account):
    with pytest.raises(journal.JournalError, match="2026-08-15"):
        journal.day(graph, account_id=account, date="last tuesday")


def test_the_week_view_skips_empty_days(graph, account):
    signals.check_in(graph, account_id=account, place="Fabrica")
    out = journal.week(graph, account_id=account, days=7)
    assert len(out["entries"]) == 1
    assert out["empty"] is False


def test_the_reflection_says_whether_a_model_wrote_it(graph, account):
    out = journal.day(graph, account_id=account)
    assert out["assisted"] is False        # no ANTHROPIC_API_KEY in tests
    assert out["reason"]


# ---- the export --------------------------------------------------------------

def test_an_empty_account_exports_an_empty_export(graph, account):
    """It reported 48 files and a zip on a host this deployment does not serve."""
    out = export.markdown(graph, account_id=account)
    assert out["download_url"] is None
    assert out["rows"] == 0
    assert "index.md" in out["documents"]
    assert "empty" in out["documents"]["index.md"]


def test_the_export_contains_your_actual_rows(graph, account):
    reflect.log(graph, "slept badly, walked anyway")
    signals.check_in(graph, account_id=account, place="Fabrica")
    out = export.markdown(graph, account_id=account)
    assert out["rows"] >= 2
    everything = "".join(out["documents"].values())
    assert "slept badly, walked anyway" in everything
    assert "Fabrica" in everything


def test_the_counts_are_counts(graph, account):
    reflect.log(graph, "one")
    reflect.log(graph, "two")
    out = export.markdown(graph, account_id=account)
    assert out["files"] == len(out["documents"])
    assert out["rows"] == sum(1 for _ in ("one", "two"))


def test_credentials_are_never_exported(graph, account):
    """An export is a file that ends up in a lot of places."""
    from gateway import accounts as acc
    acc.mint_session(graph, account)
    out = export.markdown(graph, account_id=account)
    everything = "".join(out["documents"].values()).lower()
    assert "token_hash" not in everything
    assert "password_hash" not in everything
    assert "auth_session" not in everything
    assert out["excluded_reason"]


def test_the_export_invents_no_vault(graph, account):
    out = export.markdown(graph, account_id=account)
    text = str(out).lower()
    for invented in ("connectos.app", ".zip", "presence_score", "trust index",
                     "speakeasy", "vinyl loft"):
        assert invented not in text


def test_it_is_markdown_a_reader_can_open(graph, account):
    reflect.log(graph, "a note")
    out = export.markdown(graph, account_id=account)
    doc = out["documents"]["Reflections.md"]
    assert doc.startswith("---\n")          # frontmatter
    assert "# Reflections" in doc
    assert "## a note" in doc


def test_pipes_and_newlines_in_content_do_not_break_the_document(graph, account):
    reflect.log(graph, "a | b\nsecond line")
    out = export.markdown(graph, account_id=account)
    doc = out["documents"]["Reflections.md"]
    assert "\\|" in doc
    # The note collapses to one line rather than injecting a heading mid-document.
    assert "\n## a \\| b second line" in doc


def test_the_single_file_form_holds_everything(graph, account):
    reflect.log(graph, "a note")
    signals.check_in(graph, account_id=account, place="Fabrica")
    text = export.as_single_file(graph, account_id=account)
    assert "a note" in text and "Fabrica" in text
    assert text.count("<!-- ") >= 2
