"""A QR code that is a QR code.

The wearable studio used to draw its own: `_generate_qr_svg_matrix` took a SHA-256 of the
connect URL, turned the hex digits into a 25x25 field of squares, and painted finder
patterns into three corners so the result read as a QR at a glance. It encoded nothing.
There is no version, no format information, no timing pattern, no alignment pattern and no
error correction in a hash — the bits are simply not a QR symbol — so no scanner has ever
read one, and none ever could. The response shipped next to it said "Instant camera
scanning active", and the studio offered the file as print-ready. Somebody could have paid
a print shop for a hundred shirts carrying a picture of a barcode.

That is the specific failure this repo keeps finding: a thing that photographs well and does
nothing. So the encoder is not ours. `segno` is pure Python, has no system dependencies, and
implements the actual specification; this module is a thin wrapper over it that fixes the
two decisions the rest of the app should not have to repeat:

- **Error level M or better.** A shirt creases, folds and gets photographed at an angle in
  a bar. L (7%) is for clean flat print; M (15%) is the level that survives fabric without
  inflating the symbol enough to need a bigger chest panel. segno raises it above M when a
  short payload leaves room in the same version, so `facts()` reports the level that was
  actually used rather than the one that was asked for.
- **Square modules, real quiet zone, pure black on pure white.** A QR is a contrast
  measurement before it is data. The old drawing used `#38bdf8`, `#c084fc` and rounded
  corners with a 0.92 fill factor, which is a decorative choice a binariser cannot undo.
  The four-module quiet zone is part of the symbol, not a margin — a code printed flush to
  the edge of a panel fails to locate.

`svg()` emits a self-contained SVG whose `viewBox` is in *modules*, one unit per module, so
a caller can drop it into a larger design at any size without recomputing anything, and the
run-length merge along each row keeps the badge markup small enough to sit in a data URI.
"""

import base64

import segno

# The *minimum* recovery level: 15%. A shirt creases and gets photographed at an angle, so L
# is not enough; H doubles the module count for a payload this size and a denser symbol on
# fabric is a worse trade than more redundancy.
#
# It is a minimum rather than an exact level because segno raises it for free when a shorter
# payload leaves room in the same version — which is why `facts()` reports the level the
# encoder actually used rather than echoing this constant back. A response that said "M"
# while the symbol was Q would be a small invented fact of exactly the kind this file exists
# to remove.
ERROR_LEVEL = "m"

# Modules of light around the symbol. Four is what the specification requires; less is the
# most common reason a printed code will not locate.
QUIET_ZONE = 4

DARK = "#000000"
LIGHT = "#ffffff"


def symbol(text: str):
    """The encoded symbol itself, for callers that need its version or module count.

    Returned rather than hidden so tests can assert on the real thing — a QR's version and
    module count are derived from the payload, so pinning them is how you tell an encoder
    from a drawing.
    """
    text = str(text or "")
    if not text.strip():
        raise ValueError("nothing to encode")
    return segno.make(text, error=ERROR_LEVEL)


def modules(text: str) -> int:
    """Modules along one side, quiet zone excluded (4 x version + 17)."""
    return symbol(text).symbol_size(scale=1, border=0)[0]


def svg(text: str, *, scale: int = 8, dark: str = DARK, light: str = LIGHT,
        border: int = QUIET_ZONE) -> str:
    """One QR symbol as a standalone SVG document.

    The `viewBox` counts modules, not pixels, and `width`/`height` are `scale` pixels per
    module — so the same string is both a correctly proportioned image at a default size and
    something a larger design can scale freely without the modules drifting off the grid.
    `shape-rendering="crispEdges"` is not decoration: antialiasing along module boundaries
    is what turns a small code into an unreadable one.
    """
    qr = symbol(text)
    border = max(0, int(border))
    rows = [bytearray(row) for row in qr.matrix]
    side = len(rows) + border * 2
    pixels = side * max(1, int(scale))

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {side} {side}" '
        f'width="{pixels}" height="{pixels}" shape-rendering="crispEdges" '
        f'role="img" aria-label="QR code">',
        f'<rect x="0" y="0" width="{side}" height="{side}" fill="{light}"/>',
    ]
    for r, row in enumerate(rows):
        c = 0
        width = len(row)
        while c < width:
            if not row[c]:
                c += 1
                continue
            run = 1
            while c + run < width and row[c + run]:
                run += 1
            parts.append(f'<rect x="{c + border}" y="{r + border}" width="{run}" '
                         f'height="1" fill="{dark}"/>')
            c += run
    parts.append("</svg>")
    return "".join(parts)


def data_uri(text: str, *, scale: int = 8, dark: str = DARK, light: str = LIGHT,
             border: int = QUIET_ZONE) -> str:
    """The same SVG as a `data:` URI, for an `<img>` the page can render with no request.

    Base64 rather than percent-encoded: the markup contains `#`, `"` and `<`, and a URI-
    escaped variant of it has been mis-copied into an `src` attribute in this repo before.
    """
    markup = svg(text, scale=scale, dark=dark, light=light, border=border)
    encoded = base64.b64encode(markup.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;charset=utf-8;base64,{encoded}"


def facts(text: str) -> dict:
    """What the code actually is, for a response that would otherwise have to claim it.

    The old badge said "Instant camera scanning active" and offered no way to check. These
    four numbers are checkable: re-encode the same string and you get the same version and
    the same module count, and a scanner reads the payload back.
    """
    qr = symbol(text)
    return {"version": qr.version, "error_correction": qr.error,
            "modules": qr.symbol_size(scale=1, border=0)[0],
            "quiet_zone_modules": QUIET_ZONE, "encodes": str(text)}
