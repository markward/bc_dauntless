"""Bake the full Set Course warp-point catalog into sector_model.json.

Offline step. Runs every SDK system's CreateMenus() against an isolated
Helm/Set-Course menu (needs the strict GetSubmenuW fix) and records each
system's warp points. Folds the result into sector_model.json as a
`warp_points` list per system; the sky projection ignores it.

Usage: uv run python tools/bake_set_course_catalog.py
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Ensure project root and the C++ extension are importable when run as a script
# (mirrors tests/conftest.py and tools/gameloop_harness.py).
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_BUILD_PYTHON = ROOT / "build" / "python"
if _BUILD_PYTHON.is_dir() and str(_BUILD_PYTHON) not in sys.path:
    sys.path.insert(0, str(_BUILD_PYTHON))

SYS_DIR = ROOT / "sdk" / "Build" / "scripts" / "Systems"
OUT = ROOT / "engine" / "appc" / "sector_model.json"


def _slug(label):
    return re.sub(r"[^a-z0-9]+", "-", str(label).lower()).strip("-")


def build_catalog():
    """Return {galaxy_system_id: {"module", "warp_points": [{"id","label",
    "module"}, ...]}} for every system."""
    import App  # noqa: F401  (ensures SDK import path + App shim are set up)
    from engine.appc.windows import TacticalControlWindow
    from engine.appc.target_menu import _reset_target_menu_singleton
    from engine.core.game import Game, Episode, Mission, _set_current_game
    from engine.appc.tg_ui.st_widgets import SortedRegionMenu
    from engine.appc.sector_model import system_id_for_set

    TacticalControlWindow._instance = None
    _reset_target_menu_singleton()
    g = Game(); e = Episode(); m = Mission()
    e.SetCurrentMission(m); g.SetCurrentEpisode(e)
    _set_current_game(g)
    sys.modules.pop("Bridge.HelmMenuHandlers", None)
    sys.modules.pop("HelmMenuHandlers", None)
    import Bridge.HelmMenuHandlers as helm
    helm.CreateMenus()

    # CreateMenus is NOT always in Systems/<Dir>/<Dir>.py. Three systems keep
    # it elsewhere — DryDock in DryDockSystem.py, Starbase12 in Starbase.py,
    # QuickBattle in QuickBattleSystem.py — so importing only the canonical
    # module silently skipped them. Two of those (DryDock, Starbase12) fold
    # into Tau Ceti, which is why it baked with NO destinations and the E1M1
    # objective "head to Starbase 12" had nowhere to set course to.
    #
    # Scan every module in the directory instead, and call CreateMenus on the
    # first holder, preferring the canonical file. First-only, not all: a
    # system defining it twice would otherwise register duplicate menu nodes.
    names = sorted(d for d in os.listdir(SYS_DIR) if (SYS_DIR / d).is_dir())
    failed = {}
    for n in names:
        holders = sorted(
            (f.stem for f in (SYS_DIR / n).glob("*.py")
             if f.stem != "__init__"
             and re.search(r"^def CreateMenus", f.read_text(errors="ignore"),
                           re.M)),
            key=lambda stem: (stem != n, stem),   # canonical <Dir>.py first
        )
        if not holders:
            continue
        try:
            mod = __import__("Systems.%s.%s" % (n, holders[0]),
                             fromlist=[holders[0]])
            mod.CreateMenus()
        except Exception as exc:                       # noqa: BLE001
            failed[n] = "%s: %s" % (type(exc).__name__, str(exc)[:80])

    helm_menu = TacticalControlWindow.GetInstance().GetMenuList()[0]
    sc = next((c for c in helm_menu._children
               if isinstance(c, SortedRegionMenu)), None)
    catalog, unmatched = {}, []
    model_ids = {s["id"] for s in
                 __import__("engine.appc.sector_model", fromlist=["x"])
                 .load_sector_model().get("systems", [])}
    if sc is not None:
        for node in sc._children:
            sid = system_id_for_set(node.GetLabel())
            if sid not in model_ids:
                unmatched.append((node.GetLabel(), sid))
            wps = [{"id": _slug(c.GetLabel()), "label": c.GetLabel(),
                    "module": getattr(c, "GetRegionModule", lambda: None)()}
                   for c in getattr(node, "_children", [])]
            entry = catalog.setdefault(
                sid, {"module": None, "warp_points": [], "_self_rows": []})
            entry["warp_points"].extend(wps)
            # A system node's own region. For a single-region system like Riha
            # this is the system's self-row destination. But SEVERAL menu nodes
            # can fold onto one model id — Tau Ceti gets both "Dry Dock" and
            # "Starbase 12" — and keeping only the first silently lost the
            # other. Collect them all and decide below.
            node_mod = getattr(node, "GetRegionModule", lambda: None)()
            if node_mod is not None:
                entry["_self_rows"].append((node.GetLabel(), node_mod))

    for sid, entry in catalog.items():
        rows = entry.pop("_self_rows", [])
        if len(rows) == 1:
            # One menu node: its own region is the system's module, exactly as
            # before. Single-region systems like Riha use it as their self-row
            # destination; systems with sub-regions carry it harmlessly.
            entry["module"] = rows[0][1]
        elif len(rows) > 1:
            # Multiple real destinations folded under one map system: each
            # becomes a selectable warp point. `module` stays None so nothing
            # downstream silently picks one of them as "the" destination.
            entry["warp_points"].extend(
                {"id": _slug(label), "label": label, "module": mod}
                for label, mod in rows)
    _set_current_game(None)
    if failed:
        print("[catalog] %d systems failed: %s" % (len(failed), failed))
    if unmatched:
        print("[catalog] %d unmatched system ids (add overrides): %s"
              % (len(unmatched), unmatched))
    print("[catalog] %d systems, %d warp points"
          % (len(catalog),
             sum(len(v["warp_points"]) for v in catalog.values())))
    return catalog


def fold_into_model(catalog, out_path=OUT):
    model = json.loads(Path(out_path).read_text())
    for s in model.get("systems", []):
        entry = catalog.get(s["id"])
        if entry is not None:
            s["warp_points"] = entry["warp_points"]
            s["module"] = entry["module"]
    Path(out_path).write_text(json.dumps(model, indent=2) + "\n")
    return model


def main():
    # When run as a script (not via pytest) the SDK finder + stubs that
    # pytest's conftest.py normally provides are absent.  Install them now.
    if not any(type(f).__name__ == "_SDKFinder" for f in sys.meta_path):
        import tools.mission_harness as _mh
        _mh.setup_sdk()
    fold_into_model(build_catalog())


if __name__ == "__main__":
    main()
