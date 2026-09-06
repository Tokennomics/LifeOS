"""Check a deployed LifeOS the way a first user would, and say what actually happened.

    python3 tools/verify_deploy.py https://your-app.onrender.com --city Lisbon

**Why this exists.** Three of the things a new city depends on — geocoding, Overpass and
Open-Meteo — have never made a live call from any environment this app was built in. The
sandbox blocks outbound network, and CI blocks it deliberately (`tests/conftest.py` refuses
every provider fetch, so a green suite proves nothing about the internet). City autoseeding
runs on the arrival screen, which makes that path load-bearing *and* unverified.

So this is the check that closes the gap, and it is written to be run against a real box by
somebody who wants a straight answer rather than a reassuring one:

- **It reports what it observed**, not whether it approves. Each step prints the evidence.
- **It never says a step passed because it did not crash.** Seeding "working" means places
  came back, so it waits for them and reports the count.
- **A missing optional key is not a failure.** Ticketmaster unconfigured is a status, and
  it says so instead of failing the run.
- **It creates one throwaway account** and nothing else. Nothing is deleted; nothing is
  written outside that account except the city seed, which is the thing being tested.

Exit code is 0 when the arrival path works, 1 when it does not, so it can gate a deploy.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import quote

TIMEOUT = 30
SEED_WAIT_SECONDS = 90
POLL_EVERY = 6


class Result:
    def __init__(self):
        self.lines = []
        self.failed = []

    def ok(self, step, detail=""):
        self.lines.append(("ok", step, detail))
        print(f"  ok        {step}" + (f" — {detail}" if detail else ""))

    def note(self, step, detail=""):
        self.lines.append(("note", step, detail))
        print(f"  note      {step}" + (f" — {detail}" if detail else ""))

    def fail(self, step, detail=""):
        self.lines.append(("FAILED", step, detail))
        self.failed.append(step)
        print(f"  FAILED    {step}" + (f" — {detail}" if detail else ""))


def call(base, path, *, token="", body=None, method=""):
    """One request. Returns (status, parsed-or-text). Never raises for an HTTP error."""
    url = base.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data,
                                 method=method or ("POST" if data is not None else "GET"))
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            raw = res.read().decode("utf-8", "replace")
            try:
                return res.status, json.loads(raw)
            except ValueError:
                return res.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, raw
    except Exception as exc:                     # DNS, TLS, refused, timeout
        return 0, f"{type(exc).__name__}: {exc}"


def verify(base, city, keep=False):
    out = Result()
    print(f"\nChecking {base}  (city: {city})\n")

    # 1. Is anything there at all.
    status, body = call(base, "/health")
    if status != 200:
        out.fail("the box answers", f"GET /health returned {status or 'no connection'}: "
                                    f"{str(body)[:120]}")
        return out
    out.ok("the box answers", "/health is 200")

    # 2. HTTPS is not optional: a session token is a bearer token.
    if base.startswith("https://"):
        out.ok("served over TLS")
    elif any(h in base for h in ("127.0.0.1", "localhost", "[::1]")):
        # TLS matters because of the path between a user and the server. Loopback has no
        # path, so this is worth saying and not worth failing over.
        out.note("served over TLS", "loopback, so nothing is on the wire — but a real "
                                    "deployment must be HTTPS")
    else:
        out.fail("served over TLS",
                 "this is plain HTTP — a session token is a bearer token, so anyone on the "
                 "path can take it. Do not put real users on this.")

    # 3. An account, which is what a first user does.
    handle = f"verify{int(time.time())}"
    status, body = call(base, "/v1/auth/register",
                        body={"handle": handle, "password": "verify-deploy-throwaway-pw"})
    if status != 200:
        out.fail("registering an account", f"{status}: {str(body)[:160]}")
        return out
    status, body = call(base, "/v1/auth/login",
                        body={"handle": handle, "password": "verify-deploy-throwaway-pw"})
    token = (body or {}).get("token", "") if isinstance(body, dict) else ""
    if not token:
        out.fail("signing in", f"{status}: {str(body)[:160]}")
        return out
    out.ok("registering and signing in", f"as {handle}")

    # 4. What the operator's own status page says about this box.
    status, body = call(base, "/v1/os/master-controller", token=token, body={})
    if status == 200 and isinstance(body, dict):
        on = [c["name"] for c in body.get("capabilities", []) if c.get("available")]
        off = [f"{c['name']} (needs {c.get('needs')})"
               for c in body.get("capabilities", []) if not c.get("available")]
        out.ok("capabilities configured", f"{len(on)} of {body.get('of', '?')}: "
                                          f"{', '.join(on) or 'none'}")
        if off:
            out.note("not configured", "; ".join(off))
    else:
        out.fail("reading the status page", f"{status}: {str(body)[:160]}")

    # 5. The arrival. This is the step everything else is scaffolding for, and it is a GET
    # with the city in the query string — the same request the app makes on its own screen.
    status, body = call(base, f"/v1/city/arrival?city={quote(city)}", token=token)
    if status not in (200, 201):
        out.fail("arriving in a city", f"{status}: {str(body)[:200]}")
        return out
    already = (body or {}).get("place_count", 0) if isinstance(body, dict) else 0
    out.ok("arriving in a city",
           f"accepted; {already} places already known" if already
           else "accepted; nothing here yet, so seeding should start behind the response")

    # 6. Wait for the seed. "It did not crash" is not the same as "it worked".
    print(f"\n  waiting up to {SEED_WAIT_SECONDS}s for the seed to run…")
    places, deadline, last = 0, time.time() + SEED_WAIT_SECONDS, None
    while time.time() < deadline:
        time.sleep(POLL_EVERY)
        status, body = call(base, f"/v1/city/places?city={quote(city)}", token=token)
        if status == 200 and isinstance(body, dict):
            places = body.get("count") or len(body.get("places") or [])
            last = body
            if places:
                break
    if places:
        cats = sorted({p.get("category", "") for p in (last.get("places") or [])
                       if p.get("category")})
        out.ok("places seeded from OpenStreetMap",
               f"{places} places" + (f", categories: {', '.join(cats)}" if cats else ""))
    else:
        out.fail("places seeded from OpenStreetMap",
                 "nothing came back. Check `GET /v1/seeding/queue` — it names the reason "
                 "per city rather than leaving it to guesswork. A blocked egress or a "
                 "geocoder that cannot place the city are the two usual causes.")

    # 7. Weather, which is the other keyless provider.
    status, body = call(base, f"/v1/weather/radar?city={quote(city)}", token=token)
    if status == 200 and isinstance(body, dict) and body.get("available"):
        triggers = [t.get("kind") or t.get("what") for t in (body.get("triggers") or [])]
        out.ok("conditions from Open-Meteo",
               "available" + (f", triggers: {', '.join(str(t) for t in triggers)}"
                              if triggers else ""))
    else:
        detail = (body or {}).get("status", "") if isinstance(body, dict) else str(body)[:120]
        out.fail("conditions from Open-Meteo", f"not available: {detail or status}")

    # 8. The seeding queue, whatever happened above — it is the operator's view.
    status, body = call(base, "/v1/seeding/queue", token=token)
    if status == 200 and isinstance(body, dict):
        for item in (body.get("queue") or [])[:5]:
            line = f"{item.get('city')}: {item.get('state')}"
            if item.get("detail"):
                line += f" ({item['detail']})"
            out.note("seed queue", line)

    if not keep:
        print(f"\n  the throwaway account {handle} is left in place — delete it from the "
              f"admin surface if you want it gone.")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("base_url", help="https://your-app.onrender.com")
    ap.add_argument("--city", default="Lisbon", help="a real city to arrive in")
    ap.add_argument("--keep", action="store_true", help="do not mention cleanup")
    args = ap.parse_args()

    out = verify(args.base_url, args.city, keep=args.keep)

    print("\n" + "-" * 62)
    if out.failed:
        print(f"{len(out.failed)} step(s) did not do what they claim:")
        for step in out.failed:
            print(f"  · {step}")
        print("\nThe app is up but the first-arrival path is not working. Until places and "
              "conditions come back, a new city is an empty screen.")
        return 1
    print("The arrival path works: a new city gets places and conditions on its own.")
    print("This is the one thing that could not be tested anywhere but a deployed box.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
