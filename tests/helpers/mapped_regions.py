"""Create REAL, mapped region sets through BC's own region modules.

Plan 1 wraps every mapped Systems.<Sys>.<Region> Initialize() so the map is
applied as BC creates the set; importing the module fresh through the SDK
loader and calling Initialize() is therefore the honest way to get a set that
is mapped exactly as it would be in play.
"""
import importlib
import sys


def load_region(system: str, region: str):
    import App
    import tools.mission_harness as mh
    mh.setup_sdk()
    qual = f"Systems.{system}.{region}"
    sys.modules.pop(qual, None)
    importlib.import_module(qual).Initialize()
    pSet = App.g_kSetManager.GetSet(region)
    assert pSet is not None, f"{qual}.Initialize() registered no set {region!r}"
    return pSet
