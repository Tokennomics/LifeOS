"""Everything you own, as Markdown you can walk away with.

`/export/universal-markdown` reported `export_complete: True`, 48 vault files, "42 connected
friends, mentors & squad members with bilateral trust indices", "18 saved hidden gems, vinyl
lofts & speakeasy access passcodes" — and a `download_url` pointing at a zip on
connectos.app that was never written, on a host this deployment does not serve. The
`sample_markdown_preview` was a hand-written note about a day in Munich with a
`presence_score: 98.5%` in its frontmatter.

Nothing was exported. Somebody who clicked that and believed it had their data safe.

The real thing matters more than most features here, because it is the promise that using
this app is not a trap: whatever you put in, you can take out, in a format that opens
anywhere. So this walks the account's own rows and emits real Markdown, right now, in the
response — no zip, no background job, no URL to a file that has to exist later.

- **It is your data, not a summary of it.** Every row the account owns, grouped by kind.
- **The counts are counts.** `files` is how many documents were produced, because it was
  written by counting them.
- **Nothing is scored.** No presence score, no trust index — this app computes neither.
- **Nothing leaves the process.** The Markdown is returned; where it goes next is yours to
  decide. An export that quietly uploads somewhere is the opposite of portability.
"""

import datetime

from substrate.graph import Graph

MODULE = "personal.export"
SCOPES = {"content:read", "events:read", "metrics:read", "tasks:read", "goals:read",
          "people:read", "places:read"}

MAX_ROWS = 2000
MAX_FIELD = 2000

# What each stored `type` is called in a document somebody reads. Anything not listed still
# exports — under its raw type — because dropping rows from an export to keep it tidy is how
# an export quietly stops being one.
SECTIONS = {
    "reflection": "Reflections",
    "checkin": "Check-ins",
    "city_moment": "Moments",
    "place_review": "Reviews",
    "kudos": "Kudos",
    "reminder": "Reminders",
    "tab_entry": "Shared tab",
    "crew": "Crews",
    "city_message": "City chat",
    "synergy_signal": "Published intents",
    "meetup": "Meetups",
}

# Never exported, because they are credentials or their hashes rather than anybody's data.
SECRETS = {"account", "auth_session", "crew_invite", "api_key", "calendar_feed_token",
           "pairing_code", "webhook_endpoint"}


class ExportError(ValueError):
    """An export that cannot be produced."""


def _session(graph: Graph):
    return graph.session(MODULE, SCOPES)


def _escape(value) -> str:
    text = str(value if value is not None else "")
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").strip()


def _front_matter(title: str, kind: str, stamp: str) -> str:
    return ("---\n"
            f"title: {_escape(title) or kind}\n"
            f"type: {kind}\n"
            f"exported: {datetime.datetime.now(datetime.timezone.utc).isoformat()}\n"
            + (f"date: {_escape(stamp)}\n" if stamp else "")
            + "---\n")


def _document(kind: str, rows: list) -> str:
    """One Markdown document per kind, with a row per entry."""
    heading = SECTIONS.get(kind, kind.replace("_", " ").title())
    lines = [_front_matter(heading, kind, ""), f"# {heading}\n"]
    for row in rows:
        attrs = row.get("attrs", {})
        stamp = attrs.get("created_at", "")
        headline = (attrs.get("text") or attrs.get("note") or attrs.get("caption")
                    or attrs.get("title") or attrs.get("name") or attrs.get("place")
                    or attrs.get("activity") or attrs.get("question") or row.get("id", ""))
        lines.append(f"\n## {_escape(headline)[:200]}\n")
        if stamp:
            lines.append(f"*{_escape(stamp)}*\n")
        for key, value in sorted(attrs.items()):
            if key in ("type", "created_at") or value in ("", None, [], {}):
                continue
            lines.append(f"- **{_escape(key)}**: {_escape(value)[:MAX_FIELD]}\n")
    return "".join(lines)


# Fields that name whose row a system-owned record is. A kudos, a tab entry or a moment
# lives under SYSTEM_OWNER so both parties can read it — which means an export that walked
# only the owner slice silently left out the notes people wrote you, the money on your tab
# and everything you posted in a city. That is a partial export presented as a whole one.
MINE_FIELDS = ("account_id", "author_account", "from_account", "to_account",
               "debtor", "creditor", "opened_by", "set_by", "created_by")

