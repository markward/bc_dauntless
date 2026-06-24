from engine.appc.subsystems import active_impulse_emitters, ShipSubsystem
from engine.appc.math import TGPoint3


class _Ship:
    def __init__(self, ies):
        self._ies = ies
        self._loc = TGPoint3(10.0, 20.0, 30.0)

    def GetImpulseEngineSubsystem(self):
        return self._ies

    def GetWorldLocation(self):
        return self._loc

    def GetWorldRotation(self):
        return None        # identity: world mount == ship_loc + local offset


def _pod(name, x, y, z, radius, disabled=False, destroyed=False):
    s = ShipSubsystem(name)
    s._radius = radius
    s._position = TGPoint3(x, y, z)
    # IsDestroyed() checks _destroyed flag directly — works as-is.
    # IsDisabled() is condition-based: condition <= _disabled_percentage * max_condition.
    # Default: _disabled_percentage=0.25, _max_condition=1.0 → threshold=0.25.
    # Set _condition=0.1 to trigger disabled without tripping destroyed (which needs condition==0).
    if destroyed:
        s._destroyed = True
    elif disabled:
        s._condition = 0.1   # 0.1 <= 0.25 → IsDisabled()=1, IsDestroyed()=0
    return s


def _make_ies(pods, disabled=False):
    ies = ShipSubsystem("Impulse Engines")
    if disabled:
        ies._condition = 0.1  # IsDisabled()=1
    ies._position = TGPoint3(0.0, -0.98, -0.45)
    ies._radius = 0.25
    for p in pods:
        ies.AddChildSubsystem(p)
    return ies


def test_no_player_returns_empty():
    assert active_impulse_emitters(None) == []


def test_no_impulse_subsystem_returns_empty():
    class _S:
        def GetImpulseEngineSubsystem(self):
            return None
    assert active_impulse_emitters(_S()) == []


def test_offline_master_returns_empty():
    ies = _make_ies([_pod("Port", -1.0, 0.0, 0.0, 0.25)], disabled=True)
    assert active_impulse_emitters(_Ship(ies)) == []


def test_two_online_pods_yield_two_emitters():
    pods = [_pod("Port", -1.0, 0.0, 0.0, 0.25),
            _pod("Star", +1.0, 0.0, 0.0, 0.40)]
    ems = active_impulse_emitters(_Ship(_make_ies(pods)))
    assert len(ems) == 2
    sizes = sorted(e["size"] for e in ems)
    assert sizes == [0.25, 0.40]
    assert len({e["key"] for e in ems}) == 2            # distinct keys
    # world mount = ship_loc + local (identity rotation)
    port = next(e for e in ems if e["size"] == 0.25)
    assert port["pos"] == (10.0 - 1.0, 20.0, 30.0)


def test_offline_pod_is_skipped():
    pods = [_pod("Port", -1.0, 0.0, 0.0, 0.25, disabled=True),
            _pod("Star", +1.0, 0.0, 0.0, 0.40)]
    ems = active_impulse_emitters(_Ship(_make_ies(pods)))
    assert len(ems) == 1
    assert ems[0]["size"] == 0.40


def test_destroyed_pod_is_skipped():
    pods = [_pod("Port", -1.0, 0.0, 0.0, 0.25, destroyed=True),
            _pod("Star", +1.0, 0.0, 0.0, 0.40)]
    ems = active_impulse_emitters(_Ship(_make_ies(pods)))
    assert [e["size"] for e in ems] == [0.40]


def test_no_child_pods_falls_back_to_master():
    ies = _make_ies([])                                  # online master, no pods
    ems = active_impulse_emitters(_Ship(ies))
    assert len(ems) == 1
    assert ems[0]["pos"] == (10.0 + 0.0, 20.0 - 0.98, 30.0 - 0.45)
    assert ems[0]["size"] == 0.25
