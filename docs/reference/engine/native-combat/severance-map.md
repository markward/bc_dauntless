# Severance map: making part severance a sim decision

Worktree read: `.claude/worktrees/native-combat-k3` (branch `ws/combat-launch-cache`, HEAD `5163932f4`). Read only: nothing built, run or edited.
Every path below is relative to that worktree. Anything not read directly off code is marked **inferred**.
The `stbc-reference` MCP failed to connect this session, so no BC behaviour was checked against the clean-room reference.

Abbreviations: HF `engine/appc/hit_feedback.py` · PS `engine/appc/part_severance.py` · HB `engine/appc/hull_breakup.py` · HW `engine/appc/hull_wear.py` · IB `engine/appc/internal_blast.py` · PDR `engine/appc/part_detach_render.py` · DC `engine/appc/debris_chunk.py` · ART `engine/appc/articulation.py` · HIO `engine/host_io.py` · HL `engine/host_loop.py` · PSC `native/src/renderer/part_severance_check.{h,cc}` · PSJ `native/src/renderer/part_severance_jobs.{h,cc}` · SPC `native/src/renderer/structure_parts_cache.{h,cc}` · BIND `native/src/host/host_bindings.cc`.

---

## 0. Headline: there are TWO severance mechanisms

| | **A. Appendage severance** (`part_severance`) | **B. Structure severance** (`hull_breakup`) |
|---|---|---|
| Ships | Rigged (articulated) hulls with an authored `break_fraction`: stock = Bird of Prey wings only (ART:713-722, test `test_only_the_wings_are_detachable` tests/unit/test_part_severance.py:399) | Every other ship with radius > 0.6 GU (`damage_geometry.breakables_allowed_for`, damage_geometry.py:63,106-121), not a rock, not rigged, not skinned |
| Rule | Hull damage attributed to a named NIF part accumulates. When it reaches `max hull × break_fraction`, the part goes (PS:291-340) | A voxel whose summed INTERIOR wear reaches the deck-break dial dies. A part that loses its connection to the main body leaves (PSC.cc:56-193) |
| Where it is decided | Python, synchronously inside the hit (HF:432-447 → PS:338-339) | C++ `find_severed_parts` on a worker thread, polled per FRAME from Python (HB:84-94, PSJ.cc:26-102) |
| Game state | Subsystems on the part go to 0. The part's collision spheres and trace triangles go. Mounts read their rest point | Subsystems in the piece go to 0. Collision and trace geometry are **unchanged** (inferred, §2.3) |

The two are mutually exclusive by design: HB:69-75 (Python gate) and `can_structure_sever` PSC.cc:20-24 (native gate: `node_overrides.empty() && !rigged`).

---

## 1. The severance path end to end

### 1.1 Common front: the hit, the gates, the trace

`combat.apply_hit` → `hit_feedback.dispatch` (damage-map.md §2 F6/F7, lines 177-178). Two dispatch blocks matter:

- **F6 — wear (feeds mechanism B)**, HF:377-425. The gate is `persist_decal and absorbed_hull > 0 and normal is not None and ship_instances is not None` (HF:377-378) and `iid = ship_instances.get(ship)` not None (HF:379-380). Inside it, `_structural_hit` must be true (HF:404; HF:203-218 says only LIGHT phaser fire is cosmetic). Then:
  - wear amount: `hull_wear.wear_for_hit` (HW:74-84: absorbed / 500, clamped 0.25-1.5. Phaser: ×`PHASER_RATE`. Collision: only a crumple (`dent==1`) of ≥100 hull);
  - reach = decal radius × `decal_radius_scale` (HF:409);
  - phaser: `accumulate_phaser` (HW:115-142) holds body-frame wear via `host_io.world_to_body` (needs the instance) and `flush`es on the decal emit (HF:417-418) or `drain` (HW:158-166);
  - other weapons: `hull_wear.send` → `host_io.hull_damage_add` (HW:101-108) → `hull_breakup.after_wear` (HW:87-98).
- **F7 — appendage share (mechanism A)**, HF:432-447. The gate is `_structural_hit and absorbed_hull > 0 and normal is not None and persist_decal and ship_instances is not None` (HF:432-434), plus `damage_eligibility.is_eligible(ship)` (HF:436). Then `iid` must be in `ship_instances` (HF:442) and `host_io.world_to_body(iid, …)` must answer (HF:444-446). Only then `part_severance.record_hit(ship, iid, conv[0], absorbed_hull)` (HF:447). No throttle: every beam tick counts (HF:438-441).

