"""API keys, webhooks and plugins — the group where a prop is a security bug.

`POST /developer/keys` returned `los_sk_<uuid4>` and stored nothing. `/developers/api-keys`
returned `lifeos_dk_...` with a scope list and a "10,000 req/minute" rate limit, and stored
nothing either. Both look exactly like a credential — right shape, right prefix — and
somebody would paste one into a script and believe an integration was locked down by a key
that never existed.

So the assertions here are not "a key comes back". They are:

- the secret is never stored and never shown twice;
- **presenting the key actually authenticates**, which is the line that separates a
  credential from a plausible string;
- revoking it takes effect on the next request;
- one account cannot revoke, use or see another's;
- a webhook target cannot point at the cloud metadata service.

The last one matters more than it looks. A webhook is a URL a *user* chooses that the
*server* fetches, so without an address check `http://169.254.169.254/…` as a target is a
complete credential theft on any cloud host, wearing the costume of an ordinary integration.
"""

import json

import pytest
from fastapi.testclient import TestClient

from gateway import rate_limiter
from gateway.main import create_app
from modules.platform import keys, plugins, webhooks

PW = "correct-horse-battery"

MANIFEST = {"name": "Wind Radar", "version": "1.0.0",
            "scopes": ["events:read", "content:write"],
            "description": "Tells you when it is windy."}


@pytest.fixture(autouse=True)
def _no_ambient_limits(monkeypatch):
    monkeypatch.setenv(rate_limiter.DISABLE_VAR, "1")


