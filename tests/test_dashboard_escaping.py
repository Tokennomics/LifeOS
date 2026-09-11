"""`dashboard.js` put user text straight into `innerHTML`.

Confirmed in Chromium rather than inferred: a routine named `<img src=x onerror=…>` executed.
This page keeps the session bearer token in `localStorage`, so script execution here reads it
— account takeover, not a cosmetic bug. The three widgets read the account's own rows today,
which made it latent; it stops being latent the moment any of that text arrives from an ICS
import, a seeded venue name, or another account.

`app.js` and `index.html` have had an `esc()` for a long time. `dashboard.js` shipped in the
same `index.html` with no escaping helper at all, which is the kind of gap that opens when a
file arrives from a different tool and nobody sweeps it.

These are static checks, deliberately. The browser proof is worth running once (the script is
in this session's scratchpad) but it needs Chromium and a real origin; what stops a regression
landing is a test that reads the file in CI, every run, in milliseconds.
"""

import pathlib
import re

import pytest

DASHBOARD = pathlib.Path(__file__).resolve().parent.parent / "surfaces/app/www/dashboard.js"


@pytest.fixture(scope="module")
def source():
    assert DASHBOARD.exists()
    return DASHBOARD.read_text()


def _interpolations(text: str):
    """Every `${…}` inside a template literal, with its line, comments stripped."""
    without_comments = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    without_comments = re.sub(r"^\s*//.*$", "", without_comments, flags=re.M)
    for n, line in enumerate(without_comments.splitlines(), 1):
        for hit in re.findall(r"\$\{([^}]*)\}", line):
            yield n, hit.strip()


def test_every_interpolation_is_escaped_or_coerced(source):
    """The rule, in one place: nothing reaches innerHTML without going through esc() or num().

    `API_BASE` and the two fetch paths are template literals building a URL, not HTML.
    """
    allowed_bare = {"API_BASE", "endpoint", "routineId", "riskClass"}
    unguarded = []
    for line, expr in _interpolations(source):
        if expr in allowed_bare:
            continue
        if expr.startswith("esc(") or expr.startswith("num("):
            continue
        unguarded.append(f"dashboard.js:{line} -> ${{{expr}}}")
    assert unguarded == [], "unescaped interpolation into innerHTML: " + "; ".join(unguarded)


def test_the_escaper_covers_every_character_that_matters(source):
    """A helper that misses one character is worse than none, because it looks handled."""
    assert "function esc(value)" in source
    for char in ("&", "<", ">", '"', "'"):
        assert f'"{char}"' in source or f"'{char}'" in source, f"esc() does not map {char!r}"


def test_a_width_percentage_cannot_carry_css(source):
    """`style="width: ${pct}%"` sits inside quotes already, so HTML-escaping does not save it:
    a value of `50; background:url(...)` is a second declaration. num() clamps it to 0-100."""
    # `.*?` rather than `[^}]*`: the options object `{ min: 0, max: 100 }` contains braces,
    # so a negated-brace class stops at the first one and never reaches the clamp.
    assert re.search(r'width:\s*\$\{num\(.*?min:\s*0.*?max:\s*100.*?\)\}%', source), \
        "the progress bar width is not clamped through num()"


def test_no_inline_event_handler(source):
    """The last one in the codebase. The other five were removed because each lied about what
    it did; this one called a real function, but interpolated an id into an HTML attribute —
    an id containing a quote breaks out of it. `dataset` carries it as data, not code."""
    assert "onclick=" not in source


def test_the_delegated_listener_is_bound_once(source):
    """`init()` re-renders on every routine completion. Binding inside it without a guard
    adds a listener per render, so the nth click fires n requests."""
    assert "container.dataset.wired" in source
    assert "[data-act=complete-routine]" in source


def test_the_other_served_files_have_no_inline_handlers_either():
    """dashboard.js was the last one; this keeps it that way across the served surface."""
    www = DASHBOARD.parent
    for name in ("app.js", "index.html", "dashboard.js", "travel.js", "travel.html"):
        path = www / name
        if path.exists():
            assert "onclick=" not in path.read_text(), f"{name} has an inline handler"
