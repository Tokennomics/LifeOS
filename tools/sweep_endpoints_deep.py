"""Sweep the endpoints that need a body, synthesising a valid one from the OpenAPI schema."""
import os, sys, tempfile, collections
sys.path.insert(0, "/home/user/LifeOS")
os.environ["LIFEOS_RATE_LIMIT_DISABLED"] = "1"
os.environ["LIFEOS_SIGNING_KEY"] = "s" * 40

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
schemas = spec.get("components", {}).get("schemas", {})


def sample(schema, depth=0):
    """A plausible value for one JSON schema node."""
    if depth > 4 or not isinstance(schema, dict):
        return "x"
    if "$ref" in schema:
        return sample(schemas.get(schema["$ref"].split("/")[-1], {}), depth + 1)
    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema:
            opts = [s for s in schema[key] if s.get("type") != "null"] or schema[key]
            return sample(opts[0], depth + 1)
    if "default" in schema and schema["default"] is not None:
        return schema["default"]
    if "enum" in schema:
        return schema["enum"][0]
    t = schema.get("type")
    if t == "integer":
        return 1
    if t == "number":
        return 1.0
    if t == "boolean":
        return True
    if t == "array":
        return [sample(schema.get("items", {}), depth + 1)]
    if t == "object" or "properties" in schema:
        props = schema.get("properties") or {}
        return {k: sample(v, depth + 1) for k, v in props.items()}
    fmt = schema.get("format", "")
    if fmt == "date-time":
        return "2026-09-01T20:00:00+00:00"
    return "x"


def body_for(op):
    rb = op.get("requestBody")
    if not rb:
        return None
    js = rb.get("content", {}).get("application/json", {}).get("schema")
    if not js:
        return None
    made = sample(js)
    return made if isinstance(made, dict) else {}


results = collections.defaultdict(list)
tested = 0
SKIP = ("logout", "erase", "/auth/email", "/password/reset", "/graph/restore",
        "/auth/register", "/auth/login")

for path, methods in spec["paths"].items():
    if "{" in path:
        continue
    for method, op in methods.items():
        if method not in ("post", "put", "patch"):
            continue
        if any(k in path for k in SKIP):
            continue
        body = body_for(op)
        if body is None:
            continue
        tested += 1
        r = c.request(method.upper(), path, headers=H, json=body)
        if r.status_code >= 500:
            results["5xx"].append((method, path, r.text[:150]))
        elif r.status_code == 422:
            results["422"].append((method, path, r.text[:120]))
        elif r.status_code >= 400:
            results["4xx"].append((method, path, r.text[:110]))

print(f"exercised {tested} body-taking endpoints with synthesised valid bodies\n")
for bucket in ("5xx", "422", "4xx"):
    items = results[bucket]
    print(f"--- {bucket}: {len(items)}")
    for m, p, body in items[:45]:
        print(f"   {m.upper():5} {p}  {body}")
