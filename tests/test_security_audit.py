"""Regressions for the pre-hosting audit (2026-08-05).

Every test here corresponds to a hole that was *demonstrated* against a running gateway with
two real accounts, not one that was theorised. They are grouped by the hole rather than by
the module, because that is how they will be read if one of them ever fails again.
"""

import os
import pathlib

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


def test_a_single_request_cannot_store_an_unbounded_blob(world):
    """A signed-up user could store megabytes per request and fill the disk — which on a
    small hosted box takes down everyone's instance, not just their own."""
    from gateway.main import MAX_BODY_BYTES
    r = world["c"].post("/v1/capture", headers=world["h"]["mallory"],
                        json={"text": "A" * (MAX_BODY_BYTES + 1000)})
    assert r.status_code == 413
    stored = world["c"].get("/v1/export", headers=world["h"]["mallory"]).json()["entities"]
    assert max((len(repr(e)) for e in stored), default=0) < MAX_BODY_BYTES


def test_an_ordinary_note_is_unaffected(world):
    assert world["c"].post("/v1/capture", headers=world["h"]["mallory"],
                           json={"text": "climb twice this week"}).status_code == 200


def test_the_sign_in_screen_can_render_before_anyone_signs_in(world):
    """This lived on the authed router, so a client had to already be signed in to discover
    how to sign in. Found by walking the product as a new user."""
    r = world["c"].get("/v1/auth/providers")
    assert r.status_code == 200 and r.json()["password"] is True


def test_joining_a_crew_you_found_in_the_directory_works(world):
    """`crews.join` is local and `crews.request_join` is cross-account; both are correct,
    but /v1/crews/join was the obvious endpoint and returned "unknown crew" for a crew
    listed in the directory a moment earlier."""
    c, h, ids = world["c"], world["h"], world["id"]
    crew = c.post("/v1/crews", headers=h["ana"], json={
        "name": "Lisbon Climbers", "city": "Lisbon", "visibility": "public",
        "admission": "open"}).json()["id"]
    assert c.post("/v1/crews/join", headers=h["mallory"],
                  json={"crew_id": crew}).status_code == 200
    assert c.get(f"/v1/crews/{crew}", headers=h["ana"]).json()["member_count"] == 2


# ---- the deploy would not have worked at all ---------------------------------

@pytest.mark.parametrize("env,expected_host", [
    ({}, "127.0.0.1"),                              # a laptop stays off the café wifi
    ({"PORT": "10000"}, "0.0.0.0"),                 # a PaaS sets PORT; loopback is unreachable
    ({"PORT": "10000", "LIFEOS_HOST": "127.0.0.1"}, "127.0.0.1"),   # explicit wins
])
def test_the_launcher_binds_somewhere_reachable(monkeypatch, env, expected_host):
    """It bound 127.0.0.1 unconditionally. In a container the process starts, the logs look
    healthy, and nothing outside can reach it — the whole deploy silently does nothing."""
    from scripts import launch
    for key in ("PORT", "LIFEOS_PORT", "LIFEOS_HOST"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    host, port = launch.resolve_bind()
    assert host == expected_host
    assert port == int(env.get("PORT", 8000))


def test_a_junk_port_falls_back_rather_than_crashing(monkeypatch):
    from scripts import launch
    monkeypatch.setenv("PORT", "not-a-number")
    monkeypatch.delenv("LIFEOS_HOST", raising=False)
    host, port = launch.resolve_bind()
    assert port == 8000 and host == "0.0.0.0"


# ---- no vendor-shaped credentials in the tree --------------------------------

# Assembled at import time rather than written out, so this file does not trip its own scan.
# Each entry is (vendor, prefix) where the prefix is the part vendors guarantee.
_VENDOR_PREFIXES = [
    ("Stripe secret key", "sk_" + "live_"),
    ("Stripe test key", "sk_" + "test_"),
    ("Stripe webhook signing secret", "wh" + "sec_"),
    ("Stripe restricted key", "rk_" + "live_"),
    ("GitHub personal token", "gh" + "p_"),
    ("GitHub fine-grained token", "github" + "_pat_"),
    ("AWS access key id", "AKI" + "A"),
    ("Slack bot token", "xox" + "b-"),
    ("Google API key", "AIza" + "Sy"),
    ("Anthropic API key", "sk-" + "ant-"),
    ("OpenAI key", "sk-" + "proj-"),
]

_SCANNED_SUFFIXES = (".py", ".js", ".json", ".yml", ".yaml", ".md", ".html", ".toml", ".sh")


def _tracked_files():
    """git ls-files, so vendored deps and local scratch never enter the scan."""
    import subprocess
    root = pathlib.Path(__file__).resolve().parent.parent
    out = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True)
    for line in out.stdout.splitlines():
        path = root / line
        if path.suffix in _SCANNED_SUFFIXES and path.is_file():
            yield path


