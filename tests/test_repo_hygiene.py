"""What ships to a phone, and what only ships.

`surfaces/app/www/icons/` is 9.1 MB. Three files in it are the actual app icons; the other
thirteen are JPG logo concepts totalling ~8.7 MB, referenced by nothing in `www/` — not
`index.html`, not `app.js`, not either manifest, not either service worker. They are copied
into every deploy and never loaded by anybody.

**They are the owner's design work and this file does not touch them.** It reports. The
recommendation, which is a decision for the owner rather than a test, is in
`docs/HANDOVER.md`: move design sources to a `design/` folder *outside* the served tree, so
they stay in the repo and stop being part of the payload.

What is asserted instead is the thing that would actually hurt a user: **no image in a
service worker's precache list may be large.** `addAll` on the SHELL array is a blocking
install — the app is not usable offline until every entry has downloaded — so one 890 KB
logo concept added to that list is a first launch on hotel wifi that never finishes. The
list is where the harm is; the folder is only waste.

Run it with output visible:

    python -m pytest tests/test_repo_hygiene.py -q -s

Two things this deliberately does not assert. It ignores scripts, styles, HTML and
manifests — `app.js` is 385 KB and growing, it is the application rather than an asset, and
a rule that fails every time a feature lands is a rule somebody deletes. And `icon-512.png`
is **426 KB**, well over the 200 KB line, so it is a named exception pinned to a ceiling: it
can shrink, it cannot grow, and nothing else can join it without editing this file.
"""

import pathlib
import re

WWW = pathlib.Path(__file__).resolve().parent.parent / "surfaces" / "app" / "www"
ICONS = WWW / "icons"

SERVICE_WORKERS = ["sw.js", "travel-sw.js"]
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".avif"}

MAX_PRECACHED_IMAGE = 200 * 1024

# The one file over the line today, pinned so it can only get smaller. 426 KB of PNG for a
# 512px icon is far more than an icon needs; shrinking it is the owner's call, not a test's.
ALLOWED_LARGE = {"icons/icon-512.png": 450 * 1024}


def _shell(worker, root=WWW):
    """The paths in a service worker's `const SHELL = [...]` precache array."""
    text = (root / worker).read_text()
    block = re.search(r'const SHELL\s*=\s*\[(.*?)\]', text, re.S)
    if not block:
        return []
    return [p.lstrip("./") for p in re.findall(r'["\']([^"\']+)["\']', block.group(1))]


def _oversized(worker, root=WWW):
    """Every precached image over the line, as (path, bytes, ceiling). Empty is good.

    Takes a root so the rule can be exercised against a directory that is not the real one —
    see `test_the_size_rule_catches_a_logo_concept_in_the_shell`. A guard nobody has watched
    fail is not a guard, and this repo has already found three of those.
    """
    out = []
    for entry in _shell(worker, root):
        path = root / entry
        if path.suffix.lower() not in IMAGE_SUFFIXES or not path.exists():
            continue
        ceiling = ALLOWED_LARGE.get(entry, MAX_PRECACHED_IMAGE)
        size = path.stat().st_size
        if size > ceiling:
            out.append((entry, size, ceiling))
    return out


def test_no_service_worker_precaches_a_large_image():
    offenders = []
    for worker in SERVICE_WORKERS:
        offenders += [(worker, *o) for o in _oversized(worker)]
    assert not offenders, "\n".join(
        f"{w} precaches {p} at {s // 1024} KB, over its {c // 1024} KB ceiling"
        for w, p, s, c in offenders)


def test_the_size_rule_catches_a_logo_concept_in_the_shell(tmp_path):
    """The guard, watched failing.

    Builds a copy of `www/` whose `sw.js` precaches one of the real 600-890 KB logo
    concepts, which is the exact mistake the rule exists to stop, and checks it is reported.
    Nothing in the repo is modified.
    """
    concept = next(p for p in sorted(ICONS.glob("*.jpg"))
                   if p.stat().st_size > MAX_PRECACHED_IMAGE)

    fake = tmp_path / "www"
    (fake / "icons").mkdir(parents=True)
    (fake / "icons" / concept.name).write_bytes(concept.read_bytes())
    (fake / "sw.js").write_text(
        'const CACHE = "x";\nconst SHELL = ["./", "./icons/%s"];\n' % concept.name)

    found = _oversized("sw.js", root=fake)
    assert [entry for entry, _size, _ceiling in found] == [f"icons/{concept.name}"]
    assert found[0][1] == concept.stat().st_size


def test_lists_icons_that_ship_but_are_never_loaded():
    """Reports. Asserts nothing — these are the owner's files and the call is the owner's."""
    referenced = set()
    for path in WWW.rglob("*"):
        if not path.is_file() or ICONS in path.parents or path.suffix.lower() in IMAGE_SUFFIXES:
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for icon in ICONS.iterdir():
            if icon.name in text:
                referenced.add(icon.name)

    unreferenced = sorted(p for p in ICONS.iterdir() if p.name not in referenced)
    wasted = sum(p.stat().st_size for p in unreferenced)

    print(f"\n{ICONS.relative_to(WWW.parent.parent.parent)} — "
          f"{sum(p.stat().st_size for p in ICONS.iterdir()) / 1048576:.1f} MB total")
    print(f"  {len(unreferenced)} file(s) referenced from nowhere in www/, "
          f"{wasted / 1048576:.1f} MB, shipped with every deploy and never loaded:")
    for p in unreferenced:
        print(f"    {p.name:42} {p.stat().st_size / 1024:7.0f} KB")
    if not unreferenced:
        print("    (none)")
    print("  Recommendation is in docs/HANDOVER.md: a design/ folder outside the served tree.")
