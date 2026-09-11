"""How much of the app is real, and how much is a prop?

Run it from the repo root: `python3 tools/audit_props.py`. An optional argument points it at
a different copy of the handler file, which is how it gets run against history:

    git show 17810f7:gateway/modules_api.py > /tmp/x.py && python3 tools/audit_props.py /tmp/x.py

There are two passes, because there are two kinds of prop and the first pass is blind to the
second.

PASS 1 — "returns a literal". A handler that never touches the graph and never imports a
module, but does return a dict literal, is almost certainly inventing its answer. As of
2026-08-13 that was **186 of 448 handlers, 42%**; as of 2026-08-22 it is **24 of 495, 5%**.
A brand-new account was being told it had 12 real-world meetups, 34 kudos and a "Crag
Pioneer" badge, and two accounts got byte-identical "personal" statistics. That does not
read as a placeholder to a user, it reads as the whole app being fake.

Erring toward flagging is not licence to be wrong by double. This once read only each
handler's own body, so the ~46 handlers that reach the graph through a shared helper
counted as literals and it reported 81 where the truth was 35. It resolves helpers first
now. A count that overstates is a count people stop reading, which is the same failure as a
status page that always says OK.

PASS 2 — "touch the graph but assert". Pass 1 gives a handler a clean bill the moment it
calls `_graph(request)`, and the newer class of prop does exactly that. The Munich journal
wrote real rows and stored `presence_score: "98.5%"` on them. The wearable QR scan created a
genuine `proximity_encounter` entity carrying `verified_via: "wearable_qr_scan"` and handed
back `karma_awarded: "+50 Real-World Connection Karma"` — a real write wrapped around an
invented claim. Storing something is not the same as having checked it.

So pass 2 re-reads every handler pass 1 called real, plus the bodies of the shared helpers
and module functions it can resolve, and flags a small list of tokens that in this codebase
have only ever appeared on invented values: a percent string in a value position, `karma`,
`xp_`, `trust_score`, `match_score`, `presence_score`, `verified_via`, and a literal
`"verified"/"vouched"/"found": True`. It prints the line each hit sat on, because "flagged"
without the line is a thing people stop reading.

Three sources of noise are removed before the scan, and all three were found by running it:
docstrings (house style is that a replaced handler's docstring **quotes the prop it
replaced**, so scanning them flags precisely the handlers that were fixed), `#` comments,
and any line whose key is one of the named disclaimer fields — `no_*`, `note`, `suggestion`,
`reason`, `why`. Honest copy names the thing it disclaims: `"no_score": "No karma, no
streak"` is the opposite of the defect and must not read as one. Those four filters took the
list from 21 to 8.

**What it cannot see, stated so nobody trusts it further than it goes:**

- **A true hit is not a defect.** `/payments/stripe/webhook` returns `"verified": True`
  after actually running the HMAC, and `/trust/vouch` returns `"vouched": True` after
  actually writing the vouch. Both are true statements and both are flagged; nothing here
  can tell "asserted" from "checked, then reported". Read the line.
- **It matches text, not meaning.** `x2="100%"` in an embedded SVG gradient is
  indistinguishable from `"trust_score": "98% (KYC & Graph Verified)"` — both are a percent
  string after an `=` or `:`. That false positive is left in rather than special-cased,
  because narrowing the rule until the SVG passes is how the rule stops catching the other
  one. A handler's own *name* is scanned too. That is what surfaced
  `/trust/karma-score`, whose body had been honest counts for some time while the path
  still named a thing this app does not have; it is `/trust/standing` now, with the old
  path kept as an alias, so the alias is the one that still appears here.
- **Resolution is one hop and by name.** `alias.function(...)` resolves when the import is
  visible in this file and the function is top-level in that module. `session.foo()`, two
  hops, or anything assembled dynamically is invisible, so a handler can still assert an
  invented value out of reach of this tool.
- It reads the working tree's `modules/` even when pass 1 is pointed at an old copy of the
  handler file, so a run against history mixes an old gateway with today's modules.
- A clean pass 2 means "none of these nine tokens appear". It is not a statement that the
  handler is honest, and it is not a substitute for reading the response.
"""
import ast, re, pathlib, sys

HANDLERS = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "gateway/modules_api.py")
src = HANDLERS.read_text()

# split into handler bodies
parts = re.split(r'\n    @router\.(get|post|put|delete|patch)\("([^"]+)"\)', src)
handlers = []
for i in range(1, len(parts), 3):
    method, path, body = parts[i], parts[i+1], parts[i+2]
    handlers.append((method, path, body.split("\n    @router")[0]))

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
    touches_graph = "_graph(request)" in body or "graph" in body and "import" in body
    imports_module = re.search(r'from modules[.\w]* import', body) is not None
    delegates = any(name + "(" in body for name in graph_helpers)
    returns_literal = re.search(r'return\s*\{', body) is not None
    if touches_graph or imports_module or delegates:
        real.append((method, path, body))
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


# ---------------------------------------------------------------- pass 2

# `from modules.social import trust` -> trust -> modules/social/trust.py
# `from modules.city import guide, live` -> both.
aliases = {}
for pkg, names in re.findall(r'from (modules[.\w]*) import ([^\n(]+)', src):
    for name in (n.strip().split(" as ")[-1].strip() for n in names.split(",")):
        if not name:
            continue
        cand = pathlib.Path(pkg.replace(".", "/")) / f"{name}.py"
        if cand.exists():
            aliases[name] = cand

