"""The wearable studio: a code that encodes, a card for somebody who exists, a claim as a claim.

The four tests this replaces pinned the props rather than the feature. Their intent is kept
and made checkable:

- "the studio produces a print-ready SVG" -> it produces one whose QR is a real symbol,
  asserted against the encoder's own version and module count and against well-formed XML,
  because the previous SVG was a SHA-256 painted to look like a barcode and passed a test
  that only checked it was an SVG. The out->in half is `tests/test_wearable_qr_roundtrip.py`,
  which rasterises the panel in a browser and decodes it back.
- "an endpoint generates a badge for a handle" -> for the handle you send, with no
  invented person behind it when you send none.
- "a profile lookup returns a person" -> for a handle that resolves to an account, from
  what that account wrote, and 404 otherwise. The old test asserted `found is True`,
  a title-cased name and an invented interest for a handle nobody owned.
- "a scan records a vouch" -> `assert data["vouched"] is True` and `"Karma" in
  data["karma_awarded"]` become: a real vouch row exists, both sides can read it under
  trust, re-scanning does not stack it, and neither of those two keys comes back.
"""

import ast
import pathlib
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app
from modules.social import trust
from modules.wearables import qr, tshirt_studio
from substrate.graph import Graph

PW = "correct-horse-battery"
ROOT = pathlib.Path(__file__).resolve().parent.parent

# Every host this deployment does not serve, plus the people the props invented. Kept in one
# place because six tests below check the same list against different surfaces.
NOT_OURS = ("lifeos.app", "connectos.app")
INVENTED = ("alex_v", "Alex V.", "elena_s", "AI Research · Surfing · Deep Work")

# Response fields that are allowed to name what they disclaim ("verifies no identity",
# "no karma"). A whole-body substring assert without this fails on our own honest copy —
# it has done, three times, in this repo.
PROSE_KEYS = ("no_money", "note", "suggestion", "reason", "why", "disclaimer", "print_note")


@pytest.fixture(autouse=True)
def _no_ambient_limits(monkeypatch):
    monkeypatch.setenv(rate_limiter.DISABLE_VAR, "1")


