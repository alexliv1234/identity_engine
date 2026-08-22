"""Bearer API-key authentication (spec §5.3).

Keys are never stored or logged in plaintext: only `sha256(key)` hex lives in
`App.api_key_hash`. The plaintext is generated once, shown once (by
`kb_tools/create_app_key.py`), and never recoverable afterwards.
"""

from __future__ import annotations

import hashlib
import secrets

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from api.db import get_session
from api.models import App
from engine.errors import EngineError, ErrorCode


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def generate_key() -> str:
    return "sk_" + secrets.token_hex(24)


def require_app(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> App:
    """FastAPI dependency guarding every `/v1` route.

    A missing header, a malformed header, and a valid-format-but-unknown key
    all raise the exact same `EngineError` — same code, same message. Callers
    must not be able to distinguish "you forgot the header" from "that key
    doesn't exist" from the response; either is a hint an attacker can use to
    enumerate valid keys.
    """
    unauthorized = EngineError(ErrorCode.UNAUTHORIZED, "invalid or missing api key")

    if not authorization or not authorization.startswith("Bearer "):
        raise unauthorized

    key = authorization.removeprefix("Bearer ").strip()
    if not key:
        raise unauthorized

    app_row = session.query(App).filter_by(api_key_hash=hash_key(key)).one_or_none()
    if app_row is None:
        raise unauthorized

    return app_row
