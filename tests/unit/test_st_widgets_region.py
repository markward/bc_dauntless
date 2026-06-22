from engine.appc.tg_ui.st_widgets import SortedRegionMenu_CreateW


def test_region_module_retained():
    m = SortedRegionMenu_CreateW("Vesuvi Dust Cloud", "Systems.Vesuvi.Vesuvi4")
    assert m.GetRegionModule() == "Systems.Vesuvi.Vesuvi4"
    assert m._region == "Systems.Vesuvi.Vesuvi4"


def test_region_module_defaults_none():
    m = SortedRegionMenu_CreateW("Some System")
    assert m.GetRegionModule() is None


def test_warp_event_constant_exists():
    import App
    assert isinstance(App.ET_WARP_BUTTON_PRESSED, int)
