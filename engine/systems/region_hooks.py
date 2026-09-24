"""Apply the system map to a region set the moment BC's region module makes it.

Every path that creates a mapped region set -- warp arrival
(warp.ChangeRenderedSetAction), MissionLib.SetupSpaceSet, a mission calling
Systems.X.Y.Initialize() directly (E7M3 does eight), and system loading --
ends in that region module's Initialize(). So that call is wrapped: BC's body
runs unchanged, then apply_map.apply_to_set. Installed from the SDK loaders'
post-exec hook (engine/appc/sdk_overrides.py), the same place ship-data
overrides are installed.

Not at AddObjectToSet: BC's <Region>_S.py adds a body THEN calls
PlaceObjectByName, which would overwrite a position applied at the add.

Ordering is load-bearing: the map must be applied before anything realizes the
set, because host_loop's planet_natural_scale caches GetRadius() at realize --
applied after, a body is DRAWN at BC's radius and TARGETED at the map's.
check_realized() is the alarm for that: a set whose name resolves to a system
but which apply_to_set never marked.
"""
from __future__ import annotations

_WRAPPED_ATTR = "_dauntless_region_map_wrap"
_FLAG_ATTR = "_system_map_applied"

# Names of mapped-frame sets realized without the map, in order. Test-visible.
unmapped_realized: list = []


def reset() -> None:
    unmapped_realized.clear()


def is_mapped(pSet) -> bool:
    return bool(getattr(pSet, _FLAG_ATTR, False))


def on_region_module_exec(module, qualname: str) -> None:
    """Wrap a just-executed Systems.<System>.<Region> module's Initialize.

    No-op for anything that is not a mapped region module: packages, the
    <Region>_S static modules, helpers like Systems.Utils, and regions no map
    covers (Starbase12, DeepSpace, the multiplayer sets).
    """
    parts = qualname.split(".")
    if len(parts) != 3 or parts[0] != "Systems" or parts[2].endswith("_S"):
        return
    init = getattr(module, "Initialize", None)
    get_name = getattr(module, "GetSetName", None)
    if not callable(init) or not callable(get_name):
        return
    if getattr(init, _WRAPPED_ATTR, False):
        return
    set_name = get_name()
    from engine.systems import resolve
    if resolve.system_of(set_name) is None:
        return

    def Initialize(*args, **kwargs):
        result = init(*args, **kwargs)
        import App
        from engine.systems import apply_map
        pSet = App.g_kSetManager.GetSet(set_name)
        if pSet is not None:
            apply_map.apply_to_set(pSet, set_name)
        return result

    setattr(Initialize, _WRAPPED_ATTR, True)
    module.Initialize = Initialize


def check_realized(pSet) -> bool:
    """False, with one loud line, when a mapped-frame set is realized unmapped."""
    if pSet is None or is_mapped(pSet):
        return True
    from engine.systems import resolve
    name = pSet.GetName()
    if resolve.system_of(name) is None:
        return True
    unmapped_realized.append(name)
    print(f"[systems] ALARM: set {name!r} belongs to a mapped system but was "
          f"realized without the map -- its bodies will draw at BC's radius and "
          f"position. It was created by a path that bypassed its region module's "
          f"Initialize().", flush=True)
    return False
