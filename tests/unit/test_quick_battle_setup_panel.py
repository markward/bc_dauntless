"""Tests for QuickBattleSetupPanel — the on-theme "Quick Battle Setup" shell.

T1 scope: header + a single Ships tab + Start/Close, no body content yet.
Mirrors test_developer_options_panel.py / test_configuration_panel.py: state,
open/close, dispatch_event branches, render_payload snapshot dedup, and ESC.
"""
import json

import pytest

from engine.ui.quick_battle_setup_panel import QuickBattleSetupPanel


@pytest.fixture
def panel():
    return QuickBattleSetupPanel()


def _body(payload):
    return json.loads(payload[len("setQuickBattleSetup("):-2])


# ---- construction / open-close -------------------------------------------

def test_name_is_quick_battle_setup(panel):
    assert panel.name == "quick-battle-setup"


def test_initially_closed(panel):
    assert panel.is_open() is False


def test_open_close_round_trip(panel):
    panel.open()
    assert panel.is_open() is True
    panel.close()
    assert panel.is_open() is False


# ---- dispatch_event -------------------------------------------------------

def test_dispatch_close_closes(panel):
    panel.open()
    assert panel.dispatch_event("close") is True
    assert panel.is_open() is False


def test_dispatch_start_returns_true_and_calls_callback(panel):
    calls = []
    p = QuickBattleSetupPanel(on_start=lambda: calls.append("start"))
    p._qb_module = _stub_qb_module()       # non-empty roster -> Start is live
    p.open()
    assert p.dispatch_event("start") is True
    assert calls == ["start"]


def test_dispatch_start_without_callback_is_noop(panel):
    panel.open()
    # No on_start wired — Start is still "handled" (later task wires it).
    assert panel.dispatch_event("start") is True


def test_dispatch_unknown_returns_false(panel):
    panel.open()
    assert panel.dispatch_event("bogus") is False


# ---- render_payload -------------------------------------------------------

def test_render_payload_shape(panel):
    panel.open()
    body = _body(panel.render_payload())
    assert body["open"] is True
    # The single-pane layout dropped the tab strip — no tabs/selected_tab keys.
    assert "tabs" not in body
    assert "selected_tab" not in body


def test_render_payload_dedups(panel):
    panel.open()
    assert panel.render_payload() is not None
    assert panel.render_payload() is None


def test_render_payload_close_emits_hide(panel):
    panel.open()
    panel.render_payload()
    panel.close()
    out = panel.render_payload()
    assert _body(out) == {"open": False}


def test_invalidate_re_emits(panel):
    panel.open()
    first = panel.render_payload()
    assert panel.render_payload() is None
    panel.invalidate()
    assert panel.render_payload() == first


# ---- keyboard -------------------------------------------------------------

def test_handle_key_esc_when_open_closes(panel):
    panel.open()
    panel.handle_key_esc()
    assert panel.is_open() is False


def test_handle_key_esc_when_closed_is_noop(panel):
    panel.handle_key_esc()
    assert panel.is_open() is False


# ---- Ships tab: live SDK widget reader ------------------------------------
#
# Build a stub QuickBattle module out of the real shim widgets so the panel
# walks an authentic tree (g_pShipsPane -> stylized window -> ship-menu
# STSubPane -> STCharacterMenu categories -> STButton ships; g_pFriendMenu /
# g_pEnemyMenu STSubPanes of STButtons). The panel reads the module via its
# injectable `_qb_module` hook.

from types import SimpleNamespace

from engine.appc.characters import STButton
from engine.appc.tg_ui.st_widgets import STCharacterMenu, STSubPane
from engine.appc.windows import STStylizedWindow_CreateW


def _ship_button(label, enabled=True):
    b = STButton(label)
    if not enabled:
        b.SetDisabled()
    return b


