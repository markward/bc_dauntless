# Instance-attached emitter lights (design)

**Date:** 2026-09-16
**Status:** implemented 2026-09-16 (gate green); awaiting live verification on a 144 Hz display
**Area:** renderer dynamic lights + host-loop emitter producer

## Goal

Subsystem light emitters must move with the hull they are attached to —
same pose, same frame — on any refresh rate, and the per-frame Python cost
of producing them must drop. Torpedo and explosion lights are world-space
and are out of scope.

## Root cause of the jitter

The hull of every AI ship (and the AI/cutscene-driven player) is drawn at
`lerp(prev, cur, _interp_alpha)` from the transform buffer
(`_sync_instance_transforms`, `host_loop.py`). The emitter lights are built
by `_build_emitter_light_render_data` from `ship.GetWorldLocation()` /
`GetWorldRotation()` — the raw `cur` pose, which changes only on a 60 Hz sim
tick. On a 144 Hz display the light steps every ~2.4 frames while the hull
glides, and leads the hull by up to one tick. The result is the visible
jitter between cast light and hull.

Two facts rule out the obvious "read `pose_of` instead" fix:

1. The producer runs inside `_advance_combat`, which is called **before**
   `_pose_of` is constructed and before `_sync_instance_transforms` captures
   `cur` into the buffer. Sampling the buffer there returns last tick's pose.
2. `_advance_combat` runs once per **render frame**, so at 144 Hz the
   producer already does 2.4× the transform work per tick for nothing.

C++ is a pure consumer today: `set_dynamic_lights` (`host_bindings.cc`)
takes already-world-space `DynamicLightDescriptor`s and
`select_instance_dynamic_lights` (`frame.cc`) picks the nearest four per
draw. All positioning is Python.

## Working example in the tree

`ParticleEmitterDescriptor` (`renderer/frame.h`) carries an `instance_id`
plus **body-frame** `emit_pos` / `emit_dir`; `particle_pass.cc` transforms
them by `inst->world` each frame — the same matrix the hull is drawn with, so
particles cannot disagree with the hull by construction. This design applies
the same pattern to dynamic lights.

## Approach chosen

**Body-frame per frame, geometry cached in Python, resolved to world in
C++ once per frame in `frame()`.** Rejected alternatives:

- *Resolve lazily in `select_instance_dynamic_lights`* — re-transforms every
  attached light for every instance (N×M) for no benefit.
- *Resolve at `set_dynamic_lights` binding time* — wrong: store-bound
  instances are recomposed at the top of `frame()`, and interpolated ships
  receive `set_world_transform` **after** `_advance_combat`, so the binding
  would read last frame's matrices. Same ordering trap as the Python-only
  route.
- *Register emitter geometry natively at spawn, push only intensities* —
  lowest per-frame cost but adds a native cache that must be invalidated on
  SPV live edits, despawn and mission swap. Deferred; revisit only if the
  frame profiler (`docs/engine/frame-profiler.md`) says `cb.render_data` is
  still significant after this change.

## Section 1 — renderer

### Descriptor

`DynamicLightDescriptor` (`renderer/frame.h`) gains

```cpp
scenegraph::InstanceId instance_id{};   // {0,0} sentinel => world-space
```

When set, `pos_a`, `pos_b`, `direction` and `up` are **ship body-frame,
unscaled GU** — the frame the SPV authors emitters in and the frame
`subsystem_world_position` uses for pins ("ship world-loc + R·local, no
scale"). When unset the descriptor is world-space exactly as today.

### Resolve pass

New pure function in `renderer/dynamic_lights.{h,cc}`:

```cpp
/// Resolve every attached light in `lights` to world space through its
/// instance's current `world` matrix. Unattached entries are untouched.
/// An attached light whose instance no longer exists is removed.
void resolve_attached_dynamic_lights(const scenegraph::World& world,
                                     std::vector<DynamicLightDescriptor>& lights);
```

Per attached light, with `M = inst->world`:

- `s = length(vec3(M[0]))` — the instance's uniform scale, recovered the
  same way `select_instance_dynamic_lights` and `shield_pass.cc` do (BC
  models are uniform-scale).
- `pos_world = vec3(M[3]) + (mat3(M) · pos) / s` for `pos_a` and `pos_b` —
  scale divided out because emitter offsets are unscaled GU.
- `direction`, `up` (cones only, i.e. `spot_tan_x >= 0`):
  `normalize(mat3(M) · v)`.
- `instance_id` reset to the sentinel on the resolved entry, so nothing
  downstream can tell it was ever attached.
- Missing instance (`world.get(id) == nullptr`, e.g. despawned between
  `set_dynamic_lights` and `frame()`): the entry is erased — the same choice
  `particle_pass.cc` makes with `continue`.

### Where it runs

`frame()` in `host_bindings.cc` calls
`resolve_attached_dynamic_lights(g_world, g_dynamic_lights)` **once**, after
`sync_instance_transforms_from_store()` has recomposed every bound
instance's `world` (every `set_world_transform` push for the frame has
already landed by the time `frame()` is entered), and before
`render_space_geometry` / the SPV hull-mode draw. That placement is the
feature: the light is resolved through the identical matrix the hull is
drawn with that frame. `select_dynamic_lights`, `frame.cc`'s per-instance
selection and `opaque.frag` are untouched.

