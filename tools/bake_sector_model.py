"""Bake poc/map.json -> engine/appc/sector_model.json (the sky's galaxy model).

Offline build step. The runtime reads the JSON; the heavy SDK inference lives
in the committed poc/map.json, which this transforms into the minimal schema the
sky projection needs.
"""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IN = ROOT / "poc" / "map.json"
DEFAULT_OUT = ROOT / "engine" / "appc" / "sector_model.json"
_DEFAULT_GALAXY = [120, 120, 140]

# A hazard nebula is named "{system}-haz{n}" and belongs to that system. The
# system must sit comfortably INSIDE its own hazard nebula so the procedural sky
# envelops (fills the dome) when the player is in that system — otherwise a
# "dust cloud system" like Vesuvi renders its own nebula as a distant patch.
# extract_map.py derives the map radius and the system→nebula offset with
# different scalings (sqrt-compressed radius vs linear offset), which can leave
# the anchor a hair outside (Vesuvi: dist 30.0 vs radius 29.5). Extend the radius
# so the anchor lands at <= this fraction of it.
_HOME_NEBULA_OCCUPANCY = 0.9


def hex_to_rgb01(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]


def _owner_system_id(nebula_id):
    """The system a hazard nebula belongs to, e.g. 'vesuvi-haz0' -> 'vesuvi'.
    Returns None for nebulae that aren't system-owned hazards."""
    if not nebula_id or "-haz" not in nebula_id:
        return None
    return nebula_id.split("-haz", 1)[0]


def _home_envelop_radius(nebula, radius, sys_pos):
    """Extend `radius` so the owning system sits inside this hazard nebula.

    No-op when the nebula has no owning system in the map or the system is
    already comfortably inside; otherwise grows the radius so the anchor lands
    at `_HOME_NEBULA_OCCUPANCY` of it (never shrinks)."""
    owner = _owner_system_id(nebula.get("id"))
    pos = sys_pos.get(owner)
    if pos is None:
        return radius
    p, c = pos, nebula["position"]
    dist = math.sqrt(sum((p[k] - c[k]) ** 2 for k in range(3)))
    return max(radius, round(dist / _HOME_NEBULA_OCCUPANCY, 1))


def build_sector_model(map_data):
    # Back-fill enrichment the runtime added on top of the baked skeleton
    # (warp_points, module, ...). id/position come fresh from map_data; every
    # other key on the existing on-disk entry is preserved so re-baking never
    # silently drops it.
    existing = {}
    try:
        for s in json.loads(DEFAULT_OUT.read_text()).get("systems", []):
            existing[s["id"]] = {k: v for k, v in s.items()
                                 if k not in ("id", "position")}
    except (OSError, ValueError):
        pass
    systems = []
    for s in map_data.get("systems", []):
        entry = {"id": s["id"], "position": s["position"]}
        entry.update(existing.get(s["id"], {}))
        systems.append(entry)
    sys_pos = {s["id"]: s["position"] for s in map_data.get("systems", [])}
    nebulae = [{"position": n["position"],
                "radius": _home_envelop_radius(n, n["radius"], sys_pos),
                "color": hex_to_rgb01(n["color"])}
               for n in map_data.get("nebulae", [])]
    starclouds = []
    for g in map_data.get("galaxies", []):
        mc = (g.get("appearance", {}).get("swatch", {}) or {}).get("meanColor") or _DEFAULT_GALAXY
        starclouds.append({"position": g["position"], "size": g["size"],
                           "color": [c / 255.0 for c in mc]})
    return {"systems": systems, "nebulae": nebulae, "starclouds": starclouds}


def main(in_path=DEFAULT_IN, out_path=DEFAULT_OUT):
    model = build_sector_model(json.loads(Path(in_path).read_text()))
    Path(out_path).write_text(json.dumps(model, indent=2) + "\n")
    print("[bake] %d systems, %d nebulae, %d star-clouds -> %s" % (
        len(model["systems"]), len(model["nebulae"]), len(model["starclouds"]), out_path))
    return model


if __name__ == "__main__":
    main()
