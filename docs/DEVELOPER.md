# Building against LifeOS

Three things exist: **API keys**, **webhooks**, and a **plugin registry**. This page says what
each does and — just as important — what it does not, because the versions that shipped
before 2026-08-14 claimed all three and implemented none of them.

## API keys

```sh
curl -X POST https://<host>/v1/developer/keys \
  -H "Authorization: Bearer $YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "nightly export", "scopes": ["read"]}'
```

```json
{
  "key_id": "…",
  "name": "nightly export",
  "secret": "los_sk_…",
  "shown": "los_sk_abcde",
  "store_it_now": "This is the only time the key is shown…"
}
```

**The secret appears once.** Only a SHA-256 hash is stored, so a leaked database does not
leak working keys, and "show me my key again" is answered with "issue a new one".

Use it exactly like a session token:

```sh
curl https://<host>/v1/weekend -H "Authorization: Bearer los_sk_…"
```

A key **acts as the account that issued it and never as more**. Every ownership check
downstream treats a key-authenticated request as that account, so a key cannot reach
anything its issuer could not.

`GET /v1/developer/keys` lists them without secrets. `DELETE /v1/developer/keys/{key_id}`
revokes one, and revocation takes effect on the very next request. Twenty-five live keys per
account.

*Previously: this endpoint returned `los_sk_<uuid4>` and stored nothing. The key was
well-formed, looked exactly like a credential, and opened nothing.*

## Webhooks

```sh
curl -X POST https://<host>/v1/developers/webhooks \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"target_url": "https://you.example/hook",
       "events": ["meetup.created", "checkin.created"]}'
```

Events this app actually emits — an unknown one is refused at subscribe time rather than
accepted and never fired:

`meetup.created` · `meetup.joined` · `checkin.created` · `kudos.sent` · `review.written` ·
`signal.opened` · `walk.started`

### Verifying a delivery

Every request carries two headers:

```
X-LifeOS-Timestamp: 1755140000
X-LifeOS-Signature: sha256=<hex>
```

The signature is HMAC-SHA256 over **`<timestamp>.<raw body>`** with your signing secret.
The timestamp is inside the signed payload deliberately — signing the body alone lets a
captured delivery be replayed a week later.

```python
import hashlib, hmac

def verify(secret, body, timestamp, header):
    expected = "sha256=" + hmac.new(
        secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)
```

Reject anything with a timestamp more than a few minutes old.

### What delivery does not do

**At-most-once, synchronous, no retries.** There is no background worker in this app, so a
delivery is attempted at the moment the event happens and a failure is recorded rather than
queued. `GET /v1/developers/webhooks/deliveries` shows what actually happened, which is the
screen you want when nothing is arriving.

Build for that: treat a missed delivery as normal and reconcile by polling, rather than
assuming a retry queue that does not exist.

Targets must be public addresses. Private and link-local ranges are refused at subscribe
time and re-checked at delivery, because a webhook is a URL you choose and *we* fetch —
without that check, `http://169.254.169.254/…` would be a credential theft wearing the
costume of an ordinary integration.

## Plugins

`POST /v1/developer/plugins/register` validates a manifest and stores the registration.
Re-registering the same name updates it, so shipping a version is not a duplicate.

```json
{"name": "Wind Radar", "version": "1.0.0",
 "scopes": ["events:read", "content:write"],
 "description": "Tells you when it is windy."}
```

`POST /v1/developers/plugin-sandbox` reports, in plain words, what a plugin is asking for:

```json
{"permissions": [{"scope": "events:read",
                  "means": "read your calendar and the events you are going to",
                  "known": true}],
 "unrecognised_scopes": [],
 "executed": false, "simulated": false, "published": false}
```

**Nothing is executed.** Running third-party code inside the process that holds every user's
graph is not something to approximate, and a sandbox that is only *called* a sandbox is the
most dangerous possible version of this. Knowing what a plugin wants before installing it is
most of the value and none of the risk.

There is no store, no revenue share and no ratings. Ratings need users.

*Previously: the plugin list returned four plugins with developers and ratings out of five,
none of which existed; registration returned success and stored nothing; the sandbox reported
`PASSED (100% telemetry accuracy)` and `PUBLISHED_TO_COMMUNITY_STORE` for any id.*

## Rate limits

Per-route, applied to a key exactly as to a session — there is no separate developer tier.
Key issuance is capped at 10/hour per account. The "10,000 req / minute" the old response
advertised was enforced by nothing.
