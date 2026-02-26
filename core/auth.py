import logging
import os
from typing import Any, Dict

import requests
from fastapi import Security, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.status import HTTP_403_FORBIDDEN, HTTP_503_SERVICE_UNAVAILABLE


bearer_scheme = HTTPBearer(auto_error=False)


def _auth_verify_url() -> str:
    return os.getenv("AUTH_VERIFY_URL", "https://gsauth.com/api/v1/omnicortex/me").strip()


def _auth_verify_timeout() -> float:
    raw = os.getenv("AUTH_VERIFY_TIMEOUT", "8").strip()
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 8.0


async def get_api_key(
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
    verify_url = _auth_verify_url()
    if not verify_url:
        raise HTTPException(
            status_code=HTTP_503_SERVICE_UNAVAILABLE,
            detail="AUTH_VERIFY_URL not configured",
        )

    try:
        response = requests.get(
            verify_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=_auth_verify_timeout(),
        )
    except requests.RequestException as exc:
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

    return {"token": token, "profile": profile}
