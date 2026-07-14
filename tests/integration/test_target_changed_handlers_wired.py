"""ET_TARGET_WAS_CHANGED end-to-end: the real SDK handlers actually RUN.

test_target_was_changed_event.py (unit) proves the event fires and that a
hand-built AI preprocessor reacts. It does NOT prove the real bridge-menu
handlers work, because none of the bridge-load integration tests that wire
HelmMenuHandlers.SetPlayer / ScienceMenuHandlers.SetPlayer (which register
the real TargetChanged bodies on the player) ever call SetTarget on that
wired player afterwards -- so those handler BODIES had never once executed
in this engine, even after Task 9b made the event itself real.

engine/appc/events.py:311 TGEventHandlerObject.ProcessEvent is deliberately
UNGUARDED (see its docstring) -- a raise inside a handler propagates and
fails the test that triggers it. That's exactly the property this test
leans on: SetTarget() below either runs Helm.TargetChanged,
Science.TargetChanged and E1M2.TargetChanged clean, or the test goes red.

Boots the real bridge/mission via host_loop._init_mission (real LoadBridge.Load,
real Bridge.HelmMenuHandlers / Bridge.ScienceMenuHandlers CreateMenus, real
Maelstrom.Episode1.E1M2.E1M2 mission init), matching the convention of the
other host_loop._init_mission integration tests (test_e1m2_orbit_haven.py).
"""
import App
from engine import host_loop
from tests.integration.test_sdk_bridge_load import _fresh_world

E1M2_MODULE = "Maelstrom.Episode1.E1M2.E1M2"


def _target_changed_handler_names(player):
    """Every qualified handler name registered on the player under
    ET_TARGET_WAS_CHANGED -- the event ShipClass.SetTarget actually fires.
    (SetPlayer also registers '.TargetChanged' under App.ET_SET_TARGET, which
    is an UNDEFINED App-module constant -- rank 42 in docs/stub_heatmap.md --
    so each of those registrations lands under its own fresh id()-hashed
    _NamedStub key and is neither reachable again nor ever fired; it is
    irrelevant to this event and deliberately excluded here.)"""
    return list(player._handlers.get(App.ET_TARGET_WAS_CHANGED, []))


def test_real_target_changed_handlers_registered_on_player():
    _fresh_world()
    host_loop._init_mission(E1M2_MODULE)

    import MissionLib
    player = MissionLib.GetPlayer()
    assert player is not None

    names = _target_changed_handler_names(player)
    assert names.count("Bridge.HelmMenuHandlers.TargetChanged") == 2
    assert names.count("Bridge.ScienceMenuHandlers.TargetChanged") == 2
    assert names.count("Maelstrom.Episode1.E1M2.E1M2.TargetChanged") == 1
    assert len(names) == 5


def test_set_target_runs_every_real_handler_body_without_raising():
    """Not vacuous: before SetTarget, the Helm 'Intercept' and Science 'Scan
    Target' buttons are created SetDisabled() (HelmMenuHandlers.py:223,
    ScienceMenuHandlers.py:84). Calling SetTarget on a real, scannable set
    object must run the real handler bodies and flip both to enabled --
    proving TargetChanged actually executed, not just that nothing raised."""
    import Bridge.BridgeUtils as BridgeUtils

    _fresh_world()
    mission, episode, game, mod = host_loop._init_mission(E1M2_MODULE)

    import MissionLib
    player = MissionLib.GetPlayer()
    pSet = App.g_kSetManager.GetSet("Vesuvi6")
    assert player.GetContainingSet() is pSet
    haven = pSet.GetObject("Haven")
    assert haven is not None
    assert player.GetTarget() is None

    helm_menu = BridgeUtils.GetBridgeMenu("Helm")
    science_menu = BridgeUtils.GetBridgeMenu("Science")
    intercept_button = helm_menu.GetButtonW("Intercept")
    scan_target_button = science_menu.GetButtonW("Scan Target")
    assert intercept_button.IsEnabled() == 0
    assert scan_target_button.IsEnabled() == 0

    # Deliberately UNguarded dispatch (events.py:311) -- if any of Helm's,
    # Science's, or E1M2's TargetChanged raises, this call raises and the
    # test goes red right here.
    player.SetTarget(haven)

    assert intercept_button.IsEnabled() == 1, "HelmMenuHandlers.TargetChanged did not run"
    assert scan_target_button.IsEnabled() == 1, "ScienceMenuHandlers.TargetChanged did not run"
