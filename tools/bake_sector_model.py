"""Bake poc/map.json -> engine/appc/sector_model.json (the sky's galaxy model).

Offline build step. The runtime reads the JSON; the heavy SDK inference lives
in the committed poc/map.json, which this transforms into the minimal schema the
sky projection needs.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IN = ROOT / "poc" / "map.json"
DEFAULT_OUT = ROOT / "engine" / "appc" / "sector_model.json"
_DEFAULT_GALAXY = [120, 120, 140]


def hex_to_rgb01(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]


def build_sector_model(map_data):
    existing = {}
    try:
        for s in json.loads(DEFAULT_OUT.read_text()).get("systems", []):
            if "warp_points" in s:
                existing[s["id"]] = s["warp_points"]
    except (OSError, ValueError):
        pass
    systems = []
    for s in map_data.get("systems", []):
        entry = {"id": s["id"], "position": s["position"]}
        if s["id"] in existing:
            entry["warp_points"] = existing[s["id"]]
        systems.append(entry)
    nebulae = [{"position": n["position"], "radius": n["radius"],
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
