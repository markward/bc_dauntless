"""UiPanel.set_footer_button creates one right-aligned button at the bottom."""
from engine.ui import UiPanel


def test_footer_creates_one_container_and_button(fake_dom):
    panel = UiPanel(id="f", width_vw=30, height_vh=30, title="T")
    btn = panel.set_footer_button("Cancel")
    root = fake_dom.panel_root(panel.panel_id)
    classes = [
        " ".join(fake_dom.element(c).classes)
        for c in fake_dom.children(root)
    ]
    assert classes == ["bc-panel-header", "bc-panel-body", "bc-panel-footer"]
    footer_id = fake_dom.children(root)[-1]
    footer_kids = fake_dom.children(footer_id)
    assert len(footer_kids) == 1
    assert "bc-button" in fake_dom.element(footer_kids[0]).classes
    assert fake_dom.element(footer_kids[0]).text == "Cancel"
    assert btn is not None


def test_footer_click_fires_callback(fake_dom):
    panel = UiPanel(id="f", width_vw=30, height_vh=30, title="T")
    seen = []
    panel.set_footer_button("Cancel", on_click=lambda: seen.append("clicked"))
    root = fake_dom.panel_root(panel.panel_id)
    footer_id = [
        c for c in fake_dom.children(root)
        if "bc-panel-footer" in fake_dom.element(c).classes
    ][0]
    btn_id = fake_dom.children(footer_id)[0]
    fake_dom.fire_click(btn_id)
    assert seen == ["clicked"]


def test_footer_relabel_reuses_container(fake_dom):
    panel = UiPanel(id="f", width_vw=30, height_vh=30, title="T")
    panel.set_footer_button("Cancel")
    panel.set_footer_button("Close", on_click=lambda: None)
    root = fake_dom.panel_root(panel.panel_id)
    footers = [
        c for c in fake_dom.children(root)
        if "bc-panel-footer" in fake_dom.element(c).classes
    ]
    assert len(footers) == 1
    btn_id = fake_dom.children(footers[0])[0]
    assert fake_dom.element(btn_id).text == "Close"


def test_no_footer_when_set_footer_button_never_called(fake_dom):
    panel = UiPanel(id="f", width_vw=30, height_vh=30, title="T")
    root = fake_dom.panel_root(panel.panel_id)
    classes = [
        " ".join(fake_dom.element(c).classes)
        for c in fake_dom.children(root)
    ]
    assert "bc-panel-footer" not in " ".join(classes)
