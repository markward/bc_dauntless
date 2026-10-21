"""Pythonic wrapper around the _dauntless_host extension module (non-render).

Sibling of engine.renderer, covering the *non-render* surface of
_dauntless_host: window/input polling, per-frame VFX descriptor lists, and the
hit/damage feedback bindings. Application code should import from here, not from
_dauntless_host directly.

This is the same manifest-validated pattern renderer.py uses, for the same
reason: `host_bindings.cc` compiles into *both* build/dauntless and the
_dauntless_host module, so a forgotten `cmake --build` leaves a stale .so where
an entire feature silently no-ops while every test stays green.
validate_bindings() (below) checks the live module against this manifest at
real-host boot to catch that loudly.

The manifest is hand-maintained but kept honest by
tests/unit/test_host_io_binding_manifest.py, which derives ground truth from
this file's own `_h.NAME` references — you cannot add or remove a wrapper
without updating the manifest, or the gate goes red.

Headless / not-built is a *different* condition from a stale build: the
extension may be legitimately absent (unit tests, headless import contexts). We
import it guarded and every wrapper treats `_h is None` as a no-op / safe
default WITHOUT raising. validate_bindings() is the single check point for the
stale-build case; it is never invoked at import time.
"""
import logging
from typing import List, Optional, Tuple

from engine import input_map

try:
    import _dauntless_host as _h
except ImportError:
    _h = None  # bindings module not built; headless — wrappers no-op.

_logger = logging.getLogger(__name__)


# ── Native-binding manifest ──────────────────────────────────────────────────
# REQUIRED: called hard (`_h.NAME(...)`). A missing one is a broken/stale build —
#   the façade crashes the moment that code path runs.
_REQUIRED_BINDINGS = frozenset({
    "key_state", "key_pressed", "mouse_button_pressed", "mouse_button_released",
    "consume_mouse_delta", "set_cursor_locked", "framebuffer_size", "window_size",
    "set_torpedoes", "set_shockwaves", "set_hit_vfx", "set_particle_emitters",
    "set_dynamic_lights",
    "set_phaser_beams", "set_tractor_beams",
    "cursor_pos",
    "shield_hit", "world_to_body", "damage_decal_add",
    "hull_damage_add", "hull_damage_add_body",
    "model_nodes", "model_nearest_part", "set_instance_decals",
    "hull_split_parts", "structure_part_at", "breach_burst",
    "ray_trace_mesh", "instance_translation",
    "transform_alloc", "transform_free", "transform_get_position",
    "transform_set_position", "transform_get_rotation", "transform_set_rotation",
    "transform_get_rotation_col", "transform_get_positions",
    "transform_live_count", "transform_capacity",
    "set_instance_transform_slot",
    "set_instance_node_transform",
    "clear_instance_node_overrides",
    "set_instance_node_hidden", "instance_model",
    "drain_text_events", "cef_send_text_events", "cef_reset_text_translator",
    "request_relaunch",
    "set_key_capture", "key_capture_active",
    # Not a function: the InstanceId type itself. set_instance_transform_slot
    # isinstance-checks against it to tell a real render instance from a test
    # double's plain int, so a build without it is just as broken as one
    # missing a call.
    "InstanceId",
})

# OPTIONAL: soft-guarded (`getattr(_h, "NAME", None)` / `hasattr(_h, "NAME")`).
# A missing one degrades to a no-op (warned at boot under --developer) rather
# than raising AttributeError mid-mission. The star map bindings are optional
# because a stale .so must leave the Set Course modal usable-but-blank, not
# crash the helm menu the moment the player opens it.
_OPTIONAL_BINDINGS = frozenset({
    "starmap_set_enabled", "starmap_set_viewport",
    "starmap_set_camera", "starmap_set_scene",
    "profiler_set_enabled", "profiler_enabled",
    "profiler_set_gpu_enabled", "profiler_gpu_enabled",
    "profiler_set_gpu_focus",
    "profiler_scopes", "profiler_frame", "profiler_last_frame_raw",
    "set_swap_interval", "swap_interval",
    "set_cursor_shape",
    "ray_trace_mesh_pick", "model_identity", "set_bridge_highlight",
    "set_bridge_material_overrides", "set_bridge_pbr_enabled",
    "set_bridge_probe_origin", "set_bridge_probe_scales",
    "request_bridge_probe_capture",
    "set_bridge_spots", "set_bridge_alert_level",
    "set_bridge_spot_colours", "set_bridge_glow",
    "set_bridge_area_lights", "set_bridge_area_colours", "bridge_mesh_geometry",
    "set_bridge_glow_captures", "set_bridge_probe_layers",
    "bridge_probe_signatures", "bridge_quality",
    "set_bridge_probe_state", "set_bridge_layer_values",
})


def validate_bindings(*, strict: bool = False) -> List[str]:
    """Check the live `_h` module against the binding manifest at real-host boot.

    Returns the sorted list of every missing binding name (empty == clean) so it
    is assertable without scraping log output. Catches a stale/incomplete .so
    loudly at startup rather than as a silently-dead feature mid-mission.

    Required-missing → logged at ERROR (always); raises RuntimeError if `strict`.
    Optional-missing → logged at WARNING (only under --developer); never raises.

    The `keys` submodule is treated as a required entry: input verification
    depends on it, and an editing slip in host_bindings.cc dropping it must be
    caught rather than silently break key binding validation.

    When `_h is None` (headless / not built) there is nothing to validate, so
    this returns []. That is a legitimately different condition from a stale
    build and must never raise here.

    Invoked only from the real-host boot path; never at import time.
    """
    if _h is None:
        return []

    missing_required = sorted(n for n in _REQUIRED_BINDINGS if not hasattr(_h, n))
    if not hasattr(_h, "keys"):
        missing_required = sorted(missing_required + ["keys"])
    missing_optional = sorted(n for n in _OPTIONAL_BINDINGS if not hasattr(_h, n))

    if missing_required:
        _logger.error(
            "_dauntless_host is missing required binding(s) — stale/incomplete "
            "native module; rebuild with `cmake --build build -j`: %s",
            ", ".join(missing_required),
        )
    if missing_optional:
        # Lazy import avoids any import-order coupling; dev_mode imports
        # _dauntless_host, not host_io, so there is no cycle either way.
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


