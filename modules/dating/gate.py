"""Phase 3b gates — the dating surface is off unless every precondition is met.

The gates exist because this is the first feature where shipping it badly harms *users*
rather than the owner. They fail closed: every entry point calls `require_surface()`
first, and a misconfigured deployment gets no dating surface at all rather than a
half-working one.

**Age.** The ROADMAP originally said age assurance "needs a third party, which means it is
the first LifeOS feature that cannot be 'works with no API key'." That was overstated.
The major dating services do not run government-ID verification on ordinary signup — they
collect a date of birth, enforce a hard 18+ minimum, and rely on the app-store age rating.
Third-party ID checks appear where a specific jurisdiction compels them (the UK Online
Safety Act being the live example), not as the baseline. So the baseline here is a hard
18+ declaration that fails closed, with `method` recorded on the declaration so a stricter
provider can be added later without a migration — `method` is the seam.

**What is stored is the derived fact, not the date of birth.** Checking an age needs a
DOB; *keeping* one does not. We compute, gate, and persist `adult: true` plus when and
how it was established. A birth date is personal data with no further use here, so it is
never written to the graph. If a jurisdiction later demands re-verification, that is a new
declaration, not a lookup.

Two gates cannot be satisfied by code and are the reason `LIFEOS_DATING_ENABLED` defaults
to off: **G0 hosting** (a directory of real people looking for dates should not run on a
URL that can't be reached from a phone) and **G4 real users** (≥2 people who actually
asked). Turning the flag on is a deliberate operator act, taken once both are true.
"""

import datetime
import os

from substrate import SYSTEM_OWNER, now_iso
from substrate.graph import Graph

MODULE = "dating"
SCOPES = {"content:read", "content:write"}

ENABLE_VAR = "LIFEOS_DATING_ENABLED"
MIN_AGE = 18
SELF_DECLARED = "self_declared"

_TRUE = {"1", "true", "yes", "on"}


class DatingUnavailable(RuntimeError):
    """The surface is off, or a precondition for running it is missing."""


class AgeGateError(RuntimeError):
    """The caller has not established that they are over 18, or is not."""


def _sys(graph: Graph):
    """A session over the system-owned slice — declarations are not the user's to edit."""
    return Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(MODULE, SCOPES)


# ---- G0/G4: is the surface on at all? ---------------------------------------

def surface_enabled() -> bool:
    return str(os.environ.get(ENABLE_VAR, "")).strip().lower() in _TRUE


def availability() -> dict:
    """Why the surface is or isn't up. Safe to expose — it describes configuration,
    never a person."""
    from modules.security import crypto_tokens

    enabled = surface_enabled()
    signed = crypto_tokens.signing_configured()
    reasons = []
    if not enabled:
        reasons.append(f"{ENABLE_VAR} is not set (gates G0 hosting and G4 real users)")
    if not signed:
        reasons.append(f"{crypto_tokens.ENV_VAR} is not configured; matching cannot be blinded")
    return {"available": enabled and signed, "reasons": reasons}


def require_surface() -> None:
    state = availability()
    if not state["available"]:
        raise DatingUnavailable("dating is unavailable: " + "; ".join(state["reasons"]))


# ---- G2: over 18 -------------------------------------------------------------

def _age_on(dob: datetime.date, today: datetime.date) -> int:
    """Whole years, birthday-aware — `(today - dob).days // 365` is wrong across leap years."""
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _declaration(graph: Graph, account_id: str):
    hits = _sys(graph).find_entities(
        "content", {"type": "dating_adult", "account_id": account_id}, limit=1)
    return hits[0] if hits else None


def declare_age(graph: Graph, account_id: str, date_of_birth: str,
                method: str = SELF_DECLARED, source: str = MODULE) -> dict:
    """Establish that an account is over 18. The date of birth is checked and discarded.

    Raises `AgeGateError` for anyone under 18 and stores nothing for them — recording a
    refusal would mean holding data about a minor in order to prove we hold none.
    """
    require_surface()
    account_id = str(account_id or "").strip()
    if not account_id:
        raise ValueError("account_id required")
    try:
        dob = datetime.date.fromisoformat(str(date_of_birth or "").strip())
    except ValueError:
        raise ValueError("date_of_birth must be an ISO date, e.g. 1994-03-21")

    today = datetime.datetime.now(datetime.timezone.utc).date()
    if dob > today:
        raise ValueError("date_of_birth is in the future")
    if _age_on(dob, today) < MIN_AGE:
        raise AgeGateError(f"the dating surface is {MIN_AGE}+")

    attrs = {
        "type": "dating_adult", "account_id": account_id, "adult": True,
        "min_age": MIN_AGE, "method": method, "declared_at": now_iso(),
    }
    existing = _declaration(graph, account_id)
    if existing:
        _sys(graph).update_entity(existing["id"], attrs, source=source)
        declaration_id = existing["id"]
    else:
        declaration_id = _sys(graph).create_entity(
            "content", attrs, source=source, owner_id=SYSTEM_OWNER)
    return {"account_id": account_id, "adult": True, "method": method,
            "declaration_id": declaration_id}


def is_adult(graph: Graph, account_id: str) -> bool:
    record = _declaration(graph, account_id)
    return bool(record and record["attrs"].get("adult") is True)


def require_adult(graph: Graph, account_id: str) -> None:
    if not is_adult(graph, account_id):
        raise AgeGateError(
            f"this account has not confirmed it is {MIN_AGE}+ — declare age first")
