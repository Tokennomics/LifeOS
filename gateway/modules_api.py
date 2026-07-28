"""REST surface for the module suite (Reconnect, Convoy, Memento, Steward, Vitals,
Ledger, Calibre, Hearth). Mounted by gateway.main; handlers pull graph/claude off
app.state. Every endpoint works with zero API keys (offline fallbacks in the modules)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from gateway.auth import caller_graph

from modules.calibre import decisions as calibre
from modules.convoy import concierge, events_ingest, match_v1
from modules.coordinate import coordinator
from modules.crews import crews, invites
from modules.discover import discover
from modules.hearth import spaces as hearth
from modules.ledger import ledger
from modules.memento import capsules, quests
from modules.reconnect import decay, invite
from modules.steward import actions as steward_actions
from modules.steward import scanners as steward_scanners
from modules.vitals import energy


class PersonIn(BaseModel):
    name: str
    cadence_days: int = 30


class PersonRef(BaseModel):
    person_id: str


class ConvoyEventIn(BaseModel):
    title: str
    start: str
    place: str = ""
    url: str = ""


class InviteIn(BaseModel):
    event_id: str
    person_ids: list[str]


class RsvpIn(BaseModel):
    event_id: str
    person_id: str
    going: bool


class EventRef(BaseModel):
    event_id: str


class CapsuleIn(BaseModel):
    text: str
    lat: float
    lon: float
    place: str = ""
    radius_m: float = 75.0
    event_id: str = ""


class CoordsIn(BaseModel):
    lat: float
    lon: float


class AdminActIn(BaseModel):
    item_id: str
    action: str  # approve | dismiss


class WindowsIn(BaseModel):
    windows: list[dict]


class SpendIn(BaseModel):
    amount: float
    category: str
    note: str = ""


class DecisionIn(BaseModel):
    title: str
    choice: str
    confidence: float
    predicted: str
    review_days: int = 30


class ResolveIn(BaseModel):
    decision_id: str
    happened: bool


class SpaceIn(BaseModel):
    name: str
    member_ids: list[str] = []


class CoordProposeIn(BaseModel):
    person_id: str
    slots: list[str]
    places: list[str]
    weights: dict = {}          # owner's {slots:{slot:w}, places:{place:w}}; defaults to "free at all"


class CoordRespondIn(BaseModel):
    coordination_id: str
    weights: dict = {}          # peer's vector — sanitized to the proposed slots/places


class CoordApproveIn(BaseModel):
    coordination_id: str
    side: str                   # owner | peer
    choice: int                 # index into the ranked candidates


class CrewIn(BaseModel):
    name: str
    topic: str = ""
    city: str = ""
    member_ids: list[str] = []
    visibility: str = "private"
    admin_id: str | None = None
    admission: str = "approval"     # invite | approval | open


class CrewPolicyIn(BaseModel):
    crew_id: str
    visibility: str | None = None
    admission: str | None = None
    by: str | None = None


class PublicEventIn(BaseModel):
    title: str
    start: str = ""
    city: str = ""
    topic: str = ""
    place: str = ""
    visibility: str = "private"
    crew_id: str = ""


class IntentIn(BaseModel):
    city: str
    interests: list[str] = []
    starts: str = ""
    ends: str = ""


class InterestIn(BaseModel):
    event_id: str
    person_id: str
    going: bool = True


class CrewJoinIn(BaseModel):
    crew_id: str
    person_id: str | None = None    # omit to act as your own account (cross-account joins)


class CrewActIn(BaseModel):
    crew_id: str
    person_id: str
    by: str | None = None       # acting admin, where the action is admin-gated


class CrewReportIn(BaseModel):
    crew_id: str
    reporter_id: str
    reason: str
    subject_id: str | None = None


class ReportResolveIn(BaseModel):
    report_id: str
    action: str = "actioned"    # actioned | dismissed


class GroupProposeIn(BaseModel):
    crew_id: str
    slots: list[str]
    places: list[str]
    quorum: int = 2


class GroupRespondIn(BaseModel):
    coordination_id: str
    person_id: str = ""      # omitted -> the caller's own account (cross-account members)
    weights: dict = {}


class GroupApproveIn(BaseModel):
    coordination_id: str
    person_id: str = ""
    choice: int


class GroupCalendarIn(BaseModel):
    coordination_id: str
    person_id: str = ""


class InviteLinkIn(BaseModel):
    crew_id: str
    by: str | None = None
    ttl_hours: int = 24 * 7
    max_uses: int = 25


class InviteRedeemIn(BaseModel):
    token: str
    person_id: str = ""      # omitted -> the caller's own account


class InviteRevokeIn(BaseModel):
    invite_id: str
    by: str | None = None


class ImportIn(BaseModel):
    schema_name: str = Field(..., alias="schema")
    exported_at: str
    source: str
    items: list[dict]


def _subject(request: Request, explicit: str | None) -> str:
    """Who the action is for: an explicit local person, or — when omitted — the caller's
    own ACCOUNT, which is the identity shared crews are built from."""
    if explicit:
        return explicit
    caller = getattr(request.state, "caller", None)
    if caller and caller.get("account_id"):
        return caller["account_id"]
    raise HTTPException(status_code=400, detail="person_id required (or sign in with an account)")


def _graph(request: Request):
    """Every module read/write goes through here, so scoping it to the caller scopes
    the whole module surface at once (config owner when there are no accounts)."""
    return caller_graph(request)


def _claude(request: Request):
    return request.app.state.claude


def _serialize_event(session, event: dict) -> dict:
    a = event["attrs"]
    yes_names = []
    for pid in a.get("yes", []):
        person = session.get_entity(pid)
        if person:
            yes_names.append(person["attrs"].get("name", "?"))
    return {"id": event["id"], "title": a.get("title", ""), "start": a.get("start", ""),
            "place": a.get("place", ""), "url": a.get("url", ""), "status": a.get("status", ""),
            "invited": len(a.get("invited", [])), "yes": yes_names, "no": len(a.get("no", []))}


def build_router(auth) -> APIRouter:
    router = APIRouter(prefix="/v1", dependencies=[Depends(auth)])

    def guard(fn):
        try:
            return fn()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    # ---- Reconnect / People ---------------------------------------------

    @router.get("/people")
    def people(request: Request):
        return {"people": decay.ranked(_graph(request))}

    @router.post("/people")
    def add_person(request: Request, body: PersonIn):
        return {"person_id": decay.add_person(_graph(request), body.name, body.cadence_days)}

    @router.post("/reconnect/draft")
    def reconnect_draft(request: Request, body: PersonRef):
        return guard(lambda: invite.draft(_graph(request), body.person_id, claude=_claude(request)))

    @router.post("/reconnect/touch")
    def reconnect_touch(request: Request, body: PersonRef):
        return guard(lambda: decay.touch(_graph(request), body.person_id))

    # ---- Convoy ----------------------------------------------------------

    @router.get("/convoy")
    def convoy_events(request: Request):
        graph = _graph(request)
        session = graph.session("convoy", events_ingest.SCOPES)
        return {"events": [_serialize_event(session, e) for e in events_ingest.upcoming(graph)]}

    @router.post("/convoy/event")
    def convoy_add(request: Request, body: ConvoyEventIn):
        return guard(lambda: {"event_id": events_ingest.add_social_event(
            _graph(request), body.title, body.start, body.place, body.url)})

    @router.post("/convoy/invite")
    def convoy_invite(request: Request, body: InviteIn):
        return guard(lambda: match_v1.invite(_graph(request), body.event_id, body.person_ids,
                                             claude=_claude(request)))

    @router.post("/convoy/rsvp")
    def convoy_rsvp(request: Request, body: RsvpIn):
        return guard(lambda: match_v1.rsvp(_graph(request), body.event_id, body.person_id, body.going))

    @router.post("/convoy/attended")
    def convoy_attended(request: Request, body: EventRef):
        return guard(lambda: match_v1.attended(_graph(request), body.event_id))

    @router.get("/convoy/digest")
    def convoy_digest(request: Request):
        return concierge.digest(_graph(request), claude=_claude(request))

    # ---- Memento ---------------------------------------------------------

    @router.get("/capsules")
    def capsules_list(request: Request, lat: float | None = None, lon: float | None = None):
        return {"capsules": capsules.nearby(_graph(request), lat, lon),
                "quests": quests.suggestions(_graph(request))}

    @router.post("/capsules")
    def capsules_drop(request: Request, body: CapsuleIn):
        return guard(lambda: capsules.drop(_graph(request), body.text, body.lat, body.lon,
                                           body.place, body.radius_m, body.event_id))

    @router.post("/capsules/unlock")
    def capsules_unlock(request: Request, body: CoordsIn):
        return capsules.unlock(_graph(request), body.lat, body.lon)

    # ---- Steward ---------------------------------------------------------

    @router.get("/admin")
    def admin_items(request: Request):
        return {"items": steward_actions.open_items(_graph(request))}

    @router.post("/admin/scan")
    def admin_scan(request: Request):
        return steward_scanners.scan(_graph(request))

    @router.post("/admin/act")
    def admin_act(request: Request, body: AdminActIn):
        if body.action not in ("approve", "dismiss"):
            raise HTTPException(status_code=400, detail="action must be approve or dismiss")
        fn = steward_actions.approve if body.action == "approve" else steward_actions.dismiss
        return guard(lambda: fn(_graph(request), body.item_id))

    # ---- Vitals ----------------------------------------------------------

    @router.get("/vitals")
    def vitals_get(request: Request):
        return {"windows": energy.windows(_graph(request))}

    @router.post("/vitals")
    def vitals_set(request: Request, body: WindowsIn):
        return guard(lambda: energy.set_windows(_graph(request), body.windows))

    # ---- Ledger ----------------------------------------------------------

    @router.get("/ledger")
    def ledger_summary(request: Request):
        return ledger.summary(_graph(request))

    @router.post("/ledger")
    def ledger_add(request: Request, body: SpendIn):
        return guard(lambda: {"spend_id": ledger.log_spend(
            _graph(request), body.amount, body.category, body.note)})

    # ---- Calibre ---------------------------------------------------------

    @router.get("/decisions")
    def decisions_list(request: Request):
        graph = _graph(request)
        return {"decisions": calibre.open_decisions(graph), "calibration": calibre.calibration(graph)}

    @router.post("/decisions")
    def decisions_log(request: Request, body: DecisionIn):
        return guard(lambda: {"decision_id": calibre.log(
            _graph(request), body.title, body.choice, body.confidence, body.predicted, body.review_days)})

    @router.post("/decisions/resolve")
    def decisions_resolve(request: Request, body: ResolveIn):
        return guard(lambda: calibre.resolve(_graph(request), body.decision_id, body.happened))

    # ---- Hearth ----------------------------------------------------------

    @router.get("/spaces")
    def spaces_list(request: Request):
        return {"spaces": hearth.spaces(_graph(request))}

    @router.post("/spaces")
    def spaces_create(request: Request, body: SpaceIn):
        return guard(lambda: hearth.create_space(_graph(request), body.name, body.member_ids))

    # ---- Coordinate (Phase 3: mediator-brokered 1:1 scheduling) ----------

    @router.get("/coordinate")
    def coordinate_list(request: Request):
        return {"coordinations": coordinator.list_open(_graph(request))}

    @router.post("/coordinate/propose")
    def coordinate_propose(request: Request, body: CoordProposeIn):
        return guard(lambda: coordinator.propose(
            _graph(request), body.person_id, body.slots, body.places, body.weights))

    @router.post("/coordinate/respond")
    def coordinate_respond(request: Request, body: CoordRespondIn):
        return guard(lambda: coordinator.respond(_graph(request), body.coordination_id, body.weights))

    @router.post("/coordinate/approve")
    def coordinate_approve(request: Request, body: CoordApproveIn):
        return guard(lambda: coordinator.approve(
            _graph(request), body.coordination_id, body.side, body.choice))

    # ---- Crews + group coordination --------------------------------------

    @router.get("/crews")
    def crews_browse(request: Request, topic: str = "", city: str = "", visibility: str = ""):
        """visibility='public' is the directory query — the only view a stranger gets."""
        return {"crews": crews.browse(_graph(request), topic=topic, city=city, visibility=visibility)}

    @router.post("/crews")
    def crews_create(request: Request, body: CrewIn):
        return guard(lambda: crews.create(
            _graph(request), body.name, body.topic, body.city, body.member_ids,
            visibility=body.visibility, admin_id=body.admin_id, admission=body.admission))

    @router.post("/crews/policy")
    def crews_policy(request: Request, body: CrewPolicyIn):
        """Admin control: how the crew is found (visibility) and who gets in (admission)."""
        return guard(lambda: crews.set_policy(
            _graph(request), body.crew_id, body.visibility, body.admission, body.by))

    @router.get("/crews/directory")
    def crews_directory(request: Request, topic: str = "", city: str = ""):
        """The cross-account public directory — every published crew, whoever owns it.
        Declared before /crews/{crew_id} so the literal path wins."""
        return {"crews": crews.directory(_graph(request), topic=topic, city=city)}

    @router.get("/crews/invite-link")
    def crews_invite_links(request: Request, crew_id: str, by: str = ""):
        """Links issued for a crew (admin only) — state, never the secret. Declared before
        /crews/{crew_id} so the literal path wins."""
        return {"invites": guard(lambda: invites.for_crew(
            _graph(request), crew_id, _subject(request, by)))}

    @router.get("/crews/{crew_id}")
    def crews_get(request: Request, crew_id: str):
        caller = getattr(request.state, "caller", None) or {}
        return guard(lambda: crews.get(_graph(request), crew_id, caller.get("account_id")))

    @router.post("/crews/join")
    def crews_join(request: Request, body: CrewJoinIn):
        return guard(lambda: crews.join(_graph(request), body.crew_id, body.person_id))

    @router.post("/crews/invite")
    def crews_invite(request: Request, body: CrewActIn):
        return guard(lambda: crews.invite(_graph(request), body.crew_id, body.person_id, body.by))

    @router.post("/crews/invite/accept")
    def crews_accept(request: Request, body: CrewJoinIn):
        subject = _subject(request, body.person_id)
        return guard(lambda: crews.accept_invite(_graph(request), body.crew_id, subject))

    @router.post("/crews/invite/decline")
    def crews_decline(request: Request, body: CrewJoinIn):
        subject = _subject(request, body.person_id)
        return guard(lambda: crews.decline_invite(_graph(request), body.crew_id, subject))

    @router.post("/crews/request")
    def crews_request(request: Request, body: CrewJoinIn):
        subject = _subject(request, body.person_id)
        return guard(lambda: crews.request_join(_graph(request), body.crew_id, subject))

    @router.post("/crews/invite-link")
    def crews_invite_link(request: Request, body: InviteLinkIn):
        """Mint a shareable join link. The token comes back ONCE — it is never re-readable."""
        return guard(lambda: invites.create(
            _graph(request), body.crew_id, _subject(request, body.by),
            body.ttl_hours, body.max_uses))

    @router.post("/crews/invite-link/redeem")
    def crews_invite_redeem(request: Request, body: InviteRedeemIn):
        """Join by holding the link — works for a private crew you could never have found."""
        subject = _subject(request, body.person_id)
        return guard(lambda: invites.redeem(_graph(request), body.token, subject))

    @router.post("/crews/invite-link/revoke")
    def crews_invite_revoke(request: Request, body: InviteRevokeIn):
        return guard(lambda: invites.revoke(
            _graph(request), body.invite_id, _subject(request, body.by)))

    @router.post("/crews/request/approve")
    def crews_approve(request: Request, body: CrewActIn):
        return guard(lambda: crews.approve_request(
            _graph(request), body.crew_id, body.person_id, body.by))

    @router.post("/crews/request/deny")
    def crews_deny(request: Request, body: CrewActIn):
        return guard(lambda: crews.deny_request(_graph(request), body.crew_id, body.person_id, body.by))

    @router.post("/crews/leave")
    def crews_leave(request: Request, body: CrewJoinIn):
        subject = _subject(request, body.person_id)
        return guard(lambda: crews.leave(_graph(request), body.crew_id, subject))

    @router.post("/crews/block")
    def crews_block(request: Request, body: CrewActIn):
        return guard(lambda: crews.block(_graph(request), body.crew_id, body.person_id, body.by))

    @router.post("/crews/unblock")
    def crews_unblock(request: Request, body: CrewActIn):
        return guard(lambda: crews.unblock(_graph(request), body.crew_id, body.person_id, body.by))

    @router.get("/crews/reports/open")
    def crews_reports(request: Request, crew_id: str = "", status: str = ""):
        return {"reports": crews.reports(_graph(request), crew_id=crew_id, status=status)}

    @router.post("/crews/report")
    def crews_report(request: Request, body: CrewReportIn):
        return guard(lambda: crews.report(
            _graph(request), body.crew_id, body.reporter_id, body.reason, body.subject_id))

    @router.post("/crews/report/resolve")
    def crews_report_resolve(request: Request, body: ReportResolveIn):
        return guard(lambda: crews.resolve_report(_graph(request), body.report_id, body.action))

    @router.post("/coordinate/group/propose")
    def coordinate_group_propose(request: Request, body: GroupProposeIn):
        return guard(lambda: coordinator.propose_group(
            _graph(request), body.crew_id, body.slots, body.places, body.quorum))

    @router.get("/coordinate/group/mine")
    def coordinate_group_mine(request: Request, person_id: str = ""):
        """Crew sessions you can answer — including ones opened in another account."""
        subject = _subject(request, person_id)
        return {"coordinations": coordinator.my_sessions(_graph(request), subject)}

    @router.post("/coordinate/group/respond")
    def coordinate_group_respond(request: Request, body: GroupRespondIn):
        subject = _subject(request, body.person_id)
        return guard(lambda: coordinator.respond_group(
            _graph(request), body.coordination_id, subject, body.weights))

    @router.post("/coordinate/group/approve")
    def coordinate_group_approve(request: Request, body: GroupApproveIn):
        subject = _subject(request, body.person_id)
        return guard(lambda: coordinator.approve_group(
            _graph(request), body.coordination_id, subject, body.choice))

    @router.post("/coordinate/group/calendar")
    def coordinate_group_calendar(request: Request, body: GroupCalendarIn):
        """Put a confirmed crew night on your own calendar (idempotent)."""
        subject = _subject(request, body.person_id)
        return guard(lambda: coordinator.add_to_calendar(
            _graph(request), body.coordination_id, subject))

    # ---- Discover (intent -> local public events/crews) -------------------

    @router.get("/discover")
    def discover_find(request: Request, city: str = "", interests: str = ""):
        """What's on for me here. Omit `interests` to match on your graph's own profile."""
        wants = [i.strip() for i in interests.split(",") if i.strip()] or None
        return discover.find(_graph(request), city=city, interests=wants)

    @router.post("/discover/events")
    def discover_publish(request: Request, body: PublicEventIn):
        return guard(lambda: discover.publish_event(
            _graph(request), body.title, body.start, body.city, body.topic,
            body.place, body.visibility, body.crew_id))

    @router.get("/discover/intents")
    def discover_intents(request: Request):
        return {"intents": discover.intents(_graph(request))}

    @router.post("/discover/intents")
    def discover_set_intent(request: Request, body: IntentIn):
        return guard(lambda: discover.set_intent(
            _graph(request), body.city, body.interests, body.starts, body.ends))

    @router.get("/discover/intents/{intent_id}")
    def discover_for_intent(request: Request, intent_id: str):
        return guard(lambda: discover.find_for_intent(_graph(request), intent_id))

    @router.get("/feed")
    def feed(request: Request, cities: str = "", interests: str = ""):
        """Your feed: where you are + where you're going, ranked by match, crowd and timing."""
        city_list = [c.strip() for c in cities.split(",") if c.strip()] or None
        wants = [i.strip() for i in interests.split(",") if i.strip()] or None
        return discover.feed(_graph(request), cities=city_list, interests=wants)

    @router.post("/feed/interested")
    def feed_interested(request: Request, body: InterestIn):
        return guard(lambda: discover.mark_interest(
            _graph(request), body.event_id, body.person_id, body.going))

    # ---- Travel Mode / Reconciliation ------------------------------------

    @router.post("/import")
    def travel_import(request: Request, body: ImportIn):
        from modules.travel import reconcile
        data = body.model_dump(by_alias=True) if hasattr(body, "model_dump") else body.dict(by_alias=True)
        return guard(lambda: reconcile.reconcile(_graph(request), data))

    return router
