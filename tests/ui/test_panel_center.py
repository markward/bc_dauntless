"""UiPanel supports anchor='center'."""
from engine.ui import UiPanel


def test_center_anchor_is_accepted(fake_dom):
    panel = UiPanel(id="c", anchor="center", width_vw=40, height_vh=70)
    panels = list(fake_dom._panels.values())
    assert len(panels) == 1
    assert panels[0].anchor == "center"
    panel.destroy()


def test_default_anchor_unchanged(fake_dom):
    """Regression: the default is still top-right after adding 'center'."""
    panel = UiPanel(id="d", width_vw=20, height_vh=20)
    assert list(fake_dom._panels.values())[0].anchor == "top-right"
    panel.destroy()
