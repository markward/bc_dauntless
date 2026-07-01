"""Torpedo spread volley — a Dual(2)/Quad(4) spread fires that many torpedoes
in a single StartFiring call, fanned out sideways, with homing deferred by
_SPREAD_DELAY so they diverge then converge on the locked target.  Single(1)
is byte-identical to the pre-spread path.
"""
from unittest.mock import patch

import pytest

import App  # noqa: F401  (SDK shim import order)
from engine.appc.math import TGPoint3, TGMatrix3
from engine.appc import projectiles
from engine.appc.projectiles import Torpedo, register, update_all
from engine.appc.subsystems import TorpedoSystem, TorpedoTube
from engine.appc.weapon_subsystems import _SPREAD_DELAY
from engine.appc.properties import WeaponSystemProperty


@pytest.fixture(autouse=True)
def clear_registry():
    projectiles._active.clear()
    yield
    projectiles._active.clear()


class _Tgt:
    def __init__(self, x, y, z):
        self._loc = TGPoint3(x, y, z)
    def GetWorldLocation(self): return self._loc
    def IsDead(self): return 0


def _system_with_tubes(num_tubes, *, target=None, rot=None):
    """Build a TorpedoSystem with `num_tubes` ready PhotonTorpedo tubes on a
    ship at the origin with an (optional) axis-aligned rotation and target
    lock.  Returns (system, ship)."""
    from engine.appc.ships import ShipClass_Create
    ship = ShipClass_Create("Test")
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    if rot is not None:
        ship.SetMatrixRotation(rot)
    ship._target = target
    ship._target_subsystem = None

    parent = TorpedoSystem("Torpedoes")
    parent.TurnOn()
    prop = WeaponSystemProperty("Torpedoes")
    prop.SetTorpedoScript(0, "Tactical.Projectiles.PhotonTorpedo")
    parent.SetProperty(prop)
    parent._parent_ship = ship
    ship._torpedo_system = parent

    for i in range(num_tubes):
        tube = TorpedoTube("Torpedo %d" % i)
        tube._max_ready = 1
        tube._num_ready = 1
        tube._reload_delay = 40.0
        parent.AddChildSubsystem(tube)
    return parent, ship


def _identity():
    R = TGMatrix3(); R.MakeIdentity()
    return R


# ── Volley count ────────────────────────────────────────────────────────────

def test_single_spread_fires_one_torpedo():
    tgt = _Tgt(0, 100, 0)
    system, _ = _system_with_tubes(4, target=tgt, rot=_identity())
    system.SetSpread(1)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        system.StartFiring(target=tgt, offset=None)
    assert len(projectiles._active) == 1


def test_dual_spread_fires_two_torpedoes():
    tgt = _Tgt(0, 100, 0)
    system, _ = _system_with_tubes(4, target=tgt, rot=_identity())
    system.SetSpread(2)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        system.StartFiring(target=tgt, offset=None)
    assert len(projectiles._active) == 2


def test_quad_spread_fires_four_torpedoes():
    tgt = _Tgt(0, 100, 0)
    system, _ = _system_with_tubes(4, target=tgt, rot=_identity())
    system.SetSpread(4)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        system.StartFiring(target=tgt, offset=None)
    assert len(projectiles._active) == 4


def test_spread_clamped_to_eligible_tube_count():
    """Quad(4) requested but only 2 tubes ready → fires 2."""
    tgt = _Tgt(0, 100, 0)
    system, _ = _system_with_tubes(2, target=tgt, rot=_identity())
    # GetSpreadOptions on a 2-tube system is [1, 2], so SetSpread(4) clamps
    # to the current value; force _spread = 4 directly to exercise the
    # StartFiring clamp against eligible tube count.
    system._spread = 4
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        system.StartFiring(target=tgt, offset=None)
    assert len(projectiles._active) == 2


# ── Homing delay ────────────────────────────────────────────────────────────