def _stub_qb_module():
    """A fake QuickBattle module with the three relevant globals populated
    with real shim widgets, nested exactly as BuildDialog/GenerateShipMenu
    build them."""
    ships_pane = STSubPane()

    # GenerateShipMenu: g_pShipsPane -> stylized window -> ship-menu STSubPane
    # -> STCharacterMenu categories -> STButton ships.
    window = STStylizedWindow_CreateW("StylizedWindow", "NoMinimize", "Ships")
    ship_menu = STSubPane()
    window.AddChild(ship_menu)
    ships_pane.AddChild(window, 0.0, 0.0)

    fed = STCharacterMenu("Fed Ships")
    fed.AddChild(_ship_button("Akira"))
    fed.AddChild(_ship_button("Galaxy"))
    klingon = STCharacterMenu("Klingon Ships")
    klingon.AddChild(_ship_button("BOP"))
    bases = STCharacterMenu("Bases")
    bases.AddChild(_ship_button("Fed Starbase", enabled=False))
    ship_menu.AddChild(fed)
    ship_menu.AddChild(klingon)
    ship_menu.AddChild(bases)

    friend_menu = STSubPane()
    friend_menu.AddChild(_ship_button("Galaxy"), 0.0, 0.0)
    enemy_menu = STSubPane()
    enemy_menu.AddChild(_ship_button("BOP"))
    enemy_menu.AddChild(_ship_button("Warbird"))

    return SimpleNamespace(
        g_pShipsPane=ships_pane,
        g_pFriendMenu=friend_menu,
        g_pEnemyMenu=enemy_menu,
        g_sPlayerType="Galaxy",
        bInSimulation=0,
        # SelectShipType stores the clicked ship's type int here; the friendly
        # table maps it to the ship NAME (index [0]) — what Set As Player Ship
        # assigns to g_sPlayerType.
        g_iSelectedShipType=-1,
        g_dFriendlyShipTypeToDetails={
            9: ["Sovereign", "Sovereign", "x", "QuickBattleFriendlyAI", "Friendly"],
            3: ["Galaxy", "Galaxy", "x", "QuickBattleFriendlyAI", "Friendly"],
        },
        # Enemy type->details table; details[1] is the GetString key used as the
        # roster label (no g_pMissionDatabase here -> key resolves to itself).
        g_dEnemyShipTypeToDetails={
            7: ["BOP", "BOP", "x", "QuickBattleAI", "Enemy"],
            8: ["Warbird", "Warbird", "x", "QuickBattleAI", "Enemy"],
        },
        g_pAddFriendButton=_ship_button("Add As Friendly"),
        g_pAddEnemyButton=_ship_button("Add As Enemy"),
        g_pDeleteButton=_ship_button("Delete"),
        ET_CLOSE_DIALOG=4242,
        g_pXO=object(),
    )


def _spy_activation(button):
    """Replace a button's SendActivationEvent with a recorder; return the log."""
    fired = []
    button.SendActivationEvent = lambda: fired.append(True)
    return fired


@pytest.fixture
def qb_panel():
    p = QuickBattleSetupPanel()
    p._qb_module = _stub_qb_module()
    p.open()
    return p


def test_ships_payload_has_categories_with_nested_ships(qb_panel):
    body = _body(qb_panel.render_payload())
    cats = body["categories"]
    labels = [c["label"] for c in cats]
    assert labels == ["Fed Ships", "Klingon Ships", "Bases"]
    fed = cats[0]
    assert [s["label"] for s in fed["ships"]] == ["Akira", "Galaxy"]
    bases = cats[2]
    assert bases["ships"][0]["label"] == "Fed Starbase"
    assert bases["ships"][0]["enabled"] is False
    assert fed["ships"][0]["enabled"] is True


def test_ships_payload_has_friend_and_enemy_lists(qb_panel):
    # Rosters are stacked by label into {label, count} (count 1 each here).
    body = _body(qb_panel.render_payload())
    assert body["friendly"] == [{"label": "Galaxy", "count": 1}]
    assert body["enemy"] == [
        {"label": "BOP", "count": 1},
        {"label": "Warbird", "count": 1},
    ]


