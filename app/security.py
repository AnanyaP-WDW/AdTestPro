"""Network boundary: optional shared-token auth, same-origin writes, safe headers.

Local single-user default: no ADTESTPRO_AUTH_TOKEN means no auth (dev convenience).
Set it (and expose the app beyond localhost) to require HTTP Basic / Bearer.
Browser pages get the native Basic prompt; API clients can send Bearer.
"""

from __future__ import annotations

import base64
import binascii
import logging
import os
import secrets
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import PlainTextResponse

logger = logging.getLogger("adtestpro.security")

AUTH_ENV = "ADTESTPRO_AUTH_TOKEN"
OPEN_PATHS = {"/health"}  # Docker healthcheck stays unauthenticated
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
SAFE_FETCH_SITES = {"same-origin", "none"}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    # Inline script/style are already used by the shell; this still pins every
    # source to this origin (plus data: images) and blocks external exfiltration.
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; "
        "form-action 'self'"
    ),
}


def auth_token() -> str:
    return os.getenv(AUTH_ENV, "").strip()


def _presented_token(request: Request) -> str:
    """Bearer token, or the password half of Basic (username is ignored)."""
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    value = value.strip()
    if scheme.lower() == "bearer":
        return value
    if scheme.lower() == "basic" and value:
        try:
            decoded = base64.b64decode(value, validate=True).decode("utf-8", "replace")
        except (binascii.Error, ValueError):
            return ""
        return decoded.partition(":")[2]
    return ""


def authorized(request: Request) -> bool:
    token = auth_token()
    if not token:
        return True  # single-user local default: nothing to check
    return secrets.compare_digest(_presented_token(request), token)


def same_origin(request: Request) -> bool:
    """Reject cross-site writes (CSRF).

    Origin is authoritative when the browser sends one. Sandboxed preview panes
    send `Origin: null`, so there the fetch-metadata hint is the only signal.
    Non-browser clients (curl, tests) send neither and are not CSRF-able.
    """
    host = request.headers.get("host", "").strip().lower()
    origin = request.headers.get("origin")
    if origin and origin != "null":
        return bool(host) and urlsplit(origin).netloc.lower() == host
    site = request.headers.get("sec-fetch-site", "").strip().lower()
    if not site:
        return origin is None  # opaque origin with no hint is refused
    return site in SAFE_FETCH_SITES


def _finish(response, path: str):
    for key, value in SECURITY_HEADERS.items():
        response.headers.setdefault(key, value)
    if not path.startswith("/static/"):
        response.headers.setdefault("Cache-Control", "no-store")  # settings can hold a key
    return response


async def security_middleware(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS":  # CORS preflight must pass through untouched
        return _finish(await call_next(request), path)
    if path not in OPEN_PATHS:
        if not authorized(request):
            response = PlainTextResponse("Authentication required.", status_code=401)
            response.headers["WWW-Authenticate"] = 'Basic realm="AdTestPro", charset="UTF-8"'
            return _finish(response, path)
        if request.method in UNSAFE_METHODS and not same_origin(request):
            # Header values only: enough to diagnose a proxy/preview pane, no secrets.
            logger.warning("refused %s %s origin=%r host=%r sec-fetch-site=%r",
                           request.method, path, request.headers.get("origin"),
                           request.headers.get("host"), request.headers.get("sec-fetch-site"))
            return _finish(PlainTextResponse("Cross-origin request refused.", status_code=403), path)
    return _finish(await call_next(request), path)
