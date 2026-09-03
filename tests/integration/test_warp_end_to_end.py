"""End-to-end Stage-1 warp: the production direct-spine path.

The Set Course popup records the destination set-module on the SDK warp button
(host `on_course_set` -> btn.SetDestination). Clicking the Helm "Warp" button
engages the warp spine directly (host `on_warp_engage` -> warp.execute_warp).
Stage 1 deliberately does NOT fire the SDK ET_WARP_BUTTON_PRESSED event or run
WarpPressed (its camera/control work is deferred to Stages 2-3, and running it
live was the cause of a silent no-op).
"""
import App
from engine.appc import warp
from engine.appc.sets import SetClass_Create


def _waypoint(name, set_name, x):
    wp = App.Waypoint_Create(name, set_name, None)
    wp.SetTranslateXYZ(x, 0.0, 0.0); wp.Update(0)


def _setup_player_and_dest():
    App.g_kSetManager._sets.clear()
    warp.configure_warp_hooks(realize=None, teardown=None)
    src = SetClass_Create(); App.g_kSetManager.AddSet(src, "Src")
    player = App.ShipClass_Create(); player.SetName("player")
    src.AddObjectToSet(player, "player")
    App.Game_SetCurrentPlayer(player)
    import types, sys
    mod = types.ModuleType("FakeSys.Dst")
    def Initialize():
        s = SetClass_Create(); App.g_kSetManager.AddSet(s, "Dst")
        _waypoint("Player Start", "Dst", 42.0)
    mod.Initialize = Initialize
    sys.modules["FakeSys.Dst"] = mod
    return src, player


def test_set_course_then_warp_engage_switches_system():
    src, player = _setup_player_and_dest()
    btn = App.STWarpButton_CreateW("Warp")
    App.SortedRegionMenu_SetWarpButton(btn)

    # on_course_set: the popup records the chosen destination module.
    btn.SetDestination("FakeSys.Dst")
    # on_warp_engage: the Helm Warp button click engages the spine directly.
    warp.execute_warp(btn)

    assert App.g_kSetManager.GetSet("Src") is None          # source terminated
    dst = App.g_kSetManager.GetSet("Dst")
    assert dst.GetObject("player") is player                # player moved in
    assert App.g_kSetManager.GetRenderedSet().GetName() == "Dst"
    assert abs(player.GetWorldLocation().x - 42.0) < 1e-3   # placed at Player Start


def test_warp_engage_without_course_is_noop():
    src, player = _setup_player_and_dest()
    btn = App.STWarpButton_CreateW("Warp")  # no destination set
    App.SortedRegionMenu_SetWarpButton(btn)

    warp.execute_warp(btn)

    # No course set -> nothing happens: player stays, destination never loaded.
    assert App.g_kSetManager.GetSet("Src") is src
    assert App.g_kSetManager.GetSet("Dst") is None
    assert src.GetObject("player") is player


# --- a course-less Warp click must not strand the Helm menu ---------------

def test_engaging_without_a_course_leaves_the_helm_menu_alone(monkeypatch):
    """The Helm "Warp" button was clickable with no course set. engage_warp
    greys the Helm menu BEFORE execute_warp, and the matching re-enable is
    scheduled INSIDE the warp sequence — which execute_warp never starts
    without a destination. The menu stayed greyed for the rest of the session.

    Asserted on the Helm menu, not on the warp: a fix that merely skipped the
    warp would still leave the player locked out, which is the actual bug.
    """
    from engine import bridge_officers
    from engine.host_loop import engage_warp

    _setup_player_and_dest()
    btn = App.STWarpButton_CreateW("Warp")          # no destination
    App.SortedRegionMenu_SetWarpButton(btn)

    greyed = []
    monkeypatch.setattr(bridge_officers, "disable_helm_menu",
                        lambda: greyed.append(1))

    engage_warp(btn, None)

    assert greyed == [], "the Helm menu must not be greyed with no course set"


def test_engaging_with_a_course_still_greys_the_helm_menu(monkeypatch):
    """The counterweight: the guard must not disarm the real warp path, which
    depends on the menu being greyed for the duration (BC does the same in
    WarpPressed, HelmMenuHandlers.py:862)."""
    from engine import bridge_officers
    from engine.host_loop import engage_warp

    _setup_player_and_dest()
    btn = App.STWarpButton_CreateW("Warp")
    btn.SetDestination("FakeSys.Dst")
    App.SortedRegionMenu_SetWarpButton(btn)

    greyed = []
    monkeypatch.setattr(bridge_officers, "disable_helm_menu",
                        lambda: greyed.append(1))

    engage_warp(btn, None)

    assert greyed == [1]
    assert App.g_kSetManager.GetRenderedSet().GetName() == "Dst"
