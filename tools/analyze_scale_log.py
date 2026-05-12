"""Parse BCScaleLog.cfg produced by tools/scale_logger.py and print a summary.

Usage:
    uv run python tools/analyze_scale_log.py [path-to-BCScaleLog.cfg]

If no path is given, defaults to game/BCScaleLog.cfg (where SaveConfigFile
writes from the game's working directory).

The cfg is the engine's full config dump — many sections. We only read
the `[BCScaleLog]` section appended by the instrumentation snippet.
"""
import pathlib
import re
import sys
from collections import defaultdict


SECTION = "BCScaleLog"


def parse_cfg(path: pathlib.Path) -> dict:
    """Return {key: value_string} for the [BCScaleLog] section. Values stay
    as strings — we coerce at read-time in the summary printer."""
    section_re = re.compile(r"^\[(?P<name>[^\]]+)\]\s*$")
    kv_re      = re.compile(r"^(?P<key>[^=]+?)\s*=\s*(?P<val>.*?)\s*$")
    out: dict = {}
    current = None
    for raw in path.read_text(encoding="latin-1").splitlines():
        m = section_re.match(raw)
        if m:
            current = m.group("name")
            continue
        if current != SECTION:
            continue
        m = kv_re.match(raw)
        if m:
            out[m.group("key")] = m.group("val")
    return out


def group_objects(data: dict) -> list[dict]:
    """Collect obj{N}_* keys into per-object dicts, sorted by index."""
    obj_re = re.compile(r"^obj(?P<idx>\d+)_(?P<field>.+)$")
    rows: dict[int, dict] = defaultdict(dict)
    for k, v in data.items():
        m = obj_re.match(k)
        if not m:
            continue
        rows[int(m.group("idx"))][m.group("field")] = v
    return [rows[i] for i in sorted(rows.keys())]


def coerce_float(s: str | None) -> float | None:
    if s is None:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fmt(v, width: int = 12) -> str:
    if v is None:
        return "-".rjust(width)
    if isinstance(v, float):
        return f"{v:>{width}.4f}"
    return str(v).rjust(width)


def main(argv: list[str]) -> int:
    if len(argv) >= 2:
        cfg_path = pathlib.Path(argv[1])
    else:
        cfg_path = pathlib.Path(__file__).resolve().parent.parent / "game" / "BCScaleLog.cfg"
    if not cfg_path.exists():
        print(f"not found: {cfg_path}", file=sys.stderr)
        print("hint: BCScaleLog.cfg is written into the game's working directory",
              file=sys.stderr)
        return 2

    data = parse_cfg(cfg_path)
    if not data:
        print(f"no [{SECTION}] section in {cfg_path}", file=sys.stderr)
        print("hint: did tools/scale_logger.py get installed and did the game run "
              "with the rendered set live for at least 10 seconds?",
              file=sys.stderr)
        return 1

    dump_id   = data.get("dump_id", "?")
    wall      = data.get("wall",    "?")
    frame     = data.get("frame",   "?")
    set_name  = data.get("set_name", "<no set>")
    n_objects = int(data.get("n_objects", "0") or 0)

    print(f"file:      {cfg_path}")
    print(f"dump_id:   {dump_id}  (>1 confirms multiple captures)")
    print(f"wall:      {wall}s")
    print(f"frame:     {frame}")
    print(f"set:       {set_name}")
    print(f"objects:   {n_objects}")

    cam_present = data.get("cam_present", "0") == "1"
    print()
    print("=== camera ===")
    if not cam_present:
        print("(no active camera)")
    else:
        print(f"  eye:    {data.get('cam_eye', '-')}")
        print(f"  fwd:    {data.get('cam_fwd', '-')}")
        print(f"  up:     {data.get('cam_up',  '-')}")
        near = coerce_float(data.get("cam_near"))
        far  = coerce_float(data.get("cam_far"))
        l    = coerce_float(data.get("cam_left"))
        r    = coerce_float(data.get("cam_right"))
        t    = coerce_float(data.get("cam_top"))
        b    = coerce_float(data.get("cam_bottom"))
        print(f"  near/far: {fmt(near)} {fmt(far)}")
        print(f"  frustum L/R/T/B: {fmt(l)} {fmt(r)} {fmt(t)} {fmt(b)}")

    print()
    print("=== objects ===")
    header = f"{'#':>3}  {'type':<24}  {'name':<28}  {'radius':>10}  {'scale':>10}  {'position':<32}  model"
    print(header)
    print("-" * len(header))
    objs = group_objects(data)
    for i, o in enumerate(objs):
        type_str  = o.get("type",  "")
        name_str  = o.get("name",  "")
        radius    = coerce_float(o.get("radius"))
        scale     = coerce_float(o.get("scale"))
        pos       = o.get("pos",   "")
        model     = o.get("model", "")
        print(f"{i:>3}  {type_str:<24}  {name_str:<28}  {fmt(radius, 10)}  {fmt(scale, 10)}  {pos:<32}  {model}")

    print()
    print("=== by type ===")
    by_type: dict[str, list[dict]] = defaultdict(list)
    for o in objs:
        by_type[o.get("type", "?")].append(o)
    for t, rows in sorted(by_type.items()):
        radii  = [coerce_float(o.get("radius")) for o in rows]
        scales = [coerce_float(o.get("scale"))  for o in rows]
        radii  = [v for v in radii  if v is not None]
        scales = [v for v in scales if v is not None]
        n = len(rows)
        r_summary = f"radius [{min(radii):.2f}..{max(radii):.2f}]" if radii else "radius -"
        s_summary = f"scale  [{min(scales):.4f}..{max(scales):.4f}]" if scales else "scale -"
        print(f"  {t:<24}  count={n:>3}  {r_summary}  {s_summary}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
