"""Today leads with today, there is one navigation bar, and the shortcuts are real.

A brand-new account used to land on 70 cards and 198 visible buttons. The four used every
day — this week's plan, the weekend, Steward, the journal — were cards 67 to 70, below a
feature palette, a guided tour, and operator tools such as Revenue and Stripe & PayPal.
`tidyToday()` in app.js reorders Today after it renders; measured in Chromium on a phone
viewport, the first screen went to 5 cards and 16 buttons.

The reorder finds cards by heading, which is exactly how it could break silently: rename
a card and it falls out of the order with no error. These tests read the source so that a
rename fails here instead.
"""

import pathlib
import re

WWW = pathlib.Path(__file__).resolve().parent.parent / "surfaces/app/www"
APP = (WWW / "app.js").read_text()
INDEX = (WWW / "index.html").read_text()


def _list(name):
    body = re.search(rf"const {name} = \[(.*?)\];", APP, re.S).group(1)
    return re.findall(r'"([^"]+)"', body)


def _headings():
    """Every card heading in app.js, normalised the way cardKey() normalises it."""
    out = []
    for raw in re.findall(r"<h[23][^>]*>(.*?)</h[23]>", APP, re.S):
        text = re.sub(r"<[^>]+>", "", raw)
        text = re.sub(r"\$\{[^}]*\}", "X", text)
        text = text.replace("&amp;", "&").lower()
        out.append(re.sub(r"^[^a-z]+", "", text).strip())
    return out


def test_every_card_the_reorder_names_still_exists():
    headings = _headings()
    missing = [key for key in _list("TODAY_CORE") + _list("TODAY_OPERATOR")
               if not any(h.startswith(key) for h in headings)]
    assert missing == [], f"tidyToday() names cards that no longer exist: {missing}"


def test_the_daily_cards_come_first_in_order():
    assert _list("TODAY_CORE") == ["welcome to lifeos", "week ", "weekend digest",
                                   "steward", "reflection journal"]


def test_operator_tools_are_not_on_the_daily_path():
    """Revenue, payments, the plugin SDK and the content pipeline are for whoever runs the
    box. They fold into their own section at the end of Today rather than into Explore."""
    operator = _list("TODAY_OPERATOR")
    for key in ("revenue", "stripe & paypal", "what is switched on", "automated city content"):
        assert key in operator


def test_the_reorder_runs_before_handlers_are_wired():
    """Moving cards after wire() would keep their listeners, but running it first means
    nothing depends on that."""
    render = APP[APP.index("function render() {"):]
    assert render.index("tidyToday(view)") < render.index("wire(view)")


def test_one_navigation_bar():
    """A floating dock was created on every render over the fixed bottom nav: six tabs to
    its seven, no Capture, different names for the same places, and it swallowed taps."""
    assert 'className = "mobile-dock"' not in APP
    assert "data-dock=" not in APP
    tabs = re.findall(r'data-tab="([a-z]+)"', INDEX)
    assert "capture" in tabs and len(tabs) == len(set(tabs)) == 7


def test_ctrl_k_has_exactly_one_meaning_and_one_listener():
    """It was bound twice — once per render, inside wire() — and the two raced: one opened a
    modal, the other focused a search box behind it."""
    listeners = re.findall(r'key(?:\.toLowerCase\(\))?\s*===\s*"k"', APP)
    assert len(listeners) == 1


def test_the_shortcut_list_matches_the_shortcuts_that_exist():
    """The list advertised T, P, M, S, V, F and B, and no handler read any of them."""
    body = re.search(r"const SHORTCUTS = \{(.*?)\n\};", APP, re.S).group(1)
    bound = {k.upper() if k != "?" else "?" for k in re.findall(r'^\s*"?([a-z?])"?\s*:', body, re.M)}
    listed = set(re.findall(r"<code[^>]*>([^<]+)</code>", INDEX)) - {"Ctrl+K"}
    assert listed == bound, f"listed {sorted(listed)} but bound {sorted(bound)}"


def test_every_shortcut_target_exists():
    for act in ("focus-start", "mindfulness-start"):
        assert f'data-act="{act}"' in APP, f"shortcut presses {act}, which is gone"
    assert 'id="camera-scan-btn"' in INDEX


def test_single_letters_are_ignored_while_typing():
    guard = APP[APP.index("function typingInto"):APP.index("const run = SHORTCUTS")]
    for tag in ("input", "textarea", "select", "isContentEditable"):
        assert tag in guard
