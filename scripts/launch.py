"""Start the gateway (and the PWA it serves) with one command.

**Binding is deliberate, and it used to be wrong for every hosted deployment.** This bound
`127.0.0.1` unconditionally, which is right on a laptop and fatal in a container: the
process starts, the logs look healthy, and nothing outside the container can reach it. Every
platform host — Render, Fly, Railway, a plain Docker run — also assigns the port it wants
through `$PORT` rather than letting the app pick 8000.

So:

- `PORT` (or `LIFEOS_PORT`) is honoured, defaulting to 8000.
- `LIFEOS_HOST` chooses the interface, defaulting to `127.0.0.1` — a laptop should not
  publish itself to the café wifi just because someone ran the launcher.
- **Except when `PORT` is set**, which is how every PaaS announces "you are in a container
  and I will route traffic to you". Then the default flips to `0.0.0.0`, because a container
  that binds loopback is a container nobody can reach.

An explicit `LIFEOS_HOST` always wins over that heuristic.
"""

import os
import sys

import uvicorn

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def resolve_bind() -> tuple[str, int]:
    """(host, port) from the environment, with the container heuristic explained above."""
    port_var = os.environ.get("PORT") or os.environ.get("LIFEOS_PORT") or ""
    in_container = bool(port_var.strip())
    try:
        port = int(port_var) if in_container else 8000
    except ValueError:
        port = 8000
    host = os.environ.get("LIFEOS_HOST", "").strip() or ("0.0.0.0" if in_container else "127.0.0.1")
    return host, port


def main():
    host, port = resolve_bind()
    shown = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host
    print("Launching LifeOS — local-first life operating system")
    print(f"[*] Gateway   http://{shown}:{port}")
    print(f"[*] App       http://{shown}:{port}/app/")
    print(f"[*] API docs  http://{shown}:{port}/docs")
    if host == "0.0.0.0":
        print("[*] Bound to all interfaces (PORT is set, so this looks like a container).")
    uvicorn.run("gateway.main:create_app", factory=True, host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
