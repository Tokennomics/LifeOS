# Working on LifeOS while away from your PC

The repo lives at **github.com/Tokennomics/LifeOS**. Two ways to keep working with
nothing but a phone or a borrowed laptop — no LifeOS install, no tokens needed.

## A. Read / jot notes (fastest)

- Browse all the code + notes at github.com on any phone browser.
- To edit text (README, notes, prompts): open the repo and press **`.`** (or change
  `github.com` → `github.dev` in the URL). That's VS Code in the browser. Good for
  editing, but it **can't run** the app.

## B. Actually code AND run it — GitHub Codespaces (the good one)

A Codespace is a full Linux dev machine + VS Code in your browser. Works on a phone,
tablet, or any laptop.

1. On the repo's GitHub page → green **Code** button → **Codespaces** → **Create
   codespace on main**.
2. It boots ready to go — the devcontainer auto-installs everything
   (`pip install -r requirements.txt`). No venv dance needed; the container *is* the
   isolated environment.
3. In the Codespace terminal:
   ```bash
   python -m pytest                 # 73 tests, ~1s
   python -m substrate.migrate      # create the dev database
   uvicorn gateway.main:create_app --factory --host 0.0.0.0 --port 8787
   ```
4. Codespaces auto-forwards port 8787 and gives you a temporary **https URL**. Open
   that URL + `/app/` on your **phone** to use the actual LifeOS app — plan your week,
   capture thoughts, drop capsules — while travelling. (This is the v0.1 self-use gate,
   done from a beach.)
   - To reach it from your phone's own browser (outside the Codespace tab): open the
     **Ports** panel → right-click 8787 → **Port Visibility → Public**, then open the URL.

Everything runs token-free (offline fallbacks). Add `ANTHROPIC_API_KEY` as a Codespace
secret only if you want the AI paths live.

## Syncing back to your PC

You're editing one shared repo, so keep it simple:

- In the Codespace, after changes: `git add -A && git commit -m "…" && git push`
- Back home, before touching the PC copy: `cd C:\Ventures\lifeos && git pull`
- Don't edit both places without pulling first, or you'll get merge conflicts.

Note: `data/lifeos.db` is gitignored, so the app-data you create on holiday stays in the
Codespace and won't follow you home — that's fine, it's a tinker database. Your **code
and notes** are what sync.
