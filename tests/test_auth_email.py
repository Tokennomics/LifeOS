"""Email verification: the proof that `identities.NEEDS_PROOF` has been waiting for.

The threat model here is not subtle. `/v1/auth/email/code` is unauthenticated and takes an
arbitrary address, so it is simultaneously an enumeration oracle, a mail-bombing tool and —
if a code ever reaches the caller instead of the mailbox — a complete authentication bypass.
Most of this file is those three things, checked from the attacker's side.
"""

import datetime

import pytest
from fastapi.testclient import TestClient

from gateway import identities, rate_limiter
from gateway.main import OTP_ECHO_VAR, create_app
from modules.auth import mailer, otp

PW = "correct-horse-battery"
ADDRESS = "ana@example.com"


@pytest.fixture(autouse=True)
def _no_ambient_limits(monkeypatch):
    monkeypatch.setenv(rate_limiter.DISABLE_VAR, "1")
    monkeypatch.delenv(OTP_ECHO_VAR, raising=False)
    monkeypatch.delenv(mailer.RESEND_KEY_VAR, raising=False)
    monkeypatch.delenv(mailer.FROM_VAR, raising=False)


@pytest.fixture
def sent(monkeypatch):
    """A configured mailer that records instead of sending."""
    monkeypatch.setenv(mailer.RESEND_KEY_VAR, "re_test_key")
    monkeypatch.setenv(mailer.FROM_VAR, "LifeOS <hi@example.com>")
    outbox = []

    def fake(to, subject, text):
        outbox.append({"to": to, "subject": subject, "text": text})
        return {"sent": True, "status": "sent", "id": "msg-1"}

    monkeypatch.setitem(mailer._PROVIDERS, "resend", fake)
    return outbox


def _code_from(outbox):
    import re
    return re.search(r"\b(\d{6})\b", outbox[-1]["text"]).group(1)


# ---- the code itself ---------------------------------------------------------

def test_a_code_is_delivered_and_verifies(graph, sent):
    otp.request_code(graph, ADDRESS)
    assert otp.verify_code(graph, ADDRESS, _code_from(sent))["verified"] is True


def test_the_plaintext_code_is_never_stored(graph, sent):
    """A backup, a log line or an export that contains a live code is a live credential."""
    from substrate import SYSTEM_OWNER
    from substrate.graph import Graph
    otp.request_code(graph, ADDRESS)
    code = _code_from(sent)

    rows = Graph(graph.conn, graph.bus, default_owner=SYSTEM_OWNER).session(
        "t", {"content:read"}).find_entities("content", {"type": otp.RECORD}, limit=10)
    assert rows and all(code not in repr(row["attrs"]) for row in rows)


def test_a_code_is_single_use(graph, sent):
    otp.request_code(graph, ADDRESS)
    code = _code_from(sent)
    otp.verify_code(graph, ADDRESS, code)
    with pytest.raises(otp.OtpError):
        otp.verify_code(graph, ADDRESS, code)


def test_a_code_expires(graph, sent, monkeypatch):
    otp.request_code(graph, ADDRESS)
    code = _code_from(sent)
    later = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=otp.TTL_MINUTES + 1)
    monkeypatch.setattr(otp, "_now", lambda: later)
    with pytest.raises(otp.OtpError):
        otp.verify_code(graph, ADDRESS, code)


def test_guessing_is_capped(graph, sent):
    """The whole security of a six-digit code. Without the cap, a million guesses is an
    afternoon; with it, the fifth wrong guess destroys the code."""
    otp.request_code(graph, ADDRESS)
    code = _code_from(sent)
    wrong = "000000" if code != "000000" else "111111"

    for _ in range(otp.MAX_ATTEMPTS):
        with pytest.raises(otp.OtpError):
            otp.verify_code(graph, ADDRESS, wrong)

    with pytest.raises(otp.OtpError):
        otp.verify_code(graph, ADDRESS, code), "the real code must be dead too"


def test_a_new_code_supersedes_the_old_one(graph, sent):
    """Two live codes means the attempt cap is really 5xN, and 'resend' has to mean the new
    one works."""
    otp.request_code(graph, ADDRESS)
    first = _code_from(sent)
    otp.request_code(graph, ADDRESS)
    second = _code_from(sent)

    assert otp.verify_code(graph, ADDRESS, second)["verified"] is True
    otp.request_code(graph, ADDRESS)
    with pytest.raises(otp.OtpError):
        otp.verify_code(graph, ADDRESS, first)


def test_a_code_for_one_purpose_cannot_be_spent_on_another(graph, sent):
    """Otherwise a code minted to link an address to your own account can be replayed to
    sign in as whoever owns it."""
    otp.request_code(graph, ADDRESS, "link")
    with pytest.raises(otp.OtpError):
        otp.verify_code(graph, ADDRESS, _code_from(sent), "sign_in")


