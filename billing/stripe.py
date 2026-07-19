"""Billing scaffolding — OFF by default. No stripe import, no network, until a key exists.

While billing is disabled every feature is entitled (n=1 self-use). When STRIPE_KEY is
set, `entitled()` becomes the gate for PLUS_FEATURES and the checkout flow gets built
against real products. Monetization plan: master doc §4.
"""

PLUS_FEATURES = {
    "unlimited_ai",      # unlimited AI planning/retros
    "seasons",
    "reconnect_auto",
    "memento_vault",
    "steward_automations",
}

FREE_FEATURES = {"capture", "basic_weekly_plan", "one_convoy_per_month", "export"}


def billing_enabled(cfg: dict) -> bool:
    return bool(cfg.get("billing", {}).get("stripe_key"))


def entitled(cfg: dict, feature: str) -> bool:
    if not billing_enabled(cfg):
        return True  # everything free while billing is off
    if feature in FREE_FEATURES:
        return True
    # TODO(stripe): look up the subscription for cfg.owner.id once checkout exists.
    return False
