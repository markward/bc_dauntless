import App


def test_tgframe_surface():
    f = App.TGFrame_Create("lcars", 4300)
    rect = f.GetInnerRect()
    assert rect.GetLeft() == 0.0 and rect.GetTop() == 0.0
    f.SetNiColor(0.2, 0.4, 1.0, 1.0)
    f.SetEdgeStretch(App.TGFrame.NO_STRETCH_LR)
    assert App.TGFrame_Cast(f) is f
    assert App.TGFrame_Cast(object()) is None


def test_sttiled_icon_surface():
    icon = App.STTiledIcon_Create("lcars", 4101, App.NiColorA_BLACK)
    icon.SetTiling(App.STTiledIcon.DIRECTION_X, 10)
    icon.SetTileSize(App.STTiledIcon.DIRECTION_X, 4.0)
    assert App.STTiledIcon_Cast(icon) is icon


def test_numeric_bar_and_fill_gauge():
    from engine.appc.tg_ui.eng_power import STNumericBar, STFillGauge
    bar = STNumericBar()
    bar.SetRange(0.0, 1.25)
    bar.SetValue(0.75)
    assert bar.GetValue() == 0.75
    g = STFillGauge()
    g.SetFillFraction(0.5)
    assert g.GetFillFraction() == 0.5


def test_app_globals_engineering_colors():
    assert App.globals.DEFAULT_ST_INDENT_HORIZ > 0.0
    c = App.globals.g_kEngineeringMainPowerColor
    assert hasattr(c, "r") and hasattr(c, "a")
    assert App.g_kEngineeringMainPowerColor is c
    for name in ("WarpCore", "MainPower", "BackupPower", "Engines", "Shields",
                 "Weapons", "Sensors", "Cloak", "Tractor", "CtrlBkgndLine"):
        assert getattr(App.globals, "g_kEngineering%sColor" % name) is not None
