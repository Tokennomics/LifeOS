"""Regressions for the pre-hosting audit (2026-08-05).

Every test here corresponds to a hole that was *demonstrated* against a running gateway with
two real accounts, not one that was theorised. They are grouped by the hole rather than by
the module, because that is how they will be read if one of them ever fails again.
"""

import os

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app
from substrate import safefetch

PW = "correct-horse-battery"


@pytest.fixture(autouse=True)
def _no_ambient_limits(monkeypatch):
    monkeypatch.setenv(rate_limiter.DISABLE_VAR, "1")
    monkeypatch.delenv(safefetch.ALLOW_PRIVATE_VAR, raising=False)


@pytest.fixture
def world(cfg):
    """Ana with something private, and Mallory with an account and bad intentions."""
    client = TestClient(create_app(cfg))
    for name in ("ana", "mallory"):
        assert client.post("/v1/auth/register",
                           json={"handle": name, "password": PW}).status_code == 200
    tokens = {n: client.post("/v1/auth/login",
                             json={"handle": n, "password": PW}).json()["token"]
              for n in ("ana", "mallory")}
    head = {n: {"Authorization": f"Bearer {t}"} for n, t in tokens.items()}
    ids = {n: client.get("/v1/auth/me", headers=head[n]).json()["account_id"] for n in head}

    client.post("/v1/capture", headers=head["ana"], json={"text": "Ana's therapy notes"})
    return {"c": client, "h": head, "id": ids}


# ---- CRITICAL: acting as another account -------------------------------------

def test_a_stranger_cannot_take_over_a_crew_by_naming_its_admin(world):
    """The worst finding, and it was verified end to end before it was fixed: `by` came off
    the request body and `crews._require_admin` compared it to the ACL, so *naming* the
    admin was the same as *being* the admin. Mallory read the public roster, called
    /v1/crews/block with `by` set to Ana's id, and removed Ana from her own crew — members
    1 -> 0, admins emptied."""
    c, h, ids = world["c"], world["h"], world["id"]
    crew = c.post("/v1/crews", headers=h["ana"], json={
        "name": "Lisbon Sushi Club", "city": "Lisbon", "visibility": "public",
        "admission": "approval", "admin_id": ids["ana"]}).json()["id"]

    attack = c.post("/v1/crews/block", headers=h["mallory"],
                    json={"crew_id": crew, "person_id": ids["ana"], "by": ids["ana"]})
    assert attack.status_code == 403

    intact = c.get(f"/v1/crews/{crew}", headers=h["ana"]).json()
    assert intact["member_count"] == 1 and ids["ana"] in intact["admins"]


@pytest.mark.parametrize("path,body", [
    ("/v1/crews/policy", {"crew_id": "x", "visibility": "private", "admission": "open"}),
    ("/v1/crews/request/approve", {"crew_id": "x", "person_id": "y"}),
    ("/v1/crews/request/deny", {"crew_id": "x", "person_id": "y"}),
    ("/v1/crews/unblock", {"crew_id": "x", "person_id": "y"}),
    ("/v1/crews/invite", {"crew_id": "x", "person_id": "y"}),
])
def test_every_admin_action_refuses_a_borrowed_identity(world, path, body):
    r = world["c"].post(path, headers=world["h"]["mallory"],
                        json={**body, "by": world["id"]["ana"]})
    assert r.status_code == 403, f"{path} accepted someone else's id"


def test_a_message_cannot_be_attributed_to_someone_else(world):
    """Mallory sent 'I quit, effective today' as Ana."""
    r = world["c"].post("/v1/comms/messages", headers=world["h"]["mallory"], json={
        "sender_id": world["id"]["ana"], "recipient_id": "x", "body": "I quit"})
    assert r.status_code == 403


