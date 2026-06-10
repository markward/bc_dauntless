"""Player-ship impulse degradation + drift through _PlayerControl.apply."""
from engine.host_loop import _PlayerControl
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import ShipSubsystem


class _FakeKeys:
    KEY_W = 1; KEY_S = 2; KEY_A = 3; KEY_D = 4; KEY_Q = 5; KEY_E = 6
    KEY_R = 7; KEY_0 = 8
    KEY_1 = 11; KEY_2 = 12; KEY_3 = 13; KEY_4 = 14; KEY_5 = 15
    KEY_6 = 16; KEY_7 = 17; KEY_8 = 18; KEY_9 = 19


class _FakeHost:
    """Minimal host: no keys held, no edges, unless primed."""
    def __init__(self):
        self.keys = _FakeKeys()
        self._pressed = set()
        self._state = set()
    def key_pressed(self, code): return code in self._pressed
    def key_state(self, code): return code in self._state
    def press(self, code): self._pressed.add(code)
    def clear_edges(self): self._pressed.clear()


def _galaxy_player():
    ship = ShipClass_Create("Galaxy")
    ies = ship.GetImpulseEngineSubsystem()
    ies.SetMaxSpeed(6.3)
    ies.SetMaxAccel(1.5)
    ies.SetMaxAngularVelocity(0.28)
    ies.SetMaxAngularAccel(0.12)
    for i in range(3):
        ies.AddChildSubsystem(ShipSubsystem("pod%d" % i))
    return ship


def _disable_pods(ship, count):
    ies = ship.GetImpulseEngineSubsystem()
    for i in range(count):
        ies.GetChildSubsystem(i).SetCondition(0.0)


def test_partial_loss_caps_player_top_speed():
    ship = _galaxy_player()
    ctrl = _PlayerControl()
    h = _FakeHost()
    h.press(h.keys.KEY_9)            # full impulse
    ctrl.apply(ship, 1.0 / 60, h); h.clear_edges()
    _disable_pods(ship, 1)           # f = 2/3
    for _ in range(60 * 20):
        ctrl.apply(ship, 1.0 / 60, h)
    assert abs(ctrl._current_speed - 6.3 * (2.0 / 3.0)) < 1e-2


def test_total_loss_player_drifts_constant_speed():
    ship = _galaxy_player()
    ctrl = _PlayerControl()
    h = _FakeHost()
    h.press(h.keys.KEY_9)
    ctrl.apply(ship, 1.0 / 60, h); h.clear_edges()
    for _ in range(60 * 10):
        ctrl.apply(ship, 1.0 / 60, h)
    speed_before = ctrl._current_speed
    p0 = ship.GetTranslate()
    _disable_pods(ship, 3)           # drift
    for _ in range(60 * 5):
        ctrl.apply(ship, 1.0 / 60, h)
    assert ctrl._drift_velocity is not None
    p1 = ship.GetTranslate()
    travelled = ((p1.x - p0.x) ** 2 + (p1.y - p0.y) ** 2
                 + (p1.z - p0.z) ** 2) ** 0.5
    # 5 s of drift at ~speed_before GU/s
    assert abs(travelled - speed_before * 5.0) < speed_before * 0.05


def test_repair_resumes_player_powered_flight():
    ship = _galaxy_player()
    ctrl = _PlayerControl()
    h = _FakeHost()
    h.press(h.keys.KEY_9)
    ctrl.apply(ship, 1.0 / 60, h); h.clear_edges()
    for _ in range(60 * 10):
        ctrl.apply(ship, 1.0 / 60, h)
    _disable_pods(ship, 3)
    for _ in range(60 * 2):
        ctrl.apply(ship, 1.0 / 60, h)
    assert ctrl._drift_velocity is not None
    ies = ship.GetImpulseEngineSubsystem()
    pod = ies.GetChildSubsystem(0)
    pod.SetCondition(pod.GetMaxCondition())
    ctrl.apply(ship, 1.0 / 60, h)
    assert ctrl._drift_velocity is None
    assert ctrl._current_speed > 0.0
