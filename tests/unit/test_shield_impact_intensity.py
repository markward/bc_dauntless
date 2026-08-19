"""A torpedo's shield flash is seeded brighter than a phaser tick's.

`ShieldState` keeps the 8 most recent hits and the shader SUMS them. A phaser
applies damage every tick, so under sustained fire all 8 slots hold
near-simultaneous, near-co-located splashes: at 60 Hz with ShieldGlowDecay 1.0
that is a summed intensity of 3.78 from a 0.5 seed. A torpedo is a single push
— 0.5. Same seed, 7.6x less light, which is why torpedo impacts read as dim
once the phaser ones looked right.

The seed is per PUSH, so a single discrete impact needs a bigger one. BC draws
the same asymmetry: a shield hit always shows the glow, and a torpedo
ADDITIONALLY triggers Effects.TorpedoShieldHit subject to a magnitude check,
while no PhaserShieldHit handler exists at all (stbc_reference
spec/ShieldFacingDamage.md §4.3). `_play_audio` in this module already encodes
that same split for sound.
"""
import pytest

from engine.appc import hit_feedback
from engine.appc.math import TGPoint3
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import HullSubsystem, ShieldSubsystem


def _shielded_ship():
    s = ShipClass_Create("Target")
    s._hull = HullSubsystem("Hull")
    s._hull.SetMaxCondition(10000.0)
    ss = ShieldSubsystem("Shield Generator")
    for f in range(ShieldSubsystem.NUM_SHIELDS):
        ss.SetMaxShields(f, 5000.0)
    s.SetShieldSubsystem(ss)
    return s


def _seed_pushed(monkeypatch, weapon_type):
    """The intensity handed to host_io.shield_hit for a fully-absorbed hit."""
    seen = []
    monkeypatch.setattr(hit_feedback.host_io, "shield_hit",
                        lambda iid, point, rgba, intensity, radius=0.0:
                            seen.append(intensity))
    ship = _shielded_ship()
    hit_feedback.dispatch(
        ship=ship, source=None, point=TGPoint3(0.0, 10.0, 0.0), normal=None,
        damage=100.0, subsystem=None,
        absorbed_shields=100.0, absorbed_subsystem=0.0, absorbed_hull=0.0,
        sub_transition=None, ship_instances={ship: 3},
        weapon_type=weapon_type, radius=0.15)
    assert len(seen) == 1
    return seen[0]


def test_torpedo_seeds_a_brighter_flash_than_a_phaser_tick(monkeypatch):
    torpedo = _seed_pushed(monkeypatch, "torpedo")
    phaser = _seed_pushed(monkeypatch, "phaser")
    assert torpedo > phaser


def test_torpedo_seed_offsets_the_phaser_stacking_advantage():
    """A phaser fills all 8 slots; a torpedo fills one. The seeds have to
    differ by enough to matter — parity is the bug this file exists for."""
    assert hit_feedback.shield_impact_intensity("torpedo") >= \
        3.0 * hit_feedback.shield_impact_intensity("phaser")


def test_unknown_and_missing_weapon_types_use_the_default(monkeypatch):
    default = hit_feedback.shield_impact_intensity("phaser")
    assert hit_feedback.shield_impact_intensity(None) == default
    assert hit_feedback.shield_impact_intensity("tractor") == default
    assert _seed_pushed(monkeypatch, None) == default


def test_seeds_stay_within_the_renderer_range():
    """Intensity multiplies coverage in the shader; the additive blend has no
    ceiling, so a wild value blows out to white rather than reading as an
    impact."""
    for wt in ("phaser", "torpedo", None):
        v = hit_feedback.shield_impact_intensity(wt)
        assert 0.0 < v <= 4.0, wt


# ── the weapon's radius must reach the renderer ─────────────────────────────
#
# The procedural splash is "sized to the impact": shield_splash_reach() in
# renderer/shield_state.h turns the weapon's DamageRadiusFactor into a
# world-space ripple reach. `radius` was already an argument to dispatch(), but
# it went only to the damage decal and the hull carve -- the shield path
# dropped it, so every weapon splashed identically.

def _radius_pushed(monkeypatch, radius):
    """The radius handed to host_io.shield_hit for a fully-absorbed hit."""
    seen = []
    monkeypatch.setattr(hit_feedback.host_io, "shield_hit",
                        lambda iid, point, rgba, intensity, radius=0.0:
                            seen.append(radius))
    ship = _shielded_ship()
    hit_feedback.dispatch(
        ship=ship, source=None, point=TGPoint3(0.0, 10.0, 0.0), normal=None,
        damage=100.0, subsystem=None,
        absorbed_shields=100.0, absorbed_subsystem=0.0, absorbed_hull=0.0,
        sub_transition=None, ship_instances={ship: 3},
        weapon_type="torpedo", radius=radius)
    assert len(seen) == 1
    return seen[0]


def test_weapon_radius_reaches_the_shield_pass(monkeypatch):
    assert _radius_pushed(monkeypatch, 0.13) == pytest.approx(0.13)
    assert _radius_pushed(monkeypatch, 0.15) == pytest.approx(0.15)


def test_a_hit_with_no_weapon_radius_still_pushes_a_splash(monkeypatch):
    """Collisions and splash damage carry no DamageRadiusFactor. They must
    still flash the shield -- the renderer clamps 0 up to its reach floor."""
    assert _radius_pushed(monkeypatch, 0.0) == pytest.approx(0.0)
