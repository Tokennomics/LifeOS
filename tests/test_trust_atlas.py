"""Vouches, places, and what a month contained.

`/trust/web-of-trust` was the most dangerous prop left. It returned `trust_verified: True`
and `trust_score: "98/100 (Tier-1 Community Vouched)"` for any name you sent, with a
vouching chain naming people who do not exist and a `privacy_standard` of "Zero-Knowledge
Proof" describing a scheme implemented nowhere. Somebody who reads that about a stranger
meets them differently — same failure mode as SafeWalk telling you your crew was watching.

`/atlas/living-memory-map` reported 48 pins and a time capsule counting down 342 days to a
place you had never been. `/vitals/social-wellness` reported a flourishing score of 92 on an
account created a second earlier.
"""

import pytest

from gateway import accounts
from modules.personal import atlas
from modules.social import signals, trust

PW = "correct-horse-battery"
INVENTED = ("98/100", "tier-1", "zero-knowledge", "community_verified",
            "calton hill", "eisbachwelle", "catriona", "time-capsule", "342",
            "flourishing", "deep_connection", "screen time")


@pytest.fixture
def people(graph):
    return {name: accounts.register(graph, name, PW)["account_id"]
            for name in ("ana", "bo", "cy")}


# ---- vouches -----------------------------------------------------------------

def test_a_vouch_is_a_named_person_saying_they_know_you(graph, people):
    trust.vouch(graph, account_id=people["ana"], for_account=people["bo"],
                handle="ana", note="climbed together for two years")
    out = trust.about(graph, account_id=people["cy"], subject=people["bo"])
    assert out["count"] == 1
    assert out["vouchers"][0]["handle"] == "ana"
    assert out["vouchers"][0]["note"] == "climbed together for two years"


def test_nothing_is_scored_or_verified(graph, people):
    """It said 98/100 and "community verified" about everybody, including a stranger you
    had just typed in."""
    trust.vouch(graph, account_id=people["ana"], for_account=people["bo"])
    out = trust.about(graph, account_id=people["cy"], subject=people["bo"])
    assert out["no_score"] is True
    assert out["verified"] is False
    assert out["disclaimer"]
    text = str(out).lower()
    for invented in INVENTED:
        assert invented not in text


def test_somebody_with_no_vouches_is_not_a_red_flag(graph, people):
    out = trust.about(graph, account_id=people["ana"], subject=people["bo"])
    assert out["count"] == 0
    assert out["empty"] is True
    assert "not a red flag" in out["suggestion"]


def test_you_cannot_vouch_for_yourself(graph, people):
    with pytest.raises(trust.TrustError, match="yourself"):
        trust.vouch(graph, account_id=people["ana"], for_account=people["ana"])


def test_vouching_twice_does_not_double_the_count(graph, people):
    """A count of vouches has to be a count of people, not a count of clicks."""
    trust.vouch(graph, account_id=people["ana"], for_account=people["bo"], note="one")
    out = trust.vouch(graph, account_id=people["ana"], for_account=people["bo"],
                      note="two")
    assert out["already"] is True
    about = trust.about(graph, account_id=people["cy"], subject=people["bo"])
    assert about["count"] == 1
    assert about["vouchers"][0]["note"] == "two"


def test_a_vouch_can_be_withdrawn(graph, people):
    """One that cannot be taken back is one nobody should give."""
    trust.vouch(graph, account_id=people["ana"], for_account=people["bo"])
    trust.withdraw(graph, account_id=people["ana"], for_account=people["bo"])
    assert trust.about(graph, account_id=people["cy"],
                       subject=people["bo"])["empty"] is True


def test_withdrawing_one_you_never_gave(graph, people):
    with pytest.raises(trust.TrustError, match="not vouched"):
        trust.withdraw(graph, account_id=people["ana"], for_account=people["bo"])


def test_you_can_see_whether_you_are_among_them(graph, people):
    trust.vouch(graph, account_id=people["ana"], for_account=people["bo"])
    assert trust.about(graph, account_id=people["ana"],
                       subject=people["bo"])["you_vouched"] is True
    assert trust.about(graph, account_id=people["cy"],
                       subject=people["bo"])["you_vouched"] is False


