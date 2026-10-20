"""SPIKE (damage redesign): Damage Preview kills the Akira's impulse system
in stages -- controller, then port, then starboard engine."""
from engine.dev_missions import damage_preview as dp


class _Sub:
    def __init__(self, name, children=()):
        self.name, self.children, self.condition = name, list(children), 1.0

    def GetName(self):
        return self.name

    def GetNumChildSubsystems(self):
        return len(self.children)

    def GetChildSubsystem(self, i):
        return self.children[i]

    def SetCondition(self, c):
        self.condition = c


class _Ship:
    def __init__(self):
        self.port, self.star = _Sub("Port Impulse"), _Sub("Star Impulse")
        self.ies = _Sub("Impulse Engines", (self.port, self.star))

    def GetImpulseEngineSubsystem(self):
        return self.ies


def test_steps_destroy_controller_then_port_then_starboard(monkeypatch):
    ship = _Ship()
    monkeypatch.setattr(dp, "_wreck", lambda: ship)
    dp._step_index[0] = 0
    order = []
    for _ in dp._IMPULSE_STEPS:
        dp.DestroyNextImpulseStep(None)
        order.append([s.condition for s in (ship.ies, ship.port, ship.star)])
    assert order == [[0.0, 1.0, 1.0], [0.0, 0.0, 1.0], [0.0, 0.0, 0.0]]
    dp.DestroyNextImpulseStep(None)          # past the last step: no-op
