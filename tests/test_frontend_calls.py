"""Every function the PWA calls from a handler is defined somewhere it ships.

The four Voice Copilot buttons called `triggerVoiceQuery()`, which was never written. Each
tap threw a ReferenceError that `act()` turned into a toast, the suite stayed green, and
the feature had never once worked. pytest does not run the front end, so this reads the
source: any name called as `await name(` or `=> name(` must be declared as a function or
bound with const/let/var in one of the served scripts.
"""

import pathlib
import re

WWW = pathlib.Path(__file__).resolve().parent.parent / "surfaces/app/www"
SCRIPTS = ["app.js", "agent.js", "dashboard.js", "travel.js", "travel-coach.js",
           "travel-stats.js", "audio_feedback.js", "sync_queue.js", "horizon-core.js"]

# Browser and language globals, and parameter names that are called (act's `fn`, a
# Promise's `resolve` / `reject`). Anything else has to be defined in the served code.
GLOBALS = {"fetch", "setTimeout", "clearTimeout", "requestAnimationFrame", "prompt",
           "confirm", "alert", "Promise", "JSON", "String", "Number", "Math", "Date",
           "Array", "Object", "Boolean", "isNaN", "parseInt", "parseFloat",
           "encodeURIComponent", "fn", "resolve", "reject"}


def _source():
    return "\n".join((WWW / name).read_text() for name in SCRIPTS)


def _defined(src):
    names = set(re.findall(r"function\s+([A-Za-z_$][\w$]*)", src))
    names |= set(re.findall(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", src))
    names |= set(re.findall(r"([A-Za-z_$][\w$]*)\s*[:=]\s*(?:async\s*)?\(?[\w,\s]*\)?\s*=>", src))
    return names


def _called(src):
    return set(re.findall(r"(?:await\s+|=>\s*)([A-Za-z_$][\w$]*)\s*\(", src))


def test_every_called_function_exists():
    src = _source()
    missing = sorted(_called(src) - _defined(src) - GLOBALS)
    assert missing == [], f"called but never defined: {missing}"


def test_the_check_would_have_caught_the_voice_buttons():
    src = _source().replace("async function triggerVoiceQuery", "async function _gone")
    assert "triggerVoiceQuery" in sorted(_called(src) - _defined(src) - GLOBALS)