### Binding

`set_dynamic_lights` parses an optional `instance_id` key
(`d["instance_id"].cast<scenegraph::InstanceId>()`, the same marshal the
particle and hit-vfx bindings use). Absent or `None` ⇒ world-space. Every
existing producer omits the key, so torpedo and explosion dicts are
byte-identical.

## Section 2 — Python producer

### Cache

`_build_ship_emitter_cache` entries become

```
(sub, is_impulse, is_warp, phase, spec, struct)
```

where `struct = light_emitters.emitter_spec_to_struct(spec)` — the static
body-frame geometry, colour, radius and cone tangents. It is built at every
cache construction: spawn, `CreatePlayerShip` reuse, and SPV Save's
`refresh_ship_emitters`. All three already route through this function, so
SPV live refresh of the cached struct is free.

### Per frame

`_build_emitter_light_render_data` no longer reads `GetWorldRotation()` and
no longer calls `_world_from_body` / `_rotate_body` / `emitter_spec_to_struct`.
Per ship it reads `GetWorldLocation()` once for the camera-distance fade
(per-ship early-out kept; a one-tick error on the ~86 GU cull band is
invisible). Per emitter:

```python
inten = light_emitters.resolve_emitter_intensity(...)   # unchanged
if inten is None: continue
d = dict(struct)
d["intensity"] = inten * fade
d["instance_id"] = iid
out.append(d)
```

The call site stays in `_advance_combat`'s `cb.render_data` scope — with
nothing pose-dependent leaving Python there is no ordering constraint left
to protect. `_world_from_body` / `_rotate_body` remain for their other
callers. `_build_dynamic_light_render_data` (torpedoes) and
`_build_explosion_light_render_data` are untouched.

### Manual-flight player

The manually flown player is bound to the transform store, so its
`inst->world` is composed in C++ from the live pose each frame — the same
matrix its hull draws with. Attached lights therefore track it exactly, with
no special case.

## Section 3 — tests

**C++ — `native/tests/renderer/dynamic_lights_test.cc`**
`resolve_attached_dynamic_lights`:
- point light on an instance with rotation R, translation t and scale s ≠ 1
  lands at `t + R·p` (scale divided out);
- strip: `pos_b` resolved the same way;
- cone: `direction` and `up` rotated by R and unit-length;
- unattached entries byte-identical before/after;
- attached entry whose instance is missing is removed;
- resolved entry's `instance_id` is the sentinel.

**C++ — frame-level ordering guard** (`test_cone_light_frame.cc` pattern):
an attached light on an instance whose `world` is pushed via
`set_world_transform` after the light list is set lights the hull at the
pushed pose, proving the resolve runs after the sweep, not at binding time.

**Python — `tests/test_host_loop_emitter_lights.py`,
`tests/unit/test_dynamic_light_render_marshal.py`:**
- producer output carries body-frame positions and `instance_id == iid`;
- producer never calls `GetWorldRotation` (double asserts);
- `emitter_spec_to_struct` is called by the cache builder, not per frame;
- `refresh_ship_emitters` rebuilds the cached struct from the new spec;
- torpedo / explosion dicts carry no `instance_id`;
- existing budget / camera-fade / scope tests keep passing unchanged.

**Gate and live check:** `scripts/check_tests.sh` green; then a live pass on
Mark's 144 Hz display confirming cast light is locked to the hull on AI
ships, the AI-driven player and the manually flown player.

## Out of scope

- Native emitter registration (see rejected alternatives).
- Torpedo / explosion lights.
- Owner-filtering of emitter lights (they still cast on neighbouring hulls;
  accepted in the original emitter design).