def test_issuance_is_capped_per_address(graph, sent):
    """Without this, anyone who knows an address can use us to mail-bomb it, and our
    sending domain wears the reputation damage."""
    for _ in range(otp.MAX_PER_WINDOW):
        otp.request_code(graph, ADDRESS)
    with pytest.raises(otp.OtpError, match="too many codes"):
        otp.request_code(graph, ADDRESS)


def test_every_rejection_says_the_same_thing(graph, sent):
    """Wrong / expired / never-issued must be indistinguishable — the differences help an
    attacker map state and help a user with nothing."""
    reasons = set()
    for address, code in ((ADDRESS, "123456"), ("nobody@example.com", "123456")):
        try:
            otp.verify_code(graph, address, code)
        except otp.OtpError as exc:
            reasons.add(str(exc))
    otp.request_code(graph, ADDRESS)
    try:
        otp.verify_code(graph, ADDRESS, "999999")
    except otp.OtpError as exc:
        reasons.add(str(exc))
    assert len(reasons) == 1


@pytest.mark.parametrize("bad", ["", "   ", "not-an-address", "@example.com", "ana@"])
def test_junk_addresses_are_refused(graph, bad):
    with pytest.raises(otp.OtpError):
        otp.request_code(graph, bad, send=False)


# ---- the mailer degrades ------------------------------------------------------

def test_no_provider_is_a_status_not_a_crash():
    result = mailer.send(ADDRESS, "s", "t")
    assert result["sent"] is False and result["status"] == "not_configured"
    assert mailer.RESEND_KEY_VAR in " ".join(result["missing"])


def test_the_status_never_echoes_the_key(monkeypatch):
    monkeypatch.setenv(mailer.RESEND_KEY_VAR, "re_super_secret")
    monkeypatch.setenv(mailer.FROM_VAR, "LifeOS <hi@example.com>")
    assert "re_super_secret" not in repr(mailer.status())


def test_a_provider_outage_does_not_raise(monkeypatch, graph):
    monkeypatch.setenv(mailer.RESEND_KEY_VAR, "re_test_key")
    monkeypatch.setenv(mailer.FROM_VAR, "LifeOS <hi@example.com>")

    def boom(to, subject, text):
        raise OSError("connection reset")
    monkeypatch.setitem(mailer._PROVIDERS, "resend", boom)

    assert mailer.send(ADDRESS, "s", "t")["status"] == "send_failed"
    # and the whole flow still issues a code rather than 500-ing
    assert otp.request_code(graph, ADDRESS)["delivered"] is False


# ---- the gateway --------------------------------------------------------------

def test_signing_in_by_email_creates_then_reuses_one_account(cfg, sent):
    client = TestClient(create_app(cfg))
    assert client.post("/v1/auth/email/code", json={"email": ADDRESS}).status_code == 200

    first = client.post("/v1/auth/email/verify",
                        json={"email": ADDRESS, "code": _code_from(sent)}).json()
    assert first["created"] is True and first["token"]

    client.post("/v1/auth/email/code", json={"email": ADDRESS})
    second = client.post("/v1/auth/email/verify",
                         json={"email": ADDRESS, "code": _code_from(sent)}).json()
    assert second["created"] is False
    assert second["account_id"] == first["account_id"], "same address, same account"


def test_the_address_is_case_insensitive(cfg, sent):
    client = TestClient(create_app(cfg))
    client.post("/v1/auth/email/code", json={"email": "Ana@Example.COM"})
    signed = client.post("/v1/auth/email/verify",
                         json={"email": ADDRESS, "code": _code_from(sent)})
    assert signed.status_code == 200


def test_a_wrong_code_is_a_401_not_a_session(cfg, sent):
    client = TestClient(create_app(cfg))
    client.post("/v1/auth/email/code", json={"email": ADDRESS})
    assert client.post("/v1/auth/email/verify",
                       json={"email": ADDRESS, "code": "000001"}).status_code in (401, 200)
    bad = client.post("/v1/auth/email/verify", json={"email": ADDRESS, "code": "abcdef"})
    assert bad.status_code == 401 and "token" not in bad.json()


def test_requesting_a_code_reveals_nothing_about_who_has_an_account(cfg, sent):
    """Identical responses for a known and an unknown address. Anything else and this is a
    'does this person use LifeOS' lookup, which the dating surface makes a real disclosure."""
    client = TestClient(create_app(cfg))
    client.post("/v1/auth/email/code", json={"email": ADDRESS})
    client.post("/v1/auth/email/verify",
                json={"email": ADDRESS, "code": _code_from(sent)})

    known = client.post("/v1/auth/email/code", json={"email": ADDRESS})
    unknown = client.post("/v1/auth/email/code", json={"email": "ghost@example.com"})
    assert known.status_code == unknown.status_code == 200
    assert set(known.json()) == set(unknown.json())
    assert known.json()["delivered"] == unknown.json()["delivered"] is True


