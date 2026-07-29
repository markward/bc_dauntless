import json
from engine.core import ids
from engine.ui.tactical_orders_panel import TacticalOrdersPanel


class _FakeButton:
    """Mirrors the REAL STButton surface (engine/appc/characters.py):
    IsEnabled()/SetEnabled()/SetDisabled() round-trip an `_enabled` flag,
    defaulting to enabled like the real widget's `__init__`. Deliberately
    has NO IsDisabled() method — the real STButton doesn't define one
    either, and a fake that did previously masked a production bug where
    `hasattr(button, "IsDisabled")` was vacuously True via TGObject.
    __getattr__'s stub fallback, collapsing every row to enabled=False
    (see engine/ui/tactical_orders_panel.py's `_row` for the ids.implements
    fix and the postmortem comment there)."""
    def __init__(self, label, chosen=False, enabled=True):
        self._label, self._chosen, self._enabled = label, chosen, enabled
        self.activated = 0

    def GetLabel(self):      return self._label
    def IsChosen(self):      return self._chosen
    def IsEnabled(self):     return self._enabled
    def SetEnabled(self, *args):   self._enabled = True
    def SetDisabled(self, *args):  self._enabled = False
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
    left = _FakeButton("TacticLeft", enabled=False)
    m_atwill = _FakeButton("ManeuverAtWill", chosen=True)
    p = _panel_with([destroy, stop], [atwill, left], [m_atwill])
    p.visible = True
    js = p.render_payload()
    assert js is not None and js.startswith("setTacticalOrders(")
    payload = json.loads(js[len("setTacticalOrders("):-2])
    assert payload["visible"] is True
    labels = [r["label"] for r in payload["orders"]["rows"]]
    assert labels == ["OrderDestroy", "OrderStop"]
    assert payload["orders"]["rows"][1]["chosen"] is True          # Stop chosen
    assert payload["tactics"]["rows"][1]["enabled"] is False        # TacticLeft disabled
    assert [r["label"] for r in payload["maneuvers"]["rows"]] == ["ManeuverAtWill"]


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
    assert len(payload["orders"]["rows"]) > 0
    assert len(payload["tactics"]["rows"]) > 0
    assert len(payload["maneuvers"]["rows"]) > 0
    # Labels are localized display strings (data/TGL/Bridge Menus.tgl), not
    # the internal SDK keys -- "OrderStop" localizes to "Stop".
    assert "Stop" in [r["label"] for r in payload["orders"]["rows"]]


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
    maneuver_row_id = payload["maneuvers"]["rows"][0]["id"]
    tactic_row_id = payload["tactics"]["rows"][0]["id"]
    assert maneuver_row_id != tactic_row_id  # ids must not collide

    assert p.dispatch_event("click:" + maneuver_row_id) is True
    assert maneuver_atwill.activated == 1
    assert tactic_atwill.activated == 0  # the Tactics twin must NOT fire

    assert p.dispatch_event("click:" + tactic_row_id) is True
    assert tactic_atwill.activated == 1
    assert maneuver_atwill.activated == 1  # unchanged by the Tactics click


# ── Collapsible Maneuvers/Tactics popups (BC's STCharacterMenu) ──────────
#
# BC's Maneuvers and Tactics panes are STCharacterMenu popups whose
# collapsed label is set to the CURRENT selection by
# UpdateOrderStatusButtons; clicking expands the list, picking an option
# collapses it again. Orders is a plain always-expanded 2-col grid and is
# NOT collapsible -- these tests pin that asymmetry down.

def test_maneuvers_and_tactics_collapsed_by_default_showing_chosen():
    atwill = _FakeButton("TacticAtWill", chosen=False)
    aggressive = _FakeButton("TacticAggressive", chosen=True)
    m_atwill = _FakeButton("ManeuverAtWill", chosen=True)
    m_evasive = _FakeButton("ManeuverEvasive", chosen=False)
    p = _panel_with([], [atwill, aggressive], [m_atwill, m_evasive])
    p.visible = True

    payload = json.loads(p.render_payload()[len("setTacticalOrders("):-2])

    assert payload["tactics"]["collapsible"] is True
    assert payload["tactics"]["expanded"] is False
    assert payload["tactics"]["current"]["label"] == "TacticAggressive"

    assert payload["maneuvers"]["collapsible"] is True
    assert payload["maneuvers"]["expanded"] is False
    assert payload["maneuvers"]["current"]["label"] == "ManeuverAtWill"

    # Full rows list is still present in the payload even while collapsed
    # (the JS decides what to display; the panel always projects everything).
    assert len(payload["tactics"]["rows"]) == 2
    assert len(payload["maneuvers"]["rows"]) == 2


