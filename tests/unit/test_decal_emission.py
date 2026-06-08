"""dispatch must emit a decal exactly when hull damage was dealt, and never
when shields fully absorbed the hit (the shield-gating fix)."""
import pytest

from engine.appc import hit_feedback
from engine.appc import damage_decals as dd


class _Pt:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _FakeHost:
    def __init__(self):
        self.decal_calls = []

    def damage_decal_add(self, *, instance_id, world_point, world_normal,
                         radius, intensity, weapon_class, time):
        self.decal_calls.append(dict(
            instance_id=instance_id, world_point=world_point,
            world_normal=world_normal, radius=radius, intensity=intensity,
            weapon_class=weapon_class, time=time))


class _Hull:
    def IsDestroyed(self):
        return 0


class _Ship:
    def GetHull(self):
        return _Hull()


@pytest.fixture
def patched(monkeypatch):
    # Isolate decal emission: deterministic clock, no real App/audio needed.
    monkeypatch.setattr(dd, "current_game_time", lambda: 42.0)
    return monkeypatch


def _dispatch(host, *, absorbed_hull, weapon_type="torpedo", normal=_Pt(0, 0, 1)):
    ship = _Ship()
    hit_feedback.dispatch(
        ship=ship, source=None, point=_Pt(1, 2, 3), normal=normal,
        damage=10.0, subsystem=None,
        absorbed_shields=0.0, absorbed_subsystem=0.0,
        absorbed_hull=absorbed_hull, sub_transition=None,
        host=host, ship_instances={ship: "IID"},
        weapon_type=weapon_type, radius=0.2,
    )


def test_decal_emitted_when_hull_damaged(patched):
    host = _FakeHost()
    _dispatch(host, absorbed_hull=5.0)
    assert len(host.decal_calls) == 1
    call = host.decal_calls[0]
    assert call["instance_id"] == "IID"
    assert call["world_point"] == (1, 2, 3)
    assert call["weapon_class"] == dd.WEAPON_CLASS_SCORCH
    assert call["radius"] == 0.2
    assert call["time"] == 42.0
    assert 0.0 < call["intensity"] <= 1.0


def test_no_decal_when_shields_absorbed(patched):
    host = _FakeHost()
    _dispatch(host, absorbed_hull=0.0)        # shields ate it
    assert host.decal_calls == []


def test_phaser_emits_heat_glow_class(patched):
    host = _FakeHost()
    _dispatch(host, absorbed_hull=3.0, weapon_type="phaser")
    assert host.decal_calls[0]["weapon_class"] == dd.WEAPON_CLASS_HEAT_GLOW


def test_no_decal_without_normal(patched):
    # No surface normal (sphere-entry / fallback hit) -> no decal; we lack a
    # reliable orientation for normal-aware falloff.
    host = _FakeHost()
    _dispatch(host, absorbed_hull=5.0, normal=None)
    assert host.decal_calls == []


def test_headless_host_none_is_safe(patched):
    # dispatch is documented headless-safe: host=None must not raise and must
    # emit nothing. Makes the "headless-safe" invariant machine-checked.
    _dispatch(None, absorbed_hull=5.0)
