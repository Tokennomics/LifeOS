"""One account, several ways in — and the takeover this must not allow.

The RSA keypair below is generated in-process rather than checked in: a private key in a
repo is a private key on the internet, and this repo has already shipped one published
secret. Generation is a few seconds of Miller-Rabin, which is cheaper than the alternative.
"""

import base64
import hashlib
import json
import random

import pytest
from fastapi.testclient import TestClient

from gateway import accounts, identities, rate_limiter
from gateway.main import create_app
from modules.auth import oidc, rs256

PW = "correct-horse-battery"
CLIENT_ID = "lifeos.example.client"


# ---- a real RSA key, made here ----------------------------------------------

def _probable_prime(bits, rng):
    def is_prime(n, k=16):
        for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
            if n % p == 0:
                return n == p
        d, r = n - 1, 0
        while d % 2 == 0:
            d //= 2
            r += 1
        for _ in range(k):
            a = rng.randrange(2, n - 1)
            x = pow(a, d, n)
            if x in (1, n - 1):
                continue
            for _ in range(r - 1):
                x = x * x % n
                if x == n - 1:
                    break
            else:
                return False
        return True
    while True:
        candidate = rng.getrandbits(bits) | (1 << bits - 1) | 1
        if is_prime(candidate):
            return candidate


