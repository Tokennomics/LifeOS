"""How much of the app is real, and how much is a prop?

Run it from the repo root: `python3 tools/audit_props.py`.

As of 2026-08-13 the answer was **186 of 448 handlers, 42%**. A handler returning a dict
literal is fine as a sketch and fatal as a first impression: a brand-new account was being
told it had 12 real-world meetups, 34 kudos and a "Crag Pioneer" badge, and two accounts got
byte-identical "personal" statistics. That does not read as a placeholder to a user, it reads
as the whole app being fake — and it costs you the parts that genuinely work.

The heuristic is deliberately crude and errs toward flagging: a handler that never touches
the graph and never imports a module, but does return a dict literal, is almost certainly
inventing its answer. Read the list, do not trust the number blindly.

Heuristic: a handler that never touches the graph and returns a dict literal is returning
invented data. That is fine for a mock and fatal for a first impression.
"""
import re, pathlib, collections

src = pathlib.Path("gateway/modules_api.py").read_text()
# split into handler bodies
parts = re.split(r'\n    @router\.(get|post|put|delete|patch)\("([^"]+)"\)', src)
handlers = []
for i in range(1, len(parts), 3):
    method, path, body = parts[i], parts[i+1], parts[i+2]
    handlers.append((method, path, body))

real, prop, unclear = [], [], []
for method, path, body in handlers:
    touches_graph = "_graph(request)" in body or "graph" in body and "import" in body
    imports_module = re.search(r'from modules[.\w]* import', body) is not None
    returns_literal = re.search(r'return\s*\{', body) is not None
    if touches_graph or imports_module:
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
print("--- a sample of the props ---")
for m, p in prop[:30]:
    print(f"  {m.upper():5} {p}")
