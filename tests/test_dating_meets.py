"""Dating discovery — who is open to meeting someone here.

`mutual_match` was already correct about interest in a *named* person. What it could not do
was tell you who to name, so `/dating/instant-meet` filled that gap with Elena R., 1.2 km
away, at a 96% score computed from seven constants.

The replacement has to be honest *and* has to not become a browsable list of who is single
in a city. So the assertions that matter here are the ones about who cannot see what:
reciprocal visibility, the gates running before any read, and blocks cutting both ways.

Written against three real registered accounts, like `test_dating_match.py`, because a
single-owner test passes under the broken code as well as the fixed one.
"""

import datetime

import pytest

from gateway import accounts
from modules.dating import gate, meets, safety
from modules.security import crypto_tokens
from substrate.graph import Graph

KEY = "b7Qv2xLp9NrK4mYtZs8WfCg3JhDn6VaE"      # 32 chars, test-only
PW = "correct-horse-battery"


def _adult_dob() -> str:
    today = datetime.datetime.now(datetime.timezone.utc).date()
    return today.replace(year=today.year - 30).isoformat()


@pytest.fixture
def world(graph, monkeypatch):
    monkeypatch.setenv(crypto_tokens.ENV_VAR, KEY)
    monkeypatch.setenv(gate.ENABLE_VAR, "1")
    made = {}
    for name in ("ana", "bruno", "carla"):
        account = accounts.register(graph, name, PW)
        made[name] = Graph(graph.conn, graph.bus, default_owner=account["owner_id"])
        made[f"{name}_id"] = account["account_id"]
        gate.declare_age(graph, account["account_id"], _adult_dob())
    made["root"] = graph
    return made


def _open(w, who, city="Lisbon", **kw):
    return meets.open_to_meeting(w[who], city, account_id=w[f"{who}_id"], handle=who, **kw)


def _nearby(w, who, city="Lisbon"):
    return meets.nearby(w[who], city, account_id=w[f"{who}_id"])


# ---- reciprocal visibility: the rule that makes this safe -------------------

def test_you_cannot_see_the_list_without_being_on_it(world):
    """The single most important property. Without it this is a directory of who is single
    in a city, readable by anyone who signs up and never publishes anything."""
    _open(world, "bruno")
    seen = _nearby(world, "ana")
    assert seen["you_are_open"] is False
    assert seen["people"] == []


def test_the_rule_is_explained_rather_than_thrown(world):
    _open(world, "bruno")
    seen = _nearby(world, "ana")
    assert "open yourself" in seen["suggestion"]


def test_being_open_reveals_the_others(world):
    _open(world, "bruno", vibe="drinks somewhere loud")
    _open(world, "ana")
    seen = _nearby(world, "ana")
    assert seen["you_are_open"] is True
    assert [p["handle"] for p in seen["people"]] == ["bruno"]
    assert seen["people"][0]["vibe"] == "drinks somewhere loud"


def test_reading_does_not_publish_you(world):
    """If looking put you on the list, "you must be on the list to read it" would be a rule
    that enforces itself by removing the choice."""
    _open(world, "bruno")
    _nearby(world, "ana")
    assert meets.mine(world["ana"], account_id=world["ana_id"]) == []
    assert _nearby(world, "bruno")["people"] == []


def test_the_account_id_comes_back_because_it_is_the_next_step(world):
    """A handle is not enough — `express_interest` takes an account id, and without it the
    list is a wall of names you cannot act on."""
    _open(world, "bruno")
    _open(world, "ana")
    assert _nearby(world, "ana")["people"][0]["account_id"] == world["bruno_id"]


def test_you_are_never_in_your_own_list(world):
    _open(world, "ana")
    assert _nearby(world, "ana")["people"] == []


def test_a_different_city_is_a_different_list(world):
    _open(world, "bruno", city="Porto")
    _open(world, "ana", city="Lisbon")
    assert _nearby(world, "ana", "Lisbon")["people"] == []


# ---- the gates run before anything is read ---------------------------------

