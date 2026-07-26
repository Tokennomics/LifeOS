"""Gateway auth: legacy single-user bearer token, or real accounts once any exist.

Two modes, chosen by the data rather than a flag:

  no accounts registered -> the original behaviour. The configured static token (or no
                            token at all, for localhost dev) grants access as the config
                            owner. Nothing about an existing install changes.
  accounts registered    -> callers must present a session token from /v1/auth/login, and
                            every request is scoped to that account's own slice of the
                            graph. The static token still works as the owner's key, so
                            the bot and local scripts keep running.
"""

from fastapi import Header, HTTPException, Request

from gateway import accounts
from substrate.graph import Graph


def _bearer(authorization: str) -> str:
    if authorization.startswith("Bearer "):
        return authorization[len("Bearer "):].strip()
    return ""


def make_auth_dependency(token: str):
    async def require_auth(request: Request, authorization: str = Header(default="")):
        graph = getattr(request.app.state, "graph", None)
        presented = _bearer(authorization)
        request.state.caller = None

        if graph is not None and accounts.accounts_exist(graph):
            if token and presented == token:
                return                      # the owner's own key: config-owner scope
            caller = accounts.resolve(graph, presented)
            if caller is None:
                raise HTTPException(status_code=401, detail="log in to continue")
            request.state.caller = caller
            return

        if not token:
            return                          # localhost dev, no accounts
        if presented != token:
            raise HTTPException(status_code=401, detail="invalid or missing bearer token")

    return require_auth


def caller_graph(request: Request) -> Graph:
    """The graph as this caller sees it — their own owner scope, or the config owner's."""
    base = request.app.state.graph
    caller = getattr(request.state, "caller", None)
    if caller and caller.get("owner_id"):
        return Graph(base.conn, base.bus, default_owner=caller["owner_id"])
    return base