def verify_keys() -> None:
    """Validate the host `keys` submodule against engine.input_map's table.

    GLFW codes are stable, but this guards against the host submodule ever
    diverging (e.g. an editing slip in host_bindings.cc). Non-fatal: mismatches
    are logged, never raised. No-op when headless or when the submodule is
    absent (validate_bindings reports the latter as a missing required entry).
    """
    if _h is None or not hasattr(_h, "keys"):
        return
    mismatches = input_map.verify_against_host(_h.keys)
    if mismatches:
        _logger.warning(
            "engine.input_map disagrees with _dauntless_host.keys on %d key(s): %s",
            len(mismatches), mismatches,
        )


# ── Window / input polling ───────────────────────────────────────────────────

def key_state(key: int) -> bool:
    if _h is None:
        return False
    return _h.key_state(key)


def key_pressed(key: int) -> bool:
    if _h is None:
        return False
    return _h.key_pressed(key)


def set_key_capture(on: bool) -> None:
    """Hand the keyboard to a focused CEF text field (True) or give it back
    (False). Only engine.ui.text_capture calls this."""
    if _h is None:
        return
    _h.set_key_capture(bool(on))


def key_capture_active() -> bool:
    """True while a CEF text field holds the keyboard (native clears it on
    page load and renderer crash). False headless."""
    if _h is None:
        return False
    return bool(_h.key_capture_active())


def mouse_button_pressed(button: int) -> bool:
    if _h is None:
        return False
    return _h.mouse_button_pressed(button)


def mouse_button_released(button: int) -> bool:
    if _h is None:
        return False
    return _h.mouse_button_released(button)


def consume_mouse_delta() -> Tuple[float, float]:
    if _h is None:
        return (0.0, 0.0)
    return _h.consume_mouse_delta()


def set_cursor_locked(locked: bool) -> None:
    if _h is None:
        return
    _h.set_cursor_locked(locked)


def framebuffer_size() -> Tuple[int, int]:
    if _h is None:
        return (0, 0)
    return _h.framebuffer_size()


def window_size() -> Tuple[int, int]:
    if _h is None:
        return (0, 0)
    return _h.window_size()


def set_cursor_shape(shape: str) -> None:
    """OS pointer shape: "arrow" or "crosshair" (Manual Aim). Soft-guarded:
    a stale .so leaves the arrow in place rather than raising mid-frame."""
    fn = getattr(_h, "set_cursor_shape", None)
    if fn is not None:
        fn(str(shape))


def cursor_pos() -> Optional[Tuple[float, float]]:
    """Cursor in FRAMEBUFFER (physical) pixels -- renderer/window.cc:173-182.
    None when headless (no window to have a cursor in)."""
    if _h is None:
        return None
    return _h.cursor_pos()


def drain_text_events() -> List[Tuple[int, int, int, int, int]]:
    """Typed characters and key events since the last call, oldest first, as
    (kind, code, scancode, action, mods); kind 0 = char (code = codepoint),
    1 = key (code = GLFW key, every key not just editing keys -- native's
    TextEventTranslator needs every press/release to pair a key with its
    char and to know when to emit a KEYUP), 2 = edit command (code =
    renderer::EditCommand). Empty when headless."""
    if _h is None:
        return []
    return list(_h.drain_text_events())


def cef_send_text_events(events: List[Tuple[int, int, int, int, int]]) -> None:
    """Forward one drain_text_events() batch to the CEF overlay, in order.
    No-op headless or with no browser alive.

    Native pairs kind 0/1 events into real KEYDOWN+CHAR / KEYUP through the
    process's single TextEventTranslator (see cef_lifecycle.cc /
    text_input.{h,cc}) and routes kind 2 straight to the focused frame's
    edit command. This replaced a per-event binding (one SendKeyEvent call
    per queued event, character always 0 on an editing key) that CEF's
    macOS key translator misread as flags-changed, not a real key event."""
    if _h is None:
        return
    _h.cef_send_text_events(events)


def cef_reset_text_translator() -> None:
    """Forget every key the native TextEventTranslator currently believes
    is held. Call at a capture boundary (gained or released) so a key still
    down across it cannot emit an orphaned KEYUP into a page that never
    saw its KEYDOWN. No-op headless."""
    if _h is None:
        return
    _h.cef_reset_text_translator()


# ── Per-frame VFX descriptor lists ───────────────────────────────────────────

def set_torpedoes(torpedoes: list) -> None:
    if _h is None:
        return
    _h.set_torpedoes(torpedoes)


def set_shockwaves(shockwaves: list) -> None:
    if _h is None:
        return
    _h.set_shockwaves(shockwaves)


def set_dynamic_lights(lights: list) -> None:
    if _h is None:
        return
    _h.set_dynamic_lights(lights)


def set_hit_vfx(vfx: list) -> None:
    if _h is None:
        return
    _h.set_hit_vfx(vfx)


def set_particle_emitters(emitters: list) -> None:
    if _h is None:
        return
    _h.set_particle_emitters(emitters)


def set_phaser_beams(beams: list) -> None:
    if _h is None:
        return
    _h.set_phaser_beams(beams)


def set_tractor_beams(beams: list) -> None:
    if _h is None:
        return
    _h.set_tractor_beams(beams)


