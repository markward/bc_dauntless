"""dispatch must emit a decal exactly when hull damage was dealt, and never
when shields fully absorbed the hit (the shield-gating fix).

Native decal emit routes through engine.host_io.damage_decal_add; these tests
patch that wrapper (host_io owns the single guard point) rather than injecting
a raw host= module (Task 4 of the host_io façade refactor)."""
import pytest

from engine import host_io
from engine.appc import hit_feedback
from engine.appc import damage_decals as dd


class _Pt:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _DecalCapture:
    """Positional-arg capture matching host_io.damage_decal_add's signature
    (instance_id, world_point, world_normal, radius, intensity, weapon_class,
    time, world_tangent=None, dent=0.0)."""

    def __init__(self):
        self.decal_calls = []

    def __call__(self, instance_id, world_point, world_normal,
                 radius, intensity, weapon_class, time, world_tangent=None,
                 dent=0.0):
        self.decal_calls.append(dict(
            instance_id=instance_id, world_point=world_point,
            world_normal=world_normal, radius=radius, intensity=intensity,
            weapon_class=weapon_class, time=time, world_tangent=world_tangent,
            dent=dent))


class _Hull:
    def IsDestroyed(self):
        return 0


class _Ship:
    def GetHull(self):
        return _Hull()


@pytest.fixture
def decal(monkeypatch):
    """Patch host_io.damage_decal_add with a call-capturing spy and return it."""
    spy = _DecalCapture()
    monkeypatch.setattr(host_io, "damage_decal_add", spy)
    return spy


@pytest.fixture(autouse=True)
def _isolate_host_io(monkeypatch):
    """Neutralize the sibling host_io hit/damage wrappers so dispatch's spark /
    flash paths never reach the strict real native binding (which rejects the
    string 'IID' these unit tests use)."""
    monkeypatch.setattr(host_io, "world_to_body", lambda *a, **k: None)
    monkeypatch.setattr(host_io, "shield_hit", lambda *a, **k: None)


@pytest.fixture
def patched(monkeypatch):
    # Isolate decal emission: deterministic clock, no real App/audio needed.
    monkeypatch.setattr(dd, "current_game_time", lambda: 42.0)
    return monkeypatch


def _dispatch(*, absorbed_hull, weapon_type="torpedo", normal=_Pt(0, 0, 1),
              persist_decal=True, tangent=None, decal_radius=None,
              decal_dent=0.0):
    ship = _Ship()
    hit_feedback.dispatch(
        ship=ship, source=None, point=_Pt(1, 2, 3), normal=normal,
        damage=10.0, subsystem=None,
        absorbed_shields=0.0, absorbed_subsystem=0.0,
        absorbed_hull=absorbed_hull, sub_transition=None,
        ship_instances={ship: "IID"},
        weapon_type=weapon_type, radius=0.2, persist_decal=persist_decal,
        tangent=tangent, decal_radius=decal_radius, decal_dent=decal_dent,
    )


def test_decal_emitted_when_hull_damaged(patched, decal):
    _dispatch(absorbed_hull=5.0)
    assert len(decal.decal_calls) == 1
    call = decal.decal_calls[0]
    assert call["instance_id"] == "IID"
    assert call["world_point"] == (1, 2, 3)
    assert call["weapon_class"] == dd.WEAPON_CLASS_SCORCH
    # r_hit (0.2) is scaled by the per-class visual radius scale before emit.
    assert call["radius"] == pytest.approx(
        0.2 * dd.decal_radius_scale(dd.WEAPON_CLASS_SCORCH))
    assert call["time"] == 42.0
    assert 0.0 < call["intensity"] <= 1.0


def test_no_decal_when_shields_absorbed(patched, decal):
    _dispatch(absorbed_hull=0.0)        # shields ate it
    assert decal.decal_calls == []


def test_phaser_emits_heat_glow_class(patched, decal):
    _dispatch(absorbed_hull=3.0, weapon_type="phaser")
    assert decal.decal_calls[0]["weapon_class"] == dd.WEAPON_CLASS_HEAT_GLOW


def test_no_decal_without_normal(patched, decal):
    # No surface normal (sphere-entry / fallback hit) -> no decal; we lack a
    # reliable orientation for normal-aware falloff.
    _dispatch(absorbed_hull=5.0, normal=None)
    assert decal.decal_calls == []


def test_headless_host_none_is_safe(patched):
    # dispatch is documented headless-safe: with no wrapper patched, the real
    # host_io.damage_decal_add no-ops when the native module is absent. With no
    # renderer instance (empty map) dispatch must emit nothing and not raise.
    ship = _Ship()
    hit_feedback.dispatch(
        ship=ship, source=None, point=_Pt(1, 2, 3), normal=_Pt(0, 0, 1),
        damage=10.0, subsystem=None,
        absorbed_shields=0.0, absorbed_subsystem=0.0,
        absorbed_hull=5.0, sub_transition=None,
        ship_instances={},  # unmapped: caller-side skip
        weapon_type="torpedo", radius=0.2,
    )


