"""Merge the q14 env-census dumps out of game/*.cfg (phased + possibly chunked).

Like collect_q13.py, q14 differs from the generic collect.py:
  1. Section/file names carry a phase suffix:
       q14 menu   -> BCProbe_q14_menu
       q14 battle -> BCProbe_q14_battle
  2. A dump may be split across numbered chunk files
     (BCProbe_q14_menu.cfg, BCProbe_q14_menu_1.cfg, ...) merged in NUMERIC order.
  3. Each dump carries a `data_lines = N` sanity header; if the merged line count
     is short of N, the write TRUNCATED -> COUNT MISMATCH.

Usage:
    uv run python tools/probes/collect_q14.py           # menu + battle
    uv run python tools/probes/collect_q14.py menu      # just one phase
"""
import pathlib
import re
import sys

from collect import extract_section          # reuse the exact section parser

PROBES = pathlib.Path(__file__).parent
RESULTS = PROBES / "results"
GAME = PROBES.parent.parent / "game"

# phase -> (cfg/section base, output result filename)
STREAMS = {
    "menu":   ("BCProbe_q14_menu",   "q14_env_menu.txt"),
    "battle": ("BCProbe_q14_battle", "q14_env_battle.txt"),
}
DEFAULT_STREAMS = ("menu", "battle")


def chunk_index(path: pathlib.Path, base: str) -> int:
    """<base>.cfg -> 0 ; <base>_7.cfg -> 7 ; anything else -> -1 (excluded)."""
    m = re.match(rf"{re.escape(base)}(?:_(\d+))?$", path.stem)
    if not m:
        return -1
    return int(m.group(1)) if m.group(1) else 0


def collect_stream(stream: str) -> bool:
    base, out_name = STREAMS[stream]
    files = [p for p in GAME.glob(f"{base}*.cfg") if chunk_index(p, base) >= 0]
    files.sort(key=lambda p: chunk_index(p, base))
    if not files:
        print(f"  {stream}: no {base}*.cfg in game/ -- phase not run")
        return False

    lines: list[str] = []
    for f in files:
        lines.extend(extract_section(f, base))

    declared = None
    for ln in lines:
        m = re.match(r"data_lines\s*=\s*(\d+)", ln)
        if m:
            declared = int(m.group(1))
            break

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / out_name
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rel = out.relative_to(PROBES.parent.parent)
    print(f"  {stream}: wrote {rel}  ({len(lines)} lines, {len(files)} file(s))")

    if declared is None:
        print(f"  {stream}: WARNING no data_lines header -- cannot verify completeness")
    elif len(lines) < declared:
        print(f"  {stream}: COUNT MISMATCH -- {len(lines)} lines collected but header "
              f"declares {declared} data lines. TRUNCATED; re-run with _CHUNK = 1.")
    else:
        print(f"  {stream}: OK -- {len(lines)} lines (>= {declared} declared)")
    return True


def main() -> None:
    args = sys.argv[1:]
    streams = args if args else DEFAULT_STREAMS
    any_ok = False
    for stream in streams:
        if stream not in STREAMS:
            print(f"unknown stream '{stream}' (expected one of {sorted(STREAMS)})")
            continue
        if collect_stream(stream):
            any_ok = True
    if not any_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
