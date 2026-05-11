from engine.ui import UiButton, bindings


def test_button_renders_label_into_dom(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    root = bindings.panel_root(pid)
    btn = UiButton(parent_element=root, label="Shield Generator", menu_level=3)
    el = fake_dom.element(btn.element_id)
    assert "bc-button" in el.classes
    assert "menu-3" in el.classes
    assert el.text == "Shield Generator"
    assert "selected" not in el.classes


def test_button_starts_selected_if_requested(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    btn = UiButton(parent_element=bindings.panel_root(pid),
                   label="Warp Core", selected=True)
    el = fake_dom.element(btn.element_id)
    assert "selected" in el.classes


def test_button_set_label_updates_dom(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    btn = UiButton(parent_element=bindings.panel_root(pid), label="A")
    btn.set_label("B")
    assert fake_dom.element(btn.element_id).text == "B"


def test_button_destroy_removes_from_dom(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    root = bindings.panel_root(pid)
    btn = UiButton(parent_element=root, label="A")
    assert fake_dom.children(root) == [btn.element_id]
    btn.destroy()
    assert fake_dom.children(root) == []
