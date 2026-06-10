# Subsystem glow-dimming generalization — design

**Date:** 2026-06-10
**Status:** Approved (design); ready for implementation plan.
**Supersedes:** `2026-06-10-impulse-offline-glow-mask-design.md` (narrow first
cut; the world-space sphere approach there is replaced by reusing the existing
body-frame glow-region machinery).

## Goal

Generalize the existing warp-nacelle glow-dimming system so that **three**
subsystems drive hull-glow dimming from their live condition, with one unified
behaviour:

- **Impulse Engines** (new)
- **Sensor Array** (new)
- **Warp Engines** (already implemented; keeps its capsule shape-detection)

Unified three-state behaviour for all three:

- **Healthy** (not disabled, not destroyed) → full glow.
- **Disabled** (`IsDisabled()` and not `IsDestroyed()`) → **continuous flicker**.
- **Destroyed** (`IsDestroyed()`) → **off** (a brief blow-out flicker, then dark).

This replaces warp's current behaviour (dim to a 0.08 residual with a 0.4 s
flicker on the disable edge, for disabled-or-destroyed alike).

## Background — what exists today

The renderer already has a per-instance, body-frame, capsule glow-dimming
system, built for warp nacelles:

- **C++ region geometry** `native/src/renderer/nacelle_region.{cc,h}`:
  `compute_nacelle_region(model, center, axis, radius)` walks the model's
  vertices and fits a capsule `[aft, fore]` along `axis` (this is the
  "shape detection" that handles the long Y-axis nacelles — **must be kept**).
- **Per-instance state** `scenegraph::Instance::Nacelle` (center, axis, radius,
  aft, fore, dim_target, disable_time, active), `std::array<Nacelle, 4>`.
- **Shader** `native/src/renderer/shaders/opaque.frag`: uniforms
  `u_nacelle_count`, `u_nacelle_a/b/c[4]`, and `nacelle_glow_mult(p_body, now)`
  which multiplies the glow term — inside the capsule, flicker for the first
  `NACELLE_FLICKER_SECS` (0.4) then settle to `dim_target`. `count == 0` skips
  the loop (production path byte-identical).
- **Host bindings** `compute_nacelle_region`, `set_nacelle_dim`.
- **Python driver** `engine/appc/warp_glow.py` (`WarpGlowController`): registers
  a capsule per warp pod, pushes `(dim_target, disable_time)` each frame.
- **Wiring** `engine/host_loop.py`: `warp_glow_controllers` dict keyed by
  instance id; created on ship spawn, `update(now)` each frame, pruned on death.

### Key geometric realization

The shader's capsule test degenerates **exactly** to a sphere when
`axis == (0,0,0)` and `aft == fore == 0`: then `t = dot(d, axis) = 0`,
`perp = d`, and the test becomes `dot(d, d) > radius²` with the axial bound
`0 <= 0 <= 0` always passing. So impulse/sensor **spheres need no new shader
shape** — only a host entry point that stores a sphere region **without** the
vertex-fit (impulse/sensor glow is a compact spot, not a long tube).

Both new subsystems expose a single hardpoint with position + radius
(Galaxy: Impulse pos `(0,-0.98,-0.45)` r `0.25`; Sensor pos `(0,-0.45,-0.5)`
r `0.28`), in the same body-frame/game-unit basis warp pods already use.

## Architecture

### 1. Rename: `nacelle` → `glow_region` (C++)

The infra now serves engines and sensors, so the "nacelle" name is misleading.
Rename for semantic accuracy (mechanical rename; capsule-fit logic unchanged):

- Files: `nacelle_region.{cc,h}` → `glow_region.{cc,h}`; the C++ test
  `native/tests/renderer/nacelle_region_test.cc` → `glow_region_test.cc`.
- Type `NacelleRegion` → `GlowRegion`; constants `kNacelle*` → `kGlowRegion*`.
- Capsule fit function `compute_nacelle_region` → **`compute_capsule_region`**
  (still fits `[aft, fore]` via vertex walk — for warp).
- New free function **`add_sphere_region(center, radius)`** → returns a
  `GlowRegion` with `axis = (0,0,0)`, `aft = fore = 0`, `radius` as given
  (no vertex walk, no widen).
