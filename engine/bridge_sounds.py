"""Load the bridge config module's own sounds -- a documented SDK deviation.

"LiftDoor" (sfx/door.wav), the sound every one of BC's 19 LiftDoorAction call sites
names, is loaded ONLY by GalaxyBridge.LoadSounds() / SovereignBridge.LoadSounds() --
and NOTHING in the 1228 SDK files calls them. LoadBridge.Load calls the module's
CreateBridgeModel, ConfigureCharacters and PreloadAnimations, but not LoadSounds;
its UNLOAD path, however, does call UnloadSounds(). So the SDK unloads a sound it
never loads.

Whether BC's native engine calls it, or whether this is a bug in BC's shipped
scripts, is not determinable from the SDK -- and this module does not pretend to
know. What is certain is that without the call, TGSoundAction("LiftDoor") resolves
to nothing and every lift door is silent. GalaxyBridge.LoadSounds() loads exactly
one sound, so restoring the pairing the unload path already assumes costs nothing.
"""
import importlib
import logging

_logger = logging.getLogger(__name__)


def load_bridge_module_sounds(bridge_set) -> bool:
    """Call LoadSounds() on the bridge config module named by the set's config
    (e.g. "GalaxyBridge"). Returns True when a module's LoadSounds() actually ran.
    Best-effort: any failure degrades to False, never raises."""
    if bridge_set is None:
        return False
    try:
        config = str(bridge_set.GetConfig() or "")
    except Exception:
        return False
    if not config:
        return False
    try:
        module = importlib.import_module("Bridge." + config)
        fn = getattr(module, "LoadSounds", None)
        if fn is None:
            return False
        fn()
        return True
    except Exception:
        _logger.debug("bridge LoadSounds failed for %r", config, exc_info=True)
        return False
