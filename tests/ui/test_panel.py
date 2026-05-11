from engine.ui import UiPanel, UiButton, UiCollapsibleList, bindings


def test_panel_creates_panel_in_dom(fake_dom):
    panel = UiPanel(id="targets", anchor="top-right",
                    width_vw=20.0, height_vh=60.0)
    assert fake_dom.panel_root(panel.panel_id) is not None


def test_panel_button_factory_attaches_to_root(fake_dom):
    panel = UiPanel(id="targets")
    b = panel.button("Loose Button")
    assert isinstance(b, UiButton)
    assert b.element_id in fake_dom.children(fake_dom.panel_root(panel.panel_id))


def test_panel_collapsible_factory_attaches_to_root(fake_dom):
    panel = UiPanel(id="targets")
    c = panel.collapsible("Bird of Prey-1", affiliation="enemy")
    assert isinstance(c, UiCollapsibleList)
    root_children = fake_dom.children(fake_dom.panel_root(panel.panel_id))
    # The collapsible adds a wrapper to root
    assert len(root_children) == 1
    assert "bc-collapsible" in fake_dom.element(root_children[0]).classes


def test_panel_buttons_share_radio_group(fake_dom):
    panel = UiPanel(id="p")
    a = panel.button("A"); b = panel.button("B")
    fake_dom.fire_click(a.element_id)
    assert a.selected and not b.selected
    fake_dom.fire_click(b.element_id)
    assert b.selected and not a.selected


def test_panel_clear_removes_children(fake_dom):
    panel = UiPanel(id="p")
    panel.button("A"); panel.collapsible("B", affiliation="enemy")
    root = fake_dom.panel_root(panel.panel_id)
    assert len(fake_dom.children(root)) == 2
    panel.clear()
    assert fake_dom.children(root) == []


def test_panel_destroy_destroys_panel(fake_dom):
    panel = UiPanel(id="p")
    pid = panel.panel_id
    panel.destroy()
    import pytest
    with pytest.raises(KeyError):
        fake_dom.panel_root(pid)
