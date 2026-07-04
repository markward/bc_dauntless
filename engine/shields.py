"""Python glue between ship state and the C++ shield render pass.

The renderer-side state lives in `native/src/renderer/shield_pass.cc`; this
module translates Phase-1 ShieldProperty data-bag values into
`host.shield_register` / `host.shield_hit` calls.

Calling convention matches the host bindings (see
`native/src/host/host_bindings.cc`): tuples for vectors/colors, keyword
arguments for clarity.
"""
import App
from engine.appc.properties import ShieldProperty

# Mode values match `renderer::ShieldMode` in the C++ header.
SHIELD_MODE_ELLIPSOID = 0
SHIELD_MODE_SKIN = 1


def _find_shield_property(ship):
    """Returns the ship's ShieldProperty, or None if none exists.

    Phase 1 ships store properties on the ModelPropertySet they hold a
    reference to (populated by hardpoint imports via RegisterLocalTemplate
    + ShipClass.LoadPropertySet). Tests can also pass fakes with a
    flat `subsystems` list."""
    for sub in getattr(ship, "subsystems", []):
        if isinstance(sub, ShieldProperty):
            return sub
    get_set = getattr(ship, "GetPropertySet", None)
    if get_set is None:
        return None
    try:
        prop_set = get_set()
        for prop in prop_set.GetPropertyList():
            if isinstance(prop, ShieldProperty):
                return prop
    except Exception:
        return None
    return None


def _color_tuple(prop, default=(1.0, 1.0, 1.0, 1.0)):
    """Read the ship's ShieldGlowColor as an RGBA tuple, default white."""
    val = prop.GetShieldGlowColor()
    if isinstance(val, App.TGColorA):
        return (val.r, val.g, val.b, val.a)
    return default


def register_ship_shield(host, instance_id, ship,
                         aabb_center, aabb_half_extents):
    """Push a ship's shield render state to the C++ pass.

    Reads the ship's ShieldProperty for:
    - ShieldGlowColor → default flash color
    - ShieldGlowDecay → exponential decay constant (seconds)
    - SkinShielding   → 1 = hull-conforming, 0/absent = ellipsoid (default)

    Silently does nothing if the ship has no ShieldProperty subsystem
    (asteroids, debris, etc.). Hardpoints that want a shielded ship must
    instantiate App.ShieldProperty_Create(...) and register it on the ship."""
    prop = _find_shield_property(ship)
    if prop is None:
        return
    skin = prop.GetSkinShielding()
    mode = SHIELD_MODE_SKIN if skin else SHIELD_MODE_ELLIPSOID
    decay = prop.GetShieldGlowDecay()
    color = _color_tuple(prop)
    host.shield_register(
        instance_id=instance_id,
        mode=mode,
        decay_seconds=float(decay),
        default_color=color,
        aabb_center=tuple(aabb_center),
        aabb_half_extents=tuple(aabb_half_extents),
    )


def _point_tuple(p):
    """Accept tuple/list (already-unpacked) or TGPoint3-style .x/.y/.z."""
    if hasattr(p, "x"):
        return (float(p.x), float(p.y), float(p.z))
    return (float(p[0]), float(p[1]), float(p[2]))


def fire_debug_hit(host, instance_id, world_point):
    """Push a synthetic hit at world_point. Color (0,0,0,0) signals the
    renderer to use the ship's registered default ShieldGlowColor."""
    from engine.appc.hit_feedback import SHIELD_IMPACT_INTENSITY
    host.shield_hit(
        instance_id=instance_id,
        point=_point_tuple(world_point),
        rgba=(0.0, 0.0, 0.0, 0.0),
        intensity=SHIELD_IMPACT_INTENSITY,
    )