- `scenegraph::Instance::Nacelle` → `GlowRegion`; `kMaxNacelles` →
  `kMaxGlowRegions`; member `nacelles` → `glow_regions`. **Add field**
  `float flicker = 0.0f;` (1 = disabled/continuous flicker, 0 = solid settle).
- Shader uniforms `u_nacelle_*` → `u_glow_region_*`; `MAX_NACELLES` →
  `MAX_GLOW_REGIONS`; `nacelle_glow_mult` → `glow_region_mult`. Pack `flicker`
  into the currently-unused `u_glow_region_c[i].w` slot (frame.cc line 130
  hardcodes `0.0f` there today).
- Host bindings: `compute_nacelle_region` → `compute_capsule_region`;
  `set_nacelle_dim` → `set_glow_region_dim` (gains a `flicker` arg); new
  `add_sphere_region(instance_id, center, radius)` → region index. Python
  wrappers in `engine/renderer.py` renamed to match.

### 2. Three-state behaviour (shader)

Per-region data (vec4 layout unchanged except the spare `.w`):

- `a = center.xyz, radius`
- `b = axis.xyz, aft`
- `c = fore, dim_target, edge_time, flicker`

`glow_region_mult(p_body, now)`:

```glsl
// inside the region (capsule/sphere test unchanged):
if (edge_time < 0.0) continue;                  // healthy
float age = max(now - edge_time, 0.0);
float region_mult;
if (flicker > 0.5) {
    // Disabled: continuous oscillation between floor and full.
    region_mult = mix(DISABLED_FLOOR, 1.0, 0.5 + 0.5 * stutter(age));
} else {
    // Destroyed: brief blow-out flicker, then settle to dim_target (0 = off).
    float blow = mix(dim_target, 1.0, 0.5 + 0.5 * stutter(age));
    float w    = clamp(age / GLOW_FLICKER_SECS, 0.0, 1.0);
    region_mult = mix(blow, dim_target, w);
}
mult = min(mult, region_mult);                  // overlapping regions: darkest wins
```

- `GLOW_FLICKER_SECS = 0.4` (the renamed `NACELLE_FLICKER_SECS`).
- `DISABLED_FLOOR = 0.0` (flicker troughs reach dark; tuned by eye in-app).
- `stutter(age)` is the existing 15 Hz two-sine helper — reused unchanged.

Healthy regions write `edge_time = -1.0` and are skipped, so an all-healthy
ship is byte-identical to today (and `count == 0` still short-circuits).

### 3. Generalized Python driver

Replace `engine/appc/warp_glow.py` with `engine/appc/subsystem_glow.py`. Pure,
headless-testable helpers plus one per-ship controller.

**State + mapping helpers** (pure):

```python
HEALTHY, DISABLED, DESTROYED = "healthy", "disabled", "destroyed"

def glow_state(sub) -> str:
    if sub is None: return HEALTHY
    if sub.IsDestroyed(): return DESTROYED
    if sub.IsDisabled():  return DISABLED
    return HEALTHY

# (dim_target, flicker) pushed to the shader per state:
#   healthy   -> (1.0, 0.0)   [edge_time -1 => region inert]
#   disabled  -> (0.0, 1.0)   [continuous flicker; dim_target unused by shader]
#   destroyed -> (0.0, 0.0)   [blow-out then off]
def dim_and_flicker(state) -> tuple[float, float]: ...

def glow_edge(prev_state, cur_state, prev_time, now) -> float:
    # -1.0 when healthy; `now` when the (non-healthy) state CHANGES
    # (healthy->disabled, healthy->destroyed, disabled->destroyed);
    # otherwise keep prev_time (same non-healthy state persists).
```

**Region enumeration:**

```python
WARP_AXIS = (0.0, 1.0, 0.0)   # ship-forward (model +Y), column-vector convention

def warp_pods(warp_subsystem) -> list:   # children, else [aggregator], else []
```

**`ShipGlowController(renderer, instance_id, ship)`** registers, at
construction:

- one **capsule** region per warp pod (`r.compute_capsule_region(iid, pos,
  WARP_AXIS, radius)`),
