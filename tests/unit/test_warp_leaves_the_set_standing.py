"""Warping away leaves the set you left standing -- only its render instances go.

BC's region modules expose Initialize / GetSet / Terminate, and `DeleteSet`
appears in all 102 of them only inside `Terminate()`. Nothing in BC's warp path
deletes a set, and no mission calls `Terminate()` -- the bound is the mission
change. Destroying the source set on departure was ours, and E7M3 shows why it
cannot be BC's: it stocks four sensor posts across four star systems at mission
start, for a player who tours them later.

The render teardown is a different call and STAYS (system-frames spec, sec. 3):
it destroys instances, never objects, and returning re-realizes them.
"""
import App
from engine.appc import warp
from engine.appc.sets import SetClass_Create


def setup_function(_):
    # g_kSetManager._sets and the rendered-set name are global and conftest
    # does not auto-clear them; both warp paths refuse to touch the set that is
    # currently rendered, so a stale one would decide this test's outcome.
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()
    warp.configure_warp_hooks(realize=None, teardown=None)


def teardown_function(_):
    App.g_kSetManager._sets.clear()
    App.g_kSetManager.ClearRenderedSet()
    warp.configure_warp_hooks(realize=None, teardown=None)


def _space_set(name):
    pSet = SetClass_Create()
    App.g_kSetManager.AddSet(pSet, name)
    return pSet


def _ship_in(pSet, name):
    ship = App.ShipClass_Create()
    ship.SetName(name)
    pSet.AddObjectToSet(ship, name)
    return ship


def _depart(src):
    ship = _ship_in(src, "player")
    warp._WarpDepartAction(src, ship).Play()
    return ship


def _arrive(src, ship, to):
    dest = _space_set(to)
    App.g_kSetManager.MakeRenderedSet(to)
    warp._ArriveFinalizeAction(src, ship).Play()
    return dest


def test_departure_alone_leaves_the_source_set_standing():
    src = _space_set("Ona1")
    _depart(src)
    assert App.g_kSetManager.GetSet("Ona1") is src


def test_arrival_finalize_alone_leaves_the_source_set_standing():
    """The instant (non-flythrough) path never ran departure; finalize used to
    be its fallback delete."""
    src = _space_set("Ona1")
    ship = _ship_in(src, "player")
    _arrive(src, ship, to="Ona2")
    assert App.g_kSetManager.GetSet("Ona1") is src


def test_content_staged_in_the_source_set_survives_a_full_warp():
    """The property the change exists for: a mission's ship is still there
    when you come back."""
    src = _space_set("Ona1")
    post = _ship_in(src, "Sensor Post 1")
    ship = _depart(src)
    _arrive(src, ship, to="Ona2")
    assert App.g_kSetManager.GetSet("Ona1").GetObject("Sensor Post 1") is post


def test_the_warp_transit_set_is_still_cleaned_up():
    """The tunnel is not a region. Leaking one per warp is a slow leak nobody
    would attribute to this change."""
    src = _space_set("Ona1")
    ship = _depart(src)
    _arrive(src, ship, to="Ona2")
    assert App.g_kSetManager.GetSet(warp._WARP_TRANSIT_SET_NAME) is None


def test_the_render_teardown_still_fires_for_the_source_set():
    """Instances go, the set stays. Without this the left set's Planet
    instance survives and draws in the next system's sky (the reference
    branch's ghost planet)."""
    seen = []
    warp.configure_warp_hooks(teardown=lambda s: seen.append(s.GetName()))
    src = _space_set("Ona1")
    ship = _depart(src)
    _arrive(src, ship, to="Ona2")
    assert "Ona1" in seen
    assert App.g_kSetManager.GetSet("Ona1") is src


def test_departing_a_set_that_is_not_a_region_is_fine():
    """QuickBattle, a mission's own set: no region module, nothing to consult."""
    src = _space_set("QuickBattle")
    ship = _depart(src)
    _arrive(src, ship, to="Ona1")
    assert App.g_kSetManager.GetSet("QuickBattle") is src
