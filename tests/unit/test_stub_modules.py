def test_loadspacehelper_create_ship_callable():
    import loadspacehelper
    result = loadspacehelper.CreateShip("Galaxy", None, "player", "Start")
    assert result is not None


def test_loadspacehelper_preload_ship_callable():
    import loadspacehelper
    result = loadspacehelper.PreloadShip("Galaxy", 1)
    assert result is not None


def test_load_bridge_load_callable():
    import LoadBridge
    result = LoadBridge.Load("GalaxyBridge")
    assert result is not None


def test_bridge_helm_menu_handlers_attr_set():
    import Bridge.HelmMenuHandlers
    Bridge.HelmMenuHandlers.g_bShowEnteringBanner = 0
