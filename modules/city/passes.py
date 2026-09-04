"""A wallet pass for something that exists.

The pass payload itself was already honest — a real PKPass JSON, base64'd into a data URI,
so what comes back is an artefact rather than a link to a file on a host this deployment
does not serve. Two things around it were not:

- `event_name` came from the request body and nothing else, so an empty body minted a pass
  for `""`, and any string minted a pass for an event that had never existed.
- The serial number and the entry field were constants: `VIP-KARMA-98` and "VIP FAST-PASS",
  identical on every pass on every deployment. A serial number that is the same for everyone
  identifies nothing, and "VIP FAST-PASS" is a claim about a door this app has no
  relationship with.

So a pass is built from a row or not at all. The lookup takes a meetup id (the city surface's
own object) or an event id in the caller's own slice, and an id that matches neither is
`UnknownEvent` — a 404 at the gateway, because the honest answer to "make me a pass for
this" when there is no this is that it was not found.

The serial is the row's own id, which is unique per gathering and already exists. Nothing is
minted: `modules/crews/invites.py` mints capability tokens and hashes them, and that machinery
is for things that grant access. A wallet pass here grants nothing and says so.
"""

import base64
import json

from substrate import SYSTEM_OWNER
from substrate.graph import Graph

from modules.city import meetups

MODULE = "city.passes"
SCOPES = {"content:read", "events:read"}

#: Apple's own type identifier field. Named after this app rather than a store identity it
#: does not have — there is no signing certificate here, so no real pass type id exists.
PASS_TYPE = "pass.os.life.event"
ORGANIZATION = "LifeOS"

NOT_SIGNED = ("This is the pass payload, not a signed .pkpass bundle: signing needs an "
              "Apple certificate, which is not in this repo. It grants no entry to "
              "anywhere.")


class PassError(ValueError):
    """A pass that cannot be built from what was given."""


class UnknownEvent(LookupError):
    """No meetup and no event with that id — a 404, not a 400."""


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def _find(graph: Graph, event_id: str) -> dict:
    """The meetup or event this id names, in that order, or `UnknownEvent`."""
    event_id = str(event_id or "").strip()
    if not event_id:
        raise PassError("which event? pass `meetup_id` or `event_id`")

    row = _sys(graph).get_entity(event_id)
    if row is not None and row["attrs"].get("type") == meetups.RECORD:
        attrs = row["attrs"]
        return {"kind": "meetup", "id": row["id"], "title": attrs.get("title", ""),
                "place": attrs.get("place", ""), "starts_at": attrs.get("starts_at", ""),
                "host": attrs.get("organiser_handle") or "",
                "cancelled": bool(attrs.get("cancelled"))}

    own = graph.session(MODULE, SCOPES).get_entity(event_id)
    if own is not None and own.get("kind") == "event":
        attrs = own["attrs"]
        return {"kind": "event", "id": own["id"], "title": attrs.get("title", ""),
                "place": attrs.get("place", ""), "starts_at": attrs.get("start", ""),
                "host": "", "cancelled": attrs.get("status", "") == "cancelled"}

    raise UnknownEvent(event_id)


def payload(found: dict) -> dict:
    """The PKPass JSON for a row that exists. Every field comes off the row."""
    fields = [{"key": "event", "label": "EVENT", "value": found["title"]}]
    secondary = []
    if found.get("place"):
        secondary.append({"key": "place", "label": "WHERE", "value": found["place"]})
    if found.get("starts_at"):
        secondary.append({"key": "when", "label": "WHEN", "value": found["starts_at"]})
    if found.get("host"):
        secondary.append({"key": "host", "label": "ORGANISER", "value": found["host"]})

    return {
        "formatVersion": 1,
        "passTypeIdentifier": PASS_TYPE,
        # The row's own id: unique per gathering, and it already exists. The old one was
        # the same string on every pass.
        "serialNumber": found["id"],
        "organizationName": ORGANIZATION,
        "description": found["title"],
        "foregroundColor": "rgb(255, 255, 255)",
        "backgroundColor": "rgb(30, 41, 59)",
        "eventTicket": {"primaryFields": fields, "secondaryFields": secondary},
    }


def wallet_pass(graph: Graph, event_id: str) -> dict:
    """Build a pass for a real row, or fail to find one."""
    found = _find(graph, event_id)
    if not found["title"]:
        raise PassError("that has no title to put on a pass")
    if found["cancelled"]:
        raise PassError("that one was called off")

    body = json.dumps(payload(found))
    encoded = base64.b64encode(body.encode("utf-8")).decode("ascii")

    return {"pass_generated": True, "kind": found["kind"], "event_id": found["id"],
            "event_name": found["title"], "place": found.get("place", ""),
            "starts_at": found.get("starts_at", ""),
            "pkpass_url": f"data:application/vnd.apple.pkpass;base64,{encoded}",
            "signed": False, "grants_entry": False, "not_signed": NOT_SIGNED}
