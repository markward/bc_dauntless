# Hardpoint handling — research findings (2026-06-04)

**Status:** investigation complete; clean implementation TODO.
**Spike branch:** `feat/hardpoint-research-spike` (commit `edbf828`) —
*reference only, do not merge*.

## Why this doc exists

A session of in-game calibration plus SDK / NIF / ModelPropertyEditor
inspection turned up several entangled bugs in how we interpret BC
hardpoint data. Most were caused by `TGObject.__getattr__`'s data-bag
catch-all silently swallowing SDK setters we hadn't typed. Rather than
patch them in place, we want to redo the implementation cleanly off a
single, well-understood model.

This doc captures the working model + the findings, so the clean
implementation has a single source of truth.

## TL;DR

1. **The TGObject data-bag is a foot-gun.** Any `SetX` / `GetX` call
   that doesn't hit a typed method on the property class falls through
   to `TGModelProperty.__getattr__`, which stores it in `self._data`
   keyed by `(field_name, args[:-1]) → args[-1]`. The corresponding
   `GetX()` then returns `None` — and most callers test
   `isinstance(v, TGPoint3)` before using it, so the value silently
   vanishes. *This is how `SetPosition`, `SetOrientation`, and
   `SetWidth` on every phaser bank in the game ended up as defaults.*

2. **BC's render scale is fixed at 0.01** (per
   `sdk/Tools/ModelPropertyEditor/modelpropertyeditor.reg`,
   `HKCU\Software\Totally Games\ModelPropertyEditor\Options\ModelScale`).
   It is NOT derived from `ship.GetRadius()` or any other per-class
   value. Empirical calibration against Galaxy lands at ~0.0102 — within
   2% of the MPE preview scale.

3. **Phaser strips are *arcs*, not rectangles or lines.** The arc lies
   on a sphere of radius `Length` around `Position`, swept across
   `ArcWidthAngles` around the `Up` axis. `Width` appears to be the
   radial thickness (rim → inward). This needs validation against real
   BC visuals on more ships.

4. **The `Position` field on every subsystem is a real, distinct mount
   point on the ship.** Hull at `(0, -1.5, -0.5)`, dorsal phasers at
   `(0, 1.27, 0.5)`, ventral phasers at `(0, 1.3, 0.16)`, etc. We were
   ignoring all of these and rendering everything at body origin.

5. **`SetOrientation(forward, up)` defines the bank's local basis.**
   `Right = up × forward` (right-handed so `world_up = direction × right`
   recovers `up` cleanly in the arc check). All three axes should be
   stored explicitly (BC's `PhaserBank` exposes
   `GetOrientationForward/Up/Right`).

## The bugs, in detail

### Bug A — Phaser positions all at (0, 0, 0)

`SubsystemProperty` had no typed `SetPosition`. Galaxy hardpoints call
`DorsalPhaser1.SetPosition(0, 1.27, 0.5)` with 3 floats. That fell
through to the data-bag, which stored
`("Position", (0, 1.27)) → 0.5` — losing the entire intent. The bank's
`SetProperty()` then called `prop.GetPosition()` (data-bag, returns
`None`), didn't `isinstance` to `TGPoint3`, so `bank._position` stayed
at its default `(0, 0, 0)`.

**Consequence:** *Every* mount point on *every* ship was at the ship's
centre of mass. Phaser strips, sensor arrays, shield generators, warp
cores, impulse engines, every torpedo tube, the bridge — all stacked
at the origin. Our debug overlay only revealed this because we drew
concentric arcs *at the same point*, all visually overlapping.

**Subsystems affected (Galaxy):** Hull, Bridge (HullProperty), Sensor
Array, Shield Generator, Warp Core, Engineering (Repair), all 5
impulse mounts, both warp engine mounts, all 8 phaser banks, all 6
torpedo tubes, Phasers/Tractors/Torpedoes parent systems — **~30 per
ship**.

### Bug B — Phaser arc centred on the ship's nose for *every* bank

