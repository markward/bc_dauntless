"""Dev-only keybinding handlers. Imported by engine.host_loop on startup.

Handlers needing per-frame state (player ship, session) are re-bound every
tick via register_for_frame(); pure-static handlers can be registered once
at module import time.
"""
import engine.dev_mode as dev_mode


def register_for_frame(_h, session, player) -> None:
    """Re-bind handlers that close over per-frame state. Called once per tick
    from the host loop before dev_mode.dispatch_dev_key().
    """
    # F10: debug shield-hit on the shield surface. Real BC weapons impact the
    # bubble at a surface point; firing at the ship center would put the hit
    # too far inside the bubble for the distance falloff to ever exceed zero
    # on the visible shell. Offset along the ship's forward axis by ~1.0 x
    # the ship's GetRadius() so the hit lands near the bubble surface.
    def _f10_shield_debug() -> None:
        if player is None or session is None:
            return
        iid = session.ship_instances.get(player)
        if iid is None:
            return
        from engine.shields import fire_debug_hit
        wp = player.GetWorldLocation()
        try:
            fwd = player.GetWorldRotation().GetCol(1)
            fx, fy, fz = float(fwd.x), float(fwd.y), float(fwd.z)
        except Exception:
            fx, fy, fz = 1.0, 0.0, 0.0
        offset = 1.0 * player.GetRadius()
        fire_debug_hit(
            _h,
            instance_id=iid,
            world_point=(wp.x + fx * offset, wp.y + fy * offset, wp.z + fz * offset),
        )

    dev_mode.register_dev_keybinding(
        _h.keys.KEY_F10, _f10_shield_debug, "Shield-hit debug (F10)"
    )
