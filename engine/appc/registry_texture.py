# engine/appc/registry_texture.py
"""BC Federation registry / hull-name texture swaps -> per-registry model variant.

BC's `ObjectClass.ReplaceTexture(new_path, old_name)` swaps one texture on a
loaded ship model so a Federation hull renders a named registry ("Dauntless",
"Venture", "Sovereign", ...). `old_name` ("ID") is matched against the NIF's
embedded texture basenames — the Galaxy carries `Ent-D_topdish_ID_glow.tga`, the
Sovereign `Ent-E-dishtopbottomID_glow.tga` — and `new_path` is a game/-relative
`.tga` (e.g. `Data/Models/SharedTextures/FedShips/Dauntless.tga`). The SDK calls
this in ~60 places: `MissionLib.py` (the player ship-change path, per Federation
class) and every campaign mission for named NPC hulls.

Our renderer BAKES the swap into the Model at load time (a per-registry variant,
distinct in the native asset cache — `native/src/assets/src/model_build.cc`
`apply_texture_replacements`). So the request must be known BEFORE the ship's
render instance is built. But `ReplaceTexture` is called during a mission's
`Initialize` / QuickBattle setup, before the set's instances are realized. So we
QUEUE each request per ship and hand it to `load_model` when the loader builds
the instance — the same deferred pattern as `engine.appc.visible_damage`.

`ObjectClass.ReplaceTexture` (engine/appc/objects.py) routes here; the two ship
build loops in `engine/host_loop.py` drain via `replacements_for`. See CLAUDE.md
(the Galaxy `Ent-D_topdish_ID_glow.tga` -> `Dauntless.tga` example).
"""
from typing import List, Optional, Tuple

# id(ship) -> {"ship": ship, "reps": [(old_name, new_texture), ...]}. Keyed by
# id() (not the ship object) so nothing depends on ObjectClass being hashable,
# mirroring visible_damage's identity handling. Cleared on mission swap / test
# teardown via reset().
_pending: dict = {}

# BC's per-Federation-class default registry, verbatim from MissionLib.py:591-599
# (the ship-change path's "give it a default NCC" block). Keyed by ship class
# (the `ships.<Class>` script's leaf name). Paths are game/-relative, matching
# the SDK's ReplaceTexture arguments; `old_name` is always "ID".
DEFAULT_REGISTRY_BY_CLASS = {
    "Galaxy":     "Data/Models/SharedTextures/FedShips/Dauntless.tga",
    "Sovereign":  "Data/Models/Ships/Sovereign/Sovereign.tga",
    "Nebula":     "Data/Models/SharedTextures/FedShips/Berkeley.tga",
    "Akira":      "Data/Models/Ships/Akira/Geronimo.tga",
    "Ambassador": "Data/Models/Ships/Ambassador/Zhukov.tga",
}

# BC's ReplaceTexture old-name for every Federation registry swap.
REGISTRY_OLD_NAME = "ID"


def queue_replace(ship, new_path: str, old_name: str = REGISTRY_OLD_NAME) -> None:
    """Record a BC ReplaceTexture(new_path, old_name) request for `ship`.

    `new_path` is stored verbatim (the SDK's game/-relative path, e.g.
    "Data/Models/SharedTextures/FedShips/Dauntless.tga"). The native loader
    resolves it by BASENAME against the ship's texture search dirs — which
    include the per-ship + shared High/ LOD dirs — so the omitted LOD subdir in
    BC's paths (the file is really in FedShips/High/) resolves correctly, and no
    game/ install is needed here for the queue itself.

    Last-write-wins per `old_name` (a second swap of the same slot replaces the
    first), matching BC where the final ReplaceTexture call is the one baked in.
    """
    if ship is None:
        return
    new_tex = str(new_path)
    entry = _pending.setdefault(id(ship), {"ship": ship, "reps": []})
    reps = entry["reps"]
    for i, (old, _tex) in enumerate(reps):
        if old == old_name:
            reps[i] = (old_name, new_tex)
            return
    reps.append((old_name, new_tex))


def replacements_for(ship) -> List[Tuple[str, str]]:
    """Return `[(old_name, new_texture), ...]` for `ship` (empty if none). The
    list shape is exactly what `renderer.load_model(..., texture_replacements=)`
    and the native binding expect."""
    if ship is None:
        return []
    entry = _pending.get(id(ship))
    return list(entry["reps"]) if entry else []


def has_replacements(ship) -> bool:
    entry = _pending.get(id(ship))
    return bool(entry and entry["reps"])


def clear_for(ship) -> None:
    """Drop a ship's queued replacements."""
    if ship is not None:
        _pending.pop(id(ship), None)


def reset() -> None:
    """Clear the registry (mission swap / test teardown)."""
    _pending.clear()


def _class_of(ship) -> Optional[str]:
    """The ship's class leaf name ("Galaxy") from its `ships.<Class>` script,
    or None."""
    try:
        script = ship.GetScript()
    except Exception:
        return None
    if not script:
        return None
    return str(script).rsplit(".", 1)[-1]


def apply_class_default(ship) -> bool:
    """Apply the Federation class-default registry (BC's MissionLib "default NCC")
    to `ship`, if its class has one. Routes through `ship.ReplaceTexture` so it
    flows the same deferred path as SDK calls. Returns True if a default applied.
    """
    cls = _class_of(ship)
    if cls is None:
        return False
    rel = DEFAULT_REGISTRY_BY_CLASS.get(cls)
    if rel is None:
        return False
    try:
        ship.ReplaceTexture(rel, REGISTRY_OLD_NAME)
    except Exception:
        return False
    return True
