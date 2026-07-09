import types
import pytest

from engine.appc import hull_hit_smoke, particles
from engine.appc.math import TGPoint3


class _RNG:
    """Deterministic App.g_kSystemWrapper.GetRandomNumber stand-in.
    Returns queued values in order; falls back to `default` when drained."""
    def __init__(self, values, default=0):
        self._values = list(values)
        self._default = default
        self.calls = []

    def GetRandomNumber(self, n):
        self.calls.append(n)
        return self._values.pop(0) if self._values else self._default


@pytest.fixture
def captured(monkeypatch):
    """Capture the CreateSmokeHigh call args; return a dict updated on emit."""
    box = {}

    def fake_create(fVelocity, fLife, fSize, pEmitFrom, kEmitPos, kEmitDir, pAttachTo):
        box.update(dict(fVelocity=fVelocity, fLife=fLife, fSize=fSize,
                        emit_from=pEmitFrom, emit_pos=kEmitPos, emit_dir=kEmitDir,
                        attach_to=pAttachTo))
        return types.SimpleNamespace(Start=lambda: box.__setitem__("started", True))

    fake_effects = types.SimpleNamespace(CreateSmokeHigh=fake_create)
    monkeypatch.setitem(__import__("sys").modules, "Effects", fake_effects)
    # Detail defaults HIGH; world_to_body returns a fixed body anchor.
    monkeypatch.setattr(particles, "EffectController_GetEffectLevel",
                        lambda: particles.EffectController.HIGH)
    monkeypatch.setattr(hull_hit_smoke.host_io, "world_to_body",
                        lambda iid, p, n: ((0.1, 0.2, 0.3), (0.0, 0.0, 1.0)))
    return box


def _emit(rng_values, weapon, monkeypatch, ship_instances=None):
    if ship_instances is None:
        ship_instances = {"ship": 7}
    rng = _RNG(rng_values)
    monkeypatch.setattr(hull_hit_smoke.App, "g_kSystemWrapper", rng)
    hull_hit_smoke.maybe_emit(
        "ship", TGPoint3(5.0, 6.0, 7.0), TGPoint3(0.0, 1.0, 0.0),
        weapon, ship_instances=ship_instances)
    return rng


def test_torpedo_emits_below_threshold(captured, monkeypatch):
    # roll 1 < 2  -> emit ; then fLife roll 5 -> 2.0 + 0.5
    _emit([1, 5], "torpedo", monkeypatch)
    assert captured.get("started") is True
    assert captured["fVelocity"] == 0.2
    assert captured["fSize"] == 0.3
    assert captured["fLife"] == pytest.approx(2.5)
    assert captured["emit_pos"] == (0.1, 0.2, 0.3)      # body-frame anchor
    assert captured["emit_dir"] == (0.0, 0.0, 1.0)
    assert captured["emit_from"] == "ship"


def test_torpedo_silent_at_threshold(captured, monkeypatch):
    _emit([2], "torpedo", monkeypatch)                  # 2 >= 2 -> no emit
    assert "started" not in captured


def test_phaser_threshold_is_three(captured, monkeypatch):
    _emit([2, 0], "phaser", monkeypatch)                # 2 < 3 -> emit
    assert captured.get("started") is True


def test_unknown_weapon_never_emits(captured, monkeypatch):
    _emit([0], None, monkeypatch)
    assert "started" not in captured


def test_detail_below_medium_suppresses(captured, monkeypatch):
    monkeypatch.setattr(particles, "EffectController_GetEffectLevel",
                        lambda: particles.EffectController.LOW)
    _emit([0], "torpedo", monkeypatch)
    assert "started" not in captured


def test_missing_normal_skips(captured, monkeypatch):
    rng = _RNG([0, 0])
    monkeypatch.setattr(hull_hit_smoke.App, "g_kSystemWrapper", rng)
    hull_hit_smoke.maybe_emit(
        "ship", TGPoint3(5.0, 6.0, 7.0), None, "torpedo",
        ship_instances={"ship": 7})
    assert "started" not in captured


def test_no_instance_skips(captured, monkeypatch):
    _emit([0, 0], "torpedo", monkeypatch, ship_instances={})   # ship not mapped
    assert "started" not in captured


def test_ship_instances_none_skips(captured, monkeypatch):
    rng = _RNG([0, 0])
    monkeypatch.setattr(hull_hit_smoke.App, "g_kSystemWrapper", rng)
    hull_hit_smoke.maybe_emit(
        "ship", TGPoint3(5.0, 6.0, 7.0), TGPoint3(0.0, 1.0, 0.0), "torpedo")
    assert "started" not in captured
