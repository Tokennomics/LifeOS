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
