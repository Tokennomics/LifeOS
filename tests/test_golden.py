"""Golden-file suite for the anti-hindrance core (T3).

The SAME fixtures (tests/golden/cases.json) are checked against both
implementations of the shared logic:
  - Python: modules/horizon/core.py (here)
  - Travel Mode JS: surfaces/app/www/horizon-core.js (via tests/golden/run_js.mjs)

Because both compare to one authored expectation, neither can drift from the
spec — or from each other — without turning a check red. That protects the owner:
the phone build and the server can never quietly disagree about how a week is
planned when there's no laptop around to notice.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from modules.horizon import core

GOLDEN = Path(__file__).parent / "golden" / "cases.json"
CASES = json.loads(GOLDEN.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES["plan"], ids=[c["name"] for c in CASES["plan"]])
def test_plan_golden(case):
    assert core.offline_plan(case["input"]) == case["expected"]


@pytest.mark.parametrize("case", CASES["classify"], ids=[c["input"]["text"][:32] for c in CASES["classify"]])
def test_classify_golden(case):
    assert core.is_project_idea(case["input"]["text"]) == case["expected"]


@pytest.mark.parametrize("case", CASES["retro"], ids=[f"{c['input']['week']}-{len(c['input']['tasks'])}" for c in CASES["retro"]])
def test_retro_golden(case):
    assert core.retro(case["input"]["week"], case["input"]["tasks"]) == case["expected"]


@pytest.mark.parametrize("case", CASES["gate"], ids=[str(c["input"]["days_used"]) for c in CASES["gate"]])
def test_gate_golden(case):
    i = case["input"]
    assert core.gate_from_counts(i["days_used"], i["logs_recorded"], i["retros_completed"]) == case["expected"]


def test_travel_js_core_matches_golden():
    """Travel Mode's JS core must produce identical outputs to the golden fixtures.

    Fails the suite if node reports any drift. Skips only when node is entirely
    absent (CI provides it), so drift is caught rather than hidden.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available to run the Travel Mode JS parity check")
    runner = Path(__file__).parent / "golden" / "run_js.mjs"
    result = subprocess.run([node, str(runner)], capture_output=True, text=True)
    assert result.returncode == 0, (
        "Travel Mode JS core drifted from the golden fixtures:\n"
        + result.stdout + "\n" + result.stderr
    )
