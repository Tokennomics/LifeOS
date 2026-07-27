"""Travel Mode's Journey numbers, checked under pytest.

`surfaces/app/www/travel-stats.js` has no Python twin (unlike horizon-core.js), so there is
nothing to compare it against — but these are the figures the app shows the owner about his
own life, and a streak that flatters or a day count that disagrees with the gate is exactly
the dishonesty the doubt rule exists to prevent. The JS suite runs here so it gates commits
alongside everything else rather than being a thing someone remembers to run.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

RUNNER = Path(__file__).parent / "travel" / "run_stats.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_travel_stats_js():
    result = subprocess.run(["node", str(RUNNER)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
