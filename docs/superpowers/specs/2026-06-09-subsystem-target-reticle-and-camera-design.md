# Subsystem Target Reticle & Camera Focus — Design

**Date:** 2026-06-09
**Status:** Approved design, pending implementation plan
**Area:** targeting HUD (renderer), tracking camera, subsystem world-position core

## Problem

When the player locks a **subsystem** that sits far from the ship centre (a
Galaxy's port/star warp nacelles, the impulse pods), nothing on screen moves to
that subsystem:

1. The tracking camera keeps orbiting the ship's hull centre.
2. There is no on-screen indication of *which* part is locked.

This became visible only after the "faithful hardpoint subsystem loading" work
made off-centre nacelles/pods individually targetable for the first time. The
camera always used `ship.GetWorldLocation()` (hull centre); this was latent, not
a regression.

Bridge Commander's faithful HUD is a **two-element reticle**, drawn natively by
the original engine (the SDK only loads the textures — see
`sdk/Build/scripts/Tactical/ReticleTextures.py`):

- `game/data/target.tga` — corner brackets that box the **whole** target ship.
  Framing the whole ship is *correct*.
- `game/data/subtarget.tga` — a crosshair that marks the **specific** locked
  subsystem.

This reimplementation has **neither** element today. So the work is: build the
two-element reticle from scratch, and re-centre the tracking camera on the
locked subsystem.

## Decisions (from brainstorming)

| Question | Decision |
|---|---|
| Camera behaviour on subsystem lock | **Re-centre** the look-at point on the subsystem (camera *distance/zoom* stays keyed to ship radius). |
| Reticle model | **Faithful BC two-element**: full-ship corner box (`target.tga`) + subtarget crosshair (`subtarget.tga`). |
| Crosshair sizing | Constant on-screen pixel size (BC's fixed 8×8 icon). |
| Box sizing | Scales with distance — projected from the ship's bounding sphere. |
| Render path | **Native GL billboard pass**, modelled on `SubsystemPinPass`. |
| Box visibility | Whenever a **target** exists — any view (chase or tracking), independent of camera mode. Crosshair shows whenever a **subsystem** is locked. |
| Occlusion | Both elements draw **depth-test-off** (always on top), faithful to BC and consistent with `SubsystemPinPass`. |
| Unrotated `GetWorldLocation` bug | **Fold the fix in** (see §5). |

## Architecture — single source of truth

Both the camera and the reticle must agree, frame-for-frame, on where a
subsystem is. They share **one** computation: a subsystem's world mount point =
`ship_world_location + R · local_mount` (R = ship world rotation,
column-vector convention; **no scale** — BC stores mounts in world units
relative to the ship centre).

The canonical implementation today is `subsystem_world_position(sub, ship)` in
[`engine/ui/ship_property_viewer.py:14`](../../../engine/ui/ship_property_viewer.py).
`_ShipSubsystem.GetWorldLocation()`
([`engine/appc/subsystems.py:743`](../../../engine/appc/subsystems.py)) computes
the *same thing* but **omits the rotation** — a real bug (see §5).

### New module: `engine/ui/target_reticle.py`

Pure Python (no GL/CEF imports), the single decision point for both consumers:

```python
def target_aim_point(player) -> TGPoint3 | None:
    """World point the tracking camera should orbit.
    Subsystem world position if a valid subsystem is locked; else the
    target's hull centre; None if there is no valid target."""

def build_target_reticle(player) -> TargetReticlePayload:
    """What the reticle pass should draw this frame:
      visible:       bool   — a valid target exists
      ship_center:   (x,y,z) world hull centre
      ship_radius:   float  — target GetRadius() (GU), drives box size
      subtarget_pos: (x,y,z) | None — subsystem world pos, or None when no
                     subsystem is locked / it is invalid."""
```

Both functions resolve subsystem positions through the **same** core routine as
`GetWorldLocation` (post-fix, §5), so the camera look-at and the crosshair can
never disagree — "picks match by construction," the discipline the Ship
Property Viewer spec already established.

Target/subsystem validity (subsystem still attached and not destroyed; target
non-self and in range) mirrors the director's existing `_valid_target` logic so
the reticle hides exactly when tracking disengages.

## Component 1 — Camera re-centre

`_TrackingCamera.compute(...)`
([`engine/cameras/tracking.py:128`](../../../engine/cameras/tracking.py)) frames
player **S** and target **T**, with `T = target.GetWorldLocation()` driving the
plane basis, the inscribed-angle locus, and the look-at.

Change:
- Add optional `aim_point=None` to `compute(...)`. When provided,
  `T = aim_point` (replacing `target.GetWorldLocation()`); all downstream solver
  and spring code is untouched.
- The director ([`engine/cameras/director.py:122,135`](../../../engine/cameras/director.py))
  computes `aim_point = target_aim_point(player)` and passes it into **both**
  `tracking.compute(...)` call sites.

Because `aim_point` flows through the existing position/rotation springs,
re-centring on an off-centre nacelle **eases** over instead of snapping, and
switching subsystems glides. `set_ship_radius` / zoom distances stay keyed to
the **ship** radius, so framing distance does not collapse when a tiny part is
locked.

**Edge cases (in `target_aim_point`):**
- No subsystem locked → hull centre (byte-identical to current path).
- Subsystem destroyed/removed/detached → treated as no subsystem → hull centre.
- Subsystem with no 3D mount → core routine already returns ship centre.
- No valid target → director already falls back to Chase before consulting us.

## Component 2 — `TargetReticlePass` (native GL)

New `native/src/renderer/target_reticle_pass.{cc,h}`, modelled directly on
[`subsystem_pin_pass.cc`](../../../native/src/renderer/subsystem_pin_pass.cc):
same unit-quad VBO, same camera-facing billboard expansion
(`u_view_proj` + `u_camera_right`/`u_camera_up`), same depth-test-off draw and
state restore.

**Assets** (loaded once, like the pin glyphs):
`game/data/target.tga`, `game/data/subtarget.tga`, decoded via
`assets::decode_tga` + `assets::upload_image`.

**Full-ship box** — four `target.tga` corner billboards using BC's four mirror
orientations (`ReticleTextures.py` icon locations 0–3: UL, UR mirror-H,
LL mirror-V, LR rotate-180). Each corner sits at `ship_center` offset by
`±ship_screen_radius` along `cam_right`/`cam_up`, where `ship_screen_radius`
derives from the projected bounding sphere (`ship_radius`). The box wraps the
whole ship and scales with distance. **This is the element that correctly
frames the whole ship — faithful, not a bug.**

**Subtarget crosshair** — one `subtarget.tga` billboard at `subtarget_pos`,
drawn only when `subtarget_pos` is non-null. Constant on-screen pixel size via
the pin pass's `kPinSizePx` distance-compensation (`world = 2·dist·px·tan/h`),
matching BC's fixed-size icon.

**Mirror handling** is the one addition over the pin pass: corner quads need
per-corner UV flips. Pass a `vec2 u_uv_flip` uniform (or flip UVs per draw)
rather than four textures. Shader is a near-clone of `subsystem_pin.{vs,fs}`.

**Occlusion:** depth-test-off → both elements always visible over the hull
(answers the "occluded behind hull" edge case; faithful to BC).

New shaders ⇒ run `cmake -B build -S .` (regenerate embedded-shader headers)
**before** `cmake --build build -j`.

## Component 3 — Host wiring & data flow

**Host binding** `set_target_reticle(payload)` in
[`host_bindings.cc`](../../../native/src/host/host_bindings.cc), mirroring
`set_subsystem_pins`:
- Module-scope `renderer::TargetReticle g_target_reticle;` +
  `std::unique_ptr<TargetReticlePass> g_target_reticle_pass;`.
- Construct in the init block (alongside host_bindings.cc:217–218), reset in the
  teardown block (254–258).
- Render in the same draw block as the pin/hologram passes (340–343), gated on
  `g_target_reticle.visible`.

**Python wrapper** `set_target_reticle(...)` in
[`engine/renderer.py`](../../../engine/renderer.py) next to `set_subsystem_pins`
(renderer.py:321), `hasattr`-guarded so it silently no-ops without an engine
(per the damage-decals gotcha).

**Per-frame feed** in host_loop's HUD/camera section (near the existing
`r.set_camera(...)` at host_loop.py:2674), run **every frame regardless of
camera mode**:
```python
r.set_target_reticle(build_target_reticle(player))
```

**Data flow:**
```
player.GetTarget() / GetTargetSubsystem()
   ├─ target_aim_point(player) ──→ director ──→ tracking.compute(aim_point=…) ──→ camera
   └─ build_target_reticle(player) ──→ r.set_target_reticle ──→ TargetReticlePass
        (both resolve subsystem pos through the one shared core routine)
```

## Component 4 — Folded-in fix: rotated subsystem world position

`_ShipSubsystem.GetWorldLocation()` (subsystems.py:743) currently returns
`parent_ship_loc + self._position` with **no rotation** — wrong for any
pitched/rolled ship. The weapon-aim sites (host_loop.py:297, 454) already lean
on it, so phaser/torpedo aim and beam length are subtly wrong on rotated targets
today.

Fix:
- `GetWorldLocation()` rotates `self._position` through
  `self._parent_ship.GetWorldRotation()` (column-vector `R · local`), matching
  `subsystem_world_position`.
- **De-duplicate:** extract the `ship_loc + R · local` computation into one
  routine so `GetWorldLocation` and `subsystem_world_position` cannot diverge
  again. `subsystem_world_position` keeps its explicit-`ship` escape hatch for
  the Hull/root subsystem (whose `_climb_to_ship()` returns None).
- Weapon-aim sites keep calling `sub.GetWorldLocation()` — now correct, no
  re-pointing needed.

**Blast radius:** these tests reference subsystem world positions / weapon aim
and must be audited for hardcoded *unrotated* expectations and updated to the
correct rotated values:
`tests/unit/test_subsystems.py`, `tests/unit/test_combat_hit_resolution.py`,
`tests/unit/test_shield_face_from_hit_point.py`,
`tests/unit/test_phaser_fire_range_gate.py`,
`tests/unit/test_torpedo_tube_fire_dumb.py`,
`tests/unit/test_weapons_disabled_blocks_fire.py`,
`tests/unit/test_fire_script_choose_subsystem.py`,
`tests/ui/test_ship_property_viewer.py`. Tests using an **identity** ship
rotation are unaffected (rotated `R·0`-offset == unrotated).

## Camera-rules compliance

No global-up assumption introduced. The tracking camera already derives body-up
from `R.GetCol(2)`; we only swap the *look-at point*. Reticle billboards use the
camera's own right/up from the view matrix (screen-space), so no world-Z
reference enters anywhere.

## Testing

**Pure-Python** (`tests/test_target_reticle.py`, focused subset only — the full
suite OOMs the machine):
- `target_aim_point`: subsystem world pos (rotated) when locked; hull centre
  when none; hull centre when subsystem destroyed/detached; ship centre when
  subsystem has no mount. **Use a pitched/rolled ship** so `R·local` is
  exercised.
- `build_target_reticle`: `visible` + `subtarget_pos` across four states
  (no target / target only / subsystem locked / invalid target).
- Single-source-of-truth: `target_aim_point` and
  `build_target_reticle().subtarget_pos` agree for a locked subsystem.

**Camera** (extend tracking/director tests): with a subsystem locked the
look-at equals the subsystem world pos; with none, the hull centre. Use the
no-spring path (`dt=None`) for deterministic geometry.

**Folded-in fix** (`tests/unit/test_subsystems.py`): `GetWorldLocation` on a
rotated ship equals `ship_loc + R·local`; equals `subsystem_world_position`.

**GL pass**: not unit-tested (consistent with the other passes). Manual
verification via `./build/dauntless --developer` — lock a Galaxy port nacelle
and confirm: (1) the corner box wraps the whole ship; (2) the subtarget
crosshair sits on the nacelle; (3) the camera eases to centre the nacelle;
(4) switching subsystems moves both smoothly; (5) destroying the locked
subsystem drops the crosshair and recentres on the hull; (6) the box (no
crosshair) shows for a ship-only target in chase view.

## Scope

**In:** `engine/ui/target_reticle.py`; `aim_point` override in tracking +
director; `TargetReticlePass` (+ shader, pipeline accessor, embedded headers);
`set_target_reticle` host binding + `renderer.py` wrapper; host_loop feed;
`GetWorldLocation` rotation fix + de-dup; tests above.

**Out:** windowed/render-to-texture or CEF reticle; any reticle styling beyond
the two stock textures; changes to weapon damage/arc *logic* (only the
now-correct position flows through).

## Open implementation details (resolve during build)

- Confirm `_parent_ship` is populated for every targetable subsystem (pods,
  nacelles, bridge) so `GetWorldLocation` has a ship to rotate against; fall
  back to the helper's explicit-ship path where it isn't.
- Exact `ship_screen_radius` factor (bounding-sphere radius vs. a small padding
  multiplier) tuned by feel in `--developer`.
- `target.tga` corner pixel dimensions (16×8 per `ReticleTextures.py`) →
  on-screen corner size constant.
