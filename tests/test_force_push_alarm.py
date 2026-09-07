"""The alarm on the thing that has erased this repository twice.

`main` was force-pushed on 2026-08-2x and again on 2026-08-31, each time dropping 77
commits and restoring two modules that fabricate data. Both times it was noticed by
chance, days later, and recovered with a two-parent merge.

No workflow can *prevent* it — that is branch protection, a repository setting. What
`.github/workflows/force-push-alarm.yml` does is deny it silence: GitHub sets
`forced: true` on a non-fast-forward push, so the workflow fires, names the commits that
left the branch, opens an issue with the recovery that worked both times, and fails.

These tests exist because the alarm is worth exactly as much as its configuration. A
workflow that triggers on the wrong event, or asks for permissions it does not have, is
one that stays quiet on the day it matters — and the day it matters, nobody is reading it.
"""

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOW = pathlib.Path(__file__).resolve().parent.parent / ".github/workflows/force-push-alarm.yml"


@pytest.fixture(scope="module")
def flow():
    assert WORKFLOW.exists(), "the force-push alarm is gone"
    loaded = yaml.safe_load(WORKFLOW.read_text())
    # PyYAML reads a bare `on:` key as the boolean True, which is YAML 1.1 doing what it
    # was asked. GitHub reads it as the string. Accept whichever this parser produced.
    loaded["_on"] = loaded.get("on", loaded.get(True))
    return loaded


def test_it_watches_pushes_to_main(flow):
    assert flow["_on"]["push"]["branches"] == ["main"]


def test_it_only_fires_on_a_non_fast_forward(flow):
    """`github.event.forced` is the whole point. Without the guard it would open an issue
    on every ordinary merge, and an alarm that cries every day is one nobody reads."""
    assert flow["jobs"]["detect"]["if"] == "github.event.forced"


def test_it_can_open_an_issue(flow):
    """The default GITHUB_TOKEN cannot write issues unless the workflow asks. Getting this
    wrong fails at the moment of use, on the one run that matters."""
    assert flow["permissions"]["issues"] == "write"


def test_it_fetches_enough_history_to_name_what_was_lost(flow):
    """`git log AFTER..BEFORE` needs real history. A shallow checkout answers nothing."""
    checkout = [s for s in flow["jobs"]["detect"]["steps"]
                if str(s.get("uses", "")).startswith("actions/checkout")]
    assert checkout, "no checkout step"
    assert checkout[0]["with"]["fetch-depth"] == 0


def test_it_fails_the_run(flow):
    """Opening an issue is not enough on its own: a green tick beside a force-push is the
    silence this exists to break."""
    body = WORKFLOW.read_text()
    assert "exit 1" in body


def test_it_recommends_a_merge_and_warns_against_a_reset(flow):
    """The recovery it prints has to be the one that works. A reset back to the old tip
    drops whatever the force-push added — the same mistake, pointed the other way. A merge
    has two parents and loses neither side; that is what recovered this twice."""
    body = WORKFLOW.read_text()
    assert "git merge" in body
    assert "Do **not** reset" in body


def test_it_points_at_the_setting_that_would_actually_prevent_this(flow):
    body = WORKFLOW.read_text()
    assert "Settings → Branches" in body
    assert "block force pushes" in body.lower()
