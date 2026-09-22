"""Hold-fire on a target ahead routes phaser damage through apply_hit
each tick (so shield/hull condition decreases)."""
from unittest.mock import patch

import pytest

from engine.appc.math import TGPoint3
from engine.host_loop import _advance_combat
from tests.helpers.beams import prime_lit_banks


def _target_with_shields(at_y=50.0, hull_max=10000.0, shields_strength=5000.0):
    """Stand-in target ship with hull + full shields at ship_pos+Y*at_y.

    Raises shields by going to YELLOW alert — combat.apply_hit gates
    shield absorption on the generator being powered (IsOn)."""
    from engine.appc.subsystems import HullSubsystem, ShieldSubsystem
    from engine.appc.properties import ShieldProperty
    from engine.appc.ships import ShipClass, ShipClass_Create
    tgt = ShipClass_Create("Target")
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(hull_max)
    tgt._hull = hull
    shields = ShieldSubsystem("Shields")
    for f in range(ShieldProperty.NUM_SHIELDS):
        shields.SetMaxShields(f, shields_strength)
    tgt._shield_subsystem = shields
    tgt._radius = 20.0
    tgt.SetAlertLevel(ShipClass.YELLOW_ALERT)
    return tgt


def test_held_fire_decreases_target_shield(galaxy_red):
    ship = galaxy_red
    sys_ = ship.GetPhaserSystem()
    for i in range(sys_.GetNumWeapons()):
        bank = sys_.GetWeapon(i)
        bank._charge_level = bank._max_charge

    target = _target_with_shields()
    p = ship.GetWorldLocation()
    target.SetWorldLocation(TGPoint3(p.x, p.y + 50.0, p.z))
    ship.SetTarget(target)

    front_before = target.GetShields().GetCurrentShields(0)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        sys_.StartFiring(target)
        prime_lit_banks(sys_)
        _advance_combat([ship, target], dt=0.1, ship_instances=None)
    front_after = target.GetShields().GetCurrentShields(0)
    assert front_after < front_before, (
        f"Held-fire should decrement front shield; before={front_before}, after={front_after}"
    )


def test_target_drifts_out_of_arc_bank_auto_stops(galaxy_red):
    ship = galaxy_red
    sys_ = ship.GetPhaserSystem()
    for i in range(sys_.GetNumWeapons()):
        bank = sys_.GetWeapon(i)
        bank._charge_level = bank._max_charge

    target = _target_with_shields()
    p = ship.GetWorldLocation()
    target.SetWorldLocation(TGPoint3(p.x, p.y + 50.0, p.z))
    ship.SetTarget(target)

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        sys_.StartFiring(target)
    firing_before = sum(sys_.GetWeapon(i).IsFiring() for i in range(sys_.GetNumWeapons()))
    # Galaxy SingleFire(1) → exactly one bank fires.
    assert firing_before == 1

    # Move target directly astern of the player.
    target.SetWorldLocation(TGPoint3(p.x, p.y - 50.0, p.z))

    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        _advance_combat([ship, target], dt=0.1, ship_instances=None)
    firing_after = sum(sys_.GetWeapon(i).IsFiring() for i in range(sys_.GetNumWeapons()))
    assert firing_after == 0, (
        f"Out-of-arc auto-stop; before={firing_before}, after={firing_after}"
    )


def test_phaser_hit_point_comes_from_host_ray_trace_mesh(galaxy_red, monkeypatch):
    """When host_io.ray_trace_mesh returns a surface point, apply_hit receives
    it, not target.GetWorldLocation(). Task 4: the mesh trace routes through
    host_io, so the test patches that wrapper."""
    from engine import host_io
    ship = galaxy_red
    sys_ = ship.GetPhaserSystem()
    for i in range(sys_.GetNumWeapons()):
        bank = sys_.GetWeapon(i)
        bank._charge_level = bank._max_charge

    target = _target_with_shields()
    p = ship.GetWorldLocation()
    target.SetWorldLocation(TGPoint3(p.x, p.y + 50.0, p.z))
    ship.SetTarget(target)

    SURFACE_POINT = (1.5, 47.25, -2.0)  # Distinct from target_pos.

    monkeypatch.setattr(
        host_io, "ray_trace_mesh",
        lambda iid, origin, direction, max_dist: (SURFACE_POINT, (0.0, -1.0, 0.0), 1.0))

    captured = {}
    import engine.appc.combat as combat

    def spy(ship_, damage, hit_point, source, subsystem=None,
            *, normal=None, ship_instances=None, **kwargs):
        captured["hit_point"] = hit_point

    sentinel = object()
    with patch.object(combat, "apply_hit", spy), \
         patch("engine.audio.tg_sound.TGSoundManager.instance"):
        sys_.StartFiring(target)
        prime_lit_banks(sys_)
        _advance_combat([ship, target], dt=0.1,
                        ship_instances={target: sentinel})

    assert "hit_point" in captured, "apply_hit was never called"
    hp = captured["hit_point"]
    assert hp.x == pytest.approx(SURFACE_POINT[0])
    assert hp.y == pytest.approx(SURFACE_POINT[1])
    assert hp.z == pytest.approx(SURFACE_POINT[2])


