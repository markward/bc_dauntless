def test_loadspacehelper_create_ship_callable():
    import loadspacehelper
    result = loadspacehelper.CreateShip("Galaxy", None, "player", "Start")
    assert result is not None


def test_loadspacehelper_preload_ship_callable():
    import loadspacehelper
    # PreloadShip is a void procedure; it should not raise
    loadspacehelper.PreloadShip("Galaxy", 1)


def test_load_bridge_load_callable():
    import App
    import LoadBridge
    from engine.appc.windows import TacticalControlWindow
    from engine.appc.tg_ui import st_widgets
    try:
        result = LoadBridge.Load("GalaxyBridge")
        assert result is not None
    finally:
        App.g_kEventManager._broadcast_handlers.clear()
        if hasattr(App.g_kEventManager, "_method_handlers"):
            App.g_kEventManager._method_handlers.clear()
        LoadBridge._reset_menus_created()
        TacticalControlWindow._instance = None
        st_widgets._reset_module_state()


def test_bridge_helm_menu_handlers_attr_set():
    import Bridge.HelmMenuHandlers
    Bridge.HelmMenuHandlers.g_bShowEnteringBanner = 0
