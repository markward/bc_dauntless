"""Developer "Collision Sim" mission: the player Galaxy parked just above a
STATIC Romulan Warbird so a slow roll or pitch grinds the saucer into it —
a reproducible low-speed contact for judging collision scuffs live.

Only the mission's own decisions are pinned: which ships, that the Warbird
is immobile, and the measured placement. Ship creation and the set are
stubbed at the SDK boundary."""
import pytest

from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass


class _Group:
    def __init__(self):
        self.names = []
    def AddName(self, n):
        self.names.append(n)


class _Mission:
    def __init__(self):
        self.friendlies = _Group()
    def GetFriendlyGroup(self):
        return self.friendlies


@pytest.fixture
def spawned(monkeypatch):
    import MissionLib, loadspacehelper, LoadBridge, App
    import Systems.QuickBattle.QuickBattleRegion as region
    made = {}

    def _player(name, pSet, label, _):
        s = ShipClass(); s.SetName(label); made["player"] = (name, s); return s

    def _ship(name, pSet, label, _):
        s = ShipClass(); s.SetName(label); made["npc"] = (name, s); return s

    monkeypatch.setattr(MissionLib, "CreatePlayerShip", _player)
    monkeypatch.setattr(loadspacehelper, "CreateShip", _ship)
    monkeypatch.setattr(LoadBridge, "Load", lambda name: made.setdefault("bridge", name))
    monkeypatch.setattr(region, "Initialize", lambda: None)
    monkeypatch.setattr(App.g_kSetManager, "GetSet", lambda name: object(), raising=False)
    return made


def test_player_is_a_galaxy_on_its_own_bridge_at_the_origin(spawned):
    from engine.dev_missions import collision_sim
    collision_sim.Initialize(_Mission())
    name, ship = spawned["player"]
    assert name == "Galaxy" and spawned["bridge"] == "GalaxyBridge"
    p = ship.GetWorldLocation()
    assert (p.x, p.y, p.z) == (0.0, 0.0, 0.0)


def test_warbird_is_static_and_parked_the_measured_gap_below(spawned):
    from engine.dev_missions import collision_sim
    collision_sim.Initialize(_Mission())
    name, warbird = spawned["npc"]
    assert name == "Warbird"
    assert warbird.IsImmobile(), "the target must be a fixed anchor (SetStatic)"
    p = warbird.GetWorldLocation()
    # Galaxy lowest point -1.07 GU, Warbird highest +1.53 GU, 0.4 GU clearance
    # (measured with dump_bounds; see the mission's comment).
    assert (p.x, p.y) == (0.0, 0.0)
    assert p.z == pytest.approx(-(1.07 + 1.53 + collision_sim.CLEARANCE_GU))
    assert collision_sim.CLEARANCE_GU == 0.4


def test_both_ships_are_friendly_so_nothing_shoots(spawned):
    from engine.dev_missions import collision_sim
    m = _Mission()
    collision_sim.Initialize(m)
    assert set(m.friendlies.names) == {"Player", "Anvil"}
