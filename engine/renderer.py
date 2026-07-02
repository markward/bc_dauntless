"""Pythonic wrapper around the _dauntless_host extension module.

Re-exports the binding functions with type hints. Application code should
import from here, not from _dauntless_host directly.
"""
import logging
from typing import Tuple

import _dauntless_host as _h

_logger = logging.getLogger(__name__)

InstanceId = _h.InstanceId


# ── Native-binding manifest ──────────────────────────────────────────────────
# The set of _dauntless_host bindings this façade expects. `host_bindings.cc`
# compiles into *both* build/dauntless and the _dauntless_host module, so a
# forgotten `cmake --build` leaves a stale .so where an entire feature silently
# no-ops while every test stays green. validate_bindings() (below) checks the
# live module against this manifest at real-host boot to catch that loudly.
#
# The manifest is hand-maintained but kept honest by
# tests/unit/test_renderer_binding_manifest.py, which derives ground truth from
# this file's own `_h.NAME` / `getattr(_h, "NAME")` references — you cannot add
# or remove a wrapper without updating the manifest, or the gate goes red.
#
# REQUIRED: called hard (`_h.NAME(...)`). A missing one is a broken/stale build —
#   the façade crashes the moment that code path runs. `InstanceId` (a type,
#   resolved at the import above) is deliberately excluded: its absence already
#   hard-fails `import`, so it needs no manifest entry.
_REQUIRED_BINDINGS = frozenset({
    "add_sphere_region", "assemble_officer", "bridge_pass_set_enabled",
    "cef_composite", "cef_initialize", "cef_pump", "cef_reload", "cef_shutdown",
    "cef_toggle_devtools", "clear_hologram_ship", "clear_subsystem_pins",
    "clear_viewscreen_comm_source", "compute_capsule_region",
    "consume_mouse_delta", "create_bridge_instance", "create_comm_instance",
    "create_instance", "damage_decals_tick", "decals_set_enabled",
    "destroy_instance", "dust_set_density", "dust_set_enabled", "filmic_enabled",
    "filmic_set_enabled", "frame", "get_instance_bounds",
    "get_instance_head_center", "hdr_set_enabled", "init", "load_animation_clips",
    "load_instance_clip", "load_model", "model_aabb", "motion_blur_enabled",
    "motion_blur_set_enabled", "nebula_lightning_enabled",
    "nebula_lightning_set_enabled", "play_instance_gesture", "play_instance_idle",
    "procedural_sky_enabled", "procedural_sky_set_enabled", "restore_rest_pose",
    "rim_set_enabled", "set_backdrops", "set_bridge_camera", "set_bridge_lighting",
    "set_bridge_wall_time", "set_camera", "set_comm_set_id", "set_cursor_locked",
    "set_dust_planets", "set_emissive_scale", "set_glow_region_dim",
    "set_hologram_only_mode", "set_hologram_ship", "set_hull_discharges",
    "set_instance_animation", "set_instance_rest_pose", "set_lens_flares",
    "set_lighting", "set_nebula_godrays", "set_nebula_wake", "set_nebulae",
    "set_rim_eligible", "set_subsystem_pins", "set_suns",
    "set_viewscreen_brightness", "set_viewscreen_comm_source",
    "set_viewscreen_enabled", "set_viewscreen_model", "set_viewscreen_static",
    "set_viewscreen_static_source", "set_visible", "set_warp_flash_intensity",
    "set_warp_streak_intensity", "set_warp_travel_dir", "set_world_transform",
    "shadows_set_enabled", "shield_hit", "shield_register", "shield_unregister",
    "should_close", "shutdown", "smaa_set_enabled", "specular_set_enabled",
    "volumetric_nebulae_enabled", "volumetric_nebulae_set_enabled",
    "warp_flythrough_enabled", "warp_flythrough_set_enabled",
})