def test_single_shot_has_no_homing_delay():
    tgt = _Tgt(0, 100, 0)
    system, _ = _system_with_tubes(4, target=tgt, rot=_identity())
    system.SetSpread(1)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        system.StartFiring(target=tgt, offset=None)
    assert projectiles._active[-1]._homing_start_age == 0.0


def test_diverged_torps_carry_homing_delay():
    tgt = _Tgt(0, 100, 0)
    system, _ = _system_with_tubes(4, target=tgt, rot=_identity())
    system.SetSpread(2)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        system.StartFiring(target=tgt, offset=None)
    for torp in projectiles._active:
        assert torp._homing_start_age == _SPREAD_DELAY


# ── Divergence direction ────────────────────────────────────────────────────

def test_dual_diverges_left_and_right():
    """Dual: the two torps fan to +right and -right (opposite lateral sign),
    each still with a forward component toward the target."""
    tgt = _Tgt(0, 100, 0)  # straight ahead in +Y
    system, _ = _system_with_tubes(4, target=tgt, rot=_identity())
    system.SetSpread(2)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        system.StartFiring(target=tgt, offset=None)
    torps = projectiles._active
    assert len(torps) == 2
    lateral = [t._velocity.x for t in torps]     # dot with right=(1,0,0)
    assert any(l > 0 for l in lateral)
    assert any(l < 0 for l in lateral)
    # Forward component toward the target (+Y) preserved for both.
    for t in torps:
        assert t._velocity.y > 0


def test_quad_covers_all_four_axes():
    """Quad: torps cover +right, -right, +up, -up."""
    tgt = _Tgt(0, 100, 0)
    system, _ = _system_with_tubes(4, target=tgt, rot=_identity())
    system.SetSpread(4)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        system.StartFiring(target=tgt, offset=None)
    torps = projectiles._active
    assert len(torps) == 4
    right_dots = [t._velocity.x for t in torps]   # right = (1,0,0)
    up_dots = [t._velocity.z for t in torps]      # up = (0,0,1)
    assert any(d > 1e-6 for d in right_dots)      # +right
    assert any(d < -1e-6 for d in right_dots)     # -right
    assert any(d > 1e-6 for d in up_dots)         # +up
    assert any(d < -1e-6 for d in up_dots)        # -up


# ── Homing gate: suppressed then engages ────────────────────────────────────

def test_homing_suppressed_before_start_age_then_engages():
    tgt = _Tgt(0, 100, 0)
    t = Torpedo()
    t._position = TGPoint3(0, 0, 0)
    t._velocity = TGPoint3(10, 0, 0)   # heading +X, target is +Y
    t._ttl = 30.0
    t._age = 0.0
    t._target_ship = tgt
    t._guidance_lifetime = 10.0
    t._max_angular_accel = 5.0
    t._homing_start_age = 0.4
    register(t)

    # Step while age < 0.4 — no steering: velocity stays purely +X.
    update_all(dt=0.1, all_ships=[])
    assert t._velocity.y == 0.0
    assert t._velocity.x == pytest.approx(10.0)

    # Push age past 0.4 — homing engages, +Y component appears.
    t._age = 0.5
    update_all(dt=0.1, all_ships=[])
    assert t._velocity.y > 0.0


# ── Single-path regression guard ────────────────────────────────────────────

def test_single_spread_path_unchanged():
    """SetSpread(1) produces a torp identical to the pre-spread path: homes
    immediately (no delay) and has no lateral divergence toward the target."""
    tgt = _Tgt(0, 100, 0)
    system, _ = _system_with_tubes(4, target=tgt, rot=_identity())
    system.SetSpread(1)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        system.StartFiring(target=tgt, offset=None)
    torp = projectiles._active[-1]
    assert torp._homing_start_age == 0.0
    assert torp._target_ship is tgt
    # Straight at the target (+Y) — no lateral (X/Z) divergence.
    assert torp._velocity.x == pytest.approx(0.0, abs=1e-9)
    assert torp._velocity.z == pytest.approx(0.0, abs=1e-9)
    assert torp._velocity.y > 0.0