`EnergyWeaponProperty` had no typed `SetOrientation`. SDK call:

```python
DorsalPhaser1Forward.SetXYZ(-1.0, 0.0, 0.0)  # port
DorsalPhaser1Up.SetXYZ(0.0, 0.0, 1.0)        # body up
DorsalPhaser1.SetOrientation(DorsalPhaser1Forward, DorsalPhaser1Up)
```

The two-arg `SetOrientation` hit the data-bag and was dropped. `bank.
_direction` stayed at the `EnergyWeaponProperty.__init__` default
`(0, 1, 0)` — *body +Y, dead ahead* — for every phaser on every ship.

**Consequence:** Every bank's firing cone was centred on the ship's
nose. ±50° around forward instead of ±50° around port/starboard/etc.
A ship in front of you took fire from every dorsal bank simultaneously.

### Bug C — `SetWidth` silently dropped

`SetWidth(1.35)` (the strip's radial / lateral dimension, distinct
from `SetPhaserWidth` which is the beam thickness) had no typed setter.
Dropped the same way. The deferred TODO in
`docs/superpowers/deferred/2026-05-18-phaser-hardpoint-coverage.md`
had noted this without realising it was being eaten by the data-bag.

### Bug D — `_strip_emit_position` modelled the strip as a line

Even with positions correct, the emit-point math placed the beam
origin on a 1D line `Position ± (Length/2) · Right`. With
`Position = (0, 1.27, 0.5)` and Galaxy `Right = (0, -1, 0)`, that's a
line *inside the saucer body* running along ±Y. Beams emerged from
inside the ship.

The strip is in fact an **arc** at radius `Length` around `Position`,
swept across `ArcWidthAngles` around `Up`. Emit point = closest point
on that arc to the target.

### Bug E — Render scale was derived from `GetRadius()`

We had `natural_scale = ship.GetRadius() / NIF_extent` with a
calibration constant `NIF_TO_WORLD = 4.3665 / 403.258`. Both the
formula and the constant are wrong — there's no per-ship-class scale
in the SDK at all. BC scales every NIF uniformly by **`0.01`** (per
MPE's reg key). `GetRadius()` is a *gameplay* value (used for splash
damage radius, AI threat range), not a rendering input.

### Bug F (still present) — `_emitter_in_arc` aim-origin is inconsistent

Two call sites pass different aim conventions to the arc check:

