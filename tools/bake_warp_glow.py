"""Bake warp-nacelle glow regions into engine/appc/hardpoint_overrides.py.

Scaffolding tool, companion to bake_impulse_glow.py. For every hardpoint file
it extracts the warp engine templates and emits per-nacelle cylinder regions
along model +Y (ship-forward), centred on the hardpoint position.

Values are the capsule fit's own no-capture FORMULA FALLBACK — the old runtime
vertex-walk fit cannot be reproduced from hardpoint data alone, so these are a
hand-tuning STARTING POINT, not fit-quality extents:

    radius = kGlowCapsuleRenderRadiusFrac * kGlowCapsuleRadiusWiden * R = 0.375*R
    extent = +/- kGlowCapsuleFallbackHalfLenFactor * kGlowCapsuleRadiusWiden * R
           = +/- 3.125*R          (R = the hardpoint's authored radius)

Pod selection mirrors subsystem_glow.warp_pods(): EP_WARP-typed EngineProperty
templates are the pods; a ship with none falls back to its WarpEngineProperty
aggregator (if any). Ships whose override section already mentions any of the
pod template names are skipped (hand-tuned values survive — e.g. galaxy).

Usage:
    uv run python tools/bake_warp_glow.py          # dry run: report only
    uv run python tools/bake_warp_glow.py --write  # merge into sections
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

# Not real ships: galaxy_dauntless_mods is the stock-BC validation copy.
EXCLUDE = {"galaxy_dauntless_mods"}

RADIUS_FRAC = 0.375   # 0.3 render frac * 1.25 widen
HALF_LEN_FRAC = 3.125  # 2.5 fallback half-len * 1.25 widen

sys.path.insert(0, str(PROJECT_ROOT / "build" / "python"))
sys.path.insert(0, str(PROJECT_ROOT))


def hardpoint_leaves() -> list[str]:
    return sorted(
        f.stem for f in SDK_HARDPOINTS.glob("*.py")
        if f.stem != "__init__" and f.stem not in EXCLUDE
    )


def extract_warp_pods(mgr, EngineProperty, WarpEngineProperty):
    """(name, hardpoint_radius) per warp pod, mirroring warp_pods()."""
    def radius_of(prop):
        r = prop.GetRadius()
        return float(r) if r else 1.0

    pods = [
        (p.GetName(), radius_of(p))
        for p in mgr._local.values()
        if isinstance(p, EngineProperty)
        and p.GetEngineType() == EngineProperty.EP_WARP
    ]
    if pods:
        return pods
    return [
        (p.GetName(), radius_of(p))
        for p in mgr._local.values()
        if isinstance(p, WarpEngineProperty)
    ]


def warp_block(pods, indent="    ") -> str:
    lines = [
        f"{indent}# Warp glow: formula starting point (0.375*R radius,",
        f"{indent}# +/-3.125*R extent; tools/bake_warp_glow.py) -- hand-tune"
        " per nacelle.",
        f"{indent}for name, radius, aft, fore in (",
    ]
    for name, r in pods:
        rad = round(RADIUS_FRAC * r, 4)
        half = round(HALF_LEN_FRAC * r, 4)
        lines.append(f'{indent}    ("{name}", {rad}, {-half}, {half}),')
    lines += [
        f"{indent}):",
        f"{indent}    p = find(name)",
        f"{indent}    if p is not None:",
        f'{indent}        p.SetGlowRegionShape(0, "Cylinder")',
        f"{indent}        p.SetGlowRegionAxis(0, 0.0, 1.0, 0.0)",
        f"{indent}        p.SetGlowRegionRadius(0, radius)",
        f"{indent}        p.SetGlowRegionExtent(0, aft, fore)",
        "",
    ]
    return "\n".join(lines)


def new_section(leaf: str, pods) -> str:
    return "\n".join([
        "",
        "############################################",
        f"# {leaf} — baked warp glow (tools/bake_warp_glow.py)",
        "############################################",
        "",
        f"def _{leaf}(find):",
        warp_block(pods),
    ])


def section_text(text: str, leaf: str) -> str | None:
    """Source of the `_<leaf>` section function, or None if absent."""
    m = re.search(
        rf"^def _{re.escape(leaf)}\(find\):\n(.*?)(?=^def _|\nOVERRIDES = )",
        text, re.DOTALL | re.MULTILINE)
    return m.group(0) if m else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    import tools.mission_harness as mh
    mh.setup_sdk()
    import App
    from engine.appc.properties import EngineProperty, WarpEngineProperty

    mgr = App.g_kModelPropertyManager
    text = OVERRIDES_PATH.read_text()

    merged, created, skipped, no_warp, failed = [], [], [], [], []
    for leaf in hardpoint_leaves():
        modname = f"ships.Hardpoints.{leaf}"
        mgr.ClearLocalTemplates()
        sys.modules.pop(modname, None)
        try:
            importlib.import_module(modname)
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{leaf}: {type(exc).__name__}: {exc}")
            continue
        pods = extract_warp_pods(mgr, EngineProperty, WarpEngineProperty)
        if not pods:
            no_warp.append(leaf)
            continue
        section = section_text(text, leaf)
        if section is not None:
            if any(f'"{name}"' in section for name, _r in pods):
                skipped.append(leaf)   # hand-tuned warp values already present
                continue
            anchor = f"def _{leaf}(find):\n"
            text = text.replace(anchor, anchor + warp_block(pods) + "\n", 1)
            merged.append(leaf)
        else:
            anchor = "\nOVERRIDES = {"
            text = text.replace(
                anchor, f"\n{new_section(leaf, pods).strip()}\n\n{anchor.strip()}", 1)
            m = re.search(r"OVERRIDES = \{.*?\n\}", text, re.DOTALL)
            entry = f'    "{leaf}": _{leaf},\n'
            text = text[: m.end() - 1] + entry + text[m.end() - 1:]
            created.append(leaf)
    mgr.ClearLocalTemplates()

    print(f"merged into existing sections: {len(merged)} -> {', '.join(merged) or '-'}")
    print(f"new sections                 : {len(created)} -> {', '.join(created) or '-'}")
    print(f"skipped (already authored)   : {len(skipped)} -> {', '.join(skipped) or '-'}")
    print(f"no warp                      : {len(no_warp)} -> {', '.join(no_warp) or '-'}")
    for f in failed:
        print(f"FAILED                       : {f}")

    if not args.write:
        print("\ndry run — pass --write to apply")
        return 1 if failed else 0
    OVERRIDES_PATH.write_text(text)
    print(f"\nwrote {len(merged) + len(created)} section change(s) to {OVERRIDES_PATH}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