def test_no_vendor_credential_prefixes_are_committed():
    """A GitHub secret-scanning alert fired on `gateway/modules_api.py` for a Stripe webhook
    signing secret. The value was invented — this repo has never integrated Stripe — but it
    was spelled in Stripe's namespace, published on a public repo, and handed identically to
    every caller, which is a broken signing secret quite apart from the alert.

    The lesson is not "remove that one string". It is that code arrives here from several
    tools, and demo data that *looks* like a credential reads as a real leak to anyone
    scanning, including GitHub. Catch it in CI, not three days later in an email.

    If this fails on a genuinely fake value: do not add an ignore. Mint it at runtime
    (`_issued_credential`) or use a prefix that is not some vendor's."""
    hits = []
    here = pathlib.Path(__file__).resolve()
    for path in _tracked_files():
        if path == here:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for vendor, prefix in _VENDOR_PREFIXES:
            index = text.find(prefix)
            if index != -1:
                line = text.count("\n", 0, index) + 1
                hits.append(f"{path.name}:{line} looks like a {vendor}")
    assert hits == [], "credential-shaped literals committed: " + "; ".join(hits)


def test_an_issued_credential_is_never_the_same_twice(world):
    """The whole point of the fix. Two provisioning calls that return one shared string are
    worse than no secret at all, because callers will trust it to authenticate a webhook."""
    client, headers = world["c"], world["h"]["ana"]
    first = client.post("/v1/developers/webhooks", headers=headers,
                        json={"target_url": "https://a.example/hook"}).json()
    second = client.post("/v1/developers/webhooks", headers=headers,
                         json={"target_url": "https://b.example/hook"}).json()
    assert first["signing_secret"] != second["signing_secret"]
    assert len(first["signing_secret"]) >= 32

    keys = {client.post("/v1/developers/api-keys", headers=headers,
                        json={"app_name": "x"}).json()["api_key"] for _ in range(3)}
    assert len(keys) == 3


# ---- browser-side hardening --------------------------------------------------

def test_every_response_carries_the_security_headers(cfg):
    """There were none at all — not on the API, not on the PWA. Checked on `/health`
    precisely because it is the one route that answers before authentication."""
    client = TestClient(create_app(cfg))
    for path in ("/health", "/v1/auth/providers"):
        headers = client.get(path).headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "no-referrer"
        assert "content-security-policy" in headers


def test_the_csp_blocks_token_exfiltration_and_base_tag_injection(cfg):
    """The session token lives in localStorage, so the CSP's job here is not to stop a script
    running — `'unsafe-inline'` has to stay while the PWA has inline handlers — but to stop
    one *sending anything anywhere* once it does."""
    csp = TestClient(create_app(cfg)).get("/health").headers["content-security-policy"]
    directives = dict(part.strip().split(" ", 1) for part in csp.split(";") if " " in part.strip())
    assert directives["connect-src"] == "'self'", "an injected script must not reach a third party"
    assert directives["object-src"] == "'none'"
    assert directives["base-uri"] == "'self'"
    assert directives["frame-ancestors"] == "'none'"
    assert "'unsafe-eval'" not in csp


