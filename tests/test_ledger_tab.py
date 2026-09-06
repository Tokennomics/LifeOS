"""The shared tab: the numbers have to add up, and both sides have to see the same one."""

import pytest

from modules.ledger import tab


def test_a_split_is_owed_to_the_person_who_paid(graph):
    out = tab.split(graph, account_id="ana", participants=["bo", "cy"], amount=30,
                    currency="EUR", note="dinner")
    assert out["split"] is True
    assert out["money_moved"] is False
    assert {e["person"] for e in out["entries"]} == {"bo", "cy"}
    assert all(e["owes_you"] == 10.0 for e in out["entries"])
    assert out["your_share"] == 10.0


def test_the_split_adds_back_up_to_what_was_paid(graph):
    """Ten euros three ways cannot be 3.33 each and a penny nobody has."""
    out = tab.split(graph, account_id="ana", participants=["bo", "cy"], amount=10)
    owed = sum(e["owes_you"] for e in out["entries"])
    assert round(owed + out["your_share"], 2) == 10.00
    # The odd cent stays with whoever paid.
    assert out["your_share"] == 3.34


def test_a_split_of_an_awkward_amount_still_reconciles(graph):
    for total, people in ((0.07, 3), (100.01, 7), (9.99, 4), (1234.56, 11)):
        others = [f"p{i}" for i in range(people)]
        out = tab.split(graph, account_id="payer", participants=others, amount=total)
        owed = sum(e["owes_you"] for e in out["entries"])
        assert round(owed + out["your_share"], 2) == round(total, 2), (total, people)


def test_the_calculator_records_nothing_and_says_so(graph):
    out = tab.preview(60, 4)
    assert out["recorded"] is False
    assert out["each"] == 15.0
    assert round(out["each"] * 3 + out["your_share"], 2) == 60.00
    assert tab.balances(graph, account_id="ana")["empty"] is True


def test_the_calculator_needs_two_people(graph):
    with pytest.raises(tab.TabError, match="at least two"):
        tab.preview(60, 1)


def test_both_sides_see_the_same_number(graph):
    tab.split(graph, account_id="ana", participants=["bo"], amount=20)
    hers = tab.balances(graph, account_id="ana")["balances"][0]
    his = tab.balances(graph, account_id="bo")["balances"][0]
    assert hers["net"] == his["net"] == 10.0
    assert hers["they_owe_you"] is True
    assert his["they_owe_you"] is False


def test_a_third_party_sees_none_of_it(graph):
    tab.split(graph, account_id="ana", participants=["bo"], amount=20)
    assert tab.balances(graph, account_id="cy")["empty"] is True
    assert tab.entries(graph, account_id="cy")["empty"] is True


def test_currencies_never_mix(graph):
    tab.split(graph, account_id="ana", participants=["bo"], amount=20, currency="EUR")
    tab.split(graph, account_id="ana", participants=["bo"], amount=20, currency="GBP")
    out = tab.balances(graph, account_id="ana")
    assert sorted(b["currency"] for b in out["balances"]) == ["EUR", "GBP"]
    assert out["owed_to_you"] == {"EUR": 10.0, "GBP": 10.0}


def test_a_tip_is_recorded_as_owed_not_sent(graph):
    out = tab.iou(graph, account_id="ana", to_account="bo", amount=3.5, currency="EUR")
    assert out["money_moved"] is False
    assert out["visible_to_them"] is True
    assert tab.balances(graph, account_id="ana")["you_owe"] == {"EUR": 3.5}
    assert tab.balances(graph, account_id="bo")["owed_to_you"] == {"EUR": 3.5}


def test_a_promised_coffee_needs_no_amount(graph):
    out = tab.iou(graph, account_id="ana", to_account="bo", item="flat white")
    assert out["item"] == "flat white"
    assert out["amount"] is None
    # A promise of a thing is not a money balance.
    assert tab.balances(graph, account_id="ana")["empty"] is True
    assert tab.entries(graph, account_id="bo")["total"] == 1