# OPTIONAL: soft-guarded (`getattr(_h, "NAME", None)` / `hasattr(_h, "NAME")`).
# These degrade to no-ops by design and may be legitimately absent in a minimal
# or headless build config — so a missing one is warned (under --developer),
# never fatal. `set_officer_face` also appears as a hard `_h.set_officer_face`
# call *inside* its own hasattr guard, so it is optional despite that inner ref.
_OPTIONAL_BINDINGS = frozenset({
    "cef_execute_javascript", "clear_spv_overlay_beams", "clear_target_reticle",
    "instance_node_world", "instance_surface_points", "play_instance_node_anim",
    "play_instance_node_clip", "set_cloak_dials", "set_cloak_ships",
    "set_officer_face", "set_spv_overlay_beams", "set_target_reticle",
    "spawn_test_character", "stop_instance_node_anim",
})


def validate_bindings(*, strict: bool = False) -> list[str]:
    """Check the live `_h` module against the binding manifest at real-host boot.

    Returns the sorted list of every missing binding name (empty == clean) so it
    is assertable without scraping log output. Catches a stale/incomplete .so
    loudly at startup rather than as a silently-dead feature mid-mission.

    Required-missing → logged at ERROR (always); raises RuntimeError if `strict`.
    Optional-missing → logged at WARNING (only under --developer); never raises.

    Invoked only from the real-host boot path (host_loop.run, right after
    r.init). Unit tests that monkeypatch `renderer._h` never call it, so their
    partial fakes are never inspected; and it never runs at import time.
    """
    missing_required = sorted(n for n in _REQUIRED_BINDINGS if not hasattr(_h, n))
    missing_optional = sorted(n for n in _OPTIONAL_BINDINGS if not hasattr(_h, n))

    if missing_required:
        _logger.error(
            "_dauntless_host is missing required binding(s) — stale/incomplete "
            "native module; rebuild with `cmake --build build -j`: %s",
            ", ".join(missing_required),
        )
    if missing_optional:
        # Lazy import avoids any import-order coupling; dev_mode imports
        # _dauntless_host, not renderer, so there is no cycle either way.
        from engine import dev_mode
        if dev_mode.is_enabled():
            _logger.warning(
                "_dauntless_host is missing optional binding(s) — the matching "
                "features will silently no-op: %s",
                ", ".join(missing_optional),
            )

    if missing_required and strict:
        raise RuntimeError(
            "missing required _dauntless_host bindings (rebuild the native "
            "module with `cmake --build build -j`): " + ", ".join(missing_required)
        )
    return sorted(set(missing_required) | set(missing_optional))


def init(width: int, height: int, title: str) -> None:
    _h.init(width, height, title)


def shutdown() -> None:
    _h.shutdown()


def should_close() -> bool:
    return _h.should_close()


def frame() -> None:
    _h.frame()


def load_model(nif_path: str, texture_search_path,
               texture_replacements=None) -> int:
    """Load (and cache) a NIF model. `texture_replacements`, when given, is a
    list of (old_substring, new_abs_path) pairs baking BC ReplaceTexture swaps
    into a distinct per-registry model variant (Federation hull names). None /
    empty is byte-identical to the plain load."""
    return _h.load_model(nif_path, texture_search_path, texture_replacements)


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


def procedural_sky_enabled() -> bool:
    """True when the procedural sky (Modern VFX) is on; False = stock BC."""
    return _h.procedural_sky_enabled()


def set_procedural_sky_enabled(enabled: bool) -> None:
    """Toggle the map-driven procedural sky. On = the baked galaxy sky;
    Off = the original STBC authored starbox (byte-identical stock BC)."""
    _h.procedural_sky_set_enabled(enabled)


def filmic_enabled() -> bool:
    """Read the Filmic Filter toggle (Modern VFX). Default: on."""
    return _h.filmic_enabled()


def set_filmic_enabled(enabled: bool) -> None:
    """Toggle the Filmic Filter (Modern VFX): film grain + vignette +
    chromatic aberration on the exterior view. Default: on."""
    _h.filmic_set_enabled(enabled)


def motion_blur_enabled() -> bool:
    """Read the Motion Blur toggle (Modern VFX). Default: on."""
    return _h.motion_blur_enabled()


def set_motion_blur_enabled(enabled: bool) -> None:
    """Toggle camera Motion Blur (Modern VFX) on the exterior view. Default: on."""
    _h.motion_blur_set_enabled(enabled)


def warp_flythrough_enabled() -> bool:
    """Read the Warp Flythrough toggle (Modern VFX). Default: on."""
    return _h.warp_flythrough_enabled()


