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


def test_panel_sets_initial_css_vars_from_theme(fake_dom):
    panel = UiPanel(id="p")
    vars_ = fake_dom.panel_css_vars(panel.panel_id)
    # Affiliation defaults present
    assert vars_["--aff-enemy-color"]    == "rgb(216,43,43)"
    assert vars_["--aff-friendly-color"] == "rgb(80,112,230)"
    # Menu-level 3 defaults present
    assert vars_["--menu-3-normal"]      == "rgb(207,96,159)"
    assert vars_["--menu-3-highlighted"] == "rgb(246,147,204)"
    assert vars_["--menu-3-selected"]    == "rgb(103,48,79)"


def test_theme_change_after_panel_creation_repushes_vars(fake_dom):
    from engine.ui import theme
    panel = UiPanel(id="p")
    theme.set_affiliation("enemy", (1, 2, 3))
    try:
        # Caller pushes — there's no auto-watch
        panel.refresh_theme()
        assert fake_dom.panel_css_vars(panel.panel_id)["--aff-enemy-color"] \
            == "rgb(1,2,3)"
    finally:
        theme.reset_affiliations()


# ── Panel header (title + collapsible toggle) ───────────────────────────────


def test_panel_without_title_or_collapsible_has_no_header(fake_dom):
    panel = UiPanel(id="p")
    root_children = fake_dom.children(fake_dom.panel_root(panel.panel_id))
    # No header div should be created
    assert not any(
        "bc-panel-header" in fake_dom.element(c).classes for c in root_children)


def test_panel_with_title_renders_title_text(fake_dom):
    panel = UiPanel(id="p", title="Targets")
    root_children = fake_dom.children(fake_dom.panel_root(panel.panel_id))
    # Children: [header, body]
    assert len(root_children) == 2
    header_id, body_id = root_children
    assert "bc-panel-header" in fake_dom.element(header_id).classes
    assert "bc-panel-body" in fake_dom.element(body_id).classes
    # Title element is inside the header
    title_id = fake_dom.children(header_id)[0]
    assert "bc-panel-title" in fake_dom.element(title_id).classes
    assert fake_dom.element(title_id).text == "Targets"


def test_panel_with_title_only_has_no_toggle(fake_dom):
    panel = UiPanel(id="p", title="Targets")
    header_id = fake_dom.children(fake_dom.panel_root(panel.panel_id))[0]
    header_children = fake_dom.children(header_id)
    assert not any(
        "bc-panel-toggle" in fake_dom.element(c).classes for c in header_children)


def test_panel_with_collapsible_renders_toggle(fake_dom):
    panel = UiPanel(id="p", collapsible=True)
    header_id = fake_dom.children(fake_dom.panel_root(panel.panel_id))[0]
    header_children = fake_dom.children(header_id)
    assert any(
        "bc-panel-toggle" in fake_dom.element(c).classes for c in header_children)


def test_panel_toggle_click_collapses_and_uncollapses(fake_dom):
    panel = UiPanel(id="p", title="T", collapsible=True)
    root_children = fake_dom.children(fake_dom.panel_root(panel.panel_id))
    header_id, body_id = root_children
    toggle_id = next(
        c for c in fake_dom.children(header_id)
        if "bc-panel-toggle" in fake_dom.element(c).classes)
    assert fake_dom.element(body_id).visible is True
    assert panel.collapsed is False
    fake_dom.fire_click(toggle_id)
    assert fake_dom.element(body_id).visible is False
    assert panel.collapsed is True
    fake_dom.fire_click(toggle_id)
    assert fake_dom.element(body_id).visible is True
    assert panel.collapsed is False


def test_panel_toggle_glyph_updates_on_collapse(fake_dom):
    panel = UiPanel(id="p", collapsible=True)
    header_id = fake_dom.children(fake_dom.panel_root(panel.panel_id))[0]
    toggle_id = fake_dom.children(header_id)[1]  # title (empty) then toggle
    assert fake_dom.element(toggle_id).text == "▼"
    panel.set_collapsed(True)
    assert fake_dom.element(toggle_id).text == "▲"
    panel.set_collapsed(False)
    assert fake_dom.element(toggle_id).text == "▼"


def test_set_collapsed_on_non_collapsible_panel_raises(fake_dom):
    import pytest
    panel = UiPanel(id="p", title="T")  # title without collapsible
    with pytest.raises(RuntimeError):
        panel.set_collapsed(True)


def test_set_title_on_headerless_panel_raises(fake_dom):
    import pytest
    panel = UiPanel(id="p")
    with pytest.raises(RuntimeError):
        panel.set_title("X")


def test_set_title_updates_dom(fake_dom):
    panel = UiPanel(id="p", title="A")
    panel.set_title("B")
    title_id = fake_dom.children(
        fake_dom.children(fake_dom.panel_root(panel.panel_id))[0])[0]
    assert fake_dom.element(title_id).text == "B"


def test_panel_with_header_button_factory_attaches_to_body(fake_dom):
    panel = UiPanel(id="p", title="Targets")
    btn = panel.button("Hello")
    # button should be inside the body div, not directly under #root
    root_children = fake_dom.children(fake_dom.panel_root(panel.panel_id))
    body_id = root_children[1]
    assert btn.element_id in fake_dom.children(body_id)
    # Direct root children are just [header, body], not the button itself
    assert btn.element_id not in root_children