@pytest.mark.parametrize("path,body", [
    ("/v1/comms/chatroom/send", {"event_id": "e", "message": "spoofed"}),
    ("/v1/venues/rsvp", {"event_id": "e", "status": "going"}),
    ("/v1/venues/convoy/update", {"latitude": 1.0, "longitude": 2.0,
                                  "eta": "20:00", "event_id": "e"}),
])
def test_other_identity_claims_are_refused_too(world, path, body):
    r = world["c"].post(path, headers=world["h"]["mallory"],
                        json={**body, "user_id": world["id"]["ana"]})
    assert r.status_code == 403, f"{path} accepted someone else's id"


def test_your_own_id_is_still_fine(world):
    """Pinning the actor must not break a client that correctly sends its own id."""
    r = world["c"].post("/v1/comms/messages", headers=world["h"]["mallory"], json={
        "sender_id": world["id"]["mallory"], "recipient_id": "x", "body": "hello"})
    assert r.status_code == 200


def test_omitting_the_id_uses_the_session(world):
    r = world["c"].post("/v1/comms/messages", headers=world["h"]["ana"],
                        json={"recipient_id": "x", "body": "hi"})
    assert r.status_code == 200 and r.json()["sender_id"] == world["id"]["ana"]


# ---- HIGH: cross-tenant leakage through export ------------------------------

def test_export_does_not_carry_other_accounts_provenance(world):
    """`entities` was owner-filtered and `edges`/`observations` were not, so every export
    included a provenance row for every write on the box: entity id, module, timestamp — a
    complete activity timeline for every other user."""
    mine = world["c"].get("/v1/export", headers=world["h"]["ana"]).json()
    theirs = world["c"].get("/v1/export", headers=world["h"]["mallory"]).json()

    assert len(mine["observations"]) > 0, "Ana must still get her own provenance"
    assert theirs["entities"] == [] and theirs["observations"] == []
    assert theirs["edges"] == []


def test_export_still_returns_everything_you_own(world):
    """Law 2 is full export. Scoping must not quietly become withholding."""
    body = world["c"].get("/v1/export", headers=world["h"]["ana"]).json()
    assert "therapy" in repr(body["entities"])
    owned = {e["id"] for e in body["entities"]}
    assert all(o["entity_id"] in owned for o in body["observations"])


def test_graph_summary_is_not_a_cross_tenant_activity_oracle(world):
    summary = world["c"].get("/v1/graph", headers=world["h"]["mallory"]).json()
    assert summary["entities"] == 0 and summary["observations"] == 0
    assert summary["edges"] == 0


# ---- HIGH: SSRF --------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",      # AWS/Render/DO instance credentials
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://127.0.0.1:8787/v1/stats",
    "http://localhost:6379/",
    "http://10.0.0.1/", "http://192.168.1.1/", "http://172.16.0.1/",
    "http://[::1]:8787/", "http://0.0.0.0/",
])
def test_the_server_refuses_to_be_aimed_at_itself_or_the_metadata_service(url):
    with pytest.raises(safefetch.UnsafeURL):
        safefetch.check_url(url)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "gopher://x/", "ftp://x/y",
                                 "javascript:alert(1)", "", "http://"])
def test_only_http_urls_are_fetched(url):
    with pytest.raises(safefetch.UnsafeURL):
        safefetch.check_url(url)


def test_a_hostname_that_resolves_to_loopback_is_still_refused():
    """Blocking the *name* 'localhost' is theatre — 127.0.0.1 has a thousand spellings and
    an attacker can point their own DNS record at it. The resolved address is what counts."""
    for spelling in ("http://127.0.0.1/", "http://127.1/", "http://2130706433/"):
        with pytest.raises(safefetch.UnsafeURL):
            safefetch.check_url(spelling)


def test_a_deliberate_lan_calendar_can_be_allowed(monkeypatch):
    """The NucBox case: the calendar really is on the LAN, and the person who needs this
    knows they need it."""
    monkeypatch.setenv(safefetch.ALLOW_PRIVATE_VAR, "1")
    assert safefetch.check_url("http://192.168.1.50:8080/cal.ics")


