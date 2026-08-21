"""Meta endpoints — engine/KB version and system registry (spec §5)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.auth import require_app
from api.models import App
from engine import __version__
from engine.kb.version import kb_version
from engine.orchestrator import SYSTEM_REGISTRY

router = APIRouter(tags=["meta"])


@router.get("/meta/versions")
def versions(_app: App = Depends(require_app)) -> dict:
    return {
        "engine": __version__,
        "kb": kb_version(),
        "systems": sorted(SYSTEM_REGISTRY),
    }
