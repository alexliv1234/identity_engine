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

## Offline place lookup

`engine/places/lookup.py` resolves city names to lat/lon/timezone with no
network call, ever. City data © GeoNames (https://www.geonames.org), CC BY 4.0.

Known limitation: `engine/places/data/cities.csv` currently ships as a
curated seed (~94 hand-verified cities) rather than the full GeoNames
`cities15000` extract, since building the full set requires a manual
download (see `kb_tools/build_cities.py`). Running
`python kb_tools/build_cities.py <cities15000.txt> <countryInfo.txt> engine/places/data/cities.csv`
against a real GeoNames extract replaces the seed with the full dataset.
