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


def format_line(path: Path, status: str, reason: tuple) -> str:
    """Render one per-file result line (or two lines for parse errors).

    Paths inside PROJECT_ROOT render relative; paths outside render absolute
    (e.g. tmp_path in tests).
    """
    try:
        rel = path.relative_to(PROJECT_ROOT)
        display = str(rel)
    except ValueError:
        display = str(path)

    marker = "PASS" if status == "pass" else "FAIL"
    kind, payload = reason
    if kind == "counts":
        strings_n, sounds_n = payload
        return f"  {marker}  {display}  (strings={strings_n} sounds={sounds_n})"
    if kind == "empty":
        return f"  {marker}  {display}  empty: 0 strings, 0 sounds"
    exc = payload
    exc_msg = (str(exc).splitlines() or [""])[0]
    return f"  {marker}  {display}\n         {type(exc).__name__}: {exc_msg}"


def main() -> None:
    files = discover_tgl_files()

    print("open_stbc TGL harness")
    print("=" * 50)
    print(f"Found {len(files)} TGL files\n")
    print("Parsing...\n")

    results: list[tuple[Path, str, tuple]] = []
    for path in files:
        status, reason = classify(path)
        results.append((path, status, reason))
        print(format_line(path, status, reason))

    passed = sum(1 for _, s, _ in results if s == "pass")
    failed = len(results) - passed
    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed of {len(results)} total")

    if failed:
        errors: Counter[str] = Counter()
        for _, status, reason in results:
            if status == "fail":
                errors[error_key(status, reason)] += 1
        print(f"\nTop errors ({len(errors)} distinct):")
        for msg, count in errors.most_common(15):
            print(f"  [{count:2d}]  {msg}")


if __name__ == "__main__":
    main()