def test_roster_stacks_identical_ships_with_a_tally(qb_panel):
    # Add two more BOPs to the enemy menu -> a single 'BOP ×3' row, with the
    # first-seen order (BOP before Warbird) preserved.
    enemy = qb_panel._qb_module.g_pEnemyMenu
    enemy.AddChild(_ship_button("BOP"))
    enemy.AddChild(_ship_button("BOP"))
    qb_panel.invalidate()
    body = _body(qb_panel.render_payload())
    assert body["enemy"] == [
        {"label": "BOP", "count": 3},
        {"label": "Warbird", "count": 1},
    ]


def test_categories_collapsed_by_default(qb_panel):
    body = _body(qb_panel.render_payload())
    assert all(c["expanded"] is False for c in body["categories"])


def test_every_node_has_stable_id_resolving_to_widget(qb_panel):
    body = _body(qb_panel.render_payload())
    cat = body["categories"][0]
    ship = cat["ships"][0]
    # ids resolve back to the live stub widgets via the id->widget map.
    # The first category is g_pShipsPane -> window -> ship_menu -> first child.
    fed_menu = (qb_panel._qb_module.g_pShipsPane
                .GetFirstChild()        # stylized window
                .GetFirstChild()        # ship-menu STSubPane
                .GetFirstChild())       # first STCharacterMenu (Fed Ships)
    assert qb_panel.widget_for_id(cat["id"]) is fed_menu
    ship_widget = qb_panel.widget_for_id(ship["id"])
    assert isinstance(ship_widget, STButton)
    assert ship_widget.GetLabel() == "Akira"


def test_ids_are_stable_across_renders(qb_panel):
    first = _body(qb_panel.render_payload())
    qb_panel.invalidate()
    second = _body(qb_panel.render_payload())
    assert first["categories"][0]["id"] == second["categories"][0]["id"]
    assert first["categories"][0]["ships"][0]["id"] == second["categories"][0]["ships"][0]["id"]


def test_expand_event_toggles_category_expanded(qb_panel):
    body = _body(qb_panel.render_payload())
    cat_id = body["categories"][0]["id"]
    assert qb_panel.dispatch_event("expand:" + str(cat_id)) is True
    body2 = _body(qb_panel.render_payload())
    assert body2["categories"][0]["expanded"] is True
    # Toggle back.
    assert qb_panel.dispatch_event("expand:" + str(cat_id)) is True
    body3 = _body(qb_panel.render_payload())
    assert body3["categories"][0]["expanded"] is False


def test_expand_only_re_emits_on_change(qb_panel):
    cat_id = _body(qb_panel.render_payload())["categories"][0]["id"]
    assert qb_panel.render_payload() is None  # dedup
    qb_panel.dispatch_event("expand:" + str(cat_id))
    assert qb_panel.render_payload() is not None  # expand changed snapshot


def test_click_ship_event_is_handled(qb_panel):
    body = _body(qb_panel.render_payload())
    ship_id = body["categories"][0]["ships"][0]["id"]
    assert qb_panel.dispatch_event("click-ship:" + str(ship_id)) is True


# ---- T3: dispatch back to the SDK (SendActivationEvent) --------------------

def test_click_ship_fires_button_activation(qb_panel):
    body = _body(qb_panel.render_payload())
    ship_id = body["categories"][0]["ships"][0]["id"]
    fired = _spy_activation(qb_panel.widget_for_id(ship_id))
    qb_panel.dispatch_event("click-ship:" + str(ship_id))
    assert fired == [True]


def test_click_ship_marks_it_selected(qb_panel):
    body = _body(qb_panel.render_payload())
    ships = body["categories"][0]["ships"]
    # Nothing selected initially.
    assert all(s["selected"] is False for s in ships)
    target = ships[1]
    qb_panel.dispatch_event("click-ship:" + str(target["id"]))
    body2 = _body(qb_panel.render_payload())
    ships2 = body2["categories"][0]["ships"]
    assert ships2[1]["selected"] is True
    assert ships2[0]["selected"] is False


