"""Sharing, pairing and being early — the three things the growth props pretended to do.

Every endpoint in this family handed back a URL on `connectos.app`, a domain this
deployment does not serve, for a resource that was never created:

- `/viral/invite-crew` returned `invite_code: "CREW-LISBON-8921"` — the same code for every
  crew on every instance — plus `bonus_karma: 100` and a free-coffee voucher from a rewards
  programme that does not exist and that nobody has agreed to fund.
- `/viral/social-share` returned `story_card_url: ".../story-sunset-88.png"`, a 1080x1920
  image that was never rendered, with an "embedded QR code" at another URL that was also
  never rendered.
- `/nfc/tap-to-synergy` reported a **94% compatibility score** with a named stranger and
  three shared passions, for any peer string you sent, over a protocol ("NFC & Apple
  NameDrop Ephemeral Handshake") that a web app cannot speak.
- `/seeding/pioneer-pass` minted "City Pioneer #042" with a year of free VIP.

What is left when the invented rewards and the invented image host are removed is still
worth having, and all three of these are real:

- **Being early is a fact**, not a badge. Your position among the people who have shown up
  in a city is countable, so it is counted — and it comes with nothing attached, because
  perks are a promise only the operator can make.
- **A share card can be drawn here.** There is no rasteriser in this app, so there is no
  PNG; an SVG is a real image that this process can actually produce, and it carries the
  real link rather than a picture of one.
- **Two phones cannot tap**, but two people standing together can read a short code aloud.
  That is the honest shape of the same idea, and unlike the prop it ends with the two
  accounts actually knowing about each other.
"""

import datetime
import secrets

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

from modules.city import chat

MODULE = "growth.share"
SCOPES = {"content:read", "content:write"}
PAIRING = "pairing_code"

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # no I/L/O/0/1 — these get read aloud
CODE_LENGTH = 6
CODE_MINUTES = 10
MAX_TEXT = 120


class ShareError(ValueError):
    """Something that cannot be shared, paired or counted."""


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse(stamp: str):
    try:
        return datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _text(value, cap: int = MAX_TEXT) -> str:
    return str(value or "").strip()[:cap]


# ---- being early -------------------------------------------------------------

def standing(graph: Graph, city: str, *, account_id: str) -> dict:
    """Where you come in the order of people who have shown up in this city.

    The prop minted "City Pioneer #042 · Lisbon" with a year of free VIP and complimentary
    coffee at partner roasters — perks nobody had agreed to provide, attached to a number
    that was whatever the caller sent. The number is real here and there is nothing attached
    to it, because a fact about when you arrived is the app's to state and a reward is not.
    """
    if not account_id:
        raise ShareError("sign in first")
    if not str(city or "").strip():
        raise ShareError("which city?")
    room = chat.slug(city)

    # Anyone who has published a signal, posted in the room, or reviewed a place here.
    session = _sys(graph)
    first_seen: dict[str, str] = {}
    for kind, field in (("synergy_signal", "account_id"), ("city_message", "account_id"),
                        ("city_moment", "account_id"), ("place_review", "author_account")):
        for row in session.find_entities("content", {"type": kind, "city": room}, limit=800):
            who = row["attrs"].get(field, "")
            when = row["attrs"].get("created_at", "")
            if not who or not when:
                continue
            if who not in first_seen or when < first_seen[who]:
                first_seen[who] = when

    order = sorted(first_seen.items(), key=lambda kv: kv[1])
    position = next((i + 1 for i, (who, _) in enumerate(order) if who == account_id), 0)
    return {"city": room, "people_here": len(order),
            "your_position": position or None,
            "you_are_here": bool(position),
            "since": first_seen.get(account_id, ""),
            # The whole of the honest version: a count, and no badge.
            "no_perks": ("Nothing is unlocked by being early. This is a count of people, "
                         "not a membership tier."),
            "note": ("You have not posted or published anything here yet, so you are not "
                     "in the count." if not position else "")}


# ---- a share card that this process can actually draw ------------------------