def test_phaser_beam_render_endpoint_clipped_to_mesh(galaxy_red):
    """The rendered phaser beam endpoint is clipped to the mesh-trace
    surface point so the visible beam ends on the hull, not at the
    target's bounding-sphere centre."""
    ship = galaxy_red
    sys_ = ship.GetPhaserSystem()
    for i in range(sys_.GetNumWeapons()):
        bank = sys_.GetWeapon(i)
        bank._charge_level = bank._max_charge

    target = _target_with_shields()
    p = ship.GetWorldLocation()
    target.SetWorldLocation(TGPoint3(p.x, p.y + 50.0, p.z))
    ship.SetTarget(target)

    SURFACE_POINT = (1.5, 47.25, -2.0)  # Distinct from target centre.

    from engine import host_io

    beam_data = None

    def _capture_beams(data):
        nonlocal beam_data
        beam_data = list(data)

    def _fake_trace(iid, origin, direction, max_dist):
        return (SURFACE_POINT, (0.0, -1.0, 0.0), 1.0)

    sentinel = object()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"), \
         patch.object(host_io, "set_phaser_beams", _capture_beams), \
         patch.object(host_io, "shield_hit", lambda *a, **k: None), \
         patch.object(host_io, "ray_trace_mesh", _fake_trace):
        sys_.StartFiring(target)
        _advance_combat([ship, target], dt=0.1,
                        ship_instances={target: sentinel})

    # host_io.set_phaser_beams should have been called with at least one entry.
    assert beam_data is not None
    assert len(beam_data) >= 1
    # Every entry's target must equal SURFACE_POINT (the clipped endpoint).
    for entry in beam_data:
        end = entry["target"]
        assert end[0] == pytest.approx(SURFACE_POINT[0])
        assert end[1] == pytest.approx(SURFACE_POINT[1])
        assert end[2] == pytest.approx(SURFACE_POINT[2])


# ── Continuous impact feedback while a beam rests on a target ───────────────
# The DAMAGE is pulsed (one flush per 0.53 s of dwell — bible §2.2), but the
# impact is not: BC draws its beam glow at the contact point every frame
# (PhaserLights.tga, §14.1). Ours spawns the flash and the spark burst from
# hit_feedback, which used to run per tick because the damage did. When the
# damage moved to pulses the flash and sparks went with it — a hit every
# 0.53 s per bank instead of every frame, which live read as the glowing
# hull impact and the ejected debris disappearing.

def _count_impacts(ship, target, ticks, dt=1.0 / 60):
    from engine.appc import hit_vfx
    from engine import host_io
    spawns, splashes = [], []
    with patch.object(hit_vfx, "spawn", lambda *a, **k: spawns.append(1)), \
         patch.object(host_io, "shield_hit", lambda *a, **k: splashes.append(1)), \
         patch("engine.audio.tg_sound.TGSoundManager.instance"):
        for _ in range(ticks):
            _advance_combat([ship, target], dt=dt, ship_instances={target: 1})
    return len(spawns), len(splashes)


def test_a_beam_resting_on_a_bare_hull_flashes_every_frame(galaxy_red):
    ship = galaxy_red
    sys_ = ship.GetPhaserSystem()
    for i in range(sys_.GetNumWeapons()):
        sys_.GetWeapon(i)._charge_level = sys_.GetWeapon(i)._max_charge
    target = _target_with_shields(shields_strength=0.0)   # bare hull
    p = ship.GetWorldLocation()
    target.SetWorldLocation(TGPoint3(p.x, p.y + 50.0, p.z))
    ship.SetTarget(target)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        sys_.StartFiring(target)
        prime_lit_banks(sys_)
    spawns, _ = _count_impacts(ship, target, ticks=60)
    assert spawns >= 55, (
        "the hull flash and its sparks must fire every frame the beam is in "
        "contact, not once per damage pulse — got %d in 60 ticks" % spawns)


def test_a_beam_resting_on_a_raised_shield_splashes_every_frame(galaxy_red):
    ship = galaxy_red
    sys_ = ship.GetPhaserSystem()
    for i in range(sys_.GetNumWeapons()):
        sys_.GetWeapon(i)._charge_level = sys_.GetWeapon(i)._max_charge
    target = _target_with_shields()                       # shields up
    p = ship.GetWorldLocation()
    target.SetWorldLocation(TGPoint3(p.x, p.y + 50.0, p.z))
    ship.SetTarget(target)
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        sys_.StartFiring(target)
        prime_lit_banks(sys_)
    _, splashes = _count_impacts(ship, target, ticks=60)
    assert splashes >= 55, (
        "the shield splash must fire every frame the beam is in contact — "
        "got %d in 60 ticks" % splashes)