def test_an_iou_needs_an_amount_or_a_thing(graph):
    with pytest.raises(tab.TabError):
        tab.iou(graph, account_id="ana", to_account="bo")


def test_settling_clears_the_balance(graph):
    tab.split(graph, account_id="ana", participants=["bo"], amount=20)
    out = tab.settle(graph, account_id="bo", counterparty="ana")
    assert out["settled"] is True
    assert out["clear"] is True
    assert out["still_owed"] == 0.0
    assert out["money_moved"] is False
    assert tab.balances(graph, account_id="ana")["empty"] is True
    assert tab.balances(graph, account_id="bo")["empty"] is True


def test_a_partial_settlement_leaves_the_rest(graph):
    tab.split(graph, account_id="ana", participants=["bo"], amount=50)
    out = tab.settle(graph, account_id="bo", counterparty="ana", amount=10)
    assert out["still_owed"] == 15.0
    assert out["clear"] is False
    assert tab.balances(graph, account_id="ana")["owed_to_you"] == {"EUR": 15.0}


def test_you_cannot_settle_more_than_you_owe(graph):
    tab.split(graph, account_id="ana", participants=["bo"], amount=20)
    with pytest.raises(tab.TabError, match="only owe"):
        tab.settle(graph, account_id="bo", counterparty="ana", amount=999)
    # And the balance is untouched by the attempt.
    assert tab.balances(graph, account_id="ana")["owed_to_you"] == {"EUR": 10.0}


def test_you_cannot_settle_a_debt_that_is_not_yours(graph):
    tab.split(graph, account_id="ana", participants=["bo"], amount=20)
    with pytest.raises(tab.TabError, match="do not owe"):
        tab.settle(graph, account_id="ana", counterparty="bo")


def test_settling_a_currency_you_do_not_owe_is_refused(graph):
    tab.split(graph, account_id="ana", participants=["bo"], amount=20, currency="EUR")
    with pytest.raises(tab.TabError, match="do not owe"):
        tab.settle(graph, account_id="bo", counterparty="ana", currency="GBP")


def test_debts_in_both_directions_net_off(graph):
    tab.split(graph, account_id="ana", participants=["bo"], amount=20)   # bo owes 10
    tab.split(graph, account_id="bo", participants=["ana"], amount=6)    # ana owes 3
    out = tab.balances(graph, account_id="ana")
    assert out["balances"] == [{"counterparty": "bo", "currency": "EUR", "net": 7.0,
                                "they_owe_you": True, "direction": "they owe you"}]


def test_a_debt_you_never_agreed_to_can_be_rejected(graph):
    """Without this, anybody could assert anybody else owed them a thousand euros and the
    other side could only watch it sit there."""
    out = tab.split(graph, account_id="ana", participants=["bo"], amount=2000)
    entry_id = out["entries"][0]["entry_id"]
    assert tab.balances(graph, account_id="bo")["you_owe"] == {"EUR": 1000.0}

    tab.dispute(graph, account_id="bo", entry_id=entry_id, reason="I was not there")
    assert tab.balances(graph, account_id="bo")["empty"] is True
    assert tab.balances(graph, account_id="ana")["empty"] is True


def test_a_disputed_entry_is_not_deleted(graph):
    """An entry that vanishes is an argument with no record."""
    out = tab.split(graph, account_id="ana", participants=["bo"], amount=20)
    tab.dispute(graph, account_id="bo", entry_id=out["entries"][0]["entry_id"])
    for who in ("ana", "bo"):
        rows = tab.entries(graph, account_id=who)["entries"]
        assert len(rows) == 1 and rows[0]["disputed"] is True


