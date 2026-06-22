import App
from engine.appc import warp
from engine.appc.sets import SetClass_Create


def _make_set(name, with_player_start=True):
    """Build a registered set with a 'Player Start' waypoint."""
    s = SetClass_Create()
    App.g_kSetManager.AddSet(s, name)
    if with_player_start:
        wp = App.Waypoint_Create("Player Start", name, None)
        wp.SetTranslateXYZ(10.0, 20.0, 30.0)
        wp.Update(0)
    return s


def setup_function(_):
    # fresh set manager + registry per test
    App.g_kSetManager._sets.clear()
    warp.configure_warp_hooks(realize=None, teardown=None)


def test_change_rendered_set_loads_and_switches(monkeypatch):
    # A fake destination module that registers a set on Initialize().
    import types, sys
    mod = types.ModuleType("FakeSys.Dest")
    def Initialize():
        _make_set("Dest")
    mod.Initialize = Initialize
    sys.modules["FakeSys.Dest"] = mod
    act = warp.ChangeRenderedSetAction_Create("FakeSys.Dest")
    act.Play()
    assert App.g_kSetManager.GetSet("Dest") is not None
    assert App.g_kSetManager.GetRenderedSet().GetName() == "Dest"


def test_warp_sequence_moves_player_and_terminates_source():
    import types, sys
    src = _make_set("Source")
    player = App.ShipClass_Create()
    player.SetName("player")
    src.AddObjectToSet(player, "player")

    mod = types.ModuleType("FakeSys.Dest2")
    mod.Initialize = lambda: _make_set("Dest2")
    sys.modules["FakeSys.Dest2"] = mod

    seq = warp.WarpSequence_Create(player, "FakeSys.Dest2", 5.0, "Player Start")
    seq.Play()

    assert App.g_kSetManager.GetSet("Source") is None          # source terminated
    dest = App.g_kSetManager.GetSet("Dest2")
    assert dest.GetObject("player") is player                  # player moved in
    assert App.g_kSetManager.GetRenderedSet().GetName() == "Dest2"
    # placed at Player Start
    loc = player.GetWorldLocation()
    assert abs(loc.x - 10.0) < 1e-3
