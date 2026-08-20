"""One-shot: download the JPL DE406 ephemeris kernel the engine needs.

Design spec §2: no external network calls in the request path. The Skyfield
adapter (`engine/ephemeris/skyfield_adapter.py`) refuses to download the
kernel itself and raises `EphemerisDataMissing` naming this script instead —
so fetching it is a deliberate, human-run setup step, not something that can
happen silently mid-request.

Source: https://ssd.jpl.nasa.gov/ftp/eph/planets/bsp/de406.bsp (public domain,
NASA/JPL). de406.bsp was chosen over the newer, smaller de440s.bsp because
de440s.bsp starts 1849-12-26 and this project's birth-date floor is
1800-01-01; de406.bsp covers -3000 to +3000 and is the smallest full-range
kernel JPL publishes. ~300 MB; this will take a while on a slow connection.

Run manually, once, from the repo root:

    .venv/Scripts/python kb_tools/fetch_ephemeris.py     # Windows
    .venv/bin/python kb_tools/fetch_ephemeris.py          # macOS/Linux

Not part of the request path. Not run automatically by any test or import.
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

KERNEL_URL = "https://ssd.jpl.nasa.gov/ftp/eph/planets/bsp/de406.bsp"
DATA_DIR = Path(__file__).resolve().parent.parent / "engine" / "ephemeris" / "data"
DEST = DATA_DIR / "de406.bsp"

# The file has been stable at this exact size on JPL's server since 2000
# (see Last-Modified in its HTTP headers); check it as a basic integrity
# guard against a truncated or redirected download.
EXPECTED_SIZE_BYTES = 300_800_000

_CHUNK_SIZE = 1024 * 1024  # 1 MiB


def main(force: bool = False) -> None:
    if DEST.exists() and not force:
        size = DEST.stat().st_size
        if size == EXPECTED_SIZE_BYTES:
            print(f"{DEST} already present ({size:,} bytes). Nothing to do.")
            return
        print(f"{DEST} exists but is {size:,} bytes, not {EXPECTED_SIZE_BYTES:,}. Re-downloading.")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = DEST.with_suffix(".bsp.partial")

    print(f"Downloading {KERNEL_URL}")
    print(f"  -> {DEST}  (~{EXPECTED_SIZE_BYTES / 1_000_000:.0f} MB, this takes a while)")

    with urllib.request.urlopen(KERNEL_URL) as response, tmp_path.open("wb") as out_file:
        total_reported = response.length or EXPECTED_SIZE_BYTES
        downloaded = 0
        last_percent_printed = -1
        while True:
            chunk = response.read(_CHUNK_SIZE)
            if not chunk:
                break
            out_file.write(chunk)
            downloaded += len(chunk)
            percent = int(downloaded * 100 / total_reported)
            if percent != last_percent_printed:
                print(f"\r  {percent:3d}%  ({downloaded:,} / {total_reported:,} bytes)", end="")
                last_percent_printed = percent
    print()

    actual_size = tmp_path.stat().st_size
    if actual_size != EXPECTED_SIZE_BYTES:
        tmp_path.unlink()
        raise SystemExit(
            f"Downloaded file is {actual_size:,} bytes, expected "
            f"{EXPECTED_SIZE_BYTES:,}. Deleted the partial download; try again."
        )

    tmp_path.replace(DEST)
    print(f"Done: {DEST} ({actual_size:,} bytes).")


if __name__ == "__main__":
    main(force="--force" in sys.argv[1:])