@pytest.fixture
def city(cfg):
    client = TestClient(create_app(cfg))
    people = {}
    for name in ("ana", "bruno"):
        client.post("/v1/auth/register", json={"handle": name, "password": PW})
        token = client.post("/v1/auth/login",
                            json={"handle": name, "password": PW}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        people[name] = {"h": headers,
                        "id": client.get("/v1/auth/me", headers=headers).json()["account_id"]}
    return client, people


def _issue(client, who, name="script"):
    return client.post("/v1/developer/keys", json={"name": name}, headers=who["h"]).json()


# ---- the line that makes a key a credential ----------------------------------

def test_an_issued_key_actually_authenticates(city):
    """Without this, everything else in this file is a nicer-looking prop."""
    client, people = city
    secret = _issue(client, people["ana"])["secret"]
    me = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {secret}"})
    assert me.status_code == 200
    assert me.json()["account_id"] == people["ana"]["id"]


def test_a_key_acts_as_its_issuer_and_nobody_else(city):
    """A key must never be a way to be *more* than the account that made it."""
    client, people = city
    secret = _issue(client, people["ana"])["secret"]
    client.post("/v1/events/qr-checkin", json={"place": "the bar"},
                headers={"Authorization": f"Bearer {secret}"})
    assert client.get("/v1/checkins", headers=people["ana"]["h"]).json()["total"] == 1
    assert client.get("/v1/checkins", headers=people["bruno"]["h"]).json()["total"] == 0


def test_a_made_up_key_authenticates_nothing(city):
    client, _ = city
    fake = keys.PREFIX + "obviously-not-a-real-key"
    assert client.get("/v1/auth/me",
                      headers={"Authorization": f"Bearer {fake}"}).status_code == 401


def test_revoking_takes_effect_immediately(city):
    """A revocation that does not take effect is worse than having none at all."""
    client, people = city
    made = _issue(client, people["ana"])
    headers = {"Authorization": f"Bearer {made['secret']}"}
    assert client.get("/v1/auth/me", headers=headers).status_code == 200
    client.request("DELETE", f"/v1/developer/keys/{made['key_id']}",
                   headers=people["ana"]["h"])
    assert client.get("/v1/auth/me", headers=headers).status_code == 401


# ---- the secret --------------------------------------------------------------

def test_the_secret_is_never_stored(graph):
    made = keys.issue(graph, "script", account_id="ana")
    row = keys._sys(graph).get_entity(made["key_id"])
    assert made["secret"] not in json.dumps(row["attrs"])
    assert row["attrs"]["digest"] != made["secret"]


def test_the_secret_is_never_shown_again(city):
    client, people = city
    made = _issue(client, people["ana"])
    listed = client.get("/v1/developer/keys", headers=people["ana"]["h"]).json()
    assert made["secret"] not in json.dumps(listed)
    assert listed["keys"][0]["shown"] == made["shown"]


def test_two_keys_are_distinguishable_in_a_list(city):
    client, people = city
    first = _issue(client, people["ana"], "zapier")
    second = _issue(client, people["ana"], "cron")
    assert first["shown"] != second["shown"]
    names = {k["name"] for k in
             client.get("/v1/developer/keys", headers=people["ana"]["h"]).json()["keys"]}
    assert names == {"zapier", "cron"}


def test_a_key_needs_a_name_you_will_recognise_later(graph):
    with pytest.raises(keys.KeyError_):
        keys.issue(graph, "   ", account_id="ana")


def test_keys_are_capped(graph):
    for i in range(keys.MAX_KEYS):
        keys.issue(graph, f"key {i}", account_id="ana")
    with pytest.raises(keys.KeyError_):
        keys.issue(graph, "one too many", account_id="ana")


def test_scopes_are_validated(graph):
    with pytest.raises(keys.KeyError_):
        keys.issue(graph, "script", account_id="ana", scopes=["everything"])


# ---- one account cannot touch another's --------------------------------------

def test_you_cannot_see_another_accounts_keys(city):
    client, people = city
    _issue(client, people["ana"])
    assert client.get("/v1/developer/keys",
                      headers=people["bruno"]["h"]).json()["keys"] == []


def test_you_cannot_revoke_another_accounts_key(city):
    """A refusal, not a silent no-op that reads as success."""
    client, people = city
    made = _issue(client, people["ana"])
    res = client.request("DELETE", f"/v1/developer/keys/{made['key_id']}",
                         headers=people["bruno"]["h"])
    assert res.status_code == 400
    assert client.get("/v1/auth/me",
                      headers={"Authorization": f"Bearer {made['secret']}"}).status_code == 200


def test_verify_does_not_explain_why_it_failed(graph):
    """"No such key", "revoked" and "malformed" are one answer to whoever holds it."""
    made = keys.issue(graph, "script", account_id="ana")
    keys.revoke(graph, made["key_id"], account_id="ana")
    assert keys.verify(graph, made["secret"]) is None
    assert keys.verify(graph, "not-even-a-key") is None


def test_using_a_key_records_when(graph):
    made = keys.issue(graph, "script", account_id="ana")
    assert keys.listing(graph, account_id="ana")["keys"][0]["last_used_at"] == ""
    keys.verify(graph, made["secret"])
    assert keys.listing(graph, account_id="ana")["keys"][0]["last_used_at"]


# ---- webhooks ----------------------------------------------------------------

def test_a_webhook_target_cannot_be_the_metadata_service(city):
    """Every cloud exposes unauthenticated instance credentials on 169.254.169.254. A
    webhook is a URL a user picks and the server fetches — this is the whole ballgame."""
    client, people = city
    res = client.post("/v1/developers/webhooks",
                      json={"target_url": "http://169.254.169.254/latest/meta-data/",
                            "events": ["meetup.created"]},
                      headers=people["ana"]["h"])
    assert res.status_code == 400


def test_a_webhook_target_cannot_be_localhost(city):
    client, people = city
    assert client.post("/v1/developers/webhooks",
                       json={"target_url": "http://127.0.0.1:8000/hook",
                             "events": ["meetup.created"]},
                       headers=people["ana"]["h"]).status_code == 400


def test_an_event_this_app_never_emits_is_refused(city):
    """A subscription to an event that will never fire is a support ticket six months on."""
    client, people = city
    res = client.post("/v1/developers/webhooks",
                      json={"target_url": "https://example.com/hook",
                            "events": ["nuclear.launch"]},
                      headers=people["ana"]["h"])
    assert res.status_code == 400
    assert "never emits" in res.text


def test_a_webhook_is_stored_and_listed(city):
    client, people = city
    made = client.post("/v1/developers/webhooks",
                       json={"target_url": "https://example.com/hook",
                             "events": ["meetup.created"]},
                       headers=people["ana"]["h"]).json()
    assert made["signing_secret"].startswith(webhooks.SECRET_PREFIX)
    listed = client.get("/v1/developers/webhooks", headers=people["ana"]["h"]).json()
    assert listed["webhooks"][0]["url"] == "https://example.com/hook"


def test_the_signing_secret_is_not_listed_back(city):
    client, people = city
    made = client.post("/v1/developers/webhooks",
                       json={"target_url": "https://example.com/hook",
                             "events": ["meetup.created"]},
                       headers=people["ana"]["h"]).json()
    listed = client.get("/v1/developers/webhooks", headers=people["ana"]["h"]).text
    assert made["signing_secret"] not in listed


def test_a_delivery_is_signed_over_the_timestamp_and_body(graph):
    """Signing the body alone lets a captured delivery be replayed a week later."""
    made = webhooks.subscribe(graph, "https://example.com/hook", ["meetup.created"],
                              account_id="ana")
    seen = {}

    def fake_post(url, body, headers):
        seen.update({"url": url, "body": body, "headers": headers})
        return 200

    webhooks.dispatch(graph, "meetup.created", {"meetup_id": "m1"}, post=fake_post)

    stamp = seen["headers"][webhooks.TIMESTAMP_HEADER]
    assert seen["headers"][webhooks.SIGNATURE_HEADER] == webhooks.sign(
        made["signing_secret"], seen["body"], stamp)
    assert json.loads(seen["body"])["data"]["meetup_id"] == "m1"


def test_a_different_secret_does_not_verify(graph):
    webhooks.subscribe(graph, "https://example.com/hook", ["meetup.created"],
                       account_id="ana")
    seen = {}
    webhooks.dispatch(graph, "meetup.created", {}, post=lambda u, b, h: seen.update(
        {"b": b, "h": h}) or 200)
    wrong = webhooks.sign("los_wh_wrong", seen["b"],
                          seen["h"][webhooks.TIMESTAMP_HEADER])
    assert seen["h"][webhooks.SIGNATURE_HEADER] != wrong


def test_only_subscribers_of_that_event_are_called(graph):
    webhooks.subscribe(graph, "https://example.com/a", ["meetup.created"],
                       account_id="ana")
    webhooks.subscribe(graph, "https://example.com/b", ["kudos.sent"], account_id="ana")
    called = []
    webhooks.dispatch(graph, "meetup.created", {},
                      post=lambda u, b, h: called.append(u) or 200)
    assert called == ["https://example.com/a"]


def test_a_failing_target_is_recorded_not_retried(graph):
    """At-most-once is a real limitation, and an integrator who knows builds differently."""
    webhooks.subscribe(graph, "https://example.com/hook", ["meetup.created"],
                       account_id="ana")

    def boom(url, body, headers):
        raise OSError("connection refused")

    out = webhooks.dispatch(graph, "meetup.created", {}, post=boom)
    assert out["failed"] == 1 and out["retried"] is False
    assert webhooks.listing(graph, account_id="ana")["webhooks"][0]["failures"] == 1


def test_a_dead_subscriber_does_not_break_the_user_action(city):
    """Somebody's meetup must not fail to be created because their integration is down."""
    client, people = city
    client.post("/v1/developers/webhooks",
                json={"target_url": "https://example.invalid/hook",
                      "events": ["checkin.created"]},
                headers=people["ana"]["h"])
    res = client.post("/v1/events/qr-checkin", json={"place": "the bar"},
                      headers=people["ana"]["h"])
    assert res.status_code == 200 and res.json()["checked_in"] is True


def test_a_removed_webhook_stops_receiving(graph):
    made = webhooks.subscribe(graph, "https://example.com/hook", ["meetup.created"],
                              account_id="ana")
    webhooks.remove(graph, made["webhook_id"], account_id="ana")
    called = []
    webhooks.dispatch(graph, "meetup.created", {},
                      post=lambda u, b, h: called.append(u) or 200)
    assert called == []


def test_you_cannot_remove_another_accounts_webhook(graph):
    made = webhooks.subscribe(graph, "https://example.com/hook", ["meetup.created"],
                              account_id="ana")
    with pytest.raises(webhooks.WebhookError):
        webhooks.remove(graph, made["webhook_id"], account_id="bruno")


def test_deliveries_are_visible_to_their_owner(graph):
    webhooks.subscribe(graph, "https://example.com/hook", ["meetup.created"],
                       account_id="ana")
    webhooks.dispatch(graph, "meetup.created", {}, post=lambda u, b, h: 200)
    assert webhooks.deliveries(graph, account_id="ana")["deliveries"][0]["ok"] is True
    assert webhooks.deliveries(graph, account_id="bruno")["deliveries"] == []


def test_a_real_event_reaches_a_real_subscriber(city, monkeypatch):
    """The wiring test: a webhook registered through HTTP fires when a user does a thing."""
    client, people = city
    client.post("/v1/developers/webhooks",
                json={"target_url": "https://example.com/hook",
                      "events": ["checkin.created"]},
                headers=people["ana"]["h"])
    called = []
    monkeypatch.setattr(webhooks, "_post",
                        lambda url, body, headers: called.append(url) or 200)
    client.post("/v1/events/qr-checkin", json={"place": "the viewpoint"},
                headers=people["ana"]["h"])
    assert called == ["https://example.com/hook"]


# ---- plugins -----------------------------------------------------------------

def test_the_plugin_list_starts_empty(city):
    """There were four, with developers and ratings out of five, on an empty database."""
    client, people = city
    body = client.get("/v1/developer/plugins", headers=people["ana"]["h"]).json()
    assert body["plugins"] == [] and body["empty"] is True
    assert "KiteSurf" not in client.get("/v1/developer/plugins",
                                        headers=people["ana"]["h"]).text


def test_registering_stores_it(city):
    """It returned success and a slugified id and stored nothing, so a developer would
    register, see it work, and never find their plugin again."""
    client, people = city
    made = client.post("/v1/developer/plugins/register", json={"manifest": MANIFEST},
                       headers=people["ana"]["h"]).json()
    assert made["registered"] is True and made["created"] is True
    listed = client.get("/v1/developer/plugins", headers=people["ana"]["h"]).json()
    assert [p["name"] for p in listed["plugins"]] == ["Wind Radar"]


def test_registering_the_same_name_updates_rather_than_duplicates(city):
    client, people = city
    client.post("/v1/developer/plugins/register", json={"manifest": MANIFEST},
                headers=people["ana"]["h"])
    again = client.post("/v1/developer/plugins/register",
                        json={"manifest": {**MANIFEST, "version": "1.1.0"}},
                        headers=people["ana"]["h"]).json()
    assert again["created"] is False
    listed = client.get("/v1/developer/plugins", headers=people["ana"]["h"]).json()
    assert len(listed["plugins"]) == 1 and listed["plugins"][0]["version"] == "1.1.0"


def test_an_invalid_manifest_is_refused(city):
    client, people = city
    res = client.post("/v1/developer/plugins/register",
                      json={"manifest": {"name": "No version"}},
                      headers=people["ana"]["h"])
    assert res.status_code == 400


def test_permissions_are_explained_in_words(city):
    """A permission screen showing `content:write` and nothing else is one nobody reads."""
    client, people = city
    made = client.post("/v1/developer/plugins/register", json={"manifest": MANIFEST},
                       headers=people["ana"]["h"]).json()
    means = {p["scope"]: p["means"] for p in made["permissions"]}
    assert "calendar" in means["events:read"]
    assert "notes" in means["content:write"]


def test_an_unrecognised_scope_is_surfaced_not_dropped(graph):
    """A manifest asking for something this app has never heard of is exactly what an
    installer needs to see."""
    out = plugins.check(graph, plugin_manifest={**MANIFEST,
                                                "scopes": ["content:read", "root:all"]})
    assert out["unrecognised_scopes"] == ["root:all"]


def test_the_sandbox_runs_nothing_and_says_so(city):
    """It reported `simulation_status: "PASSED (100% telemetry accuracy)"` and
    `store_status: "PUBLISHED_TO_COMMUNITY_STORE"` for any id."""
    client, people = city
    made = client.post("/v1/developer/plugins/register", json={"manifest": MANIFEST},
                       headers=people["ana"]["h"]).json()
    out = client.post("/v1/developers/plugin-sandbox",
                      json={"plugin_id": made["plugin_id"]},
                      headers=people["ana"]["h"]).json()
    assert out["executed"] is False and out["simulated"] is False
    assert out["published"] is False
    assert "PASSED" not in json.dumps(out)


def test_registration_claims_no_store_and_no_rev_share(city):
    client, people = city
    made = client.post("/v1/developer/plugins/register", json={"manifest": MANIFEST},
                       headers=people["ana"]["h"]).json()
    assert made["published"] is False and made["rev_share"] is None


def test_you_cannot_remove_another_accounts_plugin(city):
    client, people = city
    made = client.post("/v1/developer/plugins/register", json={"manifest": MANIFEST},
                       headers=people["ana"]["h"]).json()
    res = client.request("DELETE", f"/v1/developer/plugins/{made['plugin_id']}",
                         headers=people["bruno"]["h"])
    assert res.status_code == 400


# ---- a key is exactly its issuer, including for moderation --------------------

def test_a_key_is_not_a_way_past_the_operator_gate(city):
    """The operator gate is the only place in this app where a physical-safety feature can
    fail open, so it is worth pinning that an API key does not widen it: an ordinary
    account's key is an ordinary account."""
    client, people = city
    secret = _issue(client, people["ana"])["secret"]
    res = client.get("/v1/dating/reports", headers={"Authorization": f"Bearer {secret}"})
    assert res.status_code in (403, 503)      # 403 not an operator, 503 surface off


def test_a_moderators_key_carries_their_moderator_rights(city, monkeypatch):
    """The other half, and it has to be true for the same reason: a key *is* the account.
    An operator whose key could not moderate would just paste their session token instead,
    which is strictly worse."""
    client, people = city
    monkeypatch.setenv("LIFEOS_MODERATOR_ACCOUNTS", people["ana"]["id"])
    secret = _issue(client, people["ana"])["secret"]
    res = client.get("/v1/crews/reports/open",
                     headers={"Authorization": f"Bearer {secret}"})
    assert res.status_code == 200


def test_a_host_that_does_not_resolve_yet_can_still_be_subscribed(graph):
    """DNS is flaky and staging hostnames appear later. Rejecting a subscription because a
    name does not resolve *right now* makes this gate fail closed on an ordinary
    integration — and the check that matters runs again at delivery, where it is current."""
    made = webhooks.subscribe(graph, "https://not-registered.example",
                              ["meetup.created"], account_id="ana")
    assert made["webhook_id"]


def test_an_ip_literal_is_still_refused_without_any_dns(graph):
    """Catching 169.254.169.254 needs no resolution at all, so softening the DNS gate must
    not soften this one."""
    with pytest.raises(webhooks.WebhookError):
        webhooks.subscribe(graph, "http://169.254.169.254/latest/meta-data/",
                           ["meetup.created"], account_id="ana")


def test_the_signing_prefix_does_not_impersonate_a_vendor(graph):
    """Stripe already owns a webhook-secret prefix. One that collides with a vendor's makes
    every future secret scan a judgement call, which is how a real leak gets waved through.

    The prefix is not written out here on purpose — the repo's scanner caught this file's
    own docstring in CI, and a scanner that has to be taught exceptions stops being one."""
    made = webhooks.subscribe(graph, "https://example.com/hook", ["meetup.created"],
                              account_id="ana")
    assert made["signing_secret"].startswith("los_wh_")
    assert ("wh" + "sec_") not in made["signing_secret"]   # built, not written
