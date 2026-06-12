"""
Phase 1 shim for LoadBridge.

In the real game, LoadBridge.Load(bridge_name) loads a bridge NIF model and
registers the resulting SetClass under the name "bridge" in g_kSetManager.
In Phase 1 headless mode we just create an empty SetClass so that
g_kSetManager.GetSet("bridge") returns a valid object rather than None.

We also record the most recent bridge_name argument so the host loop can
swap the renderer's bridge model to match the active mission. Stock BC
mission scripts call LoadBridge.Load("SovereignBridge") or
LoadBridge.Load("GalaxyBridge") during StartMission.
"""
import logging

# Default mirrors the host loop's eagerly-loaded DBridge.
LAST_REQUESTED: str = "GalaxyBridge"

_logger = logging.getLogger(__name__)

_menus_created = False


def _reset_menus_created():
    """Mission-swap hook (reset_sdk_globals) and test reset."""
    global _menus_created
    _menus_created = False


def CreateCharacterMenus(*args, **kwargs):
    """Build the five bridge menus via the real SDK handlers.

    Mirrors sdk/Build/scripts/LoadBridge.py:131-161. Each stage is
    exception-wrapped: a broken menu must not kill mission load
    (logging.exception keeps the traceback); the integration tests assert
    all five built, so gaps stay loud in CI.
    """
    global _menus_created
    if _menus_created:
        return
    import importlib
    import App
    if App.Game_GetCurrentGame() is None:
        # Stock BC never builds bridge menus before a game exists — Load()
        # is called from mission StartMission. The host's eager bridge
        # preload runs pre-game; defer (without latching the flag) to the
        # mission's own Load().
        return
    _menus_created = True

    handler_modules = [
        "Bridge.TacticalMenuHandlers",
        "Bridge.HelmMenuHandlers",
        "Bridge.ScienceMenuHandlers",
        "Bridge.XOMenuHandlers",
        "Bridge.EngineerMenuHandlers",
    ]
    for mod_name in handler_modules:
        try:
            importlib.import_module(mod_name).CreateMenus()
        except Exception:
            _logger.exception("CreateMenus failed for %s", mod_name)

    tcw = App.TacticalControlWindow_GetTacticalControlWindow()

    # Epilogue — mirrors SDK LoadBridge.py:152-161: point the window at the
    # Tactical menu (engine-internal in original BC) and pre-hide it.
    try:
        pDatabase = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
        sTactical = pDatabase.GetString("Tactical")
        pMenu = tcw.FindMenu(sTactical)
        tcw.SetTacticalMenu(pMenu)
        pPane = tcw.GetMenuParentPane(sTactical)
        if pPane is not None:
            pPane.SetNotVisible()
        if pMenu is not None:
            pMenu.SetNotVisible()
        App.g_kLocalizationManager.Unload(pDatabase)
    except Exception:
        _logger.exception("bridge-menu epilogue (Tactical hide) failed")

    try:
        import Tactical.Interface.TacticalControlWindow as _TCW_script
        _TCW_script.SetupBridgeNone()
    except Exception:
        _logger.exception("SetupBridgeNone failed")


def Load(bridge_name: str = ""):
    global LAST_REQUESTED
    if bridge_name:
        LAST_REQUESTED = bridge_name
    import App
    existing = App.g_kSetManager.GetSet("bridge")
    if existing:
        CreateCharacterMenus()
        return existing
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "bridge")
    # Add a placeholder bridge-model object so GetObject("bridge") returns
    # a real ObjectClass with GetAnimNode() rather than None.
    bridge_obj = App.ObjectClass()
    pSet.AddObjectToSet(bridge_obj, "bridge")
    # Match sdk/Build/scripts/LoadBridge.py:183 — every bridge variant
    # registers a baseline ambient so the bridge pass has something to
    # render against. Without this the renderer falls back to its
    # DEFAULT_AMBIENT (typically 0.1) and the interior looks ~black.
    pSet.CreateAmbientLight(1.0, 1.0, 1.0, 1.0, "ambientlight1")
    # Stock BC builds the five bridge menus as part of Load —
    # sdk/Build/scripts/LoadBridge.py:187.
    CreateCharacterMenus()
    return pSet