def set_warp_flythrough_enabled(enabled: bool) -> None:
    """Toggle the warp flythrough VFX (Modern VFX). Off = instant hard cut."""
    _h.warp_flythrough_set_enabled(enabled)


def set_warp_streak_intensity(intensity: float) -> None:
    """Set the 0..1 star-streak intensity for the warp flythrough."""
    _h.set_warp_streak_intensity(float(intensity))


def set_warp_flash_intensity(intensity: float) -> None:
    """Set the 0..1 warp-flash intensity for the warp flythrough."""
    _h.set_warp_flash_intensity(float(intensity))


def set_warp_travel_dir(direction) -> None:
    """Set the world-space travel direction (x, y, z) for the warp flythrough."""
    x, y, z = direction
    _h.set_warp_travel_dir(float(x), float(y), float(z))


def volumetric_nebulae_enabled() -> bool:
    """Read the Volumetric Nebulae toggle (Modern VFX). Default: on."""
    return _h.volumetric_nebulae_enabled()


def set_volumetric_nebulae_enabled(enabled: bool) -> None:
    """Toggle Volumetric Nebulae (Modern VFX). Default: on."""
    _h.volumetric_nebulae_set_enabled(enabled)


def nebula_lightning_enabled() -> bool:
    """Read the Nebula Lightning toggle (Modern VFX). Default: on."""
    return _h.nebula_lightning_enabled()


def set_nebula_lightning_enabled(enabled: bool) -> None:
    """Toggle Nebula Lightning (Modern VFX). Default: on."""
    _h.nebula_lightning_set_enabled(enabled)


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


def set_nebulae(nebulae: list) -> None:
    """Configure the active set's MetaNebula volumes for the nebula pass.
    Each entry: {"spheres": [(x,y,z,r)...], "rgb": (r,g,b),
    "visibility": float, "external_tex": str, "internal_tex": str,
    "fbm": (freq, gain, floor), "seed": (sx, sy, sz)}.
    Empty list = no nebula (pass early-outs)."""
    _h.set_nebulae(nebulae)


def set_nebula_wake(points: list) -> None:
    """Player nebula wake trail points for the additive billboard pass.
    Each: {"pos": (x,y,z), "strength": float, "size": float}. Empty = no wake."""
    _h.set_nebula_wake(points)


def set_nebula_godrays(flashes: list) -> None:
    """Active lightning flashes for the god-ray pass. Each: {"dir": (x,y,z),
    "intensity": float, "color": (r,g,b)}. Empty list = no god-rays."""
    _h.set_nebula_godrays(flashes)


def set_hull_discharges(discharges: list) -> None:
    """Active hull electrical discharges for the crackle pass. Each:
    {"world_pos": (x,y,z), "age": float, "life": float, "size": float,
     "color": (r,g,b)}. Empty list = none."""
    _h.set_hull_discharges(discharges)


def set_specular_enabled(enabled: bool) -> None:
    """Toggle the opaque-pass specular term. Default: on after init()."""
    _h.specular_set_enabled(enabled)


def set_rim_enabled(enabled: bool) -> None:
    """Toggle the opaque-pass Fresnel rim term. Default: on after init()."""
    _h.rim_set_enabled(enabled)


def set_hdr_enabled(enabled: bool) -> None:
    """Toggle the HDR resolve (tonemap+bloom+grade). Default: on after init()."""
    _h.hdr_set_enabled(enabled)


def set_shadows_enabled(enabled: bool) -> None:
    """Toggle sun shadow mapping (Modern VFX). Default: on after init()."""
    _h.shadows_set_enabled(enabled)


def set_decals_enabled(enabled: bool) -> None:
    """Toggle persistent hull damage decals (scorch/heat-glow). Default: on
    after init()."""
    _h.decals_set_enabled(enabled)


def set_smaa_enabled(enabled: bool) -> None:
    """Toggle the post-process SMAA 1x pass. Default: on after init()."""
    _h.smaa_set_enabled(enabled)


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


def create_comm_instance(model: int) -> InstanceId:
    """Like create_instance but tags the new instance for the comm pass."""
    return _h.create_comm_instance(model)


