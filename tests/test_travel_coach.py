"""The propose-only coach (Phase 1, autonomy level L0), checked under pytest.

The coach's claim is that it tells you true things about your own week, from real counts.
That makes staying QUIET most of its job: firing on two weeks of data, re-raising what you
dismissed, or calling a goal stuck the week after you moved it would all make it something
you stop reading — and an assistant you stop reading is worse than none at all.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

RUNNER = Path(__file__).parent / "travel" / "run_coach.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_travel_coach_js():
    result = subprocess.run(["node", str(RUNNER)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
