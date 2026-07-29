"""Multi-Provider SSO Identity Layer.

Federated social & identity auth provider support: Google OAuth, Apple ID,
Phone OTP, and Email/Password.
"""

from substrate.graph import Graph

SUPPORTED_PROVIDERS = {"google", "apple", "phone", "email"}
SCOPES = {"people:read", "people:write"}
MODULE = "accounts"


def get_supported_providers() -> list[str]:
    """Returns list of supported identity providers."""
    return sorted(list(SUPPORTED_PROVIDERS))


def authenticate_sso(graph: Graph, provider: str, provider_user_id: str,
                     email: str = "", phone: str = "", name: str = "",
                     source: str = MODULE) -> dict:
    """Authenticates or creates a user account via an SSO provider."""
    p_clean = provider.lower().strip()
    if p_clean not in SUPPORTED_PROVIDERS:
        raise ValueError(f"unsupported provider '{provider}' (supported: {sorted(list(SUPPORTED_PROVIDERS))})")
    if not provider_user_id.strip():
        raise ValueError("provider_user_id required")

    session = graph.session(MODULE, SCOPES)
    existing_people = session.find_entities("person", limit=500)

    matched = None
    for p in existing_people:
        attrs = p.get("attrs", {})
        if attrs.get("provider") == p_clean and attrs.get("provider_user_id") == provider_user_id:
            matched = p
            break
        if email and attrs.get("email") == email.lower().strip():
            matched = p
            break
        if phone and attrs.get("phone") == phone.strip():
            matched = p
            break

    if matched:
        account_id = matched["id"]
        is_new = False
    else:
        disp_name = name.strip() or email.split("@")[0] if email else f"User_{provider_user_id[:6]}"
        account_id = session.create_entity(
            "person",
            {
                "name": disp_name,
                "provider": p_clean,
                "provider_user_id": provider_user_id.strip(),
                "email": email.lower().strip(),
                "phone": phone.strip(),
                "linked_providers": [p_clean],
            },
            source=source,
        )
        is_new = True

    return {
        "account_id": account_id,
        "provider": p_clean,
        "provider_user_id": provider_user_id,
        "email": email,
        "phone": phone,
        "is_new": is_new,
    }


def link_identity_provider(graph: Graph, account_id: str, provider: str,
                           provider_user_id: str, source: str = MODULE) -> dict:
    """Links an additional identity provider to an existing account."""
    p_clean = provider.lower().strip()
    if p_clean not in SUPPORTED_PROVIDERS:
        raise ValueError(f"unsupported provider '{provider}'")

    session = graph.session(MODULE, SCOPES)
    entity = session.get_entity(account_id)
    if not entity or entity.get("kind") != "person":
        raise ValueError(f"account '{account_id}' not found")

    attrs = entity.get("attrs", {})
    providers = set(attrs.get("linked_providers", []))
    providers.add(p_clean)
    attrs["linked_providers"] = sorted(list(providers))
    session.update_entity(account_id, attrs, source=source)

    return {
        "account_id": account_id,
        "linked_providers": attrs["linked_providers"],
    }
