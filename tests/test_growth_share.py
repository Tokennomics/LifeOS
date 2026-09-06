"""Sharing, pairing and being early.

Every prop in this family returned a URL on `connectos.app` — a host this deployment does
not serve — for a resource nothing ever created: an invite code that was the same string on
every instance, a 1080x1920 PNG nothing rendered, and a "City Pioneer #042" badge carrying a
year of free VIP. `/nfc/tap-to-synergy` was the worst of them: 94% compatibility with a
named stranger and three shared passions, for any peer string, over a protocol a web app
cannot speak.

The assertions that matter: no invented rewards, no invented host, and no score.
"""

import datetime

import pytest

from gateway import accounts
from modules.city import synergy
from modules.growth import share

PW = "correct-horse-battery"


@pytest.fixture
def people(graph):
    return {name: accounts.register(graph, name, PW)["account_id"]
            for name in ("ana", "bo", "cy")}


# ---- being early -------------------------------------------------------------

def test_your_position_is_counted_from_real_rows(graph, people):
    synergy.open_to(graph, "Lisbon", "bouldering", account_id=people["ana"], handle="ana")
    synergy.open_to(graph, "Lisbon", "coffee", account_id=people["bo"], handle="bo")

    first = share.standing(graph, "Lisbon", account_id=people["ana"])
    assert first["your_position"] == 1
    assert first["people_here"] == 2

    second = share.standing(graph, "Lisbon", account_id=people["bo"])
    assert second["your_position"] == 2


def test_somebody_who_has_done_nothing_here_is_not_in_the_count(graph, people):
    synergy.open_to(graph, "Lisbon", "bouldering", account_id=people["ana"])
    out = share.standing(graph, "Lisbon", account_id=people["cy"])
    assert out["your_position"] is None
    assert out["you_are_here"] is False
    assert out["note"]


def test_being_early_unlocks_nothing(graph, people):
    """It minted a year of free VIP and complimentary coffee at partner roasters — perks
    nobody had agreed to provide."""
    synergy.open_to(graph, "Lisbon", "bouldering", account_id=people["ana"])
    out = share.standing(graph, "Lisbon", account_id=people["ana"])
    assert out["no_perks"]
    text = str(out).lower()
    for invented in ("vip", "voucher", "perks unlocked", "badge", "minted", "connectos.app"):
        assert invented not in text


def test_a_city_is_required(graph, people):
    with pytest.raises(share.ShareError):
        share.standing(graph, "", account_id=people["ana"])


# ---- the share card ----------------------------------------------------------

def test_the_card_is_an_image_this_process_actually_draws(graph):
    out = share.card("Sunset at the miradouro", subtitle="Lisbon", link="/invite/abc")
    assert out["rendered_here"] is True
    assert out["svg"].startswith("<svg")
    assert "1080" in out["svg"] and "/invite/abc" in out["svg"]
    assert "connectos.app" not in str(out)
    assert ".png" not in str(out)


def test_the_card_escapes_its_title(graph):
    """A title is user input and an SVG is markup."""
    out = share.card('</text><script>alert(1)</script>', subtitle="&<>")
    assert "<script>" not in out["svg"]
    assert "&lt;" in out["svg"] or "&amp;" in out["svg"]


def test_a_card_needs_a_title(graph):
    with pytest.raises(share.ShareError):
        share.card("")


def test_the_card_claims_no_qr(graph):
    """It advertised an "embedded QR code" at a second URL that was never rendered, and
    encoding one needs a library this app does not carry."""
    out = share.card("A night out")
    assert out["qr"] is None


# ---- pairing -----------------------------------------------------------------

def test_a_code_pairs_two_real_accounts(graph, people):
    shown = share.open_code(graph, account_id=people["ana"], handle="ana")
    assert len(shown["code"]) == share.CODE_LENGTH

    out = share.redeem_code(graph, shown["code"], account_id=people["bo"], handle="bo")
    assert out["paired"] is True
    assert out["peer_account"] == people["ana"]
    assert out["peer_handle"] == "ana"


