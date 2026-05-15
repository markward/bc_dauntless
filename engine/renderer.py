"""Pythonic wrapper around the _open_stbc_host extension module.

Re-exports the binding functions with type hints. Application code should
import from here, not from _open_stbc_host directly.
"""
from typing import Tuple

import _open_stbc_host as _h

InstanceId = _h.InstanceId


def init(width: int, height: int, title: str, ui_assets_root: str = "") -> None:
    _h.init(width, height, title, ui_assets_root)


def shutdown() -> None:
    _h.shutdown()


def should_close() -> bool:
    return _h.should_close()


def frame() -> None:
    _h.frame()


def load_model(nif_path: str, texture_search_path: str) -> int:
    return _h.load_model(nif_path, texture_search_path)


def create_instance(model: int) -> InstanceId:
    return _h.create_instance(model)


def destroy_instance(iid: InstanceId) -> None:
    _h.destroy_instance(iid)


def set_world_transform(iid: InstanceId, mat4_row_major: list) -> None:
    _h.set_world_transform(iid, mat4_row_major)


def set_visible(iid: InstanceId, visible: bool) -> None:
    _h.set_visible(iid, visible)


def set_camera(eye: Tuple[float, float, float],
               target: Tuple[float, float, float],
               up: Tuple[float, float, float],
               fov_y_rad: float, near: float, far: float) -> None:
    _h.set_camera(eye, target, up, fov_y_rad, near, far)


def set_lighting(ambient: Tuple[float, float, float],
                 directionals: list) -> None:
    """Configure the renderer's lighting state for subsequent frame()s.

    `directionals` is a list of ((dx, dy, dz), (r, g, b)) tuples where
    (dx, dy, dz) is the direction TOWARD the light source and (r, g, b)
    is the color × dimmer product. Up to 4 entries are honored;
    additional ones are silently dropped by the bindings.
    """
    _h.set_lighting(ambient, directionals)


def set_bridge_lighting(ambient: Tuple[float, float, float],
                        directionals: list) -> None:
    """Configure the bridge pass's lighting for subsequent frame()s.

    Same shape as set_lighting, but feeds the bridge pass exclusively.
    Stock BC bridges author only ambient (directionals empty).
    """
    _h.set_bridge_lighting(ambient, directionals)


def set_suns(suns: list) -> None:
    """Configure the renderer's sun list. Each entry is a dict:
        {"position": (x,y,z), "radius": float,
         "base_texture_path": str, "corona_radius": float}
    """
    _h.set_suns(suns)


def set_lens_flares(flares: list) -> None:
    """Configure the renderer's lens-flare list. Each entry is a dict:
        {
            "source_world_pos": (x, y, z),
            "elements": [
                {
                    "wedges":       int,    # 3..64
                    "texture_path": str,    # absolute
                    "position":     float,  # 0=at source, 1=screen center, 2=opposite
                    "size":         float,  # fraction of viewport height
                    "freq":         float,  # Hz wobble (0 = off)
                    "amp":          float,  # wobble amplitude (0 = off)
                }, ...
            ],
        }
    """
    _h.set_lens_flares(flares)


def set_backdrops(backdrops: list) -> None:
    """Configure the renderer's ordered backdrop list. Each entry is a
    dict matching engine.appc.backdrops.aggregate_for_renderer's output:

        {
            "texture_path": str (absolute),
            "kind": "star" | "backdrop",
            "h_tile": float, "v_tile": float,
            "h_span": float, "v_span": float,
            "world_rotation": list[9],
            "target_poly_count": int,
        }
    """
    _h.set_backdrops(backdrops)


def set_hud_state(state: dict) -> None:
    """Push per-tick HUD data (pos, yaw/pitch/roll deg, system, ship) to the overlay.

    No-op if the UI system was not initialized (headless runs, empty ui_assets_root).
    """
    _h.set_hud_state(state)


def set_dust_enabled(enabled: bool) -> None:
    """Toggle the space-dust pass. Default: on after init()."""
    _h.dust_set_enabled(enabled)


def set_dust_density(count: int) -> None:
    """Reseed the dust particle buffer with `count` particles
    (clamped to [0, 50000])."""
    _h.dust_set_density(count)


# ── Shield pass ─────────────────────────────────────────────────────────────

def model_aabb(model: int) -> Tuple[Tuple[float, float, float],
                                     Tuple[float, float, float]]:
    """Return (center, half_extents) of a loaded model's CPU-side vertex
    union. Used by engine.shields to size the shield bubble."""
    return _h.model_aabb(model)


def shield_register(instance_id: InstanceId, mode: int, decay_seconds: float,
                    default_color: Tuple[float, float, float, float],
                    aabb_center: Tuple[float, float, float],
                    aabb_half_extents: Tuple[float, float, float]) -> None:
    """Register a ship's shield state with the render pass. mode=0 ellipsoid,
    mode=1 skin. default_color is the ShieldGlowColor RGBA the renderer
    substitutes when shield_hit is called with rgba=(0,0,0,0)."""
    _h.shield_register(instance_id, mode, decay_seconds, default_color,
                       aabb_center, aabb_half_extents)


def shield_unregister(instance_id: InstanceId) -> None:
    """Remove a ship's shield state. No-op if unregistered."""
    _h.shield_unregister(instance_id)


def shield_hit(instance_id: InstanceId,
               point: Tuple[float, float, float],
               rgba: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
               intensity: float = 1.0) -> None:
    """Push a shield-hit flash for the given ship at a world-space point.
    rgba=(0,0,0,0) substitutes the ship's default ShieldGlowColor."""
    _h.shield_hit(instance_id, point, rgba, intensity)


# ── Bridge view ─────────────────────────────────────────────────────────────

def create_bridge_instance(model: int) -> InstanceId:
    """Like create_instance but tags the new instance for the bridge pass."""
    return _h.create_bridge_instance(model)


def set_bridge_camera(eye: Tuple[float, float, float],
                      target: Tuple[float, float, float],
                      up: Tuple[float, float, float],
                      fov_y_rad: float, near: float, far: float) -> None:
    """Set the bridge pass camera. No-op until bridge_pass_set_enabled(True)."""
    _h.set_bridge_camera(eye, target, up, fov_y_rad, near, far)


def bridge_pass_set_enabled(enabled: bool) -> None:
    """Enable or disable the bridge render pass."""
    _h.bridge_pass_set_enabled(enabled)


def consume_mouse_delta() -> Tuple[float, float]:
    """Return (dx, dy) accumulated cursor motion in pixels since the last
    call. Reset on each call. GLFW raw mode while cursor is locked."""
    return _h.consume_mouse_delta()


def set_cursor_locked(locked: bool) -> None:
    """Lock the cursor (hidden + raw deltas) or release it."""
    _h.set_cursor_locked(locked)