def test_selecting_another_ship_moves_the_highlight(qb_panel):
    ships = _body(qb_panel.render_payload())["categories"][0]["ships"]
    qb_panel.dispatch_event("click-ship:" + str(ships[0]["id"]))
    qb_panel.dispatch_event("click-ship:" + str(ships[1]["id"]))
    ships2 = _body(qb_panel.render_payload())["categories"][0]["ships"]
    assert ships2[0]["selected"] is False
    assert ships2[1]["selected"] is True


def test_add_enemy_activates_add_enemy_button(qb_panel):
    fired = _spy_activation(qb_panel._qb_module.g_pAddEnemyButton)
    assert qb_panel.dispatch_event("add-enemy") is True
    assert fired == [True]


def test_add_friend_activates_add_friend_button(qb_panel):
    fired = _spy_activation(qb_panel._qb_module.g_pAddFriendButton)
    assert qb_panel.dispatch_event("add-friend") is True
    assert fired == [True]


# ---- stacked-roster quantity controls (inc / dec / remove) ----------------

def test_roster_inc_enemy_sets_type_and_fires_add(qb_panel):
    # 'BOP' reverse-maps to enemy type 7; inc sets it and fires Add As Enemy.
    fired = _spy_activation(qb_panel._qb_module.g_pAddEnemyButton)
    assert qb_panel.dispatch_event("roster-inc:enemy:BOP") is True
    assert qb_panel._qb_module.g_iSelectedShipType == 7
    assert fired == [True]


def test_roster_inc_friendly_sets_type_and_fires_add(qb_panel):
    fired = _spy_activation(qb_panel._qb_module.g_pAddFriendButton)
    assert qb_panel.dispatch_event("roster-inc:friendly:Galaxy") is True
    assert qb_panel._qb_module.g_iSelectedShipType == 3
    assert fired == [True]


def test_roster_inc_unresolvable_label_is_noop(qb_panel):
    fired = _spy_activation(qb_panel._qb_module.g_pAddEnemyButton)
    # Not in the enemy table -> no type set, add button not fired.
    assert qb_panel.dispatch_event("roster-inc:enemy:Nonesuch") is True
    assert qb_panel._qb_module.g_iSelectedShipType == -1
    assert fired == []


def test_roster_dec_selects_target_then_fires_delete(qb_panel):
    # dec selects the first matching roster button (SelectEnemy), then Delete.
    bop_btn = qb_panel._qb_module.g_pEnemyMenu.GetFirstChild()
    selected = _spy_activation(bop_btn)
    deleted = _spy_activation(qb_panel._qb_module.g_pDeleteButton)
    assert qb_panel.dispatch_event("roster-dec:enemy:BOP") is True
    assert selected == [True]
    assert deleted == [True]


def test_roster_dec_no_match_does_not_fire_delete(qb_panel):
    deleted = _spy_activation(qb_panel._qb_module.g_pDeleteButton)
    assert qb_panel.dispatch_event("roster-dec:enemy:Nonesuch") is True
    assert deleted == []


def test_roster_remove_deletes_each_copy(qb_panel):
    # Three BOPs -> remove-all drives Delete once per copy (bounded by count;
    # the stub doesn't actually pop, so the bound is what stops the loop).
    enemy = qb_panel._qb_module.g_pEnemyMenu
    enemy.AddChild(_ship_button("BOP"))
    enemy.AddChild(_ship_button("BOP"))
    deleted = _spy_activation(qb_panel._qb_module.g_pDeleteButton)
    assert qb_panel.dispatch_event("roster-remove:enemy:BOP") is True
    assert deleted == [True, True, True]


