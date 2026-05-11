from engine.ui._dom import FakeDom


def test_create_panel_returns_increasing_ids():
    dom = FakeDom()
    p1 = dom.create_panel("targets", "top-right", 20.0, 60.0)
    p2 = dom.create_panel("nav",     "top-left",  15.0, 40.0)
    assert p1 != p2
    assert dom.panel_root(p1) is not None
    assert dom.panel_root(p2) is not None


def test_append_div_attaches_to_parent():
    dom = FakeDom()
    p = dom.create_panel("p", "top-right", 20.0, 60.0)
    root = dom.panel_root(p)
    a = dom.append_div(root, "bc-button")
    b = dom.append_div(root, "bc-button selected")
    assert dom.element(a).classes == ["bc-button"]
    assert dom.element(b).classes == ["bc-button", "selected"]
    assert dom.children(root) == [a, b]


def test_set_text_updates_node():
    dom = FakeDom()
    p = dom.create_panel("p", "top-right", 20.0, 60.0)
    e = dom.append_div(dom.panel_root(p), "")
    dom.set_text(e, "Shield Generator")
    assert dom.element(e).text == "Shield Generator"


def test_set_class_replaces_class_list():
    dom = FakeDom()
    p = dom.create_panel("p", "top-right", 20.0, 60.0)
    e = dom.append_div(dom.panel_root(p), "bc-button")
    dom.set_class(e, "bc-button selected")
    assert dom.element(e).classes == ["bc-button", "selected"]


def test_on_click_records_callback_and_fires():
    dom = FakeDom()
    p = dom.create_panel("p", "top-right", 20.0, 60.0)
    e = dom.append_div(dom.panel_root(p), "")
    received = []
    dom.on_click(e, lambda: received.append("clicked"))
    dom.fire_click(e)
    assert received == ["clicked"]


def test_remove_element_detaches_from_parent():
    dom = FakeDom()
    p = dom.create_panel("p", "top-right", 20.0, 60.0)
    root = dom.panel_root(p)
    a = dom.append_div(root, "")
    b = dom.append_div(root, "")
    dom.remove_element(a)
    assert dom.children(root) == [b]


def test_set_visible_toggles_flag():
    dom = FakeDom()
    p = dom.create_panel("p", "top-right", 20.0, 60.0)
    e = dom.append_div(dom.panel_root(p), "")
    assert dom.element(e).visible is True
    dom.set_visible(e, False)
    assert dom.element(e).visible is False


def test_set_panel_css_var_records_value():
    dom = FakeDom()
    p = dom.create_panel("p", "top-right", 20.0, 60.0)
    dom.set_panel_css_var(p, "--aff-color", "rgb(216,43,43)")
    assert dom.panel_css_vars(p) == {"--aff-color": "rgb(216,43,43)"}
