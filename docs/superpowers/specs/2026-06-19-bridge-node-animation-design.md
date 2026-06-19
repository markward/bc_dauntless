# Bridge Node Animation — Chairs + Doors

**Date:** 2026-06-19
**Status:** Design approved; ready for implementation plan.
**Supersedes the sketch in:** `docs/superpowers/specs/2026-06-19-bridge-chair-node-animation-followup.md`
(that file captured the findings; this is the buildable design).

## Goal

Give the **non-skinned** bridge model real **node-keyframe animation** so that:

1. **Seated officers' chairs rotate** when an officer turns to the captain, and the
   seated officer **rides the chair** — fixing the Tactical *forward*-turn gap
   (`db_face_capt_t` is empty in BC's data; the forward turn lives entirely in the
   rotating chair) and removing Helm's static-seat compromise.
2. **Bridge doors lift** during the crew walk-on cutscene (already merged) — its door
   `TGAnimAction(pBridgeNode, …)` call exists and routes to the renderer today, but the
   render path ignores it, so doors are currently inert.

This is the deferred "bridge door animations" renderer feature
(`native/src/host/docs/deferred_work.md` #38). It is **foundational, not chair-specific**:
one capability (apply a clip's sampled node transforms to a non-skinned instance) serves
both chairs and doors.

## Background — why the foundation is genuinely unbuilt

- The bridge is a **non-skinned** `assets::Model` drawn by `walk_bridge_meshes`
  (`native/src/renderer/bridge_pass.cc`), which composes
  `world_per_node[i] = world_per_node[parent] · node.local_transform` from the model's
  **static** node locals. It never consults animation state.
- `update_animations` (`native/src/renderer/animation_update.cc`) only produces a **bone
  palette** — the **skinned** path. It samples the clip against `m->skeleton`. A non-skinned
  bridge has no skeleton/skinning, so this produces nothing the bridge draw uses.
- Consequence: `bridge_cutscene.py`'s door call `renderer.set_instance_animation(iid, 0, False)`
  sets `Instance::AnimationState` that **nothing visible honors**. Doors do not move. Confirmed
  by inspection 2026-06-19.

## SDK facts (verified)

- The bridge object exposes `pBridge = pSet.GetObject("bridge")`, `pBridgeNode = pBridge.GetAnimNode()`
  (our `engine/appc/anim_node.py:TGAnimNode`, `kind="object"`, `owner=bridge`).
- **Chairs:** seated `TurnCaptain` builders are multi-action — the officer **body** clip on the
  **character** node (`db_face_capt_h` Helm, `db_face_capt_t` Tactical) PLUS the **chair** clip on
  the **bridge** node (`db_chair_H_face_capt`, `db_chair_T_face_capt`, …). The chair clip is a
  **separate NIF** (`data/animations/db_chair_*_face_capt.nif`) loaded as a named animation; it
  rotates a `console seat NN` node ~60° about the bridge vertical and also bakes a `Camera captain`
  view-path (the zoom camera — **ignored here**, it is the camera not the chair).
- **Doors:** door keyframes are baked **into DBridge.nif itself** (12 `NiKeyframeController` +
  12 `NiKeyframeData` blocks → the model's own `animations[]`). The SDK plays them with
  `TGAnimAction(pBridgeNode, "db_Door_L1", 0, 0)` (and a `TGScriptAction "LiftDoorAction"` variant)
  **inside crew walk-on / stand-up sequences** (`Bridge/Characters/{Large,Medium,Common}Animations.py`).
  There is **no** standalone door trigger in the menu flow; the walk-on cutscene is the driver.

## Two clip sources, one override map

The single new renderer capability is a **per-instance node-override map**:
`node_index → animated local_transform`. `walk_bridge_meshes` (and `aabb.cc`, kept consistent)
uses the override when present, else the node's static local. Both features feed this map:

| Source | Clip lives in | Played as | Targets |
|---|---|---|---|
| Doors | DBridge.nif's own `animations[]` (embedded clip) | the instance's embedded clip index | door-leaf nodes |
| Chairs | separate `db_chair_*_face_capt.nif` (external clip) | external clip applied to the bridge node subset | `console seat NN` |

At rest (no active clip, or t=0 identity) the override map is empty and the bridge draws
**byte-identically** to today. This is the primary regression guard.

## Architecture

### Component 1 — Non-skinned node-override animation (the foundation)

**Renderer / scenegraph.** Extend the instance animation path so a non-skinned instance can
carry **node-local overrides** sampled from a clip, in parallel with the existing skinned
bone-palette path:

- `native/src/scenegraph/include/scenegraph/instance.h` — store, per instance, an optional
  node-override map (`std::unordered_map<int, glm::mat4>` or a parallel `std::vector` sized to
  the model's node count) plus the animation state needed to sample it (clip handle/index, loop,
  start wall time, external-vs-embedded).
- `native/src/renderer/animation_update.cc` — for an instance whose model is **non-skinned** (or
  whose active clip targets named nodes rather than a skeleton), sample the clip's `NodeTrack`s by
  **node name** against the model's `nodes` vector and populate the override map with each tracked
  node's animated local. Untracked nodes get **no** entry (walk falls back to static). Reuse the
  existing keyframe sampler (`assets::sample_track_trs` / `anim_sample`).
- `native/src/renderer/bridge_pass.cc` — `walk_bridge_meshes` consults the active instance's
  override map: `local = override.count(i) ? override[i] : node.local_transform;`
- `native/src/renderer/aabb.cc` — same override lookup so bounds track animated geometry (or an
  explicit decision to leave bridge bounds static — bridges never frustum-cull the player; record
  whichever is chosen).

**Host binding** (`native/src/host/host_bindings.cc`):
- Play an **external** clip on a non-skinned instance's node subset (load the chair NIF's clip,
  apply its node tracks to the bridge instance) — the chair path.
- The **embedded**-clip path (`set_instance_animation(iid, clip_index, loop)`) already exists; make
  it produce node overrides for non-skinned instances — the door path.
- Read a named node's **animated world transform** from an instance (for officer-seat coupling).

### Component 2 — Chair playback + officer-seat coupling

**`engine/appc/bridge_placement.py`** — `capture_registered_clip` currently picks the last
`kind=="character"` action and **discards** the bridge-node chair action. Add a companion capture
(e.g. `capture_chair_clip`) that returns the `kind=="object"` (bridge-node) action's clip for the
same `<location>TurnCaptain` / `BackCaptain` builders.

**`engine/bridge_character_anim.py`** — `_process_turn`:
- As today, submit the officer **body** clip (layered, root-anchored, hold while open).
- **Also** submit the **chair** clip to the **bridge** instance via the bridge controller, and
  register the seated officer for **seat coupling** against the chair's `console seat NN` node.
- Menu-down reverses both (chair reverse clip + body BackCaptain), and clears coupling.

**Officer-seat coupling math** (per tick, for a coupled officer):

```
R_delta        = seat_animated_world · inverse(seat_rest_world)
officer_world' = seat_pivot · R_delta · inverse(seat_pivot) · officer_world
```

`seat_pivot` is the seat node's rest world translation. At rest `R_delta = I`, so a coupled
officer with an un-animated seat is **byte-identical** to its placement — the production path is
unchanged. Standing officers (no seat node) are never coupled. The officer body clip continues to
play **on top** of the coupled (chair-rotated) base, so Helm gets body-turn + seat rotation and
Tactical is carried by the chair alone.

**`engine/bridge_cutscene.py`** — already routes the door action via `request_object_anim` →
`set_instance_animation(iid, 0, False)`. Once Component 1 honors non-skinned overrides, this call
animates the door leaves with **no further change** to the cutscene. (The chair path may live in
this controller or a sibling bridge-node controller; the plan decides, keeping `bridge_cutscene.py`
focused if it would otherwise grow too large.)

## Data flow

**Chair (menu-up → turn):**
1. CEF crew menu → officer `MenuUp()` → controller turn request (existing seam).
2. `bridge_placement` returns the **body** clip (character node) **and** the **chair** clip (bridge node).
3. Body clip plays on the officer (layered, root-anchored — unchanged).
4. Chair clip plays on the **bridge** instance → `console seat NN` rotates ~60°.
5. Each tick the officer is re-based by the seat's `R_delta` (coupling); body rides on top.
6. `MenuDown()` reverses both; coupling cleared.

**Door (walk-on cutscene):**
1. Merged E1M1 walk-on sequence issues `TGAnimAction(pBridgeNode, "db_Door_L1")`.
2. `bridge_cutscene.request_object_anim` → `set_instance_animation(iid, 0, …)`.
3. Component 1 samples DBridge.nif's embedded door clip → door-leaf node overrides → leaves lift.

## Error handling / edge cases

- **No renderer (headless tests):** every renderer/coupling call is `hasattr`-guarded / try-excepted;
  capture + routing degrade to no-ops. Existing headless suites stay green.
- **Missing chair clip or seat node** (asset absent, or a station with no seat): no coupling, body
  clip still plays — never crash. Log once.
- **Mission swap:** bridge controller `reset()` clears pending chair/door requests, override maps,
  and coupling (mirrors `BridgeCutsceneController.reset()` and the MissionLib global-leak discipline).
- **Rapid open/close:** the existing in-flight eviction (turn-to-captain Minor #1) extends to the
  chair clip and coupling so a fast open+close cannot strand a rotated chair/officer.
- **Build-time verification:** confirm DBridge.nif actually contains a `console seat NN` node whose
  name matches the chair clip's track target, and that the door clip's track targets exist as nodes.
  If a name mismatch is found, resolve in the asset/import layer, not by renaming clips.

## Testing

**Native (gtest):**
- Node-override sampler: a clip animating one named node overrides only that node's local; untracked
  nodes keep their static local; an empty/identity clip reproduces the static walk exactly (regression).
- Seat-delta composition: `R_delta = I` at rest leaves the officer world unchanged; a known seat
  rotation rotates the officer about the seat pivot (not the origin).

**Python (pytest):**
- `capture_chair_clip` returns the `kind=="object"` chair action for Helm and Tactical builders.
- Menu-up routes the chair clip to the bridge instance and registers officer-seat coupling; menu-down
  reverses and clears it.
- Standing officers get **no** seat coupling.
- Headless (no renderer): capture + routing are graceful no-ops; suites stay green.

**GUI acceptance (Mark):**
- D-bridge: select **Tactical** → chair + officer rotate to face the captain (the gap, fixed);
  select **Helm** → body turns *and* seat rotates together; close → both reverse.
- Walk-on cutscene → bridge doors lift.
- Nothing selected, no cutscene → bridge render byte-identical to today.

## Behavior to preserve (do not regress)

- Standing officers (XO/Science/Engineer) + Helm body turns; menu-down reverse.
- The root-translation anchor in `sample_pose_over_base` (keeps `db_face_capt_h`'s root track from
  displacing the officer).
- Byte-identical static bridge render when no chair/door clip is active.
- Production combat/render paths unchanged (all new work is gated behind an active chair/door clip).

## Out of scope

- **Engine flares** — referenced loosely in deferred_work #38 but **not a grounded SDK target**
  (nacelle glow is the glow pass, not a `NiKeyframeController`); dropped from this project.
- A fully general non-skinned `AnimationPlayer` for arbitrary scenegraph instances — YAGNI; this
  project is bounded to the bridge instance.

See [[project_bridge_character_animation_shipped]], [[project_bridge_camera_walkon]],
[[feedback_sdk_drives_everything]].
