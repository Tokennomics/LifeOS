"""A plugin registry — what is registered, by whom, and what it asked for.

`GET /developer/plugins` returned four plugins with developers, categories, install counts
and ratings out of five: KiteSurf Wind Radar by WindyDev Labs, Padel 4th Player Finder by
PadelClub EU. None of them exist. `POST /developer/plugins/register` returned
`registered: True` and a slugified id, and stored nothing — so a developer would "register"
their plugin, see it succeed, and never find it again.

This stores registrations, validated against the manifest schema the platform module has had
since Sprint 1 and which the endpoint never called.

**What it deliberately does not do is run anything.** `POST /developers/plugin-sandbox`
reported `simulation_status: "PASSED (100% telemetry accuracy)"` and
`store_status: "PUBLISHED_TO_COMMUNITY_STORE"` for any id. Executing third-party code inside
a process that holds every user's graph is not a feature to approximate — a sandbox that is
only *called* a sandbox is the most dangerous possible version of this. So the check
validates the manifest and reports the scopes the plugin is asking for, in plain words, and
says outright that nothing was executed. Knowing what a plugin *wants* before installing it
is most of the value and none of the risk.

There is no store, no rev-share and no rating. Ratings need users, and a rating out of five
on a plugin nobody has installed is the same invention as a 96% match.
"""

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

from modules.platform import manifest as manifest_mod

MODULE = "platform.plugins"
SCOPES = {"content:read", "content:write"}
RECORD = "plugin"

MAX_LISTED = 100
MAX_PER_ACCOUNT = 20

# What each scope actually lets a plugin reach, in words a person can weigh. A permission
# screen that shows `content:write` and nothing else is a permission screen nobody reads.
SCOPE_MEANING = {
    "content:read": "read your notes, captures and saved content",
    "content:write": "create and change your notes and content",
    "events:read": "read your calendar and the events you are going to",
    "events:write": "add and change events on your calendar",
    "people:read": "read the people you track and how long since you saw them",
    "people:write": "add and change the people you track",
    "tasks:read": "read your tasks",
    "tasks:write": "add and change your tasks",
}


class PluginError(ValueError):
    """A plugin that cannot be registered."""


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def explain(scopes) -> list[dict]:
    """Every requested scope, with what it means and whether we recognise it at all.

    An unknown scope is reported rather than dropped: a manifest asking for something this
    app has never heard of is exactly the thing an installer should see.
    """
    out = []
    for scope in scopes or []:
        name = str(scope)
        out.append({"scope": name,
                    "means": SCOPE_MEANING.get(name, "unrecognised — this app has no such "
                                                     "permission, so it grants nothing"),
                    "known": name in SCOPE_MEANING})
    return out


def register(graph: Graph, plugin_manifest: dict, *, account_id: str,
             source: str = MODULE) -> dict:
    """Validate a manifest and store the registration.

    Re-registering the same name from the same account updates it, so publishing a new
    version is not a duplicate entry.
    """
    if not account_id:
        raise PluginError("sign in first")
    try:
        checked = manifest_mod.validate_manifest(plugin_manifest)
    except ValueError as exc:
        raise PluginError(str(exc))

    session = _sys(graph)
    mine = [p for p in session.find_entities(
        "content", {"type": RECORD, "account_id": account_id}, limit=100)
        if not p["attrs"].get("removed")]
    existing = next((p for p in mine if p["attrs"].get("name") == checked["name"]), None)
    if existing is None and len(mine) >= MAX_PER_ACCOUNT:
        raise PluginError(f"{MAX_PER_ACCOUNT} plugins is enough for one account")

    attrs = {
        "type": RECORD, "name": checked["name"], "version": checked["version"],
        "scopes": checked["scopes"], "bus_topics": checked["bus_topics"],
        "token_budget": checked["token_budget"],
        "description": str(plugin_manifest.get("description", ""))[:300],
        "account_id": account_id, "removed": False, "updated_at": now_iso(),
    }
    if existing is not None:
        session.update_entity(existing["id"], attrs, source=source)
        plugin_id, created = existing["id"], False
    else:
        plugin_id = session.create_entity("content", {**attrs, "created_at": now_iso()},
                                          source=source, owner_id=SYSTEM_OWNER)
        created = True

    return {
        "registered": True, "plugin_id": plugin_id, "created": created,
        "name": checked["name"], "version": checked["version"],
        "permissions": explain(checked["scopes"]),
        # Said plainly, because the old response implied all three.
        "executed": False, "published": False, "rev_share": None,
        "note": ("Registered only. Nothing was run, there is no store to publish to, and "
                 "there is no revenue share."),
    }