def test_the_referrer_policy_covers_invite_tokens(cfg):
    """Crew invites are `/app/?invite_token=…`. With a default referrer policy, every
    outbound link and every remote image on that page hands the token to a third party."""
    assert TestClient(create_app(cfg)).get(
        "/health").headers["referrer-policy"] == "no-referrer"


def test_the_pwa_escapes_every_value_it_renders_from_a_response():
    """Two render sites interpolated response fields straight into innerHTML. Neither was
    exploitable — both endpoints return hardcoded demo data — which is exactly why it would
    have survived until the day those endpoints started returning real names."""
    import pathlib
    app_js = (pathlib.Path(__file__).resolve().parent.parent
              / "surfaces" / "app" / "www" / "app.js").read_text(encoding="utf-8")
    assert "${esc(c.name)} (€${Number(c.amount).toFixed(2)})" in app_js

    # The second site was the voice-brief render, which interpolated `s.time`, `s.place`
    # and `s.activity` from a response. That handler is gone: it displayed two hardcoded
    # Lisbon venues, and the endpoint now reads a real transcript. Its replacement is the
    # shared `/ai/*` renderer, and the day those fields carry a real place name is the day
    # the escaping matters — so the check follows the code rather than being dropped.
    assert "function aiLine(item)" in app_js
    for rendered in ("esc(String(title))", "esc(extra)", "esc(going)"):
        assert rendered in app_js, f"aiLine renders {rendered} unescaped"


def test_the_pwa_builds_no_link_target_out_of_response_data():
    """`esc()` stops an attribute breaking out; it does nothing about `javascript:` in an
    href, because the scheme survives escaping intact. The defence is that no href, src or
    action is built from server data — the one exception is an <img src>, where a script
    URL does not execute. If this fails, the new sink needs a scheme allow-list, not esc()."""
    import pathlib
    import re
    app_js = (pathlib.Path(__file__).resolve().parent.parent
              / "surfaces" / "app" / "www" / "app.js").read_text(encoding="utf-8")
    unguarded = re.findall(r'(?:href|action|formaction)\s*=\s*.\$\{(?!safeUrl\()([^}]*)\}',
                           app_js)
    assert unguarded == [], f"a URL attribute skips safeUrl(): {unguarded}"


def test_safe_url_passes_links_through_and_defuses_script_urls():
    """This guard caught two real `<a href="${res.checkout_url}">` sinks the moment they
    arrived from `main`, which is the whole reason it exists. Both were hardcoded payment
    URLs, so neither was exploitable — but they were one endpoint change away from being an
    open redirect and one `javascript:` away from running as the signed-in user.

    The logic is asserted here rather than only in JS, because nothing else in CI runs the
    PWA. Kept deliberately in step with `safeUrl` in app.js."""
    from urllib.parse import urlparse

    def safe_url(raw):
        try:
            parsed = urlparse(str(raw or "").strip())
        except ValueError:
            return "#"
        return raw if parsed.scheme in ("http", "https") else "#"

    for good in ("https://checkout.stripe.com/c/pay/x", "http://example.com/a?b=c"):
        assert safe_url(good) == good
    for bad in ("javascript:alert(1)", "JaVaScRiPt:alert(1)", "data:text/html,<script>",
                "vbscript:msgbox", "", "   ", None):
        assert safe_url(bad) == "#", bad


# ---- endpoints that had never worked ------------------------------------------