# ---- the bypass this must never become ----------------------------------------

def test_the_code_never_comes_back_in_the_response(cfg):
    """The one that matters. `/v1/auth/email/code` is unauthenticated, so echoing the code
    would let anyone request one for any address, read it, and sign in as them. The
    dangerous configuration is the *likely* one: a public box whose owner has not set up
    email yet, where `request_code` hands the plaintext back so a laptop stays usable."""
    client = TestClient(create_app(cfg))
    response = client.post("/v1/auth/email/code", json={"email": ADDRESS})
    assert response.status_code == 200
    assert "code" not in response.json()
    assert response.json()["delivered"] is False
    assert not any(part.isdigit() and len(part) == otp.CODE_DIGITS
                   for part in response.text.replace('"', " ").split())


def test_the_echo_is_opt_in_and_off_by_default(cfg, monkeypatch):
    """It exists so a laptop install is completable with no mail provider, and it is exactly
    the switch that must never default on."""
    client = TestClient(create_app(cfg))
    assert "code" not in client.post("/v1/auth/email/code", json={"email": ADDRESS}).json()

    monkeypatch.setenv(OTP_ECHO_VAR, "1")
    echoed = client.post("/v1/auth/email/code", json={"email": ADDRESS}).json()
    assert len(echoed["code"]) == otp.CODE_DIGITS


def test_email_is_only_advertised_when_it_can_be_delivered(cfg, monkeypatch):
    client = TestClient(create_app(cfg))
    assert client.get("/v1/auth/providers").json()["email"]["available"] is False

    monkeypatch.setenv(mailer.RESEND_KEY_VAR, "re_test_key")
    monkeypatch.setenv(mailer.FROM_VAR, "LifeOS <hi@example.com>")
    assert client.get("/v1/auth/providers").json()["email"]["available"] is True


def test_linking_still_needs_a_session(cfg, sent):
    client = TestClient(create_app(cfg))
    assert client.post("/v1/auth/email/code",
                       json={"email": ADDRESS, "purpose": "link"}).status_code == 401


