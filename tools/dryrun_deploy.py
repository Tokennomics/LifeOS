"""Start the gateway exactly as render.yaml configures it, and check the deploy path.

Run from the repo root: `python3 tools/dryrun_deploy.py`. Exits non-zero on a problem.

Everything about a Render deploy that can be checked without paying for one: the port and
health path are read from render.yaml rather than repeated here, the config is the
repository's own config.yaml (the file the Dockerfile bakes in and load_config falls back
to), and the two secrets are generated the way Render generates them.

The first version of this wrote its own config with `auth_token: ""` and reported a
wide-open box. That was the harness, not the app — the committed config reads the token
from the environment. A dry run that does not use the real config tests a deployment
nobody is going to make.

Render sets PORT and generates both secrets; scripts/launch.py must read PORT and bind
0.0.0.0, /health must answer for the health check, and the box must NOT be open to an
unauthenticated caller. All of that is checkable here, before anybody pays for a service.
"""
import json, os, pathlib, re, secrets, socket, subprocess, sys, tempfile, time, urllib.request

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)
blueprint = pathlib.Path(ROOT, "render.yaml").read_text()
PORT = int(re.search(r"- key: PORT\n\s+value: (\d+)", blueprint).group(1))
HEALTH = re.search(r"healthCheckPath: (\S+)", blueprint).group(1)
print(f"from render.yaml: PORT={PORT}  healthCheckPath={HEALTH}")

data = tempfile.mkdtemp()
# Use the repository's OWN config.yaml — that is the file baked into the image by the
# Dockerfile's `COPY . .` and the one load_config falls back to when LIFEOS_CONFIG is
# unset, which it is on Render. Writing a config here instead would test a file that does
# not exist in production: the first attempt did exactly that, set auth_token to "" rather
# than the committed "env:LIFEOS_GATEWAY_TOKEN", and reported a wide-open box that was an
# artefact of the harness. Only the database path is redirected, so the run is disposable.
import yaml as _yaml
real = _yaml.safe_load(pathlib.Path(ROOT, "config.yaml").read_text())
assert real["gateway"]["auth_token"] == "env:LIFEOS_GATEWAY_TOKEN", \
    f"config.yaml no longer reads the token from the environment: {real['gateway']['auth_token']!r}"
real.setdefault("sqlite", {})["path"] = str(pathlib.Path(data) / "lifeos.db")
cfg = pathlib.Path(data, "config.yaml")
cfg.write_text(_yaml.safe_dump(real))
# Exactly what Render provides: the port, and two independently generated secrets.
env = {**os.environ, "LIFEOS_CONFIG": str(cfg), "PORT": str(PORT),
       "LIFEOS_SIGNING_KEY": secrets.token_urlsafe(32),
       "LIFEOS_GATEWAY_TOKEN": secrets.token_urlsafe(32)}
assert env["LIFEOS_SIGNING_KEY"] != env["LIFEOS_GATEWAY_TOKEN"]

launcher = pathlib.Path(ROOT, "scripts/launch.py")
cmd = [sys.executable, str(launcher)] if launcher.exists() else [
    sys.executable, "-m", "uvicorn", "gateway.main:create_app", "--factory",
    "--port", str(PORT), "--host", "0.0.0.0"]
print("launching:", " ".join(cmd[-3:]))
srv = subprocess.Popen(cmd, cwd=ROOT, env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
for _ in range(100):
    try:
        socket.create_connection(("127.0.0.1", PORT), 0.4).close(); break
    except OSError: time.sleep(0.4)
else:
    print("FAILED to start:\n", srv.stdout.read().decode()[-2000:]); sys.exit(1)

problems = []
def get(path, token=None):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}")
    if token: req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=10) as r: return r.status, r.read(400).decode()
    except urllib.error.HTTPError as e: return e.code, e.read(200).decode()

# 1. the health check Render will poll
s, _ = get(HEALTH)
print(f"{HEALTH:28} -> {s}")
if s != 200: problems.append(f"{HEALTH} returned {s}; Render marks the deploy unhealthy")

# 2. it must bind 0.0.0.0, not loopback — a loopback bind is unreachable behind Render
host_ip = socket.gethostbyname(socket.gethostname())
try:
    socket.create_connection((host_ip, PORT), 2).close()
    print(f"bound on {host_ip:19} -> reachable")
except OSError:
    problems.append(f"not listening on {host_ip}: bound loopback only, unreachable on Render")

# 3. the window #26 closed: with both secrets set, nothing answers unauthenticated
for path in ("/v1/graph", "/v1/today", "/v1/people"):
    s, _ = get(path)
    print(f"{path:28} -> {s} unauthenticated")
    if s == 200: problems.append(f"{path} answers 200 with no credentials")

# 4. and the owner's own token does work
s, _ = get("/v1/today", token=env["LIFEOS_GATEWAY_TOKEN"])
print(f"{'/v1/today (with token)':28} -> {s}")
if s != 200: problems.append(f"/v1/today rejects the generated LIFEOS_GATEWAY_TOKEN ({s})")

srv.terminate()
print("\n--- problems ---")
print("\n".join(problems) if problems else "none — the blueprint's config starts a healthy, closed box")
sys.exit(1 if problems else 0)
