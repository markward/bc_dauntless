from engine.ui import UiCollapsibleList, bindings


def test_collapsible_renders_header_with_title_and_arrow(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    root = bindings.panel_root(pid)
    coll = UiCollapsibleList(parent_element=root, label="Bird of Prey-1",
                             affiliation="enemy", expanded=True)
    # Header has two children: arrow region and title region.
    header_classes = fake_dom.element(coll.header_element_id).classes
    assert "bc-collapsible-header" in header_classes
    assert "aff-enemy" in header_classes
    arrow_id, title_id = fake_dom.children(coll.header_element_id)
    assert "bc-arrow"  in fake_dom.element(arrow_id).classes
    assert "bc-title"  in fake_dom.element(title_id).classes
    assert fake_dom.element(title_id).text == "Bird of Prey-1"


def test_collapsible_menu_level_class_when_no_affiliation(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    root = bindings.panel_root(pid)
    coll = UiCollapsibleList(parent_element=root, label="Subsystems",
                             menu_level=3)
    classes = fake_dom.element(coll.header_element_id).classes
    assert "menu-3" in classes
    assert not any(c.startswith("aff-") for c in classes)


def test_collapsible_set_label_updates_title_element(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    coll = UiCollapsibleList(parent_element=bindings.panel_root(pid),
                             label="One", affiliation="friendly")
    coll.set_label("Two")
    title_id = fake_dom.children(coll.header_element_id)[1]
    assert fake_dom.element(title_id).text == "Two"


def test_collapsible_destroy_removes_subtree(fake_dom):
    pid = bindings.create_panel("p", "top-right", 20.0, 60.0)
    root = bindings.panel_root(pid)
    coll = UiCollapsibleList(parent_element=root, label="X",
                             affiliation="neutral")
    assert fake_dom.children(root) != []
    coll.destroy()
    assert fake_dom.children(root) == []
