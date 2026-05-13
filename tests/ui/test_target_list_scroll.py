"""Pixel-based virtual scrolling on TargetListController.

`_scroll_pixels` is a dp offset applied as a negative margin-top on the
panel body — the panel's overflow:hidden clips rows above the visible
area.  `scroll(delta)` bumps the offset by delta rows (positive = scroll
down).  Always renders the full ship list (no slicing) so expansion-
preserved rows are still in the DOM ready to be revealed by scrolling.
"""
import pytest

from engine.appc import ship_lifecycle
from engine.ui import UiPanel, bindings as bindings_module
from engine.ui._dom import FakeDom
from engine.ui.target_list import TargetListController, _ROW_HEIGHT_DP


@pytest.fixture
def fake_dom(monkeypatch) -> FakeDom:
    dom = FakeDom()
    monkeypatch.setattr(bindings_module, "_active_dom", dom)
    return dom


@pytest.fixture(autouse=True)
def _reset_hub():
    ship_lifecycle._subscribers.clear()
    ship_lifecycle._live.clear()
    yield
    ship_lifecycle._subscribers.clear()
    ship_lifecycle._live.clear()


class _Ship:
    def __init__(self, name): self._name = name
    def GetName(self): return self._name
    def GetHull(self): return None
    def GetShieldSubsystem(self): return None
    def GetSensorSubsystem(self): return None
    def GetPowerSubsystem(self): return None
    def GetRepairSubsystem(self): return None
    def GetImpulseEngineSubsystem(self): return None
    def GetWarpEngineSubsystem(self): return None
    def GetPhaserSystem(self): return None
    def GetPulseWeaponSystem(self): return None
    def GetTorpedoSystem(self): return None
    def GetTractorBeamSystem(self): return None


def _ship_titles(fake_dom, panel) -> list[str]:
    root = fake_dom.panel_root(panel.panel_id)
    body_id = fake_dom.children(root)[-1]
    wrappers = fake_dom.children(fake_dom.children(body_id)[0])
    titles = []
    for w in wrappers:
        header = fake_dom.children(w)[0]
        title_id = fake_dom.children(header)[1]
        titles.append(fake_dom.element(title_id).text)
    return titles


def _body_margin_top(fake_dom, panel) -> str | None:
    """Scroll offset is applied as transform: translateY on the
    bc-target-scroll wrapper (first child of the panel body), NOT on
    the body itself.  Keeps body's layout box fixed so its overflow:hidden
    clips rows scrolled above the body's top edge.  Margin-top was tried
    first but RmlUi didn't reliably clip negative-margin children."""
    root = fake_dom.panel_root(panel.panel_id)
    body_id = fake_dom.children(root)[-1]
    wrapper_id = fake_dom.children(body_id)[0]
    el = fake_dom.element(wrapper_id)
    return getattr(el, "_props", {}).get("transform")


def test_initial_scroll_pixels_is_zero(fake_dom):
    panel = UiPanel(id="t", title="T")
    ctrl = TargetListController(panel, player_provider=lambda: None)
    assert ctrl._scroll_pixels == 0.0


def test_scroll_down_increases_pixels_by_one_row_per_notch(fake_dom):
    for n in ("A", "B", "C", "D"):
        ship_lifecycle.publish_added(_Ship(n))
    panel = UiPanel(id="t", title="T")
    ctrl = TargetListController(panel, player_provider=lambda: None)

    ctrl.scroll(1)
    assert ctrl._scroll_pixels == _ROW_HEIGHT_DP

    ctrl.scroll(2)
    assert ctrl._scroll_pixels == 3 * _ROW_HEIGHT_DP


def test_scroll_applies_negative_translate_on_scroll_wrapper(fake_dom):
    for n in ("A", "B"):
        ship_lifecycle.publish_added(_Ship(n))
    panel = UiPanel(id="t", title="T")
    ctrl = TargetListController(panel, player_provider=lambda: None)

    ctrl.scroll(2)
    transform = _body_margin_top(fake_dom, panel)
    expected = f"translateY(-{2 * _ROW_HEIGHT_DP:.1f}dp)"
    assert transform == expected


def test_scroll_up_clamps_at_zero(fake_dom):
    for n in ("A", "B"):
        ship_lifecycle.publish_added(_Ship(n))
    panel = UiPanel(id="t", title="T")
    ctrl = TargetListController(panel, player_provider=lambda: None)

    ctrl.scroll(-5)
    assert ctrl._scroll_pixels == 0.0


def test_all_ships_always_rendered_regardless_of_scroll(fake_dom):
    """Pixel-scroll renders the full list; visibility is achieved by
    the panel's overflow:hidden clipping rows above margin-top."""
    for n in ("A", "B", "C"):
        ship_lifecycle.publish_added(_Ship(n))
    panel = UiPanel(id="t", title="T")
    ctrl = TargetListController(panel, player_provider=lambda: None)
    assert _ship_titles(fake_dom, panel) == ["A", "B", "C"]

    ctrl.scroll(99)
    # Big scroll — all three still in DOM; margin-top moves them off-screen.
    assert _ship_titles(fake_dom, panel) == ["A", "B", "C"]


def test_scroll_with_no_ships_is_noop(fake_dom):
    panel = UiPanel(id="t", title="T")
    ctrl = TargetListController(panel, player_provider=lambda: None)
    ctrl.scroll(3)
    assert ctrl._scroll_pixels == 3 * _ROW_HEIGHT_DP  # tracked even with no ships


def test_player_skipped_from_ship_list(fake_dom):
    player = _Ship("Player")
    ship_lifecycle.publish_added(player)
    for n in ("A", "B", "C"):
        ship_lifecycle.publish_added(_Ship(n))
    panel = UiPanel(id="t", title="T")
    ctrl = TargetListController(panel, player_provider=lambda: player)
    assert _ship_titles(fake_dom, panel) == ["A", "B", "C"]


def test_ship_added_event_preserves_scroll_state(fake_dom):
    for n in ("A", "B", "C"):
        ship_lifecycle.publish_added(_Ship(n))
    panel = UiPanel(id="t", title="T")
    ctrl = TargetListController(panel, player_provider=lambda: None)
    ctrl.scroll(1)
    before = ctrl._scroll_pixels

    ship_lifecycle.publish_added(_Ship("D"))  # triggers rebuild
    assert ctrl._scroll_pixels == before
    assert _ship_titles(fake_dom, panel) == ["A", "B", "C", "D"]
    # Transform still applied after rebuild.
    assert _body_margin_top(fake_dom, panel) == f"translateY(-{before:.1f}dp)"
