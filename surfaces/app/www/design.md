# LifeOS — Design Philosophy: "Lumen"

*The living light on a dark field. You are the light source; the dark is what's at rest.*

The design language has to mean the same thing the product means (Law 8: the app renders
the life, it doesn't perform for attention). Four commitments, each traceable to a Law and
to the research.

## 1. Quiet by default, alive in the moment

Law 3 forbids engagement-time optimization; the guardrail is *app-minutes stays LOW*. So this
is **the opposite of a dopamine app.** No red notification bait, no infinite feed, no
comparison. The surface is calm and recessive so it gets out of the way — and then the few
moments that actually matter (a plan created, a capsule unlocking, a friendship refreshed)
get one small, warm, *earned* flourish. Every flow is built to finish and let you leave.

*Research anchor:* Gentler Streak — "progress, not comparison"; subtle, consistently pleasing
language. 2026 micro-interactions matured from decoration to "micro-delight" that is
functionally meaningful.

## 2. Warmth over clinical

A life OS is not a spreadsheet. The palette is a warm amber spark (you — energy, self)
glowing on a deep night field (rest, the unlit, what's at peace). Generous breathing room,
soft organic radii, and an **editorial serif** for the "written" moments — the vision, the
retro, the big numbers — so the app reads like a personal almanac of your life, not a dashboard.
Functional chrome stays in a clean sans.

*Research anchor:* Gentler Streak's "humanity"; typography hierarchy via typeface + weight +
whitespace, not noise.

## 3. Depth as the layers of a life

The graph is deep; the UI shows it. Elevation is built from lightness (each layer catches a
little more light), a whisper of ambient gradient on the base, and hairline top-highlights so
cards feel like they float — a restrained nod to 2026's spatial / liquid-glass depth without
heavy blur that would fight legibility on OLED.

*Research anchor:* Dark-mode elevation = lighter surfaces for higher layers; desaturate accents
10–20% so nothing vibrates against the dark; body text ≥ 15:1 contrast.

## 4. Reachable, one-handed, honest

Primary actions and the 6-tab bar live in the bottom thumb zone; touch targets ≥ 44px;
≥ 8px between them. "Local" is shown with pride, not as "offline" — local-first is Law 6, a
feature, not a downgrade. AI mode is a calm green upgrade, never a nag.

*Research anchor:* thumb-zone (bottom third most reachable; ~49% one-handed use); Apple 44pt /
Material 48dp targets; bottom nav is the decade's biggest mobile-UX win.

## Tokens (see style.css `:root`)

- **night** `#0A0D14` base · **surface-1/2/3** rising layers · **line** hairlines
- **spark** `#F0A94A` (amber — self/energy/primary) · **growth** `#63CE8B` (done/progress)
- **calm** `#7FA8D8` (people/rest/info) · **warn** `#E6906E` (gentle, never alarm-red)
- **text** `#ECEFF6` (~15:1) · **muted** · **faint**
- Type: **Georgia** serif for editorial moments · system sans for UI
- Space: 4pt system · Radii: 18px cards / 12px fields / full pills
- Motion: 200–320ms ease-out, entrance on tab-change only, all gated by
  `prefers-reduced-motion`. The brand node breathes — the one always-alive element.