@pytest.fixture
def two_graphs(cfg):
    """Ana and Mallory as separate owner slices on one database."""
    from gateway import accounts
    from substrate.graph import Graph
    from substrate.migrate import migrate
    from substrate.bus import Bus
    from substrate import load_config
    import substrate

    base = TestClient(create_app(cfg))          # builds and migrates the db
    root = base.app.state.graph
    made = {}
    for name in ("ana", "mallory"):
        account = accounts.register(root, name, PW)
        made[name] = Graph(root.conn, root.bus, default_owner=account["owner_id"])
    return made


def test_the_topology_hubs_are_the_callers_own(two_graphs):
    """`find_topology_hubs` read `SELECT src, dst FROM edges` with no join to entities, then
    resolved every node's name — on a shared box that is every other user's people, goals
    and memories by name.

    It was unreachable, because the endpoint called `export_graph_topology`, which does not
    exist, so it 500'd on every call. That is the trap: the obvious fix is to correct the
    function name, and correcting the function name alone is what would have shipped the
    leak."""
    from substrate import topology

    ana, mallory = two_graphs["ana"], two_graphs["mallory"]
    session = ana.session("t", {"people:write", "events:write", "people:read"})
    person = session.create_entity("person", {"name": "Rui-THERAPIST"}, source="t")
    event = session.create_entity("event", {"title": "Thursday session"}, source="t")
    session.create_edge(person, event, "attended", source="t")

    mine = topology.find_topology_hubs(ana)
    assert {hub["name"] for hub in mine} == {"Rui-THERAPIST", "Thursday session"}
    assert topology.find_topology_hubs(mallory) == [], "another owner's graph is not yours"


def test_the_csv_export_is_owner_scoped_and_actually_works(cfg):
    """`Graph.all_entities()` does not exist, so this 500'd every time — and the PWA has a
    live Export CSV button wired to it."""
    client = TestClient(create_app(cfg))
    heads = {}
    for name in ("ana", "mallory"):
        client.post("/v1/auth/register", json={"handle": name, "password": PW})
        token = client.post("/v1/auth/login",
                            json={"handle": name, "password": PW}).json()["token"]
        heads[name] = {"Authorization": f"Bearer {token}"}

    client.post("/v1/people", headers=heads["ana"], json={"name": "Rui-THERAPIST"})

    mine = client.get("/v1/graph/export/csv", headers=heads["ana"])
    assert mine.status_code == 200 and "Rui-THERAPIST" in mine.text
    theirs = client.get("/v1/graph/export/csv", headers=heads["mallory"])
    assert theirs.status_code == 200 and "Rui-THERAPIST" not in theirs.text


@pytest.mark.parametrize("payload", ['=HYPERLINK("http://evil.example","x")',
                                     "+1+1", "-2+3", "@SUM(A1:A9)"])