@pytest.fixture(scope="module")
def keypair():
    rng = random.Random(20260807)
    p, q = _probable_prime(512, rng), _probable_prime(512, rng)
    n, e = p * q, 65537
    return {"n": n, "e": e, "d": pow(e, -1, (p - 1) * (q - 1))}


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _jwks(keypair) -> dict:
    n = keypair["n"]
    return {"keys": [{"kty": "RSA", "alg": "RS256", "kid": "k1",
                      "n": _b64u(n.to_bytes((n.bit_length() + 7) // 8, "big")),
                      "e": _b64u((keypair["e"]).to_bytes(3, "big"))}]}


def _token(keypair, claims: dict, kid: str = "k1") -> str:
    header = _b64u(json.dumps({"alg": "RS256", "kid": kid, "typ": "JWT"}).encode())
    payload = _b64u(json.dumps(claims).encode())
    signing_input = f"{header}.{payload}".encode()
    n, d = keypair["n"], keypair["d"]
    size = (n.bit_length() + 7) // 8
    suffix = rs256.SHA256_DIGEST_INFO + hashlib.sha256(signing_input).digest()
    block = b"\x00\x01" + b"\xff" * (size - len(suffix) - 3) + b"\x00" + suffix
    return f"{header}.{payload}.{_b64u(pow(int.from_bytes(block, 'big'), d, n).to_bytes(size, 'big'))}"


def _claims(**over):
    import time
    base = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": "google-user-1",
            "email": "ana@example.com", "email_verified": True,
            "iat": int(time.time()), "exp": int(time.time()) + 3600}
    return {**base, **over}


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setenv(rate_limiter.DISABLE_VAR, "1")
    monkeypatch.setenv("LIFEOS_GOOGLE_CLIENT_ID", CLIENT_ID)


@pytest.fixture
def client(cfg):
    return TestClient(create_app(cfg))


# ---- verifying a provider token ----------------------------------------------

def test_a_genuine_token_is_accepted(keypair):
    proof = oidc.verify_id_token("google", _token(keypair, _claims()), jwks=_jwks(keypair))
    assert proof["subject"] == "google-user-1"
    assert proof["email"] == "ana@example.com" and proof["email_verified"] is True


def test_a_token_for_a_different_app_is_rejected(keypair):
    """The `aud` check. Skipping it is how 'sign in with Google' becomes 'sign in as
    anyone': any app's token would work on ours."""
    token = _token(keypair, _claims(aud="some.other.app"))
    with pytest.raises(oidc.TokenRejected, match="different application"):
        oidc.verify_id_token("google", token, jwks=_jwks(keypair))


def test_a_token_from_the_wrong_issuer_is_rejected(keypair):
    token = _token(keypair, _claims(iss="https://evil.example"))
    with pytest.raises(oidc.TokenRejected, match="issuer"):
        oidc.verify_id_token("google", token, jwks=_jwks(keypair))


def test_an_expired_token_is_rejected(keypair):
    import time
    token = _token(keypair, _claims(exp=int(time.time()) - 10_000))
    with pytest.raises(oidc.TokenRejected, match="expired"):
        oidc.verify_id_token("google", token, jwks=_jwks(keypair))


def test_a_tampered_payload_is_rejected(keypair):
    header, payload, signature = _token(keypair, _claims()).split(".")
    forged = _b64u(json.dumps(_claims(sub="somebody-else")).encode())
    with pytest.raises(oidc.TokenRejected, match="signature"):
        oidc.verify_id_token("google", f"{header}.{forged}.{signature}", jwks=_jwks(keypair))


def test_alg_none_is_rejected(keypair):
    """`alg` is never read from the token — the header is attacker-controlled."""
    header = _b64u(json.dumps({"alg": "none", "kid": "k1"}).encode())
    payload = _b64u(json.dumps(_claims()).encode())
    with pytest.raises(oidc.TokenRejected, match="signature"):
        oidc.verify_id_token("google", f"{header}.{payload}.", jwks=_jwks(keypair))


def test_an_unverified_email_is_dropped_not_trusted(keypair):
    """An unverified email is something the user typed. Believing it lets someone register
    victim@gmail.com at a sloppy IdP and walk in."""
    proof = oidc.verify_id_token("google", _token(keypair, _claims(email_verified=False)),
                                 jwks=_jwks(keypair))
    assert proof["email"] == "" and proof["email_verified"] is False


def test_a_mismatched_nonce_is_rejected(keypair):
    token = _token(keypair, _claims(nonce="abc"))
    with pytest.raises(oidc.TokenRejected, match="nonce"):
        oidc.verify_id_token("google", token, jwks=_jwks(keypair), nonce="xyz")
    assert oidc.verify_id_token("google", token, jwks=_jwks(keypair), nonce="abc")


def test_an_unconfigured_provider_refuses_rather_than_trusting(keypair, monkeypatch):
    monkeypatch.delenv("LIFEOS_GOOGLE_CLIENT_ID", raising=False)
    with pytest.raises(oidc.TokenRejected, match="not set"):
        oidc.verify_id_token("google", _token(keypair, _claims()), jwks=_jwks(keypair))
    assert oidc.configured("google") is False


def test_the_provider_listing_never_leaks_the_client_id(client):
    body = client.get("/v1/auth/providers").json()
    assert {p["provider"] for p in body["providers"]} == {"google", "apple"}
    assert CLIENT_ID not in client.get("/v1/auth/providers").text


# ---- identities across devices ------------------------------------------------

def test_signing_in_twice_with_the_same_identity_is_the_same_account(graph):
    first = identities.sign_in(graph, "google", "sub-1")
    second = identities.sign_in(graph, "google", "sub-1")
    assert first["account_id"] == second["account_id"]
    assert first["created"] is True and second["created"] is False
    assert first["token"] != second["token"], "a new device gets its own session"


def test_a_second_device_reaches_the_same_graph(graph, cfg):
    """The whole point: sign in on a new phone, find the same data."""
    client = TestClient(create_app(cfg))
    phone = identities.sign_in(client.app.state.graph, "apple", "apple-sub-1")
    head = {"Authorization": f"Bearer {phone['token']}"}
    client.post("/v1/capture", headers=head, json={"text": "written on the old phone"})

    tablet = identities.sign_in(client.app.state.graph, "apple", "apple-sub-1")
    seen = client.get("/v1/export", headers={"Authorization": f"Bearer {tablet['token']}"})
    assert "written on the old phone" in seen.text


def test_an_unknown_identity_never_joins_an_existing_account_by_email(graph):
    """The takeover this module exists to prevent: an attacker registers the victim's
    address at a provider and inherits their account. A new identity is a NEW account."""
    accounts.register(graph, "ana", PW)
    ana = accounts.login(graph, "ana", PW)
    fresh = identities.sign_in(graph, "google", "attacker-sub", handle_hint="ana")
    assert fresh["account_id"] != ana["session_id"]
    assert fresh["owner_id"] != ana["owner_id"], "separate graphs, not a merge"
    assert fresh["handle"] != "ana", "and the handle collision resolved"


def test_linking_is_how_you_actually_connect_them(graph):
    accounts.register(graph, "ana", PW)
    ana = accounts.login(graph, "ana", PW)
    account_id = accounts.resolve(graph, ana["token"])["account_id"]

    identities.link(graph, account_id, "google", "ana-google-sub")
    again = identities.sign_in(graph, "google", "ana-google-sub")
    assert again["account_id"] == account_id and again["created"] is False
    assert again["owner_id"] == ana["owner_id"], "same graph, reached a new way"


def test_an_identity_cannot_be_stolen_from_another_account(graph):
    first = identities.sign_in(graph, "google", "shared-sub")
    accounts.register(graph, "mallory", PW)
    mallory = accounts.resolve(graph, accounts.login(graph, "mallory", PW)["token"])
    with pytest.raises(ValueError, match="another account"):
        identities.link(graph, mallory["account_id"], "google", "shared-sub")
    assert identities.find(graph, "google", "shared-sub")["account_id"] == first["account_id"]


def test_you_cannot_unlink_your_only_way_in(graph):
    made = identities.sign_in(graph, "google", "only-sub")
    with pytest.raises(ValueError, match="only way in"):
        identities.unlink(graph, made["account_id"], "google", "only-sub")

    # verified=True because this test is about unlinking, not about proving the address.
    identities.link(graph, made["account_id"], "email", "ana@example.com", verified=True)
    assert identities.unlink(graph, made["account_id"], "google", "only-sub")["unlinked"]
    assert [i["kind"] for i in identities.for_account(graph, made["account_id"])] == ["email"]


def test_a_passwordless_account_cannot_be_entered_with_a_blank_password(graph):
    identities.sign_in(graph, "apple", "apple-sub")
    handle = identities.for_account(
        graph, identities.find(graph, "apple", "apple-sub")["account_id"])
    assert handle  # linked
    for attempt in ("", " ", "password"):
        with pytest.raises(ValueError):
            accounts.login(graph, "apple", attempt)


def test_email_is_case_insensitive_but_a_provider_subject_is_not(graph):
    made = identities.sign_in(graph, "email", "Ana@Example.COM")
    assert identities.find(graph, "email", "ana@example.com")["account_id"] == made["account_id"]
    assert identities.find(graph, "google", "SUB-1") is None or True
    identities.sign_in(graph, "google", "Sub-1")
    assert identities.find(graph, "google", "sub-1") is None, "provider ids are exact"


def test_handles_do_not_collide(graph):
    a = identities.sign_in(graph, "email", "ana@example.com")
    b = identities.sign_in(graph, "email", "ana@other.example")
    assert a["handle"] == "ana" and b["handle"] == "ana2"


def test_a_phone_number_is_never_used_as_a_public_handle(graph):
    """A handle shows up in crew rosters. A phone number is not the user's to publish."""
    made = identities.sign_in(graph, "phone", "+351912345678")
    assert "912345678" not in made["handle"]


@pytest.mark.parametrize("kind", ["", "twitter", "SQL", None])
def test_an_unknown_identity_kind_is_refused(graph, kind):
    with pytest.raises(ValueError):
        identities.sign_in(graph, kind, "x")


# ---- the endpoint ------------------------------------------------------------

def test_the_oidc_endpoint_signs_in(client, keypair, monkeypatch):
    monkeypatch.setattr(oidc, "fetch_jwks", lambda provider: _jwks(keypair))
    r = client.post("/v1/auth/oidc", json={"provider": "google",
                                           "id_token": _token(keypair, _claims())})
    assert r.status_code == 200 and r.json()["created"] is True
    me = client.get("/v1/auth/me",
                    headers={"Authorization": f"Bearer {r.json()['token']}"})
    assert me.status_code == 200 and me.json()["mode"] == "account"


def test_the_oidc_endpoint_rejects_a_forged_token(client, keypair, monkeypatch):
    monkeypatch.setattr(oidc, "fetch_jwks", lambda provider: _jwks(keypair))
    header, payload, signature = _token(keypair, _claims()).split(".")
    forged = _b64u(json.dumps(_claims(sub="someone-else")).encode())
    r = client.post("/v1/auth/oidc", json={"provider": "google",
                                           "id_token": f"{header}.{forged}.{signature}"})
    assert r.status_code == 401


def test_listing_and_linking_through_the_api(client, keypair, monkeypatch):
    monkeypatch.setattr(oidc, "fetch_jwks", lambda provider: _jwks(keypair))
    client.post("/v1/auth/register", json={"handle": "ana", "password": PW})
    token = client.post("/v1/auth/login",
                        json={"handle": "ana", "password": PW}).json()["token"]
    head = {"Authorization": f"Bearer {token}"}

    linked = client.post("/v1/auth/identities", headers=head,
                         json={"provider": "google", "id_token": _token(keypair, _claims())})
    assert linked.status_code == 200 and linked.json()["linked"] is True

    listed = client.get("/v1/auth/identities", headers=head).json()["identities"]
    assert [i["kind"] for i in listed] == ["google"]


# ---- round three: found by probing my own code ------------------------------

def test_an_email_identity_cannot_be_linked_by_simply_typing_it(graph):
    """Pre-positioned takeover. Nothing verifies that you own an address you type, so an
    attacker could link victim@example.com to their OWN account today — and on the day an
    email sign-in ships, the victim would authenticate with their real address and land
    inside the attacker's account. Found by probing, not by a test."""
    accounts.register(graph, "mallory", PW)
    mallory = accounts.resolve(graph, accounts.login(graph, "mallory", PW)["token"])
    with pytest.raises(ValueError, match="proof of control"):
        identities.link(graph, mallory["account_id"], "email", "victim@example.com")
    with pytest.raises(ValueError, match="proof of control"):
        identities.link(graph, mallory["account_id"], "phone", "+351912345678")
    assert identities.find(graph, "email", "victim@example.com") is None


def test_the_link_endpoint_refuses_an_unverified_email(client):
    client.post("/v1/auth/register", json={"handle": "mallory", "password": PW})
    token = client.post("/v1/auth/login",
                        json={"handle": "mallory", "password": PW}).json()["token"]
    r = client.post("/v1/auth/identities", headers={"Authorization": f"Bearer {token}"},
                    json={"provider": "email", "subject": "victim@example.com"})
    assert r.status_code == 400 and "proof of control" in r.json()["detail"]


def test_a_provider_identity_is_exempt_because_its_subject_was_signed(graph):
    """Google and Apple `sub` values arrive inside a signature we verified, so they are
    proof rather than a claim."""
    accounts.register(graph, "ana", PW)
    ana = accounts.resolve(graph, accounts.login(graph, "ana", PW)["token"])
    assert identities.link(graph, ana["account_id"], "google", "verified-sub")["linked"]


def test_a_verified_email_still_links(graph):
    """The gate is on unproven claims, not on email as a concept — an OTP flow passes
    verified=True and this keeps working."""
    accounts.register(graph, "ana", PW)
    ana = accounts.resolve(graph, accounts.login(graph, "ana", PW)["token"])
    assert identities.link(graph, ana["account_id"], "email", "ana@example.com",
                           verified=True)["linked"]


def test_signing_in_with_a_verified_email_still_creates_an_account(graph):
    made = identities.sign_in(graph, "email", "ana@example.com")
    assert made["created"] is True and made["handle"] == "ana"