# ── Hit / damage feedback ────────────────────────────────────────────────────
#
# The floating render origin: the native mesh queries (shield_hit,
# world_to_body, damage_decal_add, hull_damage_add, ray_trace_mesh) take
# points RELATIVE TO THE INSTANCE'S TRANSLATION and invert only
# rotation*scale, so a ship 1e6 GU from the system origin is queried with
# the precision of one at the origin. Engine code keeps speaking world points;
# these wrappers form the relative point here, in Python doubles, from
# `instance_translation(iid)`, and add it back to ray_trace_mesh's hit.
# Directions and normals are translation-free and pass through untouched.
#
# `instance_translation` is in VIEW coordinates (the viewed set's -- what
# host_loop pushes), so these wrappers speak view coordinates. A caller holding
# a point in a TARGET's own set coordinates moves it into view coordinates
# first and a returned point back out again (frames.view_offset +
# frames.shifted) -- the target's own coordinates are what BC's surface and
# the damage/decal consumers receive (Plan 2's rule).

def _relative_to(t, point):
    return (point[0] - t[0], point[1] - t[1], point[2] - t[2])


def _instance_relative(instance_id, point, host=None):
    """`point` minus the instance's double translation, or None when the
    instance is stale (every point query drops a stale id). `host` lets the
    two callers that hold the raw native module (engine.renderer,
    engine.shields' F10 key) share this one subtraction."""
    t = (host if host is not None else _h).instance_translation(instance_id)
    if t is None:
        return None
    return _relative_to(t, point)


def shield_hit(
    instance_id: int,
    point: Tuple[float, float, float],
    rgba: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
    intensity: float = 1.0,
    radius: float = 0.0,
) -> None:
    """Flash the ship's shield bubble at a world point.

    `radius` is the weapon's DamageRadiusFactor in GU (photon 0.13, phaser
    0.15); the renderer turns it into the ripple's world-space reach. 0 —
    the default, and what collisions and splash damage pass — clamps up to
    the reach floor rather than producing no splash.
    """
    if _h is None:
        return
    rel = _instance_relative(instance_id, point)
    if rel is None:
        return
    _h.shield_hit(instance_id, rel, rgba, intensity, radius)


def world_to_body(
    instance_id: int,
    world_point: Tuple[float, float, float],
    world_normal: Tuple[float, float, float],
) -> Optional[Tuple[Tuple[float, float, float], Tuple[float, float, float]]]:
    if _h is None:
        return None
    rel = _instance_relative(instance_id, world_point)
    if rel is None:
        return None
    return _h.world_to_body(instance_id, rel, world_normal)


def damage_decal_add(
    instance_id: int,
    world_point: Tuple[float, float, float],
    world_normal: Tuple[float, float, float],
    radius: float,
    intensity: float,
    weapon_class: int,
    time: float,
    world_tangent: Optional[Tuple[float, float, float]] = None,
    dent: float = 0.0,
) -> None:
    """`world_tangent` is the slip direction for a Scuff decal (world space);
    None means no preferred direction (the ring derives a perpendicular).
    `dent` (Scuff only) is the impact weight: 1 = crumpled facets + dish
    (an impact), 0 = scratches (a grind)."""
    if _h is None:
        return
    rel = _instance_relative(instance_id, world_point)
    if rel is None:
        return
    _h.damage_decal_add(instance_id, rel, world_normal, radius,
                        intensity, weapon_class, time,
                        world_tangent if world_tangent is not None
                        else (0.0, 0.0, 0.0),
                        float(dent))


def hull_damage_add(
    instance_id: int,
    world_point: Tuple[float, float, float],
    world_normal: Tuple[float, float, float],
    radius: float,
    wear: float,
    kind: int,
    rest_frame: bool = False,
) -> None:
    """Add a record to the instance's HullDamageStore. `kind` 1 = Surface,
    3 = Internal (others ignored natively). On a posed (articulated) ship the
    binding attributes the point to the part it lies on, by geometry, and
    stores it in that part's REST frame, so the damage moves with the part;
    a rigged ship at the identity pose (no overrides) is attributed in rest
    space. `rest_frame=True`: the point is already rest-frame (authored
    DamageTool volumes): attributed in REST space to the nearest rest
    triangle's node and never converted. No-op without a host/instance."""
    if _h is None:
        return
    rel = _instance_relative(instance_id, world_point)
    if rel is None:
        return
    _h.hull_damage_add(instance_id, rel, world_normal, float(radius),
                       float(wear), int(kind), bool(rest_frame))


def hull_damage_add_body(
    instance_id: int,
    body_point: Tuple[float, float, float],
    body_normal: Tuple[float, float, float],
    radius: float,
    wear: float,
    kind: int,
    rest_frame: bool = False,
) -> None:
    """hull_damage_add for a point/normal ALREADY in the (posed) body frame
    (model units, as `world_to_body` returns them). `radius` is still game
    units; the binding converts it with the same scale as hull_damage_add.
    Attribution and `rest_frame` as hull_damage_add. No translation is
    involved, so there is no instance-relative step."""
    if _h is None:
        return
    _h.hull_damage_add_body(instance_id, tuple(body_point), tuple(body_normal),
                            float(radius), float(wear), int(kind),
                            bool(rest_frame))


def model_nodes(instance_id: int) -> List[dict]:
    """Every named node of this instance's model with geometry somewhere in
    its subtree, for the SPV's part list: [{name, parent, candidate,
    bounds_min, bounds_max}, ...], bounds in SHIP units. `candidate` marks
    the nodes a human would call a part. [] when headless or on a stale id."""
    if _h is None:
        return []
    return _h.model_nodes(instance_id)


