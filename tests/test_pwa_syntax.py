"""The PWA's JavaScript has to actually parse.

**This is the test that should have existed a week earlier.** On 2026-08-05 a generated
commit inserted a new card into `app.js` without closing the template literal above it, and
a second one put backticks inside a template literal. Either is a `SyntaxError`, which means
the browser parses *none* of the file: no capture, no crews, no weekend, no sign-in. The app
served a shell and nothing else.

It stayed that way for seven days and roughly forty commits. Every one of those commits ran
a green Python suite, because nothing in this repo had ever executed the front end. A
thousand passing tests said the product worked while the product did not start.

`node --check` is the whole fix — it is a parse, not a lint, so it has no opinions and no
false positives, and it takes milliseconds. CI runs the same check; this test is here so it
also fails locally, before the commit.
"""

import pathlib
import shutil
import subprocess

import pytest

WWW = pathlib.Path(__file__).resolve().parent.parent / "surfaces" / "app" / "www"
SCRIPTS = sorted(p for p in WWW.rglob("*.js") if "vendor" not in p.parts)

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node is needed to parse JavaScript")


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_every_pwa_script_parses(script):
    result = subprocess.run(["node", "--check", str(script)],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, (
        f"{script.name} does not parse — the browser will run none of it:\n"
        f"{result.stderr.strip()[:800]}")


def test_the_scripts_index_loads_are_all_present():
    """A 404 on a <script> is the same outage as a syntax error, and just as invisible to a
    Python suite."""
    import re
    html = (WWW / "index.html").read_text(encoding="utf-8")
    for src in re.findall(r'<script[^>]+src="([^"]+)"', html):
        if src.startswith("http"):
            continue
        assert (WWW / src).is_file(), f"index.html loads {src}, which does not exist"


def test_the_pwa_offers_a_way_to_sign_in():
    """There was no register or login form anywhere in the app — the only route to a session
    was pasting a bearer token into a developer field, while `docs/HOSTING.md` told friends
    to "tap Register". The buttons that looked like sign-in called an endpoint that returns
    a fabricated user id and no token, then toasted "Authenticated!"."""
    html = (WWW / "index.html").read_text(encoding="utf-8")
    for required in ('id="auth-handle"', 'id="auth-pass"', 'id="auth-submit"',
                     'id="auth-email"', 'id="set-signout"'):
        assert required in html, f"the sign-in screen lost {required}"

    app_js = (WWW / "app.js").read_text(encoding="utf-8")
    assert "/v1/auth/register" in app_js and "/v1/auth/login" in app_js
    assert "/v1/auth/email/verify" in app_js
    # Match a *call*, not the word — the comment explaining why that endpoint is gone
    # naturally mentions it by name.
    assert 'api("/v1/auth/social-sso"' not in app_js, "the fake SSO path is back"


# ---- buttons written into the page after render ----------------------------
#
# `wire(root)` binds click handlers to the elements that exist at render time. Every result
# card in `app.js` is written afterwards with `innerHTML`, so a `[data-act]` button inside
# one has no listener: it renders, it looks live, and tapping it does nothing. Found by
# clicking "I'd meet them" in a real browser after the Python suite was fully green — the
# request was never sent and the card simply did not change.
#
# `bindLater` is the fix. These two tests keep it wired up, because the failure is silent
# in every other check this repo runs.

APP_JS = WWW / "app.js"


def test_wire_can_bind_markup_added_after_render():
    source = APP_JS.read_text(encoding="utf-8")
    assert "const bindLater" in source, (
        "wire() lost its late binder — every button inside a dynamically rendered card "
        "stops responding, silently")


def test_every_renderer_that_writes_a_data_act_binds_it():
    """A renderer that injects an action button and forgets `bindLater` ships a dead button.

    Deliberately crude — it counts, it does not parse — but the thing it guards against is
    adding a card and forgetting, which is exactly what happened.
    """
    source = APP_JS.read_text(encoding="utf-8")
    injected = source.count('data-act="')          # only ever written inside template markup
    bound = source.count("bindLater(")
    assert bound >= 5, (
        f"{injected} data-act buttons are written into markup but bindLater is called only "
        f"{bound} times — some of them cannot respond to a tap")