**`normal is not None` means a mesh-tier hit.** The surface normal exists only when `combat._resolve_hit_point` traced the real mesh: `host_io.ray_trace_mesh` → the `ray_trace_mesh` binding on the global `g_world` → `renderer::ray_trace_instance_linear` (k2-beams-map.md:30). With no instance there is "NO sphere fallback … (all headless runs)" (k2-beams-map.md:201). Sphere-tier hits pass a None normal and the decal comment says so (HF:373-374). So **both mechanisms are gated, upstream, on the renderer's mesh trace**. A sim-side decision alone is not enough; the hit geometry has to be sim-side too (§6).

Other gates:
- `persist_decal` is False under god mode (HF:375-376), so god mode never severs.
- `damage_eligibility` (A only): the player plus the 5 best-scoring others by proximity and size (damage_eligibility.py:21-73). It is refreshed only by `damage_eligibility.update`, called from `HL:1343` (`_advance_combat`). The headless harness never calls it (event-inventory.md:38: `_sim_tick` runs only `loop.tick()` + `dash.tick`).
- Instance existence (A and B): ships get instances only when in the player's or the viewed frame and once within `SHIP_DRAW_DISTANCE_GU` = 30000 (HL:7303-7313, render_scope.py:32). So even live, a fight in an unviewed frame never severs (**inferred** from the realize rule, not observed).

### 1.2 Mechanism A — appendage severance (Python)

1. `record_hit` (PS:291-340):
   - thresholds `articulation.detachable_for(leaf)` = `{name: break_fraction}` from the rig templates (ART:713-722). Return if there are none (PS:325-327).
   - model → ship units ×0.01 (PS:328).
   - attribution `part_for_live_point` (PS:166-226): the rest-box test `part_for_point` (PS:76-110, `ATTRIBUTION_MARGIN` 5.0 PS:35), then the inverse pose per posed part.
   - totals `ship._part_damage[part] += absorbed_hull` (PS:334-335). Cumulative, never decays (PS:19-22).
   - limit `GetHull().GetMaxCondition() × break_fraction` (PS:279-288, 336). Sever when total ≥ limit (PS:338-339).
