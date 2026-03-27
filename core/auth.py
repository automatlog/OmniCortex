import logging
import os
from typing import Any, Dict

import httpx
from fastapi import Security, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.status import HTTP_403_FORBIDDEN, HTTP_503_SERVICE_UNAVAILABLE


bearer_scheme = HTTPBearer(auto_error=False)

# Reusable async client (connection pooling across requests).
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=httpx.Timeout(_auth_verify_timeout()))
    return _http_client


def _auth_verify_url() -> str:
    return os.getenv("AUTH_VERIFY_URL", "https://gsauth.com/api/v1/omnicortex/me").strip()


def _auth_verify_timeout() -> float:
    raw = os.getenv("AUTH_VERIFY_TIMEOUT", "8").strip()
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 8.0


async def verify_bearer_token(token: str, x_user_id: str | None = None) -> Dict[str, Any]:
    """Verify bearer token against external auth callback and return profile metadata."""
    clean_token = (token or "").strip()
    if not clean_token:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN, detail="Authorization Bearer token missing"
        )

    verify_url = _auth_verify_url()
    if not verify_url:
        raise HTTPException(
            status_code=HTTP_503_SERVICE_UNAVAILABLE,
            detail="AUTH_VERIFY_URL not configured",
        )

    verify_headers = {"Authorization": f"Bearer {clean_token}"}
    clean_user_id = (x_user_id or "").strip()
    if clean_user_id:
        verify_headers["X-User-Id"] = clean_user_id

    try:
        client = _get_http_client()
        response = await client.get(
            verify_url,
            headers=verify_headers,
        )
    except httpx.HTTPError as exc:
        logging.error(f"Auth verification request failed: {exc}")
        raise HTTPException(
            status_code=HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth verification unavailable",
        )

    if response.status_code != 200:
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Invalid bearer token")

    try:
        profile = response.json()
    except ValueError:
        profile = {"raw": response.text[:1000]}

    return {"token": clean_token, "profile": profile, "x_user_id": clean_user_id or None}


async def get_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme),
) -> Dict[str, Any]:
    """
    Validates Authorization: Bearer <token> by calling external auth callback.
    """
    if not credentials or str(credentials.scheme).lower() != "bearer" or not credentials.credentials:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN, detail="Authorization Bearer token missing"
        )

    token = str(credentials.credentials).strip()
    x_user_id = (request.headers.get("x-user-id") or "").strip()
    return await verify_bearer_token(token=token, x_user_id=x_user_id or None)
