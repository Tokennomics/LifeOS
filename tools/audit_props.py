"""How much of the app is real, and how much is a prop?

Run it from the repo root: `python3 tools/audit_props.py`.

As of 2026-08-13 the answer was **186 of 448 handlers, 42%**. A handler returning a dict
literal is fine as a sketch and fatal as a first impression: a brand-new account was being
told it had 12 real-world meetups, 34 kudos and a "Crag Pioneer" badge, and two accounts got
byte-identical "personal" statistics. That does not read as a placeholder to a user, it reads
as the whole app being fake — and it costs you the parts that genuinely work.

As of 2026-08-22 it is **24 of 495, 5%**.

The heuristic is deliberately crude and errs toward flagging: a handler that never touches
the graph and never imports a module, but does return a dict literal, is almost certainly
inventing its answer. Read the list, do not trust the number blindly.

Erring toward flagging is not licence to be wrong by double. This once read only each
handler's own body, so the ~46 handlers that reach the graph through a shared helper
counted as literals and it reported 81 where the truth was 35. It resolves helpers first
now. A count that overstates is a count people stop reading, which is the same failure as a
status page that always says OK.
"""
import re, pathlib, collections

src = pathlib.Path("gateway/modules_api.py").read_text()
# split into handler bodies
parts = re.split(r'\n    @router\.(get|post|put|delete|patch)\("([^"]+)"\)', src)
handlers = []
for i in range(1, len(parts), 3):
    method, path, body = parts[i], parts[i+1], parts[i+2]
    handlers.append((method, path, body))

# Handlers that do their work through a shared helper — `_synergy_match`, `_conditions_for`
# — read as props to a check that only looks at the handler's own body, because the call to
# the graph is one frame down. That is not a rounding error: 46 of the 81 this once flagged
# were fully wired, and a count that overstates by more than double is a count people stop
# reading. So resolve the helpers first, then treat a call to one as touching the graph.
helper_bodies = dict(re.findall(r'\n    def (_\w+)\(.*?\n(.*?)(?=\n    (?:@router|def ))',
                                src, re.S))
graph_helpers = {name for name, body in helper_bodies.items()
                 if "_graph(request)" in body or re.search(r'from modules[.\w]* import', body)}

real, prop, unclear = [], [], []
for method, path, body in handlers:
    body = body.split("\n    @router")[0]
    touches_graph = "_graph(request)" in body or "graph" in body and "import" in body
    imports_module = re.search(r'from modules[.\w]* import', body) is not None
    delegates = any(name + "(" in body for name in graph_helpers)
    returns_literal = re.search(r'return\s*\{', body) is not None
    if touches_graph or imports_module or delegates:
        real.append((method, path))
    elif returns_literal:
        prop.append((method, path))
    else:
        unclear.append((method, path))

print(f"total handlers   : {len(handlers)}")
print(f"touch the graph  : {len(real)}")
print(f"return a literal : {len(prop)}   <-- invented data")
print(f"unclear          : {len(unclear)}")
print(f"\nshare that is prop: {len(prop)/max(len(handlers),1):.0%}\n")
print("--- every prop ---")
for m, p in prop:
    print(f"  {m.upper():5} {p}")
