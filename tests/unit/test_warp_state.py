"""Ship-level warp-state facade. The isinstance guard is load-bearing: a Planet
has no GetWarpEngineSubsystem, so TGObject.__getattr__ hands back a TRUTHY
_Stub whose GetWarpState() != WES_NOT_WARPING is True — a duck-typed predicate
would silently mark every planet in the game as 'warping'."""
import App
import pytest
from engine.appc import warp_state
from engine.appc.planet import Planet_Create
from engine.appc.ships import ShipClass
from engine.appc.subsystems import WarpEngineSubsystem


@pytest.fixture(autouse=True)
def _isolate():
    App.g_kSetManager._sets.clear()
    warp_state.reset()
    yield
    App.g_kSetManager._sets.clear()
    warp_state.reset()


def _ship_with_warp(name="s"):
    s = ShipClass()
    s.SetName(name)
    s.SetWarpEngineSubsystem(WarpEngineSubsystem("Warp Engines"))
    return s


def test_get_state_of_ship_without_warp_subsystem_is_not_warping():
    s = ShipClass()                       # no warp subsystem at all
    assert s.GetWarpEngineSubsystem() is None
    assert warp_state.get_state(s) == WarpEngineSubsystem.WES_NOT_WARPING
    assert warp_state.is_ship_warping(s) is False


def test_set_state_on_ship_without_warp_subsystem_is_a_noop():
    s = ShipClass()
    warp_state.set_state(s, WarpEngineSubsystem.WES_WARPING)   # must not raise
    assert warp_state.is_ship_warping(s) is False


def test_is_ship_warping_tracks_the_subsystem():
    s = _ship_with_warp()
    assert warp_state.is_ship_warping(s) is False
    warp_state.set_state(s, WarpEngineSubsystem.WES_WARPING)
    assert warp_state.is_ship_warping(s) is True
    warp_state.set_state(s, WarpEngineSubsystem.WES_NOT_WARPING)
    assert warp_state.is_ship_warping(s) is False


def test_planet_is_never_warping():
    # THE STUB TRAP. Planet.GetWarpEngineSubsystem() is a truthy _Stub; a
    # duck-typed predicate would report the planet as warping and make every
    # planet, moon and sun in the game non-collidable.
    p = Planet_Create(170.0, "")
    assert warp_state.is_ship_warping(p) is False


def test_tick_warp_states_completes_a_dewarp_across_the_sets():
    from engine.appc.sets import SetClass_Create
    pSet = SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "S")
    s = _ship_with_warp("npc")
    pSet.AddObjectToSet(s, "npc")
    s.GetWarpEngineSubsystem().SetWarpEffectTime(1.0)
    s.GetWarpEngineSubsystem().TransitionToState(
        WarpEngineSubsystem.WES_DEWARP_INITIATED)

    warp_state.tick_warp_states(0.5)
    assert warp_state.is_ship_warping(s) is True

    warp_state.tick_warp_states(0.6)
    assert warp_state.is_ship_warping(s) is False


def test_sync_flythrough_clears_the_state_when_the_warp_animator_stops():
    s = _ship_with_warp()
    warp_state.begin_flythrough(s)
    warp_state.set_state(s, WarpEngineSubsystem.WES_WARPING)

    warp_state.sync_flythrough(True)        # animator still running -> held
    assert warp_state.is_ship_warping(s) is True

    warp_state.sync_flythrough(False)       # animator done -> cleared
    assert warp_state.is_ship_warping(s) is False
    assert warp_state.flythrough_ship() is None


def test_sync_flythrough_without_a_registered_ship_is_a_noop():
    warp_state.sync_flythrough(False)       # must not raise
    assert warp_state.flythrough_ship() is None


def test_reset_drops_the_flythrough_registration():
    s = _ship_with_warp()
    warp_state.begin_flythrough(s)
    warp_state.reset()
    assert warp_state.flythrough_ship() is None


def test_a_second_flythrough_registration_does_not_orphan_the_first_ship():
    # C-1: a single global _flythrough_ship meant registering a second ship
    # (e.g. an NPC warping out mid-align) silently overwrote the first
    # registration. When the animator later stops, sync_flythrough could only
    # ever release the MOST RECENT registrant — leaving the first ship's warp
    # state stuck non-WES_NOT_WARPING forever (permanently non-collidable).
    player = _ship_with_warp("player")
    npc = _ship_with_warp("npc")

    warp_state.begin_flythrough(player)
    warp_state.set_state(player, WarpEngineSubsystem.WES_WARP_INITIATED)

    warp_state.begin_flythrough(npc)
    warp_state.set_state(npc, WarpEngineSubsystem.WES_WARPING)

    warp_state.sync_flythrough(False)   # animator stops: both must release

    assert warp_state.get_state(player) == WarpEngineSubsystem.WES_NOT_WARPING
    assert warp_state.get_state(npc) == WarpEngineSubsystem.WES_NOT_WARPING
    assert warp_state.is_ship_warping(player) is False
    assert warp_state.is_ship_warping(npc) is False


def test_is_flythrough_tracks_registration_of_a_specific_ship():
    player = _ship_with_warp("player")
    npc = _ship_with_warp("npc")
    warp_state.begin_flythrough(player)
    warp_state.begin_flythrough(npc)
    assert warp_state.is_flythrough(player) is True
    assert warp_state.is_flythrough(npc) is True
    warp_state.end_flythrough(npc)
    assert warp_state.is_flythrough(npc) is False
    assert warp_state.is_flythrough(player) is True


def test_end_flythrough_with_a_specific_ship_releases_only_that_ship():
    player = _ship_with_warp("player")
    npc = _ship_with_warp("npc")
    warp_state.begin_flythrough(player)
    warp_state.set_state(player, WarpEngineSubsystem.WES_WARPING)
    warp_state.begin_flythrough(npc)
    warp_state.set_state(npc, WarpEngineSubsystem.WES_WARPING)

    warp_state.end_flythrough(npc)

    assert warp_state.get_state(npc) == WarpEngineSubsystem.WES_NOT_WARPING
    assert warp_state.get_state(player) == WarpEngineSubsystem.WES_WARPING
    assert warp_state.is_flythrough(npc) is False
    assert warp_state.is_flythrough(player) is True
