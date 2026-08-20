"""One-shot: turn the GeoNames cities15000 extract into a compact vendored CSV.

Source: https://download.geonames.org/export/dump/cities15000.zip  (CC BY 4.0)
Also needs countryInfo.txt for ISO -> country-name mapping.

Run manually, commit the output. NOT part of the request path.

    python kb_tools/build_cities.py ~/Downloads/cities15000.txt \
        ~/Downloads/countryInfo.txt engine/places/data/cities.csv
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

GEONAMES_COLUMNS = {
    "name": 1,
    "asciiname": 2,
    "country": 8,
    "admin1": 10,
    "population": 14,
    "lat": 4,
    "lon": 5,
    "timezone": 17,
}


def load_country_names(path: Path) -> dict[str, str]:
    names: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split("\t")
        names[parts[0]] = parts[4]
    return names


def main(cities_txt: str, country_info: str, out_csv: str) -> None:
    countries = load_country_names(Path(country_info))
    rows = []
    with open(cities_txt, encoding="utf-8") as fh:
        for line in fh:
            p = line.rstrip("\n").split("\t")
            rows.append(
                {
                    "name": p[GEONAMES_COLUMNS["name"]],
                    "ascii": p[GEONAMES_COLUMNS["asciiname"]],
                    "country_code": p[GEONAMES_COLUMNS["country"]],
                    "country_name": countries.get(p[GEONAMES_COLUMNS["country"]], ""),
                    "admin1": p[GEONAMES_COLUMNS["admin1"]],
                    "lat": p[GEONAMES_COLUMNS["lat"]],
                    "lon": p[GEONAMES_COLUMNS["lon"]],
                    "tz": p[GEONAMES_COLUMNS["timezone"]],
                    "population": p[GEONAMES_COLUMNS["population"]],
                }
            )
    # Deterministic file order: population desc, then ascii name, then country.
    rows.sort(key=lambda r: (-int(r["population"] or 0), r["ascii"], r["country_code"]))
    out = Path(out_csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} cities to {out}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
