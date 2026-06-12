"""TG UI managers — registration sinks with real storage (no stubs).
SDK call shapes from sdk/Build/scripts/Icons/FontsAndIcons.py and
Icons/LCARS_1024.py LoadLCARS_1024."""
from engine.appc.tg_ui.managers import (
    TGFontManager, TGFontGroup, TGIconManager, TGImageManager, TGFocusManager,
)
from engine.appc.tg_ui.widgets import TGIconGroup, TGPane


def test_font_manager_register_and_lookup():
    fm = TGFontManager()
    fm.RegisterFont("Crillee", 12, "Crillee12", "LoadCrillee12")
    handle = fm.GetFont("Crillee", 12)
    assert handle.GetHeight() == 12.0
    # Unknown lookups return a default handle, never None/stub.
    assert fm.GetFont("Nope", 99).GetHeight() == 99.0


def test_icon_manager_create_and_add_group():
    im = TGIconManager()
    g = im.CreateIconGroup("LCARS_1024")
    assert isinstance(g, TGIconGroup)
    im.AddIconGroup(g)
    assert im.GetIconGroup("LCARS_1024") is g
    # Canned 1024x768 screen (matches graphics_mode singleton).
    assert im.GetScreenWidth() == 1024.0
    assert im.GetScreenHeight() == 768.0


def test_focus_manager_holds_reference():
    fm = TGFocusManager()
    p = TGPane()
    fm.SetFocus(p)
    assert fm.GetFocus() is p


def test_image_manager_is_a_sink():
    im = TGImageManager()
    im.RegisterImage("splash", "data/splash.tga")  # must not raise


def test_font_manager_default_font_and_groups():
    fm = TGFontManager()
    fm.SetDefaultFont("LCARSText", 9)
    d = fm.GetDefaultFont()
    assert d.GetFontName() == "LCARSText"
    assert d.GetFontSize() == 9
    g = fm.CreateFontGroup("Crillee", 12)
    assert g.LoadIconTexture("data/fonts/crillee12.tga") == 0
    fm.AddFontGroup(g)
    assert fm.GetFontGroup("Crillee", 12) is g
    # Unknown group lookups return a usable group, never None.
    assert fm.GetFontGroup("Nope", 1).GetFontSize() == 1


def test_focus_manager_tab_order():
    fm = TGFocusManager()
    a, b = TGPane(), TGPane()
    fm.AddObjectToTabOrder(a)
    fm.AddObjectToTabOrder(b)
    fm.AddObjectToTabOrder(a)          # idempotent
    assert fm._tab_order == [a, b]
    fm.RemoveObjectFromTabOrder(a)
    assert fm._tab_order == [b]
    fm.RemoveAllObjectsUnder(TGPane())
    assert fm._tab_order == []


def test_image_detail_default():
    assert TGImageManager().GetImageDetail() == 2


def test_icon_group_screen_dims_are_floats():
    from engine.appc.tg_ui.widgets import TGIconGroup
    g = TGIconGroup("X")
    assert g.GetIconScreenWidth(10) == 0.0
    assert g.GetIconScreenHeight(10) == 0.0


def test_module_singletons_are_right_types():
    from engine.appc.tg_ui import managers as m
    assert isinstance(m.g_kFontManager, TGFontManager)
    assert isinstance(m.g_kIconManager, TGIconManager)
    assert isinstance(m.g_kImageManager, TGImageManager)
    assert isinstance(m.g_kFocusManager, TGFocusManager)
    assert isinstance(m.g_kRootWindow, TGPane)
