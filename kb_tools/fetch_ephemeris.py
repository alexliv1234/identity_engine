"""One-shot: download the JPL DE406 ephemeris kernel the engine needs.

Design spec §2: no external network calls in the request path. The Skyfield
adapter (`engine/ephemeris/skyfield_adapter.py`) refuses to download the
kernel itself and raises `EphemerisDataMissing` naming this script instead —
so fetching it is a deliberate, human-run setup step, not something that can
happen silently mid-request.

The downloaded (or already-present) file is checked against a pinned size
*and* a pinned SHA-256 — see `EXPECTED_SHA256` for why size alone is not
enough for a file the determinism guarantee rests on.

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

import hashlib
import sys
import urllib.request
from pathlib import Path

KERNEL_URL = "https://ssd.jpl.nasa.gov/ftp/eph/planets/bsp/de406.bsp"
DATA_DIR = Path(__file__).resolve().parent.parent / "engine" / "ephemeris" / "data"
DEST = DATA_DIR / "de406.bsp"

# The file has been stable at this exact size on JPL's server since 2000 (see
# Last-Modified in its HTTP headers). Size alone catches a truncated or
# redirected download, and nothing else.
EXPECTED_SIZE_BYTES = 300_800_000

# The content hash is the check that actually protects the guarantee. A size
# comparison cannot distinguish the right kernel from a substituted one, or
# from a silently re-issued file of the same length — and this kernel is an
# input to *every* chart the engine computes. Two deployments holding
# different 300,800,000-byte kernels would produce different profiles for
# identical input with nothing anywhere noticing, which is exactly the claim
# README.md makes ("identical input plus identical engine/KB versions produce
# byte-identical profile JSON"). That claim is about deployments, not about
# one laptop. The golden suite pins the engine against this kernel; this hash
# is what pins the kernel.
#
# Verified against the working copy at engine/ephemeris/data/de406.bsp on
# 2026-08-21 by streaming it through hashlib.sha256.
EXPECTED_SHA256 = "99399a830f8a1c7eeb0c4e6975f3879f7b0086a093f84d95a84f4b5a55b0e36a"

_CHUNK_SIZE = 1024 * 1024  # 1 MiB


def sha256_of(path: Path) -> str:
    """Streamed SHA-256 — the kernel is ~300 MB and must not be read whole."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mismatch_message(path: Path, actual_size: int, actual_sha: str) -> str:
    """An actionable refusal: what differs, why it matters, what to do."""
    script = Path(__file__).name
    return "\n".join(
        [
            "",
            f"Ephemeris kernel at {path} is NOT the pinned file.",
            f"  expected size:   {EXPECTED_SIZE_BYTES:,} bytes",
            f"  actual size:     {actual_size:,} bytes",
            f"  expected sha256: {EXPECTED_SHA256}",
            f"  actual sha256:   {actual_sha}",
            "",
            "Every planetary position in every profile is read from this file, so a",
            "different kernel silently yields different profiles for identical input.",
            "",
            "To re-fetch the pinned kernel from JPL:",
            f"    .venv/Scripts/python kb_tools/{script} --force     # Windows",
            f"    .venv/bin/python kb_tools/{script} --force          # macOS/Linux",
            "",
            "Do NOT simply edit EXPECTED_SHA256 to match. If you are deliberately",
            "changing kernels, update both constants, regenerate the golden suite",
            "(kb_tools/regenerate_golden.py), and review the diff -- every chart",
            "value in it will move.",
        ]
    )


def main(force: bool = False) -> None:
    if DEST.exists() and not force:
        size = DEST.stat().st_size
        if size == EXPECTED_SIZE_BYTES:
            print(f"{DEST} present ({size:,} bytes); verifying sha256...")
            actual = sha256_of(DEST)
            if actual == EXPECTED_SHA256:
                print(f"sha256 {actual} matches. Nothing to do.")
                return
            # Right size, wrong content — the case a size check cannot see.
            # Refuse loudly instead of overwriting a file someone may have put
            # there deliberately.
            raise SystemExit(_mismatch_message(DEST, size, actual))
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
    actual_sha = sha256_of(tmp_path)
    if actual_size != EXPECTED_SIZE_BYTES or actual_sha != EXPECTED_SHA256:
        message = _mismatch_message(tmp_path, actual_size, actual_sha)
        tmp_path.unlink()
        raise SystemExit(f"{message}\n\nDeleted the failed download; try again.")

    tmp_path.replace(DEST)
    print(f"Done: {DEST} ({actual_size:,} bytes, sha256 {actual_sha}).")


if __name__ == "__main__":
    main(force="--force" in sys.argv[1:])