def test_the_surface_being_off_hides_it_entirely(world, monkeypatch):
    _open(world, "bruno")
    _open(world, "ana")
    monkeypatch.delenv(gate.ENABLE_VAR, raising=False)
    with pytest.raises(gate.DatingUnavailable):
        _nearby(world, "ana")


def test_publishing_needs_the_surface_too(world, monkeypatch):
    monkeypatch.delenv(gate.ENABLE_VAR, raising=False)
    with pytest.raises(gate.DatingUnavailable):
        _open(world, "ana")


def test_an_undeclared_age_cannot_publish(graph, monkeypatch):
    """The adult gate is the whole reason `require_adult` exists; a discovery surface that
    skipped it would be the one place in the module where it did not apply."""
    monkeypatch.setenv(crypto_tokens.ENV_VAR, KEY)
    monkeypatch.setenv(gate.ENABLE_VAR, "1")
    account = accounts.register(graph, "dana", PW)
    theirs = Graph(graph.conn, graph.bus, default_owner=account["owner_id"])
    with pytest.raises(gate.AgeGateError):
        meets.open_to_meeting(theirs, "Lisbon", account_id=account["account_id"])


def test_an_undeclared_age_cannot_read_either(world, graph):
    _open(world, "ana")
    account = accounts.register(graph, "dana", PW)
    theirs = Graph(graph.conn, graph.bus, default_owner=account["owner_id"])
    with pytest.raises(gate.AgeGateError):
        meets.nearby(theirs, "Lisbon", account_id=account["account_id"])


def test_signing_out_is_not_a_way_in(world):
    with pytest.raises(meets.MeetError):
        meets.nearby(world["root"], "Lisbon", account_id="")


# ---- blocks and mutes ------------------------------------------------------

def test_someone_you_blocked_does_not_appear(world):
    _open(world, "carla")
    _open(world, "ana")
    safety.block(world["ana"], world["carla_id"], account_id=world["ana_id"])
    assert _nearby(world, "ana")["people"] == []


def test_and_you_do_not_appear_to_them(world):
    """The half that is easy to miss. A one-way filter leaves the blocked party looking at
    somebody who cannot see them — the exact interaction a block exists to prevent."""
    _open(world, "carla")
    _open(world, "ana")
    safety.block(world["ana"], world["carla_id"], account_id=world["ana_id"])
    assert _nearby(world, "carla")["people"] == []


def test_a_muted_person_does_not_appear(world):
    from modules.city import chat
    _open(world, "carla")
    _open(world, "ana")
    chat.mute(world["ana"], world["ana_id"], world["carla_id"])
    assert _nearby(world, "ana")["people"] == []


# ---- expiry and withdrawal -------------------------------------------------

def test_a_marker_expires_on_its_own(world):
    _open(world, "bruno", hours=1)
    _open(world, "ana")
    session = meets._sys(world["root"])
    row = [r for r in session.find_entities("content", {"type": meets.RECORD}, limit=20)
           if r["attrs"]["account_id"] == world["bruno_id"]][0]
    gone = (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(hours=2)).isoformat()
    session.update_entity(row["id"], {"expires_at": gone}, source="test")
    assert _nearby(world, "ana")["people"] == []


def test_closing_one_city_leaves_the_others(world):
    _open(world, "ana", city="Lisbon")
    _open(world, "ana", city="Porto")
    meets.close(world["ana"], "Lisbon", account_id=world["ana_id"])
    assert [m["city"] for m in meets.mine(world["ana"], account_id=world["ana_id"])] == ["porto"]


def test_closing_with_no_city_takes_everything_down(world):
    """You should not have to remember which cities you left a marker in to stop being
    listed anywhere."""
    _open(world, "ana", city="Lisbon")
    _open(world, "ana", city="Porto")
    out = meets.close(world["ana"], account_id=world["ana_id"])
    assert out["closed"] == 2
    assert meets.mine(world["ana"], account_id=world["ana_id"]) == []


def test_reopening_replaces_rather_than_stacks(world):
    _open(world, "bruno", vibe="quiet drink")
    _open(world, "bruno", vibe="actually, dancing")
    _open(world, "ana")
    seen = _nearby(world, "ana")
    assert seen["people_count"] == 1
    assert seen["people"][0]["vibe"] == "actually, dancing"