def test_people_in_common_are_computed_not_asserted(graph, people):
    """It claimed "3 Mutual Friends in ConnectOS Web of Trust" for any pair."""
    trust.vouch(graph, account_id=people["cy"], for_account=people["ana"])
    trust.vouch(graph, account_id=people["cy"], for_account=people["bo"])
    out = trust.in_common(graph, account_id=people["ana"], subject=people["bo"])
    assert out["in_common"] == [people["cy"]]
    assert out["count"] == 1


def test_usually_nobody_is_in_common(graph, people):
    out = trust.in_common(graph, account_id=people["ana"], subject=people["bo"])
    assert out["count"] == 0


def test_vouches_you_gave_are_listed(graph, people):
    trust.vouch(graph, account_id=people["ana"], for_account=people["bo"])
    out = trust.given(graph, account_id=people["ana"])
    assert [v["for_account"] for v in out["given"]] == [people["bo"]]


# ---- the atlas ---------------------------------------------------------------

def test_an_empty_atlas_is_empty(graph, people):
    """It reported 48 pins and three memories in three cities, on any account."""
    out = atlas.pins(graph, account_id=people["ana"])
    assert out["empty"] is True and out["count"] == 0
    text = str(out).lower()
    for invented in INVENTED:
        assert invented not in text


def test_pins_come_from_your_check_ins(graph, people):
    signals.check_in(graph, account_id=people["ana"], place="Fabrica", city="Lisbon")
    out = atlas.pins(graph, account_id=people["ana"])
    assert out["count"] == 1
    assert out["pins"][0]["place"] == "Fabrica"
    assert out["cities"] == ["lisbon"]


def test_going_back_to_a_place_is_one_pin_with_two_memories(graph, people):
    signals.check_in(graph, account_id=people["ana"], place="Fabrica", city="Lisbon")
    signals.check_in(graph, account_id=people["ana"], place="Fabrica", city="Lisbon")
    out = atlas.pins(graph, account_id=people["ana"])
    assert out["count"] == 1
    assert out["pins"][0]["times"] == 2


def test_the_atlas_has_no_coordinates_and_no_time_capsule(graph, people):
    """A countdown of 342 days to a capsule at a place the account had never been, with a
    person who did not exist, implemented nowhere."""
    signals.check_in(graph, account_id=people["ana"], place="Fabrica")
    out = atlas.pins(graph, account_id=people["ana"])
    assert out["coordinates"] is False
    assert out["time_capsule"] is None


def test_the_atlas_can_be_filtered_to_a_city(graph, people):
    signals.check_in(graph, account_id=people["ana"], place="Fabrica", city="Lisbon")
    signals.check_in(graph, account_id=people["ana"], place="Blitz", city="Munich")
    assert atlas.pins(graph, account_id=people["ana"], city="Lisbon")["count"] == 1


# ---- wellness ----------------------------------------------------------------

def test_wellness_is_counts_not_a_score(graph, people):
    """A flourishing score of 92 and an 85/15 screen-time ratio, on an account created a
    second earlier, for a thing that measures no screens."""
    signals.check_in(graph, account_id=people["ana"], place="Fabrica", city="Lisbon")
    out = atlas.wellness(graph, account_id=people["ana"])
    assert out["outings"] == 1
    assert out["places"] == 1
    assert out["cities"] == 1
    assert out["no_score"]
    text = str(out).lower()
    for invented in INVENTED:
        assert invented not in text


def test_wellness_on_a_fresh_account_says_nothing_happened(graph, people):
    out = atlas.wellness(graph, account_id=people["ana"])
    assert out["empty"] is True
    assert out["outings"] == 0
    assert out["suggestion"]


def test_the_window_is_named_and_bounded(graph, people):
    assert atlas.wellness(graph, account_id=people["ana"], days=7)["window_days"] == 7
    assert atlas.wellness(graph, account_id=people["ana"], days=9999)["window_days"] == 365
    with pytest.raises(atlas.AtlasError):
        atlas.wellness(graph, account_id=people["ana"], days="a month")
