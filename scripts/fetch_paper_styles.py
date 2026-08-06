#!/usr/bin/env python3
"""Vendor the official conference LaTeX styles used by AR paper tasks.

Each venue ships its style files somewhere different (a GitHub template repo
for ICLR/COLM, a zip on the conference CDN for NeurIPS/ICML), and none of them
are on CTAN, so AR tasks would otherwise need network access at task-creation
time. Run this once per venue-style refresh:

    python3 scripts/fetch_paper_styles.py            # all venues
    python3 scripts/fetch_paper_styles.py iclr icml  # just these

Files land in ``loom/templates/paper/<venue>/``, next to the section skeleton
that AR copies into each paper task. The skeleton itself is committed by hand
and is not touched here.
"""

from __future__ import annotations

import argparse
import io
import shutil
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = REPO_ROOT / "loom" / "templates" / "paper"

USER_AGENT = "loom-ar-style-fetcher/1.0"

# Per venue: either a list of direct file URLs, or a zip plus the members to
# extract from it (zip layouts nest the files under a directory).
SOURCES: dict[str, dict] = {
    "iclr": {
        "note": "ICLR Master-Template repository",
        "files": [
            "https://raw.githubusercontent.com/ICLR/Master-Template/master/iclr2026/iclr2026_conference.sty",
            "https://raw.githubusercontent.com/ICLR/Master-Template/master/iclr2026/iclr2026_conference.bst",
            "https://raw.githubusercontent.com/ICLR/Master-Template/master/iclr2026/fancyhdr.sty",
            "https://raw.githubusercontent.com/ICLR/Master-Template/master/iclr2026/natbib.sty",
            "https://raw.githubusercontent.com/ICLR/Master-Template/master/iclr2026/math_commands.tex",
        ],
    },
    "colm": {
        "note": "COLM-org/Template repository",
        "files": [
            "https://raw.githubusercontent.com/COLM-org/Template/master/colm2026_conference.sty",
            "https://raw.githubusercontent.com/COLM-org/Template/master/colm2026_conference.bst",
            "https://raw.githubusercontent.com/COLM-org/Template/master/fancyhdr.sty",
            "https://raw.githubusercontent.com/COLM-org/Template/master/natbib.sty",
            "https://raw.githubusercontent.com/COLM-org/Template/master/math_commands.tex",
        ],
    },
    "neurips": {
        "note": "NeurIPS 2025 style bundle",
        "zip": "https://media.neurips.cc/Conferences/NeurIPS2025/Styles.zip",
        "members": [".sty", ".bst"],
    },
    "icml": {
        "note": "ICML 2026 style bundle",
        "zip": "https://media.icml.cc/Conferences/ICML2026/Styles/icml2026.zip",
        "members": [".sty", ".bst"],
    },
}


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def fetch_venue(venue: str) -> int:
    spec = SOURCES[venue]
    dest = TEMPLATES / venue
    dest.mkdir(parents=True, exist_ok=True)
    written = 0

    for url in spec.get("files", []):
        name = url.rsplit("/", 1)[-1]
        try:
            data = _get(url)
        except (urllib.error.URLError, OSError) as exc:
            print(f"  ! {name}: {exc}", file=sys.stderr)
            continue
        (dest / name).write_bytes(data)
        print(f"  + {name} ({len(data)} bytes)")
        written += 1

    zip_url = spec.get("zip")
    if zip_url:
        try:
            blob = _get(zip_url)
        except (urllib.error.URLError, OSError) as exc:
            print(f"  ! {zip_url}: {exc}", file=sys.stderr)
            return written
        wanted = tuple(spec.get("members", []))
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            for info in zf.infolist():
                if info.is_dir() or not info.filename.lower().endswith(wanted):
                    continue
                name = Path(info.filename).name
                if name.startswith("."):
                    continue
                with zf.open(info) as src, (dest / name).open("wb") as out:
                    shutil.copyfileobj(src, out)
                print(f"  + {name} ({info.file_size} bytes)")
                written += 1

    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "venues",
        nargs="*",
        help=f"venues to fetch (default: all of {', '.join(sorted(SOURCES))})",
    )
    args = ap.parse_args()
    venues = args.venues or sorted(SOURCES)
    unknown = [v for v in venues if v not in SOURCES]
    if unknown:
        ap.error(f"unknown venue(s): {', '.join(unknown)}")

    total = 0
    for venue in venues:
        print(f"{venue}: {SOURCES[venue]['note']}")
        total += fetch_venue(venue)
    print(f"\n{total} file(s) written under {TEMPLATES}")
    return 0 if total else 1


if __name__ == "__main__":
    raise SystemExit(main())