def test_hours_is_bounded(world):
    with pytest.raises(meets.MeetError):
        _open(world, "ana", hours=meets.MAX_HOURS + 1)


def test_zero_hours_is_refused_not_defaulted(world):
    with pytest.raises(meets.MeetError):
        _open(world, "ana", hours=0)


def test_a_marker_needs_a_city(world):
    with pytest.raises(meets.MeetError):
        meets.open_to_meeting(world["ana"], "", account_id=world["ana_id"])


# ---- agreeing to meet ------------------------------------------------------

def test_one_sided_agreement_is_not_an_agreement(world):
    """`agreed: True` used to come back for any name in the body. Ana saying yes about
    Bruno, alone, is not two people agreeing to anything."""
    out = meets.agree(world["ana"], world["bruno_id"], "drinks", account_id=world["ana_id"])
    assert out["agreed"] is False
    assert out["meeting_code"] == ""


def test_one_sided_agreement_tells_the_other_person_nothing(world):
    meets.agree(world["ana"], world["bruno_id"], "drinks", account_id=world["ana_id"])
    from modules.dating import mutual_match
    assert mutual_match.check_matches(world["bruno"], world["bruno_id"]) == []


def test_both_sides_agreeing_is_an_agreement(world):
    meets.agree(world["ana"], world["bruno_id"], "drinks", account_id=world["ana_id"])
    out = meets.agree(world["bruno"], world["ana_id"], "drinks",
                      account_id=world["bruno_id"])
    assert out["agreed"] is True
    assert out["meeting_code"]


def test_both_sides_compute_the_same_meeting_code(world):
    """The code is only useful if it is the same one out loud on both phones."""
    first = meets.agree(world["ana"], world["bruno_id"], "drinks",
                        account_id=world["ana_id"])
    second = meets.agree(world["bruno"], world["ana_id"], "drinks",
                         account_id=world["bruno_id"])
    third = meets.agree(world["ana"], world["bruno_id"], "drinks",
                        account_id=world["ana_id"])
    assert second["meeting_code"] == third["meeting_code"]
    assert first["meeting_code"] == ""     # not mutual at the time it was asked


def test_a_different_pair_gets_a_different_code(monkeypatch):
    """`4892` was the same four digits for every pair in the world, which verified nothing."""
    monkeypatch.setenv(crypto_tokens.ENV_VAR, KEY)
    assert meets.meeting_code("a", "b", "drinks") != meets.meeting_code("a", "c", "drinks")


def test_the_code_does_not_depend_on_who_asks(monkeypatch):
    monkeypatch.setenv(crypto_tokens.ENV_VAR, KEY)
    assert meets.meeting_code("a", "b", "drinks") == meets.meeting_code("b", "a", "drinks")


def test_the_code_is_six_digits(monkeypatch):
    monkeypatch.setenv(crypto_tokens.ENV_VAR, KEY)
    code = meets.meeting_code("a", "b", "drinks")
    assert len(code) == 6 and code.isdigit()


def test_agreeing_with_nobody_is_refused(world):
    with pytest.raises(meets.MeetError):
        meets.agree(world["ana"], "", "drinks", account_id=world["ana_id"])


def test_agreeing_needs_the_surface(world, monkeypatch):
    monkeypatch.delenv(gate.ENABLE_VAR, raising=False)
    with pytest.raises(gate.DatingUnavailable):
        meets.agree(world["ana"], world["bruno_id"], "drinks", account_id=world["ana_id"])


def test_a_blocked_person_never_becomes_agreed(world):
    """`express_interest` publishes nothing when blocked, so the second side can never find
    a counterpart digest — the block holds all the way through to the meeting."""
    safety.block(world["bruno"], world["ana_id"], account_id=world["bruno_id"])
    meets.agree(world["ana"], world["bruno_id"], "drinks", account_id=world["ana_id"])
    out = meets.agree(world["bruno"], world["ana_id"], "drinks",
                      account_id=world["bruno_id"])
    assert out["agreed"] is False
