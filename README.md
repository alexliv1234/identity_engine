# Identity Engine

Turns birth data into layered identity profiles.

## Development

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"    # Windows: .venv\Scripts\pip
.venv/bin/pytest                      # Windows: .venv\Scripts\pytest
```

## Determinism guarantee

Identical input plus identical engine/system versions produce byte-identical
profile JSON. See `engine/canonical.py` for the canonical serialization used
to enforce this (stable key ordering, quantized floats, no timestamps in
serialized bodies).
