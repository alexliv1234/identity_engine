"""FastAPI application factory — the shell every router plugs into.

Two things are deliberately checked at startup rather than left to surface on
the first request (Plan 3 review, task-2 corrections 2 & 3):

1. **The ephemeris.** `engine.ephemeris.get_ephemeris()` is lazy and
   `skyfield` is not even imported until something calls it. A container
   built without running `kb_tools/fetch_ephemeris.py` would otherwise boot
   healthy, pass `/health`, and only raise `EphemerisDataMissing` on the
   first customer chart request. `create_app()` forces that construction
   during startup so a misconfigured deploy fails at boot with the adapter's
   actionable message instead.

2. **The Postgres driver.** `psycopg[binary]` is an optional `postgres`
   extra (Task 1). If `IDENTITY_DATABASE_URL` points at `postgresql://` and
   the driver is not importable, a prod deploy without the extra would
   otherwise boot healthy and fail on the first query. `create_app()` checks
   this eagerly and names the fix.

Both checks are opt-out for tests via `create_app(eager_ephemeris=...)` — see
that parameter's docstring below for why an *unconditional* eager load would
make the test suite fragile rather than correct.

Task-2 review, finding 1: the ephemeris guard has a legitimate opt-out
(`eager_ephemeris=False`, used by tests) and an illegitimate one (an operator
setting `IDENTITY_EAGER_EPHEMERIS_LOAD=false` in production to silence a
failing deploy). Both reach `create_app` as "don't load eagerly", but only the
first is supposed to happen quietly. `create_app` distinguishes them by
*how* eager-loading was turned off: an explicit `eager_ephemeris=False`
argument is the caller (tests) opting out on purpose, so it stays silent;
`eager_ephemeris=None` falling through to a `Settings.eager_ephemeris_load`
that is `False` can only mean the environment variable was set, since the
field's own default is `True` — that path logs a loud startup warning naming
exactly what stopped being checked.
"""

from __future__ import annotations

import importlib.util
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI

from api.db import create_all
from api.errors import install_handlers
from api.settings import get_settings

logger = logging.getLogger(__name__)

_EAGER_EPHEMERIS_DISABLED_WARNING = (
    "IDENTITY_EAGER_EPHEMERIS_LOAD=false: the ephemeris will NOT be validated "
    "at startup. A missing or misconfigured kernel file will boot healthy, "
    "pass /health, and only surface as EphemerisDataMissing on a customer's "
    "first chart-touching request instead of failing this deploy at boot. "
    "This flag is meant for tests; if this is a production deploy, unset it."
)


class PostgresDriverMissing(RuntimeError):
    """Raised at startup when `IDENTITY_DATABASE_URL` is a `postgresql://`
    URL but the `psycopg` driver is not importable."""


def _psycopg_importable() -> bool:
    return importlib.util.find_spec("psycopg") is not None


def _check_postgres_driver(database_url: str) -> None:
    if not urlsplit(database_url).scheme.startswith("postgresql"):
        return
    if not _psycopg_importable():
        raise PostgresDriverMissing(
            "IDENTITY_DATABASE_URL is a postgresql:// URL but the psycopg driver "
            "is not installed. Run `pip install .[postgres]`."
        )


def create_app(*, eager_ephemeris: bool | None = None) -> FastAPI:
    """Build the application.

    `eager_ephemeris` overrides `Settings.eager_ephemeris_load` (default
    `True`) for this instance. It exists because an *unconditional* eager
    load at startup would make the request test suite pay the skyfield
    kernel-load cost on every `client` fixture instantiation (or, in a CI
    image without the kernel file, fail every API test outright — even ones
    like auth and error-shape tests that never touch profile computation).
    `tests/conftest.py`'s `client` fixture passes `eager_ephemeris=False` for
    exactly that reason; production leaves this `None` and gets the real
    startup guard from correction 2.

    That argument is also how a deliberate test opt-out is told apart from an
    operator quietly defeating the guard via the environment: see the module
    docstring's "Task-2 review, finding 1" note. Only the latter path logs.
    """
    settings = get_settings()
    disabled_via_environment = eager_ephemeris is None and not settings.eager_ephemeris_load
    should_load_ephemeris = (
        settings.eager_ephemeris_load if eager_ephemeris is None else eager_ephemeris
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        create_all()
        _check_postgres_driver(settings.database_url)
        if should_load_ephemeris:
            from engine.ephemeris import get_ephemeris  # noqa: PLC0415

            get_ephemeris()
        elif disabled_via_environment:
            logger.warning(_EAGER_EPHEMERIS_DISABLED_WARNING)
        yield

    app = FastAPI(
        title="Identity Engine",
        version="1.0.0",
        description=(
            "Layered identity profiles from birth data. Reflective and "
            "entertainment insight; not medical, psychological, or financial advice."
        ),
        lifespan=lifespan,
    )
    install_handlers(app)

    from api.routers import compatibility, context, meta, persons, timing  # noqa: PLC0415

    for router in (
        persons.router,
        context.router,
        compatibility.router,
        timing.router,
        meta.router,
    ):
        app.include_router(router, prefix="/v1")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    if settings.playground_enabled:
        from fastapi.staticfiles import StaticFiles  # noqa: PLC0415

        playground = Path(__file__).resolve().parents[1] / "playground"
        if playground.exists():
            app.mount(
                "/playground", StaticFiles(directory=playground, html=True), name="playground"
            )

    return app


app = create_app()