def test_current_selection_fallback_first_enabled_then_first_row():
    # No chosen row -> falls back to the first enabled row.
    left = _FakeButton("TacticLeft", enabled=False)
    aggressive = _FakeButton("TacticAggressive", enabled=True)
    p = _panel_with([], [left, aggressive], [])
    p.visible = True
    payload = json.loads(p.render_payload()[len("setTacticalOrders("):-2])
    assert payload["tactics"]["current"]["label"] == "TacticAggressive"

    # No chosen AND none enabled -> falls back to the first row outright.
    left2 = _FakeButton("TacticLeft", enabled=False)
    right2 = _FakeButton("TacticRight", enabled=False)
    p2 = _panel_with([], [left2, right2], [])
    p2.visible = True
    payload2 = json.loads(p2.render_payload()[len("setTacticalOrders("):-2])
    assert payload2["tactics"]["current"]["label"] == "TacticLeft"


def test_orders_is_never_collapsible_and_always_shows_all_rows():
    destroy = _FakeButton("OrderDestroy", chosen=True)
    stop = _FakeButton("OrderStop")
    p = _panel_with([destroy, stop], [], [])
    p.visible = True
    payload = json.loads(p.render_payload()[len("setTacticalOrders("):-2])
    assert payload["orders"]["collapsible"] is False
    assert payload["orders"]["expanded"] is True
    assert len(payload["orders"]["rows"]) == 2

    # Toggling maneuvers/tactics never affects Orders.
    p.dispatch_event("toggle:maneuvers")
    p.dispatch_event("toggle:tactics")
    payload = json.loads(p.render_payload()[len("setTacticalOrders("):-2])
    assert payload["orders"]["collapsible"] is False
    assert payload["orders"]["expanded"] is True
    assert len(payload["orders"]["rows"]) == 2


def test_toggle_expands_and_collapses_maneuvers():
    m1 = _FakeButton("ManeuverAtWill", chosen=True)
    m2 = _FakeButton("ManeuverEvasive")
    p = _panel_with([], [], [m1, m2])
    p.visible = True
    p.render_payload()  # establish baseline snapshot

    assert p.dispatch_event("toggle:maneuvers") is True
    payload = json.loads(p.render_payload()[len("setTacticalOrders("):-2])
    assert payload["maneuvers"]["expanded"] is True
    assert len(payload["maneuvers"]["rows"]) == 2

    assert p.dispatch_event("toggle:maneuvers") is True
    payload = json.loads(p.render_payload()[len("setTacticalOrders("):-2])
    assert payload["maneuvers"]["expanded"] is False


def test_toggle_unknown_group_is_not_handled():
    p = _panel_with([], [], [])
    assert p.dispatch_event("toggle:orders") is False
    assert p.dispatch_event("toggle:bogus") is False


def test_click_in_expanded_group_activates_and_collapses():
    m1 = _FakeButton("ManeuverAtWill", chosen=True)
    m2 = _FakeButton("ManeuverEvasive")
    p = _panel_with([], [], [m1, m2])
    p.visible = True
    p.render_payload()

    p.dispatch_event("toggle:maneuvers")
    payload = json.loads(p.render_payload()[len("setTacticalOrders("):-2])
    assert payload["maneuvers"]["expanded"] is True

    assert p.dispatch_event("click:maneuvers:ManeuverEvasive") is True
    assert m2.activated == 1

    payload = json.loads(p.render_payload()[len("setTacticalOrders("):-2])
    assert payload["maneuvers"]["expanded"] is False


def test_orders_click_does_not_touch_expand_state():
    destroy = _FakeButton("OrderDestroy")
    m1 = _FakeButton("ManeuverAtWill", chosen=True)
    p = _panel_with([destroy], [], [m1])
    p.visible = True
    p.render_payload()
    p.dispatch_event("toggle:maneuvers")
    payload = json.loads(p.render_payload()[len("setTacticalOrders("):-2])
    assert payload["maneuvers"]["expanded"] is True

    assert p.dispatch_event("click:orders:OrderDestroy") is True
    # An Orders click touches no render-relevant state, so render_payload()
    # correctly stays idempotent (returns None) -- assert directly on
    # internal state rather than forcing a re-render (invalidate() would
    # itself reset _expanded_groups, see test_invalidate_resets_expanded_groups).
    assert p.render_payload() is None
    assert "maneuvers" in p._expanded_groups


def test_render_idempotent_across_toggle():
    m1 = _FakeButton("ManeuverAtWill", chosen=True)
    p = _panel_with([], [], [m1])
    p.visible = True
    assert p.render_payload() is not None
    assert p.render_payload() is None  # unchanged -> no re-emit

    p.dispatch_event("toggle:maneuvers")
    assert p.render_payload() is not None  # toggle changed state -> re-emit
    assert p.render_payload() is None  # settled again -> no re-emit


def test_invalidate_resets_expanded_groups():
    m1 = _FakeButton("ManeuverAtWill", chosen=True)
    p = _panel_with([], [], [m1])
    p.visible = True
    p.render_payload()
    p.dispatch_event("toggle:maneuvers")
    payload = json.loads(p.render_payload()[len("setTacticalOrders("):-2])
    assert payload["maneuvers"]["expanded"] is True

    p.invalidate()
    payload = json.loads(p.render_payload()[len("setTacticalOrders("):-2])
    assert payload["maneuvers"]["expanded"] is False


