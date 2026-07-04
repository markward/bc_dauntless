"""Bake impulse-engine glow regions into engine/appc/hardpoint_overrides.py.

Scaffolding tool: for every hardpoint file (SDK + project-root shadows) it
extracts the impulse engine templates and emits a per-ship override section
whose values reproduce today's runtime behaviour exactly — a cylinder from the
hardpoint position running aft (model -Y) for IMPULSE_CYLINDER_LEN game units,
radius = the hardpoint radius (region centre is omitted: the schema defaults it
to the hardpoint position). The sections are a STARTING POINT for hand-tuning;
this tool never overwrites a ship that already has a section (edit or delete
the section by hand instead).

Pod selection mirrors engine/appc/subsystem_glow.impulse_engines(): the
EngineProperty templates typed EP_IMPULSE are the pods; a ship with none falls
back to its ImpulseEngineProperty aggregator (if any).

Usage:
    uv run python tools/bake_impulse_glow.py          # dry run: report only
    uv run python tools/bake_impulse_glow.py --write  # insert new sections
"""
from __future__ import annotations

import argparse
import importlib
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OVERRIDES_PATH = PROJECT_ROOT / "engine" / "appc" / "hardpoint_overrides.py"
SDK_HARDPOINTS = PROJECT_ROOT / "sdk" / "Build" / "scripts" / "ships" / "Hardpoints"
ROOT_HARDPOINTS = PROJECT_ROOT / "ships" / "Hardpoints"

# Not real ships: galaxy_dauntless_mods is the stock-BC validation copy of
# galaxy.py (see README "Information for modders").
EXCLUDE = {"galaxy_dauntless_mods"}

# The native module lives next to the build tree; needed because importing
# App pulls in engine modules that import _dauntless_host.
sys.path.insert(0, str(PROJECT_ROOT / "build" / "python"))
sys.path.insert(0, str(PROJECT_ROOT))


def hardpoint_leaves() -> list[str]:
    """All hardpoint module leaf names, root shadows included, deduped."""
    leaves = {}
    for d in (SDK_HARDPOINTS, ROOT_HARDPOINTS):
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.py")):
            if f.stem != "__init__" and f.stem not in EXCLUDE:
                leaves.setdefault(f.stem, None)
    return sorted(leaves)


def extract_impulse_pods(mgr, EngineProperty, ImpulseEngineProperty):
    """(name, radius) per impulse pod from the manager's local templates.

    Mirrors subsystem_glow.impulse_engines(): EP_IMPULSE-typed EngineProperty
    templates are the pods; none -> the ImpulseEngineProperty aggregator.
    Radius defaults to 1.0 (subsystem_glow._radius) when unset/zero.
    """
    def radius_of(prop):
        r = prop.GetRadius()
        return round(float(r), 6) if r else 1.0

    pods = [
        (p.GetName(), radius_of(p))
        for p in mgr._local.values()
        if isinstance(p, EngineProperty)
        and p.GetEngineType() == EngineProperty.EP_IMPULSE
    ]
    if pods:
        return pods
    return [
        (p.GetName(), radius_of(p))
        for p in mgr._local.values()
        if isinstance(p, ImpulseEngineProperty)
    ]


def render_section(leaf: str, pods) -> str:
    lines = [
        "",
        "############################################",
        f"# {leaf} — baked impulse glow (tools/bake_impulse_glow.py)",
        "############################################",
        "",
        f"def _{leaf}(find):",
        "    for name, radius in (",
    ]
    for name, radius in pods:
        lines.append(f'        ("{name}", {radius}),')
    lines += [
        "    ):",
        "        p = find(name)",
        "        if p is not None:",
        '            p.SetGlowRegionShape(0, "Cylinder")',
        "            p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)",
        "            p.SetGlowRegionRadius(0, radius)",
        "            p.SetGlowRegionExtent(0, 0.0, 2.0)",
        "",
    ]
    return "\n".join(lines)


def existing_override_leaves(text: str) -> set:
    m = re.search(r"OVERRIDES = \{(.*?)\}", text, re.DOTALL)
    if not m:
        raise SystemExit("OVERRIDES dict not found in hardpoint_overrides.py")
    return set(re.findall(r'"([^"]+)":', m.group(1)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true",
                    help="insert new sections into hardpoint_overrides.py")
    args = ap.parse_args()

    import tools.mission_harness as mh
    mh.setup_sdk()
    import App
    from engine.appc.properties import EngineProperty, ImpulseEngineProperty

    mgr = App.g_kModelPropertyManager
    text = OVERRIDES_PATH.read_text()
    present = existing_override_leaves(text)

    sections, skipped, no_impulse, failed = [], [], [], []
    new_keys = []
    for leaf in hardpoint_leaves():
        if leaf in present:
            skipped.append(leaf)
            continue
        modname = f"ships.Hardpoints.{leaf}"
        mgr.ClearLocalTemplates()
        sys.modules.pop(modname, None)
        try:
            importlib.import_module(modname)
        except Exception as exc:  # noqa: BLE001 - report and move on
            failed.append(f"{leaf}: {type(exc).__name__}: {exc}")
            continue
        pods = extract_impulse_pods(mgr, EngineProperty, ImpulseEngineProperty)
        if not pods:
            no_impulse.append(leaf)
            continue
        sections.append(render_section(leaf, pods))
        new_keys.append(leaf)
    mgr.ClearLocalTemplates()

    print(f"new sections : {len(new_keys)} -> {', '.join(new_keys) or '-'}")
    print(f"already have : {len(skipped)} -> {', '.join(skipped) or '-'}")
    print(f"no impulse   : {len(no_impulse)} -> {', '.join(no_impulse) or '-'}")
    for f in failed:
        print(f"FAILED       : {f}")

    if not args.write:
        print("\ndry run — pass --write to insert the sections")
        return 1 if failed else 0
    if not new_keys:
        print("nothing to write")
        return 1 if failed else 0

    anchor = "\nOVERRIDES = {"
    if anchor not in text:
        raise SystemExit("anchor 'OVERRIDES = {' not found")
    body = "".join(sections)
    entries = "".join(f'    "{leaf}": _{leaf},\n' for leaf in new_keys)
    text = text.replace(anchor, f"\n{body.strip()}\n\n{anchor.strip()}", 1)
    # Append the new keys just before the dict's closing brace.
    m = re.search(r"OVERRIDES = \{.*?\n\}", text, re.DOTALL)
    text = text[: m.end() - 1] + entries + text[m.end() - 1:]
    OVERRIDES_PATH.write_text(text)
    print(f"\nwrote {len(new_keys)} section(s) to {OVERRIDES_PATH}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
