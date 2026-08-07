"""Delete my account, and everything of mine — GDPR Art. 17, and simple decency.

Export has existed since Law 2 ("the graph is the user's"). Erasure did not, which made
that claim half true: you could take a copy of everything and remove none of it. A system
you cannot leave is not one you can honestly ask people to join.

**Erasure is not one operation, because the data is not one kind.** Four categories, and the
difference between them is the whole design:

1. **Yours alone** — captures, goals, notes, calendar, your feed subscriptions. Deleted.
   This is the bulk of it and it goes through `purge_owner`.
2. **Yours, but system-owned** — the dating age declaration, rendezvous handshakes, and the
   block rows naming you. These live under the SYSTEM owner so the module can work across
   accounts, but they are *about you*, so they are deleted too. Missing these would leave
   your dating footprint behind after you had gone.
3. **Shared, where you are a participant** — crew memberships, coordination sessions. The
   grant rows naming you are revoked, so you vanish from every roster. The crew itself
   survives, because it is other people's too.
4. **Abuse reports** — the hard one. **Pseudonymised, never deleted.** GDPR Art. 17(3)(e)
   keeps data needed for legal claims, and a safety report is exactly that: if someone
   erases their account to wipe the record of what they did, deletion becomes a feature for
   the wrong person. So the report text stays and the account ids in it are replaced with a
   one-way `erased:<digest>` marker — enough to see that two reports concern the same
   erased account, not enough to identify anyone.

**What we do NOT claim:** backups. `tools/backup.py` snapshots the database on a schedule,
and a snapshot taken before an erasure still contains the data until it rotates out. That is
normal and lawful (Art. 17 is "without undue delay", not "instantly, everywhere"), but it is
a fact the operator should know rather than discover. `RETENTION_NOTE` says so out loud, and
the receipt returned to the user carries it.
"""

import hashlib

from substrate import SYSTEM_OWNER
from substrate.graph import Graph

MODULE = "privacy"
SCOPES = {"content:read", "content:write", "events:read", "events:write",
          "people:read", "people:write"}

ERASED_PREFIX = "erased:"
RETENTION_NOTE = (
    "Database snapshots taken before this erasure still contain the data until they rotate "
    "out (see tools/backup.py --keep). Abuse reports are kept with your identifier replaced "
    "by a one-way marker, which GDPR Art. 17(3)(e) permits for the establishment or defence "
    "of legal claims."
)

#: Report types that survive erasure with their identifiers pseudonymised.
SAFETY_RECORDS = ("dating_report", "crew_report")


def pseudonym(account_id: str) -> str:
    """A stable, one-way marker for an erased account.

    Stable so two reports about the same erased person still line up for a moderator;
    one-way so the marker cannot be turned back into an account id. It is salted with the
    signing key, which means it is also not comparable across deployments.
    """
    from modules.security import crypto_tokens
    try:
        digest = crypto_tokens.sign_payload({"ns": "privacy/erased/v1", "id": str(account_id)})
    except Exception:
        # Erasure must never fail because signing is unconfigured — a weaker marker is
        # better than a user who cannot leave.
        digest = hashlib.sha256(f"privacy/erased/v1:{account_id}".encode()).hexdigest()
    return ERASED_PREFIX + digest[:32]


def _sys(graph: Graph):
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


def preview(graph: Graph, account_id: str, owner_id: str) -> dict:
    """What erasure would remove. Shown before the button, never after."""
    system = _sys(graph)
    owned = graph.conn.execute(
        "SELECT kind, COUNT(*) AS n FROM entities WHERE owner_id = ? GROUP BY kind",
        (owner_id,)).fetchall()
    counts = {r["kind"]: r["n"] for r in owned}
    memberships = len(system.spaces_granted(account_id, {
        "crew:admin", "crew:member", "crew:invited", "crew:requested", "coord:participant"}))
    reports = sum(1 for t in SAFETY_RECORDS
                  for r in system.find_entities("content", {"type": t}, limit=1000)
                  if account_id in (r["attrs"].get("reporter_id"), r["attrs"].get("subject_id")))
    return {"entities": sum(counts.values()), "by_kind": counts,
            "memberships": memberships, "safety_records_kept": reports,
            "retention_note": RETENTION_NOTE}


