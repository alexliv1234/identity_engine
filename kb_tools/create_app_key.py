"""Mint an app + API key for local development. Prints the key once.

The plaintext key is never stored: only `sha256(key)` (api.auth.hash_key)
lands in the database. If you lose the printed key, mint a new one.
"""

from __future__ import annotations

import secrets
import sys

from api.auth import generate_key, hash_key
from api.db import SessionLocal, create_all
from api.models import App


def main(name: str = "Local Dev") -> None:
    create_all()
    key = generate_key()
    with SessionLocal() as session:
        session.add(App(id="app_" + secrets.token_hex(8), name=name, api_key_hash=hash_key(key)))
        session.commit()
    print(f"app: {name}\napi key (shown once): {key}")


if __name__ == "__main__":
    main(*(sys.argv[1:2] or ["Local Dev"]))
