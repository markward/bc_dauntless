"""engine.warp_preload.Preload -- one warp's destination work, spread over the tunnel."""
import pytest

from engine import warp_preload
from engine.warp_preload import Preload


class FakeRenderer:
    def __init__(self, prebuilt=False, pending=0):
        self.prebuilt = prebuilt
        self.pending = pending
        self.prebuild_calls = []
        self.prebuilt_calls = []
        self.prefetch_calls = 0
        self.pump_calls = []

    def system_nebula_prebuild(self, profile):
        self.prebuild_calls.append(profile)

    def system_nebula_prebuilt(self, profile):
        self.prebuilt_calls.append(profile)
        return self.prebuilt

    def far_prefetch_atlases(self):
        self.prefetch_calls += 1

    def far_pump_atlas_uploads(self, n):
        self.pump_calls.append(n)
        return self.pending


class Ship:
    def __init__(self, name):
        self.name = name

    def GetName(self):
        return self.name


PROFILE = {"table": [1, 2]}


@pytest.fixture(autouse=True)
def _profile(monkeypatch):
    monkeypatch.setattr("engine.system_haze.profile_dict_for_set",
                        lambda s: PROFILE if s == "Mapped" else None)


def make(dest="Mapped", renderer=None, planets=(), ships=(), haze=True, **kw):
    r = renderer or FakeRenderer(prebuilt=True)
    log = []
    ship_list = list(ships)
    p = Preload(dest, renderer=r, haze_enabled=lambda: haze,
                planet_models=lambda s: list(planets),
                load_planet=lambda m: log.append(("planet", m)),
                ships=lambda s: list(ship_list),
                load_ship=lambda sh: log.append(("ship", sh.name)), **kw)
    return p, r, log, ship_list


def test_first_step_kicks_haze_and_atlases():
    p, r, _, _ = make()
    p.step()
    p.step()
    p.ready()
    assert r.prebuild_calls == [PROFILE]
    assert r.prefetch_calls == 1
    assert r.prebuilt_calls[0] is r.prebuild_calls[0]


def test_one_gl_load_per_step():
    p, r, log, _ = make(planets=["a", "b", "c"], ships=[Ship("s1"), Ship("s2")])
    for i in range(5):
        p.step()
        assert len(log) == i + 1
    assert [k for k, _ in log] == ["planet"] * 3 + ["ship"] * 2
    assert r.pump_calls == [2] * 5


def test_ready_waits_for_haze():
    r = FakeRenderer(prebuilt=False)
    p, r, _, _ = make(renderer=r)
    p.step()
    assert not p.ready()
    r.prebuilt = True
    assert p.ready()


def test_haze_not_awaited_when_gate_closed():
    r = FakeRenderer(prebuilt=False)
    p, r, _, _ = make(renderer=r, haze=False)
    p.step()
    assert p.ready()
    assert r.prebuild_calls == []


def test_unmapped_destination_is_ready_immediately():
    r = FakeRenderer(prebuilt=False)
    p, r, _, _ = make(dest="Unmapped", renderer=r)
    p.step()
    assert p.ready()
    assert r.prebuild_calls == []


def test_cached_haze_is_ready_on_first_step():
    p, r, _, _ = make(renderer=FakeRenderer(prebuilt=True))
    p.step()
    assert p.ready()


def test_ready_waits_for_atlases():
    p, r, _, _ = make(renderer=FakeRenderer(prebuilt=True, pending=3))
    p.step()
    assert not p.ready()
    r.pending = 0
    p.step()
    assert p.ready()


def test_atlases_false_never_touches_far_bindings():
    r = FakeRenderer(prebuilt=True, pending=9)
    p, r, _, _ = make(renderer=r, atlases=False)
    p.step()
    assert p.ready()
    assert r.prefetch_calls == 0 and r.pump_calls == []


def test_replan_adds_ships_created_by_the_mission_change():
    p, r, log, ships = make(planets=["a"])
    p.step()
    p.step()
    assert p.ready()
    ships.extend([Ship("s1"), Ship("s2")])
    p.replan()
    assert not p.ready()
    p.step()
    p.step()
    assert log == [("planet", "a"), ("ship", "s1"), ("ship", "s2")]
    assert p.ready()


def test_pending_names_the_unfinished_items():
    p, r, _, _ = make(renderer=FakeRenderer(prebuilt=False, pending=2),
                      planets=["pl"], ships=[Ship("sh")])
    p.step()
    out = p.pending()
    assert not any("pl" in s for s in out)  # loaded by the first step
    assert any("sh" in s for s in out)
    assert any("haze" in s for s in out)
    assert any("atlas" in s for s in out)


def test_begin_replaces_the_active_preload():
    deps = dict(renderer=FakeRenderer(), haze_enabled=lambda: True,
                planet_models=lambda s: [], load_planet=lambda m: None,
                ships=lambda s: [], load_ship=lambda s: None)
    a = warp_preload.begin("Mapped", **deps)
    b = warp_preload.begin("Mapped", **deps)
    assert warp_preload.active() is b and b is not a


def test_end_clears_active():
    deps = dict(renderer=FakeRenderer(), haze_enabled=lambda: True,
                planet_models=lambda s: [], load_planet=lambda m: None,
                ships=lambda s: [], load_ship=lambda s: None)
    warp_preload.begin("Mapped", **deps)
    warp_preload.end()
    assert warp_preload.active() is None


def test_a_failing_loader_does_not_block_ready(monkeypatch):
    logged = []
    monkeypatch.setattr("engine.dev_mode.log_swallowed",
                        lambda ctx, exc: logged.append(ctx))
    r = FakeRenderer(prebuilt=True)

    def boom(m):
        raise RuntimeError("x")

    p = Preload("Mapped", renderer=r, haze_enabled=lambda: True,
                planet_models=lambda s: ["bad"], load_planet=boom,
                ships=lambda s: [], load_ship=lambda s: None)
    p.step()
    p.step()
    assert p.ready()
    assert len(logged) == 1