@pytest.fixture
def world(cfg):
    client = TestClient(create_app(cfg))
    people = {}
    for name in ("ana", "bruno"):
        client.post("/v1/auth/register", json={"handle": name, "password": PW})
        token = client.post("/v1/auth/login",
                            json={"handle": name, "password": PW}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        people[name] = {"h": headers,
                        "id": client.get("/v1/auth/me", headers=headers).json()["account_id"]}
    return client, people


def _prose_stripped(payload: dict) -> str:
    """The body with its named disclaimer fields removed, for a substring assert.

    Trap 1 in this repo: honest copy names the thing it disclaims, so `"karma" not in
    str(body)` fails on a sentence that says there is no karma. Everything the house style
    puts prose in comes out first, and what is left is claims.
    """
    return str({k: v for k, v in payload.items() if k not in PROSE_KEYS})


# ---- the code is a code -------------------------------------------------------------

def test_the_encoder_produces_a_real_symbol_not_a_drawing():
    """A QR's version and module count are derived from its payload; a hash's are not.

    The replaced `_generate_qr_svg_matrix` drew 25x25 whatever it was given. Two payloads of
    very different lengths must land on different versions here, and every symbol's side
    must be the 4*version+17 the specification defines.
    """
    short = "/#connect?handle=ana"
    long = "/#connect?handle=" + ("a" * 300)

    levels = "LMQH"
    for text in (short, long):
        symbol = qr.symbol(text)
        assert qr.modules(text) == 4 * symbol.version + 17
        # M is the floor. segno raises it for free when a short payload leaves room in the
        # same version, and `facts` has to report what was used rather than what was asked
        # for — an "M" printed next to a Q symbol is a small invented fact.
        assert levels.index(symbol.error) >= levels.index("M")
    assert qr.symbol(long).version > qr.symbol(short).version

    facts = qr.facts(short)
    assert facts == {"version": qr.symbol(short).version,
                     "error_correction": qr.symbol(short).error,
                     "modules": qr.modules(short), "quiet_zone_modules": 4,
                     "encodes": short}


def test_the_qr_svg_is_well_formed_and_has_the_module_count_for_its_version():
    text = "/#connect?handle=ana"
    markup = qr.svg(text)
    root = ET.fromstring(markup)

    side = qr.modules(text) + qr.QUIET_ZONE * 2
    assert root.get("viewBox") == f"0 0 {side} {side}"

    # Every dark run in the SVG, summed, is exactly the number of dark modules the encoder
    # produced. This is the assertion the old suite could not make: a drawing has no
    # matrix to compare against.
    dark = sum(int(r.get("width")) for r in root
               if r.tag.endswith("rect") and r.get("fill") == qr.DARK)
    assert dark == sum(sum(1 for cell in row if cell) for row in qr.symbol(text).matrix)


def test_the_encoder_refuses_an_empty_payload():
    with pytest.raises(ValueError):
        qr.svg("")


# ---- the panel ----------------------------------------------------------------------

def test_the_panel_module_writes_a_row_and_carries_a_decodable_code(graph: Graph):
    res = tshirt_studio.generate_badge(
        graph, account_id="acct-1", handle="robert_k", name="Robert K.",
        tagline="AI systems and surf", interests=["AI systems", "Surfing", "Coffee"],
        base_url="http://127.0.0.1:9000/")

    assert res["handle"] == "robert_k"
    assert res["connect_url"] == "http://127.0.0.1:9000/#connect?handle=robert_k"
    assert res["qr"]["encodes"] == res["connect_url"]
    assert res["svg_data_uri"].startswith("data:image/svg+xml;")

    # The panel must be loadable as an image or the preview and the print are both blank.
    # It was not, briefly, during this ticket: the nested QR carried two `width` attributes
    # and Chromium refused the whole file with no error near the cause.
    root = ET.fromstring(res["svg"])
    nested = [el for el in root.iter() if el.tag.endswith("svg") and el is not root]
    assert len(nested) == 1
    side = qr.modules(res["connect_url"]) + qr.QUIET_ZONE * 2
    assert nested[0].get("viewBox") == f"0 0 {side} {side}"

    row = tshirt_studio.latest_badge(graph, "acct-1")
    assert row is not None
    assert row["attrs"]["account_id"] == "acct-1"
    assert row["attrs"]["handle"] == "robert_k"
    assert row["id"] == res["badge_id"]


def test_the_panel_leaves_out_what_its_owner_did_not_type(graph: Graph):
    """No name, no tagline, no pills — rather than somebody else's."""
    res = tshirt_studio.generate_badge(graph, account_id="acct-1", handle="quiet")
    assert res["name"] == "" and res["tagline"] == "" and res["interests"] == []
    assert "@quiet" in res["svg"]
    for invented in INVENTED:
        assert invented not in res["svg"]


def test_a_panel_needs_a_handle_and_a_signed_in_account(graph: Graph):
    with pytest.raises(ValueError, match="whose shirt"):
        tshirt_studio.generate_badge(graph, account_id="acct-1", handle="")
    with pytest.raises(ValueError):
        tshirt_studio.generate_badge(graph, account_id="", handle="ana")


def test_the_panel_escapes_what_its_owner_typed(graph: Graph):
    """The old version interpolated four user fields into markup raw."""
    res = tshirt_studio.generate_badge(graph, account_id="acct-1", handle="ana",
                                       name='</text><script>x</script>')
    ET.fromstring(res["svg"])
    assert "<script>" not in res["svg"]


def test_the_badge_endpoint_encodes_this_gateway_and_needs_a_handle(world):
    client, people = world
    res = client.post("/v1/wearables/tshirt-badge",
                      json={"handle": "ana", "tagline": "pottery on wednesdays"},
                      headers=people["ana"]["h"])
    assert res.status_code == 200
    body = res.json()
    assert body["connect_url"].endswith("/#connect?handle=ana")
    assert body["qr"]["version"] >= 1
    assert body["qr"]["modules"] == 4 * body["qr"]["version"] + 17
    for host in NOT_OURS:
        assert host not in str(body)

    empty = client.post("/v1/wearables/tshirt-badge", json={}, headers=people["ana"]["h"])
    assert empty.status_code == 400
    assert "whose shirt" in empty.json()["detail"]


def test_the_people_qr_route_returns_an_image_of_the_vcard_it_returns(world):
    """It returned a vCard and called itself `/people/qr`, with no code anywhere in it."""
    client, people = world
    body = client.get("/v1/people/qr", headers=people["ana"]["h"]).json()
    assert body["vcard"].startswith("BEGIN:VCARD")
    assert body["qr"]["encodes"] == body["vcard"]
    root = ET.fromstring(body["qr_svg"])
    side = qr.modules(body["vcard"]) + qr.QUIET_ZONE * 2
    assert root.get("viewBox") == f"0 0 {side} {side}"


# ---- the card ------------------------------------------------------------------------

def test_an_unknown_handle_has_no_profile(world):
    """`found: True` with an invented name, a tagline and three interests, for any string."""
    client, people = world
    res = client.get("/v1/connect/profile/nobody_at_all", headers=people["ana"]["h"])
    assert res.status_code == 404
    assert "nobody_at_all" in res.json()["detail"]


def test_a_profile_carries_no_score_and_no_invented_name(world):
    client, people = world
    body = client.get("/v1/connect/profile/bruno", headers=people["ana"]["h"]).json()

    assert body["found"] is True
    assert body["account_id"] == people["bruno"]["id"]
    assert "trust_score" not in body
    assert "mutual_nodes_count" not in body
    assert "KYC" not in _prose_stripped(body)
    # Nobody has vouched for either of them, so nobody has vouched for both.
    assert body["in_common"] == 0
    assert body["in_common_handles"] == []
    # bruno never set a name and never made a panel, so there is no name to show.
    assert body["name"] == ""
    assert body["tagline"] == ""
    assert body["interests"] == []
    assert body["has_badge"] is False
    assert body["suggestion"]
    for host in NOT_OURS:
        assert host not in str(body)


def test_a_profile_shows_only_what_its_own_subject_wrote(world):
    """The replaced handler searched badges by handle in the *reader's* slice.

    So it found the reader's own row or none, and the "none" branch invented a person. A
    panel ana makes must never caption bruno, whatever handle she typed on it.
    """
    client, people = world
    client.post("/v1/wearables/tshirt-badge",
                json={"handle": "bruno", "name": "Not Bruno", "tagline": "not his either",
                      "interests": ["nope"]},
                headers=people["ana"]["h"])

    seen = client.get("/v1/connect/profile/bruno", headers=people["ana"]["h"]).json()
    assert seen["name"] == ""
    assert seen["tagline"] == ""
    assert seen["has_badge"] is False

    client.post("/v1/wearables/tshirt-badge",
                json={"handle": "bruno", "name": "Bruno", "tagline": "climbs on tuesdays",
                      "interests": ["bouldering"]},
                headers=people["bruno"]["h"])
    now = client.get("/v1/connect/profile/bruno", headers=people["ana"]["h"]).json()
    assert now["name"] == "Bruno"
    assert now["tagline"] == "climbs on tuesdays"
    assert now["interests"] == ["bouldering"]
    assert now["has_badge"] is True
    assert now["suggestion"] == ""


def test_in_common_is_counted_from_rows(world):
    """Was the constant 4. Here it is the accounts that vouched for both, and it moves."""
    client, people = world
    cara_token = None
    client.post("/v1/auth/register", json={"handle": "cara", "password": PW})
    cara_token = client.post("/v1/auth/login",
                             json={"handle": "cara", "password": PW}).json()["token"]
    cara = {"Authorization": f"Bearer {cara_token}"}

    before = client.get("/v1/connect/profile/bruno", headers=people["ana"]["h"]).json()
    assert before["in_common"] == 0

    client.post("/v1/trust/vouch", json={"for_account": "ana"}, headers=cara)
    client.post("/v1/trust/vouch", json={"for_account": "bruno"}, headers=cara)

    after = client.get("/v1/connect/profile/bruno", headers=people["ana"]["h"]).json()
    assert after["in_common"] == 1
    assert after["in_common_handles"] == ["cara"]


def test_your_own_profile_does_not_ask_who_you_both_know(world):
    """`trust.in_common` refuses a subject equal to the caller; the handler must not 400."""
    client, people = world
    body = client.get("/v1/connect/profile/ana", headers=people["ana"]["h"]).json()
    assert body["yourself"] is True
    assert body["in_common"] == 0


# ---- the claim -----------------------------------------------------------------------

def test_a_scan_records_a_vouch_that_both_sides_can_read(world):
    """Was a `proximity_encounter` row stamped `verified_via: "wearable_qr_scan"`.

    The replacement is the same row `/trust/vouch` writes, so the check is that the scanned
    account can see it under trust, attributed, with the disclaimer trust already carries.
    """
    client, people = world
    res = client.post("/v1/connect/scan-vouch", json={"scanned_handle": "bruno"},
                      headers=people["ana"]["h"])
    assert res.status_code == 200
    body = res.json()
    assert body["recorded"] is True
    assert body["scanned_handle"] == "bruno"
    assert body["for_account"] == people["bruno"]["id"]
    assert body["via"] == "shirt_code"
    assert body["vouch_id"]

    seen = client.post("/v1/trust/web-of-trust", json={"subject": "bruno"},
                       headers=people["bruno"]["h"]).json()
    assert seen["count"] == 1
    assert seen["vouchers"][0]["from_account"] == people["ana"]["id"]
    assert "scanned their shirt code" in seen["vouchers"][0]["note"]
    assert seen["verified"] is False
    assert trust.NOT_VERIFICATION in seen["disclaimer"]


def test_a_scan_claims_nothing_it_cannot_show(world):
    """`vouched: True`, `connected: True`, `karma_awarded: "+50 ..."`, `verified_via`.

    All four are gone, and the check runs on the body with its named prose fields removed
    so that the disclaimer — which contains the word "verifies" — cannot pass it by itself.
    """
    client, people = world
    body = client.post("/v1/connect/scan-vouch", json={"scanned_handle": "bruno"},
                       headers=people["ana"]["h"]).json()
    for banned in ("vouched", "connected", "karma_awarded", "verified_via",
                   "trust_score", "xp"):
        assert banned not in body

    claims = _prose_stripped(body).lower()
    for word in ("karma", "xp", "verified", "98%"):
        assert word not in claims


def test_scanning_the_same_person_twice_does_not_stack(world):
    """`trust.vouch` updates its own row on a repeat so a count of vouches counts people.

    A shirt in a crowded room gets read many times a second; without this, one evening
    would produce a hundred rows and the count under trust would be a count of frames.
    """
    client, people = world
    first = client.post("/v1/connect/scan-vouch", json={"scanned_handle": "bruno"},
                        headers=people["ana"]["h"]).json()
    second = client.post("/v1/connect/scan-vouch", json={"scanned_handle": "bruno"},
                         headers=people["ana"]["h"]).json()
    assert second["vouch_id"] == first["vouch_id"]
    assert first["already"] is False and second["already"] is True

    seen = client.post("/v1/trust/web-of-trust", json={"subject": "bruno"},
                       headers=people["bruno"]["h"]).json()
    assert seen["count"] == 1


def test_a_scan_of_a_handle_nobody_owns_is_a_404(world):
    client, people = world
    res = client.post("/v1/connect/scan-vouch", json={"scanned_handle": "nobody_at_all"},
                      headers=people["ana"]["h"])
    assert res.status_code == 404

    blank = client.post("/v1/connect/scan-vouch", json={}, headers=people["ana"]["h"])
    assert blank.status_code == 400


def test_a_scan_cannot_be_recorded_on_somebody_elses_behalf(world):
    """`scanner_id` came out of the body, so a caller could file another person's meeting."""
    client, people = world
    client.post("/v1/connect/scan-vouch",
                json={"scanned_handle": "bruno", "scanner_id": people["bruno"]["id"]},
                headers=people["ana"]["h"])
    given = client.get("/v1/trust/vouches", headers=people["bruno"]["h"]).json()
    assert given["count"] == 0


def test_you_cannot_scan_your_own_shirt(world):
    client, people = world
    res = client.post("/v1/connect/scan-vouch", json={"scanned_handle": "ana"},
                      headers=people["ana"]["h"])
    assert res.status_code == 400


# ---- nothing invented is left on disk -------------------------------------------------

def _code_without_prose(path: pathlib.Path) -> str:
    """One Python file with its docstrings and comments removed.

    The module and handler docstrings are this repo's changelog and are required to name
    what the prop claimed — so `"alex_v" not in source` would fail on the very sentence
    that records its removal. Unparsing the AST drops docstrings and comments and leaves
    the code, which is where a default that invents a person would have to live.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


# The four handlers this ticket owns. Named so the host check can look at exactly them:
# other handlers in `modules_api.py` quote the hosts they removed in their own docstrings
# and, in one case, still carry one.
OWNED_HANDLERS = ("get_vcard_qr_endpoint", "generate_wearable_tshirt_badge_endpoint",
                  "get_public_connect_profile_endpoint",
                  "record_wearable_scan_vouch_endpoint")


def _owned_handler_code() -> str:
    """Just those four handlers, without their docstrings."""
    tree = ast.parse((ROOT / "gateway/modules_api.py").read_text(encoding="utf-8"))
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in OWNED_HANDLERS:
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
            found[node.name] = ast.unparse(node)
    assert set(found) == set(OWNED_HANDLERS), sorted(set(OWNED_HANDLERS) - set(found))
    return "\n".join(found.values())


def test_no_invented_person_survives_in_code_or_in_the_pwa():
    """Defaults, `value=` attributes and JS fallbacks all named the same two strangers.

    Asserted against the files rather than a response because the handler's default was
    only reachable by omitting a field, and the dialog's were never sent to the gateway at
    all — a response-only check saw none of them.
    """
    app_js = (ROOT / "surfaces/app/www/app.js").read_text(encoding="utf-8")
    index = (ROOT / "surfaces/app/www/index.html").read_text(encoding="utf-8")
    code = "\n".join(_code_without_prose(ROOT / p) for p in
                     ("gateway/modules_api.py", "modules/wearables/tshirt_studio.py",
                      "modules/wearables/qr.py"))

    for invented in INVENTED:
        assert invented not in app_js, invented
        assert invented not in index, invented
        assert invented not in code, invented

    # The host check is scoped to what this ticket owns. Elsewhere in `app.js` and
    # `modules_api.py` these hosts appear in other handlers' changelog prose about removing
    # them — and one unrelated handler still returns one, which is T2's, not this ticket's.
    ours = "\n".join([
        app_js[app_js.index("/* ---- Camera scanner"):],
        index,
        _owned_handler_code(),
        # Stripped, because both module docstrings are required by the house style to name
        # the host they removed.
        _code_without_prose(ROOT / "modules/wearables/tshirt_studio.py"),
        _code_without_prose(ROOT / "modules/wearables/qr.py"),
    ])
    for host in NOT_OURS:
        assert host not in ours, host


def test_the_stored_fabrication_has_no_code_left():
    """`record_proximity_vouch` wrote `verified_via` onto a row. Nothing may call it."""
    source = _code_without_prose(ROOT / "modules/wearables/tshirt_studio.py")
    assert "record_proximity_vouch" not in source
    assert "proximity_encounter" not in source
    assert "verified_via" not in source
    assert not hasattr(tshirt_studio, "record_proximity_vouch")
    assert not hasattr(tshirt_studio, "_generate_qr_svg_matrix")

    api = _code_without_prose(ROOT / "gateway/modules_api.py")
    assert "record_proximity_vouch" not in api
    assert "generate_tshirt_design" not in api


def test_the_decoder_is_vendored_and_the_page_loads_it():
    """The scanner opened a camera and had nothing to read the picture with."""
    vendored = ROOT / "surfaces/app/www/vendor/jsQR.js"
    assert vendored.exists()
    source = vendored.read_text(encoding="utf-8")
    assert 'root["jsQR"] = factory()' in source
    assert "Apache License" in source

    index = (ROOT / "surfaces/app/www/index.html").read_text(encoding="utf-8")
    assert '<script src="vendor/jsQR.js"></script>' in index
    assert index.index('vendor/jsQR.js') < index.index('src="app.js"')

    app_js = (ROOT / "surfaces/app/www/app.js").read_text(encoding="utf-8")
    assert "window.jsQR(" in app_js
    assert "BarcodeDetector" in app_js