def set_comm_set_id(iid: "InstanceId", set_id: int) -> None:
    """Tag a comm-pass instance with a set id for active-set filtering."""
    _h.set_comm_set_id(iid, set_id)


def assemble_officer(body_nif: str, head_nif: str,
                     body_tex=None, head_tex=None,
                     placement_nif=None, sample_at_start: bool = False,
                     face_images=None) -> int:
    """SP3: compose a bridge officer from a body NIF + head NIF (head grafted
    onto the body's 'Bip01 Head' bone), overriding the body/head Base textures,
    and load placement_nif's clip into the composed model's animations[0].
    Returns a ModelHandle. The caller plays the clip via set_instance_animation.

    face_images (optional): {slot: tga_path} lip-sync face textures, slots
    'a'/'e'/'u'/'blink1'/'blink2'/'eyesclosed'; uploaded for set_officer_face.
    """
    return _h.assemble_officer(body_nif, head_nif, body_tex, head_tex,
                               placement_nif, sample_at_start,
                               face_images or {})


def set_officer_face(iid: InstanceId, slot_a: str, slot_b: str, mix: float) -> None:
    """Lip-sync: blend an officer's head face texture between two slots by mix.
    Slots: 'neutral','a','e','u','blink1','blink2','eyesclosed'. No-op without
    an engine/renderer (hasattr-guarded), mirroring the other r.* wrappers."""
    if hasattr(_h, "set_officer_face"):
        _h.set_officer_face(iid, slot_a, slot_b, float(mix))


def load_instance_clip(iid: InstanceId, nif_path: str) -> int:
    """Append a NIF's animation clips to this officer instance's model.

    Returns the first new clip index (>= 1; index 0 is the placement clip baked
    at assemble_officer time), or -1 on failure (bad iid, unreadable NIF, NIF
    has no clips). Idempotent: repeated calls with the same path return the same
    index without re-appending, so the Task-5 controller can call this freely
    on every gesture start without unbounded model growth. Officer models are
    per-instance (assemble_officer never dedupes), so this never bleeds across
    characters.
    """
    return _h.load_instance_clip(iid, nif_path)


def set_instance_animation(iid: InstanceId, clip_index: int,
                           loop: bool = False,
                           sample_at_start: bool = False) -> None:
    """SP2: play model.animations[clip_index] on this instance through the GPU
    bone palette. loop=False plays once and holds the last frame;
    sample_at_start holds frame 0 instead (for move-from-station clips)."""
    _h.set_instance_animation(iid, clip_index, loop, sample_at_start)


def set_instance_rest_pose(iid: InstanceId, clip_index: int,
                           at_start: bool = False) -> None:
    """Freeze an officer at its static placement (rest) pose. at_start holds
    frame 0 (move-from-station clips); otherwise the last frame (stand/seated
    clips). Faithful to the SDK's TGAnimPosition — no play-through."""
    _h.set_instance_rest_pose(iid, clip_index, at_start)


def restore_rest_pose(iid: InstanceId) -> None:
    """Snap the instance back to its stored rest pose (AT_DEFAULT)."""
    _h.restore_rest_pose(iid)


def play_instance_idle(iid: InstanceId, clip_index: int) -> None:
    """Loop a layered idle (breathing) over the officer's rest pose: the idle
    clip drives the body, the placement supplies the root. Loops until a gesture
    or restore_rest_pose replaces it."""
    _h.play_instance_idle(iid, clip_index)


def play_instance_gesture(iid: InstanceId, clip_index: int) -> None:
    """Play a transient gesture/reaction clip layered over the officer's rest
    pose (root + un-animated bones stay at the station; only gesture-tracked
    bones move). Plays once and holds the last frame until restore_rest_pose."""
    _h.play_instance_gesture(iid, clip_index)


def play_instance_node_anim(iid: InstanceId, clip_index: int,
                            loop: bool = False, reverse: bool = False) -> None:
    """Play a non-skinned instance's embedded clip on its node hierarchy
    (bridge doors). No-op without the host binding (headless)."""
    fn = getattr(_h, "play_instance_node_anim", None)
    if fn is not None:
        fn(iid, clip_index, loop, reverse)