def test_the_csv_export_cannot_carry_a_spreadsheet_formula(cfg, payload):
    """Names are user-typed and this endpoint returns a file people open in Excel. A cell
    starting `=`, `+`, `-` or `@` is a *formula* there, and `=HYPERLINK(...)` or a DDE
    payload runs on open — the export is the delivery mechanism."""
    client = TestClient(create_app(cfg))
    client.post("/v1/auth/register", json={"handle": "ana", "password": PW})
    token = client.post("/v1/auth/login",
                        json={"handle": "ana", "password": PW}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    client.post("/v1/people", headers=headers, json={"name": payload})

    import csv
    import io

    body = client.get("/v1/graph/export/csv", headers=headers).text
    rows = list(csv.reader(io.StringIO(body)))
    cells = [cell for row in rows for cell in row]

    # The text survives — defusing must not mean mangling somebody's data.
    assert any(payload in cell for cell in cells), "the user's own text is preserved"
    # ...but no cell is handed to the spreadsheet as a formula.
    assert not any(cell[:1] in ("=", "+", "-", "@") for cell in cells), \
        f"a live formula cell in {cells}"


def test_the_endpoints_that_called_functions_that_do_not_exist(cfg):
    """Four handlers named functions their module had never defined, so they returned a 500
    on every call. Found by sweeping all 425 endpoints as a signed-in user, not by a test —
    nothing in the suite touched them."""
    client = TestClient(create_app(cfg))
    client.post("/v1/auth/register", json={"handle": "ana", "password": PW})
    token = client.post("/v1/auth/login",
                        json={"handle": "ana", "password": PW}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    for path in ("/v1/graph/topology", "/v1/routines/mindfulness/summary",
                 "/v1/graph/export/csv", "/v1/people/qr"):
        assert client.get(path, headers=headers).status_code == 200, path


def test_the_vcard_carries_the_callers_own_handle(cfg):
    """It looked up entity kind `identity`, which is not in KINDS, so every call 400'd."""
    client = TestClient(create_app(cfg))
    client.post("/v1/auth/register", json={"handle": "ana", "password": PW})
    token = client.post("/v1/auth/login",
                        json={"handle": "ana", "password": PW}).json()["token"]
    card = client.get("/v1/people/qr",
                      headers={"Authorization": f"Bearer {token}"}).json()
    assert card["name"] == "ana" and "FN:ana" in card["vcard"]


# ---- CRITICAL: any user could destroy the whole instance ----------------------

@pytest.fixture
def pair(cfg):
    client = TestClient(create_app(cfg))
    heads = {}
    for name in ("ana", "mallory"):
        client.post("/v1/auth/register", json={"handle": name, "password": PW})
        token = client.post("/v1/auth/login",
                            json={"handle": name, "password": PW}).json()["token"]
        heads[name] = {"Authorization": f"Bearer {token}"}
    client.post("/v1/people", headers=heads["ana"], json={"name": "Rui-THERAPIST"})
    client.post("/v1/capture", headers=heads["ana"], json={"text": "Therapy notes"})
    return client, heads


def test_a_signed_in_stranger_cannot_wipe_the_instance(pair):
    """The worst finding of the fourth audit, demonstrated end to end before it was fixed.

    `POST /v1/graph/restore` is an ordinary authenticated endpoint with no operator gate,
    and `import_restore` ran `DELETE FROM edges; DELETE FROM observations; DELETE FROM
    entities` with **no owner predicate anywhere** before inserting `backup_data` — which,
    for a `{}` body, is nothing. One empty POST from any account destroyed every graph on
    the box. Accounts are entities too, so the victim could not even log in afterwards."""
    client, heads = pair
    before = client.get("/v1/graph", headers=heads["ana"]).json()["entities"]
    assert before > 0

    attack = client.post("/v1/graph/restore", headers=heads["mallory"], json={})
    assert attack.status_code == 400

    assert client.get("/v1/graph", headers=heads["ana"]).json()["entities"] == before
    assert client.post("/v1/auth/login",
                       json={"handle": "ana", "password": PW}).status_code == 200


def test_a_restore_that_puts_nothing_back_is_refused(pair):
    """Distinct from the wipe above: a well-formed body with an empty entity list is still
    a request to delete everything and restore nothing, which is never what anyone means."""
    client, heads = pair
    refused = client.post("/v1/graph/restore", headers=heads["ana"],
                          json={"entities": [], "edges": []})
    assert refused.status_code == 400
    assert client.get("/v1/graph", headers=heads["ana"]).json()["entities"] > 0


def test_a_backup_contains_only_your_own_graph(pair):
    """`export_backup` was the same hole pointed the other way — raw SQL over the whole
    entities table, so any login dumped every other user's people and memories."""
    client, heads = pair
    mine = client.post("/v1/graph/backup", headers=heads["ana"]).json()
    theirs = client.post("/v1/graph/backup", headers=heads["mallory"]).json()

    assert "Rui-THERAPIST" in repr(mine["entities"])
    assert theirs["entities"] == [] and theirs["edges"] == []


def test_a_backup_restores_your_graph_exactly(pair):
    """The feature has to still work, or the fix is just a removal."""
    client, heads = pair
    saved = client.post("/v1/graph/backup", headers=heads["ana"]).json()
    client.post("/v1/people", headers=heads["ana"], json={"name": "MISTAKE"})

    result = client.post("/v1/graph/restore", headers=heads["ana"], json=saved).json()
    assert result["restored"] is True and result["entities"] == len(saved["entities"])

    after = repr(client.post("/v1/graph/backup", headers=heads["ana"]).json())
    assert "Rui-THERAPIST" in after and "MISTAKE" not in after
    assert client.post("/v1/auth/login",
                       json={"handle": "ana", "password": PW}).status_code == 200


def test_a_crafted_backup_cannot_write_into_another_account(pair):
    """Every row in a backup carries an `owner_id`, and the file is attacker-controlled. It
    is ignored in favour of the caller's own — otherwise 'restore' is a write primitive
    aimed at any slice you can name."""
    client, heads = pair
    stolen = client.post("/v1/graph/backup", headers=heads["ana"]).json()
    for entity in stolen["entities"]:
        entity["attrs"] = {**entity["attrs"], "name": "PLANTED-BY-MALLORY"}

    assert client.post("/v1/graph/restore", headers=heads["mallory"],
                       json=stolen).status_code == 200

    ana_now = repr(client.post("/v1/graph/backup", headers=heads["ana"]).json())
    assert "PLANTED-BY-MALLORY" not in ana_now
    assert "Rui-THERAPIST" in ana_now, "Ana's own rows are untouched"


def test_a_restore_writes_provenance_like_every_other_write(pair):
    """It talked to the connection directly, so restored rows had no observation trail and
    skipped kind validation. Going through the session API is what makes those automatic."""
    client, heads = pair
    saved = client.post("/v1/graph/backup", headers=heads["ana"]).json()
    client.post("/v1/graph/restore", headers=heads["ana"], json=saved)

    exported = client.get("/v1/export", headers=heads["ana"]).json()
    owned = {entity["id"] for entity in exported["entities"]}
    assert exported["observations"], "a restore leaves a provenance trail"
    assert all(row["entity_id"] in owned for row in exported["observations"])


@pytest.mark.parametrize("body", [
    {"entities": [{"kind": "not_a_kind", "attrs": {}}], "edges": []},
    {"entities": [{"kind": "person", "attrs": "not a dict"}], "edges": []},
    {"entities": "nope", "edges": []},
    {"entities": [{"kind": "person", "attrs": {"name": "ok"}}], "edges": "nope"},
])
def test_a_malformed_backup_is_a_400_not_a_500(pair, body):
    client, heads = pair
    assert client.post("/v1/graph/restore", headers=heads["ana"],
                       json=body).status_code in (200, 400)
    assert client.post("/v1/auth/login",
                       json={"handle": "ana", "password": PW}).status_code == 200


# ---- the last third-party dependencies ----------------------------------------

def test_the_pwa_loads_no_script_from_a_cdn():
    """Leaflet came from unpkg with no Subresource Integrity hash, into the origin that
    holds the session token in localStorage — so whatever unpkg returned is what ran, with
    full access to every graph endpoint. It is vendored now, verified against the sha512
    npm publishes for 1.9.4 before being committed."""
    import re
    www = pathlib.Path(__file__).resolve().parent.parent / "surfaces" / "app" / "www"
    for path in list(www.glob("*.js")) + list(www.glob("*.html")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        remote = re.findall(r'(?:src|href)\s*=\s*["\']?(https?://[^"\'\s>]+)', text)
        assert remote == [], f"{path.name} loads {remote} from a third party"


def test_the_vendored_leaflet_is_actually_there():
    """A CSP of 'self' plus a missing file is a map that silently never loads."""
    vendor = (pathlib.Path(__file__).resolve().parent.parent
              / "surfaces" / "app" / "www" / "vendor")
    js, css = vendor / "leaflet.js", vendor / "leaflet.css"
    assert js.is_file() and css.is_file()
    assert js.stat().st_size > 100_000, "that is not the real leaflet.js"
    assert "leaflet" in css.read_text(encoding="utf-8", errors="ignore")[:400].lower()


def test_the_csp_names_no_external_host(cfg):
    csp = TestClient(create_app(cfg)).get("/health").headers["content-security-policy"]
    directives = dict(part.strip().split(" ", 1)
                      for part in csp.split(";") if " " in part.strip())
    assert directives["script-src"] == "'self' 'unsafe-inline'"
    assert "unpkg" not in csp and "cdn" not in csp


def test_the_contact_card_reaches_no_third_party(cfg):
    """`qr_url` embedded the vCard in an api.qrserver.com query string, so rendering your
    own contact card handed your name and the viewer's IP to a stranger — for a card the
    PWA never displays."""
    client = TestClient(create_app(cfg))
    client.post("/v1/auth/register", json={"handle": "ana", "password": PW})
    token = client.post("/v1/auth/login",
                        json={"handle": "ana", "password": PW}).json()["token"]
    card = client.get("/v1/people/qr",
                      headers={"Authorization": f"Bearer {token}"})
    assert card.status_code == 200
    assert "qrserver" not in card.text and "http://" not in card.text
    assert card.json()["vcard_data_uri"].startswith("data:text/vcard")


@pytest.mark.parametrize("handle,leaked", [
    ("ana\nTEL:+1999", "TEL:+1999"),
    ("ana;X-EVIL:1", "X-EVIL"),
])
def test_a_crafted_handle_cannot_inject_vcard_properties(handle, leaked):
    """Handles are unrestricted — `_norm_handle` lowercases and truncates, nothing more —
    and a newline in one adds a property to the card the recipient saves to their phone."""
    from gateway.modules_api import _vcard
    card = _vcard(handle)
    assert card.count("BEGIN:VCARD") == 1
    property_lines = [line.split(":")[0] for line in card.split("\r\n") if ":" in line]
    assert leaked.split(":")[0] not in property_lines


def test_logging_a_focus_session_works(cfg):
    """The ninth dead endpoint: `mindfulness.log_focus_session` had never existed. The
    empty-body sweep only saw a 422 here and stopped; it took sending a *valid* body to
    reach the 500 underneath."""
    client = TestClient(create_app(cfg))
    client.post("/v1/auth/register", json={"handle": "ana", "password": PW})
    token = client.post("/v1/auth/login",
                        json={"handle": "ana", "password": PW}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    logged = client.post("/v1/routines/mindfulness/session", headers=headers,
                         json={"duration_minutes": 30, "distraction_count": 2,
                               "note": "deep work"})
    assert logged.status_code == 200 and logged.json()["logged"] is True
    assert logged.json()["sessions"] == 1 and logged.json()["total_minutes"] == 30

    client.post("/v1/routines/mindfulness/session", headers=headers,
                json={"duration_minutes": 60, "distraction_count": 1})
    assert client.post("/v1/routines/mindfulness/session", headers=headers,
                       json={"duration_minutes": 15, "distraction_count": 0}
                       ).json()["total_minutes"] == 105


@pytest.mark.parametrize("bad", [{"duration_minutes": 0, "distraction_count": 0},
                                 {"duration_minutes": -5, "distraction_count": 0},
                                 {"duration_minutes": 99999, "distraction_count": 0},
                                 {"duration_minutes": 30, "distraction_count": -1}])
def test_a_nonsense_focus_session_is_a_400(cfg, bad):
    client = TestClient(create_app(cfg))
    client.post("/v1/auth/register", json={"handle": "ana", "password": PW})
    token = client.post("/v1/auth/login",
                        json={"handle": "ana", "password": PW}).json()["token"]
    assert client.post("/v1/routines/mindfulness/session",
                       headers={"Authorization": f"Bearer {token}"},
                       json=bad).status_code == 400