def model_nearest_part(model, point) -> str:
    """The part whose rest-pose triangles lie nearest `point` (SHIP units,
    rest pose) on loaded model `model` (a model handle, see
    `instance_model`), or "" when headless, unloaded or partless. Use
    `part_severance.part_for_mount`, which caches and falls back, rather
    than calling this directly."""
    if _h is None:
        return ""
    return _h.model_nearest_part(model, tuple(float(v) for v in point))


def set_instance_decals(instance_id, decals) -> None:
    """The SPV's live decal preview: replace this instance's baked hull
    decals for drawing with `decals` (load_model-shaped entries, body frame,
    at most 4; [] draws none), or None to restore the baked list. No-op when
    headless."""
    if _h is None:
        return
    _h.set_instance_decals(instance_id, decals)


def hull_split_parts(instance_id: int) -> list:
    """Break off every piece the plating wear has cut from the main body of
    `instance_id` (a ship, never a rock or an articulated hull): the structure
    parts that leave together are hidden on the parent and a new renderer
    instance (a chunk) draws only them. Returns one dict per newly severed
    piece (body-frame GAME UNITS): parts (list of part indices), instance_id,
    voxels, total_voxels (the whole hull's), centroid, bounds_min,
    bounds_max, radius_gu. A part is reported once. Empty when headless, not
    ready, or nothing severed."""
    if _h is None:
        return []
    return list(_h.hull_split_parts(instance_id))


def structure_part_at(instance_id: int, body_point_gu) -> int:
    """The structure part whose voxel holds a BODY-frame point (game units)
    on `instance_id`, or -1 (outside the hull's voxels, parts not detected
    yet, stale id, headless)."""
    if _h is None:
        return -1
    return int(_h.structure_part_at(instance_id, tuple(float(c) for c in body_point_gu)))


def breach_burst(instance_id: int, body_point_gu, radius_gu: float) -> None:
    """Transient breach VFX (debris, venting, rim) at a BODY-frame point --
    for a sub-floor severed component that becomes no chunk. No-op when
    headless."""
    if _h is None:
        return
    _h.breach_burst(instance_id, tuple(body_point_gu), float(radius_gu))


def ray_trace_mesh(
    instance_id: int,
    origin: Tuple[float, float, float],
    direction: Tuple[float, float, float],
    max_dist: float,
    rest_pose: bool = False,
) -> Optional[Tuple[Tuple[float, float, float], Tuple[float, float, float], float]]:
    """World (view-coordinate) ray in, world hit out; the binding in
    between is instance-relative. `rest_pose=True` traces the model's REST
    geometry (node overrides ignored) -- for authored, rest-frame content.

    A stale id still reaches the binding, which raises -- deliberately NOT
    the silent drop the point queries make. Those are fire-and-forget
    effects with nothing to report; a trace has a result, and every caller
    (combat, manual aim, the starbase gate, visible damage) already catches
    the raise and degrades to its own fallback, so turning it into None here
    would only hide a stale id behind an ordinary miss."""
    if _h is None:
        return None
    # The flag rides only when set, so the posed call keeps its shape.
    kw = {"rest_pose": True} if rest_pose else {}
    t = _h.instance_translation(instance_id)
    if t is None:
        return _h.ray_trace_mesh(instance_id, origin, direction, max_dist, **kw)
    rel = _relative_to(t, origin)
    hit = _h.ray_trace_mesh(instance_id, rel, direction, max_dist, **kw)
    if hit is None:
        return None
    (px, py, pz), normal, dist = hit
    return (px + t[0], py + t[1], pz + t[2]), normal, dist


def ray_trace_mesh_pick(instance_id, origin, direction, max_dist,
                        exclude_meshes=()):
    """Bridge editor pick: ray_trace_mesh plus (mesh_index, triangle).

    World ray in, world hit out, like ray_trace_mesh. Triangles of
    `exclude_meshes` are never hit. Unlike ray_trace_mesh this never raises:
    the editor calls it every frame for the hover tint, so a stale id or a
    stale binary is just "no hit"."""
    fn = getattr(_h, "ray_trace_mesh_pick", None) if _h is not None else None
    if fn is None:
        return None
    t = _h.instance_translation(instance_id)
    rel = origin if t is None else _relative_to(t, origin)
    hit = fn(instance_id, rel, direction, max_dist, list(exclude_meshes))
    if hit is None:
        return None
    (px, py, pz), normal, dist, mesh, tri = hit
    if t is not None:
        px, py, pz = px + t[0], py + t[1], pz + t[2]
    return (px, py, pz), normal, dist, mesh, tri


def _lossy_str(v) -> str:
    """A NIF name as str: the binding hands names over as bytes (a NIF holds
    whatever bytes its exporter wrote), decoded here with errors="replace" so
    a non-UTF-8 name can never raise into the host loop."""
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).decode("utf-8", errors="replace")
    return str(v)


_NO_MAPS = {"roughness": False, "metalness": False, "normal": False, "emissive": False}


def model_identity(instance_id):
    """{source, content_hash, meshes:[{mesh, block, name, node_chain,
    textures, material, maps}]} for an instance's model; None headless or for
    a stale id. `textures` is the Base-stage texture basename as BUILT (parent
    inheritance resolved), or []. Names are str (lossily decoded). `maps` is
    {roughness, metalness, normal, emissive} bool (spec 2026-10-09-bridge-pbr;
    emissive: spec 2026-10-08-bridge-emitters §11.2); all-False
    when absent (a binary built before this field existed)."""
    fn = getattr(_h, "model_identity", None) if _h is not None else None
    info = None if fn is None else fn(instance_id)
    if info is None:
        return None
    for m in info["meshes"]:
        m["name"] = _lossy_str(m["name"])
        m["node_chain"] = [_lossy_str(n) for n in m["node_chain"]]
        m["textures"] = [_lossy_str(t) for t in m.get("textures", ())]
        if "maps" not in m:
            m["maps"] = dict(_NO_MAPS)
    return info


