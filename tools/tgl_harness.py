"""
TGL parser smoke-test harness for open_stbc.

Discovers every .tgl file under game/data/TGL/ and sdk/Build/Data/TGL/,
parses each via engine.missions.tgl_reader.read_tgl, and reports a
ranked summary of failures (parse errors and empty files).

Usage:
    uv run python tools/tgl_harness.py
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

# Ensure project root is on sys.path whether run as script or imported in tests.
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ROOTS: list[Path] = [
    PROJECT_ROOT / "game" / "data" / "TGL",
    PROJECT_ROOT / "sdk" / "Build" / "Data" / "TGL",
]


def discover_tgl_files() -> list[Path]:
    """Return all .tgl files (case-insensitive) under ROOTS, sorted.

    Missing roots are skipped silently — game/ is a developer-supplied
    install and may not be present in every checkout.
    """
    found: list[Path] = []
    for root in ROOTS:
        if not root.is_dir():
            continue
        found.extend(
            sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".tgl")
        )
    return found


from engine.missions.tgl_reader import read_tgl


def classify(path: Path) -> tuple[str, tuple]:
    """Parse path and classify the result.

    Returns:
        ("pass", ("counts", (strings_n, sounds_n))) on successful, non-empty parse.
        ("fail", ("empty", None)) on successful parse with zero strings AND zero sounds.
        ("fail", ("parse", exc))  on any exception from read_tgl.
    """
    try:
        tgl = read_tgl(path)
    except Exception as exc:
        return ("fail", ("parse", exc))
    if len(tgl.strings) == 0 and len(tgl.sounds) == 0:
        return ("fail", ("empty", None))
    return ("pass", ("counts", (len(tgl.strings), len(tgl.sounds))))


def error_key(status: str, reason: tuple) -> str:
    """Build the Counter grouping key for a failure.

    Only called on failures (status == "fail").
    """
    kind, payload = reason
    if kind == "empty":
        return "empty TGL (0 strings, 0 sounds)"
    exc = payload
    msg = (str(exc).splitlines() or [""])[0]
    return f"{type(exc).__name__}: {msg[:80]}"
