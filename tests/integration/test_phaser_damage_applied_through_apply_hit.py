"""Hold-fire on a target ahead routes phaser damage through apply_hit
each tick (so shield/hull condition decreases)."""
from unittest.mock import patch

import pytest

from engine.appc.math import TGPoint3
from engine.host_loop import _advance_combat


def _target_with_shields(at_y=50.0, hull_max=10000.0, shields_strength=5000.0):
    """Stand-in target ship with hull + full shields at ship_pos+Y*at_y."""
    from engine.appc.subsystems import HullSubsystem, ShieldSubsystem
    from engine.appc.properties import ShieldProperty
    from engine.appc.ships import ShipClass_Create
    tgt = ShipClass_Create("Target")
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(hull_max)
    tgt._hull = hull
    shields = ShieldSubsystem("Shields")
    for f in range(ShieldProperty.NUM_SHIELDS):
        shields.SetMaxShields(f, shields_strength)
    tgt._shield_subsystem = shields
    tgt._radius = 20.0
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
        _advance_combat([ship, target], dt=0.1, host=None, ship_instances=None)
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
        _advance_combat([ship, target], dt=0.1, host=None, ship_instances=None)
    firing_after = sum(sys_.GetWeapon(i).IsFiring() for i in range(sys_.GetNumWeapons()))
    assert firing_after == 0, (
        f"Out-of-arc auto-stop; before={firing_before}, after={firing_after}"
    )


def test_phaser_hit_point_comes_from_host_ray_trace_mesh(galaxy_red):
    """When a host is supplied with ray_trace_mesh, apply_hit receives
    the surface point, not target.GetWorldLocation()."""
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

    class FakeHost:
        def __init__(self):
            self.shield_hits = []
        def ray_trace_mesh(self, iid, origin, direction, max_dist):
            return (SURFACE_POINT, (0.0, -1.0, 0.0), 1.0)
        def shield_hit(self, instance_id, point, rgba, intensity):
            self.shield_hits.append(point)
        def __getattr__(self, name):
            return lambda *a, **kw: None

    captured = {}
    import engine.appc.combat as combat

    def spy(ship_, damage, hit_point, source, subsystem=None):
        captured["hit_point"] = hit_point

    sentinel = object()
    host = FakeHost()
    with patch.object(combat, "apply_hit", spy), \
         patch("engine.audio.tg_sound.TGSoundManager.instance"):
        sys_.StartFiring(target)
        _advance_combat([ship, target], dt=0.1,
                        host=host,
                        ship_instances={target: sentinel})

    assert "hit_point" in captured, "apply_hit was never called"
    hp = captured["hit_point"]
    assert hp.x == pytest.approx(SURFACE_POINT[0])
    assert hp.y == pytest.approx(SURFACE_POINT[1])
    assert hp.z == pytest.approx(SURFACE_POINT[2])
    # shield_hit must receive the same resolved point so the shield-pass
    # splash lands on the hull, not the target's center.
    assert len(host.shield_hits) == 1
    assert host.shield_hits[0] == SURFACE_POINT


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

    class FakeHost:
        def __init__(self):
            self.beam_data = None
        def ray_trace_mesh(self, iid, origin, direction, max_dist):
            return (SURFACE_POINT, (0.0, -1.0, 0.0), 1.0)
        def shield_hit(self, instance_id, point, rgba, intensity):
            pass
        def set_phaser_beams(self, data):
            self.beam_data = list(data)
        def __getattr__(self, name):
            return lambda *a, **kw: None

    sentinel = object()
    host = FakeHost()
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        sys_.StartFiring(target)
        _advance_combat([ship, target], dt=0.1,
                        host=host,
                        ship_instances={target: sentinel})

    # set_phaser_beams should have been called with at least one entry.
    assert host.beam_data is not None
    assert len(host.beam_data) >= 1
    # Every entry's target must equal SURFACE_POINT (the clipped endpoint).
    for entry in host.beam_data:
        end = entry["target"]
        assert end[0] == pytest.approx(SURFACE_POINT[0])
        assert end[1] == pytest.approx(SURFACE_POINT[1])
        assert end[2] == pytest.approx(SURFACE_POINT[2])
