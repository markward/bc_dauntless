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
    assert p.dispatch_event("click:orders:OrderDestroy") is True
    assert destroy.activated == 1


def test_invisible_snapshot_emits_no_rows():
    p = _panel_with([_FakeButton("OrderStop")], [], [])
    p.visible = False
    js = p.render_payload()
    payload = json.loads(js[len("setTacticalOrders("):-2])
    assert payload["visible"] is False


# ── Code-review regressions ──────────────────────────────────────────────
#
# CRITICAL 1: _resolve_panes() originally read g_pOrdersStatusUI (the
# STStylizedWindow *container*) instead of g_pOrdersStatusUIPane (the TGPane
# the order buttons are actually AddChild'd onto per SDK
# Bridge/TacticalMenuHandlers.py:591, 609/611) -- the Orders group rendered
# permanently empty. The 4 tests above all monkeypatch _resolve_panes
# entirely, so none of them could catch a wrong-global bug in the real
# implementation; this test exercises the REAL (unpatched) _resolve_panes
# against the real SDK builder, mirroring the Sub-step 3a probe.
#
# CRITICAL 2: BC's localized labels collide across groups -- TacticAtWill
# and ManeuverAtWill both localize to "At Will" (data/TGL/Bridge Menus.tgl).
# An unqualified row id made dispatch_event's first-match search
# (orders -> tactics -> maneuvers) activate the Tactics button when the
# Maneuvers row was clicked. Covered below with fakes (fast, no SDK
# dependency) since the bug is about routing logic, not widget shape.

def test_resolve_panes_reads_orders_status_ui_pane():
    import App
    import Bridge.TacticalMenuHandlers as T

    p_tactical_menu = App.STMenu_CreateW("TacticalMenu")
    pane = T.CreateOrdersStatusDisplay(400.0, p_tactical_menu)
    assert pane is not None

    # The order buttons live on g_pOrdersStatusUIPane, NOT g_pOrdersStatusUI
    # (its STStylizedWindow container, which our STStylizedWindow_CreateW
    # shim never attaches children to).
    assert T.g_pOrdersStatusUIPane is not None
    assert len(T.g_pOrdersStatusUIPane._children) > 0
    assert T.g_pOrdersStatusUI._children == []  # the decoy stays empty

    p = TacticalOrdersPanel()  # real _resolve_panes, not overridden
    orders_pane, tactics_pane, maneuvers_pane = p._resolve_panes()
    assert orders_pane is T.g_pOrdersStatusUIPane
    assert orders_pane is not T.g_pOrdersStatusUI

    p.visible = True
    js = p.render_payload()
    payload = json.loads(js[len("setTacticalOrders("):-2])
    # Orders must be non-empty (Destroy/Disable/Stop/Evade); Tactics and
    # Maneuvers were already correctly wired (STCharacterMenu, fixed in
    # Sub-step 3a) so they should be non-empty too.
    assert len(payload["orders"]) > 0
    assert len(payload["tactics"]) > 0
    assert len(payload["maneuvers"]) > 0
    # Labels are localized display strings (data/TGL/Bridge Menus.tgl), not
    # the internal SDK keys -- "OrderStop" localizes to "Stop".
    assert "Stop" in [r["label"] for r in payload["orders"]]


def test_maneuver_atwill_activates_maneuvers_not_tactics():
    # Both buttons localize/display as "At Will" -- the exact SDK collision
    # (TacticAtWill vs ManeuverAtWill, both -> "At Will" per Bridge
    # Menus.tgl). Only the Maneuvers button must activate.
    tactic_atwill = _FakeButton("At Will")
    maneuver_atwill = _FakeButton("At Will")
    p = _panel_with([], [tactic_atwill], [maneuver_atwill])
    p.visible = True

    js = p.render_payload()
    payload = json.loads(js[len("setTacticalOrders("):-2])
    maneuver_row_id = payload["maneuvers"][0]["id"]
    tactic_row_id = payload["tactics"][0]["id"]
    assert maneuver_row_id != tactic_row_id  # ids must not collide

    assert p.dispatch_event("click:" + maneuver_row_id) is True
    assert maneuver_atwill.activated == 1
    assert tactic_atwill.activated == 0  # the Tactics twin must NOT fire

    assert p.dispatch_event("click:" + tactic_row_id) is True
    assert tactic_atwill.activated == 1
    assert maneuver_atwill.activated == 1  # unchanged by the Tactics click