def _svg_escape(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def card(title: str, *, subtitle: str = "", link: str = "", footer: str = "") -> dict:
    """An SVG share card carrying the real link.

    `story_card_url` pointed at a PNG on a host this deployment does not serve, for an image
    nothing ever rendered. There is no rasteriser here — no Pillow, no headless browser in
    the request path — so a PNG would be another promise. An SVG is a real image this
    process can produce, it is self-contained, and every value in it is escaped, because a
    title is user input and an SVG is markup.
    """
    title = _text(title, 80)
    if not title:
        raise ShareError("what are you sharing?")
    subtitle, link, footer = _text(subtitle, 80), _text(link, 200), _text(footer, 60)

    lines, current = [], ""
    for word in title.split():
        if len(current) + len(word) + 1 > 22 and current:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    lines.append(current)
    lines = lines[:3]

    body = "".join(
        f'<text x="80" y="{620 + i * 96}" font-size="76" font-weight="700" '
        f'fill="#ffffff">{_svg_escape(line)}</text>' for i, line in enumerate(lines))
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1920" '
        'viewBox="0 0 1080 1920">'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#1b1033"/><stop offset="1" stop-color="#0b1020"/>'
        '</linearGradient></defs>'
        '<rect width="1080" height="1920" fill="url(#g)"/>'
        f'<text x="80" y="480" font-size="34" letter-spacing="6" fill="#a5b4fc">'
        f'{_svg_escape(subtitle.upper())}</text>'
        f'{body}'
        f'<text x="80" y="{640 + len(lines) * 96}" font-size="34" fill="#c7d2fe">'
        f'{_svg_escape(link)}</text>'
        f'<text x="80" y="1800" font-size="30" fill="#8b93a7">'
        f'{_svg_escape(footer or "LifeOS")}</text>'
        '</svg>')

    return {"title": title, "svg": svg, "format": "1080x1920 SVG",
            "link": link,
            # No QR: encoding one needs a library this app does not carry, and a URL to a
            # QR service would hand the link and the viewer's address to a third party.
            "qr": None,
            "rendered_here": True,
            "note": "An SVG, drawn here — nothing in this app rasterises images."}


# ---- pairing, which is what "tap" can honestly mean --------------------------

def open_code(graph: Graph, *, account_id: str, handle: str = "",
              source: str = MODULE) -> dict:
    """Show a short code to somebody standing next to you.

    `/nfc/tap-to-synergy` claimed an "NFC & Apple NameDrop Ephemeral Handshake" and returned
    a 94% compatibility score with three shared passions, for any peer name you sent. A web
    app cannot speak NFC or NameDrop, nobody was on the other end, and the score was a
    constant.

    Two people in the same room can still exchange six characters, which is the same idea
    with none of the fiction. The code is short because it gets read aloud, so it is also
    short-lived and single-use: six characters is guessable given long enough, and ten
    minutes is not long enough.
    """
    if not account_id:
        raise ShareError("sign in first")
    session = _sys(graph)
    for row in session.find_entities("content", {"type": PAIRING, "account_id": account_id},
                                     limit=20):
        if _live(row["attrs"]):
            session.update_entity(row["id"], {"used": True}, source=source)

    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    session.create_entity("content", {
        "type": PAIRING, "code": code, "account_id": account_id,
        "handle": _text(handle, 80), "created_at": now_iso(),
        "expires_at": (_now() + datetime.timedelta(minutes=CODE_MINUTES)).isoformat(),
        "used": False,
    }, source=source, owner_id=SYSTEM_OWNER)
    return {"code": code, "expires_in_minutes": CODE_MINUTES, "single_use": True,
            "instructions": f"Read this to them. It works once, for {CODE_MINUTES} minutes.",
            "no_nfc": ("There is no tap: a web app cannot speak NFC or NameDrop. This is "
                       "the same exchange, out loud.")}


def _live(attrs: dict, now=None) -> bool:
    if attrs.get("used"):
        return False
    expires = _parse(attrs.get("expires_at", ""))
    return bool(expires and expires > (now or _now()))


def redeem_code(graph: Graph, code: str, *, account_id: str, handle: str = "",
                source: str = MODULE) -> dict:
    """Take somebody's code. Both of you end up knowing about the other.

    Returns what you two actually have in common — from what you have both published — or
    says plainly that it is nothing yet. Never a percentage: there is no model behind a
    compatibility score, and 94% was a literal.
    """
    if not account_id:
        raise ShareError("sign in first")
    code = str(code or "").strip().upper()
    if not code:
        raise ShareError("which code?")

    session = _sys(graph)
    hits = session.find_entities("content", {"type": PAIRING, "code": code}, limit=5)
    row = next((h for h in hits if _live(h["attrs"])), None)
    if row is None:
        # One message for wrong, expired and already-used, so the code space cannot be
        # probed for which codes exist.
        raise ShareError("that code is not valid")
    peer = row["attrs"].get("account_id", "")
    if peer == account_id:
        raise ShareError("that is your own code")

    session.update_entity(row["id"], {"used": True, "used_by": account_id,
                                      "used_at": now_iso()}, source=source)
    return {"paired": True, "peer_account": peer,
            "peer_handle": row["attrs"].get("handle") or "someone",
            "shared": _shared_ground(graph, account_id, peer),
            # User-facing copy says what is true now. What it replaces belongs in the
            # docstring — a reader of this screen has no idea what "this replaces" means.
            "no_score": "No compatibility score — nothing in this app measures that.",
            "next": "You can find each other by handle now."}


def _shared_ground(graph: Graph, a: str, b: str) -> list[str]:
    """What two people have both published, if anything. Facts, not inference."""
    from modules.city import synergy

    def activities(person: str) -> set:
        out = set()
        for row in Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(
                MODULE, SCOPES).find_entities(
                    "content", {"type": synergy.RECORD, "account_id": person}, limit=100):
            if not row["attrs"].get("withdrawn"):
                out |= synergy.terms(row["attrs"].get("activity", ""))
        return out

    return sorted(activities(a) & activities(b))