# ── Follow-up review fixes ────────────────────────────────────────────────
#
# FIX 1 (BC fidelity): a collapsed popup's single visible row is the JS
# side's "current selection" row, routed to `toggle:<group>` (expand), NOT
# `click:<group>:<label>` (activate) -- BC's collapsed STCharacterMenu
# EXPANDS on click, it does not re-fire the already-chosen option. The panel
# itself doesn't need new dispatch logic for this (the `toggle:` branch
# already existed and never touches a button); this test pins the contract
# the JS relies on: dispatching the toggle action for a collapsed group
# expands it and calls no SDK activation on any button in that group.

def test_collapsed_group_click_only_expands_and_does_not_activate():
    chosen = _FakeButton("ManeuverAtWill", chosen=True)
    other = _FakeButton("ManeuverEvasive")
    p = _panel_with([], [], [chosen, other])
    p.visible = True
    payload = json.loads(p.render_payload()[len("setTacticalOrders("):-2])
    assert payload["maneuvers"]["expanded"] is False  # collapsed by default

    # This is what the JS now emits when the collapsed current-selection row
    # (or the header) is clicked -- toggle, never click:.
    assert p.dispatch_event("toggle:maneuvers") is True
    assert "maneuvers" in p._expanded_groups

    payload = json.loads(p.render_payload()[len("setTacticalOrders("):-2])
    assert payload["maneuvers"]["expanded"] is True
    # No button was activated by the collapsed-row click -- only genuine
    # option clicks (click:<group>:<label>) ever call SendActivationEvent.
    assert chosen.activated == 0
    assert other.activated == 0


# FIX 3: a collapsible group with zero rows must render safely -- no rows to
# show, no crash resolving `current` (None with no rows, per `_current_row`).

def test_collapsible_group_with_zero_rows_renders_safely():
    p = _panel_with([_FakeButton("OrderDestroy")], [], [])  # maneuvers empty
    p.visible = True
    js = p.render_payload()
    assert js is not None
    payload = json.loads(js[len("setTacticalOrders("):-2])
    assert payload["maneuvers"]["collapsible"] is True
    assert payload["maneuvers"]["rows"] == []
    assert payload["maneuvers"]["current"] is None
    # expanded is whatever the group's default state is -- False by default,
    # since it was never toggled -- and toggling an empty group is still a
    # valid (harmless) UI action.
    assert payload["maneuvers"]["expanded"] is False
    assert p.dispatch_event("toggle:maneuvers") is True
    payload = json.loads(p.render_payload()[len("setTacticalOrders("):-2])
    assert payload["maneuvers"]["expanded"] is True
    assert payload["maneuvers"]["rows"] == []
    assert payload["maneuvers"]["current"] is None


# ── Live-pass regression: every row rendered disabled ────────────────────
#
# CRITICAL: `_row()` read enabled state via `hasattr(button, "IsDisabled")`.
# The real STButton (engine/appc/characters.py) has NO IsDisabled() method
# -- only IsEnabled(), which SetEnabled()/SetDisabled() round-trip. But
# TGObject.__getattr__ hands back a truthy `_Stub` for ANY unknown
# non-underscore name (engine/core/ids.py), so `hasattr(real_button,
# "IsDisabled")` was VACUOUSLY True, `button.IsDisabled()` returned that
# truthy stub, and `enabled = not bool(stub) = False` for every single row
# regardless of the SDK's real enabled/disabled state -- the whole Orders/
# Tactics/Maneuvers panel rendered unclickable. `_FakeButton` used to
# implement IsDisabled() directly, which is exactly why 3 prior review
# passes and a full green test suite missed it: the fake didn't match the
# real widget's surface. `_FakeButton` no longer has IsDisabled() (see its
# docstring above) so tests exercise the same ids.implements() branch
# production does; this test additionally builds a REAL App.STButton_CreateW
# widget to close the loop entirely.

def test_row_reads_enabled_from_real_stbutton_not_a_vacuous_stub():
    import App

    button = App.STButton_CreateW("TacticAggressive", None, 0)

    # Sanity-check the exact footgun: hasattr() is vacuously True for a
    # method the real widget does NOT implement, which is why the
    # production fix uses ids.implements() instead.
    assert hasattr(button, "IsDisabled") is True   # the trap
    assert ids.implements(button, "IsDisabled") is False   # the real answer
    assert ids.implements(button, "IsEnabled") is True

    # Real STButton defaults to enabled (characters.py __init__).
    row = TacticalOrdersPanel._row(button, "tactics")
    assert row["enabled"] is True

    button.SetDisabled(1)
    row = TacticalOrdersPanel._row(button, "tactics")
    assert row["enabled"] is False

    button.SetEnabled(1)
    row = TacticalOrdersPanel._row(button, "tactics")
    assert row["enabled"] is True
