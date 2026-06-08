"""Pythonic wrapper around the _dauntless_host extension module.

Re-exports the binding functions with type hints. Application code should
import from here, not from _dauntless_host directly.
"""
from typing import Tuple

import _dauntless_host as _h

InstanceId = _h.InstanceId


def init(width: int, height: int, title: str) -> None:
    _h.init(width, height, title)


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


def set_bridge_wall_time(t: float) -> None:
    """Advance NiFlipController-driven texture animations on the bridge.

    Called each tick with a monotonic wall clock; the bridge pass uses
    this to compute the current animation frame per material.
    """
    _h.set_bridge_wall_time(t)


def damage_decals_tick(game_time: float) -> None:
    """Age every ship's persistent damage-decal ring on the game clock.

    Reclaims cold phaser heat-glows and supplies the shader's decal time
    (drives ember cool-down). Must be called each tick; without it the decal
    clock stays frozen and glows never cool.
    """
    _h.damage_decals_tick(game_time)


def set_suns(suns: list) -> None:
    """Configure the renderer's sun list. Each entry is a dict:
        {"position": (x,y,z), "radius": float,
         "base_texture_path": str, "corona_radius": float,
         "flare_texture_path": str}
    flare_texture_path == "" disables the flare-overlay layer for that sun
    (body + corona still draw).
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


def set_dust_enabled(enabled: bool) -> None:
    """Toggle the space-dust pass. Default: on after init()."""
    _h.dust_set_enabled(enabled)


def set_dust_density(count: int) -> None:
    """Reseed the dust particle buffer with `count` particles
    (clamped to [0, 50000])."""
    _h.dust_set_density(count)


def set_dust_planets(planets: list) -> None:
    """Configure planet centres+radii used by the dust pass for proximity
    density scaling. Each entry is a dict {position: (x,y,z), radius: r}
    in game units. Applied each frame()."""
    _h.set_dust_planets(planets)


def set_specular_enabled(enabled: bool) -> None:
    """Toggle the opaque-pass specular term. Default: on after init()."""
    _h.specular_set_enabled(enabled)


def set_rim_enabled(enabled: bool) -> None:
    """Toggle the opaque-pass Fresnel rim term. Default: on after init()."""
    _h.rim_set_enabled(enabled)


def set_hdr_enabled(enabled: bool) -> None:
    """Toggle the HDR resolve (tonemap+bloom+grade). Default: on after init()."""
    _h.hdr_set_enabled(enabled)


def set_decals_enabled(enabled: bool) -> None:
    """Toggle persistent hull damage decals (scorch/heat-glow). Default: on
    after init()."""
    _h.decals_set_enabled(enabled)


def set_rim_eligible(instance_id: InstanceId, eligible: bool) -> None:
    """Mark a ship-hull instance as eligible for the Fresnel rim term.
    Planets are left ineligible so they don't receive a metallic rim."""
    _h.set_rim_eligible(instance_id, eligible)


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


# ── CEF overlay ─────────────────────────────────────────────────────────────

def cef_initialize(view_width: int, view_height: int, html_path: str,
                   device_scale_factor: float = 1.0) -> bool:
    """Initialise the CEF overlay browser. Idempotent; returns True on success.

    ``device_scale_factor`` should match the GL framebuffer's DPR
    (framebuffer_size / window_size). On Retina that's typically 2.0;
    on non-Retina it's 1.0. CEF then renders the bitmap at view_size *
    dsf so the composite pass can blit 1:1 without bilinear upscaling.
    """
    return _h.cef_initialize(view_width, view_height, html_path,
                             device_scale_factor=device_scale_factor)


def cef_pump() -> None:
    """Run one iteration of CEF's message loop. Call once per frame."""
    _h.cef_pump()


def cef_composite() -> None:
    """Blit the latest CEF bitmap over the current framebuffer."""
    _h.cef_composite()


def cef_shutdown() -> None:
    """Tear down CEF. Call before the GL context is destroyed."""
    _h.cef_shutdown()


def cef_toggle_devtools() -> None:
    """Open or close the DevTools window for the overlay browser."""
    _h.cef_toggle_devtools()


def cef_reload() -> None:
    """Reload the overlay browser's current document."""
    _h.cef_reload()
