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


def spawn_test_character(nif_path: str):
    """Dev-only (SP1): load a skinned character NIF and spawn one instance
    framed in front of the active camera, tagged for the active render pass
    (bridge or space) — the host computes placement from its own camera + pass
    state. Returns the InstanceId, or None when the host binding is unavailable
    (e.g. headless tests or a stale .so without it).
    """
    fn = getattr(_h, "spawn_test_character", None)
    if fn is None:
        return None
    return fn(nif_path)


def set_visible(iid: InstanceId, visible: bool) -> None:
    _h.set_visible(iid, visible)


def set_emissive_scale(iid: InstanceId, scale: float) -> None:
    """Scale an instance's self-illumination (emissive + glow). 1.0 = normal,
    0.0 = destroyed/dark hull."""
    _h.set_emissive_scale(iid, scale)


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


def set_hull_damage_enabled(enabled: bool) -> None:
    """Toggle hull-breach renderer pass and carve emission. Default: on after
    init(). Flips both the C++ hull-damage pass flag (via host binding) and
    the Python emission gate so no carve geometry is submitted when off."""
    _h.hull_damage_set_enabled(enabled)
    # Lazily imported to avoid circular-import at module load time.
    from engine.appc import hit_feedback as _hf  # noqa: PLC0415
    _hf._HULL_CARVE_ENABLED = enabled


def set_fxaa_enabled(enabled: bool) -> None:
    """Toggle the post-process FXAA pass. Default: on after init()."""
    _h.fxaa_set_enabled(enabled)


def set_rim_eligible(instance_id: InstanceId, eligible: bool) -> None:
    """Mark a ship-hull instance as eligible for the Fresnel rim term.
    Planets are left ineligible so they don't receive a metallic rim."""
    _h.set_rim_eligible(instance_id, eligible)


def compute_capsule_region(instance_id: InstanceId,
                           center, axis, radius: float) -> int:
    """Fit and store a warp-nacelle glow capsule on the instance.

    center/axis are 3-tuples in game units / body frame; radius in game units.
    Returns the region index (>=0) or -1 on failure.
    """
    return _h.compute_capsule_region(
        instance_id, tuple(center), tuple(axis), float(radius))


def add_sphere_region(instance_id: InstanceId, center, radius: float) -> int:
    """Store a sphere glow region at a hardpoint. center is a 3-tuple in game
    units / body frame; radius in game units. Returns the region index (>=0) or
    -1 on failure. Used for impulse engines and sensor arrays (compact spots);
    warp nacelles use compute_capsule_region for their elongated shape."""
    return _h.add_sphere_region(instance_id, tuple(center), float(radius))


def set_glow_region_dim(instance_id: InstanceId, region_index: int,
                        dim_target: float, disable_time: float,
                        flicker: float) -> None:
    """Update a glow region's dim target [0,1], last state-change edge time
    (game-time secs; <0 = healthy), and flicker flag (1 = disabled/continuous
    flicker, 0 = solid settle)."""
    _h.set_glow_region_dim(instance_id, int(region_index),
                           float(dim_target), float(disable_time), float(flicker))


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


def create_comm_instance(model: int) -> "InstanceId":
    """Like create_instance but tags the new instance for the comm pass."""
    return _h.create_comm_instance(model)


def set_comm_set_id(iid: "InstanceId", set_id: int) -> None:
    """Tag a comm-pass instance with a set id for active-set filtering."""
    _h.set_comm_set_id(iid, set_id)


def assemble_officer(body_nif: str, head_nif: str,
                     body_tex=None, head_tex=None,
                     placement_nif=None, sample_at_start: bool = False) -> int:
    """SP3: compose a bridge officer from a body NIF + head NIF (head grafted
    onto the body's 'Bip01 Head' bone), overriding the body/head Base textures,
    and load placement_nif's clip into the composed model's animations[0].
    Returns a ModelHandle. The caller plays the clip via set_instance_animation.
    """
    return _h.assemble_officer(body_nif, head_nif, body_tex, head_tex,
                               placement_nif, sample_at_start)


def set_instance_animation(iid: InstanceId, clip_index: int,
                           loop: bool = False,
                           sample_at_start: bool = False) -> None:
    """SP2: play model.animations[clip_index] on this instance through the GPU
    bone palette. loop=False plays once and holds the last frame;
    sample_at_start holds frame 0 instead (for move-from-station clips)."""
    _h.set_instance_animation(iid, clip_index, loop, sample_at_start)


def load_animation_clips(path: str) -> list:
    """Parse a NIF's keyframe controllers into animation clips.

    Returns [{"name": str, "duration": float, "tracks": [...]}] where each
    track is {"node": str, "translation": [(t,x,y,z), ...],
    "rotation": [(t,x,y,z,w), ...]}. Used to drive the bridge camera
    walk-on cutscene (see engine/bridge_cutscene.py)."""
    return _h.load_animation_clips(path)


def set_bridge_camera(eye: Tuple[float, float, float],
                      target: Tuple[float, float, float],
                      up: Tuple[float, float, float],
                      fov_y_rad: float, near: float, far: float) -> None:
    """Set the bridge pass camera. No-op until bridge_pass_set_enabled(True)."""
    _h.set_bridge_camera(eye, target, up, fov_y_rad, near, far)