- one **sphere** region for the impulse subsystem
  (`r.add_sphere_region(iid, pos, radius)`),
- one **sphere** region for the sensor subsystem (same call).

Each retained region stores `(subsystem, region_index, prev_state,
edge_time)`. `update(now)` reads each subsystem's `glow_state`, computes
`glow_edge`, and calls `r.set_glow_region_dim(iid, idx, dim_target, edge_time,
flicker)`. Pods/subsystems with no `GetPosition`, or where region registration
returns `< 0`, are skipped. Registration and updates are wrapped so a missing
renderer binding (headless) is a clean no-op (`hasattr` guard at the call
sites, matching the existing `r.*` convention).

### 4. Wiring (`host_loop.py`)

- `warp_glow_controllers` → `ship_glow_controllers` (dict keyed by iid).
- Construct on ship spawn with the **ship** (so it can reach all three
  subsystems): `ShipGlowController(r, iid, ship)` (best-effort; failures never
  block spawn, as today).
- Per-frame `update(now)` and prune-on-death are unchanged except for the rename.

## Edge cases

- Subsystem accessor returns `None`, or hardpoint has no `GetPosition` /
  non-positive radius → that region is simply not registered (no crash).
- A ship with no warp/impulse/sensor mounts → zero regions → `count == 0` →
  no per-fragment cost.
- More than `kMaxGlowRegions` (4) regions on one ship → extra registrations
  return `-1` and are skipped (no ship reaches this: ≤2 warp pods + 1 impulse +
  1 sensor = 4).
- Disabled → destroyed transition re-stamps `edge_time`, so destruction plays
  its own blow-out even if the subsystem was already flickering.
- Repair (destroyed/disabled → healthy) clears `edge_time` to `-1.0` → full
  glow next frame.

## Stock-BC parity

All-healthy ships render byte-identical to today: every region writes
`edge_time = -1.0` (inert) and, with no regions registered, `u_glow_region_count
== 0` short-circuits the loop. The feature is additive and always-on (a
gameplay-state visual, like the persistent damage decals) — not dev-gated.

## Testing

**Python (`tests/unit/test_subsystem_glow.py`)** — supersedes
`test_warp_glow.py`:

- `glow_state`: healthy / disabled (disabled-not-destroyed) / destroyed
  (destroyed dominates even if also disabled) / `None` → healthy.
- `dim_and_flicker`: healthy `(1.0, 0.0)`, disabled `(0.0, 1.0)`, destroyed
  `(0.0, 0.0)`.
- `glow_edge`: healthy → `-1.0`; healthy→disabled stamps `now`; still-disabled
  keeps stamp; disabled→destroyed re-stamps `now`; →healthy clears to `-1.0`.
- `warp_pods`: children, else `[aggregator]`, else `[]`.
- `ShipGlowController` with a fake renderer + fake ship: registers a capsule
  per warp pod (axis `WARP_AXIS`) and a sphere for impulse + sensor; drives the
  full `set_glow_region_dim` call sequence across healthy → disabled →
  destroyed → repaired edges (asserting `dim_target`, `edge_time`, `flicker`).

**C++ (`native/tests/renderer/glow_region_test.cc`)**:

- Existing capsule-fit assertions, renamed (`compute_capsule_region` still fits
  `[aft, fore]` to vertices along the axis).
- New: `add_sphere_region(center, radius)` yields `axis == (0,0,0)`,
  `aft == fore == 0`, `radius` unchanged, `active == true`.

**In-app verification** (`./build/dauntless`): disable then destroy the
player's impulse engine, sensor array, and a warp nacelle (dev combat cheats /
applied damage); confirm each glow region flickers while disabled, blows out and
goes dark when destroyed, and restores on repair; confirm an undamaged ship is
unchanged and the warp nacelle still dims along its full length (capsule, not a
small sphere).

## Out of scope (YAGNI)

- Any subsystem beyond impulse / sensors / warp.
- Per-subsystem flicker tuning UI or config toggles (constants tuned in-shader).
- Serializing glow-region state (runtime VFX only, as today).
- Changing the impulse flight-degradation or sensor-range gameplay (already
  shipped; this is purely visual).
