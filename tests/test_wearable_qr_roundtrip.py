"""Out and back: the panel this gateway generates is decoded by the decoder it ships.

Everything else about this feature can be asserted in Python — a version number, a module
count, well-formed XML. None of that is the question anybody actually has, which is whether
a camera pointed at the shirt reads the handle back. The old badge would have passed every
structural check that could be written about it and was unreadable, so this is the test that
matters: render the returned SVG in a real browser exactly as the preview and the print do,
read the pixels, and run the vendored `jsQR` — the same file the PWA loads — over them.

A headless browser has no camera, so this is the only place the out->in path can be closed.
Rasterising is the half that the Python tests genuinely cannot do: an SVG that is malformed,
or whose modules land off the pixel grid, or whose code is drawn on a dark background,
produces a valid-looking file that no scanner reads. Each of those three was a real state of
this branch while it was being written.

Skipped rather than failed where Playwright or its Chromium is not installed: it is a
browser check, and a machine without a browser has not learned anything by failing it.
"""

import os
import pathlib
import shutil

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app

ROOT = pathlib.Path(__file__).resolve().parent.parent
JSQR = ROOT / "surfaces/app/www/vendor/jsQR.js"

CHROMIUM = os.environ.get(
    "LIFEOS_TEST_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")

PW = "correct-horse-battery"

# Draw the 1000x1000 panel at its own size. Smaller and the QR's modules stop landing on
# whole pixels, which is a real failure mode for a printed code but not the one under test.
CANVAS = 1000

# One expression, evaluated in the page: SVG -> <img> -> canvas -> pixels -> jsQR.
DECODE = """
async (svg) => {
  const url = URL.createObjectURL(new Blob([svg], {type: "image/svg+xml"}));
  const img = new Image();
  await new Promise((ok, no) => {
    img.onload = ok;
    // An SVG that is not well-formed fails here and nowhere else: the browser reports
    // nothing and simply declines to paint it.
    img.onerror = () => no(new Error("the browser could not load the panel as an image"));
    img.src = url;
  });
  const cv = document.createElement("canvas");
  cv.width = %d; cv.height = %d;
  const ctx = cv.getContext("2d");
  // White underneath, the way paper and a screen both are. Without it the canvas starts
  // transparent and any transparent pixel binarises unpredictably.
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, cv.width, cv.height);
  ctx.drawImage(img, 0, 0, cv.width, cv.height);
  const px = ctx.getImageData(0, 0, cv.width, cv.height);
  const hit = window.jsQR(px.data, px.width, px.height, { inversionAttempts: "dontInvert" });
  return hit ? hit.data : null;
}
""" % (CANVAS, CANVAS)


@pytest.fixture(autouse=True)
def _no_ambient_limits(monkeypatch):
    monkeypatch.setenv(rate_limiter.DISABLE_VAR, "1")


@pytest.fixture(scope="module")
def page_decoder():
    """A blank page with the app's own vendored decoder in it."""
    sync_playwright = pytest.importorskip(
        "playwright.sync_api", reason="playwright is a dev dependency"
    ).sync_playwright
    if not (pathlib.Path(CHROMIUM).exists() or shutil.which("chromium")):
        pytest.skip(f"no chromium at {CHROMIUM}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=CHROMIUM if pathlib.Path(CHROMIUM).exists() else None,
            args=["--no-first-run", "--disable-background-networking",
                  "--disable-component-update"])
        page = browser.new_page()
        page.set_content("<!doctype html><meta charset=utf-8><body></body>")
        page.add_script_tag(content=JSQR.read_text(encoding="utf-8"))
        assert page.evaluate("typeof window.jsQR") == "function"
        yield page
        browser.close()


@pytest.fixture
def signed_in(cfg):
    client = TestClient(create_app(cfg))
    client.post("/v1/auth/register", json={"handle": "ana", "password": PW})
    token = client.post("/v1/auth/login",
                        json={"handle": "ana", "password": PW}).json()["token"]
    return client, {"Authorization": f"Bearer {token}"}


def test_the_panel_this_gateway_generates_decodes_back_to_its_connect_url(
        signed_in, page_decoder):
    client, headers = signed_in
    body = client.post("/v1/wearables/tshirt-badge",
                       json={"handle": "ana", "name": "Ana", "tagline": "pottery",
                             "interests": ["pottery", "cold water"]},
                       headers=headers).json()

    decoded = page_decoder.evaluate(DECODE, body["svg"])
    assert decoded == body["connect_url"]

    # And the URL is one the scanner can act on: the handle comes back out of it.
    assert decoded.endswith("/#connect?handle=ana")


def test_the_vcard_code_decodes_back_to_the_vcard(signed_in, page_decoder):
    """`/people/qr` answered with a vCard and no image at all."""
    client, headers = signed_in
    body = client.get("/v1/people/qr", headers=headers).json()
    assert page_decoder.evaluate(DECODE, body["qr_svg"]) == body["vcard"]


def test_a_handle_with_characters_that_break_markup_still_decodes(signed_in, page_decoder):
    """The panel interpolates the handle into SVG text and into the encoded URL.

    Both were raw before. An unescaped `&` makes the file unloadable, which shows up as a
    blank preview rather than an error, and a percent-encoding mistake in the URL yields a
    code that scans to the wrong handle — worse than one that does not scan.
    """
    client, headers = signed_in
    client.post("/v1/auth/register", json={"handle": "a&b c", "password": PW})
    body = client.post("/v1/wearables/tshirt-badge", json={"handle": "a&b c"},
                       headers=headers).json()
    assert page_decoder.evaluate(DECODE, body["svg"]) == body["connect_url"]
    assert "handle=a%26b+c" in body["connect_url"]
