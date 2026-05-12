"""Engine glue for shield-hit pushes.

The renderer-side state lives in C++ (see native/src/renderer/shield_pass.cc).
engine.shields wraps the host bindings so SDK-side code can call into them
without dealing with tuple packing or default-color resolution rules.
"""
from unittest.mock import MagicMock

import App
from engine.appc.properties import ShieldProperty


def _color(r, g, b, a):
    c = App.TGColorA()
    c.SetRGBA(r, g, b, a)
    return c


def test_fire_debug_hit_sends_to_host():
    import engine.shields as s
    host = MagicMock()
    s.fire_debug_hit(host, instance_id=42, world_point=(1.0, 2.0, 3.0))
    host.shield_hit.assert_called_once_with(
        instance_id=42,
        point=(1.0, 2.0, 3.0),
        rgba=(0.0, 0.0, 0.0, 0.0),
        intensity=1.0,
    )


def test_fire_debug_hit_accepts_tgpoint3():
    """Player.GetWorldLocation returns a TGPoint3 (.x/.y/.z) — verify the
    glue unpacks it correctly."""
    import engine.shields as s
    from engine.appc.math import TGPoint3
    host = MagicMock()
    s.fire_debug_hit(host, instance_id=1, world_point=TGPoint3(4.0, 5.0, 6.0))
    host.shield_hit.assert_called_once()
    assert host.shield_hit.call_args.kwargs["point"] == (4.0, 5.0, 6.0)


def test_register_ship_shield_skips_when_no_shield_property():
    import engine.shields as s
    host = MagicMock()

    class FakeShip:
        subsystems = []

    s.register_ship_shield(host, instance_id=1, ship=FakeShip(),
                           aabb_center=(0, 0, 0), aabb_half_extents=(1, 1, 1))
    host.shield_register.assert_not_called()


def test_register_ship_shield_reads_skin_flag_and_color():
    import engine.shields as s
    host = MagicMock()

    shield_prop = ShieldProperty("Shield Generator")
    shield_prop.SetShieldGlowColor(_color(0.2, 0.4, 1.0, 1.0))
    shield_prop.SetShieldGlowDecay(2.0)
    shield_prop.SetSkinShielding(1)

    class FakeShip:
        subsystems = [shield_prop]

    s.register_ship_shield(host, instance_id=7, ship=FakeShip(),
                           aabb_center=(0, 1, 0),
                           aabb_half_extents=(10, 5, 30))
    host.shield_register.assert_called_once_with(
        instance_id=7,
        mode=1,  # SKIN
        decay_seconds=2.0,
        default_color=(0.2, 0.4, 1.0, 1.0),
        aabb_center=(0, 1, 0),
        aabb_half_extents=(10, 5, 30),
    )


def test_register_ship_shield_finds_property_via_property_set():
    """Phase-1 ships expose properties via GetPropertySet().GetPropertyList(),
    not via .subsystems. The glue should reach into either."""
    import engine.shields as s
    host = MagicMock()

    shield_prop = ShieldProperty("Shield Generator")
    shield_prop.SetShieldGlowColor(_color(0.5, 0.5, 0.5, 1.0))
    shield_prop.SetSkinShielding(1)

    class FakePropertySet:
        def GetPropertyList(self):
            return [shield_prop]

    class FakeShip:
        def GetPropertySet(self):
            return FakePropertySet()

    s.register_ship_shield(host, instance_id=99, ship=FakeShip(),
                           aabb_center=(0, 0, 0),
                           aabb_half_extents=(1, 1, 1))
    host.shield_register.assert_called_once()
    assert host.shield_register.call_args.kwargs["mode"] == 1


def test_register_ship_shield_defaults_when_keys_absent():
    """No SetSkinShielding → ellipsoid. No decay → 1.0. No color → white."""
    import engine.shields as s
    host = MagicMock()

    shield_prop = ShieldProperty("Shield Generator")
    # Don't set any of the optional shield-render keys.

    class FakeShip:
        subsystems = [shield_prop]

    s.register_ship_shield(host, instance_id=3, ship=FakeShip(),
                           aabb_center=(0, 0, 0),
                           aabb_half_extents=(1, 1, 1))
    call = host.shield_register.call_args.kwargs
    assert call["mode"] == 0  # ELLIPSOID
    assert call["decay_seconds"] == 1.0
    assert call["default_color"] == (1.0, 1.0, 1.0, 1.0)