def _render(row: dict) -> dict:
    attrs = row["attrs"]
    return {"plugin_id": row["id"], "name": attrs.get("name", ""),
            "version": attrs.get("version", ""),
            "description": attrs.get("description", ""),
            "scopes": attrs.get("scopes", []),
            "permissions": explain(attrs.get("scopes", [])),
            "account_id": attrs.get("account_id", ""),
            "updated_at": attrs.get("updated_at", "")}


def listing(graph: Graph, *, account_id: str = "", limit: int = MAX_LISTED) -> dict:
    """Registered plugins. Mine only when an account is given, otherwise all of them —
    registrations are public by design, since the point is that somebody can look one up
    before installing it."""
    query = {"type": RECORD}
    if account_id:
        query["account_id"] = account_id
    rows = [r for r in _sys(graph).find_entities("content", query, limit=MAX_LISTED * 2)
            if not r["attrs"].get("removed")]
    plugins = [_render(r) for r in rows]
    plugins.sort(key=lambda p: p["name"].lower())
    return {"plugins": plugins[:limit], "empty": not plugins,
            # There were four, with ratings, on an empty database.
            "no_ratings": "Nobody has rated these. Ratings need users.",
            "suggestion": "" if plugins else (
                "No plugins registered on this instance yet.")}


def remove(graph: Graph, plugin_id: str, *, account_id: str,
           source: str = MODULE) -> dict:
    session = _sys(graph)
    row = session.get_entity(plugin_id)
    if row is None or row["attrs"].get("type") != RECORD:
        raise PluginError("unknown plugin")
    if row["attrs"].get("account_id") != account_id:
        raise PluginError("that plugin is not yours")
    session.update_entity(plugin_id, {"removed": True}, source=source)
    return {"removed": True, "plugin_id": plugin_id}


def check(graph: Graph, *, plugin_id: str = "", plugin_manifest: dict | None = None) -> dict:
    """What a plugin is asking for — without running a line of it.

    The honest replacement for a "sandbox" that reported a passing simulation for any id.
    Answers the question an installer actually has: what would this be allowed to touch?
    """
    if plugin_manifest is not None:
        try:
            checked = manifest_mod.validate_manifest(plugin_manifest)
        except ValueError as exc:
            return {"valid": False, "reason": str(exc), "executed": False}
        scopes, name, version = checked["scopes"], checked["name"], checked["version"]
    else:
        row = _sys(graph).get_entity(plugin_id) if plugin_id else None
        if row is None or row["attrs"].get("type") != RECORD:
            raise PluginError("unknown plugin")
        attrs = row["attrs"]
        scopes, name, version = attrs.get("scopes", []), attrs.get("name", ""), attrs.get("version", "")

    unknown = [s["scope"] for s in explain(scopes) if not s["known"]]
    return {
        "valid": True, "name": name, "version": version,
        "permissions": explain(scopes),
        "unrecognised_scopes": unknown,
        # The three claims the old endpoint made, each refused by name.
        "executed": False, "simulated": False, "published": False,
        "why": ("Nothing was run. Executing third-party code in the process that holds "
                "every user's graph is not something to approximate, and a sandbox that is "
                "only called a sandbox is the most dangerous version of this. What you get "
                "is what the plugin is asking for, before you decide."),
    }
