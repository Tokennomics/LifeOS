"""Mini-Program Registry & Manifest Service.

Manages manifest profiles of local or sideloaded LifeOS micro-frontends (Mini-Apps).
"""

from substrate.graph import Graph

SCOPES = {"admin:read", "admin:write"}
MODULE = "miniapp"


def register_miniapp(
    graph: Graph,
    name: str,
    url: str,
    icon: str = ""
) -> dict:
    """Registers a new mini-app manifest inside the substrate database."""
    if not name.strip() or not url.strip():
        raise ValueError("name and url are required")

    session = graph.session(MODULE, SCOPES)
    
    attrs = {
        "type": "miniapp_manifest",
        "name": name,
        "url": url,
        "icon": icon
    }
    
    app_id = session.create_entity("admin_item", attrs, source="miniapp_registry")
    return {
        "app_id": app_id,
        "name": name,
        "url": url,
        "icon": icon
    }


def list_miniapps(graph: Graph) -> list[dict]:
    """Lists all registered mini-app manifests."""
    session = graph.session(MODULE, SCOPES)
    
    items = session.find_entities("admin_item", limit=200)
    apps = []

    for item in items:
        attrs = item.get("attrs", {})
        if attrs.get("type") == "miniapp_manifest":
            apps.append({
                "app_id": item["id"],
                "name": attrs.get("name"),
                "url": attrs.get("url"),
                "icon": attrs.get("icon")
            })

    return apps