def test_pairing_reports_no_score(graph, people):
    """94% compatibility, for any peer string, was the same number for everybody."""
    shown = share.open_code(graph, account_id=people["ana"], handle="ana")
    out = share.redeem_code(graph, shown["code"], account_id=people["bo"])
    assert out["no_score"]
    # No field carries a rating, and what two people have in common is a list of things
    # they both said — never a number. (The disclaimer text names the old 94%, so this
    # checks the shape of the answer rather than searching the prose for digits.)
    assert not [k for k in out if "score" in k and k != "no_score"]
    assert not [k for k in out if "compat" in k or "percent" in k]
    assert isinstance(out["shared"], list)
    assert not any(isinstance(v, (int, float)) and not isinstance(v, bool)
                   for v in out.values())
    # And the code that opened it does not claim a protocol this app cannot speak.
    assert "cannot speak NFC" in shown["no_nfc"]


def test_shared_ground_comes_from_what_both_published(graph, people):
    synergy.open_to(graph, "Lisbon", "bouldering and coffee", account_id=people["ana"])
    synergy.open_to(graph, "Porto", "coffee tasting", account_id=people["bo"])
    shown = share.open_code(graph, account_id=people["ana"], handle="ana")
    out = share.redeem_code(graph, shown["code"], account_id=people["bo"])
    assert out["shared"] == ["coffee"]


def test_two_strangers_share_nothing_and_it_says_so(graph, people):
    shown = share.open_code(graph, account_id=people["ana"])
    out = share.redeem_code(graph, shown["code"], account_id=people["bo"])
    assert out["shared"] == []


def test_a_code_works_once(graph, people):
    shown = share.open_code(graph, account_id=people["ana"])
    share.redeem_code(graph, shown["code"], account_id=people["bo"])
    with pytest.raises(share.ShareError, match="not valid"):
        share.redeem_code(graph, shown["code"], account_id=people["cy"])


def test_a_code_expires(graph, people, monkeypatch):
    shown = share.open_code(graph, account_id=people["ana"])
    later = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=share.CODE_MINUTES + 1)
    monkeypatch.setattr(share, "_now", lambda: later)
    with pytest.raises(share.ShareError, match="not valid"):
        share.redeem_code(graph, shown["code"], account_id=people["bo"])


def test_wrong_expired_and_used_are_indistinguishable(graph, people):
    """One message, so the six-character space cannot be probed for live codes."""
    shown = share.open_code(graph, account_id=people["ana"])
    share.redeem_code(graph, shown["code"], account_id=people["bo"])
    with pytest.raises(share.ShareError) as used:
        share.redeem_code(graph, shown["code"], account_id=people["cy"])
    with pytest.raises(share.ShareError) as never:
        share.redeem_code(graph, "ZZZZZZ", account_id=people["cy"])
    assert str(used.value) == str(never.value)


def test_you_cannot_pair_with_yourself(graph, people):
    shown = share.open_code(graph, account_id=people["ana"])
    with pytest.raises(share.ShareError, match="your own"):
        share.redeem_code(graph, shown["code"], account_id=people["ana"])


def test_showing_a_new_code_retires_the_old_one(graph, people):
    first = share.open_code(graph, account_id=people["ana"])
    share.open_code(graph, account_id=people["ana"])
    with pytest.raises(share.ShareError, match="not valid"):
        share.redeem_code(graph, first["code"], account_id=people["bo"])


def test_codes_avoid_characters_that_are_misread_aloud(graph, people):
    for _ in range(20):
        code = share.open_code(graph, account_id=people["ana"])["code"]
        assert not (set(code) & set("ILO01"))


def test_signing_in_is_required(graph):
    with pytest.raises(share.ShareError, match="sign in"):
        share.open_code(graph, account_id="")
    with pytest.raises(share.ShareError, match="sign in"):
        share.standing(graph, "Lisbon", account_id="")
