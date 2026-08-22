"""The test suite runs as a *development* process.

`api/settings.py` refuses to construct outside `IDENTITY_ENVIRONMENT=development`
when the database URL is unset or SQLite, because a deployment that forgets
IDENTITY_DATABASE_URL creates a SQLite file inside an ephemeral container and
loses every tenant's data on the next deploy, silently. This suite genuinely
does want the SQLite default, so it says so -- here rather than in
`conftest.py`, because `tests/__init__.py` is imported before `tests/conftest.py`
and therefore before `conftest`'s own `from api.main import create_app`, which
builds a `Settings` at import time.

`setdefault`, not assignment: an outer environment that has deliberately set
IDENTITY_ENVIRONMENT (to run the suite against a production-shaped
configuration, say) keeps its value.
"""

import os

os.environ.setdefault("IDENTITY_ENVIRONMENT", "development")