2. The boxes come from `articulation.part_boxes_for(leaf, iid)` (ART:669-710). They are derived from `host_io.model_nodes(iid)`, which needs a **render instance of a loaded model**, cached per leaf the first time any instance is offered (ART:687-710). Headless returns `{}` unless a test seeds `_derived_boxes` (tests/conftest.py:1801-1830 seeds the Bird of Prey).
3. `sever` (PS:450-480), in order:
   1. `_parts_detached.add` (PS:469);
   2. `native_combat.push_posed_parts` (PS:472; the native pose table's detached bit, NC `_pose_table` native_combat.py:1638-1652);
   3. `_destroy_subsystems_on_part` (PS:526-552). For each mounted subsystem (`_mounted_subsystems` PS:483-503), `physical_parents.part_for_property` (explicit `SetPhysicalParent`, else `part_for_mount` PS:118-163, which asks `host_io.model_nearest_part(model, …)`, **a loaded model**, falling back to the box rule) and `sub.SetCondition(0.0)` (PS:548);
   4. `_silence_emitters_on` (PS:369-418, presentation);
   5. `part_detach_render.detach` (PDR:28-48): `set_instance_node_hidden` (zero matrix) on the parent, then `_spawn_chunk` (PDR:51-107): a new instance of the same model showing one part, plus `debris_chunk.spawn`. Best-effort, swallowed (PS:475-479).

### 1.3 Mechanism B — structure severance (Python throttle + C++ worker)

1. **Wear lands in the render instance's store.** `hull_damage_add` / `hull_damage_add_body` bindings (BIND:9792-9827, 9829-9852) convert the point to the body frame through **the instance's world matrix** (`to_body_frame`), attribute it to a node (`wear_node_for`), and `inst->hull_damage.add(...)` (`scenegraph::HullDamageStore`, hull_damage.h:41-72: 64 slots, merge-never-evict, a revision counter). The store **lives on `scenegraph::Instance` in `g_world`**.
2. **Wear sources that call `after_wear`:** combat (HW:95, 108, 149); internal blast (IB:189-193); `visible_damage` = AddDamage, DamageTool volumes and the death cascade (visible_damage.py:270-278); warp-core breach (warp_core_breach.py:149-156).
3. **`after_wear`** (HB:56-81) gates on `iid` not None, `breakables_allowed_for` (radius > 0.6 GU), not a rock (HB:66-68), and no rig (`articulation.parts_for_ship`, HB:73-75). Throttle: one check per ship per `kBreakupCheckInterval` = 0.5 s of game time (HB:37, 76-80). Inside the window the ship is marked `_pending_wear`.
4. **`_split`** (HB:115-164) → `host_io.hull_split_parts(iid)` (HIO:524-540; **returns `[]` when `_h is None`**, HIO:536-537) → binding (BIND:10001-10062):
   - `resolve_model(inst->model_handle)`: model must be loaded (BIND:10009-10010);
   - `structure_segmentation_shared(model->source)` (BIND:10012-10014): `nullptr` until the async detection or `.sps` read lands, which counts as "not severed";
   - `g_severance_jobs.poll(…, build_damage_list(i.hull_damage, g_params), g_params[24], skinned)` (BIND:10018-10026).
5. **`SeveranceJobs::poll`** (PSJ.cc:26-102):
   - gates: no seg, skinned, rock, chunk (`shown_parts != 0`), `!can_structure_sever` (PSJ.cc:36-40);
   - no job queued: skip if the stamp says the damage revision, severed mask and deck break are unchanged (PSJ.cc:76-79). Otherwise queue a `std::async` job owning its inputs by value and answer `pending` (PSJ.cc:81-101);
   - finished job: apply **only if** the revision, severed mask, deck break and seg all still match. Else drop it and re-queue (PSJ.cc:49-72).
6. **The decision, `find_severed_parts`** (PSC.cc:56-193), pure CPU, no GL (PSC.h:3-5):
   - `interior_wear_field` (PSC.cc:26-54): for each voxel centre, the sum over records of `wear × (1−r²)²` within reach. Surface reach is pre-scaled by **`params[7]`** (plating_damage.cc:18). Internal reach is used as stored (plating_damage.cc:22);
   - no voxel ≥ `deck_break` (`params[24]`, default 6.0, frame.cc:229) → return early (PSC.cc:67-71);
   - alive voxels: occupied, labelled, wear < deck_break, and not in a `gone` part (PSC.cc:77-87);
   - main body = the part with the most alive voxels, among parts < 32 (PSC.cc:89-93). Flood 6-connected from it (PSC.cc:95-122);
   - unreached components of ≥ `kMinPartVoxels` = 64 voxels (PSC.h:31). A part joins a piece when the majority of its alive voxels are in that component. `already_severed` = the **unhideable mask: parts ≥ `kMaxHideableParts` = 12 never sever** (PSC.h:73-76, PSJ.cc:89; that is a shader `MAX_PARTS` limit deciding gameplay);
   - output: per piece, a part bitmask, member voxels, centroid and bounds (PSC.cc:160-190).
7. **`apply_severed_pieces`** (PSC.cc:231-272), on the main thread, **fuses the decision with presentation**: per piece it creates the chunk instance (`world.create_instance`, copies pose, render state, damage and decals; `shown_parts = parts`), then **`parent.severed_parts |= parts`** (PSC.cc:267) and stamps (PSC.cc:270). The severed mask, the only record that a part has gone, lives on the render instance.
8. **Back in Python** `_split` (HB:126-164): None = pending → `_awaiting` (HB:126-128). Per fresh piece, `_spawn_components` (HB:167-182) runs:
   - `_destroy_subsystems_inside` (HB:199-235): a mount is "in" by its **voxel label** via `host_io.structure_part_at(iid, …)` (HB:297-322; binding BIND:10064-10083 needs the instance's model, seg and world scale), else by the piece bounds. Then `sub.SetCondition(0.0)` (HB:232);
   - `_silence_emitters_inside` (HB:251-294, presentation);
   - `debris_chunk.spawn` (DC:124-173), or `_burst` (`host_io.breach_burst`, HB:375-382) for a piece with no chunk instance.
9. **Polling is per FRAME, host only:** `hull_breakup.drain()` from HL:12836-12838 (`sim.debris_chunks`, after the sim ticks, before collisions). The headless harness never calls it.

### 1.4 Where each half lives

| Piece | Language / module | Needs a render instance? | Needs GL? |
|---|---|---|---|
| Hit point + normal (mesh trace) | C++ `renderer/ray_trace.cc` on `g_world` | yes | no for the trace itself; yes for the model load (BIND:923-925 throws without `g_window`) |
| Body-frame conversion | C++ binding `to_body_frame` / `world_to_body` (render pose) | yes | no |
| Wear amount | Python HW:74-84 | no | no |
| Wear store + merge | C++ `scenegraph::HullDamageStore` (GL-free lib, `scenegraph` links only glm) | **owned by the instance** | no |
| Damage list (reach × `params[7]`) | C++ `renderer/plating_damage.cc` | reads the instance store | no |
| Structure segmentation | C++ `renderer/structure_parts_cache.cc` over `voxel::detect_structure_parts` (voxel lib links nif, assets, glm only, voxel/CMakeLists.txt) | keyed by `model->source`, reached through the instance | no (the NIF is read by `collect_hull_triangles_from_source`, voxelize.h:73-80) |
| Severed-parts decision | C++ `renderer/part_severance_check.cc` (CPU) | input/output on the instance | no |
| Async + staleness | C++ `renderer/part_severance_jobs.cc` | yes | no |
| Throttle, subsystem kill | Python HB | yes (iid for `structure_part_at`) | no |
| A: attribution, threshold, kill | Python PS | yes (`world_to_body`, `model_nodes`, `model_nearest_part`) | indirectly (a loaded model) |

### 1.5 Exactly where each bails without a renderer instance

1. `HF:378`: `ship_instances is None` → F6 skipped. `HF:380`: no iid → skipped. Upstream, with no instance the trace gives `normal=None` (k2-beams-map.md:201), so `HF:377` fails first.
2. `HF:434`: F7 `ship_instances is not None`. `HF:442`: iid. `HF:446`: `world_to_body` None (`HIO:411-412` when `_h is None`).
3. `HB:64`: `iid is None` → `[]`.
4. `HIO:536-537`: `hull_split_parts` → `[]` with no host module. `BIND:10006-10010`: stale id or unloaded model → `[]`. `BIND:10014`: seg not ready → `[]`.
5. `ART:690-691`: `part_boxes_for` with no iid and nothing cached → `{}` → `part_for_point` None (PS:96-98) → `record_hit` returns None (PS:330-331).
6. `damage_eligibility._current` stays empty headless (`update` only at HL:1343) → `is_eligible` False (HF:436).

So headless never severs. The PS docstring's claim "None is fine (headless): the sim-side detach still happens" (PS:299-301) is true only for a direct `record_hit` caller with seeded boxes (the unit tests). It is never true through `dispatch`.

---

## 2. What severance changes in game state

### 2.1 Mechanism A (appendage)
- **Subsystems destroyed:** `SetCondition(0.0)` per subsystem on the part (PS:548), synchronously inside the hit. Through `_condition_changed` (subsystems.py:786-815) that posts **`ET_SUBSYSTEM_DESTROYED`** (or `_DISABLED`) via `_fire_threshold_event` and **queues an internal blast** (`internal_blast.queue`, subsystems.py:803-809). `SetCondition` also auto-enqueues for repair (subsystems.py:743-745), and `AddToRepairList` rejects destroyed systems (subsystems.py:737-741, docstring).
- **⚠ Bypasses death routing.** `SetCondition(0)` is not `DamageSystem` / `DestroySystem`: no `_route_zero_crossing` (warp-core-breach arming, cascade scheduling) and no `ship_death.begin` for a critical subsystem (objects.py:1074-1100 vs PS:548 / HB:232). A severed piece holding a critical subsystem leaves the ship alive with that subsystem at 0 (**inferred** from the code; whether any stock hull mounts a critical subsystem on a severable part was not checked).
- **Collision:** the part's hull-bound spheres stop colliding (`hull_bounds.py:155, 213`, `is_detached`).
- **Hit geometry:** the hidden node's subtree has a singular matrix, and the trace treats such a subtree as severed (`renderer/ray_trace.cc:627-641, 674, 701`). This half lives on the render instance.
- **Weapon geometry:** mounts on a detached part read their REST point (ART:809-813; native pose table detached bit, native_combat.py:1638-1652). The mounted weapons are destroyed anyway.
- **Debris body:** a `DebrisChunk` (DC) in the collision system (collisions.py:1219-1221). It is "visual debris that collides … a ship it strikes takes kinetic damage, but not targetable, no hull HP, no subsystems" (2026-09-11-breakable-hull-components-design.md §1 table). Mass = parent mass × part AABB volume fraction (PDR:86-104). **The parent's mass and radius are unchanged** (no `SetMass` / `SetRadius` in PS / HB / DC / PDR).
- Not targetable, not in sets, no `ET_OBJECT_*` event: none is posted on these paths (grep of `ET_` / `PostEvent` in PS, HB, DC, PDR finds nothing).

### 2.2 Mechanism B (structure)
- **Subsystems destroyed:** `SetCondition(0.0)` for every mount in the piece (HB:229-232), with the same events, internal blast and death-routing bypass as above. **Deferred**: applied at the frame poll that collects the worker result, not inside the hit (damage-map.md:177).
- **Feedback loop:** destroyed subsystem → `internal_blast.queue` → `IB._blast` adds Internal wear (`hull_damage_add(…, 3)`, IB:172-173) → `after_wear` (IB:189-193) → possibly more severance. IB says "Gameplay is untouched" (IB:22), but its wear feeds B, so it is gameplay.
- **Debris body:** `DebrisChunk` with mass = parent mass × piece voxels / total voxels (DC:157-158).
- **Not changed (inferred from grep):** hull collision spheres (`hull_bounds` checks only articulated names), ray-trace geometry (`ray_trace.cc` never reads `severed_parts`; only `frame.cc` and the shaders do), mass, radius, targetability. A shot through the gap still hits the missing nacelle.
- Native combat has no knowledge of structure severance (no `severed_parts` use under `native/src/combat`).

### 2.3 BC vs Dauntless
- Both mechanisms are **Dauntless additions.** The only BC surface is the global toggle `DamageableObject_SetBreakableComponentsEnabled` (objects.py:1638-1645; damage_geometry.py:3-4 "genuine Appc surface"). "Nothing in the SDK designates breakability, so we detect breaks from the hull volume" (damage_geometry.py:22-26). Appendage severance is the articulation spec's phase 2a (PS:3, `2026-09-23-ship-part-articulation-design.md`). Whether BC itself ever sheds parts mid-combat was **not verified** (the stbc-reference MCP was down).
- Dauntless rules: rigged hulls never structure-sever (PSC.cc:20-24, HB:69-75; CLAUDE.md "Layered hull damage" row); rocks crumble instead (HB:26, 66-68); radius ≤ 0.6 GU never (damage_geometry.py:63); parts ≥ 12 never (PSC.h:73-76); skinned models never (PSJ.cc:36-37); chunks never sever further (PSC.cc:203-207).

---

## 3. The data severance needs and where it comes from

| Datum | Source | GL / renderer? | Cost |
|---|---|---|---|
| Structure segmentation (voxel occupancy, int16 labels, parts) | `voxel::detect_structure_parts(collect_hull_triangles_from_source(source))` (SPC.cc:47-76), keyed by `model->source` (the NIF path, or `"<path>#s=<scale>"` for scaled loads) | **GL-free.** The voxel lib links nif, assets and glm. The cache code lives in `renderer/` but uses only `assets` + `voxel` includes (SPC.cc:13-17) | Detection ~0.3 s per hull at 128 cells (SPC.h:3-5; Debug cost not measured here). `.sps` disk cache: `<cache_dir>/structure_parts/<fnv1a64(NIF bytes)>-v<kStructurePartsVersion>.sps` (SPC.h:8-15, paths.py:532-537). Measured on disk now: **11 files, 519 KB total, largest 107 KB** (`/Users/mward/Documents/Projects/bc_dauntless/cache/structure_parts`). In memory ~3 bytes per voxel (`occ` u8 + `label` i16; volume.h:38, structure_parts.h), ~0.5-1 MB per hull class (**inferred**) |
| Started | `prefetch_structure_parts` at ship realize (HL:6841) and warp preload / hull volume (hull_volume.py:29). Otherwise lazily on the first `structure_segmentation_shared` | no | async, never blocks a frame |
| Mesh fixes | segmentation reads the **raw** NIF (`nif::load`, voxelize.h:73-76), not the mesh-fixed model | — | no change needed |
| Wear store | `scenegraph::HullDamageStore` on the instance (hull_damage.h). GL-free class, renderer-owned object | ownership is the blocker | 64 records |
| Dials | `dauntless_plating::g_params[7]` (reach scale) and `[24]` (deck break) (frame.cc:205-229). Live dev dials (plating_dials.py:37, 54), pushed through `set_plating_params` (BIND:8699-8705). These are "look" dials that **decide gameplay** | renderer global | — |
| Part boxes (A) | `host_io.model_nodes(iid)` → per-node bounds (ART:687-710) | needs a loaded model, so GL today (BIND:923-925) | once per leaf |
| Mount → part (A, B fallback) | `model_nearest_part(model, …)` (PS:154-162), `structure_part_at(iid, …)` (HB:316-322) | loaded model / instance | cached per point |
| Model → GU scale | instance world column length (BIND:10031, 10072) = BC_MODEL_SCALE × `GetScale()` | computable from the sim | — |

**A GL-free model load looks possible.** `AssetCache::Options` has `keep_cpu_data` and injectable `texture_uploader` / `mesh_uploader` (assets/cache.h:38-42), so a CPU-only model (triangles, node tree) can likely be built without a context (**inferred**: not tried). The trace (`ray_trace.cc`) includes only `assets/mesh.h`, `assets/model.h`, glm and `renderer/aabb.h`, so it is CPU code that could move out of `renderer/`.

---

## 4. Random draws in the path

**The decision itself draws nothing.** Not `record_hit`, `wear_for_hit`, `HullDamageStore::add`, `interior_wear_field` or `find_severed_parts` (read: PS:291-340, HW:74-84, PSC.cc). Grep finds no `random`, `rng` or `mt19937` in `hull_damage.cc` or `breach_events.cc`, and none in PS, HB, HW, IB or PDR.

**But the decision's TIMING is not deterministic (B):**
- The job runs on a `std::async` thread and is collected by a per-FRAME poll (HB:84-90, HL:12838). Under steady fire a finished result is **dropped** whenever the store revision moved since it was queued (PSJ.cc:60-72; HB:19-24 says so). The tick a piece leaves on therefore depends on wall-clock thread scheduling and frame rate. The subsystem kill (`SetCondition(0)` + `ET_SUBSYSTEM_DESTROYED`) inherits that.
- The segmentation's async readiness (BIND:10014) and instance existence (§1.1) also decide whether a check runs at all.

**Draws after the decision** (cosmetic intent, but they consume shared streams):
- `debris_chunk.spawn` draws 3 × `rng.uniform` from Python's **global `random`** (DC:131, 150) for the tumble axis. That is the S2 stream the AI's `random.choice` uses (event-inventory.md:229 R8; roadmap decision 12, `2026-11-01-threaded-weapons-combat-roadmap.md:66`). Both mechanisms reach it: HB:177 and PDR:101. The tumble is not purely cosmetic: `_current_angular_velocity` feeds the collision contact-point velocity (DC:62-64). It is small but gameplay.
- On the same hit, before severance: `hull_hit_smoke` (S1, HF:346-348) and `GetRandomSound` behind the wall-clock gate (HF:187-200, 354-355; damage-map H9/H10, lines 254-255).
- After severance: `ET_SUBSYSTEM_DESTROYED` handlers (SDK and missions) may draw S1 (**inferred**). `internal_blast` draws nothing (IB read). `breach_burst` VFX is native (not traced here; **inferred** not a shared stream).

So: no draw decides severance. Severance does move the S2 stream (3 draws per chunk), and its timing moves every later draw.

---

## 5. Tests that cover severance today

**Decision logic, headless:**
- `tests/unit/test_part_severance.py`: attribution, threshold (20% of 4000 → 800), never twice, cannon destroyed, posed attribution, units. Uses `record_hit(ship, None, …)` directly with boxes seeded by tests/conftest.py:1801-1830.
- `tests/unit/test_hull_breakup.py`, `tests/unit/test_hull_breakup_parts.py`: Python orchestration with `host_io.hull_split_parts` / `structure_part_at` **monkeypatched**. Covers spawn per part, mass fraction, kill by label, throttle and drain, polling, articulated never.
- `native/tests/renderer/part_severance_check_test.cc` (36 tests): `find_severed_parts` on synthetic segmentations, `split_severed_parts`, the async staleness rules, rigged and articulated never, the hideable cap. GL-free `World` (renderer test target).
- `native/tests/renderer/structure_parts_cache_test.cc`, `native/tests/voxel/structure_parts_test.cc`, `native/tests/voxel/structure_parts_io_test.cc`: segmentation, `.sps` naming, reading and corruption.

**Through dispatch:**
- `tests/unit/test_hull_wear.py:225-280`: `record_hit` monkeypatched, eligibility forced True, a fake host. Covers "LIGHT phaser records no share" and "a wear failure keeps the share".

**Bindings:** `tests/host/test_hull_damage_bindings.py:134-169`: `hull_split_parts` empty for an intact ship; `structure_part_at` −1 before parts are known; `instance_severed_parts` 0. Real GL-free instances via `_h.create_instance(0)`.

**Differentials:** `tests/helpers/posed_fight.py:165-200` (used by tests/integration/ and tests/host/ `test_native_posed_differential.py`) **calls `part_severance.sever` directly** from an `ET_WEAPON_HIT` handler. It pins the native/Python mount parity after a sever, but it bypasses `record_hit`, eligibility and the trace. `tests/helpers/in_flight.py:33-37` snapshots `hull_breakup` module state.

**No test asserts that headless never severs.** A grep for "never sever", "no sever" and `ship_instances=None` near severance terms finds nothing. Severance is absent headless only because the gates in §1.5 fail. Making it a sim decision therefore breaks no "no severance" assertion. It will change differential and sweep recordings (§6.3).

---

## 6. Recommended design: severance as a sim decision

### 6.1 Principle
Split each mechanism into a **decision** (sim: per-ship state, deterministic, at a fixed point in the tick, no render instance) and its **presentation** (renderer: hide parts, instance a chunk, VFX, emitter silencing). The renderer reads the sim's verdict and never makes one.

### 6.2 What moves where

1. **Hull geometry service, GL-free** (new native lib, or `assets` + `voxel`; the combat lib can link it). Per model source it provides:
   - CPU triangles and node tree via `AssetCache` with CPU-only uploaders (assets/cache.h:38-42; **inferred** feasible);
   - the trace accel and `ray_trace_instance_linear`, moved out of `renderer/` (it is CPU code, §3);
   - node bounds (today's `model_nodes`) and `model_nearest_part`;
   - the structure segmentation: move `structure_parts_cache.cc` from `renderer/` to the voxel lib unchanged (it depends only on assets + voxel).
   
   Keyed by the NIF path Python already resolves (`HL._ship_nif_path`, HL:6053-6073, `FilenameHigh`), loaded at ship creation for every ship that can sever, independent of draw distance. The renderer loads the same CPU model and adds GPU buffers on top. Note this is also what K2/K3 need to trace without `g_world` (k2-beams-map.md:766).
2. **Sim-owned damage state per ship.** Move the `HullDamageStore`, the severed mask and the part-check stamp from `scenegraph::Instance` to a sim object (a native ObjectRow column or a native per-ship struct). Wear points convert to the body frame from the **sim pose** (TransformStore at the tick) instead of the instance's interpolated world matrix. The render instance reads the sim's store by revision (shared pointer or copy on revision change); a chunk copies it as today (PSC.cc:264).
3. **One sim severance step** at a fixed tick point (after damage, before the effect-queue flush):
   - B: the 0.5 s game-time throttle stays. `find_severed_parts` runs synchronously, or on a worker whose result is **joined at a fixed tick** (queue at tick N, block at tick N+k). It must never be dropped or re-polled per frame. That replaces PSJ's revision race with determinism.
   - A: `record_hit` attribution against GL-free boxes, from a sim-pose body point, then the threshold.
   - Both write the per-ship severed set, kill subsystems by label (sim-side `structure_part_at`) or by physical parent, and post `ET_SUBSYSTEM_DESTROYED` through the effect queue (roadmap G).
   - **Decide and fix the death-routing bypass:** route the kill through `DestroySystem`-equivalent logic (critical → death, zero crossing → breach arming), or keep `SetCondition` deliberately and record why.
4. **Make the renderer limits explicit sim rules:** `kMaxHideableParts` = 12, skinned never, rigged never, radius > 0.6 GU, and the dials `params[7]` and `[24]` as sim constants that the renderer also reads, not renderer globals the sim borrows.
5. **Collision and trace follow the verdict.** Today B leaves the collision spheres and trace triangles in place (§2.2). With the verdict sim-side, both A and B can drop them from one place (a design choice: a live behaviour change).
6. **Stays presentation:** `apply_severed_pieces`' chunk instancing (split from the mask write at PSC.cc:267), `part_detach_render`, emitter silencing, `_burst`, VFX. The `DebrisChunk` body stays a sim object because it collides and deals damage, so it should tick in the sim, not on frame dt (HL:12832-12835; the roadmap moves collisions to game time, line 64). Its tumble draw moves to the presentation RNG (roadmap decision 12) or a sim RNG, decided deliberately.

### 6.3 Behaviour change
- **Headless and live agree**: both sever. This is the point.
- **Live is not byte-identical:**
  1. B's severance tick becomes deterministic. Today it varies with worker latency and frame rate (§4), probably by a few frames (**inferred**).
  2. Wear lands at the sim pose, not the interpolated render pose, a small shift (k2-beams-map.md:820 "two clocks of pose").
  3. Ships with no render instance (other frames; ships not yet realized) now sever.
  4. If the death bypass is fixed, a severed critical subsystem kills the ship.
  5. If collision and trace follow the verdict, shots and hulls pass through the gap.
- **Recordings change once:** headless differentials and the 26-mission sweep gain subsystem kills where hulls take enough damage. Any differential that asserted the old outcome is re-recorded, alongside the decision-12 RNG re-record.

### 6.4 Risks
- **Load cost:** a segmentation for every severable ship class at creation, plus a CPU model. With `.sps` cached it is ~50 KB on disk and ~1 MB in memory per class (§3). Without a cache, detection is ~0.3 s per class (SPC.h:4), so on a first launch or in a pytest run under a temp `DAUNTLESS_DATA_DIR` it costs per hull class. Mitigations: prefetch at creation and at warp preload as today, and a persistent dev cache for tests. BC content cannot be committed.
- **Check cost:** a check that finds a broken voxel cost ≥ 8-11 ms on the main thread in Debug (SIG-113, PSJ.h:4-6), which is why it went to a worker. A fixed-tick join keeps that cost on a worker but stalls when the join comes first. Building the check in an always-`-O2` library (the combat lib already does this, native/src/combat/CMakeLists.txt) should cut it (**inferred**, not measured).
- **Mods without `.sps`:** detected on first use and written to the cache, as today. Geometry with no parts (`np < 2`, PSC.cc:64) never severs, also as today. A mod that redirects a NIF must resolve to the same source in the sim and the renderer, or the two disagree.
- **Rigged ships:** they stay on mechanism A. They need GL-free node bounds and nearest-part. The `SetPhysicalParent` path is unchanged. `wear_node_for` (posed attribution) moves with the store and becomes sim-side for rigged hulls too.
- **Eligibility:** A's cap of 6 ships (damage_eligibility.py:22) is a perf gate deciding gameplay. Keep it as a sim rule, or drop it if the native attribution is cheap.
- **Determinism versus threads:** any worker result must be joined at a fixed tick. A result whose inputs moved must be recomputed synchronously at the join, never "next frame".

### 6.5 Size
Large, in four phases. Each phase is shippable alone.
1. **Small:** split the mask write from chunk instancing (PSC.cc:231-272). Move `hull_breakup.drain` into the sim tick with a fixed-tick join. Route kills through the effect queue. Decide the death-routing question. Renderer-dependent still, but deterministic.
2. **Medium:** sim-owned `HullDamageStore` + severed mask + sim-pose body conversion. The renderer mirrors them.
3. **Large, the critical path:** the GL-free hull geometry service (CPU model, trace, node bounds, segmentation out of `renderer/`). It unblocks headless mesh-tier hits, and therefore headless wear and severance. K2/K3's native trace wants it too.
4. **Medium:** port A's attribution and threshold, and B's step, into the combat library as part of workstream D. Re-record the differentials and the sweep.

Without phase 3 headless still cannot sever, because both mechanisms are gated upstream on the mesh normal (§1.1).