def set_bridge_highlight(instance_id, selected, hover) -> None:
    """Developer-only selection tint on the bridge: `selected` / `hover` are
    mesh indices into the instance's model (-1 = none). No-op headless."""
    fn = getattr(_h, "set_bridge_highlight", None) if _h is not None else None
    if fn is not None:
        fn(instance_id, int(selected), int(hover))


def set_bridge_material_overrides(instance_id, overrides) -> None:
    """Bridge PBR per-shape material overrides (production data, applied
    without --developer): `overrides` is [(mesh, roughness, metalness)], a
    channel < 0 meaning "no override". None or a stale id clears. No-op
    headless."""
    fn = getattr(_h, "set_bridge_material_overrides", None) if _h is not None else None
    if fn is not None:
        fn(instance_id, [(int(m), float(r), float(mt)) for m, r, mt in overrides])


def set_bridge_pbr_enabled(on) -> None:
    """Developer-only A/B switch for bridge PBR (default on). No-op headless
    and without --developer."""
    fn = getattr(_h, "set_bridge_pbr_enabled", None) if _h is not None else None
    if fn is not None:
        fn(bool(on))


def set_bridge_probe_origin(origin) -> None:
    """Bridge reflection probe capture point (x, y, z), bridge world space --
    the captain's-chair eye. Production (not developer-gated); takes effect at
    the next capture. No-op headless."""
    fn = getattr(_h, "set_bridge_probe_origin", None) if _h is not None else None
    if fn is not None:
        x, y, z = origin
        fn((float(x), float(y), float(z)))


def set_bridge_probe_scales(scales) -> None:
    """Ambient multipliers the five state reflection probes (green, yellow,
    red, offline, special) are captured with. Takes effect at the next
    capture. No-op headless."""
    fn = getattr(_h, "set_bridge_probe_scales", None) if _h is not None else None
    if fn is not None:
        fn([float(v) for v in scales])


def set_bridge_probe_layers(states, identities) -> None:
    """The state each animation layer's probe belongs to (spec 2026-10-17
    §4.4), layer k = probe 5+k, and each layer's identity
    (probe_layers.layer_identity, same length): a changed identity at an
    index keeps that layer out of the reflection until its own capture
    lands. No-op headless."""
    fn = getattr(_h, "set_bridge_probe_layers", None) if _h is not None else None
    if fn is not None:
        fn([int(s) for s in states], [int(i) for i in identities])


def bridge_probe_signatures():
    """Every probe's input signature (test/diagnostic); None headless."""
    fn = getattr(_h, "bridge_probe_signatures", None) if _h is not None else None
    return fn() if fn is not None else None


def bridge_quality() -> int:
    """The bridge rendering quality level (0 Low, 1 Medium, 2 High); 1
    (Medium) headless."""
    fn = getattr(_h, "bridge_quality", None) if _h is not None else None
    return int(fn()) if fn is not None else 1


def set_bridge_probe_state(state, dt) -> None:
    """The shown bridge state (0-4) and the paused-aware bridge dt; the
    renderer cross-fades the base reflection probes (spec 2026-10-17 §4.2).
    No-op headless."""
    fn = getattr(_h, "set_bridge_probe_state", None) if _h is not None else None
    if fn is not None:
        fn(int(state), float(dt))


def set_bridge_layer_values(values) -> None:
    """Live value per reflection layer (w^2.2, clamped to [0, 1] natively).
    No-op headless."""
    fn = getattr(_h, "set_bridge_layer_values", None) if _h is not None else None
    if fn is not None:
        fn([float(v) for v in values])


def set_bridge_alert_level(level) -> None:
    """Player alert level (0 green, 1 yellow, 2 red) choosing the bridge's
    emissive sibling-map variants; None -> green. Pushed every frame. No-op
    headless."""
    fn = getattr(_h, "set_bridge_alert_level", None) if _h is not None else None
    if fn is not None:
        fn(int(level) if level is not None else 0)


def request_bridge_probe_capture() -> None:
    """Recapture every bridge reflection probe (each state's base and every
    layer), time-sliced over the following main-bridge frames, the old
    content showing until each lands -- a bridge load only, never per frame.
    Edits need no request: the renderer queues exactly the probes whose
    inputs (lights, overrides, scales, glow captures, layers) changed, by
    signature. No-op headless."""
    fn = getattr(_h, "request_bridge_probe_capture", None) if _h is not None else None
    if fn is not None:
        fn()


def _v3(v):
    x, y, z = v
    return (float(x), float(y), float(z))


def _capture_row(caps, layers, rgbs):
    """One light's (caps5, layers5, layer_rgbs5) in binding form."""
    return ([_v3(c) for c in caps], [int(i) for i in layers], [_v3(c) for c in rgbs])


def set_bridge_spots(spots) -> int:
    """Bridge spot lights (production, not developer-gated): `spots` is
    [(pos3, dir3, inner_deg, outer_deg, range, (r, g, b), intensity
    [, caps5, layers5, layer_rgbs5])], the angles HALF-angles from the axis.
    With capture data (spec 2026-10-17 §4.1, every spot or none) the probes
    see those -- five LINEAR state colours, the animation layer per state
    (-1 none) and its at-peak colour -- and the live colour
    (set_bridge_spot_colours) never recaptures. Returns how many were
    DROPPED (invalid + over the cap). 0 headless."""
    fn = getattr(_h, "set_bridge_spots", None) if _h is not None else None
    if fn is None:
        return 0
    rows, caps = [], []
    for s in spots:
        p, d, i, o, r, c, k = s[:7]
        rows.append((_v3(p), _v3(d), float(i), float(o), float(r), _v3(c), float(k)))
        if len(s) >= 10:
            caps.append(_capture_row(s[7], s[8], s[9]))
    if caps and len(caps) == len(rows):
        return int(fn(rows, caps))
    return int(fn(rows))


