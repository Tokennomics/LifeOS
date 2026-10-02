"""A shipped change to the app reaches phones that already installed it.

Both service workers serve their shell cache-first, and a browser only re-installs a worker
when the worker file's own bytes change. So editing app.js without touching sw.js ships
nothing to an installed app: #33 (the voice copilot) and #35 (the refresh card) both
changed app.js and left sw.js alone, and every phone that had the app kept the old code.

Each worker therefore carries `SHELL_FINGERPRINT`, a hash of the files it precaches. Change
any of them and this test fails with the new value; pasting it in (and bumping CACHE)
changes the worker's bytes, which is what makes a phone fetch the new shell.
"""

import hashlib
import pathlib
import re

import pytest

WWW = pathlib.Path(__file__).resolve().parent.parent / "surfaces/app/www"
WORKERS = ["sw.js", "travel-sw.js"]


def _shell(text: str) -> list[str]:
    block = re.search(r"const SHELL\s*=\s*\[(.*?)\]", text, re.S).group(1)
    paths = [p[2:] if p.startswith("./") else p for p in re.findall(r'["\']([^"\']+)["\']', block)]
    return [p for p in paths if p]


def fingerprint(worker: str, root: pathlib.Path = WWW) -> str:
    text = (root / worker).read_text()
    digest = hashlib.sha256()
    for path in sorted(_shell(text)):
        digest.update(path.encode() + b"\0" + (root / path).read_bytes() + b"\0")
    return digest.hexdigest()[:16]


def _declared(worker: str, root: pathlib.Path = WWW) -> str:
    found = re.search(r'const SHELL_FINGERPRINT = "([0-9a-f]+)";', (root / worker).read_text())
    return found.group(1) if found else ""


@pytest.mark.parametrize("worker", WORKERS)
def test_the_worker_names_the_shell_it_caches(worker):
    want = fingerprint(worker)
    assert _declared(worker) == want, (
        f"{worker}'s precached files changed. Bump CACHE and set "
        f'const SHELL_FINGERPRINT = "{want}"; — otherwise installed apps keep the old files.')


def test_the_check_fails_when_a_cached_file_changes(tmp_path):
    for name in ("sw.js", "index.html", "style.css", "app.js", "agent.js",
                 "manifest.webmanifest"):
        (tmp_path / name).write_bytes((WWW / name).read_bytes())
    (tmp_path / "icons").mkdir()
    for icon in ("icon-192.png", "icon-512.png", "apple-touch-icon.png"):
        (tmp_path / "icons" / icon).write_bytes((WWW / "icons" / icon).read_bytes())
    assert _declared("sw.js", tmp_path) == fingerprint("sw.js", tmp_path)
    (tmp_path / "app.js").write_text((WWW / "app.js").read_text() + "\n// edited")
    assert _declared("sw.js", tmp_path) != fingerprint("sw.js", tmp_path)
