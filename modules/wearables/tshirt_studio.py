"""A shirt with a code on it that opens your card — printed, and actually scannable.

The idea was sound and everything under it was a picture of the idea.

- **The code was not a code.** `_generate_qr_svg_matrix` drew a 25x25 grid from a SHA-256
  of the connect URL with finder patterns in three corners, in cyan and violet, with rounded
  modules. Nothing can scan it. The response still said "Instant camera scanning active"
  and `print_specs` offered it as print-ready at 300 dpi in "SVG Vector, High-Resolution
  PNG" — there was no PNG. See `modules/wearables/qr.py`; the encoder is `segno` now.
- **The URL pointed at a host this deployment does not serve.** `base_url` defaulted to
  `https://lifeos.app`. A shirt printed from that badge sends whoever scans it to somebody
  else's domain, permanently, on cotton.
- **The defaults invented a person.** `handle="alex_v"`, `name="Alex V."`,
  `tagline="AI Research · Surfing · Deep Work"`, and three interests. An account that
  posted an empty body got a stranger's shirt, and the same stranger's shirt as everybody
  else who posted an empty body. The handle is required now and everything else is blank
  until its owner types it.
- **`record_proximity_vouch` stored a fabrication.** It wrote a `proximity_encounter` row
  carrying `verified_via: "wearable_qr_scan"` and answered `vouched: True` with
  `karma_awarded: "+50 Real-World Connection Karma"`, for a handle the scanner never
  decoded — the scan button posted a fixed one. A stored false record is worse than a
  displayed one: once it is a row, no screen can tell it from a true one. It is gone.
  Scanning somebody's shirt is one person's claim that they met another, which is exactly
  what `modules/social/trust.py` already records, disclaimer and all, so the endpoint writes
  a vouch instead and this module has no vouch path at all.

What is left is a real generator: it takes what its owner typed, encodes a connect URL that
belongs to the gateway that served the request, and records what was printed so the card
that URL opens can be built from the same row rather than guessed.
"""

import base64
import urllib.parse

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph
from modules.wearables import qr

MODULE = "wearables.tshirt_studio"
SCOPES = {"content:read", "content:write"}

RECORD = "wearable_tshirt_badge"

# How the connect link is spelled when there is no absolute base to hang it on. Relative on
# purpose: the client knows its own origin and this app must never mint a host it does not
# serve. `gateway/main.py` builds `/invite/{token}` the same way.
CONNECT_PATH = "/#connect"

STYLES = ("streetwear_back", "minimal_chest", "cyberpunk_matrix")

MAX_TEXT = 120
MAX_INTERESTS = 3
MAX_BADGES_SCANNED = 50

# The badge is drawn on a 1000x1000 board and the QR occupies this square of it. A shirt is
# read from a couple of metres away in bad light, so the code gets the middle third rather
# than a corner.
QR_BOX = 340
QR_X = 330
QR_Y = 350


def _sys(graph: Graph):
    """Badges are system-owned and addressed by `account_id`, like a vouch or a kudos.

    A badge is the one row in this feature that a second person has to be able to read: it
    is printed on a shirt so that strangers can scan it, and `/connect/profile/{handle}`
    answers from it. A row kept in its author's private slice cannot be read by the person
    scanning it, and reaching into another account's slice to get at it is the thing this
    ticket exists to stop. Addressed rows live under `SYSTEM_OWNER` here for exactly that
    reason, and `account_id` on the row is what says whose it is.
    """
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _text(value, cap: int = MAX_TEXT) -> str:
    return str(value or "").strip()[:cap]


def _norm_handle(value) -> str:
    return _text(value, 80).lstrip("@").strip()


def connect_url(handle: str, base: str = "") -> str:
    """Where a scanned shirt sends somebody.

    `base` is the request's own base URL when the caller has one — a printed code has to be
    absolute or a phone camera has nowhere to go — and empty everywhere else, which yields a
    relative link. Neither branch can produce a host that was written down in this repo.
    """
    query = urllib.parse.urlencode({"handle": _norm_handle(handle)})
    base = str(base or "").rstrip("/")
    return f"{base}{CONNECT_PATH}?{query}"