| Site | `aim_world` origin |
|---|---|
| `PhaserSystem.StartFiring` ([subsystems.py:1188](../../engine/appc/subsystems.py#L1188)) | `ship_pos → target` |
| Per-tick re-check ([host_loop.py:309](../../engine/host_loop.py#L309)) | `emit_pos → target` |

At close range these disagree dramatically. A bank can pass `StartFiring`
then immediately fail the next tick, or its visible beam can point in
the opposite direction of its firing arc because the emit point sat
*past* the target on the strip.

**Correct convention:** aim should be `bank.Position → target` at both
sites. The firing cone originates at the mount, not at the ship's
centre and not at the emit point.

### Bug G (parallel to A) — `PositionOrientationProperty` still swallows

The same data-bag bug class applies to `PositionOrientationProperty`,
which is a bare `pass` in our code. SDK calls:

```python
ViewscreenForward.SetPosition(ViewscreenForwardPosition)  # TGPoint3
FirstPersonCamera.SetPosition(FirstPersonCameraPosition)
```

These fall through to the data-bag too. The viewscreen-camera anchor
points and the first-person camera position all sit at `(0, 0, 0)`.
Not combat-relevant but real, and worth fixing in the same pass.

(`ObjectEmitterProperty` for ShuttleBay / ProbeLauncher has its own
typed `SetPosition(self, p)` for the single-TGPoint3 form. That one
actually works.)

## The working model (for the clean implementation)

### Render scale + offset

- `BC_MODEL_SCALE = 0.01` (treat 0.0102 as within calibration noise;
  re-verify per ship class).
- Body-frame translation overlay required to align NIF origin with HP
  coordinate origin. Galaxy calibration: `≈ (0, 0, 0)` with negligible
  Y offset — the NIF and HP frames are essentially co-located once
  scale is right. Universality across ship classes TBD.

### Per-phaser-bank data model (mirrored from BC's `PhaserBank` API)

Body-local fields:

| Field | Source | Notes |
|---|---|---|
| `Position` | `SubsystemProperty.SetPosition(x, y, z)` | Mount / arc curvature centre. |
| `Direction` (= Forward) | `EnergyWeaponProperty.SetOrientation(fwd, up)` | Aim direction at strip's angular centre. |
| `Up` | same | Arc plane normal. |
| `Right` | derived: `up × forward` | Stored explicitly; matches BC's `GetOrientationRight`. |
| `Length` | `EnergyWeaponProperty.SetLength` | Arc radius from Position. |
| `Width` | `EnergyWeaponProperty.SetWidth` | Radial thickness (rim → inward). *Unvalidated.* |
| `ArcWidthAngles` | `SetArcWidthAngles(lo, hi)` | Yaw range around Up. |
| `ArcHeightAngles` | `SetArcHeightAngles(lo, hi)` | Pitch range around per-yaw Right. |
| `PhaserWidth` | `SetPhaserWidth` | Beam thickness — distinct from `Width`. |

### Strip emit point algorithm

Given `target_world`:

1. Rotate `Position`, `Forward`, `Up` into world space using the
   ship's `R · scale`.
2. Compute `world_right = world_up × world_forward`.
3. Project `(target_world - world_Position)` onto `(world_forward,
   world_right)` (the arc plane perpendicular to `world_up`).
4. `yaw = atan2(right_proj, fwd_proj)`.
5. Clamp `yaw` to `ArcWidthAngles`.
6. `emit_direction` = Rodrigues rotation of `world_forward` around
   `world_up` by the clamped `yaw`.
7. `emit_world = world_Position + Length × emit_direction`.

For point emitters (`Length == 0`) this collapses to `world_Position`.

### Arc check (`_emitter_in_arc`)

- Aim origin: **`bank.Position` (in world space), NOT ship_pos and NOT
  emit_pos.** Both fire-time and per-tick re-checks must use the same
  origin.
- Decompose aim onto `(world_forward, world_right, world_up)`.
- `yaw = atan2(right_dot, fwd_dot)`; `pitch = asin(up_dot)`.
- Pass iff `arc_w_lo ≤ yaw ≤ arc_w_hi` and `arc_h_lo ≤ pitch ≤ arc_h_hi`.

### `SetPosition` signature handling

The SDK uses both forms across different hardpoint types:

- `SetPosition(x, y, z)` — 3 floats. Used by all `SubsystemProperty`
  subclasses (Hull, Phaser banks, Torpedo tubes, etc.).
- `SetPosition(TGPoint3)` — single point. Used by
  `ObjectEmitterProperty` (ShuttleBay, ProbeLauncher) and
  `PositionOrientationProperty` (Viewscreen*, FirstPersonCamera).

The clean implementation should accept *both* forms on every property
that has a `Position`. Put a `SetPosition(*args)` handler high enough
in the hierarchy that all of those classes inherit it, OR add it
individually with consistent semantics. Suggested: hoist it to
`TGModelProperty` itself so the data-bag never sees a `SetPosition`
call. Same for `SetOrientation`.

## Implementation plan (for the clean rewrite)

1. **Audit every typed setter in the SDK** by greping `sdk/Build/scripts/
   App.py` for `\bSetX = new.instancemethod`. For every binding,
   confirm we have a typed implementation in the matching class.
   Anything that hits the data-bag is silently broken.

2. **Hoist `SetPosition`, `SetOrientation`, `SetDirection`, `SetRight`,
   `SetUp` to a base** so every property type that has them is covered
   by a single implementation. Avoid the "added it to one class,
   forgot the parallel hierarchies" footgun this session hit twice.

3. **Replace the scale machinery in [`engine/host_loop.py:1442`](../../engine/host_loop.py#L1442)
   et seq.** with the flat `BC_MODEL_SCALE = 0.01` constant. Delete
   `NIF_TO_WORLD`, `_model_extent_from_aabb`, `natural_scale` per-ship
   storage. Verify against Sovereign and one Klingon ship before
   trusting universality.

4. **Refactor `_strip_emit_position`** to the arc algorithm above.
   Single source of truth; the debug overlay should *use the same
   function* to draw arcs (any drift between "what we draw" and "what
   we emit from" is a bug).

5. **Fix `_emitter_in_arc` callers** to pass aim from
   `bank.Position → target`. Consider changing the signature to take
   `target_world` directly and computing aim inside.

6. **Add `PositionOrientationProperty.SetPosition`** (single TGPoint3
   arg, mirroring `ObjectEmitterProperty`'s). Viewscreen camera
   positions, etc.

7. **Validate with a debug overlay** similar to the one in the spike
   branch — bright-coloured arc strips per phaser bank, Position cross,
   Forward+Up arrows. Confirm beams emerge ON the drawn arcs (proves
   `_strip_emit_position` and debug-viz are using the same model).

8. **Add `Width` interpretation tests** once we can A/B against BC
   screenshots. The radial-thickness interpretation is a guess.

## Open questions

- **Is the `0.01` scale truly universal across ship classes?** Need to
  test Sovereign, Akira, Defiant, Bird of Prey at minimum. If a ship
  drifts, BC likely has a per-class scale we haven't found yet.
- **Is `Width` radial thickness or something else?** Possible
  alternatives: lateral extent perpendicular to the strip arc; vertical
  thickness off the saucer surface; a beam-width parameter unrelated
  to strip geometry.
- **Does `ArcHeightAngles` describe the strip's physical extent or only
  the firing cone?** We currently use it only for the firing-cone
  check. If the strip itself curves vertically (3D patch instead of
  flat arc), beams would emerge above/below the saucer plane.
- **What does BC do at the `arc_w_lo == arc_w_hi` degenerate case?**
  Some torpedo tubes have point geometry — confirm they still work.
- **Is there a per-strip thickness on the saucer surface?** Real BC
  Galaxy dorsal phaser strips appear ~0.05 GU thick visually.

## Key SDK references

- `sdk/Build/scripts/ships/Hardpoints/galaxy.py` — concrete Galaxy
  hardpoints. Lines 195–697 cover all 8 phaser banks; 693+ covers
  hull and powered subsystems.
- `sdk/Build/scripts/App.py:6478–6489` — `PhaserBank.GetOrientationForward
  /Up/Right`, BC's three-axis bank API.
- `sdk/Build/scripts/App.py:9106–9156` — `PositionOrientationProperty.
  SetOrientation`, `SubsystemProperty.SetPosition`.
- `sdk/Build/scripts/App.py:9320` — `PhaserProperty.SetOrientation`
  binding (confirms it's a real method on the C++ side).
- `sdk/Tools/ModelPropertyEditor/modelpropertyeditor.reg` — UTF-16
  registry file containing the `ModelScale = 0.01` constant.

## Spike branch contents

`feat/hardpoint-research-spike` (commit `edbf828`) contains the
exploratory code:

- Position / Orientation / Width SubsystemProperty fixes.
- Arc-based `_strip_emit_position`.
- `[`-key in-game calibration mode (WASDQE / RF keys, prints scale +
  offset per press).
- Phaser HP debug overlay (red arcs + Position cross + Forward / Up
  arrows).
- `_BC_MODEL_SCALE = 0.0102`, `_BASELINE_OFFSET_BODY = (0, -0.05, 0)`.

It is **a research scaffold, not a target for merge.** The clean
implementation should pull the *findings* from this doc and the
*shape* from the spike, but write each piece deliberately rather than
incrementally patching the spike.