def test_roster_action_url_decodes_label(qb_panel):
    # Labels with spaces arrive percent-encoded from the JS side.
    enemy = qb_panel._qb_module.g_pEnemyMenu
    spaced = _ship_button("Negh Var")
    enemy.AddChild(spaced)
    qb_panel._qb_module.g_dEnemyShipTypeToDetails[11] = [
        "Negh Var", "Negh Var", "x", "QuickBattleAI", "Enemy"]
    fired = _spy_activation(qb_panel._qb_module.g_pAddEnemyButton)
    assert qb_panel.dispatch_event("roster-inc:enemy:Negh%20Var") is True
    assert qb_panel._qb_module.g_iSelectedShipType == 11
    assert fired == [True]


def test_roster_action_url_decodes_apostrophe_label(qb_panel):
    # Apostrophe names (e.g. "Vor'cha") arrive as %27 from the JS side so the
    # apostrophe can't terminate the onclick string literal; unquote restores it.
    enemy = qb_panel._qb_module.g_pEnemyMenu
    enemy.AddChild(_ship_button("Vor'cha"))
    qb_panel._qb_module.g_dEnemyShipTypeToDetails[12] = [
        "Vorcha", "Vor'cha", "x", "QuickBattleAI", "Enemy"]
    deleted = _spy_activation(qb_panel._qb_module.g_pDeleteButton)
    assert qb_panel.dispatch_event("roster-dec:enemy:Vor%27cha") is True
    assert deleted == [True]


def test_roster_unknown_side_returns_false(qb_panel):
    assert qb_panel.dispatch_event("roster-inc:bogus:BOP") is False
    assert qb_panel.dispatch_event("roster-dec:bogus:BOP") is False
    assert qb_panel.dispatch_event("roster-remove:bogus:BOP") is False


# ---- Player ship: current display + Set As Player Ship action -------------

def test_current_player_ship_name_in_payload(qb_panel):
    # g_sPlayerType is the singular current player ship name.
    assert _body(qb_panel.render_payload())["player_ship"] == "Galaxy"


def test_set_player_assigns_selected_ship(qb_panel):
    # Selected catalog ship int 9 maps to "Sovereign" in the friendly table.
    qb_panel._qb_module.g_iSelectedShipType = 9
    recreated = []
    qb_panel._qb_module.RecreatePlayer = lambda: recreated.append(True)
    qb_panel._qb_module.bInSimulation = 0
    assert qb_panel.dispatch_event("set-player") is True
    assert qb_panel._qb_module.g_sPlayerType == "Sovereign"
    assert recreated == []                 # no live swap out of combat


def test_set_player_in_combat_recreates(qb_panel):
    qb_panel._qb_module.g_iSelectedShipType = 9
    recreated = []
    qb_panel._qb_module.RecreatePlayer = lambda: recreated.append(True)
    qb_panel._qb_module.bInSimulation = 1
    assert qb_panel.dispatch_event("set-player") is True
    assert qb_panel._qb_module.g_sPlayerType == "Sovereign"
    assert recreated == [True]             # live swap via RecreatePlayer


def test_set_player_noop_for_nonflyable_selection(qb_panel):
    # A selection not in the friendly table (e.g. a starbase) can't be flown.
    qb_panel._qb_module.g_iSelectedShipType = 999
    recreated = []
    qb_panel._qb_module.RecreatePlayer = lambda: recreated.append(True)
    qb_panel._qb_module.bInSimulation = 1
    assert qb_panel.dispatch_event("set-player") is True
    assert qb_panel._qb_module.g_sPlayerType == "Galaxy"   # unchanged
    assert recreated == []


def test_start_with_callback_fires_and_closes():
    calls = []
    p = QuickBattleSetupPanel(on_start=lambda: calls.append("start"))
    p._qb_module = _stub_qb_module()       # non-empty roster -> Start is live
    p.open()
    assert p.dispatch_event("start") is True
    assert calls == ["start"]
    assert p.is_open() is False