def test_the_feed_endpoints_use_the_guard(world):
    r = world["c"].post("/v1/feeds", headers=world["h"]["mallory"],
                        json={"url": "http://169.254.169.254/latest/meta-data/"})
    assert r.status_code == 200, "adding is allowed; fetching is where the guard bites"
    feed_id = r.json()["feed_id"]
    synced = world["c"].post(f"/v1/feeds/{feed_id}/sync", headers=world["h"]["mallory"],
                             json={})
    assert synced.json()["status"] == "fetch_failed"
    assert synced.json()["added"] == 0


# ---- HIGH: brute force -------------------------------------------------------

def test_login_stops_accepting_guesses(cfg, monkeypatch):
    """60 wrong passwords used to return 60 clean 401s. rate_limiter.py existed the whole
    time and was imported by nothing."""
    monkeypatch.delenv(rate_limiter.DISABLE_VAR, raising=False)
    client = TestClient(create_app(cfg))
    client.post("/v1/auth/register", json={"handle": "ana", "password": PW})

    codes = [client.post("/v1/auth/login",
                         json={"handle": "ana", "password": f"guess{i}"}).status_code
             for i in range(30)]
    assert 429 in codes, "no back-off on repeated failed logins"
    assert codes.index(429) <= 12


def test_registration_is_capped(cfg, monkeypatch):
    monkeypatch.delenv(rate_limiter.DISABLE_VAR, raising=False)
    client = TestClient(create_app(cfg))
    codes = [client.post("/v1/auth/register",
                         json={"handle": f"bot{i}", "password": PW}).status_code
             for i in range(12)]
    assert 429 in codes


def test_the_limiter_counts_clients_separately():
    limiter = rate_limiter.RateLimiter()
    for _ in range(10):
        limiter.check_rate_limit("1.2.3.4", "auth:login", 10, 300)
    assert limiter.check_rate_limit("1.2.3.4", "auth:login", 10, 300)["allowed"] is False
    assert limiter.check_rate_limit("5.6.7.8", "auth:login", 10, 300)["allowed"] is True


def test_each_app_gets_its_own_counters(cfg, monkeypatch):
    """A module-level singleton outlived the app that made it, so a second gateway in the
    same process inherited the first one's exhausted buckets."""
    monkeypatch.delenv(rate_limiter.DISABLE_VAR, raising=False)
    first, second = TestClient(create_app(cfg)), TestClient(create_app(cfg))
    for _ in range(12):
        first.post("/v1/auth/register", json={"handle": "x", "password": PW})
    assert first.post("/v1/auth/register",
                      json={"handle": "y", "password": PW}).status_code == 429
    assert second.post("/v1/auth/register",
                       json={"handle": "z", "password": PW}).status_code == 200


def test_a_proxied_client_is_counted_by_its_own_address(cfg, monkeypatch):
    """Behind Caddy the socket address is the proxy for every caller — one bucket for the
    whole internet, which is worse than no limit."""
    monkeypatch.delenv(rate_limiter.DISABLE_VAR, raising=False)
    client = TestClient(create_app(cfg))
    client.post("/v1/auth/register", json={"handle": "ana", "password": PW})

    for i in range(15):
        client.post("/v1/auth/login", json={"handle": "ana", "password": "no"},
                    headers={"X-Forwarded-For": "9.9.9.9"})
    blocked = client.post("/v1/auth/login", json={"handle": "ana", "password": "no"},
                          headers={"X-Forwarded-For": "9.9.9.9"})
    other = client.post("/v1/auth/login", json={"handle": "ana", "password": "no"},
                        headers={"X-Forwarded-For": "8.8.8.8"})
    assert blocked.status_code == 429 and other.status_code == 401


# ---- unchanged guarantees ----------------------------------------------------