SHARED_TYPES = ("kudos", "place_review", "city_moment", "city_message", "tab_entry",
                "synergy_signal", "crew_poll", "crew_poll_vote", "crew_beacon",
                "safe_walk", "squad_routine", "meetup")


def _mine(attrs: dict, account_id: str) -> bool:
    return bool(account_id) and any(attrs.get(field) == account_id
                                    for field in MINE_FIELDS)


def markdown(graph: Graph, *, account_id: str = "") -> dict:
    """Every row that is yours, as Markdown documents, in the response.

    No zip and no download URL. A URL means a file has to exist somewhere later, and the
    thing it replaces reported one that never existed at all — so the bytes come back now,
    and what happens to them is the caller's decision.
    """
    session = _session(graph)
    by_kind: dict[str, list] = {}
    for kind in ("content", "event", "metric", "task", "goal", "person", "place"):
        try:
            rows = session.find_entities(kind, limit=MAX_ROWS)
        except Exception:
            # A kind this deployment does not use is not an error; an export that dies
            # halfway is worse than one that is missing a section it never had.
            continue
        for row in rows:
            row_type = row.get("attrs", {}).get("type") or kind
            if row_type in SECRETS:
                continue
            by_kind.setdefault(row_type, []).append(row)

    # Shared records that are nonetheless yours. Filtered by the fields that name a person,
    # so this widens the export to your own rows and to nothing else.
    if account_id:
        from substrate import SYSTEM_OWNER
        shared = Graph(graph.conn, graph.bus,
                       default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)
        seen = {row["id"] for rows in by_kind.values() for row in rows}
        for row_type in SHARED_TYPES:
            if row_type in SECRETS:
                continue
            try:
                rows = shared.find_entities("content", {"type": row_type}, limit=MAX_ROWS)
            except Exception:
                continue
            for row in rows:
                if row["id"] in seen or not _mine(row.get("attrs", {}), account_id):
                    continue
                seen.add(row["id"])
                by_kind.setdefault(row_type, []).append(row)

    documents = {}
    for row_type, rows in sorted(by_kind.items()):
        rows.sort(key=lambda r: str(r.get("attrs", {}).get("created_at", "")))
        name = SECTIONS.get(row_type, row_type.replace("_", " ").title())
        documents[f"{name}.md"] = _document(row_type, rows)

    total_rows = sum(len(rows) for rows in by_kind.values())
    index = _index(documents, by_kind, total_rows)
    return {
        "format": "markdown",
        "files": len(documents) + 1,
        "rows": total_rows,
        "documents": {"index.md": index, **documents},
        "empty": total_rows == 0,
        # The old one reported a zip on connectos.app that was never written.
        "download_url": None,
        "note": ("This is the export itself, not a link to one. Nothing was uploaded "
                 "anywhere — save it wherever you keep things."),
        "excluded": sorted(SECRETS),
        "excluded_reason": ("Credentials and their hashes are not exported. They are not "
                            "your data, and an export is a file that ends up in a lot of "
                            "places."),
    }


def _index(documents: dict, by_kind: dict, total_rows: int) -> str:
    lines = [_front_matter("LifeOS export", "index", ""), "# LifeOS export\n",
             f"\n{total_rows} row{'' if total_rows == 1 else 's'} across "
             f"{len(documents)} document{'' if len(documents) == 1 else 's'}.\n\n"]
    if not documents:
        lines.append("Nothing stored yet — this export is empty, which is the honest "
                     "answer rather than a sample of somebody else's day.\n")
    for name in sorted(documents):
        kind = name[:-3]
        count = next((len(rows) for row_type, rows in by_kind.items()
                      if SECTIONS.get(row_type, row_type.replace("_", " ").title()) == kind),
                     0)
        lines.append(f"- [[{kind}]] — {count} entr{'y' if count == 1 else 'ies'}\n")
    return "".join(lines)


def as_single_file(graph: Graph, *, account_id: str = "") -> str:
    """The whole export as one Markdown string, for saving straight to a file."""
    out = markdown(graph, account_id=account_id)
    parts = []
    for name, text in out["documents"].items():
        parts.append(f"\n\n<!-- {name} -->\n\n{text}")
    return "".join(parts).strip() + "\n"