def play_instance_node_clip(iid: InstanceId, path: str,
                            loop: bool = False, reverse: bool = False) -> None:
    """Play an external NIF clip on a non-skinned instance's node hierarchy
    (chair turn). No-op without the host binding (headless)."""
    fn = getattr(_h, "play_instance_node_clip", None)
    if fn is not None:
        fn(iid, path, loop, reverse)


def stop_instance_node_anim(iid: InstanceId) -> None:
    """Clear any bridge-node clip + overrides on this instance."""
    fn = getattr(_h, "stop_instance_node_anim", None)
    if fn is not None:
        fn(iid)


def instance_node_world(iid: InstanceId, node_name: str,
                        animated: bool = True):
    """16 floats (row-major) of the named node's world transform, or None."""
    fn = getattr(_h, "instance_node_world", None)
    return fn(iid, node_name, animated) if fn is not None else None


def instance_surface_points(iid: InstanceId):
    """World-space sample of the instance model's hull surface points (spread
    across the hull) for VFX anchoring. Returns a list of (x,y,z), or []."""
    fn = getattr(_h, "instance_surface_points", None)
    r = fn(iid) if fn is not None else None
    return r if r else []


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


def set_viewscreen_comm_source(set_id, eye, target, up, fov_y_rad, near, far) -> None:
    """Configure the comm viewscreen feed to render a remote set through the
    given camera parameters."""
    _h.set_viewscreen_comm_source(set_id, eye, target, up, fov_y_rad, near, far)


def clear_viewscreen_comm_source() -> None:
    """Disable the comm viewscreen feed, returning to the space view."""
    _h.clear_viewscreen_comm_source()


def set_viewscreen_static_source(paths) -> None:
    """Register the noise texture frames (absolute paths) for the viewscreen
    static overlay. Idempotent on the native side (cached by path)."""
    _h.set_viewscreen_static_source(paths)


def set_viewscreen_static(on, intensity) -> None:
    """Enable/disable the viewscreen static overlay and set this frame's
    intensity (0..1). Composited over the comm/forward feed in the RTT."""
    _h.set_viewscreen_static(on, intensity)


def set_viewscreen_brightness(b) -> None:
    """Multiplier (0..1) applied to the viewscreen content for the
    ViewOn/ViewOff fade. 1.0 = full brightness (no fade)."""
    _h.set_viewscreen_brightness(b)


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


# ── Cloak refraction ─────────────────────────────────────────────────────────

def set_cloak_ships(ships) -> None:
    """Set the cloaking ships drawn as refractive shells this frame.

    ``ships`` is a list of ``(instance_id, frac)`` where ``frac`` in [0, 1] is
    cloak progress (0 = visible, 1 = fully cloaked). The pass bends and
    chromatically disperses the scene behind each hull. An empty list draws
    none. No-op on a stale binary that predates the binding."""
    fn = getattr(_h, "set_cloak_ships", None)
    if fn is None:
        return
    fn([(iid, float(frac)) for iid, frac in ships])


def set_cloak_dials(strength: float = 0.04, dispersion: float = 0.50,
                    tint=(0.20, 0.85, 0.55), opacity_floor: float = 0.10,
                    opacity_ceiling: float = 0.50, shimmer_amp: float = 0.010,
                    shimmer_speed: float = 6.0, vertex_wobble: float = 0.05,
                    normal_bias: float = 1.0) -> None:
    """Live-tune the cloak. ``strength`` = max screen-space refraction offset,
    ``dispersion`` = prism split, ``tint`` = rim glow (r,g,b). The cloaked hull
    keeps its textures with the glow map keying opacity between ``opacity_floor``
    (dark hull) and ``opacity_ceiling`` (glowing surfaces). ``shimmer_amp`` /
    ``shimmer_speed`` drive an animated screen-space wobble; ``vertex_wobble``
    (game units) displaces the silhouette; ``normal_bias`` in [0,1] weights the
    refraction toward grazing surfaces. No-op on a stale binary."""
    fn = getattr(_h, "set_cloak_dials", None)
    if fn is None:
        return
    fn(float(strength), float(dispersion), tuple(tint), float(opacity_floor),
       float(opacity_ceiling), float(shimmer_amp), float(shimmer_speed),
       float(vertex_wobble), float(normal_bias))


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
