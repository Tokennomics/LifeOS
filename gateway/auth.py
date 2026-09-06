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
                # An API key is the other way to be an account. This is the line that makes
                # `/v1/developer/keys` a credential rather than a plausible string: without
                # it a key could be issued, listed and revoked and still open nothing.
                caller = _api_key_caller(graph, presented)
            if caller is None:
                raise HTTPException(status_code=401, detail="log in to continue")
            request.state.caller = caller
            return

        if not token:
            return                          # localhost dev, no accounts
        if presented != token:
            raise HTTPException(status_code=401, detail="invalid or missing bearer token")

    return require_auth


def _api_key_caller(graph: Graph, presented: str) -> dict | None:
    """A presented API key resolved to the account that issued it.

    Shaped exactly like `accounts.resolve` so everything downstream — `_actor`, `_graph`,
    every ownership check — treats a key-authenticated request as that account and nothing
    more. A key must never be a way to be *more* than its issuer.
    """
    from modules.platform import keys

    if not presented.startswith(keys.PREFIX):
        return None
    found = keys.verify(graph, presented)
    if found is None:
        return None
    return {"session_id": "", "account_id": found["account_id"],
            "owner_id": found["owner_id"], "handle": "",
            "via": "api_key", "key_id": found["key_id"], "scopes": found["scopes"]}


def caller_graph(request: Request) -> Graph:
    """The graph as this caller sees it — their own owner scope, or the config owner's."""
    base = request.app.state.graph
    caller = getattr(request.state, "caller", None)
    if caller and caller.get("owner_id"):
        return Graph(base.conn, base.bus, default_owner=caller["owner_id"])
    return base
