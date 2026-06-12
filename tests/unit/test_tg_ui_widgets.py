"""Core TG widget tree — headless state holders, no rendering.
Spec: docs/superpowers/specs/2026-06-12-tg-widget-tree-crew-menus-design.md
"""
from engine.appc.tg_ui.widgets import (
    TGPane, TGPane_Create, TGPane_Cast,
    TGIcon, TGIcon_Create, TGIcon_Cast,
    TGParagraph, TGParagraph_Create, TGParagraph_CreateW, TGParagraph_Cast,
    TGIconGroup,
    ensure_widget_id,
)


def test_pane_hierarchy_and_stored_xy():
    parent = TGPane_Create(0.5, 0.04)
    child = TGIcon_Create("LCARS_1024", 120)
    parent.AddChild(child, 0.25, 0.1, 0)
    assert parent.GetChildren() == [(child, 0.25, 0.1)]


def test_pane_visibility_and_enabled_flags():
    p = TGPane_Create()
    assert p.IsVisible() == 1
    p.SetNotVisible()
    assert p.IsVisible() == 0
    p.SetDisabled()
    assert p.IsEnabled() == 0
    p.SetEnabled()
    assert p.IsEnabled() == 1


def test_paragraph_holds_text():
    para = TGParagraph_CreateW("Mission Objectives", 1.0, None)
    assert para.GetText() == "Mission Objectives"
    para.SetText("Updated")
    assert para.GetText() == "Updated"


def test_icon_group_records_atlas_locations():
    g = TGIconGroup("LCARS_1024")
    tex = g.LoadIconTexture("Data/Icons/Bridge/RadarBorder.tga")
    g.SetIconLocation(10, tex, 0, 0, 73, 73)
    g.SetIconLocation(
        20, tex, 0, 0, 73, 73,
        TGIconGroup.ROTATE_0, TGIconGroup.MIRROR_HORIZONTAL,
    )
    assert g.GetIconLocation(10) == (tex, 0, 0, 73, 73,
                                     TGIconGroup.ROTATE_0,
                                     TGIconGroup.MIRROR_NONE)
    assert g.GetIconLocation(20)[6] == TGIconGroup.MIRROR_HORIZONTAL


def test_casts_are_lenient_and_reject_non_widgets():
    p = TGPane_Create()
    assert TGPane_Cast(p) is p
    assert TGPane_Cast(None) is None
    assert TGIcon_Cast(p) is None
    assert TGParagraph_Cast(p) is None


def test_widget_ids_monotonic_and_stable():
    a, b = TGPane_Create(), TGPane_Create()
    ida, idb = ensure_widget_id(a), ensure_widget_id(b)
    assert ida != idb
    assert ensure_widget_id(a) == ida  # stable on re-ask


def test_pane_inherits_event_handler_registration():
    from engine.appc.events import TGEventHandlerObject
    assert isinstance(TGPane_Create(), TGEventHandlerObject)