def set_bridge_spot_colours(colours) -> None:
    """Live LINEAR radiance per bridge spot, in set_bridge_spots order (spec
    §11.4); never recaptures the probes. No-op headless."""
    fn = getattr(_h, "set_bridge_spot_colours", None) if _h is not None else None
    if fn is not None:
        fn([(float(r), float(g), float(b)) for r, g, b in colours])


def set_bridge_area_lights(areas) -> int:
    """Bridge area lights -- strips and panels (spec 2026-10-08-bridge-emitters
    §16.3; production, not developer-gated): `areas` is [(centre3, half_u3,
    half_v3, range, (r, g, b), intensity[, caps5, layers5, layer_rgbs5
    [, joins]])], each emitting toward cross(half_u, half_v). Captures as
    set_bridge_spots (every light or none). Returns how many were DROPPED
    (invalid + over the cap). 0 headless."""
    fn = getattr(_h, "set_bridge_area_lights", None) if _h is not None else None
    if fn is None:
        return 0
    rows, caps, joins = [], [], []
    for a in areas:
        c, hu, hv, r, rgb, k = a[:6]
        rows.append((_v3(c), _v3(hu), _v3(hv), float(r), _v3(rgb), float(k)))
        if len(a) >= 9:
            caps.append(_capture_row(a[6], a[7], a[8]))
        joins.append(int(a[9]) if len(a) >= 10 else 0)   # spec §16.8: join bits
    kw = {"joins": joins} if any(joins) else {}
    if caps and len(caps) == len(rows):
        return int(fn(rows, caps, **kw))
    return int(fn(rows, **kw))


def set_bridge_area_colours(colours) -> None:
    """Live LINEAR radiance per bridge area light, in set_bridge_area_lights
    order; never recaptures the probes. No-op headless."""
    fn = getattr(_h, "set_bridge_area_colours", None) if _h is not None else None
    if fn is not None:
        fn([(float(r), float(g), float(b)) for r, g, b in colours])


def bridge_mesh_geometry(instance_id, mesh):
    """One bridge mesh's rest-pose triangles in WORLD space (spec §16.2):
    (vertices, normal_sum, area), three vertices per triangle, the normal sum
    area-weighted and wound as drawn. None headless, for a stale id or an
    unknown mesh; never raises (the runtime asks at every bridge load)."""
    fn = getattr(_h, "bridge_mesh_geometry", None) if _h is not None else None
    if fn is None:
        return None
    try:
        got = fn(instance_id, int(mesh))
        if got is None:
            return None
        verts, n, area = got
        t = _h.instance_translation(instance_id)
    except Exception:  # noqa: BLE001 - a stale id / binary is "no geometry"
        return None
    if t is not None:
        verts = [(x + t[0], y + t[1], z + t[2]) for x, y, z in verts]
    return ([(float(x), float(y), float(z)) for x, y, z in verts],
            (float(n[0]), float(n[1]), float(n[2])), float(area))


def set_bridge_glow(instance_id, glow) -> None:
    """Per-mesh emitter glow for the bridge (spec §11.2): [(mesh, src_code,
    (r, g, b), level)]; None clears. No-op headless."""
    fn = getattr(_h, "set_bridge_glow", None) if _h is not None else None
    if fn is not None:
        fn(instance_id, [(int(m), int(s), (float(c[0]), float(c[1]), float(c[2])), float(lv))
                         for m, s, c, lv in glow])


def set_bridge_glow_captures(instance_id, rows) -> None:
    """Per-mesh glow contribution to the probes (spec 2026-10-17 §4.5):
    [(mesh, src, caps5, layers5, layer_rgbs5)], display space; None clears.
    No-op headless."""
    fn = getattr(_h, "set_bridge_glow_captures", None) if _h is not None else None
    if fn is not None:
        fn(instance_id, [(int(m), int(s), *_capture_row(c, l, r)) for m, s, c, l, r in rows])


# ── Star map (Helm → Set Course) ─────────────────────────────────────────────
# Soft-guarded: a stale native module leaves the map blank (warned at boot
# under --developer) instead of raising AttributeError inside the helm menu.

def starmap_set_enabled(enabled: bool) -> None:
    """Show/hide the star map pass. Off by default."""
    fn = getattr(_h, "starmap_set_enabled", None)
    if fn is not None:
        fn(bool(enabled))


def starmap_set_viewport(x: int, y: int, w: int, h: int) -> None:
    """Set the map's sub-rect in FRAMEBUFFER pixels, GL origin (bottom-left)."""
    fn = getattr(_h, "starmap_set_viewport", None)
    if fn is not None:
        fn(int(x), int(y), int(w), int(h))


def starmap_set_camera(
    eye: Tuple[float, float, float],
    target: Tuple[float, float, float],
    up: Tuple[float, float, float],
    fov_y_rad: float,
    near: float,
    far: float,
) -> None:
    """Set the map's own orbit camera — independent of the gameplay camera.

    No aspect argument: the pass derives it from the map's sub-rect, the same
    rect engine.ui.star_map.project_points uses, so drawn and clickable star
    positions agree by construction.
    """
    fn = getattr(_h, "starmap_set_camera", None)
    if fn is not None:
        fn(eye, target, up, float(fov_y_rad), float(near), float(far))


