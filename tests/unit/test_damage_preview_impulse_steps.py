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
    killed = []
    from engine.appc import ship_death
    monkeypatch.setattr(ship_death, "begin", lambda s: killed.append(s))
    for _ in dp._IMPULSE_STEPS:
        dp.DestroyNextImpulseStep(None)
        order.append([s.condition for s in (ship.ies, ship.port, ship.star)])
    assert order[:3] == [[0.0, 1.0, 1.0], [0.0, 0.0, 1.0], [0.0, 0.0, 0.0]]
    assert killed == [ship]                  # the last step kills the wreck
    dp.DestroyNextImpulseStep(None)          # past the last step: no-op


def test_death_delay_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("DAUNTLESS_DAMAGE_PREVIEW_DEATH_S", "30")
    assert dp._death_delay_s() == 30.0
    monkeypatch.setenv("DAUNTLESS_DAMAGE_PREVIEW_DEATH_S", "junk")
    assert dp._death_delay_s() == 4.0


def test_wreck_distance_comes_from_the_environment(monkeypatch):
    monkeypatch.delenv("DAUNTLESS_DAMAGE_PREVIEW_DISTANCE_GU", raising=False)
    assert dp._wreck_distance_gu() == 6.0
    monkeypatch.setenv("DAUNTLESS_DAMAGE_PREVIEW_DISTANCE_GU", "2.5")
    assert dp._wreck_distance_gu() == 2.5
    monkeypatch.setenv("DAUNTLESS_DAMAGE_PREVIEW_DISTANCE_GU", "0.2")
    assert dp._wreck_distance_gu() == 1.5
    monkeypatch.setenv("DAUNTLESS_DAMAGE_PREVIEW_DISTANCE_GU", "junk")
    assert dp._wreck_distance_gu() == 6.0


def test_first_step_delay_comes_from_the_environment(monkeypatch):
    monkeypatch.delenv("DAUNTLESS_DAMAGE_PREVIEW_FIRST_S", raising=False)
    monkeypatch.delenv("DAUNTLESS_DAMAGE_PREVIEW_DEATH_S", raising=False)
    assert dp._step_delays() == [3.0, 1.5, 1.5, 4.0]   # today's timeline
    monkeypatch.setenv("DAUNTLESS_DAMAGE_PREVIEW_FIRST_S", "45")
    assert dp._step_delays() == [45.0, 1.5, 1.5, 4.0]  # an undamaged window first
    monkeypatch.setenv("DAUNTLESS_DAMAGE_PREVIEW_FIRST_S", "-2")
    assert dp._step_delays()[0] == 0.0
    monkeypatch.setenv("DAUNTLESS_DAMAGE_PREVIEW_FIRST_S", "junk")
    assert dp._step_delays()[0] == 3.0


class _Wrapper:
    def __init__(self):
        self.seeds = []

    def SetRandomSeed(self, n):
        self.seeds.append(n)


def test_seed_from_the_environment_seeds_the_game_rng(monkeypatch):
    import App
    fake = _Wrapper()
    monkeypatch.setattr(App, "g_kSystemWrapper", fake)
    monkeypatch.delenv("DAUNTLESS_DAMAGE_PREVIEW_SEED", raising=False)
    assert dp._apply_seed() is None
    assert fake.seeds == []                  # unset: the RNG is left alone
    monkeypatch.setenv("DAUNTLESS_DAMAGE_PREVIEW_SEED", "1234")
    assert dp._apply_seed() == 1234
    assert fake.seeds == [1234]
    monkeypatch.setenv("DAUNTLESS_DAMAGE_PREVIEW_SEED", "junk")
    assert dp._apply_seed() is None
    assert fake.seeds == [1234]              # junk: unseeded, not a crash


def test_seed_makes_the_death_cascade_rolls_repeat(monkeypatch):
    """The cascade rolls through App.g_kSystemWrapper.GetRandomNumber
    (death_cascade._rand): one seed, one sequence."""
    from engine.appc import death_cascade
    monkeypatch.setenv("DAUNTLESS_DAMAGE_PREVIEW_SEED", "77")
    dp._apply_seed()
    first = [death_cascade._rand(1000) for _ in range(8)]
    dp._apply_seed()
    assert [death_cascade._rand(1000) for _ in range(8)] == first
