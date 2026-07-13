"""Merge the q13 / q13b dumps out of game/*.cfg (phased + possibly chunked).

The q13 family differs from generic collect.py in three ways:
  1. Section/file names carry a stream suffix the generic tool would not find:
       q13 menu   -> BCProbe_q13_menu
       q13 battle -> BCProbe_q13_battle
       q13b       -> BCProbe_q13b        (method surface, phase-less)
  2. A single logical dump may be split across numbered chunk files
     (BCProbe_q13_menu.cfg, BCProbe_q13_menu_1.cfg, ...) that must be merged in
     NUMERIC chunk order (lexical order puts _10 before _2).
  3. Each dump carries a `total_dump_lines` header invariant; if the merged
     `App.` line count is short, the write TRUNCATED -> we shout COUNT MISMATCH.

Usage:
    uv run python tools/probes/collect_q13.py               # q13 menu + battle
    uv run python tools/probes/collect_q13.py menu          # just one q13 phase
    uv run python tools/probes/collect_q13.py methods       # q13b method surface
"""
import pathlib
import re
import sys

from collect import extract_section          # reuse the exact section parser

PROBES = pathlib.Path(__file__).parent
RESULTS = PROBES / "results"
GAME = PROBES.parent.parent / "game"

# stream -> (cfg/section base, output result filename)
STREAMS = {
    "menu":    ("BCProbe_q13_menu",   "q13_constants_menu.txt"),
    "battle":  ("BCProbe_q13_battle", "q13_constants_battle.txt"),
    "methods": ("BCProbe_q13b",       "q13b_method_surface.txt"),
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
        print(f"  {stream}: no {base}*.cfg in game/ -- stream not run")
        return False

    lines: list[str] = []
    for f in files:
        lines.extend(extract_section(f, base))

    declared = None
    for ln in lines:
        m = re.match(r"total_dump_lines\s*=\s*(\d+)", ln)
        if m:
            declared = int(m.group(1))
            break
    dump_lines = [ln for ln in lines if ln.startswith("App.")]

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / out_name
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rel = out.relative_to(PROBES.parent.parent)
    print(f"  {stream}: wrote {rel}  ({len(lines)} lines, {len(dump_lines)} App.* rows, {len(files)} file(s))")

    if declared is None:
        print(f"  {stream}: WARNING no total_dump_lines header -- cannot verify completeness")
    elif len(dump_lines) < declared:
        print(f"  {stream}: COUNT MISMATCH -- {len(dump_lines)} rows collected but header declares "
              f"{declared}. TRUNCATED; re-run this stream with _CHUNK = 1.")
    else:
        print(f"  {stream}: OK -- {len(dump_lines)}/{declared} rows (complete)")
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