def starmap_set_scene(discs, lines, points, brackets, starclouds) -> None:
    """Replace the star map scene. Tuple shapes:

        discs:      ((x, y, z), (r, g, b), radius_world, fill_alpha, border_alpha)
        lines:      ((ax, ay, az), (bx, by, bz), (r, g, b))
        points:     ((x, y, z), (r, g, b), size_px, selected)
        brackets:   ((x, y, z), mark, (r, g, b), size_px)
        starclouds: ((x, y, z), (r, g, b), size_px, opacity)

    Discs are nebula REGIONS — a faint flat fill inside a crisp boundary, not
    soft clouds — and are world-scaled. Star clouds are screen-scaled glyphs:
    at their model `size` they became volumes that swallowed whole regions.

    The five lists are drawn in THAT order, depth test off. Ordering is
    decided in engine.ui.star_map.build_scene; the pass never re-sorts.

    `mark` (1 here, 2 course, 3 mission) and `selected` ride along as
    semantics only — the pass derives no colour or size from either.
    engine.ui.star_map owns those enums and the palette, so presentation
    crosses this boundary as values (see its MARK_*_COLOR / *_SIZE_PX).
    """
    fn = getattr(_h, "starmap_set_scene", None)
    if fn is not None:
        fn(discs, lines, points, brackets, starclouds)


# ── Frame profiler ───────────────────────────────────────────────────────────
# Per-pass render timings from renderer::FrameTimer. Optional bindings: a stale
# .so must leave the profiler reporting "render half unavailable" rather than
# crashing the dev keybinding that toggles it.

def profiler_set_enabled(enabled: bool) -> None:
    """Enable/disable per-pass render timing. Off by default.

    Toggling either way clears the accumulated averages on the C++ side, so a
    session never blends samples taken before and after a scene change.
    """
    fn = getattr(_h, "profiler_set_enabled", None)
    if fn is not None:
        fn(bool(enabled))


def profiler_enabled() -> bool:
    """True when the render half is recording. False when the binding is absent."""
    fn = getattr(_h, "profiler_enabled", None)
    return bool(fn()) if fn is not None else False


def profiler_set_gpu_enabled(enabled: bool) -> None:
    """Opt in to GPU timer queries. Off by default.

    On Apple's GL the queries make the CPU wait for the GPU every frame, which
    adds about the GPU frame time, so a GPU-timed capture is not a frame-time
    measurement (docs/engine/perf-register.md, M-6). Turn it on only to split
    GPU cost between passes.
    """
    fn = getattr(_h, "profiler_set_gpu_enabled", None)
    if fn is not None:
        fn(bool(enabled))


def profiler_set_gpu_focus(names) -> None:
    """Nested scopes to GPU-time too (perf-register.md M-1). Apple's GL times
    only the top-level passes; each focus scope gets its own span by splitting
    its top-level pass's query, whose total is unchanged. Empty = none."""
    fn = getattr(_h, "profiler_set_gpu_focus", None)
    if fn is not None:
        fn([str(n) for n in names])


def profiler_gpu_enabled() -> bool:
    """True when GPU timing was requested. False when the binding is absent."""
    fn = getattr(_h, "profiler_gpu_enabled", None)
    return bool(fn()) if fn is not None else False


def profiler_scopes() -> List[dict]:
    """Per-pass render timings: [{name, cpu_ms, gpu_ms, gpu_measured, calls,
    depth}, ...]. `gpu_measured` False means no GPU query covered the scope
    (nested under GL_TIME_ELAPSED): its gpu_ms is NOT MEASURED, not free.

    In pass order. `cpu_ms`/`gpu_ms` are EMA-smoothed; `calls` is the raw count
    from the last resolved frame, so a pass that ran twice in one frame (the
    exterior view AND the bridge viewscreen RTT both call render_space) reads
    as calls=2 rather than being averaged into something that matches neither.
    Empty when the binding is absent or nothing has resolved yet.
    """
    fn = getattr(_h, "profiler_scopes", None)
    return list(fn()) if fn is not None else []


def profiler_last_frame_raw() -> dict:
    """The last frame's RAW render CPU times, not smoothed and not lagged:
    {cpu_ms, scopes: [{name, cpu_ms, calls, depth}, ...]}. No GPU -- that
    resolves frames later. For the spike log; empty when the binding is absent."""
    fn = getattr(_h, "profiler_last_frame_raw", None)
    if fn is None:
        return {"cpu_ms": 0.0, "scopes": []}
    return dict(fn())


def profiler_frame() -> dict:
    """Whole-frame render totals: {cpu_ms, gpu_ms, frames, enabled, ...}.

    Also `gpu_timer` ("timestamp" | "elapsed" | "none"), chosen from the
    driver's declared counter bits (`timestamp_bits`, `elapsed_bits`), and
    `timestamp_queries` issued since the last enable. Under GL_TIMESTAMP,
    `gpu_ms` is first-timestamp-to-last, NOT a sum of the nested scopes; under
    GL_TIME_ELAPSED (Apple's GL) it is the sum of the sequential top-level
    passes, the only ones timed. Returns zeros with enabled=False when the
    binding is absent.

    A gpu_ms of exactly 0.0 across many resolved frames does NOT mean a free
    GPU: a driver that declares a counter yet returns zeros produces that.
    frame_profiler's report calls it out as GPU TIMING UNAVAILABLE for the same
    reason this module reports an absent binding rather than inventing zeros.
    """
    fn = getattr(_h, "profiler_frame", None)
    if fn is None:
        return {"cpu_ms": 0.0, "gpu_ms": 0.0, "frames": 0, "enabled": False,
                "swap_interval": -1}
    return dict(fn())


def set_swap_interval(interval: int) -> None:
    """1 = vsync, 0 = uncapped. Visible windows default to 1, hidden to 0.

    Turn it off before a profiling capture: a vsync-capped frame measures the
    monitor's refresh rate, not the renderer.
    """
    fn = getattr(_h, "set_swap_interval", None)
    if fn is not None:
        fn(int(interval))


