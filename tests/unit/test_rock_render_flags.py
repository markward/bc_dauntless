"""Rock surface flag (rock-class spec §2): rocks never emit hull-hit smoke."""
import App
from tests.unit.test_rock_class import _make

from engine.appc import hull_hit_smoke, particles
from engine.appc.math import TGPoint3


class _RNG:
    """Deterministic App.g_kSystemWrapper.GetRandomNumber stand-in that
    always passes the probability roll, so the ONLY thing that can suppress
    an emit is the rock check."""
    def __init__(self, values, default=0):
        self._values = list(values)
        self._default = default

    def GetRandomNumber(self, n):
        return self._values.pop(0) if self._values else self._default


def test_hull_smoke_skips_rocks(monkeypatch):
    monkeypatch.setattr(particles, "EffectController_GetEffectLevel",
                        lambda: particles.EffectController.HIGH)
    monkeypatch.setattr(hull_hit_smoke.host_io, "world_to_body",
                        lambda iid, p, n: ((0.1, 0.2, 0.3), (0.0, 0.0, 1.0)))
    monkeypatch.setattr(hull_hit_smoke.App, "g_kSystemWrapper", _RNG([0]))
    emits = []
    monkeypatch.setattr(hull_hit_smoke, "_emit_smoke",
                        lambda *a: emits.append(a))

    rock = _make(App.GENUS_ASTEROID)
    hull_hit_smoke.maybe_emit(rock, TGPoint3(0, 0, 0), TGPoint3(0, 0, 1),
                              "torpedo", ship_instances={rock: 7})

    assert emits == []
