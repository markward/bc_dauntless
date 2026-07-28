import json
from engine.ui.tactical_orders_panel import TacticalOrdersPanel


class _FakeButton:
    def __init__(self, label, chosen=False, disabled=False):
        self._label, self._chosen, self._disabled = label, chosen, disabled
        self.activated = 0

    def GetLabel(self):     return self._label
    def IsChosen(self):     return self._chosen
    def IsDisabled(self):   return self._disabled
    def SendActivationEvent(self): self.activated += 1


class _FakePane:
    def __init__(self, buttons): self._buttons = buttons
    def _iter_buttons(self):     return list(self._buttons)


def _panel_with(orders, tactics, maneuvers):
    p = TacticalOrdersPanel()
    p._resolve_panes = lambda: (_FakePane(orders),
                                _FakePane(tactics),
                                _FakePane(maneuvers))
    return p


def test_snapshot_projects_all_three_groups():
    stop = _FakeButton("OrderStop", chosen=True)
    destroy = _FakeButton("OrderDestroy")
    atwill = _FakeButton("TacticAtWill", chosen=True)
    left = _FakeButton("TacticLeft", disabled=True)
    m_atwill = _FakeButton("ManeuverAtWill", chosen=True)
    p = _panel_with([destroy, stop], [atwill, left], [m_atwill])
    p.visible = True
    js = p.render_payload()
    assert js is not None and js.startswith("setTacticalOrders(")
    payload = json.loads(js[len("setTacticalOrders("):-2])
    assert payload["visible"] is True
    labels = [r["label"] for r in payload["orders"]]
    assert labels == ["OrderDestroy", "OrderStop"]
    assert payload["orders"][1]["chosen"] is True          # Stop chosen
    assert payload["tactics"][1]["enabled"] is False        # TacticLeft disabled
    assert [r["label"] for r in payload["maneuvers"]] == ["ManeuverAtWill"]


def test_render_is_idempotent():
    p = _panel_with([_FakeButton("OrderStop", chosen=True)], [], [])
    p.visible = True
    assert p.render_payload() is not None
    assert p.render_payload() is None  # unchanged snapshot -> no re-emit


def test_click_activates_the_matching_button():
    destroy = _FakeButton("OrderDestroy")
    p = _panel_with([destroy], [], [])
    assert p.dispatch_event("click:OrderDestroy") is True
    assert destroy.activated == 1


def test_invisible_snapshot_emits_no_rows():
    p = _panel_with([_FakeButton("OrderStop")], [], [])
    p.visible = False
    js = p.render_payload()
    payload = json.loads(js[len("setTacticalOrders("):-2])
    assert payload["visible"] is False
