"""Hit every endpoint as a signed-in user. Report 5xx (broken) and anything that leaks."""
import os, sys, tempfile, json, collections
sys.path.insert(0, "/home/user/LifeOS")
os.environ["LIFEOS_RATE_LIMIT_DISABLED"] = "1"
os.environ["LIFEOS_SIGNING_KEY"] = "x" * 40

from fastapi.testclient import TestClient
from gateway.main import create_app

tmp = tempfile.mkdtemp()
cfg = {"env": "sqlite", "sqlite": {"path": f"{tmp}/t.db"},
       "owner": {"id": "b0b00000-0000-4000-8000-000000000001", "name": "Bob"},
       "gateway": {"auth_token": ""}}
app = create_app(cfg)
c = TestClient(app, raise_server_exceptions=False)

c.post("/v1/auth/register", json={"handle": "ana", "password": "correct-horse-battery"})
tok = c.post("/v1/auth/login", json={"handle": "ana", "password": "correct-horse-battery"}).json()["token"]
H = {"Authorization": f"Bearer {tok}"}

spec = c.get("/openapi.json", headers=H).json()
results = collections.defaultdict(list)
tested = 0
for path, methods in spec["paths"].items():
    if "{" in path:
        continue
    for method in methods:
        if method not in ("get", "post"):
            continue
        # don't destroy our own session mid-sweep
        if any(k in path for k in ("logout", "erase", "/auth/email", "/password/reset")):
            continue
        tested += 1
        try:
            r = c.request(method.upper(), path, headers=H,
                          json={} if method == "post" else None)
        except Exception as e:
            results["EXCEPTION"].append((method, path, repr(e)[:120]))
            continue
        if r.status_code >= 500:
            results["5xx"].append((method, path, r.text[:160]))
        elif r.status_code == 422:
            results["422 (needs a body)"].append((method, path, ""))
        elif r.status_code >= 400:
            results["4xx"].append((method, path, r.text[:100]))

print(f"tested {tested} endpoints\n")
for bucket in ("EXCEPTION", "5xx", "4xx", "422 (needs a body)"):
    items = results[bucket]
    print(f"--- {bucket}: {len(items)}")
    if bucket in ("EXCEPTION", "5xx", "4xx"):
        for m, p, body in items[:40]:
            print(f"   {m.upper():5} {p}  {body}")