def test_health_is_still_the_only_unauthenticated_route(world):
    c = world["c"]
    assert c.get("/health").status_code == 200
    for path in ("/v1/export", "/v1/graph", "/v1/stats", "/v1/weekend", "/v1/feeds"):
        assert c.get(path).status_code == 401, f"{path} answered without a token"


def test_cors_origins_can_be_narrowed(cfg):
    app = create_app({**cfg, "gateway": {**cfg["gateway"],
                                         "cors_origins": ["https://lifeos.example"]}})
    origins = [m for m in app.user_middleware if "CORS" in str(m)]
    assert origins and "https://lifeos.example" in str(origins[0])


# =============================================================================
# Round two (2026-08-07), after `main` gained 80 commits of new modules.
# Found by sweeping every POST body field that names an identity, rather than
# reading thirteen modules by hand.
# =============================================================================

@pytest.fixture
def operator(cfg):
    """A caller holding the static gateway token — the instance operator."""
    app_cfg = {**cfg, "gateway": {**cfg["gateway"], "auth_token": "owner-key"}}
    client = TestClient(create_app(app_cfg))
    for name in ("ana", "mallory"):
        client.post("/v1/auth/register", json={"handle": name, "password": PW})
    tokens = {n: client.post("/v1/auth/login",
                             json={"handle": n, "password": PW}).json()["token"]
              for n in ("ana", "mallory")}
    head = {n: {"Authorization": f"Bearer {t}"} for n, t in tokens.items()}
    head["operator"] = {"Authorization": "Bearer owner-key"}
    ids = {n: client.get("/v1/auth/me", headers=head[n]).json()["account_id"]
           for n in ("ana", "mallory")}
    return {"c": client, "h": head, "id": ids}


def test_the_reported_person_cannot_read_the_report_about_himself(operator, monkeypatch):
    """The worst of the second pass, and worse in kind than the crew takeover: a
    physical-safety feature failing open. Mallory could read Ana's account of being
    followed home — including that it was Ana who filed it — and then dismiss it."""
    monkeypatch.setenv("LIFEOS_SIGNING_KEY", "b7Qv2xLp9NrK4mYtZs8WfCg3JhDn6VaE")
    monkeypatch.setenv("LIFEOS_DATING_ENABLED", "1")
    c, h, ids = operator["c"], operator["h"], operator["id"]

    filed = c.post("/v1/dating/report", headers=h["ana"], json={
        "subject_account_id": ids["mallory"], "reason": "he followed me home from the bar"})
    assert filed.status_code == 200

    seen = c.get("/v1/dating/reports", headers=h["mallory"])
    assert seen.status_code == 403
    assert "followed me home" not in seen.text

    queue = c.get("/v1/dating/reports", headers=h["operator"]).json()["reports"]
    assert len(queue) == 1 and queue[0]["reason"] == "he followed me home from the bar"


def test_the_reported_person_cannot_dismiss_the_report(operator, monkeypatch):
    monkeypatch.setenv("LIFEOS_SIGNING_KEY", "b7Qv2xLp9NrK4mYtZs8WfCg3JhDn6VaE")
    monkeypatch.setenv("LIFEOS_DATING_ENABLED", "1")
    c, h, ids = operator["c"], operator["h"], operator["id"]
    c.post("/v1/dating/report", headers=h["ana"],
           json={"subject_account_id": ids["mallory"], "reason": "assault"})
    report_id = c.get("/v1/dating/reports", headers=h["operator"]).json()["reports"][0]["id"]

    killed = c.post(f"/v1/dating/reports/{report_id}/resolve", headers=h["mallory"],
                    json={"action": "dismissed"})
    assert killed.status_code == 403
    assert len(c.get("/v1/dating/reports", headers=h["operator"]).json()["reports"]) == 1