def bridge_pass_set_enabled(enabled: bool) -> None:
    """Enable or disable the bridge render pass."""
    _h.bridge_pass_set_enabled(enabled)


def set_viewscreen_model(handle: int) -> None:
    """Register which loaded model handle is the bridge viewscreen surface, so
    the bridge pass binds the RTT feed texture there. No-op until
    set_viewscreen_enabled(True)."""
    _h.set_viewscreen_model(handle)


def set_viewscreen_enabled(on: bool) -> None:
    """Enable/disable the viewscreen render-to-texture feed. When on (and in
    bridge view), the renderer renders the forward space scene into the
    offscreen target and maps it onto the viewscreen instance."""
    _h.set_viewscreen_enabled(on)


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


# ── Ship Property Viewer ─────────────────────────────────────────────────────

def set_hologram_ship(instance_id: InstanceId,
                      color=(0.30, 0.62, 1.0),
                      opacity_facing: float = 0.20,
                      opacity_grazing: float = 0.70) -> None:
    """Draw the given render instance as a translucent Fresnel hologram.

    instance_id is the InstanceId of the ship's render instance.
    color is the RGB tint (r, g, b) in [0, 1].
    opacity_facing and opacity_grazing control the Fresnel ramp endpoints:
    faces aligned with the camera get opacity_facing (0.20 = 80% transparent),
    faces perpendicular get opacity_grazing (0.70 = 30% transparent).
    """
    _h.set_hologram_ship(instance_id, tuple(color),
                         float(opacity_facing), float(opacity_grazing))


def clear_hologram_ship() -> None:
    """Deactivate the hologram overlay. Takes effect next frame()."""
    _h.clear_hologram_ship()


def set_subsystem_pins(pins: list) -> None:
    """Set the subsystem pin billboard list.

    pins: list of (world_pos:(x, y, z), icon_id:int, highlighted:bool).
    Applied each frame().
    """
    _h.set_subsystem_pins(pins)


def clear_subsystem_pins() -> None:
    """Clear all subsystem pin billboards. Takes effect next frame()."""
    _h.clear_subsystem_pins()


def set_spv_overlay_beams(beams: list) -> None:
    """Set the Ship Property Viewer phaser strip/arc overlay beams.

    `beams` is a list of PhaserBeamDescriptor dicts (engine.ui.phaser_overlay).
    No-ops silently if the host binding is unavailable (headless / pre-rebuild).
    """
    fn = getattr(_h, "set_spv_overlay_beams", None)
    if fn is not None:
        fn(beams)


def clear_spv_overlay_beams() -> None:
    """Clear the SPV phaser overlay beams. Takes effect next frame()."""
    fn = getattr(_h, "clear_spv_overlay_beams", None)
    if fn is not None:
        fn()


def set_target_reticle(payload) -> None:
    """Feed the target reticle pass from a target_reticle.TargetReticlePayload.

    No-ops silently if the host binding is unavailable (headless tests).
    """
    fn = getattr(_h, "set_target_reticle", None)
    if fn is None:
        return
    fn(payload.visible, payload.ship_center, payload.ship_radius,
       payload.subtarget_pos, payload.bar_alignment)


def clear_target_reticle() -> None:
    """Hide the target reticle. Takes effect next frame()."""
    fn = getattr(_h, "clear_target_reticle", None)
    if fn is not None:
        fn()


def set_reticle_text(payload) -> None:
    """Push the reticle text overlay state (a build_reticle_text dict) to CEF.

    Reuses the existing cef_execute_javascript binding (present in both the
    CEF and no-CEF build configs); no-ops silently when unavailable (headless).
    """
    import json as _json
    fn = getattr(_h, "cef_execute_javascript", None)
    if fn is None:
        return
    fn("setReticleText(" + _json.dumps(payload) + ");")


def clear_reticle_text() -> None:
    """Hide the reticle text overlay. Takes effect next CEF pump."""
    fn = getattr(_h, "cef_execute_javascript", None)
    if fn is not None:
        fn('setReticleText({"visible": false});')


def set_hologram_only_mode(enabled: bool, bg=(0.0, 0.0, 0.0)) -> None:
    """When enabled, frame() clears to bg (r, g, b) and skips the space scene
    and bridge pass, drawing only the hologram + subsystem pins."""
    _h.set_hologram_only_mode(bool(enabled), tuple(bg))


def get_instance_bounds(instance_id: InstanceId):
    """World-space bounding sphere of an instance's model as
    (cx, cy, cz, radius), or None if the instance/model is not resolvable."""
    return _h.get_instance_bounds(instance_id)


def get_instance_head_center(instance_id: InstanceId):
    """World-space centre (cx, cy, cz) of a posed character's HEAD (vertices
    bound to 'Bip01 Head'), or the full skinned centre if there's no head bone,
    or None if unskinned / not yet posed. The officer zoom look-at point.
    Unlike get_instance_bounds (static AABB x instance world transform), this
    applies the bone palette — a bridge officer sits at an identity instance
    transform with their station offset baked into the palette."""
    return _h.get_instance_head_center(instance_id)