def swap_interval() -> int:
    """The interval currently set; -1 when unknown (no window, or no binding)."""
    fn = getattr(_h, "swap_interval", None)
    return int(fn()) if fn is not None else -1


# ── Transform store ───────────────────────────────────────────────────────────
# The native, process-wide dauntless::transform_store() — authoritative
# position/rotation for every ObjectClass. Required, not optional: a stale
# build missing any of these would leave object placement silently broken
# rather than degrading a single feature.
#
# These ten wrappers exist ONLY so the binding manifest (_REQUIRED_BINDINGS,
# validated by validate_bindings() at boot) can see the transform surface and
# fail loudly on a stale/incomplete build, instead of an AttributeError mid-
# frame. engine.appc.transform_store.NativeTransformStore deliberately
# bypasses this façade and calls _dauntless_host directly — it sits on the
# per-object, per-frame hot path, and routing it through here would add a
# Python function-call frame on exactly the path this design exists to keep
# out of Python.

def transform_alloc() -> Optional[Tuple[int, int]]:
    if _h is None:
        return None
    return _h.transform_alloc()


def transform_free(index: int, generation: int) -> None:
    if _h is None:
        return
    _h.transform_free(index, generation)


def transform_get_position(
    index: int, generation: int,
) -> Optional[Tuple[float, float, float]]:
    if _h is None:
        return None
    return _h.transform_get_position(index, generation)


def transform_set_position(
    index: int, generation: int, x: float, y: float, z: float,
) -> None:
    if _h is None:
        return
    _h.transform_set_position(index, generation, x, y, z)


def transform_get_rotation(index: int, generation: int) -> Optional[tuple]:
    """Row-major nine doubles."""
    if _h is None:
        return None
    return _h.transform_get_rotation(index, generation)


def transform_set_rotation(index: int, generation: int, rot9) -> None:
    if _h is None:
        return
    _h.transform_set_rotation(index, generation, rot9)


def transform_get_rotation_col(
    index: int, generation: int, col: int,
) -> Optional[Tuple[float, float, float]]:
    if _h is None:
        return None
    return _h.transform_get_rotation_col(index, generation, col)


def transform_get_positions(handles) -> Optional[List[Tuple[float, float, float]]]:
    if _h is None:
        return None
    return _h.transform_get_positions(list(handles))


def transform_live_count() -> int:
    if _h is None:
        return 0
    return _h.transform_live_count()


def transform_capacity() -> int:
    if _h is None:
        return 0
    return _h.transform_capacity()


def set_instance_transform_slot(iid, index: int, generation: int,
                                scale: float) -> bool:
    """Bind render instance `iid` to transform-store slot (index, generation)
    with a uniform `scale`; `index < 0` unbinds.

    The renderer then composes that instance's world matrix from the store in
    C++ every frame, so the object's position/rotation stops being marshalled
    into Python only to be handed straight back as sixteen floats.

    Returns True when the binding took effect. It returns False — and the
    caller must fall back to pushing an explicit matrix — in exactly two cases:
    the extension is absent (headless), or `iid` is not a native InstanceId
    (a test double's plain int). Both mean "no native instance to bind", never
    "the binding is missing": a stale build that dropped the binding trips
    validate_bindings() at boot, because it is in _REQUIRED_BINDINGS.
    """
    if _h is None:
        return False
    if not isinstance(iid, _h.InstanceId):
        return False
    _h.set_instance_transform_slot(iid, int(index), int(generation),
                                   float(scale))
    return True


def set_instance_node_transform(iid, node_name: str, m16) -> bool:
    """Set `node_name`'s pose on instance `iid`: a column-major 4x4 (16
    floats) in the node's PARENT space, MODEL units, applied as M * local.
    Identity clears the override. False headless, on a fake iid, or when the
    model has no such node -- "nothing to articulate", never "binding
    missing" (a stale build trips validate_bindings() at boot)."""
    if _h is None:
        return False
    if not isinstance(iid, _h.InstanceId):
        return False
    return bool(_h.set_instance_node_transform(
        iid, str(node_name), [float(v) for v in m16]))


def instance_model(iid):
    """The model handle behind render instance `iid`, or None.

    Appendage severance draws a severed part as a second instance of the SAME
    model, so it needs the parent's handle to create that copy.
    """
    if _h is None:
        return None
    if not isinstance(iid, _h.InstanceId):
        return None
    handle = _h.instance_model(iid)
    return handle or None


def set_instance_node_hidden(iid, node_name: str, hidden: bool) -> bool:
    """Collapse (hidden=True) or restore a named node's subtree on `iid`.

    Used by appendage severance at both ends: the ship hides the part it just
    lost, and the debris chunk (a second instance of the SAME model) hides
    every part except that one.

    False on headless, on a test double's plain-int iid, or when the model has
    no node by that name.
    """
    if _h is None:
        return False
    if not isinstance(iid, _h.InstanceId):
        return False
    return bool(_h.set_instance_node_hidden(iid, str(node_name), bool(hidden)))


def clear_instance_node_overrides(iid) -> bool:
    """Return instance `iid` to its static node pose."""
    if _h is None:
        return False
    if not isinstance(iid, _h.InstanceId):
        return False
    return bool(_h.clear_instance_node_overrides(iid))


def request_relaunch(extra_args: List[str]) -> None:
    """Ask host_main to re-execute the game after a clean shutdown, with the
    original arguments plus `extra_args` (Quit and Manage Mods). Last call
    wins. Only the dauntless binary honours the request after it shuts down;
    headless / the pytest .so is a no-op."""
    if _h is None:
        return
    _h.request_relaunch(list(extra_args))