def test_the_reporter_cannot_read_the_queue_either(operator, monkeypatch):
    """Not a punishment — "who else has complained about this person" is not hers to read."""
    monkeypatch.setenv("LIFEOS_SIGNING_KEY", "b7Qv2xLp9NrK4mYtZs8WfCg3JhDn6VaE")
    monkeypatch.setenv("LIFEOS_DATING_ENABLED", "1")
    c, h, ids = operator["c"], operator["h"], operator["id"]
    c.post("/v1/dating/report", headers=h["ana"],
           json={"subject_account_id": ids["mallory"], "reason": "x"})
    assert c.get("/v1/dating/reports", headers=h["ana"]).status_code == 403


def test_the_crew_moderation_queue_is_operator_only(operator):
    c, h = operator["c"], operator["h"]
    assert c.get("/v1/crews/reports/open", headers=h["mallory"]).status_code == 403
    assert c.post("/v1/crews/report/resolve", headers=h["mallory"],
                  json={"report_id": "x", "action": "dismissed"}).status_code == 403
    assert c.get("/v1/crews/reports/open", headers=h["operator"]).status_code == 200


def test_a_named_moderator_account_can_service_the_queue(operator, monkeypatch):
    """A solo operator on a phone will not want to carry the static token around."""
    monkeypatch.setenv("LIFEOS_MODERATOR_ACCOUNTS", operator["id"]["ana"])
    c, h = operator["c"], operator["h"]
    assert c.get("/v1/crews/reports/open", headers=h["ana"]).status_code == 200
    assert c.get("/v1/crews/reports/open", headers=h["mallory"]).status_code == 403


def test_you_cannot_vote_as_another_member(world):
    """Ballot stuffing: `member_id` came off the body, so one account could cast every
    member's vote in a crew's venue poll."""
    r = world["c"].post("/v1/venues/vote", headers=world["h"]["mallory"],
                        json={"poll_id": "p", "place_id": "sushi",
                              "member_id": world["id"]["ana"]})
    assert r.status_code == 403


def test_you_cannot_forge_an_audit_log_entry_as_someone_else(world):
    """The audit log is what you read after an incident. Anyone could write false entries
    attributed to anyone."""
    r = world["c"].post("/v1/security/audit-log", headers=world["h"]["mallory"],
                        json={"event_type": "login_failure", "actor_id": world["id"]["ana"],
                              "details": {}})
    assert r.status_code == 403


def test_you_cannot_register_a_resource_owned_by_someone_else(world):
    r = world["c"].post("/v1/miniapp/resources", headers=world["h"]["mallory"],
                        json={"owner_id": world["id"]["ana"], "name": "drill"})
    assert r.status_code == 403


def test_every_identity_field_in_the_whole_api_is_pinned(world):
    """The sweep that found the three above, kept as a test so a NEW endpoint that takes an
    identity from the body fails here rather than in production."""
    c, h, ids = world["c"], world["h"], world["id"]
    identity = {"user_id", "account_id", "sender_id", "member_id", "owner_id", "reporter_id",
                "host_id", "admin_id", "by", "actor_id", "author_id", "requester_id",
                "creator_id", "participant_id"}
    spec = c.app.openapi()
    defs = spec.get("components", {}).get("schemas", {})

    def sample(prop):
        return {"number": 1.0, "integer": 1, "boolean": True,
                "array": [], "object": {}}.get(prop.get("type"), "x")

    accepted = []
    for path, ops in spec["paths"].items():
        op = ops.get("post")
        if not op or "requestBody" not in op:
            continue
        schema = op["requestBody"].get("content", {}).get("application/json", {}).get("schema", {})
        model = defs.get(schema["$ref"].split("/")[-1], {}) if "$ref" in schema else schema
        props = model.get("properties", {})
        fields = [p for p in props if p in identity]
        if not fields:
            continue
        body = {k: sample(v) for k, v in props.items()}
        body.update({f: ids["ana"] for f in fields})
        if c.post(path, headers=h["mallory"], json=body).status_code == 200:
            accepted.append((path, fields))
    assert accepted == [], f"these accepted another account's id: {accepted}"