def test_no_decal_when_persist_decal_false(patched, decal):
    # God mode (combat passes persist_decal=False): hull "damage" is still
    # reported for the transient spark, but must NOT leave a persistent scar.
    _dispatch(absorbed_hull=5.0, persist_decal=False)
    assert decal.decal_calls == []


def test_collision_emits_scuff_with_tangent_and_decal_radius(patched, decal):
    _dispatch(absorbed_hull=5.0, weapon_type="collision",
              tangent=_Pt(0, 1, 0), decal_radius=2.5)
    assert len(decal.decal_calls) == 1
    c = decal.decal_calls[0]
    assert c["weapon_class"] == dd.WEAPON_CLASS_SCUFF
    assert c["world_tangent"] == (0, 1, 0)
    assert c["radius"] == pytest.approx(2.5)        # chord, scale 1.0 — NOT 0.2 * anything


def test_weapon_callers_pass_no_tangent_and_keep_the_weapon_radius(patched, decal):
    _dispatch(absorbed_hull=5.0)                     # torpedo, radius=0.2
    c = decal.decal_calls[0]
    assert c["world_tangent"] is None
    assert c["radius"] == pytest.approx(0.2 * dd.decal_radius_scale(dd.WEAPON_CLASS_SCORCH))


def test_decal_radius_none_falls_back_to_the_hit_radius_for_a_collision(patched, decal):
    _dispatch(absorbed_hull=5.0, weapon_type="collision")
    assert decal.decal_calls[0]["radius"] == pytest.approx(0.2)


def test_decal_radius_never_reaches_the_carve(patched, decal, monkeypatch):
    # Spec §6: a collision apply_hit leaves r_hit, the subsystem catchment,
    # the carve influence radius and WeaponHitEvent.GetRadius() exactly as
    # before -- decal_radius is a DECAL-ONLY override. Pin that the carve's
    # influence radius is derived from `radius` (0.2), never from
    # `decal_radius` (2.5), even though this dispatch sets both.
    from engine.appc import damage_eligibility, hull_carve

    monkeypatch.setattr(damage_eligibility, "is_eligible", lambda ship: True)
    carve_calls = []
    monkeypatch.setattr(host_io, "hull_carve_add",
                        lambda *a, **k: carve_calls.append(a))

    _dispatch(absorbed_hull=5.0, weapon_type="collision",
              tangent=_Pt(0, 1, 0), decal_radius=2.5)

    assert decal.decal_calls[0]["radius"] == pytest.approx(2.5)
    assert len(carve_calls) == 1
    # positional signature: (iid, point, normal, influ, strength, time, ...)
    influ = carve_calls[0][3]
    assert influ == pytest.approx(hull_carve.carve_influ_gu(0.2))
    assert influ != pytest.approx(hull_carve.carve_influ_gu(2.5))


def test_dent_weight_reaches_the_decal(patched, decal):
    _dispatch(absorbed_hull=5.0, weapon_type="collision", decal_dent=1.0)
    assert decal.decal_calls[0]["dent"] == 1.0
    _dispatch(absorbed_hull=5.0)                 # weapons: never a dent
    assert decal.decal_calls[1]["dent"] == 0.0


def test_developer_mode_logs_each_decal_emit_to_stderr(patched, decal, monkeypatch, capsys):
    """Live 2026-09-21: 'I can't see any decals' had no trail — nothing said
    whether a decal was emitted, of which class, where, or how big. Under
    --developer every emit prints one line to stderr; production is silent."""
    from engine import dev_mode
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: True)
    _dispatch(absorbed_hull=5.0, weapon_type="collision", tangent=_Pt(0, 1, 0),
              decal_radius=0.3, decal_dent=1.0)
    err = capsys.readouterr().err
    lines = [l for l in err.splitlines() if l.startswith("[decal]")]
    assert len(lines) == 1, err
    assert "class=2" in lines[0] and "dent=1.0" in lines[0] and "r=0.300" in lines[0]
    assert "(1.0,2.0,3.0)" in lines[0]                  # the world point


def test_decal_emit_log_is_silent_outside_developer_mode(patched, decal, monkeypatch, capsys):
    from engine import dev_mode
    monkeypatch.setattr(dev_mode, "is_enabled", lambda: False)
    _dispatch(absorbed_hull=5.0, weapon_type="collision")
    assert "[decal]" not in capsys.readouterr().err