def _pills(interests: list) -> str:
    tags = []
    for index, tag in enumerate(interests[:MAX_INTERESTS]):
        x = 120 + (index * 260)
        label = _escape(tag)
        tags.append(f"""
        <g transform="translate({x}, 830)">
            <rect x="0" y="0" width="230" height="46" rx="23" fill="#1e293b" stroke="#38bdf8" stroke-width="1.5"/>
            <text x="115" y="30" font-family="system-ui, -apple-system, sans-serif" font-size="16" font-weight="600" fill="#f8fafc" text-anchor="middle">{label}</text>
        </g>""")
    return "\n".join(tags)


def _escape(value: str) -> str:
    """XML-escape one field before it goes into the badge markup.

    Handles and taglines are user-typed and unrestricted, and this markup is handed back as
    a data URI the page renders. The old version interpolated all four fields raw, so an
    apostrophe broke the file and a `<` broke considerably more than that.
    """
    return (str(value or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _badge_svg(*, handle: str, name: str, tagline: str, interests: list,
               url: str) -> str:
    """The printable board: brand, the real code, and only the lines its owner filled in.

    Every text element below is conditional. The old design always drew a name, a tagline
    and three interest pills, so an account that supplied none of them still got a shirt
    with somebody's name on it. An empty field is left out rather than filled.
    """
    # The QR goes in as a nested `<svg>` with its own module-based viewBox, so its modules
    # land on exact boundaries whatever size the board is printed at. The opening tag is
    # rebuilt rather than patched: `qr.svg` already carries `width`/`height`, and an element
    # with two of either is not well-formed XML, which makes the whole board fail to load as
    # an image with no error anywhere near the cause.
    side = qr.modules(url) + qr.QUIET_ZONE * 2
    inner = qr.svg(url, scale=1)
    inner = inner[inner.index(">") + 1:]
    code = (f'<svg x="{QR_X}" y="{QR_Y}" width="{QR_BOX}" height="{QR_BOX}" '
            f'viewBox="0 0 {side} {side}" preserveAspectRatio="xMidYMid meet" '
            f'shape-rendering="crispEdges">{inner}')

    identity = f"@{_escape(handle)}"
    if name:
        identity = f"{_escape(name)} ({identity})"

    lines = [f'<text x="500" y="775" font-family="system-ui, -apple-system, sans-serif" '
             f'font-size="28" font-weight="700" fill="#ffffff" text-anchor="middle">{identity}</text>']
    if tagline:
        lines.append(f'<text x="500" y="808" font-family="system-ui, -apple-system, sans-serif" '
                     f'font-size="16" fill="#94a3b8" text-anchor="middle">{_escape(tagline)}</text>')

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000" width="1000" height="1000">
  <defs>
    <linearGradient id="bgGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#090d16"/>
      <stop offset="50%" stop-color="#0f172a"/>
      <stop offset="100%" stop-color="#1e1b4b"/>
    </linearGradient>
    <linearGradient id="nexusGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#38bdf8"/>
      <stop offset="50%" stop-color="#818cf8"/>
      <stop offset="100%" stop-color="#c084fc"/>
    </linearGradient>
    <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="8" result="blur" />
      <feComposite in="SourceGraphic" in2="blur" operator="over" />
    </filter>
  </defs>

  <rect width="1000" height="1000" rx="36" fill="url(#bgGrad)" stroke="#1e293b" stroke-width="3"/>

  <g transform="translate(500, 160)" filter="url(#glow)">
    <path d="M-60,-30 C-90,-60 -20,-75 0,-40 C20,-75 90,-60 60,-30 C30,0 70,45 45,65 C25,85 -10,60 0,40 C10,60 -25,85 -45,65 C-70,45 -30,0 -60,-30 Z" fill="none" stroke="url(#nexusGrad)" stroke-width="5"/>
    <circle cx="0" cy="0" r="8" fill="#f59e0b"/>
  </g>

  <text x="500" y="260" font-family="system-ui, -apple-system, sans-serif" font-size="34" font-weight="800" letter-spacing="4" fill="#f8fafc" text-anchor="middle">SCAN TO CONNECT</text>
  <text x="500" y="295" font-family="system-ui, -apple-system, sans-serif" font-size="17" font-weight="600" letter-spacing="3" fill="#38bdf8" text-anchor="middle">LIFEOS</text>

  <!-- White plate behind the code. A QR on a dark gradient does not binarise; the quiet
       zone has to be light or the symbol cannot be located at all. -->
  <rect x="{QR_X - 14}" y="{QR_Y - 14}" width="{QR_BOX + 28}" height="{QR_BOX + 28}" rx="18" fill="#ffffff" stroke="#38bdf8" stroke-width="2.5"/>
  {code}

  {chr(10).join(lines)}

  {_pills(interests)}

  <text x="500" y="930" font-family="system-ui, -apple-system, sans-serif" font-size="13" letter-spacing="1.5" fill="#64748b" text-anchor="middle">SCANNING THIS OPENS A PUBLIC CARD. IT VERIFIES NOTHING.</text>
</svg>"""


def generate_badge(graph: Graph, *, account_id: str, handle: str, name: str = "",
                   tagline: str = "", interests: list | None = None,
                   style: str = "streetwear_back", base_url: str = "",
                   source: str = MODULE) -> dict:
    """Print-ready board for one account's shirt, with a real code on it.

    `handle` is required and has no default. The row is addressed to the caller's account
    (see `_sys`) so `/connect/profile/{handle}` can show a tagline that its own subject
    wrote, and only that: captioning somebody with a badge a third party generated about
    them is the same class of mistake as the profile that invented one outright.
    """
    account_id = str(account_id or "").strip()
    if not account_id:
        raise ValueError("sign in first")
    handle = _norm_handle(handle)
    if not handle:
        raise ValueError("whose shirt is this?")
    if style not in STYLES:
        style = STYLES[0]

    name = _text(name)
    tagline = _text(tagline)
    interests = [_text(i, 40) for i in (interests or []) if _text(i, 40)][:MAX_INTERESTS]

    url = connect_url(handle, base_url)
    markup = _badge_svg(handle=handle, name=name, tagline=tagline,
                        interests=interests, url=url)
    encoded = base64.b64encode(markup.encode("utf-8")).decode("ascii")

    badge_id = _sys(graph).create_entity("content", {
        "type": RECORD, "account_id": account_id, "handle": handle,
        "name": name, "tagline": tagline, "interests": interests, "style": style,
        "connect_url": url, "created_at": now_iso(),
    }, source=source, confidence=1.0, owner_id=SYSTEM_OWNER)

    return {
        "badge_id": badge_id,
        "handle": handle,
        "name": name,
        "tagline": tagline,
        "interests": interests,
        "style": style,
        "connect_url": url,
        "svg": markup,
        "svg_data_uri": f"data:image/svg+xml;charset=utf-8;base64,{encoded}",
        "qr": qr.facts(url),
        "print_note": ("The board is vector and has no fixed size — it prints at whatever "
                       "the shop sets. Keep the white plate around the code: the light "
                       "border is part of the symbol, not a margin."),
        "note": ("The code opens a public card for this handle. It carries no identity "
                 "check and proves nothing about who is wearing the shirt."),
    }


def latest_badge(graph: Graph, account_id: str) -> dict | None:
    """The most recent badge one account generated *for itself*, or nothing.

    The match on `account_id` is the ownership check, and it is the whole point of this
    function. The handler it replaced searched by `handle` in the *caller's* slice, which
    meant it found the reader's own badges and never the subject's — and then invented a
    name, a tagline and three interests for the subject when it found none. A profile shows
    what its subject wrote about themselves or it shows nothing.
    """
    account_id = str(account_id or "").strip()
    if not account_id:
        return None
    rows = _sys(graph).find_entities(
        "content", {"type": RECORD, "account_id": account_id}, limit=MAX_BADGES_SCANNED)
    # `find_entities` orders by `created_at` ascending; regenerating a badge writes a new
    # row rather than overwriting the last, so the newest is the one that is on the shirt.
    return rows[-1] if rows else None