def test_start_without_callback_stays_open(panel):
    panel.open()
    assert panel.dispatch_event("start") is True
    # No callback wired -> handled no-op; the panel does not close.
    assert panel.is_open() is True


def test_close_fires_close_dialog_event(qb_panel, monkeypatch):
    import App
    posted = []
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", lambda e: posted.append(e))
    qb_panel.dispatch_event("close")
    assert qb_panel.is_open() is False
    assert len(posted) == 1
    assert posted[0].GetEventType() == qb_panel._qb_module.ET_CLOSE_DIALOG
    assert posted[0].GetDestination() is qb_panel._qb_module.g_pXO


def test_handle_key_esc_fires_close_dialog_event(qb_panel, monkeypatch):
    """ESC must close the panel the same way the Close button does.

    A bare close() only clears our view flag and leaves the SDK's g_bDialogUp
    set, so _sync_quick_battle_panel reopens the panel on the very next tick.
    ESC therefore has to post ET_CLOSE_DIALOG too.
    """
    import App
    posted = []
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", lambda e: posted.append(e))
    qb_panel.handle_key_esc()
    assert qb_panel.is_open() is False
    assert len(posted) == 1
    assert posted[0].GetEventType() == qb_panel._qb_module.ET_CLOSE_DIALOG
    assert posted[0].GetDestination() is qb_panel._qb_module.g_pXO


def test_start_fires_close_dialog_then_callback(monkeypatch):
    import App
    posted = []
    monkeypatch.setattr(App.g_kEventManager, "AddEvent", lambda e: posted.append(e))
    calls = []
    p = QuickBattleSetupPanel(on_start=lambda: calls.append("start"))
    p._qb_module = _stub_qb_module()
    p.open()
    assert p.dispatch_event("start") is True
    assert calls == ["start"]
    assert p.is_open() is False
    # ET_CLOSE_DIALOG was posted so g_bDialogUp clears (panel won't reopen).
    assert any(e.GetEventType() == p._qb_module.ET_CLOSE_DIALOG for e in posted)


# ---- guard: QuickBattle globals absent ------------------------------------

def test_absent_qb_module_renders_empty_lists(panel):
    # No _qb_module injected and the real module is unimportable headless ->
    # empty lists, no raise.
    panel._qb_module = None
    panel.open()
    body = _body(panel.render_payload())
    assert body["categories"] == []
    assert body["friendly"] == []
    assert body["enemy"] == []


def test_absent_qb_globals_renders_empty_lists(panel):
    # Module present but globals are None (BuildDialog not run yet).
    panel._qb_module = SimpleNamespace(
        g_pShipsPane=None, g_pFriendMenu=None, g_pEnemyMenu=None)
    panel.open()
    body = _body(panel.render_payload())
    assert body["categories"] == []
    assert body["friendly"] == []
    assert body["enemy"] == []


# ---- Start gating: disabled until a ship is on a roster -------------------

def test_can_start_true_when_roster_has_ships(qb_panel):
    # The stub seeds friendly=[Galaxy], enemy=[BOP, Warbird].
    assert _body(qb_panel.render_payload())["can_start"] is True


def test_can_start_false_when_rosters_empty(panel):
    panel._qb_module = SimpleNamespace(
        g_pShipsPane=None, g_pFriendMenu=STSubPane(), g_pEnemyMenu=STSubPane())
    panel.open()
    body = _body(panel.render_payload())
    assert body["friendly"] == []
    assert body["enemy"] == []
    assert body["can_start"] is False


def test_start_is_noop_when_rosters_empty():
    calls = []
    p = QuickBattleSetupPanel(on_start=lambda: calls.append("start"))
    p._qb_module = SimpleNamespace(
        g_pFriendMenu=STSubPane(), g_pEnemyMenu=STSubPane())
    p.open()
    # Even with a callback wired, an empty roster makes Start a handled no-op.
    assert p.dispatch_event("start") is True
    assert calls == []
    assert p.is_open() is True
