"""REST surface for the module suite (Reconnect, Convoy, Memento, Steward, Vitals,
Ledger, Calibre, Hearth). Mounted by gateway.main; handlers pull graph/claude off
app.state. Every endpoint works with zero API keys (offline fallbacks in the modules)."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
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


class CoachRewordIn(BaseModel):
    proposals: list[dict]


class GoalMilestoneIn(BaseModel):
    title: str
    target_week: str = ""


class ParkedPromoteIn(BaseModel):
    target_level: str = "goal"


class TimeCapsuleIn(BaseModel):
    text: str
    unlock_at: str


class PersonNoteIn(BaseModel):
    person_id: str
    note: str


class DecisionOutcomeIn(BaseModel):
    happened: bool
    reflection: str = ""


class CriticalCardIn(BaseModel):
    full_name: str = ""
    blood_type: str = ""
    allergies: str = ""
    notes: str = ""
    emergency_contacts: list[dict] = []


class DeadmanConfigIn(BaseModel):
    interval_hours: float = 24.0
    grace_hours: float = 12.0
    contacts: list[dict] = []


class DatingInterestIn(BaseModel):
    target_account_id: str
    activity_id: str


class ManifestValidateIn(BaseModel):
    manifest: dict


class EventFeedbackIn(BaseModel):
    event_id: str
    rating: int
    notes: str = ""


class NotificationEnqueueIn(BaseModel):
    channel: str
    recipient: str
    title: str
    body: str = ""


class VenueLinkIn(BaseModel):
    target_id: str
    place_info: dict


class RoutineCreateIn(BaseModel):
    name: str
    trigger: str
    time_of_day: str = "morning"
    items: list[str] = []


class VaultNoteIn(BaseModel):
    title: str
    content: str
    tags: list[str] = []


class AssistantChatIn(BaseModel):
    message: str


class CalendarSyncIn(BaseModel):
    ics_content: str


class FinancialGoalIn(BaseModel):
    title: str
    target_amount: float
    current_amount: float = 0.0
    currency: str = "USD"


class FinancialProgressIn(BaseModel):
    amount_delta: float


class UserBundleRestoreIn(BaseModel):
    bundle_data: dict


class AuditLogIn(BaseModel):
    event_type: str
    actor_id: str = "system"
    details: dict = {}


class JournalEntryIn(BaseModel):
    wins: list[str] = []
    gratitude: list[str] = []
    reflection: str = ""
    mood_rating: int = 5


class GoalDependencyIn(BaseModel):
    goal_id: str
    depends_on_goal_id: str


class SsoLoginIn(BaseModel):
    provider: str
    provider_user_id: str
    email: str = ""
    phone: str = ""
    name: str = ""


class SsoLinkIn(BaseModel):
    account_id: str
    provider: str
    provider_user_id: str


class BillingCustomerIn(BaseModel):
    account_id: str
    email: str = ""


class BillingSubscribeIn(BaseModel):
    account_id: str
    plan_id: str = "pro"
    payment_token: str = "tok_mock"


class SystemLogIn(BaseModel):
    level: str = "INFO"
    module: str
    message: str
    metadata: dict = {}


class SanitizeIn(BaseModel):
    text: str


class TokenVerifyIn(BaseModel):
    data: dict
    signature: str


class FocusSessionIn(BaseModel):
    duration_minutes: int
    distraction_count: int
    note: str = ""


class ExpenseSplitIn(BaseModel):
    total_amount: float
    currency: str = "USD"
    payer_id: str
    member_ids: list[str]


class VenueVoteIn(BaseModel):
    poll_id: str
    place_id: str
    member_id: str


class ChatMessageIn(BaseModel):
    sender_id: str
    recipient_id: str
    body: str
    linked_entity_id: str | None = None


class MiniAppRegisterIn(BaseModel):
    name: str
    url: str
    icon: str = ""


class SplitSettleIn(BaseModel):
    split_id: str
    settled_amount: float


class OptimizeItineraryIn(BaseModel):
    place_ids: list[str]


class CrewGoalIn(BaseModel):
    crew_id: str
    title: str
    target_date: str


class LedgerSyncIn(BaseModel):
    total_amount: float
    currency: str = "USD"
    payer_id: str
    member_ids: list[str]


class ResourceRegisterIn(BaseModel):
    owner_id: str
    name: str


class ResourceLoanIn(BaseModel):
    resource_id: str
    borrower_id: str


class GraphQaIn(BaseModel):
    query_text: str


class OutingMatchIn(BaseModel):
    member_ids: list[str]
    day: str









class SleepDataIn(BaseModel):
    date: str
    hours_slept: float
    sleep_quality: int
    wake_time: str


class EmergencyAlertIn(BaseModel):
    message: str


class CrewItineraryIn(BaseModel):
    venue_ids: list[str]
    start_time: str = ""


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
    @router.get("/steward/queue")
    def admin_items(request: Request):
        return {"items": steward_actions.open_items(_graph(request))}

    @router.post("/admin/scan")
    def admin_scan(request: Request):
        return steward_scanners.scan(_graph(request))

    @router.post("/admin/act")
    @router.post("/steward/approve")
    def admin_act(request: Request, body: AdminActIn):
        if body.action not in ("approve", "dismiss"):
            raise HTTPException(status_code=400, detail="action must be approve or dismiss")
        fn = steward_actions.approve if body.action == "approve" else steward_actions.dismiss
        return guard(lambda: fn(_graph(request), body.item_id))

    # ---- Coach Reword ----------------------------------------------------

    @router.post("/coach/reword")
    def coach_reword(request: Request, body: CoachRewordIn):
        from modules.horizon import coach_reword
        claude = _claude(request)
        return {"proposals": coach_reword.reword_proposals(body.proposals, claude_gateway=claude)}

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

    @router.get("/discover/personalized-event-feed")
    def personalized_event_feed_endpoint(request: Request):
        from modules.venues import event_feed
        return event_feed.get_personalized_event_feed(_graph(request))

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

    # ---- ICS Calendar Export ---------------------------------------------

    @router.get("/calendar/export.ics")
    def calendar_export(request: Request):
        from modules.calendars import export
        content = export.export_user_ics(_graph(request))
        return Response(content=content, media_type="text/calendar")

    @router.get("/crews/{crew_id}/export.ics")
    def crew_calendar_export(request: Request, crew_id: str):
        from modules.calendars import export
        content = export.export_crew_ics(_graph(request), crew_id)
        return Response(content=content, media_type="text/calendar")

    # ---- Triage OS Brief -------------------------------------------------

    @router.get("/triage/brief")
    def triage_brief(request: Request):
        from modules.triage import brief
        return brief.generate_triage_brief(_graph(request))

    # ---- Vision & Goals Expansion ----------------------------------------

    @router.post("/goals/{goal_id}/milestones")
    def goal_add_milestone(request: Request, goal_id: str, body: GoalMilestoneIn):
        from modules.horizon import milestones
        return guard(lambda: milestones.add_milestone(_graph(request), goal_id, body.title, body.target_week))

    @router.post("/milestones/{milestone_id}/complete")
    def milestone_complete(request: Request, milestone_id: str):
        from modules.horizon import milestones
        return guard(lambda: milestones.complete_milestone(_graph(request), milestone_id))

    @router.get("/goals/{goal_id}/progress")
    def goal_progress_get(request: Request, goal_id: str):
        from modules.horizon import milestones
        return guard(lambda: milestones.goal_progress(_graph(request), goal_id))

    @router.get("/goals/velocity")
    def goal_velocity_get(request: Request):
        from modules.horizon import analytics
        return analytics.goal_velocity(_graph(request))

    @router.get("/parked")
    def parked_list(request: Request):
        from modules.horizon import parked_sorter
        return {"parked": parked_sorter.list_parked(_graph(request))}

    @router.post("/parked/{idea_id}/promote")
    def parked_promote(request: Request, idea_id: str, body: ParkedPromoteIn):
        from modules.horizon import parked_sorter
        return guard(lambda: parked_sorter.promote_parked(_graph(request), idea_id, body.target_level))

    # ---- Memento Time Capsules -------------------------------------------

    @router.post("/capsules/time")
    def capsule_time_drop(request: Request, body: TimeCapsuleIn):
        from modules.memento import time_capsules
        return guard(lambda: time_capsules.drop_time_capsule(_graph(request), body.text, body.unlock_at))

    @router.post("/capsules/unlock-time")
    def capsule_time_unlock(request: Request):
        from modules.memento import time_capsules
        return time_capsules.check_time_unlocks(_graph(request))

    # ---- Reconnect Touch History & Notes ---------------------------------

    @router.get("/reconnect/history/{person_id}")
    def reconnect_history(request: Request, person_id: str):
        from modules.reconnect import touch_history
        return guard(lambda: touch_history.get_touch_history(_graph(request), person_id))

    @router.post("/reconnect/notes")
    def reconnect_add_note(request: Request, body: PersonNoteIn):
        from modules.reconnect import touch_history
        return guard(lambda: touch_history.add_person_note(_graph(request), body.person_id, body.note))

    # ---- Calibre Decision Reviews ----------------------------------------

    @router.get("/decisions/pending")
    def decisions_pending(request: Request):
        from modules.calibre import review
        return {"pending": review.pending_reviews(_graph(request))}

    @router.post("/decisions/{decision_id}/outcome")
    def decision_outcome(request: Request, decision_id: str, body: DecisionOutcomeIn):
        from modules.calibre import review
        return guard(lambda: review.record_outcome(_graph(request), decision_id, body.happened, body.reflection))

    # ---- Critical Card & Dead-Man's Switch -------------------------------

    @router.post("/triage/card")
    def triage_card_save(request: Request, body: CriticalCardIn):
        from modules.triage import critical_card
        return guard(lambda: critical_card.save_critical_card(_graph(request), body.model_dump()))

    @router.get("/triage/card")
    def triage_card_get(request: Request):
        from modules.triage import critical_card
        return critical_card.get_critical_card(_graph(request))

    @router.post("/triage/deadman/config")
    def deadman_config(request: Request, body: DeadmanConfigIn):
        from modules.triage import deadman
        return guard(lambda: deadman.set_config(_graph(request), body.interval_hours, body.grace_hours, body.contacts))

    @router.post("/triage/deadman/ping")
    def deadman_ping(request: Request):
        from modules.triage import deadman
        return deadman.ping(_graph(request))

    @router.get("/triage/deadman/status")
    def deadman_status(request: Request):
        from modules.triage import deadman
        return deadman.check_status(_graph(request))

    # ---- Agent Budgeting & Outbox ----------------------------------------

    @router.get("/agent/budget")
    def agent_budget(request: Request, module: str = "steward"):
        from modules.steward import budget
        return budget.check_budget(_graph(request), module)

    @router.post("/agent/outbox/process")
    def agent_outbox_process(request: Request):
        from modules.steward import outbox
        return outbox.process_outbox(_graph(request))

    # ---- Mutual-Consent Activity Dating ----------------------------------

    @router.post("/dating/interest")
    def dating_interest(request: Request, body: DatingInterestIn):
        from modules.dating import mutual_match
        return guard(lambda: mutual_match.express_interest(_graph(request), body.target_account_id, body.activity_id))

    @router.get("/dating/matches")
    def dating_matches(request: Request):
        from modules.dating import mutual_match
        caller = getattr(request.state, "caller", None)
        return {"matches": mutual_match.check_matches(_graph(request), account_id=caller)}

    # ---- Platform Manifest Validation ------------------------------------

    @router.post("/platform/validate")
    def platform_validate(request: Request, body: ManifestValidateIn):
        from modules.platform import manifest
        return guard(lambda: manifest.validate_manifest(body.manifest))

    # ---- Growth & Crew Activation ----------------------------------------

    @router.post("/crews/{crew_id}/feedback")
    def crew_event_feedback(request: Request, crew_id: str, body: EventFeedbackIn):
        from modules.growth import feedback
        return guard(lambda: feedback.record_event_feedback(_graph(request), crew_id, body.event_id, body.rating, body.notes))

    @router.get("/crews/{crew_id}/activation")
    def crew_activation(request: Request, crew_id: str):
        from modules.growth import feedback
        return feedback.crew_activation_status(_graph(request), crew_id)

    # ---- Data Portability Export Bundle ----------------------------------

    @router.get("/export/bundle")
    def export_bundle(request: Request):
        from modules.backup import export_graph
        return export_graph.export_user_bundle(_graph(request))

    # ---- System Health & Diagnostics -------------------------------------

    @router.get("/health/diagnostics")
    def health_diagnostics(request: Request):
        from modules.health import diagnostics
        return diagnostics.run_diagnostics(_graph(request))

    # ---- Notification Dispatcher -----------------------------------------

    @router.post("/notifications/enqueue")
    def notification_enqueue(request: Request, body: NotificationEnqueueIn):
        from modules.notifications import dispatcher
        return guard(lambda: dispatcher.enqueue_notification(_graph(request), body.channel, body.recipient, body.title, body.body))

    @router.post("/notifications/dispatch")
    def notification_dispatch(request: Request):
        from modules.notifications import dispatcher
        return dispatcher.dispatch_pending(_graph(request))

    # ---- Google Maps Venues & Places ------------------------------------

    @router.get("/venues/search")
    def venues_search(query: str, city: str = "", category: str = ""):
        from modules.venues import places
        return guard(lambda: places.search_venues(query, city=city, category=category))

    @router.get("/venues/recommendations")
    def recommend_places_endpoint(request: Request, crew_id: str | None = None):
        from modules.venues import recommender
        return recommender.recommend_places(_graph(request), crew_id)

    @router.get("/venues/activity-heatmap")
    def get_activity_heatmap_endpoint(request: Request):
        from modules.venues import heatmap
        return heatmap.get_activity_heatmap(_graph(request))

    @router.get("/venues/vote/results")
    def get_poll_results_endpoint(request: Request, poll_id: str):
        from modules.venues import voting
        return voting.get_poll_results(_graph(request), poll_id)

    @router.post("/venues/vote")
    def submit_vote_endpoint(request: Request, body: VenueVoteIn):
        from modules.venues import voting
        return guard(lambda: voting.submit_vote(_graph(request), body.poll_id, body.place_id, body.member_id))

    @router.get("/venues/{place_id}")
    def venue_details(place_id: str):
        from modules.venues import places
        return guard(lambda: places.get_venue_details(place_id))

    @router.post("/venues/link")
    def venue_link(request: Request, body: VenueLinkIn):
        from modules.venues import places
        return guard(lambda: places.link_venue(_graph(request), body.target_id, body.place_info))

    # ---- Habit Routines --------------------------------------------------

    @router.post("/routines")
    def create_routine_endpoint(request: Request, body: RoutineCreateIn):
        from modules.routines import tracker
        return guard(lambda: tracker.create_routine(_graph(request), body.name, body.trigger, body.time_of_day, body.items))

    @router.post("/routines/{routine_id}/complete")
    def complete_routine_endpoint(request: Request, routine_id: str):
        from modules.routines import tracker
        return guard(lambda: tracker.log_routine_completion(_graph(request), routine_id))

    @router.get("/routines/streaks")
    def get_routines_streaks_endpoint(request: Request):
        from modules.routines import tracker
        return tracker.get_routines_status(_graph(request))

    # ---- Personal Knowledge Vault ----------------------------------------

    @router.post("/vault/notes")
    def create_vault_note_endpoint(request: Request, body: VaultNoteIn):
        from modules.vault import semantic_notes
        return guard(lambda: semantic_notes.save_note(_graph(request), body.title, body.content, body.tags))

    @router.get("/vault/search")
    def search_vault_endpoint(request: Request, query: str = "", tag: str = ""):
        from modules.vault import semantic_notes
        return semantic_notes.search_vault(_graph(request), query=query, tag=tag)

    # ---- Energy & Focus Balance Analytics --------------------------------

    @router.get("/horizon/energy-balance")
    def energy_balance_endpoint(request: Request):
        from modules.horizon import energy_balance
        return energy_balance.get_energy_balance(_graph(request))

    # ---- AI Life Assistant Chat Gateway ----------------------------------

    @router.post("/assistant/chat")
    def assistant_chat_endpoint(request: Request, body: AssistantChatIn):
        from gateway import assistant_chat
        claude = getattr(request.app.state, "claude", None)
        return guard(lambda: assistant_chat.process_assistant_message(_graph(request), body.message, claude=claude))

    # ---- Retro Forecast & Auto Generator ---------------------------------

    @router.get("/horizon/retro/forecast")
    def retro_forecast_endpoint(request: Request, goal_id: str):
        from modules.horizon import retro_forecaster
        return guard(lambda: retro_forecaster.forecast_goal_completion(_graph(request), goal_id))

    @router.post("/horizon/retro/auto-generate")
    def auto_generate_retro_endpoint(request: Request):
        from modules.horizon import retro_forecaster
        return retro_forecaster.generate_auto_retro(_graph(request))

    # ---- Multi-Calendar Sync Importer -----------------------------------

    @router.post("/calendar/sync-import")
    def calendar_sync_import_endpoint(request: Request, body: CalendarSyncIn):
        from modules.calendar import sync_engine
        return guard(lambda: sync_engine.import_ics_feed(_graph(request), body.ics_content))

    # ---- AI Weekly Auto-Planner ----------------------------------------

    @router.post("/horizon/planner/auto-draft")
    def auto_draft_planner_endpoint(request: Request, week: str = "W01"):
        from modules.horizon import auto_planner
        return guard(lambda: auto_planner.auto_draft_week_plan(_graph(request), week=week))

    # ---- Financial Goal Tracker ----------------------------------------

    @router.post("/finance/goals")
    def create_financial_goal_endpoint(request: Request, body: FinancialGoalIn):
        from modules.finance import budget_tracker
        return guard(lambda: budget_tracker.create_financial_goal(_graph(request), body.title, body.target_amount, body.current_amount, body.currency))

    @router.post("/finance/goals/{goal_id}/progress")
    def log_financial_progress_endpoint(request: Request, goal_id: str, body: FinancialProgressIn):
        from modules.finance import budget_tracker
        return guard(lambda: budget_tracker.log_financial_progress(_graph(request), goal_id, body.amount_delta))

    @router.get("/finance/summary")
    def get_financial_summary_endpoint(request: Request):
        from modules.finance import budget_tracker
        return budget_tracker.get_financial_summary(_graph(request))

    # ---- Backup Restore Engine -----------------------------------------

    @router.post("/export/restore")
    def restore_user_bundle_endpoint(request: Request, body: UserBundleRestoreIn):
        from modules.backup import import_graph
        return guard(lambda: import_graph.restore_user_bundle(_graph(request), body.bundle_data))

    # ---- System Audit Logger --------------------------------------------

    @router.post("/security/audit-log")
    def log_security_event_endpoint(request: Request, body: AuditLogIn):
        from modules.security import audit_logger
        return guard(lambda: audit_logger.log_security_event(_graph(request), body.event_type, body.actor_id, body.details))

    @router.get("/security/audit-log")
    def get_security_audit_log_endpoint(request: Request, limit: int = 100):
        from modules.security import audit_logger
        return audit_logger.get_security_audit_log(_graph(request), limit=limit)

    # ---- Personal Reflection Journal -------------------------------------

    @router.post("/journal/entries")
    def create_journal_entry_endpoint(request: Request, body: JournalEntryIn):
        from modules.memento import journal
        return guard(lambda: journal.log_journal_entry(_graph(request), body.wins, body.gratitude, body.reflection, body.mood_rating))

    @router.get("/journal/entries")
    def get_journal_entries_endpoint(request: Request, limit: int = 50):
        from modules.memento import journal
        return journal.get_journal_entries(_graph(request), limit=limit)

    # ---- Goal Dependency & Blocker Solver --------------------------------

    @router.post("/goals/dependency")
    def link_goal_dependency_endpoint(request: Request, body: GoalDependencyIn):
        from modules.horizon import blocker_solver
        return guard(lambda: blocker_solver.link_goal_dependency(_graph(request), body.goal_id, body.depends_on_goal_id))

    @router.get("/goals/{goal_id}/blockers")
    def get_goal_blockers_endpoint(request: Request, goal_id: str):
        from modules.horizon import blocker_solver
        return guard(lambda: blocker_solver.get_goal_blockers(_graph(request), goal_id))

    # ---- Multi-Provider SSO Identity ------------------------------------

    @router.post("/auth/sso/login")
    def sso_login_endpoint(request: Request, body: SsoLoginIn):
        from modules.accounts import sso_auth
        return guard(lambda: sso_auth.authenticate_sso(_graph(request), body.provider, body.provider_user_id, body.email, body.phone, body.name))

    @router.post("/auth/sso/link")
    def sso_link_endpoint(request: Request, body: SsoLinkIn):
        from modules.accounts import sso_auth
        return guard(lambda: sso_auth.link_identity_provider(_graph(request), body.account_id, body.provider, body.provider_user_id))

    @router.get("/auth/providers")
    def get_sso_providers_endpoint():
        from modules.accounts import sso_auth
        return sso_auth.get_supported_providers()

    # ---- Billing & Payments Gateway -------------------------------------

    @router.post("/billing/customer")
    def create_billing_customer_endpoint(request: Request, body: BillingCustomerIn):
        from modules.billing import payments
        return guard(lambda: payments.create_customer(_graph(request), body.account_id, body.email))

    @router.post("/billing/subscribe")
    def subscribe_billing_plan_endpoint(request: Request, body: BillingSubscribeIn):
        from modules.billing import payments
        return guard(lambda: payments.subscribe_plan(_graph(request), body.account_id, body.plan_id, body.payment_token))

    @router.get("/billing/status")
    def get_billing_status_endpoint(request: Request, account_id: str):
        from modules.billing import payments
        return guard(lambda: payments.get_billing_status(_graph(request), account_id))

    # ---- Structured System Logger & Telemetry ----------------------------

    @router.post("/system/log")
    def log_system_event_endpoint(request: Request, body: SystemLogIn):
        from modules.telemetry import system_logger
        return guard(lambda: system_logger.log_system_event(_graph(request), body.level, body.module, body.message, body.metadata))

    @router.get("/system/logs")
    def get_system_logs_endpoint(request: Request, level: str | None = None, limit: int = 100):
        from modules.telemetry import system_logger
        return system_logger.get_system_logs(_graph(request), level=level, limit=limit)

    # ---- Security Hardening & Threat Defense -----------------------------

    @router.post("/security/sanitize")
    def sanitize_text_endpoint(body: SanitizeIn):
        from modules.security import sanitizer
        return sanitizer.scan_prompt_injection(body.text)

    @router.post("/security/verify-token")
    def verify_token_endpoint(body: TokenVerifyIn):
        from modules.security import crypto_tokens
        valid = crypto_tokens.verify_payload(body.data, body.signature)
        return {"valid": valid}

    # ---- 8-Core Ecosystem Expansion -------------------------------------

    @router.get("/graph/topology")
    def get_graph_topology_endpoint(request: Request):
        from substrate import topology
        return topology.export_graph_topology(_graph(request))

    @router.post("/goals/nudges/scan")
    def scan_milestone_nudges_endpoint(request: Request):
        from modules.horizon import milestone_nudges
        return milestone_nudges.scan_milestone_nudges(_graph(request))

    @router.post("/vault/auto-link")
    def auto_link_notes_endpoint(request: Request):
        from modules.vault import auto_linker
        return auto_linker.auto_link_notes(_graph(request))

    @router.post("/routines/sleep")
    def log_sleep_data_endpoint(request: Request, body: SleepDataIn):
        from modules.routines import sleep_tracker
        return guard(lambda: sleep_tracker.log_sleep_data(_graph(request), body.date, body.hours_slept, body.sleep_quality, body.wake_time))

    @router.get("/routines/sleep/summary")
    def get_circadian_summary_endpoint(request: Request):
        from modules.routines import sleep_tracker
        return sleep_tracker.get_circadian_summary(_graph(request))

    @router.post("/safety/broadcast")
    def broadcast_emergency_alert_endpoint(request: Request, body: EmergencyAlertIn):
        from modules.safety import contact_broadcast
        return guard(lambda: contact_broadcast.broadcast_emergency_alert(_graph(request), body.message))

    @router.post("/venues/itinerary/generate")
    def generate_crew_itinerary_endpoint(request: Request, body: CrewItineraryIn):
        from modules.venues import itinerary_builder
        return guard(lambda: itinerary_builder.generate_crew_itinerary(_graph(request), body.venue_ids, body.start_time))

    @router.post("/security/anomaly/scan")
    def scan_security_anomalies_endpoint(request: Request):
        from modules.security import anomaly_detector
        return anomaly_detector.scan_security_anomalies(_graph(request))

    @router.get("/routines/analytics")
    def get_routine_analytics_endpoint(request: Request):
        from modules.routines import analytics
        return analytics.get_routine_analytics(_graph(request))

    @router.get("/goals/{goal_id}/projection")
    def project_goal_completion_endpoint(request: Request, goal_id: str):
        from modules.horizon import progress_model
        return guard(lambda: progress_model.project_goal_completion(_graph(request), goal_id))

    @router.post("/routines/mindfulness/session")
    def log_focus_session_endpoint(request: Request, body: FocusSessionIn):
        from modules.routines import mindfulness
        return guard(lambda: mindfulness.log_focus_session(_graph(request), body.duration_minutes, body.distraction_count, body.note))

    @router.get("/routines/mindfulness/summary")
    def get_mindfulness_summary_endpoint(request: Request):
        from modules.routines import mindfulness
        return mindfulness.get_mindfulness_summary(_graph(request))

    @router.get("/graph/export/graphml")
    def export_graphml_endpoint(request: Request):
        from substrate import graphml_exporter
        return Response(content=graphml_exporter.export_graphml(_graph(request)), media_type="application/xml")

    @router.post("/ledger/split")
    def split_expenses_endpoint(request: Request, body: ExpenseSplitIn):
        from modules.ledger import splitter
        return guard(lambda: splitter.split_expenses(_graph(request), body.total_amount, body.currency, body.payer_id, body.member_ids))

    @router.post("/reconnect/auto-remind")
    def enqueue_decay_reminders_endpoint(request: Request):
        from modules.reconnect import auto_reminder
        return auto_reminder.enqueue_decay_reminders(_graph(request))

    @router.get("/graph/centrality")
    def calculate_centrality_endpoint(request: Request):
        from substrate import centrality
        return centrality.calculate_centrality(_graph(request))

    @router.post("/comms/messages")
    def send_message_endpoint(request: Request, body: ChatMessageIn):
        from modules.comms import chat
        return guard(lambda: chat.send_message(_graph(request), body.sender_id, body.recipient_id, body.body, body.linked_entity_id))

    @router.get("/comms/messages")
    def get_messages_endpoint(request: Request, recipient_id: str):
        from modules.comms import chat
        return chat.get_messages(_graph(request), recipient_id)

    @router.post("/miniapp/register")
    def register_miniapp_endpoint(request: Request, body: MiniAppRegisterIn):
        from modules.miniapp import registry
        return guard(lambda: registry.register_miniapp(_graph(request), body.name, body.url, body.icon))

    @router.get("/miniapp/list")
    def list_miniapps_endpoint(request: Request):
        from modules.miniapp import registry
        return registry.list_miniapps(_graph(request))

    @router.post("/ledger/settle")
    def settle_split_endpoint(request: Request, body: SplitSettleIn):
        from modules.ledger import billing
        return guard(lambda: billing.settle_split(_graph(request), body.split_id, body.settled_amount))

    @router.post("/venues/optimize-itinerary")
    def optimize_outing_route_endpoint(request: Request, body: OptimizeItineraryIn):
        from modules.venues import optimizer
        return optimizer.optimize_outing_route(_graph(request), body.place_ids)

    @router.get("/routines/synergy")
    def calculate_habit_synergies_endpoint(request: Request):
        from modules.routines import synergy
        return synergy.calculate_habit_synergies(_graph(request))

    @router.post("/horizon/crew-goals")
    def create_crew_goal_endpoint(request: Request, body: CrewGoalIn):
        from modules.horizon import crew_goals
        return guard(lambda: crew_goals.create_crew_goal(_graph(request), body.crew_id, body.title, body.target_date))

    @router.post("/ledger/sync-queue")
    def enqueue_sync_item_endpoint(request: Request, body: LedgerSyncIn):
        from modules.ledger import sync_queue
        return guard(lambda: sync_queue.enqueue_sync_item(_graph(request), body.model_dump()))

    @router.post("/ledger/sync-queue/process")
    def process_sync_queue_endpoint(request: Request):
        from modules.ledger import sync_queue
        return sync_queue.process_sync_queue(_graph(request))

    @router.post("/routines/sleep-nudge")
    def generate_circadian_nudge_endpoint(request: Request):
        from modules.routines import sleep_nudges
        return sleep_nudges.generate_circadian_nudge(_graph(request))

    @router.get("/graph/predictions")
    def predict_relationships_endpoint(request: Request):
        from substrate import predictor
        return predictor.predict_relationships(_graph(request))

    @router.post("/miniapp/resources")
    def register_resource_endpoint(request: Request, body: ResourceRegisterIn):
        from modules.miniapp import resources
        return guard(lambda: resources.register_resource(_graph(request), body.owner_id, body.name))

    @router.post("/miniapp/resources/loan")
    def request_loan_endpoint(request: Request, body: ResourceLoanIn):
        from modules.miniapp import resources
        return guard(lambda: resources.request_loan(_graph(request), body.resource_id, body.borrower_id))

    @router.post("/routines/streak-nudge")
    def trigger_streak_nudges_endpoint(request: Request):
        from modules.routines import streak_nudges
        return streak_nudges.trigger_streak_nudges(_graph(request))

    @router.post("/graph/qa")
    def query_graph_memories_endpoint(request: Request, body: GraphQaIn):
        from substrate import qa_bot
        return guard(lambda: qa_bot.query_graph_memories(_graph(request), body.query_text))

    @router.post("/venues/match-outing")
    def match_outing_slots_endpoint(request: Request, body: OutingMatchIn):
        from modules.venues import matcher
        return guard(lambda: matcher.match_outing_slots(_graph(request), body.member_ids, body.day))

    @router.get("/vitals/energy-forecast")
    def forecast_energy_battery_endpoint(request: Request):
        from modules.vitals import energy_forecaster
        return energy_forecaster.forecast_energy_battery(_graph(request))

    @router.get("/graph/integrity")
    def audit_graph_integrity_endpoint(request: Request):
        from substrate import integrity
        return integrity.audit_graph_integrity(_graph(request))

    return router
