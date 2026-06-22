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


def _player_in_set(name):
    src = _make_set(name)
    player = App.ShipClass_Create()
    player.SetName("player")
    src.AddObjectToSet(player, "player")
    return player, src


def test_none_destination_is_noop():
    # A None warp destination => harmless no-op: no exception, player stays in
    # its current set, no rendered-set crash. Mirrors BC's pcDestModule guard.
    player, src = _player_in_set("Home")
    warp.WarpSequence_Create(player, None).Play()
    assert App.g_kSetManager.GetSet("Home") is src        # source intact
    assert src.GetObject("player") is player              # player unmoved


def test_empty_destination_is_noop():
    player, src = _player_in_set("Home2")
    warp.WarpSequence_Create(player, "").Play()
    assert App.g_kSetManager.GetSet("Home2") is src
    assert src.GetObject("player") is player


def test_whitespace_destination_is_noop():
    player, src = _player_in_set("Home3")
    warp.WarpSequence_Create(player, "   ").Play()
    assert App.g_kSetManager.GetSet("Home3") is src
    assert src.GetObject("player") is player


def test_bad_module_still_raises():
    # Fail loud: a non-empty but unimportable module must still raise.
    player, _ = _player_in_set("Home4")
    import pytest
    with pytest.raises(Exception):
        warp.WarpSequence_Create(player, "FakeSys.DoesNotExist").Play()


def test_warp_silences_looping_weapon_sfx():
    # A phaser bank firing at the moment of warp must be StopFiring()'d so its
    # looped SFX doesn't carry into the new system.
    class _Bank:
        def __init__(self):
            self.stopped = False
        def StopFiring(self):
            self.stopped = True

    class _WSys:
        def __init__(self, banks):
            self._b = banks
        def GetNumChildSubsystems(self):
            return len(self._b)
        def GetChildSubsystem(self, i):
            return self._b[i]

    import types, sys
    src = _make_set("SrcW")
    player = App.ShipClass_Create()
    player.SetName("player")
    src.AddObjectToSet(player, "player")
    bank = _Bank()
    player._phaser_system = _WSys([bank])

    mod = types.ModuleType("FakeSys.DestW")
    mod.Initialize = lambda: _make_set("DestW")
    sys.modules["FakeSys.DestW"] = mod

    warp.WarpSequence_Create(player, "FakeSys.DestW", 0.0, "Player Start").Play()
    assert bank.stopped is True  # phaser loop silenced on warp out
