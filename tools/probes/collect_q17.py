"""Merge the q17 bridge-graph dumps out of game/*.cfg (scenario-suffixed).

    Scenario A (QuickBattle bridge)  -> BCProbe_q17_A
    Scenario B (E1M1 / mission)      -> BCProbe_q17_B
    unknown                          -> BCProbe_q17_unknown

Usage:
    uv run python tools/probes/collect_q17.py           # A + B
    uv run python tools/probes/collect_q17.py B         # just Scenario B
"""
import pathlib
import re
import sys

from collect import extract_section          # reuse the exact section parser

PROBES = pathlib.Path(__file__).parent
RESULTS = PROBES / "results"
GAME = PROBES.parent.parent / "game"

STREAMS = {
    "A":       ("BCProbe_q17_A",       "q17_bridge_graph_A.txt"),
    "B":       ("BCProbe_q17_B",       "q17_bridge_graph_B.txt"),
    "unknown": ("BCProbe_q17_unknown", "q17_bridge_graph_unknown.txt"),
}
DEFAULT_STREAMS = ("A", "B")


def chunk_index(path: pathlib.Path, base: str) -> int:
    m = re.match(rf"{re.escape(base)}(?:_(\d+))?$", path.stem)
    if not m:
        return -1
    return int(m.group(1)) if m.group(1) else 0


def collect_stream(stream: str) -> bool:
    base, out_name = STREAMS[stream]
    files = [p for p in GAME.glob(f"{base}*.cfg") if chunk_index(p, base) >= 0]
    files.sort(key=lambda p: chunk_index(p, base))
    if not files:
        print(f"  {stream}: no {base}*.cfg in game/ -- scenario not run")
        return False

    lines: list[str] = []
    for f in files:
        lines.extend(extract_section(f, base))

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / out_name
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rel = out.relative_to(PROBES.parent.parent)
    chars = [ln for ln in lines if ln.startswith(("Helm", "Tactical", "Science", "Engineer", "XO"))]
    print(f"  {stream}: wrote {rel}  ({len(lines)} lines, {len(chars)} station rows, {len(files)} file(s))")
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
