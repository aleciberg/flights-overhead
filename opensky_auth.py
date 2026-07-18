"""
Shared OpenSky OAuth2 client-credentials token cache.

Used by both fetcher.py (/states/all) and enrichment.py (/flights/aircraft) —
both endpoint families are rate-limited separately, and anonymous access to
/flights/* runs out of quota fast, so both need the same bearer token.
"""

import os
import time
from typing import Optional

import requests

OPENSKY_AUTH_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network"
    "/protocol/openid-connect/token"
)

OPENSKY_CLIENT_ID = os.getenv("OPENSKY_USER")
OPENSKY_CLIENT_SECRET = os.getenv("OPENSKY_PASS")

_token: Optional[str] = None
_token_expires_at: float = 0.0
_TOKEN_REFRESH_MARGIN_S = 60


def get_access_token() -> Optional[str]:
    """Return a cached or freshly fetched OAuth2 bearer token, or None if
    no credentials are configured (falls back to anonymous requests)."""
    global _token, _token_expires_at

    if not OPENSKY_CLIENT_ID or not OPENSKY_CLIENT_SECRET:
        return None

    if _token and time.time() < _token_expires_at:
        return _token

    resp = requests.post(
        OPENSKY_AUTH_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": OPENSKY_CLIENT_ID,
            "client_secret": OPENSKY_CLIENT_SECRET,
        },
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()

    _token = payload["access_token"]
    _token_expires_at = time.time() + payload["expires_in"] - _TOKEN_REFRESH_MARGIN_S
    return _token


def auth_headers() -> dict:
    """Bearer-auth header dict, or {} to fall back to an anonymous request."""
    try:
        token = get_access_token()
    except requests.RequestException:
        return {}
    return {"Authorization": f"Bearer {token}"} if token else {}