def test_you_cannot_dispute_your_own_claim(graph):
    """Disputing is for the side an entry counts against — you cannot withdraw a claim by
    disputing it, and you cannot dispute somebody else's debt on their behalf."""
    out = tab.split(graph, account_id="ana", participants=["bo"], amount=20)
    entry_id = out["entries"][0]["entry_id"]
    with pytest.raises(tab.TabError, match="not yours"):
        tab.dispute(graph, account_id="ana", entry_id=entry_id)
    with pytest.raises(tab.TabError, match="not yours"):
        tab.dispute(graph, account_id="cy", entry_id=entry_id)
    assert tab.balances(graph, account_id="bo")["you_owe"] == {"EUR": 10.0}


def test_a_settlement_is_disputed_by_whoever_was_supposedly_paid(graph):
    """"I paid you" is a claim too, and the person who did not receive it gets a say."""
    tab.split(graph, account_id="ana", participants=["bo"], amount=20)
    settled = tab.settle(graph, account_id="bo", counterparty="ana")
    with pytest.raises(tab.TabError, match="not yours"):
        tab.dispute(graph, account_id="bo", entry_id=settled["entry_id"])
    tab.dispute(graph, account_id="ana", entry_id=settled["entry_id"])
    assert tab.balances(graph, account_id="ana")["owed_to_you"] == {"EUR": 10.0}


def test_disputing_twice_is_harmless(graph):
    out = tab.split(graph, account_id="ana", participants=["bo"], amount=20)
    entry_id = out["entries"][0]["entry_id"]
    tab.dispute(graph, account_id="bo", entry_id=entry_id)
    assert tab.dispute(graph, account_id="bo", entry_id=entry_id)["already"] is True


def test_disputing_something_that_is_not_an_entry(graph):
    with pytest.raises(tab.TabError, match="no such entry"):
        tab.dispute(graph, account_id="bo", entry_id="not-an-id")


def test_money_is_never_a_float_on_the_way_in(graph):
    """0.1 + 0.2 accumulating across a hundred entries is how a tab quietly goes wrong."""
    for _ in range(100):
        tab.iou(graph, account_id="ana", to_account="bo", amount=0.1)
    assert tab.balances(graph, account_id="ana")["you_owe"] == {"EUR": 10.0}


def test_nonsense_amounts_are_refused(graph):
    for bad in (0, -5, "abc", None, "", float("inf"), 10_000_000_000):
        with pytest.raises(tab.TabError):
            tab.split(graph, account_id="ana", participants=["bo"], amount=bad)


def test_a_split_needs_somebody_to_split_with(graph):
    with pytest.raises(tab.TabError):
        tab.split(graph, account_id="ana", participants=[], amount=10)
    with pytest.raises(tab.TabError):
        tab.split(graph, account_id="ana", participants=["ana"], amount=10)


def test_signing_in_is_required(graph):
    with pytest.raises(tab.TabError, match="sign in"):
        tab.split(graph, account_id="", participants=["bo"], amount=10)
    with pytest.raises(tab.TabError, match="sign in"):
        tab.balances(graph, account_id="")


def test_the_history_explains_the_balance(graph):
    tab.split(graph, account_id="ana", participants=["bo"], amount=20, note="tapas")
    tab.settle(graph, account_id="bo", counterparty="ana", amount=4)
    out = tab.entries(graph, account_id="bo", counterparty="ana")
    kinds = [e["kind"] for e in out["entries"]]
    assert sorted(kinds) == ["settlement", "split"]
    assert all(e["counterparty"] == "ana" for e in out["entries"])


def test_a_currency_must_look_like_one(graph):
    with pytest.raises(tab.TabError, match="three-letter"):
        tab.split(graph, account_id="ana", participants=["bo"], amount=10, currency="euros")


def test_nothing_here_claims_money_moved(graph):
    """The one claim that must never appear in this module's output."""
    outs = [tab.split(graph, account_id="ana", participants=["bo"], amount=10),
            tab.iou(graph, account_id="ana", to_account="cy", amount=2),
            tab.balances(graph, account_id="ana"),
            tab.settle(graph, account_id="bo", counterparty="ana", amount=1)]
    for out in outs:
        if "money_moved" in out:
            assert out["money_moved"] is False
        assert "payment_link" not in out
        assert "voucher_code" not in out