_parsed = {}
def _module_function(alias, func):
    """The top-level body of `func` in the module `alias` names, or "" if not resolvable.

    Through `ast` rather than a regex, because a `def` here routinely spans three lines and
    a signature-shaped regex silently returned the tail of the signature instead of the
    body — which meant the docstring survived and every honestly-replaced handler was
    flagged by the prop its own docstring was quoting. The docstring is dropped here.
    """
    path = aliases.get(alias)
    if path is None:
        return ""
    if path not in _parsed:
        text = path.read_text()
        try:
            _parsed[path] = (text, ast.parse(text))
        except SyntaxError:
            _parsed[path] = (text, None)
    text, tree = _parsed[path]
    if tree is None:
        return ""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func:
            stmts = node.body
            if (stmts and isinstance(stmts[0], ast.Expr)
                    and isinstance(stmts[0].value, ast.Constant)
                    and isinstance(stmts[0].value.value, str)):
                stmts = stmts[1:]          # the docstring
            return "\n".join(ast.get_source_segment(text, s) or "" for s in stmts)
    return ""


# Tokens that in this repo have only ever sat on an invented value. Each is paired with the
# words to print, because "flagged" without the reason is not actionable.
TELLS = [
    (re.compile(r'[:=]\s*f?["\'][^"\'\n]*\b\d+%'), 'a percent string in a value position'),
    (re.compile(r'karma'),                          'karma'),
    (re.compile(r'\bxp_'),                          'xp_'),
    (re.compile(r'trust_score'),                    'trust_score'),
    (re.compile(r'match_score'),                    'match_score'),
    (re.compile(r'presence_score'),                 'presence_score'),
    (re.compile(r'verified_via'),                   'verified_via'),
    (re.compile(r'["\']verified["\']\s*:\s*True'),  '"verified": True'),
    (re.compile(r'["\']vouched["\']\s*:\s*True'),   '"vouched": True'),
    (re.compile(r'["\']found["\']\s*:\s*True'),     '"found": True'),
]


_AFTER_DEF = re.compile(
    r'(\bdef \w+\((?:[^()]|\([^()]*\))*\)[^\n:]*:[ \t]*\n[ \t]*)(?:[rfbu]{0,2})("""|\'\'\').*?\2', re.S)
_LEADING = re.compile(r'\A[ \t\r\n]*(?:[rfbu]{0,2})("""|\'\'\').*?\1', re.S)

def _undoc(body):
    """Drop a leading docstring, and only that.

    House style here is that a replaced handler's docstring quotes the prop it replaced —
    "returned `trust_score: 98/100`" — so scanning docstrings flags precisely the handlers
    that were fixed. Only a docstring is dropped: a triple-quoted string further down is
    usually content (`tshirt_studio` builds its whole SVG that way) and is exactly where an
    invented value hides.

    Two shapes, because a handler body arrives with its `def` line attached while a helper
    body arrives already inside the function. (Module functions come back from
    `_module_function` with the docstring gone; the second pattern is the belt to that
    braces.)
    """
    body = _LEADING.sub("", _AFTER_DEF.sub(r"\1", body), count=1)
    return "\n".join(_keep(line) for line in body.splitlines())


# Trap 1 in this repo: honest copy names the thing it disclaims, so "No karma, no streak"
# trips the `karma` rule. House style puts every disclaimer in one of a small set of named
# fields, so those lines are dropped, along with comments — a comment saying the old
# response carried `trust_score: "98/100"` is the note that it no longer does.
_DISCLAIMER = re.compile(r'["\'](?:no_\w+|note|suggestion|reason|why|disclaimer)["\']\s*:')

def _keep(line):
    if _DISCLAIMER.search(line):
        return ""
    return line.split("#", 1)[0] if "#" in line and not re.search(r'["\'][^"\']*#', line) else line


def _reach(body):
    """The handler body plus everything one resolvable hop below it."""
    text = [_undoc(body)]
    for name, hbody in helper_bodies.items():
        if name + "(" in body:
            text.append(_undoc(hbody))
    for alias, func in re.findall(r'\b(\w+)\.(\w+)\s*\(', body):
        if alias in aliases:
            text.append(_undoc(_module_function(alias, func)))
    return "\n".join(text)


asserts = []
for method, path, body in real:
    text = _reach(body)
    hits = []
    for rx, label in TELLS:
        m = rx.search(text)
        if m:
            # The line it sat on, so a disclaimer or an SVG gradient is obvious on sight
            # rather than after opening the file. A bare "flagged" is not actionable.
            line = text[:m.start()].rsplit("\n", 1)[-1] + text[m.start():].split("\n", 1)[0]
            hits.append((label, " ".join(line.split())[:78]))
    if hits:
        asserts.append((method, path, sorted(hits)))

print(f"\n--- touch the graph but assert : {len(asserts)} ---")
print("(these reach the graph and still name an invented-looking value; read the line)")
if not asserts:
    print("  (none)")
for m, p, hits in asserts:
    print(f"  {m.upper():5} {p}")
    for label, line in hits:
        print(f"        {label:38}  {line}")
