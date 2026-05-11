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


def test_button_click_fires_callback(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    fired: list[str] = []
    btn = UiButton(parent_element=bindings.panel_root(pid), label="X",
                   on_click=lambda: fired.append("ok"))
    fake_dom.fire_click(btn.element_id)
    assert fired == ["ok"]


def test_button_no_callback_does_not_explode(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    btn = UiButton(parent_element=bindings.panel_root(pid), label="X")
    fake_dom.fire_click(btn.element_id)  # must not raise


from engine.ui.button import _RadioGroup


def test_radio_group_selects_one_at_a_time(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    root = bindings.panel_root(pid)
    group = _RadioGroup()
    a = UiButton(parent_element=root, label="A"); group.adopt(a)
    b = UiButton(parent_element=root, label="B"); group.adopt(b)
    c = UiButton(parent_element=root, label="C"); group.adopt(c)
    # Click A → only A selected
    fake_dom.fire_click(a.element_id)
    assert a.selected and not b.selected and not c.selected
    # Click B → only B
    fake_dom.fire_click(b.element_id)
    assert b.selected and not a.selected and not c.selected
    # Click B again → still only B; no toggle to unselected
    fake_dom.fire_click(b.element_id)
    assert b.selected


def test_radio_group_does_not_refire_when_clicking_selected(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    root = bindings.panel_root(pid)
    group = _RadioGroup()
    fires: list[str] = []
    a = UiButton(parent_element=root, label="A",
                 on_click=lambda: fires.append("a"))
    group.adopt(a)
    fake_dom.fire_click(a.element_id)        # selects → fires
    fake_dom.fire_click(a.element_id)        # already selected → no fire
    assert fires == ["a"]


def test_radio_group_previously_selected_does_not_fire_on_deselect(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    root = bindings.panel_root(pid)
    group = _RadioGroup()
    fires: list[str] = []
    a = UiButton(parent_element=root, label="A",
                 on_click=lambda: fires.append("a"))
    b = UiButton(parent_element=root, label="B",
                 on_click=lambda: fires.append("b"))
    group.adopt(a); group.adopt(b)
    fake_dom.fire_click(a.element_id)        # a fires
    fake_dom.fire_click(b.element_id)        # b fires; a's callback must NOT fire
    assert fires == ["a", "b"]


def test_radio_group_set_selected_programmatic_also_exclusive(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    root = bindings.panel_root(pid)
    group = _RadioGroup()
    a = UiButton(parent_element=root, label="A")
    b = UiButton(parent_element=root, label="B")
    group.adopt(a); group.adopt(b)
    group.select(a)
    assert a.selected and not b.selected
    group.select(b)
    assert b.selected and not a.selected
