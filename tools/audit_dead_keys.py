"""Keys the PWA reads off a response that no route or module ever emits.

Run from the repo root: `python3 tools/audit_dead_keys.py`.

The companion to `audit_props.py`, and the defect that tool's success creates. When a prop
handler is replaced, its invented keys stop being returned — but the card still reads them,
so it renders `undefined` where it used to render a fabrication. Better, and still broken.

The heuristic is deliberately crude in one direction: a key counts as live if *any* file
under `gateway/` or `modules/` emits it, so a key that is dead on the route a card calls but
alive on some other route will not be flagged. It under-reports; it does not invent. Read
the list against the handler the card actually calls.

As of 2026-09-05 it reports 76 dead of 263 reads. `docs/tickets/T5-dead-response-keys.md`
is the ticket to close that.
"""
import os, re, sys, pathlib
js = pathlib.Path("surfaces/app/www/app.js").read_text()
# strip comments so changelog prose does not count as a read
js = re.sub(r'/\*.*?\*/', '', js, flags=re.S)
js = re.sub(r'^\s*//.*$', '', js, flags=re.M)
reads = set()
for m in re.finditer(r'\bres\.([a-z_][a-z0-9_]*)\b', js):
    reads.add(m.group(1))
server = ""
for p in list(pathlib.Path("gateway").rglob("*.py")) + list(pathlib.Path("modules").rglob("*.py")):
    server += p.read_text()
emitted = set(re.findall(r'"([a-z_][a-z0-9_]*)"\s*:', server))
emitted |= set(re.findall(r"'([a-z_][a-z0-9_]*)'\s*:", server))
dead = sorted(k for k in reads if k not in emitted)
# `| head` closes the pipe mid-write; that is the shell being asked for fewer lines, not an
# error, and a traceback there makes a working tool look broken.
try:
    print(f"{len(reads)} distinct res.X reads, {len(dead)} with no server-side key")
    for k in dead:
        print("  ", k)
    sys.stdout.flush()
except BrokenPipeError:
    os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
