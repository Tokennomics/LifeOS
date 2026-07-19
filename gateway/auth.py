"""Bearer-token auth for the gateway. Empty token = auth disabled (local dev)."""

from fastapi import Header, HTTPException


def make_auth_dependency(token: str):
    async def require_auth(authorization: str = Header(default="")):
        if not token:
            return
        if authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="invalid or missing bearer token")

    return require_auth