def erase_account(graph: Graph, account_id: str, owner_id: str,
                  source: str = MODULE) -> dict:
    """Erase an account and everything of theirs. Returns a receipt.

    Ordered so that a crash part-way leaves the account unusable rather than half-erased:
    sessions die first, the account record dies last. There is no transaction spanning all
    of this, so the order IS the safety property.
    """
    from gateway import accounts

    system = _sys(graph)
    receipt = {"account_id": account_id, "sessions_revoked": 0, "entities": 0,
               "edges": 0, "observations": 0, "grants": 0,
               "memberships_revoked": 0, "system_rows": 0, "safety_records_kept": 0}

    # 1. Cut every session first — from here the account cannot act, even if the rest fails.
    receipt["sessions_revoked"] = accounts.revoke_all(graph, account_id, source=source)["revoked"]

    # 2. Leave every shared space. Done before the purge because the grant rows are keyed on
    #    the SPACE, and some of those spaces are other people's entities.
    for space in system.spaces_granted(account_id, {
            "crew:admin", "crew:member", "crew:invited", "crew:requested",
            "crew:blocked", "coord:participant"}):
        for scope in ("crew:admin", "crew:member", "crew:invited", "crew:requested",
                      "crew:blocked", "coord:participant"):
            try:
                receipt["memberships_revoked"] += system.revoke(
                    account_id, scope, space, source=source)
            except Exception:
                continue      # a space that has already gone is not a failure

    # 3. Pseudonymise the safety records BEFORE the account id stops existing.
    marker = pseudonym(account_id)
    for kind in SAFETY_RECORDS:
        for row in system.find_entities("content", {"type": kind}, limit=1000):
            patch = {}
            for field in ("reporter_id", "subject_id"):
                if row["attrs"].get(field) == account_id:
                    patch[field] = marker
            if patch:
                system.update_entity(row["id"], {**patch, "erased_party": True},
                                     source=source)
                receipt["safety_records_kept"] += 1

    # 4. System-owned rows that are nonetheless about this person.
    for kind, field in (("dating_adult", "account_id"),):
        for row in system.find_entities("content", {"type": kind, field: account_id}, limit=50):
            system.delete_entity(row["id"], source=source)
            receipt["system_rows"] += 1
    receipt["system_rows"] += _erase_dating_traces(graph, system, account_id, source)

    # 5. Everything they own.
    purged = system.purge_owner(owner_id, source=source)
    receipt.update({k: purged[k] for k in ("entities", "edges", "observations", "grants")})

    # 6. The account record itself, last.
    for row in system.find_entities("content", {"type": "account"}, limit=1000):
        if row["id"] == account_id:
            system.delete_entity(row["id"], source=source)
            break

    receipt["retention_note"] = RETENTION_NOTE
    receipt["erased"] = True
    return receipt


def _erase_dating_traces(graph: Graph, system, account_id: str, source: str) -> int:
    """Handshakes and blocks are keyed by digest, not by name — so they are found by
    recomputing the digests this account could have produced, not by searching for its id.

    Blocks need every counterpart, which is why the pair is derived from the account's own
    intents rather than from a scan: the block row itself names nobody by design.
    """
    from modules.dating import mutual_match, safety as dating_safety

    removed = 0
    intents = graph.conn.execute(
        "SELECT attrs FROM entities WHERE kind = 'content' "
        "AND json_extract(attrs, '$.type') = 'dating_intent' "
        "AND json_extract(attrs, '$.user_id') = ?", (account_id,)).fetchall()
    import json
    for row in intents:
        attrs = json.loads(row["attrs"]) if isinstance(row["attrs"], str) else row["attrs"]
        target, activity = attrs.get("target"), attrs.get("activity")
        if not target or not activity:
            continue
        for rk in (mutual_match._rendezvous(account_id, target, activity),):
            for hit in system.find_entities("content", {"type": "dating_handshake", "rk": rk},
                                            limit=2):
                system.delete_entity(hit["id"], source=source)
                removed += 1
        key = dating_safety._pair_key(account_id, target)
        for hit in system.find_entities("content", {"type": "dating_block", "pair_key": key},
                                        limit=2):
            system.delete_entity(hit["id"], source=source)
            removed += 1
    return removed