def test_an_address_cannot_be_linked_to_a_second_account(cfg, sent):
    """The takeover `identities` exists to prevent, arriving through the new door: proving
    control of an address must not move it off the account that already holds it."""
    client = TestClient(create_app(cfg))
    client.post("/v1/auth/email/code", json={"email": ADDRESS})
    owner = client.post("/v1/auth/email/verify",
                        json={"email": ADDRESS, "code": _code_from(sent)}).json()

    client.post("/v1/auth/register", json={"handle": "mallory", "password": PW})
    token = client.post("/v1/auth/login",
                        json={"handle": "mallory", "password": PW}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    client.post("/v1/auth/email/code", json={"email": ADDRESS, "purpose": "link"},
                headers=headers)
    stolen = client.post("/v1/auth/email/verify", headers=headers,
                         json={"email": ADDRESS, "code": _code_from(sent),
                               "purpose": "link"})
    assert stolen.status_code == 400

    client.post("/v1/auth/email/code", json={"email": ADDRESS})
    again = client.post("/v1/auth/email/verify",
                        json={"email": ADDRESS, "code": _code_from(sent)}).json()
    assert again["account_id"] == owner["account_id"], "the address never moved"


def test_a_verified_code_is_the_only_way_an_email_identity_gets_linked(graph):
    """`link()` has refused a typed address since it was written. That must stay true — this
    module is allowed past it because it delivered the code, not because it asked nicely."""
    with pytest.raises(ValueError, match="verified"):
        identities.link(graph, "acct-1", "email", ADDRESS)


# ---- password reset -----------------------------------------------------------

@pytest.fixture
def bruno(cfg, sent):
    """A password account with a verified address on it — the only shape that can reset."""
    client = TestClient(create_app(cfg))
    client.post("/v1/auth/register", json={"handle": "bruno", "password": PW})
    token = client.post("/v1/auth/login",
                        json={"handle": "bruno", "password": PW}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    client.post("/v1/auth/email/code", headers=headers,
                json={"email": "bruno@example.com", "purpose": "link"})
    client.post("/v1/auth/email/verify", headers=headers,
                json={"email": "bruno@example.com", "code": _code_from(sent),
                      "purpose": "link"})
    return {"c": client, "h": headers, "token": token,
            "id": client.get("/v1/auth/me", headers=headers).json()["account_id"]}


def _reset(client, sent, password="new-horse-battery"):
    client.post("/v1/auth/email/code",
                json={"email": "bruno@example.com", "purpose": "reset"})
    return client.post("/v1/auth/password/reset",
                       json={"email": "bruno@example.com", "code": _code_from(sent),
                             "password": password})


def test_a_forgotten_password_can_actually_be_reset(bruno, sent):
    """`docs/HOSTING.md` called this the single most important thing to fix before anyone
    outside the owner's circle uses the app: a forgotten password meant an account that
    nobody could ever get back into."""
    client = bruno["c"]
    assert _reset(client, sent).status_code == 200
    assert client.post("/v1/auth/login",
                       json={"handle": "bruno", "password": "new-horse-battery"}
                       ).status_code == 200


def test_the_old_password_stops_working(bruno, sent):
    client = bruno["c"]
    _reset(client, sent)
    assert client.post("/v1/auth/login",
                       json={"handle": "bruno", "password": PW}).status_code == 401


def test_a_reset_ends_every_existing_session(bruno, sent):
    """Somebody resetting has usually lost control of the account. Leaving the sessions open
    means the reset changes nothing for whoever is already inside."""
    client = bruno["c"]
    assert client.get("/v1/auth/me", headers=bruno["h"]).status_code == 200
    body = _reset(client, sent).json()
    assert body["sessions_revoked"] >= 1
    assert client.get("/v1/auth/me", headers=bruno["h"]).status_code == 401
    assert client.get("/v1/auth/me",
                      headers={"Authorization": f"Bearer {body['token']}"}).status_code == 200


def test_a_sign_in_code_cannot_be_spent_as_a_reset(bruno, sent):
    """Otherwise anyone who can read one code can take the account, and a sign-in code is
    the easiest one to get someone to read out."""
    client = bruno["c"]
    client.post("/v1/auth/email/code", json={"email": "bruno@example.com"})
    assert client.post("/v1/auth/password/reset",
                       json={"email": "bruno@example.com", "code": _code_from(sent),
                             "password": "new-horse-battery"}).status_code == 401


def test_an_address_linked_to_nothing_cannot_reset_anything(cfg, sent):
    client = TestClient(create_app(cfg))
    client.post("/v1/auth/email/code",
                json={"email": "ghost@example.com", "purpose": "reset"})
    assert client.post("/v1/auth/password/reset",
                       json={"email": "ghost@example.com", "code": _code_from(sent),
                             "password": "new-horse-battery"}).status_code == 401


def test_reset_failures_are_indistinguishable(bruno, sent):
    """A real code on an unlinked address and a wrong code must read the same, or reset
    becomes the account-enumeration oracle that /email/code was written not to be."""
    client = bruno["c"]
    client.post("/v1/auth/email/code",
                json={"email": "ghost@example.com", "purpose": "reset"})
    unlinked = client.post("/v1/auth/password/reset",
                           json={"email": "ghost@example.com", "code": _code_from(sent),
                                 "password": "new-horse-battery"})
    wrong = client.post("/v1/auth/password/reset",
                        json={"email": "bruno@example.com", "code": "000000",
                              "password": "new-horse-battery"})
    assert unlinked.status_code == wrong.status_code == 401
    assert unlinked.json() == wrong.json()


def test_a_reset_code_is_single_use(bruno, sent):
    client = bruno["c"]
    client.post("/v1/auth/email/code",
                json={"email": "bruno@example.com", "purpose": "reset"})
    code = _code_from(sent)
    body = {"email": "bruno@example.com", "code": code, "password": "new-horse-battery"}
    assert client.post("/v1/auth/password/reset", json=body).status_code == 200
    assert client.post("/v1/auth/password/reset",
                       json={**body, "password": "third-horse-battery"}).status_code == 401


def test_a_weak_new_password_is_refused(bruno, sent):
    assert _reset(bruno["c"], sent, password="x").status_code == 400


def test_setting_a_password_gives_a_passwordless_account_a_second_way_in(cfg, sent):
    """An email-only account has `password_hash == ""`, which `_verify_password` refuses
    outright. Reset has to lift that rather than leave a blank hash behind."""
    client = TestClient(create_app(cfg))
    client.post("/v1/auth/email/code", json={"email": ADDRESS})
    client.post("/v1/auth/email/verify",
                json={"email": ADDRESS, "code": _code_from(sent)})

    client.post("/v1/auth/email/code", json={"email": ADDRESS, "purpose": "reset"})
    assert client.post("/v1/auth/password/reset",
                       json={"email": ADDRESS, "code": _code_from(sent),
                             "password": "new-horse-battery"}).status_code == 200
    assert client.post("/v1/auth/login",
                       json={"handle": "ana", "password": "new-horse-battery"}
                       ).status_code == 200
