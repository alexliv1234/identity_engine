"""Canonical JSON serialization.

The determinism guarantee in the spec (§8) is "identical input + versions =>
byte-identical profile JSON". Two things break that: dict key ordering and
float representation noise. This module fixes both.
"""

from __future__ import annotations

import json
from typing import Any

FLOAT_PRECISION = 6


def quantize(value: Any) -> Any:
    """Recursively round floats so equal-in-principle values are equal in bytes."""
    if isinstance(value, float):
        return round(value, FLOAT_PRECISION) + 0.0  # +0.0 normalizes -0.0 to 0.0
    if isinstance(value, dict):
        return {k: quantize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [quantize(v) for v in value]
    return value


def canonical_json(obj: Any) -> str:
    """Serialize with sorted keys, no whitespace, and quantized floats."""
    return json.dumps(
        quantize(obj),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
