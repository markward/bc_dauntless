# Radius / scale audit: making `GetRadius()` the scaled world radius

**Status:** reading notes, 2026-11-03. Nothing was built, run or changed. Prerequisite for the phase 1 size-rule task (BC's size rule; Task 7 in their plan since the ghost fix took Task 6) and phase 3a of `docs/superpowers/specs/2026-11-03-native-motion-and-proximity-design.md`. Design: `docs/superpowers/specs/2026-11-03-scaled-getradius-design.md`.

**Sources and their state**
- **Code** = branch `project/combat_threading` at `2369cba41`. Line numbers are from that commit. Re-checked against `0b55cda86` (the base of `ws/scaled-getradius`) in §10, which lists what moved.
- **SDK** = BC SDK v1.1 scripts at the configured SDK root. Paths below are relative to `sdk/Build/scripts/`.
- **Reference** = `/Users/mward/Documents/Projects/stbc_reference/spec/` (read directly; its MCP server was down).
- **Live captures** = `docs/reference/instrumented_experiments/2026-05-15-hardpoint-scale-investigation.md`: `GetRadius()` logged inside the original `stbc.exe`.
- **Golden fights** live on `ws/native-default` (`aae2cdaa2`: `tests/helpers/golden_fight.py`, `tests/integration/test_golden_fights.py`). They are not in `2369cba41`. Read there.

Facts carry file:line. Anything else is marked **inferred** or **derived**.

Classes used throughout:
- **DRAWN**: wants the world (drawn) size. Scaling fixes it, or is neutral for it.
- **BASE**: wants the unscaled model-space value. It must move to a new base accessor (`GetBaseRadius()` below).
- **DOUBLE**: already multiplies by scale itself or through a helper. It would double-scale.
- **NEUTRAL**: the receiver's scale is 1 in every stock path, so either accessor gives the same answer. The row says which one to keep.
- **N/A**: the receiver is another class with its own `GetRadius` (subsystem, property, event, ProximityCheck, DebrisChunk).
- **INERT**: the value reaches nothing (a stub, or a code path our engine replaces).

---

## 1. Answers in brief

1. **Calls.** Engine `ObjectClass` `GetRadius()` reads split into DRAWN 32, BASE 12, DOUBLE 3 direct (+15 through two helpers) and NEUTRAL 11; N/A 12. The SDK's 72 lines are DRAWN 47, NEUTRAL 12, N/A 3, INERT 8, comments 2. **No SDK call wants the base.** §3, Annexes A and B.
2. **Scale multipliers.** Four helpers multiply radius by scale: `collisions.world_radius`, `rocks.rock.effective_radius`, `planet.aggregate_suns_for_renderer`, and the planet realise `natural_scale` ×2. Every other `GetScale()` use scales a non-radius quantity: hull box, render matrix, body points, hull pieces. Those stay. §5, Annex C.
3. **Native.** The mirror carries the raw `_radius` and `_scale`. Every native radius reader already applies the scale itself (`beam_geometry.cc:173`, `sensor_detect.cc:433`), **except K4** (`k4_eligibility.cc:86-104`). K4 reads the bare `_radius` as the twin of `damage_eligibility._radius`, which is `GetRadius()`. K4 is the one kernel that must change. No renderer or collision C++ reads the mirror. §7, Annex D.
4. **Writers.** Every write to an `ObjectClass` `_radius` goes through `SetRadius` or `__init__`, and every one means a **base** value (§6). **BC has no `ObjectClass.SetRadius`.** `App.py` binds `SetRadius` only on `ProximityCheck` (`App.py:6158`), `SubsystemProperty` (`:9147`) and `BlinkingLightProperty` (`:9965`). The SDK never calls `SetRadius` on an object. So ours is engine-internal, and it can be defined as setting the base.
5. **Bounding radius.** BC's value is the merged world bound **sphere**. Ours is the AABB corner distance from the origin. Merging the NIF's stored per-shape spheres up the node tree reproduces BC's live Galaxy value **exactly** (4.366) and the Sovereign to −1.6% (**derived**). The two rules differ by −28% to +64% across 39 stock models (FedStarbase 296.4 vs 181.1). **This is a second behaviour change. It is recorded as a decision (D1), not adopted; Mark ruled (a) on 2026-11-03, keeping the corner rule on this branch.** §2.3.
6. **Behaviour changes.** Only objects whose scale isn't 1 change: E1M2/E2M1/Multi1/Multi6 rocks, the docking player, promoted field rocks, and the far-tier test rock. Collisions, avoidance, zoom fit and sensor occlusion already use the scaled value, so they do not change. Intercept, warp-path obstacles, line queries, reticle, range readout, damage eligibility, in-system warp stand-off, tractor stand-off and SDK explosion sizes now see the drawn size. Golden fights should be **byte-identical**, because no golden scene calls `SetScale`. §8.

---

## 2. What BC does (reference, SDK, live captures)

### 2.1 GetRadius is the world bound, with scale

- **Stated** (`spec/CameraModes.md` §3.1, lines 108-121): every size-scaling site reads the object's virtual at `+0xe4` (`0x00419960`). That virtual forwards to the scene node's **world bound** (a sphere) and reads its radius at `+0x0c`. It is "the NIF model's bounding-sphere radius in world units, with world scale applied — exactly the value the published `ObjectClass_GetRadius` returns to script. Not a bounding-box extent".
- **Stated** (`spec/ObjectClass.md:447`): `GetRadius(obj)` is `obj->(+0xe4)()`, then the float at `+0x0c`. The wrapper `ObjectClass_GetRadius 0x005F4F20` is graded BE (`:493`).
- **Derived from the SDK** (`AI/Compound/DockWithStarbase.py:47-50`): `if pShip.GetRadius() > 4.0: pShip.SetScale(pShip.GetScale() * 4.0 / pShip.GetRadius())`. With a scaled GetRadius, the new scale is `s·4/(b·s) = 4/b`, so the world radius becomes exactly 4.0, however often it runs. With ours unscaled it gives `4s/b`. The script is only correct under BC's reading.

### 2.2 SetRadius

- `ObjectClass`'s published roster (`spec/ObjectClass.md` "Published entries", 25 entries) has `GetRadius` and **no `SetRadius`**. `App.py:3920` binds `ObjectClass.GetRadius` only.
- The SDK's `.SetRadius(` calls go to `ProximityCheck` (`MissionLib.py:216`, `ConditionInRange.py:102`, `:214`, E6M3, E6M5) and to hardpoint properties. None goes to an object.
- `Planet_Create(radius, name)` (`spec/Planet.md:37-43`) passes the radius into the constructor, which is an SEH wall, not reconstructed. How BC turns that radius into the planet's node scale is **not stated**. Ours: `render_scale = GetRadius() / NIF bound radius` (`host_loop.py:6528-6545`; `docs/reference/instrumented_experiments/2026-07-07-planet-render-scale.md`).
- **Conclusion:** our `ObjectClass.SetRadius` is engine surface, with no BC twin to match. Every engine caller writes a base (§6). It is defined as "set the unscaled base radius", and the name stays (renaming 44 call sites buys nothing).

### 2.3 Sphere vs box: the second behaviour difference (decision D1)

**What the reference gives:** the world bound is a sphere (§2.1). It does not describe how Gamebryo builds that sphere. Neither `stbc_reference/spec` nor `model` mentions `NiBound`, `UpdateWorldBound` or a merge rule (full-repo grep).

**What we compute** (`host_loop.py:6495-6501`, `_seed_ship_radius` `:6549-6568`): for ships, `(|c| + |h|) × BC_MODEL_SCALE` of the model AABB. That is the corner distance from the model origin, an upper bound on any vertex's distance from the origin. Rocks get the largest half-extent (`_model_sphere_radius_from_aabb`). Planets get the SDK radius.

**Derivation** (scratch scripts, not committed; inputs are stock NIFs read with `build/native/tools/dump_nif_tree` plus a NiAVObject transform reader):
- Each `NiTriShapeData` stores a bounding sphere (`native/src/nif/src/blocks/ni_tri_shape.cc:86`).
- Transform each sphere through its node chain, then merge children bottom-up in child order with the smallest-enclosing-sphere rule. That merge rule is **inferred** to be Gamebryo's.
- Compare with BC's logged live `GetRadius()` (scale 1):

| Ship | BC live `GetRadius()` | Merged stored spheres (**derived**) | Ours (AABB corner) | Ours / BC |
|---|---|---|---|---|
| Galaxy | 4.366 | **4.366** | 4.033 | 0.924 |
| Sovereign | 3.929 | 3.866 (−1.6%) | 3.906 | 0.994 |

The Galaxy match to four figures is strong evidence for the merged-sphere model. The Sovereign residual is unexplained. Candidates: the merge order or rule, or something attached to the live ship's node that the file lacks (**inferred**). Two data points are not a proof.

Across all 39 stock high-LOD models (GU at scale 1; "merged" is the derivation above):

| Model | Ours | Merged | Merged / ours |
|---|---|---|---|
| FedStarbase | 296.412 | 181.060 | 0.61 |
| CardStarbase | 37.775 | 27.848 | 0.74 |
| CardOutpost | 15.694 | 12.309 | 0.78 |
| FedOutpost | 17.508 | 13.981 | 0.80 |
| SpaceFacility | 16.232 | 12.839 | 0.79 |
| CardStation | 25.708 | 25.062 | 0.97 |
| DryDock | 9.001 | 12.176 | 1.35 |
| CommArray | 18.330 | 13.016 | 0.71 |
| CommLight | 1.958 | 1.553 | 0.79 |
| Sunbuster | 12.763 | 9.819 | 0.77 |
| KessokMissile_high | 2.797 | 2.085 | 0.75 |
| Akira | 3.131 | 3.081 | 0.98 |
| Ambassador | 3.429 | 3.254 | 0.95 |
| BirdOfPrey | 1.652 | 1.491 | 0.90 |
| CardFreighter | 2.092 | 2.015 | 0.96 |
| CardHybrid | 6.473 | 4.802 | 0.74 |
| Freighter | 2.074 | 1.873 | 0.90 |
| Galaxy | 4.033 | 4.366 | 1.08 |
| Galor | 2.727 | 1.874 | 0.69 |
| Keldon | 3.643 | 2.593 | 0.71 |
| KessokHeavy | 8.808 | 8.474 | 0.96 |
| KessokLight | 3.681 | 3.076 | 0.84 |
| Marauder | 2.868 | 2.679 | 0.93 |
| Nebula | 3.048 | 3.142 | 1.03 |
| Shuttle | 0.163 | 0.150 | 0.92 |
| Sovereign | 3.906 | 3.866 | 0.99 |
| Transport | 3.367 | 2.451 | 0.73 |
| Vorcha | 4.368 | 3.322 | 0.76 |
| Warbird | 8.179 | 7.486 | 0.92 |
| lifeboat | 0.117 | 0.078 | 0.67 |
| Probe / Probe2 | 0.019 / 0.045 | 0.018 / 0.041 | 0.95 / 0.91 |
| asteroid / 1 / 2 / 3 | 1.212 / 0.298 / 0.858 / 6.204 | 0.741 / 0.232 / 0.547 / 4.732 | (rocks are seeded from max-half: 0.722 / 0.186 / 0.537 / 4.703) |

**Readings:**
- Ours over-states most hulls by 5-30%, and stations by up to 64% (FedStarbase). It under-states the Galaxy (−8%) and the DryDock (−26%).
- For rocks, our max-half rule is within 3% of the merged sphere for asteroid/asteroid2/3. It is 20% under for asteroid1 (0.186 vs 0.232).
- An earlier comment (`engine/cameras/__init__.py:116`) says "our GetRadius() is within 10% of BC's merged NiBound … Galaxy 4.03 vs 4.46". The live capture says 4.366, not 4.46, and the table shows the 10% claim does not hold across the fleet.

**Not adopted here.** Switching the seed rule changes every hull's radius. That moves chase distances, splash radii (`loadspacehelper.py:100`), Intercept's `> 150` avoid gate (`AI/PlainAI/Intercept.py:286`; FedStarbase stays above it), collision bodies and avoidance. It is a separate ruling. See the design's D1.

---

## 3. SDK `GetRadius()` calls (72 lines, 34 files)

Every SDK `GetRadius()` call on an object wants the drawn size, which is what BC hands it (§2.1). The table says what changes for us when the receiver is scaled. "Scale 1" means the receiver is never scaled by any SDK or engine path (§5.3).

| File:line | Receiver | Class | Effect of the change |
|---|---|---|---|
| `Effects.py:573, 611, 660` | `WeaponHitEvent` | N/A | none |
| `Effects.py:710, 787, 792, 797, 801` | dying object (ship or rock) | DRAWN | debris/explosion size follows a scaled object |
| `loadspacehelper.py:100` | new ship | DRAWN | splash radius at `CreateShip`. Scale 1 then (SetScale comes after CreateShip in every SDK caller) |
| `MissionLib.py:4971` | warp-path obstacle | DRAWN | **scaled rocks are now obstacles at their drawn size** (`GrabWarpObstaclesFromSet`) |
| `WarpSequence.py:168, 629` | warping ship | DRAWN | scale 1 except while docking |
| `Maelstrom/Episode7/E7M1/E7M1.py:1402, 1410, 1718` | ship / freighter | DRAWN | scale 1 |
| `…/E6M2/E6M2.py:2537` | ship | DRAWN | scale 1 |
| `…/E6M5/E6M5.py:491` | object | DRAWN | scale 1 |
| `…/E6M4/E6M4.py:439, 441` | planet | NEUTRAL | scale 1 |
| `…/E1M2/E1M2.py:2044-2047` | planet Haven | NEUTRAL | scale 1 |
| `…/E1M2/E1M2.py:3114` | dying object (`CreateDebrisExplosion`) | DRAWN | final explosion follows a scaled rock |
| `…/E1M2/E1M2.py:3359` | `AreObjectsHeadingTowardTarget` target: Facility / Haven (`:3322`, `:3326`) | NEUTRAL | scale 1 |
| `…/E4M5/E4M5.py:297` | shipyard | DRAWN | scale 1 |
| `…/E3M2/E3M2.py:832, 876` | probe / object | DRAWN | scale 1 |
| `…/E2M1/E2M1.py:678` | planet | NEUTRAL | scale 1 |
| `…/E2M6/E2M6.py:538` | ship | DRAWN | scale 1 |
| `…/E5M4/E5M4.py:981` | player, into `IsLocationEmptyTG` | INERT | `SetClass.IsLocationEmptyTG` is a stub returning 1 (`engine/appc/sets.py:357-359`) |
| `Tactical/LensFlares.py:79` | sun | NEUTRAL | scale 1 |
| `AI/Preprocessors.py:1741, 1780, 1811, 1876` | AvoidObstacles ship / obstacles | INERT (replaced) | the engine's AvoidObstacles node overrides `TestCourseOverride` with `collision_avoidance.course_override_for` (`engine/appc/ai_optimized.py:262-269`), which already uses scaled `world_radius`. That these SDK lines run only under `TestCourseOverride` is **inferred** |
| `AI/Compound/DockWithStarbase.py:47, 50` | docking player | DRAWN | **fixed**: gate and shrink now match BC (§2.1) |
| `AI/Compound/DockWithStarbase.py:103` | object, into `IsLocationEmptyTG` | INERT | stub |
| `AI/PlainAI/Intercept.py:157, 168, 180` | intercept target | DRAWN | **stand-off from a scaled target's drawn surface.** E1M2's intercept tutorial targets the scaled asteroid fragments (`E1M2.py:1815-1818`) |
| `AI/PlainAI/Intercept.py:201, 264` | own ship | DRAWN | scale 1 except while docking |
| `AI/PlainAI/Intercept.py:283` | planet | NEUTRAL | scale 1 |
| `AI/PlainAI/Intercept.py:286, 289` | ShipClass obstacle with radius > 150 | DRAWN | E1M2's largest rock: asteroid3 base 4.703 × 8.5 ≈ 40 GU, still below 150 (**derived**). No change in stock |
| `AI/PlainAI/Warp.py:400` | own ship | DRAWN | scale 1 except while docking |
| `AI/PlainAI/FollowThroughWarp.py:182, 202, 224` | object / ship | DRAWN | follows a scaled leader / target |
| `AI/Player/Defense.py:6`, `DestroyFreelyClose.py:6, 16`, `DisableForeClose.py:6`, `DestroyForeClose.py:6`, `DisableFreelyClose.py:6`, `DisableFreely.py:6`, `DestroyFreely.py:5, 16` | target / own ship | DRAWN | weapon-range margins grow against a scaled target (a rock attacked under player AI) |
| `AI/Player/OrbitPlanet.py:32, 52` | planet | NEUTRAL | scale 1 |
| `Conditions/ConditionInRange.py:102, 202, 214` | `pObject1` | DRAWN | trigger range = distance + drawn radius. Stock missions use ships or planets as object 1 (scale 1). **Inferred** from the E1M2 read: not every mission was checked |
| `Actions/EffectScriptActions.py:86` | warping ship | DRAWN | warp flash size (`warp_in_flash.WarpFlash_CreateWithoutShip`). Scale 1 except while docking |
| `Systems/Multi1/Multi1.py:110`, `Systems/Multi6/Multi6_S.py:71` | — | — | comments |
| `Systems/Multi1/Multi1.py:131`, `Systems/Multi6/Multi6_S.py:92` | scaled asteroid, into `IsLocationEmptyTG` | INERT | stub |
| `QuickBattle/QuickBattle.py:2804` | player + ship | DRAWN | scale 1 |
| `Multiplayer/Episode/Mission5/Mission5.py:1453` | starbase | DRAWN | scale 1 |

Counts (lines): DRAWN 47, NEUTRAL 12, N/A 3, INERT 8 (4 `IsLocationEmptyTG` stub reads, 4 replaced AvoidObstacles lines), comments 2. Total 72. **No BASE.**

Stub heatmap (`docs/stub_heatmap.md`, 792 runs to 2026-10-14): none of `ObjectClass` `GetRadius` / `SetScale` / `GetScale` appears. `WarpFlash_CreateWithoutShip` is listed (rank 116), but it has since been implemented (`engine/appc/warp_in_flash.py:75`). `IsLocationEmptyTG` was confirmed a stub by reading (`sets.py:357-359`).

---

## 4. Engine `GetRadius()` calls

The full per-call tables are Annex A (`engine/appc/`, `App.py`, `tools/`) and Annex B (the rest of `engine/`). Counts, recounted from the table rows:

| Class | appc (Annex A) | rest of engine (Annex B) | Total |
|---|---|---|---|
| DRAWN | 15 | 17 | 32 |
| BASE | 0 | 12 (3 must change, 7 seed guards, 2 base-in-practice) | 12 |
| DOUBLE (direct) | 2 (`collisions.world_radius`, `planet.aggregate_suns_for_renderer`) | 1 (`rocks.rock.effective_radius`) | 3 |
| NEUTRAL | 4 | 7 | 11 |
| N/A | 9 (+2 tools; +5 BC-side probes) | 3 | 12 |

Plus 15 call sites that reach the DOUBLE helpers (13 through `world_radius`, 2 through `effective_radius`). These are fixed in the helper, with no per-site edit (Annex A §2). No ObjectClass `_radius` / `_scale` is read directly anywhere outside `objects.py`'s own accessors (Annexes A §3, B §D).

**BASE sites that must change** (otherwise they double-scale):
- `host_loop.py:7168` and `:8484`: planet render scale `GetRadius() / sphere_radius`, which `_apply_live_world_transform` multiplies by `GetScale()` again. Latent: no planet is ever scaled.
- `ui/spv_decals_pane.py:320`: divides by `BC_MODEL_SCALE` to get NIF body units.

**BASE by pairing** (sign tests that read then seed; scale-invariant for scale > 0, but they read the quantity they write): `host_loop.py:6561`, `:7163`, `:8311`, `:8479`, `dev_missions/felix_destroy.py:88`, `dev_missions/combat_stress.py:232`, `:255`.

**BASE in practice:**
- `ui/phaser_overlay.py:186`: the SPV mount frame is unscaled.
- `systems/apply_map.py:195`: a read-then-`SetRadius` that keeps a sun's atmosphere ratio.

**DRAWN reads that change value for scaled objects** (the behaviour list in §8):
- `ships.py:812` in-system warp stand-off;
- `tractor.py:60-61` stand-off;
- `planet.py:457` line-query reach;
- `perception.py:261` range readout;
- `damage_eligibility.py:32` (with K4, §7);
- `objects.py:399` random point fallback, `:779` `LineCollides`;
- `ui/reticle_text.py:76` and `ui/target_reticle.py:100` reticle (today under-sized for scaled rocks);
- `host_loop.py:7503` chase-camera reseed (re-seeds on the docking shrink and restore);
- `quickbattle/late_arrivals.py:270` spacing.

---

## 5. Sites that multiply by scale

Full table: Annex C §A.

### 5.1 Radius × scale (these become the new `GetRadius()` or read the base)

| Helper | Today | Becomes | Callers |
|---|---|---|---|
| `collisions.world_radius` (`collisions.py:117-143`) | `GetRadius() × GetScale()`, guarded: scale ≤ 0 or non-finite → base. DebrisChunk → its own `GetRadius()` | For an ObjectClass, `GetRadius()` (which takes the same guard, D2). DebrisChunk and other duck types are unchanged | 15 Python sites + K2/K3 identity lists (`native_combat.py:4717`, `:5801`). Native twin `beam_geometry.cc:173`, unchanged |
| `rocks.rock.effective_radius` (`rock.py:60-70`) | base = `GetRadius()`, else hull radius; `× GetScale()` | base = `GetBaseRadius()`, else hull radius; `× GetScale()` (the hull radius is unscaled, so the base form is the only one that keeps the fallback right) | 5 sites; native twin `sensor_detect.cc:433`, unchanged |
| `planet.aggregate_suns_for_renderer` (`planet.py:169-207`) | `radius × scale`, `corona × scale` | `GetBaseRadius() × scale`. **`planet.py` is owned by the proximity project → request (design §7)**. Latent: no sun is scaled | renderer sun feed |
| planet realise `natural_scale` (`host_loop.py:7167`, `:8483`) | `GetRadius() / sphere_radius`, then × `GetScale()` at draw | `GetBaseRadius() / sphere_radius` | render transform |
| `camera_modes._target_radius` | rides on the two helpers | no edit | 9 sites (zoom fit, tracking, director) |

### 5.2 Scale × a non-radius quantity (unchanged)

`combat._hull_box_for` (7 callers), `hull_bounds.hull_spheres_world` / `hull_spheres_near` / `bound_radius`, the render matrices (`_ship_world_matrix`, `_apply_live_world_transform`, `_sync_instance_transforms` ×2, `part_detach_render._copy_render_state`), `debris_chunk.spawn`, `subsystems.body_point_world`, `manual_aim.update`, `hull_breakup._ship_scale`, `spv_decals_pane.instance_scale`, and `sim_restore` (copies the scale). Native: `beam_geometry.cc:223`, `damage.cc:411`, `projectile_geometry.cc:149`, `weapon_geometry.cc:280`.

### 5.3 Who is ever scaled

- **SDK:**
  - rocks: `E1M2.py:1110` (Debris1-6, ×3), `:3027` (asteroids, per-asteroid scale), `E2M1.py:481`, `Multi1.py:108`, `Multi6_S.py:69`;
  - **the player**: `DockWithStarbase.py:50` (shrink), `:235` (restore);
  - `Cebalrai1_S.py:69` and `Belaruz4_S.py:45` are comments.
- **Engine:** `rocks/rock.py:208` (promoted field rocks, `radius_gu / r_q` ≈ 1 ± 5%), `dev_missions/far_tier_field.py:57`, `quickbattle/sim_restore.py:325` (re-applies a recorded scale).
- **Never scaled:** planets, suns, torpedoes.

---

## 6. Writers of `_radius`, and what `SetRadius` means

Full table: Annex C §B. Every write goes through `ObjectClass.__init__` (`objects.py:96`, 0.0) or `ObjectClass.SetRadius` (`objects.py:213-214`). There are no direct writes.

| Writer | Value | Intent |
|---|---|---|
| `_seed_ship_radius` (`host_loop.py:6549-6568`), also via QB `set_radius_fn` and the warp-in seeder | AABB corner (ship) or max half-extent (rock) × `BC_MODEL_SCALE` | base |
| planet realise fallback (`host_loop.py:7165`, `:8481`) | `extent × BC_MODEL_SCALE` | base (= world at scale 1) |
| `Planet.__init__` via `Planet_Create` / `Sun_Create` (`planet.py:27`) | SDK radius | base (= world at scale 1) |
| `apply_map.apply_to_set:229`, `_rescale_sun:198`, `Sun_Create:241-249` | map `radius_gu` | world, = base because bodies are never scaled |
| `RockClass_Create` (`rock.py:195`) | quantised `r_q`, before any `SetScale(radius_gu / r_q)` (`:208`) | base |
| `felix_destroy.py:89`, `combat_stress.py:233`, `:256` | 4.0 nominal (headless) | base |
| Torpedo `_radius` property (`projectiles.py:307-318`) | only `__init__` 0.0 | base |

- No writer computes a radius from `GetRadius()`, so nothing compounds.
- Writers that run after an SDK `SetScale` write a base value, which is what they mean.
- **SetRadius afterwards:** it sets the unscaled base radius, and `GetRadius()` returns base × scale. `SetRadius(r); GetRadius()` returns `r × s` on a scaled object. No SDK script does that (§2.2).
- **ProximityCheck** overrides `GetRadius` and `SetRadius` to its trigger radius (`ai.py:1267-1274`). Inheriting `GetBaseRadius()` would return its unused `_radius` (0.0), so it overrides `GetBaseRadius` too (design §3).

---

## 7. Native

Full table: Annex D.
- `_radius` / `_scale` are pushed raw by attribute name (`NativeField.__set__`, `native_combat.py:651-677`; `mirror.cc:33-34`; `ObjectRow` `mirror.h:198`). **Keep pushing the base.**
  - Pushing a scaled radius would lose `world_radius`'s bad-scale fallback and `effective_radius`'s hull fallback.
  - It would break `test_native_combat_mirror.py:134-137` and `test_native_deferred_frees.py:230-245`, which pin row = attributes.
- **K4** (`k4_eligibility.cc:86-89`, `:104`): its finite check, `max_r` and size term read the bare `r->_radius`. Twin: `damage_eligibility._radius` = `float(ship.GetRadius())`. It becomes `world_radius(m, h)` (given D2's guard), with the finite check on that value.
  - `test_native_k4_eligibility.py` and `native/tests/combat/k4_eligibility_test.cc` never call `SetScale`, so they pass either way. Scale cases must be added.
- Everything else is already base × scale in C++ and unchanged: `world_radius`, `bubble_bound_radius`, the K2 sphere tier, the K3 sphere test and back-off, and `effective_radius`. Its Python twins move to the base accessor.
- Guard lists: a Python twin that calls `GetBaseRadius` must have it in `_K2_OBJECT_NAMES` (`native_combat.py:4731`) and `_STEP_SHIP_PATCHES` (`:5509`). Otherwise a patched base accessor no longer sends the step to Python (**inferred** from the guard design).
- Outside `native/src/combat`, nothing reads the mirror. The reticle (`target_reticle_pass.cc:153`) and the dust planet feed get `GetRadius()` from Python and become scaled automatically.
- Test-side DOUBLE: `tests/host/test_native_k3_differential.py:196`, `:221` compute `GetRadius() * GetScale()`. Harmless at scale 1, but they should read `GetRadius()`.

---

## 8. What changes, and which tests see it

Only objects with scale ≠ 1 change (§5.3). Headless, an SDK hardpoint rock has `GetRadius() == 0`, because `HullProperty.SetRadius` sets only the hull (`rock.py:61-65`), and the host seeds it only at realise. **So headless runs see almost none of the rock changes. They are live-only.**

| Behaviour | Changes? | Why |
|---|---|---|
| Collisions (body radius, contact, piece cull) | no | already `world_radius` |
| AI personal space / AvoidObstacles | no | engine scan already uses `world_radius` (§3) |
| Zoom fit (Z + viewscreen) | no | `_target_radius` → `effective_radius` / `world_radius`. `tests/integration/test_e1m2_target_zoom_fit.py` should stay green unchanged |
| Sensor occlusion by rocks | no | `effective_radius` (Python + `sensor_detect.cc`) |
| E1M2 Intercept tutorial | **yes (live)** | `Intercept.py:157-180` stands off a scaled fragment's drawn surface, not its model radius |
| Warp-path obstacles | **yes (live)** | `MissionLib.py:4971`: a scaled rock is a bigger obstacle. The own-ship radius (`Warp.py:400`) changes only while docking |
| Line queries (FireScript occlusion, Intercept, ConditionInLineOfSight) | **yes (live)** | `planet.py:457` reach |
| Target reticle box, range readout | **yes (live), a fix** | `reticle_text.py:76`, `target_reticle.py:100`, `perception.py:261` |
| Damage eligibility ranking | **yes** for scaled ships/rocks in the combat list | `damage_eligibility.py:32` + K4 |
| In-system warp / Intercept-warp stand-off to a rock | **yes (live)** | `ships.py:812` |
| Tractor stand-off on a scaled rock | **yes (live)** | `tractor.py:60-61` |
| Rock and ship death explosions (SDK `Effects`, E1M2:3114) | **yes (live)**, visual | DRAWN size |
| Docking (DockWithStarbase) | small | Shrink = BC (exactly 4.0 GU world). Same as today on the first dock at scale 1. Chase camera re-seeds on shrink and restore (`host_loop.py:7503`; probably invisible under the cinematic, **inferred**). Clear-out is a 300 GU `GetNearObjects` plus the inert `IsLocationEmptyTG`: unchanged |
| Promoted field rocks | small | `GetRadius()` = exact `radius_gu`, not the 2-figure `r_q` |
| Proximity line query (phase 1) | yes, intended | reach reads `GetRadius()`. The size-rule task's near rule will see the scaled value with no edit there |
| ProximityCheck firing | no | `proximity_table` measures centre distance; `SetIgnoreObjectSize` is stored, unused (side finding) |

**Tests**
- **Golden fights** (`ws/native-default`): every scene is `combat_stress` or the K1 ops scenes, with radii set by hand and **no `SetScale`** (`golden_fight.py:466-470`, `posed_fight.py:255`, `combat_stress.py:233`, `:256`). With D2's guard and scale 1.0, `r * 1.0 == r` exactly. **Expected: byte-identical. That is the falsifier.** If one moves, find out why before re-recording.
- **Must be rewritten on purpose:** `tests/unit/test_collision_radius_scale.py:47-56` `test_get_radius_stays_unscaled_and_effective_radius_scales_once`. It is a guard against exactly this change.
- **Stay green, and pin the helpers through the change:**
  - `tests/integration/test_native_can_detect_differential.py:295` `test_rock_field_sweep` (E1M2's six ×3 rocks, the only real-mission scaled scene);
  - `tests/host/test_native_beam_trace.py:283`;
  - `tests/unit/test_native_beam_geometry.py:519`;
  - `tests/unit/test_native_projectile_geometry.py:276`;
  - `tests/unit/test_camera_modes.py` (scaled rocks, `:1264-1280`);
  - `tests/unit/test_rock_death.py:515-540`;
  - `tests/unit/test_rock_create.py`;
  - `tests/unit/test_hull_bounds.py:94-100` (the DockWithStarbase shrink);
  - `tests/integration/test_collision_avoidance.py:680-702`;
  - `tests/unit/test_native_combat_mirror.py`;
  - `tests/unit/test_physics_object.py:119-123`.
- **Need new cases:** K4 with `SetScale` (Python + C++); `GetRadius` = base × scale with the guard; `GetBaseRadius`; the ProximityCheck override.
- **Campaign sweep** (26 missions, headless): expected unchanged. Headless rocks have base 0 and nothing else is scaled. Run it because the brief requires it for a behaviour change, not because it can see the rock changes.

---

## 9. Notes on the annexes

- The four annexes were produced by parallel read-only passes over the same commit, and are kept as written apart from headings.
- Their own count lines are superseded by §4's recount. Annex A's "27 code calls" counts 30 rows. Annex B's "9 BASE / 8 NEUTRAL" counts 12 and 7 rows.
- Annex D's "no golden fight files" is about `2369cba41` only: the goldens are on `ws/native-default`.
- Docstrings and comments that go stale are listed in Annex A §4, Annex B §B and Annex C conflict C8.

---

## 10. Re-check against the branch base `0b55cda86` (2026-11-03)

`project/combat_threading` merged into main (`7d3d9e5e9`), and `project/native-motion-and-proximity` forked from it; `0b55cda86` adds phase 0 profiler rows. All of this was compared file by file against the `2369cba41` snapshot.

**One new native consumer: the tractor stand-off.**
- The tractor force now runs only in C++ (`native/src/combat/src/tractor_force.cc`, "a port of engine/appc/tractor.py as it stood at 23b3845d5"). `engine/appc/tractor.py` keeps the constants and calls `native_combat.tractor_force_step`.
- So the two DRAWN rows `tractor.py:60-61` (Annex A, §4) are gone from Python. Their C++ form, `Step::standoff` (`tractor_force.cc:74-78`), reads the bare base: `source.row->_radius + target.row->_radius + TRACTOR_STANDOFF_MARGIN_GU`.
- It must change with the flip, to `world_radius` on both bodies, or a towed scaled rock keeps the unscaled gap. The design's §5 and plan Task 2 now cover it.
- That makes the native readers of the bare base two: K4 and the tractor. Every other `_radius`/`_scale` read in `native/src` is unchanged since the snapshot.

**Counts.** Engine `GetRadius()` reads: 129 → 127 (only the two tractor rows went). Engine `GetScale()` reads: 47 → 47. SDK: unchanged.

**Files the plan touches.**
- Byte-identical to the snapshot: `collisions.py`, `rocks/rock.py`, `spv_decals_pane.py`, `phaser_overlay.py`, `apply_map.py`, `felix_destroy.py`, `combat_stress.py`, `cameras/__init__.py`, `k4_eligibility.cc`, `sensor_detect.cc`, and the test files the plan names.
- Changed, but not in anything radius-related: `objects.py` (adds `_mass`), `damage_eligibility.py` and `beam_geometry.cc` (the switch rename and the aim-offset change from "fire control native only"), `projectile_geometry.cc`.
- Shifted: `host_loop.py` by −42 lines throughout (for example 6561 → 6519, 7163 → 7121, 7167 → 7126, 8311 → 8269, 8479 → 8437, 8483 → 8442, 7625 → 7583); `native_combat.py` `_K2_OBJECT_NAMES` 4731 → 4641 and `_STEP_SHIP_PATCHES` 5509 → 5419; `planet.py` `aggregate_suns_for_renderer` 169 → 147, `GetLineIntersectObjects`'s reach 457 → 470, `_is_proximity_participant` 245 → 246; `projectile_geometry.cc`'s stale `combat.py:916` comment 133 → 132.
- The line numbers in §1–§9 and the annexes are still the snapshot's. The design and plan carry the current ones.

**Golden fights.** `tests/integration/test_golden_fights.py` is on the branch base now, so Annex D's "not in `2369cba41`" no longer applies.

## 11. Outcome (2026-11-03)

- Commits on `ws/scaled-getradius`:
  - `a1e307f06` + `5811d1b36`: refactor. `GetBaseRadius` added; the base readers and the radius × scale helpers read it. No behaviour change.
  - `f9543f8c8`: the behaviour change. `GetRadius()` is base × guarded scale. K4 and the tractor stand-off use `world_radius`.
  - `f3ec124a5`: `world_radius` is `GetRadius()`; stale prose rewritten.
- Golden fights byte-identical: yes (no re-record).
- Sweep: `tests/integration/test_golden_fights.py` + `test_warp_button_handler_sweep.py` + `test_campaign_warp_transitions.py`: 44 passed.
- Focused tests at `f3ec124a5`: 779 pytest passed; ctest `-R combat_` 354/354.
- Tractor stand-off test geometry: the target sits 10 GU from the source. The plan's 33 GU never engaged the stand-off, so it could not fail.
- D1 (merged bounding sphere): ruled (a) by Mark 2026-11-03, not on this branch.
- Live check: **verified by Mark 2026-11-04** ("I am seeing the changes you described"), at 41f1f55bf.

## Annex A. Engine `GetRadius()` calls in `engine/appc/`, `App.py`, `tools/`


Snapshot: `project/combat_threading` @ `2369cba41`. Read-only.

Legend: **DRAWN** = wants world size (scaling fixes or is neutral); **BASE** = needs the unscaled base (`GetBaseRadius()`);
**DOUBLE** = already multiplies by scale (directly or via helper), would double-scale; **NEUTRAL** = receiver's scale is 1 in
practice; **N/A** = receiver is a different class with its own GetRadius.

Which objects actually have `_scale != 1` (engine writers of `SetScale`, `grep -rn 'SetScale('`): rocks only in engine code —
`engine/rocks/rock.py:208` (promotion, `exact_radius`), `engine/dev_missions/far_tier_field.py:57`,
`engine/quickbattle/sim_restore.py:325` (restores a recorded scale) — plus SDK mission scripts (E1M2 `SetScale(3)` etc. on
asteroids). `docs/reference/instrumented_experiments/2026-05-12-system-scale-investigation.md` (static SDK analysis + a live
E1M1 capture) says stock SDK never calls `SetScale` on planets/suns, "only Vesuvi asteroids and dock/undock sequences". The SDK
tree is not in the snapshot, so the planet/sun = 1 claim and the "dock/undock" ship case are **inferred from that doc**, not
re-checked here.

#### 1. Code calls of `GetRadius` on a receiver (every call)

| file:line | function | receiver | class | note / what it becomes |
|---|---|---|---|---|
| engine/appc/warp_state.py:48 | `warp_in_radius` | ship (ObjectClass/ShipClass) | DRAWN | Warp-in slide distance = `slide_radii * radius` (callers: warp_in_flash.py:94, warp.py:1344, subsystems.py:1968). World size is the right reading. `r > 0.0` gate unchanged for scale > 0. Stays `GetRadius()`. |
| engine/appc/warp_state.py:57 | `warp_in_radius` (after seeder) | ship | DRAWN | Same as :48. The seeder (`host_loop` `_seed_quickbattle_ship_radius`) writes the base via `SetRadius`; read stays `GetRadius()`. |
| engine/appc/tractor.py:60 | `_standoff_distance` | tractor source (ship) | DRAWN | Combined hull radii plus margin, a world separation. Stays. Fixes a scaled rock being towed. |
| engine/appc/tractor.py:61 | `_standoff_distance` | tractor target (ship/rock) | DRAWN | Same. |
| engine/appc/combat.py:860 | `_apply_hit` (subsystem allocation loop) | ShipSubsystem | N/A (other class) | `ShipSubsystem.GetRadius` (subsystems.py:932, NativeField `Subsystem._radius`). Native twin damage.cc:519 `stock(m,h)._radius` is the subsystem row. Unaffected. |
| engine/appc/ships.py:812 | `ShipClass.InSystemWarp` | warp target (ship / planet / rock) | DRAWN | `stop = distance + target.GetRadius()`: BC's standoff from the target's SURFACE. BC's GetRadius is world-scaled, so this gets more faithful for a scaled target. Stays. |
| engine/appc/ships.py:1352 | `ShipClass.SetupProperties` hull-property copy loop (`(prop.GetRadius, receiver.SetRadius)`, bound method called as `src()`) | HullProperty (properties.py:296) | N/A (other class) | Property to subsystem copy. Unaffected. |
| engine/appc/ships.py:1623 | `ShipClass.SetupProperties` engine-pod seeding loop (`(prop.GetRadius, pod.SetRadius)`) | EngineProperty | N/A (other class) | Unaffected. |
| engine/appc/ships.py:1689 | `_copy_powered_subsystem_fields` | subsystem property | N/A (other class) | Unaffected. |
| engine/appc/collisions.py:132 | **`world_radius`** (HELPER) | any collidable: ship, rock, planet, sun; DebrisChunk | DOUBLE | Today `GetRadius() * GetScale()` (guarded: scale must be > 0 and finite, read through `type(obj)`; DebrisChunk returns raw). **Becomes `float(obj.GetRadius())`** for ObjectClass, with DebrisChunk unchanged. ⚠️ Keep the guard: native twin `beam_geometry.cc:173 world_radius` = `(s>0 && finite) ? _radius*_scale : _radius`. An unguarded `_radius*_scale` GetRadius diverges from it at s <= 0 / NaN. Either GetRadius applies the same guard, or world_radius computes `GetBaseRadius() * guarded scale`. Test fakes with GetRadius but no GetScale are handled by the `getattr(type(obj),"GetScale")` path today. Keep that path, or check those fakes. K2 and K3 snapshot `collisions.world_radius` (native_combat.py:4717, :5801), so changing its body changes the stock identity the kernels compare against. Callers are listed in §2. |
| engine/appc/collisions.py:1216 | `iter_collidables` | ShipClass / Planet in active sets | NEUTRAL (sign test) | `GetRadius() > 0.0`: unchanged for any scale > 0. A `SetScale(0)` object would drop out (today it stays). Either accessor works. Recommend `GetRadius()`. |
| engine/appc/running_lights.py:59 | `lights_for` | BlinkingLightProperty | N/A (other class) | Light size from the property. Unaffected. |
| engine/appc/subsystem_glow.py:223 | `_radius` (helper, `hasattr` at :222) | ShipSubsystem | N/A (other class) | Unaffected. |
| engine/appc/warp_flight.py:178 | `obstacles_for` (unmapped-set branch) | Planet / Sun (`GetClassObjectList(Planet)`) | NEUTRAL | Planets and suns are scale 1 (inferred, scale doc). The mapped-system branch uses `b.radius_gu` from the map, not GetRadius. Recommend `GetRadius()` (correct if a mod scales a planet). |
| engine/appc/damage_eligibility.py:32 | **`_radius`** (HELPER used by `select_eligible`) | ships in the combat tick list (rocks included if present; inferred) | DRAWN, but ⚠️ **native twin breaks** | Size score `_radius(s)/max_r`. With the change, a scaled rock (E1M2 3-8.5x) ranks bigger, which fits "bigger ship". ⚠️ The **K4 kernel** `native/src/combat/src/k4_eligibility.cc:87-104` reads raw `o_radius` (mirror of `_radius`) as the twin of this `_radius()`. If the Python moves to scaled, K4 must read `_radius * _scale`, or K4 and Python disagree whenever a scale != 1. Alternative: `GetBaseRadius()` here keeps K4 byte-identical. Decide which; don't leave it split. K4 snapshots `("select_eligible", "_radius")` (native_combat.py:5658). |
| engine/appc/planet.py:169 | `aggregate_suns_for_renderer` | Sun | DOUBLE | `radius = obj.GetRadius()`, then `"radius": radius*scale` and `"corona_radius": radius*_CORONA_SHELL_RATIO*scale`. **Becomes** `radius` and `radius*_CORONA_SHELL_RATIO`, and the `GetScale()` read is dropped. Suns are scale 1 in practice (inferred), so the visible effect is nil, but the code would double-scale. The `radius <= 0` gate is fine. |
| engine/appc/planet.py:245 | `_is_proximity_participant` | non-physics set objects (planets, suns, Waypoint, LightPlacement, GridClass…) | NEUTRAL (sign test) | `> 0.0`. Physics objects return True earlier. Recommend `GetRadius()`. |
| engine/appc/planet.py:457 | `ProximityManager.GetLineIntersectObjects` | proximity candidates: ships, rocks, planets | DRAWN | `reach = r + obj.GetRadius()`. SDK consumers are FireScript occlusion, Intercept (`shipRadius*4`) and MissionLib warp-path obstacles. Gets BC-faithful. Behaviour change: scaled E1M2 rocks now block lines at their drawn size. |
| engine/appc/death_cascade.py:272 | `_fire` | dying ship | DRAWN | Blast sizes: AddDamage radius (hull-wear records are world GU, converted via `model_per_gu` in hull_wear.py:132-139, so world is right), explosion and light. Ships are scale 1 in practice. Rocks die through `rocks.death`, not here. Stays. |
| engine/appc/death_cascade.py:302 | `_fire_final` | dying ship | DRAWN | Closing explosion size. Stays. |
| engine/appc/perception.py:261 | `_surface_gu` (HELPER; via `perceived_by` and `measure_surface_gu_to`) | target ship / rock / planet | DRAWN | BC range readout = distance to the bounding sphere. Fixes the readout for scaled rocks. Uses `implements(ship,"GetRadius")` (MRO, ProximityCheck excluded by type only if it's listed; inferred). Stays. |
| engine/appc/subsystems.py:304 | `active_impulse_emitters` | impulse pod (ShipSubsystem) | N/A (other class) | Unaffected. |
| engine/appc/subsystems.py:315 | same (master-mount fallback) | ImpulseEngineSubsystem | N/A (other class) | Unaffected. |
| engine/appc/internal_blast.py:71 | `queue` | destroyed ShipSubsystem | N/A (other class) | Unaffected. |
| engine/appc/objects.py:399 | `ObjectClass._random_point_on_model` (headless / instance-less fallback) | self (ObjectClass) | DRAWN | Random point on the bounding sphere. The docstring at :368 says "GetRadius() is already world-scale", which is false today for scaled objects and becomes true. Stays. |
| engine/appc/objects.py:779 | `ObjectClass.LineCollides` | self | DRAWN | Solid-ball segment test, used by DockWithStarbase. Stays. |
| engine/appc/objects.py:1013 | `ObjectClass.GetClonedModelRadius` | self | DRAWN | Mirrors `GetRadius()`. Unreached in practice (`HasClonedModel` returns 0). Stays. |
| engine/appc/lens_flare.py:94 | `aggregate_lens_flares_for_renderer` (`src = flare._source`) | flare source object (normally a Sun) | NEUTRAL | `source_radius` goes to the renderer. Suns are scale 1 (inferred). Recommend `GetRadius()`: after the planet.py:169 fix, sun body and flare use the same quantity (today a scaled sun would draw at r*s while the flare used r). |
| engine/appc/warp_core_breach.py:105 | `core_radius_gu` | ship | DRAWN | Wound radius = clamp(0.25*R, 0.1, 1.2) GU, laid as world-GU hull-wear records. Stays. |
| engine/appc/damage_geometry.py:112-115 | `breakables_allowed_for` (`getter = getattr(ship,"GetRadius")`; `getter()`) | ship | DRAWN | `radius > BREAKABLE_MIN_RADIUS_GU (0.6)` (Galor floor). Ships are scale 1 in practice, so nil effect. `tests/unit/test_damage_geometry_flags.py` pins the stock fleet. Stays. |
| tools/bake_impulse_glow.py:66 | `extract_impulse_pods.radius_of` | EngineProperty / ImpulseEngineProperty | N/A (other class) | |
| tools/bake_warp_glow.py:58 | `extract_warp_pods.radius_of` | EngineProperty / WarpEngineProperty | N/A (other class) | |
| tools/hardpoint_logger.py:63 | snippet (`_safe_call(ship,"GetRadius")`) | BC's real ship (runs inside stbc.exe) | N/A (other class: real Appc) | Python 1.5 instrumentation. Records BC's own world-scaled GetRadius. Unaffected. |
| tools/scale_logger.py:102 | snippet (`_safe_call(obj,"GetRadius")`) | BC real objects | N/A (real Appc) | Logged next to GetScale (:105). Unaffected. |
| tools/probes/q19_shield_facing_and_beam.py:137 | probe `_call("radius", pTarget, "GetRadius", ())` | BC real target | N/A (real Appc) | |
| tools/probes/q11_planet_scale.py:126 | probe `_safe(pPlayer,"GetRadius",())` | BC real player | N/A (real Appc) | |
| tools/probes/q11_planet_scale.py:183 | probe `_safe(p,"GetRadius",())` | BC real planet | N/A (real Appc) | |
| App.py | (none) | — | — | No GetRadius call. Lines 2021/2063 are `_Stub` comments about numeric coercion only. |

Not calls, only guards (listed for completeness): `combat.py:135`/`:860`, `splash_damage.py:71`/`:99`, `projectiles.py:1041`,
`tractor.py:60-61`, `subsystem_glow.py:222`, `subsystems.py:304/315`, `damage_eligibility.py:32`, `warp_core_breach.py:105`
(`hasattr(x,"GetRadius")`); `camera_modes.py:280`, `perception.py:261` (`implements`). Method definitions (receivers for the
N/A rows): objects.py:210 (base), ai.py:1274 `ProximityCheck` (`_proximity_radius`; ObjectClass subclass that overrides,
which native_combat.py:5503 calls out), subsystems.py:932, properties.py:296, events.py:439, debris_chunk.py:90 (world size
already), engine/cameras/director.py:46, projectiles.py:309 Torpedo (`_rad` property).

#### 2. Calls that reach GetRadius through a helper (fixed once in the helper)

| file:line | function | helper | receiver | class | becomes |
|---|---|---|---|---|---|
| engine/appc/combat.py:135 | `_resolve_hit_point` (sphere fallback) | collisions.world_radius | hit ship | DOUBLE via helper | unchanged call. Helper fix covers it. K2/K3 twin. |
| engine/appc/combat.py:972 | `bubble_bound_radius` | collisions.world_radius | ship | DOUBLE via helper | same. Native twin projectile_geometry.cc:142 `world_radius(m, ship)`. |
| engine/appc/collisions.py:156 | `contact_radius` | world_radius | collidable | DOUBLE via helper | same |
| engine/appc/collisions.py:293 | `_resolve_body` | world_radius | collidable | DOUBLE via helper | same (`_Body.radius`) |
| engine/appc/collisions.py:377, :381 | `_deepest_piece_overlap` | world_radius | pair objects | DOUBLE via helper | same |
| engine/appc/collision_avoidance.py:388 | `_avoid_objects` | world_radius | own ship | DOUBLE via helper | same |
| engine/appc/collision_avoidance.py:487 | `_test_course_override` | world_radius | own ship | DOUBLE via helper | same |
| engine/appc/collision_avoidance.py:846 | `_build_obstacle_snapshot` | world_radius | obstacles | DOUBLE via helper | same |
| engine/appc/splash_damage.py:71 | `apply` | world_radius | target | DOUBLE via helper | same |
| engine/appc/splash_damage.py:99 | `_impact_point` | world_radius | target | DOUBLE via helper | same |
| engine/appc/projectiles.py:1019 | `update_all` (hull-sphere hit) | world_radius | ship | DOUBLE via helper | same. Native twin k3_projectiles.cc:764. |
| engine/appc/projectiles.py:1041 | `update_all` | world_radius | ship | DOUBLE via helper | same. Native twin k3_projectiles.cc:780. |
| engine/appc/camera_modes.py:288 | `_target_radius` (non-rock) | world_radius | camera target | DOUBLE via helper | same |
| engine/appc/camera_modes.py:285 | `_target_radius` (rock) | rocks.rock.effective_radius | rock | DOUBLE via helper | see effective_radius below |
| engine/appc/sensor_occlusion.py:128 | `_major_rocks` | rocks.rock.effective_radius | rock | DOUBLE via helper | same. Native twin sensor_detect.cc:433-440. |

**HELPER `engine/rocks/rock.py:59 effective_radius`** (outside engine/appc, read because appc depends on it): today it computes
`base = GetRadius()`, uses `hull.GetRadius()` instead when `base <= 0`, and returns `base * GetScale()`. That would DOUBLE. It
**becomes**: `GetBaseRadius()` with the hull fallback, times `GetScale()`. Equivalently `GetRadius()` if > 0, else
`hull.GetRadius() * GetScale()`, because the hull is a subsystem and its radius is unscaled. Native twin `sensor_detect.cc:433`
reads raw mirror `_radius` and `_scale`. It stays correct as long as the Python keeps base * scale. Only its comment
"`float(rock.GetRadius())`" goes stale.

Helpers to change: **`collisions.world_radius`** (13 appc callers + 4 native twins, whose logic stays right), **`rocks.rock.effective_radius`**
(2 appc callers + 1 native twin, logic stays right), **`planet.aggregate_suns_for_renderer`** (local DOUBLE), and a decision on **`damage_eligibility._radius`**
(K4 twin must move with it).

#### 3. Direct `._radius` / `._scale` reads on ObjectClass-family objects in engine/appc

| file:line | function | receiver | class | note |
|---|---|---|---|---|
| engine/appc/objects.py:80-81 | class body | ObjectClass | — (definition) | `_radius = native_combat.NativeField(float)`, `_scale = native_combat.NativeField(float)`. Keys default to the attribute name, so mirror fields `"_radius"` and `"_scale"`, Kind::Object (mirror.cc:33-34; C++ enum `Field::o_radius`, `Field::_scale`; ObjectRow `double _radius, _scale` mirror.h:198). Accessors mirror.cc:281 `o_radius` → `r._radius`. |
| engine/appc/objects.py:96-97 | `ObjectClass.__init__` | self | write | 0.0 / 1.0 |
| engine/appc/objects.py:211 | `GetRadius` | self | the change site | becomes `_radius * _scale` |
| engine/appc/objects.py:214 | `SetRadius` | self | write (base) | stays a base write. ⚠️ Open: after the change `SetRadius(r)` then `GetRadius()` gives back `r*s` on a scaled object. BC's SetRadius semantics weren't checked here. |
| engine/appc/objects.py:217, :220 | `GetScale` / `SetScale` | self | — | |

No other engine/appc module reads `obj._radius` or `obj._scale` on an ObjectClass-family object (`grep -rnE '\._radius\b|\._scale\b|"_radius"|"_scale"'`).
Other `_radius` hits belong to other classes: properties.py:280/294/297 (property), events.py:425/439/440 (event),
subsystems.py:334/403/933/936 (`Subsystem._radius` NativeField), tg_ui/widgets.py:344 (`_scale`, a widget). native_combat.py:5658's
`"_radius"` is the *function name* `damage_eligibility._radius`.

##### How the mirror is pushed (native_combat.py)
- `NativeField.__set__` (native_combat.py:~651): it stores `obj.__dict__[name]`. If the object has a row (`_nslot`), it pushes
  through `combat_push_scalar(h, _fid(key), push_code, value)` (`_push_scalar`). Off the main thread it queues `_repush_native`.
  `_fid` resolves the name through `_h.combat_field_names()`.
- On registration, `register` → `_push_all` pushes every field from `_fields_of(type(obj))` (MRO walk).
- `combat_dump` keys are the raw attribute values (`_matches` compares against `obj.__dict__`), so the **mirror carries the base
  `_radius` and the raw `_scale`**, not `GetRadius()`. Nothing needs to change in the push path. Every native reader that stands in
  for Python `GetRadius()` has to apply `_scale` itself.
- Native readers of Object `_radius` / `_scale`:
  - `beam_geometry.cc:173 world_radius` (r*s, guarded). OK once Python world_radius equals GetRadius with the same guard.
    Used by beam_trace.cc:124, projectile_geometry.cc:142, k3_projectiles.cc:764/780.
  - `sensor_detect.cc:433 effective_radius` (base*s). OK.
  - **`k4_eligibility.cc:87-104` (raw `_radius` as `damage_eligibility._radius`). Mismatch if that Python moves to scaled GetRadius.**
  - `damage.cc:411`, `weapon_geometry.cc:280`, `beam_geometry.cc:223`, `projectile_geometry.cc:149` read `_scale` alone (hull box /
    body point scaling). Not radius, unaffected.
- K2 (`_K2_OBJECT_NAMES`, native_combat.py:4731) and the step scan (`_STEP_SHIP_PATCHES` :5509) treat `GetRadius`/`GetScale` as
  stood-in methods. They check identity against the stock class (ruling C2), so editing `ObjectClass.GetRadius`'s body is
  allowed, as long as each native twin follows the new semantics (the list above).

#### 4. Comment / docstring mentions that go stale (no code effect)

| file:line | text gist | after the change |
|---|---|---|
| collisions.py:118-126 | "GetRadius() is SDK surface and stays UNSCALED" | rewrite (now scaled) |
| collisions.py:198, :369, :1067 | "world_radius: GetRadius() x GetScale()" | rewrite as "GetRadius()" |
| combat.py:133, :965-969 | "GetRadius() x GetScale()", "Scaled (GetRadius x GetScale)" | rewrite |
| camera_modes.py:271-272 | "GetRadius() is unscaled SDK surface" | rewrite |
| projectiles.py:899, :1015 | "(GetRadius x GetScale)" | rewrite |
| sensor_occlusion.py:5 | "never GetRadius() alone, which ignores scale" | rewrite |
| objects.py:368 | "GetRadius() is already world-scale" | becomes true |
| objects.py:759, :998-1011 | LineCollides / cloned-model docstrings | fine |
| hull_bounds.py:311-312 | host seeds `if ship.GetRadius() <= 0.0` | still true for sign. The host seeder writes the base via SetRadius |
| warp_state.py:37 | "GetRadius() == 0 until realised" | fine |
| ships.py:762, :1686 | InSystemWarp / subsystem copy | fine |
| planet.py:233 | "real ship reports GetRadius() == 0" headless | fine |
| internal_blast.py:9, warp_core_breach.py:9, :31 | formula comments | fine |
| damage_geometry.py:59 | "How GetRadius should be derived is itself an open question" | note BC = world-scaled |
| native sensor_detect.cc:434, :439; k4_eligibility.cc:80 | twin comments citing `rock.GetRadius()` / `_radius(s)` | update with the twins |

#### 5. Counts (section 1, code calls only)

- DRAWN: 15 (warp_state×2, tractor×2, ships:812, planet:457, death_cascade×2, perception, objects×3, warp_core_breach,
  damage_geometry, damage_eligibility, which is DRAWN only if K4 moves with it)
- DOUBLE: 2 direct (collisions.world_radius, planet.aggregate_suns_for_renderer), plus 15 helper-routed call sites in §2 (13 world_radius +
  2 effective_radius), fixed by changing 2 helpers (world_radius, rocks effective_radius)
- NEUTRAL: 4 (collisions:1216 and planet:245 sign tests; warp_flight:178 and lens_flare:94, planets/suns)
- BASE: 0 strictly required. damage_eligibility._radius becomes BASE only if you choose to keep K4 untouched.
- N/A (other class): 11 in engine/appc + tools (combat:860, ships:1352/1623/1689, running_lights:59, subsystem_glow:223,
  subsystems:304/315, internal_blast:71, bake_impulse_glow:66, bake_warp_glow:58), plus 5 BC-side instrumentation reads
  (hardpoint_logger, scale_logger, 3 probe sites).

---

## Annex B. Engine `GetRadius()` calls outside `engine/appc/`


Snapshot: `project/combat_threading` @ `2369cba41`.

Grep: `grep -rn 'GetRadius()' engine | grep -v '^engine/appc/'` gives **74 lines**. 36 are real calls (37 call expressions, because shuttle_service.py:1091 has two). 38 are comments or docstrings. All 74 are listed below.

#### Facts checked by reading (they decide the NEUTRAL rows)

- **Overrides.** Only the base `ObjectClass.GetRadius` (objects.py:210) serves ships, rocks, planets, suns and stations. No `def GetRadius` in planet.py, ships.py or rock.py. Separate classes: `ShipSubsystem` (subsystems.py:932), `SubsystemProperty`/`BlinkingLightProperty` (properties.py:296), `ProximityCheck` (ai.py:1274), events.py:439, `DebrisChunk` (debris_chunk.py:90) and `_GhostTarget` (cameras/director.py:46).
- **Planets and suns are always at scale 1 in practice.** The SDK calls `SetScale` 9 times (E1M2 x2, E2M1, DockWithStarbase x2, Multi1, Multi6, plus 2 commented out). All of them target rocks or the docking ship, never a Planet. In the engine, `SetScale` is called only by far_tier_field.py:57 (a rock), rock.py:208 (a promoted rock) and sim_restore.py:325. sim_restore restores only CT_DAMAGEABLE_OBJECT records, and a Planet is not a DamageableObject (rocks/death.py comment). **Inferred:** a mod could still scale a planet, so rows that only work because the scale is 1 are tagged NEUTRAL, not "safe".
- **Planets draw at** `natural_scale * GetScale()` (`_apply_live_world_transform`). `natural_scale = GetRadius()/sphere_radius` is cached at realise.
- **Ships draw at** `BC_MODEL_SCALE * GetScale()` (`_ship_world_matrix`). Ship rendering never reads GetRadius.
- **Scaled ObjectClass objects in practice:**
  - E1M2 rocks (3x, and 3.7–8.5x), E2M1 rocks, Multi1/Multi6 rocks, the far_tier_field test rock.
  - Promoted field rocks: `RockClass_Create(exact_radius=True)` sets `_radius = r_q` (2 significant figures) and `scale = radius_gu/r_q`, which is about 1 ± 5%.
  - The player while docking: SDK DockWithStarbase.py:47-50 does `SetScale(GetScale()*4/GetRadius())` and restores it at 235.
- **A zero-guard is scale-invariant.** `GetRadius() <= 0` or `> 0` gives the same answer for any scale > 0, so a guard works in practice with either accessor. Guards paired with a `SetRadius` seed are still tagged BASE so that read and write use the same quantity.

#### A. Real calls

| file:line | function | receiver | class | note / what it becomes |
|---|---|---|---|---|
| engine/host_loop.py:5514 | `_aggregate_planets` | Planet (non-Sun) in each live set | NEUTRAL (intent DRAWN) | Influence sphere for the dust pass's proximity density. Planet scale is 1. Keep `GetRadius()`: the drawn size is what the dust should respect. |
| engine/host_loop.py:6010 | `_nearest_live_entry` | Planet from `session.planet_instances` | NEUTRAL (intent DRAWN) | Surface distance for choosing the atmosphere/surface dial target. Planet scale is 1. Keep `GetRadius()`. |
| engine/host_loop.py:6561 | `_seed_ship_radius` | ship or rock being realised | BASE (guard) | `if ship.GetRadius() > 0: return`, then `SetRadius(extent*BC_MODEL_SCALE)`. Scale-invariant test, but it pairs with a base write. Becomes `GetBaseRadius()`. Called from realise (7130s area via `realize_set_objects`), from the loader (8395) and from `_seed_quickbattle_ship_radius` (8329). **The docstring at 6558-6560 ("Both are unscaled: ... multiply by GetScale() (collisions.world_radius)") goes stale.** |
| engine/host_loop.py:7163 | `realize_set_objects` (planet loop) | Planet | BASE (guard) | `<= 0` then `planet.SetRadius(extent*BC_MODEL_SCALE)`. Becomes `GetBaseRadius()`. Neutral in practice. |
| engine/host_loop.py:7168 | `realize_set_objects` (planet loop) | Planet | **BASE (must change)** | `natural_scale = radius / sphere_radius`, then `_apply_live_world_transform` multiplies by `GetScale()` again. A scaled `GetRadius()` here would draw a scaled planet at s² size. Becomes `GetBaseRadius()`. Neutral today (scale 1); breaks only if a planet is ever scaled. |
| engine/host_loop.py:7503 | `_reconcile_camera_radius` (per frame) | player ship | DRAWN | Seeds chase/tracking distances. Today they use the unscaled radius. After the change they follow the drawn size. **Behaviour change:** while DockWithStarbase shrinks the player, this per-frame compare (`radius != director.chase.ship_radius`) re-seeds the chase distances on the shrink and again on the restore. `set_ship_radius` keeps any user zoom. During docking the view is a Placement cinematic, so this is probably invisible. Inferred faithful: BC's chase uses the scaled NiBound. |
| engine/host_loop.py:7625 | `_check_mapped_bodies_untouched` | Planet in a mapped set | NEUTRAL | Compared with `body.radius_gu`, which `apply_map` wrote through `SetRadius`. Scale 1, so either accessor works. Recommend keeping `GetRadius()`: a script's `SetScale` on a mapped body is also a resize the tripwire should report (inferred intent). |
| engine/host_loop.py:8311 | `_MissionLoader._seed_quickbattle_ship_radius` | new QB ship / recreated player / warp-in arrival (also registered as `warp_state.set_radius_seeder`, 10974) | BASE (guard) | Early-return guard before `_seed_ship_radius`. Becomes `GetBaseRadius()`. Scale-invariant. |
| engine/host_loop.py:8479 | `_MissionLoader` realise-session planet loop (`_realize_session`) | Planet | BASE (guard) | Twin of 7163. Becomes `GetBaseRadius()`. |
| engine/host_loop.py:8484 | same | Planet | **BASE (must change)** | Twin of 7168: `natural_scale = radius / sphere_radius`. Becomes `GetBaseRadius()`. |
| engine/host_loop.py:8724 | `_viewscreen_scene_feed` | player ship | DRAWN | `tc.set_ship_radius(...)` for the viewscreen tracking solver. Player scale is 1 except while docking. Keep `GetRadius()`. |
| engine/host_loop.py:11249 | `run()` setup (camera director seed) | `session.player` | DRAWN | Initial chase/tracking seed. Keep. |
| engine/host_loop.py:12489 | `run()` loop, `_on_player_change` closure | new player ship | DRAWN | Re-seeds the cameras on a player identity change. Keep. |
| engine/host_loop.py:12501 | `run()` loop, after a pending mission swap | player | DRAWN | Same as above. Keep. |
| engine/host_loop.py:13124 | `run()` loop, `prep.camera` fixed-camera branch | player | DRAWN | `eye z = CAM_MAX_RADII * radius`. Keep. |
| engine/host_loop.py:13482 | `run()` loop, DOF foreground frame | player | DRAWN | The foreground ramp spans the player's hull. Keep. |
| engine/dev_keybindings.py:71 | `register_for_frame._f10_shield_debug` | player | DRAWN | Debug hit offset about one radius ahead, near the bubble. The bubble is drawn at instance scale. Keep. Neutral in practice. |
| engine/orbit_altitude.py:108 | `install.CreateAI` wrapper (orbit_distances) | Planet (OrbitPlanet target) | NEUTRAL (intent DRAWN) | Altitude = max(150, 0.15·R) above the surface. Planet scale is 1. Keep `GetRadius()`: the SDK OrbitPlanet reads the same call. |
| engine/ui/spv_decals_pane.py:320 | `_decal_ship_radius` (fallback branch only) | player ship (SPV) | **BASE (must change)** | Divided by `BC_MODEL_SCALE` to get NIF body units. The docstring says "UNSCALED GU ... never divided by GetScale()". It becomes `GetBaseRadius()`. Otherwise a scaled ship would get radius·s in body units. Reached only when the instance has no model handle. |
| engine/ui/reticle_text.py:76 | `build_reticle_text` | player's target (ship / rock / planet / station) | DRAWN (**fixes a bug**) | Box top/bottom projection. Today an E1M2 3–8.5x rock, a Multi1/Multi6/E2M1 rock or a promoted field rock gets a bracket sized to the unscaled radius. Keep `GetRadius()`; the change fixes it. |
| engine/ui/target_reticle.py:100 | `build_target_reticle` | player's target | DRAWN (**fixes a bug**) | `ship_radius` in the reticle payload sent to native. Native knows nothing about the scale. Same fix as above. Keep. |
| engine/ui/phaser_overlay.py:186 | `_arc_fallback_radius` | SPV ship (player) | BASE (neutral) | Arc envelope for Length-0 weapons, drawn around `subsystem_world_position` mounts. Those are world-loc + R·local with **no scale** (unscaled frame). To match that frame use `GetBaseRadius()`. Player scale is 1 outside docking, so either works in practice. |
| engine/ui/running_light_editor.py:94 | `spec_from_property` | `BlinkingLightProperty` | N/A (other class) | properties.py:296. |
| engine/dev_missions/felix_destroy.py:88 | `_seed_radius` (headless only) | QB/mission ship | BASE (guard) | `<=0` then `SetRadius(NOMINAL_HULL_RADIUS_GU)`. Use `GetBaseRadius()`. Scale-invariant. |
| engine/dev_missions/combat_stress.py:232 | `_place_on_ring` seed (headless) | ring ship | BASE (guard) | Same pattern. `GetBaseRadius()`. |
| engine/dev_missions/combat_stress.py:255 | `Initialize` (headless) | player | BASE (guard) | Same pattern. `GetBaseRadius()`. |
| engine/rocks/death.py:267 | `_break_up` (major-piece loop) | new RockClass piece (`RockClass_Create`, no `exact_radius`, so scale 1) | NEUTRAL (intent DRAWN) | Targetable threshold on the built radius. Scale is 1. Keep `GetRadius()`: the comment wants "the built one the player sees". |
| engine/systems/shuttle_service.py:1024 | `_round_point` | home station (Starbase 12) | NEUTRAL (intent DRAWN) | Clearance radius for the round-the-station waypoint. Station scale is 1. Keep. |
| engine/systems/shuttle_service.py:1091 (1st) | `_hull_radius` (used by `_bands`, 1106) | dry dock / station | NEUTRAL (intent DRAWN) | `max(obj.GetRadius(), hull.GetRadius())`. Keep. Note the max mixes a (now scaled) object radius with an unscaled hull-subsystem radius. They agree at scale 1. |
| engine/systems/shuttle_service.py:1091 (2nd) | `_hull_radius` | `HullSubsystem` | N/A (other class) | subsystems.py:932. |
| engine/rocks/rock.py:66 | `effective_radius` (**shared helper**) | rock | **DOUBLE** | `base = GetRadius(); ...; return base * GetScale()`. This would square the scale. Fix: `base = float(rock.GetBaseRadius())` and the rest unchanged (zero behaviour change). Alternatively `r = GetRadius(); if r <= 0: r = hull.GetRadius()*GetScale()`. Callers: engine/rocks/minors.py:98-100/162, engine/rocks/death.py:213, and in appc: camera_modes.py `_target_radius`, sensor_occlusion.py, ships.py. Those reach engine/cameras/zoom_fit.py:35, tracking.py:207 and director.py:257. Docstring 61-65 goes stale. |
| engine/rocks/rock.py:69 | `effective_radius` hull fallback | `HullSubsystem` | N/A (other class) | Unscaled hull radius × GetScale(); still correct after the change. |
| engine/systems/apply_map.py:195 | `_rescale_sun` | Sun | BASE (neutral) | Read-modify-write: `ratio = atmosphere/old_radius`, then `SetRadius(radius_gu)`. Pairs with the base writer, so use `GetBaseRadius()`. Sun scale is 1. Whether BC's atmosphere radius is scaled is not known (inferred). |
| engine/quickbattle/late_arrivals.py:267 | `_arrive_group` | player | DRAWN | Seeds `placed` for the overlap nudge. Keep. |
| engine/quickbattle/late_arrivals.py:270 | `_arrive_group` | every CT_DAMAGEABLE_OBJECT in the QB set (ships, stations, **rocks**) | DRAWN (**fixes**) | Promoted field rocks (scale ≈ 1 ± 5%) and any scripted-scale rock are under-sized today. Keep. |
| engine/quickbattle/spawn.py:222 | `_place` | created QB ship | DRAWN | Nudge-search radius. QB ships are scale 1 (`_apply_identity` sets no scale). Keep. |
| engine/quickbattle/spawn.py:331 | `_probe_radius` | throwaway probe ship | DRAWN (neutral) | Read right after the seed. Feeds late-arrival radii (spawn.py:297). Scale 1. Keep. |
| engine/quickbattle/spawn.py:404 | `_place_created` | player | DRAWN | Seeds `placed`. Keep. |
| engine/quickbattle/spawn.py:410 | `_place_created` | group member ships | DRAWN | Radii for `placement.group_positions` / `escort_positions`. Keep. |
| engine/quickbattle/spawn.py:413 | `_place_created` | player | DRAWN | Escort spacing. Keep. |

#### B. Comment and docstring hits (no call; listed because the grep matches them)

`stale?` means the text describes GetRadius as unscaled, or relies on that, and should be reworded with the change.

| file:line | context | stale? |
|---|---|---|
| host_loop.py:6214 | realise docstring ("invisible, GetRadius() ...") | no |
| host_loop.py:6488 | BC_MODEL_SCALE comment ("GetRadius() is a gameplay value") | no |
| host_loop.py:6537 | `_model_sphere_radius_from_aabb` doc (render_scale = GetRadius()/bound) | **yes**: becomes GetBaseRadius()/bound |
| host_loop.py:6538 | same | **yes** |
| host_loop.py:6540 | same | **yes** |
| host_loop.py:6550 | `_seed_ship_radius` doc | **yes** (with 6558-6560, "Both are unscaled ... world_radius") |
| host_loop.py:6620 | `_ship_world_matrix` doc (natural_scale = GetRadius()/NIF_extent) | already stale (ships use flat BC_MODEL_SCALE); reword to base |
| host_loop.py:6621 | same | as above |
| host_loop.py:6737 | `MissionSession.planet_natural_scale` comment | **yes**: base radius |
| host_loop.py:6824 | `_cache_ship_hull_pieces` doc | no |
| host_loop.py:7170 | planet realise comment ("draws at exactly GetRadius()") | still true for the drawn radius at scale 1; reword to base × scale |
| host_loop.py:7477 | `_UNKNOWN_SHIP_RADIUS` comment | no |
| host_loop.py:7483 | `_reconcile_camera_radius` doc | no |
| host_loop.py:7487 | same (quotes the `if ship.GetRadius() <= 0.0: SetRadius` guard) | minor: the guard becomes GetBaseRadius |
| host_loop.py:8294 | `_seed_quickbattle_ship_radius` doc | no |
| host_loop.py:8393 | loader seed comment | no |
| host_loop.py:8486 | planet loop comment | as 7170 |
| host_loop.py:10971 | warp-in radius seeder comment | no |
| host_loop.py:12968 | `_reconcile_camera_radius` call comment | no |
| dev_keybindings.py:57 | F10 comment | no |
| ui/spv_decals_pane.py:304 | `_decal_ship_radius` doc ("GetRadius(), which is UNSCALED GU") | **yes**: GetBaseRadius() |
| ui/ship_property_viewer_panel.py:1085 | `_effective_radius` doc (subsystem radius) | no (subsystem) |
| ui/ship_property_viewer_panel.py:2009 | subsystem `radius` doc | no (subsystem) |
| dev_missions/combat_stress.py:67 | nominal radius comment | no |
| dev_missions/combat_stress.py:224 | guard comment | no |
| cameras/__init__.py:109 | "Distance ... multiples of the ship's NIF bounding-sphere radius (what GetRadius() returns)" | becomes more accurate (BC bound includes scale) |
| cameras/__init__.py:116 | "our GetRadius() is within 10% of BC's merged NiBound" | no (scale-1 measurement) |
| cameras/__init__.py:133 | tracking radii comment | no |
| cameras/chase.py:74 | `set_ship_radius` doc | no |
| rocks/rock.py:61 | `effective_radius` doc (61-65: "live the host sets GetRadius ... without SetScale ... reading GetRadius alone plans them at ~0.8 GU") | **yes** |
| systems/apply_map.py:15 | module doc (planet_natural_scale caches GetRadius()/NIF_extent) | **yes**: base |
| systems/region_hooks.py:16 | module doc (same cache) | **yes**: base |
| quickbattle/spawn.py:43 | `set_radius_fn` doc | no |
| quickbattle/spawn.py:215 | `_place` doc | no |
| quickbattle/spawn.py:389 | `_place_created` comment | no |

#### C. Other GetRadius references (not `GetRadius()` text)

| file:line | what | class |
|---|---|---|
| host_loop.py:13483 | `hasattr(player, "GetRadius")` guard for 13482 | n/a (guard) |
| ui/phaser_overlay.py:184 | `hasattr(ship, "GetRadius")` guard for 186 | n/a (guard) |
| ui/ship_property_viewer.py:408 | `getattr(sub, "GetRadius", ...)` | N/A (subsystem) |
| cameras/director.py:46 | `_GhostTarget.GetRadius` def | N/A (other class); see D |

#### D. Direct `._radius` / `._scale` reads and writes outside engine/appc

`grep -rnE '\._radius\b|\._scale\b' engine | grep -v '^engine/appc/'` finds only:

| file:line | function | receiver | class | note |
|---|---|---|---|---|
| engine/cameras/director.py:42 | `_GhostTarget.__init__` (write) | `_GhostTarget` (plain class, not ObjectClass) | N/A (other class) | Stores `camera_modes._target_radius(tgt)`, which is already the DRAWN radius (world_radius / effective_radius). |
| engine/cameras/director.py:46 | `_GhostTarget.GetRadius` (read) | `_GhostTarget` | N/A (other class) | When `_target_radius(ghost)` runs, `world_radius` multiplies by an unreadable GetScale, which counts as 1, so the result is consistent today and after the change. Keep this in mind if `world_radius` is rewritten to call `GetScale()` unguarded. |

There are **no** direct `_radius` / `_scale` accesses on ObjectClass-family objects outside engine/appc. No `getattr(obj, "_radius")` or `__dict__` access either.

#### E. Writers outside appc that affect the new GetRadius() (for completeness)

| file:line | write | receiver | note |
|---|---|---|---|
| host_loop.py:6566 | `SetRadius(r*BC_MODEL_SCALE)` | ship/rock | base seed; stays base |
| host_loop.py:7165, 8481 | `SetRadius(extent*BC_MODEL_SCALE)` | Planet | base seed |
| dev_missions/felix_destroy.py:89, combat_stress.py:233, 256 | `SetRadius(nominal)` | ship | base seed (headless) |
| rocks/rock.py:195 | `SetRadius(r_q)` | rock | base; paired with 208 `SetScale(radius_gu/r_q)` for promoted rocks. After the change `GetRadius()` on a promoted rock returns radius_gu exactly (today r_q). |
| rocks/rock.py:147 | `hull.SetRadius(...)` | HullSubsystem | N/A |
| systems/apply_map.py:198 | `sun.SetRadius(radius_gu)` | Sun | base (scale 1) |
| systems/apply_map.py:229 | `obj.SetRadius(body.radius_gu)` | mapped Planet | base; the map's radius is meant as the drawn size, which holds at scale 1 |
| dev_missions/far_tier_field.py:57 | `rock.SetScale(ROCK_SCALE)` | rock | now changes GetRadius() |
| rocks/rock.py:208 | `SetScale(radius_gu/r_q)` | promoted rock | now changes GetRadius() |
| quickbattle/sim_restore.py:325 | `new.SetScale(record.scale)` | rebuilt damageable | radius is re-seeded (base) at realise, so this is consistent |

#### Indirect paths outside appc that go through appc helpers (DOUBLE-exposed until the helpers change)

- engine/cameras/zoom_fit.py:33-37 uses `camera_modes._target_radius`, which goes to `collisions.world_radius` / `rock.effective_radius`, plus `combat._hull_box_for` (re-applies GetScale to `_shield_hull_box`; not radius-based).
- engine/cameras/tracking.py:204-207 uses `_target_radius(player)`.
- engine/cameras/director.py:252-257 uses `_target_radius(tgt)` (ghost).
- engine/rocks/minors.py:98-100,162 and engine/rocks/death.py:213 use `effective_radius`.

These are correct once `world_radius` and `effective_radius` stop multiplying by scale, or read the base. Nothing in these files needs editing.

---

## Annex C. Scale multipliers and `_radius` writers


Snapshot: `project/combat_threading` @ `2369cba41`. Read-only.
"inferred" = not proven by reading the code path end to end.

#### 0. Facts that frame everything below

| Fact | Evidence |
|---|---|
| `_radius` and `_scale` on ObjectClass are `native_combat.NativeField(float)` descriptors: every write is pushed to the native Object row. | `engine/appc/objects.py:80-81` |
| ALL Python writes to an ObjectClass `_radius` go through `ObjectClass.SetRadius` (objects.py:213-214) or `ObjectClass.__init__` (objects.py:96, `0.0`). No `__dict__["_radius"]`, `setattr(...,"_radius")` or other direct write exists in `engine/`. | grep `\._radius\b`, `"_radius"` |
| ALL Python writes to `_scale` go through `ObjectClass.SetScale` (objects.py:219-220) or `__init__` (objects.py:97, `1.0`). | grep `\._scale\b` |
| Native combat kernels read the RAW fields `o._radius` / `o._scale`, never `GetRadius()`. So their `radius*scale` twins stay right as long as `_radius` stays the BASE value. | `native/src/combat/src/beam_geometry.cc:173-178` (world_radius twin), `sensor_detect.cc:433-440` (effective_radius twin), `projectile_geometry.cc:149`, `weapon_geometry.cc:280`, `beam_geometry.cc:223`, `damage.cc:411` |
| **But native twins of a BARE `GetRadius()` read `o._radius` too** -- these diverge once GetRadius is scaled (see conflict C1). | `native/src/combat/src/k4_eligibility.cc:80-104` twins `damage_eligibility._radius` = `float(ship.GetRadius())` |
| GetRadius/SetRadius overrides on ObjectClass-family classes: only `ProximityCheck(ObjectClass)` (`engine/appc/ai.py:1267/1274`), which stores `_proximity_radius` and never touches `_radius`. Torpedo overrides the `_radius` ATTRIBUTE with a property (`projectiles.py:307-318`, backing slot `_rad`) but inherits GetRadius/SetRadius. | grep `def GetRadius` |
| Duck-typed non-ObjectClass bodies with GetRadius: `DebrisChunk` (debris_chunk.py:90, GetRadius = WORLD size, GetScale = shared-model render scale), `_GhostTarget` (cameras/director.py:46, radius already world, no GetScale). | read |
| SDK (`/Users/mward/Documents/Star Trek Bridge Commander/sdk/Build/scripts`) never calls `SetRadius` on an ObjectClass: only `ProximityCheck.SetRadius` (MissionLib:216, E6M3:657, E6M5:492, ConditionInRange:102/214) and hardpoint properties. | grep SDK |
| SDK `SetScale` receivers: E1M2.py:1110 (debris asteroids, 3), E1M2.py:3027 (asteroids), E2M1.py:481 (asteroids), Multi1.py:108 / Multi6_S.py:69 (asteroids), **AI/Compound/DockWithStarbase.py:50 and :235 (the docking ship, i.e. the PLAYER)**. No planet, sun or torpedo. | grep SDK |

#### A. Every site that multiplies/divides by scale

##### A.1 Radius x scale (these collapse to the new scaled `GetRadius()`)

| file:line | function | computes | after the change |
|---|---|---|---|
| engine/appc/collisions.py:117-143 | `world_radius(obj)` (**HELPER**) | `GetRadius() * GetScale()` (via `type(obj).GetScale`, s<=0/non-finite -> r); DebrisChunk -> `GetRadius()` unscaled (already world) | Becomes plain `float(obj.GetRadius())` for ObjectClass. Keep the DebrisChunk branch semantics (it already returns GetRadius). Note: a non-ObjectClass duck-type with GetRadius+GetScale (test fakes) would lose its scaling if the body is simplified -- inferred risk, tests only. Native twin `beam_geometry.cc:173` keeps `_radius*_scale` (still correct). Docstring 118-129 must be rewritten. |
| engine/rocks/rock.py:60-70 | `effective_radius(rock)` (**HELPER**) | `base * GetScale()`, base = `GetRadius()` if >0 else `GetHull().GetRadius()` | Must read the BASE for the >0 test and the hull fallback: `base = GetBaseRadius(); if base<=0: base = hull radius; return base*GetScale()`. Using new `GetRadius()` as base would DOUBLE-scale. Native twin `sensor_detect.cc:433` reads raw `_radius` -> unchanged/correct. |
| engine/appc/camera_modes.py:269-292 | `_target_radius(obj, default)` (**HELPER**) | rock -> `effective_radius`; else `world_radius` | No change needed (rides on the two helpers). Docstring 271-273 ("GetRadius() is unscaled SDK surface") goes stale. |
| engine/appc/planet.py:169-207 | `aggregate_suns_for_renderer` | `radius = GetRadius()`; out `radius * scale`, `corona = radius * _CORONA_SHELL_RATIO * scale` | Either use `GetRadius()` (scaled) and drop `* scale`, or keep `GetBaseRadius()*scale`. Suns are never scaled (no SDK/engine SetScale), so latent only; but leaving it as-is DOUBLE-scales a scaled sun. |
| engine/host_loop.py:7161-7177 | `realize_set_objects` (planet branch) | `radius = planet.GetRadius()`; `natural_scale = radius / sphere_radius`; then `_apply_live_world_transform(..., natural_scale)` multiplies by `GetScale()` again | **Must become `GetBaseRadius()`**, else render = base*s/sphere * s (double scale). Latent: planets never scaled. |
| engine/host_loop.py:8477-8493 | `HostController._realize_session` (planet loop) | identical to above | identical: **`GetBaseRadius()`** |
| (beneficiary) engine/appc/objects.py:379-400 | `ObjectClass._random_point_on_model` fallback | `radius = self.GetRadius()` with docstring "GetRadius() is already world-scale" -- currently FALSE for scaled objects | becomes correct with no edit |

###### Helper caller lists

`collisions.world_radius` -- 15 call sites (plus 2 native guard lists):
| caller | function |
|---|---|
| engine/appc/collisions.py:156 | `contact_radius` (itself a helper, below) |
| engine/appc/collisions.py:293 | `_resolve_body` (fills `_Body.radius`, consumed by broadphase `resolve_collisions:1167`) |
| engine/appc/collisions.py:377, :381 | `_deepest_piece_overlap` (cull radius for `hull_spheres_near`) |
| engine/appc/combat.py:135 | `_resolve_hit_point` (sphere fallback) |
| engine/appc/combat.py:972 | `bubble_bound_radius` |
| engine/appc/camera_modes.py:288 | `_target_radius` |
| engine/appc/collision_avoidance.py:388 | `_avoid_objects` |
| engine/appc/collision_avoidance.py:487 | `_test_course_override` |
| engine/appc/collision_avoidance.py:846 | `_build_obstacle_snapshot` |
| engine/appc/projectiles.py:1019, :1041 | `update_all` (hull sphere hit, ray backoff) |
| engine/appc/splash_damage.py:71 | `apply` |
| engine/appc/splash_damage.py:99 | `_impact_point` |
| engine/appc/native_combat.py:4717, :5801 | `_K2_FUNCTIONS` / `_K3_FUNCTIONS` identity-snapshot lists (function identity, not value -- an edited body is fine; inferred from "stands in for" comments) |

`collisions.contact_radius` -- 3 sites: `collisions.spheres_clear:190` (x2), `debris_chunk._release_parent_mask_if_clear:119`.

`rocks.rock.effective_radius` -- 5 sites: `camera_modes._target_radius:285`, `sensor_occlusion._major_rocks:128`, `rocks.minors._effective_radius:100` (seam; its caller `minors.halo_spec:162`), `rocks.death._break_up:213`; plus native twin `sensor_detect.cc:433`.

`camera_modes._target_radius` -- 9 sites: `cameras/zoom_fit.target_extent:35`, `cameras/director.py:257` (`_GhostTarget`), `cameras/tracking.py:207`, `camera_modes.py:315, :417, :721, :1036, :1055`.

##### A.2 Scale used for a NON-radius quantity (unchanged)

| file:line | function | computes | after |
|---|---|---|---|
| engine/appc/combat.py:313-341 | `_hull_box_for(ship)` (**HELPER**) | cached `_shield_hull_box` (centre, half) x `GetScale()` | unchanged (hull box, not radius). Callers (7 Python): combat.`shield_bubble_entry:428`, `_shield_face_from_hit_point:565`, `bubble_bound_radius:982`; collisions.`_bubble_contact:470`, `resolve_collisions:1178`; cameras/zoom_fit.`target_extent:37`; native guard lists native_combat.py:4715/5799/6251. |
| engine/appc/hull_bounds.py:150 | `hull_spheres_world` | piece centre and piece radius x scale | unchanged (hull-piece cache, not `_radius`). Caller: `point_is_inside_hull:241`. |
| engine/appc/hull_bounds.py:201 | `hull_spheres_near` | same, body-frame cull | unchanged. Callers: collisions.py:376/380, collision_avoidance.py:602. |
| engine/appc/hull_bounds.py:343-369 | `bound_radius` | memoised piece reach x scale | unchanged (piece-derived, not GetRadius). Caller: collision_avoidance.`_build_obstacle_snapshot:853`. |
| engine/host_loop.py:6616-6645 | `_ship_world_matrix(ship, natural_scale)` | render matrix scale `natural_scale * GetScale()` | unchanged. Callers host_loop.py:7098, :8403 (`BC_MODEL_SCALE`). |
| engine/host_loop.py:6689-6706 | `_apply_live_world_transform` | render matrix `natural_scale * GetScale()` | unchanged; but the planet `natural_scale` fed in at 7175/8491 must be computed from the BASE radius (A.1). Callers 7175, 8491, 10233, 10276. |
| engine/host_loop.py:10205-10213 | `_sync_instance_transforms` (player, interpolated) | render matrix `model_scale * GetScale()` | unchanged |
| engine/host_loop.py:10247-10260 | `_sync_instance_transforms` (NPC ships) | render matrix `model_scale * GetScale()` | unchanged |
| engine/appc/part_detach_render.py:155-166 | `_copy_render_state` | severed-part chunk render matrix `BC_MODEL_SCALE * GetScale()` | unchanged |
| engine/appc/debris_chunk.py:162 | `spawn` | stores parent `GetScale()` as chunk's render scale; chunk radius comes from native part bounds (`hull_breakup:177` `c["radius_gu"]`, `part_detach_render:103` from box half-extents), NOT GetRadius | unchanged |
| engine/appc/subsystems.py:133-146 | `body_point_world` (**HELPER**) | mount/aim point x scale, rotate, + pos | unchanged. Callers: `subsystems.target_offset_world:128`, `projectiles.py:1174` (`_steer_point` baked offset). |
| engine/manual_aim.py:195-202 | `update` | pick offset / scale -> unscaled target offset | unchanged |
| engine/appc/hull_breakup.py:323-328 | `_ship_scale` (**HELPER**) | point x scale for `structure_part_at`, cache key | unchanged. Callers: `_in_piece:246`, `_lookup_part:316`, `:365`. |
| engine/ui/spv_decals_pane.py:116-124 | `instance_scale` (**HELPER**, ObjectClass receiver) | `BC_MODEL_SCALE * GetScale()` render/body-unit factor | unchanged. Callers: spv_decals_pane.py:137, :682; spv_edit_targets.py:1079; spv_running_lights_pane.py:761. |
| engine/quickbattle/sim_restore.py:228 / :324-325 | `_record` / `_rebuild` | records `GetScale()`, re-applies `SetScale(record.scale)` after `CreateShip` | unchanged (copies scale only; radius is re-seeded at realise as a base value) |
| engine/rocks/rock.py:205-208 | `RockClass_Create(exact_radius=True)` | `SetScale(radius_gu / r_q)` | unchanged (scale writer; see B) |

##### A.3 N/A (non-ObjectClass receivers or unrelated `_scale` names)

- engine/appc/tg_ui/widgets.py:344 `self._scale` -- UI widget.
- engine/ui/ship_property_viewer.py:41 / decal_editor.py:39 `_scale(a, s)` -- vector helpers.
- engine/ui/ship_property_viewer_panel.py:1696 `src.get_scale()` -- SPV edit source.
- engine/host_loop.py:10354 `_scale` local -- CEF viewport scale.
- renderer `set_emissive_scale`, `set_bridge_ambient_scale`, bridge_lighting ambient scale, host_loop 2486 `GetCoreScale` (phaser bank), tractor `end_width_scale` -- unrelated.
- host_loop.py:7513-7586 `_celestial_matrix` / `celestial_scale` -- map bodies (not ObjectClass), `radius_gu / sphere_radius`.
- engine/appc/debris_chunk.py:93 `DebrisChunk.GetScale` -- not ObjectClass (its own field).
- Native renderer `model_radius * scale` (frame.cc:500/1394, hull_interior_policy.cc:19, atmosphere_pass.cc:55, sun_pass.cc) -- render instance scale, not `_radius`.

#### B. Every writer of `_radius` on ObjectClass-family objects

| file:line | receiver | value written | intent | conflict? |
|---|---|---|---|---|
| engine/appc/objects.py:96 | any ObjectClass (`__init__`) | `0.0` | base (unset) | no |
| engine/appc/objects.py:213-214 | `ObjectClass.SetRadius` (the only writer API) | `float(r)` | -- | becomes the base setter; consider renaming/aliasing `SetBaseRadius` since BC has no ObjectClass.SetRadius |
| engine/host_loop.py:6549-6568 | `_seed_ship_radius` -> ship / rock (ShipClass/RockClass) | `extent * BC_MODEL_SCALE` (ship: AABB corner distance; rock: bound-sphere radius) -- model-derived at GetScale()==1 | **BASE** (docstring: "Both are unscaled: the collision and hit code multiply by GetScale()") | No value conflict. Guard `if ship.GetRadius() > 0.0: return` -- with scaled GetRadius, `>0` is unchanged for scale>0; for `scale == 0` (allowed by SetScale) a set radius would read 0 and be re-seeded/overwritten (inferred edge). Prefer `GetBaseRadius()` in the guard. Callers: realize paths (via `_realize_session`/`realize_set_objects`, inferred) and `_seed_quickbattle_ship_radius` (host_loop.py:8293-8330). Runs AFTER any SDK SetScale (E1M2/E2M1 rocks are scaled right after CreateShip, before realise) -- writing base after scale is correct. |
| engine/host_loop.py:8293-8330 | `_seed_quickbattle_ship_radius` (registered via `spawn.set_radius_fn`, host_loop.py:8172; cleared 13899) | delegates to `_seed_ship_radius` | **BASE** | guard `ship.GetRadius() > 0.0` same note as above |
| engine/host_loop.py:7163-7166 | `realize_set_objects` -> Planet/Sun | `extent * BC_MODEL_SCALE` when `GetRadius() <= 0` (AABB corner, NOT the sphere radius) | base == world (planets unscaled) | guard reads GetRadius (fine at scale 1). The READ after it (7167) is the double-scale risk in A.1. |
| engine/host_loop.py:8479-8482 | `_realize_session` -> Planet/Sun | same | same | same |
| engine/appc/planet.py:27 | `Planet.__init__` (via `Planet_Create(radius, model)` planet.py:89-95 and `Sun_Create` planet.py:98-119) | SDK-authored radius (e.g. 200.0) | BC: the drawn/world radius (render_scale = radius / NIF bound, per host_loop.py:6535-6541). base == world because scale is 1 | no (latent only if a planet/sun were SetScale'd: none are) |
| engine/systems/apply_map.py:229 | `apply_to_set` -> named map bodies (planets/moons in the region set) | `body.radius_gu` (system-map authored size) | **WORLD** (the size the body is drawn and targeted at) | conflict only if scale != 1; never happens for planets (inferred: body_names are planets/moons) |
| engine/systems/apply_map.py:174-199 | `_rescale_sun` -> Sun | `radius_gu` (map star radius); READS `old_radius = GetRadius()` to keep atmosphere ratio | **WORLD** | read-modify-write of the ATMOSPHERE (ratio), not of `_radius`; with scaled GetRadius the ratio is atmo/(base*s) -- only differs for a scaled sun (none). Not compounding. |
| engine/systems/apply_map.py:241-249 | `Sun_Create(star.radius_gu, ...)` | map radius | WORLD == base at scale 1 | no |
| engine/rocks/rock.py:195 | `RockClass_Create` -> RockClass | `r_q = stats.quantise_radius(radius_gu)` (catalogue-quantised size) | **BASE** (model is loaded so it draws at r_q x GetScale; `_render_load_scale`) | no. Written BEFORE `SetScale` at :208 (only when `exact_radius`), so world = r_q * (radius_gu/r_q) = radius_gu as intended. Callers: `DamageableObject_Create` rock.py:239 (stock size from `_STOCK_RADIUS_GU`), rocks/death.py:251 (breakup pieces, `p.radius_gu`), rocks/promotion.py:153 (`exact_radius=True`). |
| engine/rocks/rock.py:147 | `_install_hull` -> **HullSubsystem** (N/A: subsystem `_radius`) | r_q | base | N/A, but it is `effective_radius`'s fallback base, multiplied by scale -- keep it base |
| engine/dev_missions/felix_destroy.py:85-91 | `_seed_radius` -> ShipClass (headless only) | `NOMINAL_HULL_RADIUS_GU = 4.0` when `GetRadius() <= 0` | nominal; base == world (no scale in these missions) | no |
| engine/dev_missions/combat_stress.py:233 | ring ships (headless only) | `_NOMINAL_HULL_RADIUS_GU = 4.0` when `GetRadius() <= 0` | same | no |
| engine/dev_missions/combat_stress.py:256 | player (headless only) | 4.0 | same | no |
| engine/appc/projectiles.py:307-318 | `Torpedo._radius` property (ObjectClass subclass) | only written by `ObjectClass.__init__` (0.0); no other writer found in engine/ or SDK (inferred: mods could call SetRadius) | base | Torpedo inherits GetRadius -> becomes `_rad * _scale`; `_scale` is never set on a torpedo (1.0). Note `_scale` IS still a NativeField on a torpedo but with no `_nslot` it only stores to `__dict__` (native_combat.py:651-661). No conflict. |
| engine/appc/ai.py:1267 | `ProximityCheck.SetRadius` | `_proximity_radius` | N/A (does not touch `_radius`). A new base-class `GetBaseRadius()` would return ProximityCheck's unused `_radius` (0.0), not its trigger radius -- decide whether ProximityCheck should override it. |

##### B N/A writers (filtered out)

- Subsystem `_radius`: engine/appc/subsystems.py:403, :936 (`ShipSubsystem.SetRadius`); ships.py:1691 `subsystem.SetRadius(rad)`; rocks/rock.py:147 hull.
- Properties: properties.py:280/294 (`BlinkingLightProperty`); hardpoint_overrides.py:33-209 (subsystem properties), :733-766 (running lights); hardpoint_override_writer.py:498 (emits text), :102 `_LightRecorder`.
- Events: combat.py:940 `evt.SetRadius` and events.py:440 (`WeaponHitEvent`).
- Cameras: cameras/director.py:42 `_GhostTarget._radius` (already world radius from `_target_radius`).
- Docstring-only: host_loop.py:7487, rocks/rock.py:100, systems/render_scope.py:22.

##### Read-modify-write / ordering

- **No engine writer computes a new `_radius` from `GetRadius()`** (no compounding inside engine/). All guards are `GetRadius() <= 0` / `> 0` tests only.
- `_rescale_sun` reads GetRadius() for a ratio (atmosphere only; see table).
- Writers that run AFTER a SetScale: `_seed_ship_radius` / planet seed at realise after an SDK `SetScale` (E1M2, E2M1, Multi1, Multi6 rocks; DockWithStarbase only runs much later). They write a BASE value, which is what they intend -> correct.
- **SDK read-modify-write that the change FIXES:** `AI/Compound/DockWithStarbase.py:47-50`:
  `if pShip.GetRadius() > 4.0: ... pShip.SetScale(pShip.GetScale() * 4.0 / pShip.GetRadius())`.
  BC (scaled GetRadius): new scale = s*4/(b*s) = 4/b -> world radius exactly 4.0, idempotent. Ours today (unscaled): new scale = 4s/b -> world 4s, and the `> 4.0` gate tests the unscaled radius. After the change both match BC. Restore at :235 is a plain saved-scale write.

#### SetScale call sites (engine/)

| file:line | receiver | value |
|---|---|---|
| engine/rocks/rock.py:208 | RockClass (`RockClass_Create(exact_radius=True)`: rock promotion) | `radius_gu / r_q` |
| engine/dev_missions/far_tier_field.py:57 | RockClass ("Far Tier Test Rock", `CreateShip("Asteroidh1")`) | `ROCK_SCALE` |
| engine/quickbattle/sim_restore.py:325 | rebuilt unowned real object (ShipClass/RockClass via `loadspacehelper.CreateShip`) | recorded pre-battle scale |
| engine/appc/objects.py:219 | definition | -- |

**Planets, suns, torpedoes: never SetScale'd (engine or SDK). Player ships: YES, by SDK `DockWithStarbase.py:50` (shrink to 4 GU world radius) and restored at :235.** Also any ship can be rescaled through sim_restore if it was scaled pre-battle (inferred: rocks in practice).

#### Conflicts and required edits

| # | Severity | Site | Problem after the change | Fix |
|---|---|---|---|---|
| C1 | **real, native/Python divergence** | engine/appc/damage_eligibility.py:31-32 `_radius(ship) = GetRadius()` vs native twin `native/src/combat/src/k4_eligibility.cc:80-104` reading raw `r->_radius` | Python becomes scaled, K4 stays base -> different eligibility scores for any scaled ship (docking player, E1M2/E2M1 rocks if in the ship list); K4 differential tests would catch it (inferred) | decide intent: either Python uses `GetBaseRadius()` (no behaviour change) or the K4 kernel uses `_radius * _scale` |
| C2 | latent double-scale | host_loop.py:7167 and :8483 planet `natural_scale = GetRadius()/sphere_radius` then x `GetScale()` | double scale for a scaled planet | use `GetBaseRadius()` |
| C3 | latent double-scale | planet.py:169-207 `aggregate_suns_for_renderer` `radius*scale` | double scale for a scaled sun | drop `* scale` or use base |
| C4 | double-scale | rocks/rock.py:66-70 `effective_radius` `GetRadius()*GetScale()` | E1M2 rocks (scale 3-8.5) would be 9-72x | use base for the >0 test + fallback |
| C5 | double-scale | collisions.py:130-143 `world_radius` | every scaled ship/rock double-scaled in collisions, combat, avoidance, splash, cameras, projectiles | reduce to `GetRadius()` (keep DebrisChunk rule) |
| C6 | edge | `_seed_ship_radius` / QB seed / planet seed guards `GetRadius() > 0` | for `GetScale() == 0` a seeded radius reads 0 and would be re-seeded (inferred, not seen in practice) | guard on `GetBaseRadius()` |
| C7 | design | `ProximityCheck` inherits a new `GetBaseRadius()` returning `_radius` (0.0) | may surprise a caller | override or document |
| C8 | docs | docstrings that say "GetRadius() is unscaled": collisions.py:118-129, :198, :369-373, :1066-1067; combat.py:133, :969; camera_modes.py:271-275; rock.py:61-65; host_loop.py:6550-6560, :6620, :6737; projectiles.py:899, :1015; region_hooks.py:16; apply_map.py:14-15; sensor_occlusion.py:5; `docs/reference/engine/native-combat/can-detect-inputs.md:193`; native comments `beam_geometry.h:77`, `sensor_detect.cc:434` ("float(rock.GetRadius())" -> now GetBaseRadius) | stale prose | update |

##### Bare `GetRadius()` readers whose VALUE changes for scaled objects (seen in passing; not the scope of this audit, not exhaustive)

These read GetRadius() alone and will now see the scaled radius (BC-faithful, but a behaviour change for the docking player and scaled rocks): damage_eligibility.py:32 (C1); host_loop `_reconcile_camera_radius` / chase `set_ship_radius` (chase framing of the docking player); warp_state.py:48/57; warp_flight.py:178; warp_core_breach.py:105; shuttle_service.py:1024/1091; quickbattle/spawn.py:222/331/404/410/413 and late_arrivals.py:267/270 (placement spacing; scale 1 at spawn); rocks/death.py:267 (piece radius, scale 1 for non-exact pieces); DockWithStarbase.py:47/50 (fixed, above).

---

## Annex D. Native consumers of radius and scale


Snapshot: `project/combat_threading` @ `2369cba41`. Read-only.
proven by reading the cited lines unless marked **(inferred)**.

Classes:
- **DRAWN**: wants the world (scaled) size. With the change it should read `_radius * _scale` (or the guarded form).
- **BASE**: wants the unscaled radius.
- **DOUBLE**: already multiplies the mirrored base `_radius` by `_scale`. It would double-scale if the pushed radius became scaled. If base `_radius` stays pushed, it is already correct and **unchanged**.
- **N/A**: reads `_scale` for something other than the radius (hull box, body points), or reads a *subsystem* radius.

---

#### 1. How `_radius` / `_scale` reach C++

| Where | What |
|---|---|
| `engine/appc/objects.py:80-81` | `ObjectClass._radius = NativeField(float)`, `_scale = NativeField(float)`. `NativeField.__set__` (`native_combat.py:651-662`) stores the raw attribute value in `obj.__dict__`, then pushes it with `_h.combat_push_scalar(h, fid, code, value)` (`native_combat.py:664-677`). The field id is `_fid(self._key)`, and the key is the **attribute name** (`"_radius"`, `"_scale"`). Writes from other threads queue `_repush_native`. |
| `engine/appc/objects.py:210-220` | `GetRadius` returns `self._radius`, `SetRadius` writes `self._radius`, `GetScale` / `SetScale` likewise for `_scale`. So the mirror holds whatever was written to the attribute, which today is the BASE radius. |
| `engine/appc/subsystems.py:334` | `ShipSubsystem._radius = NativeField(float, key="Subsystem._radius")`. This is a **separate** field (`Field::s_radius`). `ShipSubsystem` derives from `TGEventHandlerObject`, not `ObjectClass` (`subsystems.py:326`), and its `GetRadius` is its own (`:932`). **Not affected by the change.** |
| `native/src/combat/src/mirror.cc:32-34, 63` | Field table: `{"_radius", Object, F}`, `{"_scale", Object, F}`, `{"_radius", Subsystem, F}`. |
| `native/src/combat/include/dauntless/combat/mirror.h:47, 66, 162, 198, 242` | Enum `Field::o_radius`, `Field::_scale`, `Field::s_radius`. `ObjectRow` holds `double _radius = 0.0, _scale = 1.0;` (:198) and `SubsystemRow` holds `double _radius` (:242). |
| `native/src/combat/src/mirror.cc:281-282, 344` | Field-to-member mapping: `o_radius -> ObjectRow::_radius`, `_scale -> ObjectRow::_scale`, `s_radius -> SubsystemRow::_radius`. |
| `native/src/host/host_bindings.cc:12610-12618` | Python-name-to-field-id map. `s_radius` is keyed `"Subsystem._radius"`, everything else by its table name. |
| `engine/appc/projectiles.py:308-318`, `native_combat.py:2918` | `Torpedo._radius` is a property (`_rad`). Torpedoes have **no** Object row, and `torpedo_table.h` has no radius field, so the change does not reach them natively. |
| `native_combat.py:4731-4732` (`_K2_OBJECT_NAMES`), `:5509-5511` (`_STEP_SHIP_PATCHES`), `:5786-5788` (K3 comment), `:6119-6122` (`_DMG_SHIP_NAMES`: GetScale only) | Method-identity and instance-patch guards. `GetRadius` and `GetScale` are snapshotted, and a patched class or instance sends the step to Python. **If the Python twins move to a new base accessor (for example `GetBaseRadius`), add that name to `_K2_OBJECT_NAMES` and `_STEP_SHIP_PATCHES`.** Otherwise a patched base accessor would no longer route to Python. **(inferred: the requirement follows from the guard design; no test exercises it yet)** |
| `native_combat.py:5658` | The K4 snapshot pins `damage_eligibility._radius`. A redefinition of that function is caught. |

##### Other radius/scale values that cross into C++ (outside the combat mirror)

| Python site | Binding | Expression | Class | Becomes |
|---|---|---|---|---|
| `engine/host_loop.py:7163-7176`, `:8479-8492` (planet realize) | `set_instance_transform_slot` / `set_world_transform` via `_apply_live_world_transform` (`:6688-6705`) | `natural_scale = planet.GetRadius() / sphere_radius`, then the draw scale is `natural_scale * GetScale()` | **DOUBLE**: a SetScale'd planet would draw at r·s² | Use the base accessor (`GetRadius() > 0` / `SetRadius` seeding at `:7163` / `:8479` should use it too). Draw scale is gameplay-radius-derived **only for planets**: ships use the flat `BC_MODEL_SCALE` (`:6740-6743` comment). |
| `engine/host_loop.py:6561` `_seed_ship_radius` | (SetRadius only, not a push) | `if ship.GetRadius() > 0.0: return` | BASE (sign test) | Base accessor, or keep: same answer for scale > 0. |
| `engine/host_loop.py:5514` `_aggregate_planets` | dust pass planet feed `{position, radius}` (`_aggregate_dust_planets`, `:5568`) | `obj.GetRadius()` | DRAWN | Becomes scaled automatically. That is correct if a planet is ever scaled. |
| `engine/ui/target_reticle.py:99-119` | `set_target_reticle(ship_radius=)` -> `native/src/renderer/target_reticle_pass.cc:153` | `target.GetRadius()` | DRAWN (bracket size) | Scaled automatically. Today a SetScale(3) E1M2 rock gets a reticle sized for the 1x radius **(inferred visual effect)**. |
| `engine/host_loop.py:13482` DOF | `set_dof_params` (via the Python focus solver) | `player.GetRadius()` | DRAWN | Scaled automatically. |
| `engine/appc/lens_flare.py:94,115` | `"source_radius"` key | `src.GetRadius()` | DRAWN | No native reader of `source_radius` was found (`grep` of `native/src`). **(inferred: unused natively)** |
| `engine/appc/projectiles.py:931-936` -> `:846` `transform_sweep_candidates` (`native/src/transforms/include/dauntless/transform_store.h:146-157`) | the `bounds[]` array | `bubble_bound_radius(ship)` -> `collisions.world_radius` | DOUBLE (through `world_radius`) | Stays right if `world_radius` reads the base accessor (see section 2). |
| `engine/rocks/minors.py:98-100,162` `halo_spec` | `minors_add_cloud` (halo numbers) | `rocks.rock.effective_radius(rock)` | DOUBLE (through `effective_radius`) | Stays right if `effective_radius` reads the base accessor. |
| `engine/appc/planet.py:377-392` `GetNearObjects` | `transform_within_radius` | caller-supplied `radius` | N/A (a query radius, not the object's) | Callers that pass `obj.GetRadius()` are Python-side and are not audited here. |

---

#### 2. Every read of the mirrored Object radius / scale in `native/src/combat/`

Found by `grep -rnE "_radius\b|_scale\b|o_radius|s_radius"` and by tracing every caller of `world_radius` / `bubble_bound_radius` / `effective_radius`. No read was found in k0_charging, k1_fire_control, fire_gates (its `scale` is the discharge/damage scale), torpedo_table, part_pose, step_scan, profile_eval, nebula_density (sphere radii come from `MetaNebula._spheres`, not GetRadius), stop_firing, write_log, sensor_state, or py_math (its `scale` is a local in hypot).

##### 2a. Radius reads

| file:line | expression | Python twin | class | becomes (base `_radius` + `_scale` still pushed) |
|---|---|---|---|---|
| `beam_geometry.cc:173-178` `world_radius` | `r = o._radius; s = o._scale; return (s > 0 && isfinite(s)) ? r*s : r;` | `engine/appc/collisions.py:117-142` `world_radius`: `r = float(obj.GetRadius())`, then `r*s if s>0 and isfinite(s) else r` (and the DebrisChunk rule: DebrisChunk is not an ObjectClass, `debris_chunk.py:36`, so it has no row) | **DOUBLE** | **C++ unchanged.** The **Python twin must change** `obj.GetRadius()` to the base accessor, or it double-scales. It must keep the guard: `test_native_beam_geometry.py:519-528` fuzzes `_scale` in {0, -2, NaN, ±inf} and compares hex-exact. |
| `beam_trace.cc:122-126` (K2 phaser hull trace, sphere tier) | `radius = world_radius(m, target)` | `combat.py:132-135` `_resolve_hit_point`: `world_radius(ship) if hasattr(ship,"GetRadius") else 0.0` | DOUBLE (via world_radius) | Unchanged. Follows `world_radius`. |
| `k3_projectiles.cc:757-766` (SPHERE state, hull-sphere test) | `sphere_hit(seg_cur, e.pos, world_radius(m_, e.ship))` | `projectiles.py:1019` `sphere_hit(seg_cur, ship.GetWorldLocation(), world_radius(ship))` | DOUBLE | Unchanged. |
| `k3_projectiles.cc:776-786` (aim back-off + ray reach) | `radius = world_radius(m_, e.ship); backoff = radius + seg_len; ray_max = 2*radius + seg_len` | `projectiles.py:1041` `radius = world_radius(ship) if hasattr(...) else 0.0` (+ `:1003` comment) | DOUBLE | Unchanged. |
| `projectile_geometry.cc:135-160` `bubble_bound_radius` | `radius = world_radius(m, ship)`, then `radius*(1+k)` with no box, else `max(radius, centre_len + max_semi)` | `combat.py:948-990` `bubble_bound_radius` (the C++ comment says `combat.py:916`, which is stale) | DOUBLE | Unchanged. |
| `k3_projectiles.cc:893-896` (ship cache bound) | `e.bound = bubble_bound_radius(m_, h)` | `projectiles.py:931-936` | DOUBLE | Unchanged. |
| `sensor_detect.cc:432-440` `effective_radius` | `base = rock._radius; if (base <= 0) base = hull ? hull->_radius : 0; return base * rock._scale;` | `engine/rocks/rock.py:60-70` `effective_radius`: `base = float(rock.GetRadius())`, hull fallback, `base * float(rock.GetScale())` (no guard on scale) | **DOUBLE** | **C++ unchanged.** The **Python twin must change** to the base accessor. With a scaled GetRadius the `base <= 0` test and the hull fallback would also be wrong (hull radius is unscaled and needs ×scale). Pushing a scaled radius could not express this rule. |
| `sensor_detect.cc:458-466` `_major_rocks` | `r = effective_radius(m, row); if (r >= min_r) ...` | `sensor_occlusion.py:118-128` | DOUBLE | Unchanged. |
| `k4_eligibility.cc:80-90` (E1, `max_r`) | `isfinite(r->_radius)`; `max_r = py_max(max_r, r->_radius)` | `engine/appc/damage_eligibility.py:31-32,52`: `_radius(ship) = float(ship.GetRadius())`, `max(... ) or 1.0` | **DRAWN** (today it reads the bare base radius, and the twin is bare `GetRadius()`) | **The only kernel that must change.** C++ becomes the new GetRadius expression: `r->_radius * r->_scale` (then `isfinite` on the **product**: NaN/inf scale, or 0 × inf, must fall back as Python's NaN would) if GetRadius is unguarded, or `world_radius(m, h)` if GetRadius adopts world_radius's `s>0 && finite` guard. It must match the Python bit for bit, so decide the GetRadius guard first. |
| `k4_eligibility.cc:104` (E2, size term) | `size = r._radius / max_r` | `damage_eligibility.py:56` `size = _radius(s) / max_r` | **DRAWN** | Same expression as E1. Compute it once per row into the `rows[]` loop. |
| `damage.cc:519-521` (hit's subsystem overlap) | `r_sub = stock(m, h)._radius` (**SubsystemRow**) | `combat.py:860` `r_sub = sub.GetRadius()` (a ShipSubsystem) | N/A (subsystem radius) | Unchanged. |
| `sensor_detect.cc:437` | `hull->_radius` (**SubsystemRow**, the hull fallback) | `rock.py:68-69` `hull.GetRadius()` | N/A (subsystem); the result is ×scale in the DOUBLE row above | Unchanged. |

##### 2b. `_scale` reads that are not a radius (unaffected, listed so nobody "fixes" them)

| file:line | expression | Python twin | class |
|---|---|---|---|
| `beam_geometry.cc:223-226` `shield_bubble_entry` | hull box centre/half × `(t._scale <= 0 ? 1 : t._scale)` | `combat.py:307-340` `_hull_box_for` | N/A. The box is cached at scale 1 (`host_loop.py:6517-6519`). Unchanged. |
| `damage.cc:411-416` `shield_face` | same hull-box scaling | `combat.py:_shield_face_from_hit_point` via `_hull_box_for` | N/A. Unchanged. |
| `projectile_geometry.cc:149-153` `bubble_bound_radius` box term | same hull-box scaling | `combat.py:_hull_box_for` | N/A. Unchanged. |
| `weapon_geometry.cc:277-283` `body_point_world` | `o0 = p * t._scale` (no guard) | `subsystems.py:134-147` `body_point_world` | N/A (body-frame point). Unchanged. |

##### Push base, or push scaled?

**Keep pushing the base `_radius` and `_scale` separately.** On that design the native side needs one change, in K4 (E1 + E2, three lines). Every other kernel already computes `_radius × _scale` itself, and only its Python twins (`collisions.world_radius`, `rocks.rock.effective_radius`) must switch from `GetRadius()` to the base accessor.

Pushing a scaled radius would be strictly worse:
- (a) `world_radius`'s rule (bad scale -> base) cannot be recovered from a product.
- (b) `effective_radius`'s `base <= 0` / hull-fallback rule needs the base.
- (c) The field is keyed by the attribute name and pushed on attribute write. A derived "scaled" field would need a push on **both** `_radius` and `_scale` writes, plus new audit/dump handling (`tests/unit/test_native_combat_mirror.py:134-137`, `test_native_deferred_frees.py:230-245` pin the row equal to the raw attributes).
- (d) Five DOUBLE sites would each need editing instead of one DRAWN site.

**Design decision needed before coding K4:** does the new `GetRadius()` guard non-positive / non-finite scale like `world_radius` does (`s>0 && finite ? r*s : r`)? If it does, `world_radius` can simply become `GetRadius()` for ObjectClass, K4's C++ can call `world_radius(m, h)`, and there is one rule everywhere. If it does not, NaN/0/negative scales diverge between `GetRadius()` and `world_radius`, and K4's C++ must use the raw product.

---

#### 3. C++ outside `native/src/combat` that reads an object radius or scale

| Location | Reads | Gameplay radius? |
|---|---|---|
| `native/src/host/host_bindings.cc:13090-13094` `combat_test_world_radius`, `:13116-13120` `combat_test_bubble_bound_radius` | wrap the combat functions above | Test-only bindings (used by `tests/unit/test_native_beam_geometry.py:527`, `test_native_projectile_geometry.py:297,311`, `tests/helpers/k3_fight.py:658`). |
| `native/src/host/host_bindings.cc:12610-12618` | field-name map | Plumbing only. |
| `native/src/transforms/src/transform_store.cc:106-130` `compose_world_matrix*` | per-instance draw `scale` (from `set_instance_transform_slot`) | Not GetRadius for ships (`BC_MODEL_SCALE × GetScale`). For **planets** it is `GetRadius()/sphere_radius × GetScale()` computed in Python (section 1 table): DOUBLE risk on the Python side. |
| `native/src/transforms/include/dauntless/transform_store.h:146-157` `sweep_candidates` | `bounds[]` pushed from Python | = `bubble_bound_radius` (DOUBLE via world_radius, see section 1). |
| `native/src/transforms` `within_radius` / `proximity_report` | caller r² | Query radii, not object radii. |
| `native/src/renderer/target_reticle_pass.cc:153` | `reticle.ship_radius` | = Python `target.GetRadius()`: DRAWN, becomes scaled. |
| `native/src/renderer/dust_pass.cc` (planet feed) | planet `radius` | = Python `planet.GetRadius()`: DRAWN. |
| `native/src/renderer/minor_field.cc:374-470`, `rock_near.cc:989` | `PlayerBox{world, center_mu, half_mu}`: render instance world (incl. render scale) × model AABB (`minor_field.h:86-92`) | **No.** It never sees GetRadius. Minor radii come from catalogue fragments / halo spec (`effective_radius`, DOUBLE, Python). |
| `native/src/renderer` rock fields (`rockfield_query_large` -> `h.rock.radius`, host_bindings `:9136`) | field rocks' own radii | Native-owned; flows *out* to Python (`promotion.py:153` `RockClass_Create(hit["radius"], exact_radius=True)`). Not GetRadius. |
| Ship draw scale generally | `natural_scale` = `BC_MODEL_SCALE` for ships | Not gameplay radius (`host_loop.py:6737-6743`). |

No renderer, collision or host C++ reads the combat mirror's `_radius` / `_scale` (verified by grep of `native/src` for `Field::o_radius|Field::_scale|\._radius|->_radius|\._scale|->_scale` outside `native/src/combat`: only `host_bindings.cc:12618`).

---

#### 4. Tests that pin radius/scale-based native behaviour

There is no file or test named "golden fight". The fight differentials compare a Python arm with a native arm live: `tests/helpers/{k3_fight,k0_fight,posed_fight}.py` drive `combat_stress`. The only recorded golden on this path is `tests/host/test_native_beam_trace.py:396-410` `BINDING_GOLDEN`, which is a sha256 of `ray_trace_mesh` outputs only (mesh, not radius). **It is unaffected.**

##### Scenes with SetScale'd objects

| Test | Scaled? | Native path pinned | Effect of the change |
|---|---|---|---|
| `tests/integration/test_native_can_detect_differential.py:295-334` `test_rock_field_sweep` | **Yes**: E1M2 Vesuvi 6, six `SetScale(3)` debris rocks (four major occluders) | `sensor_detect.cc effective_radius` (DOUBLE) | Breaks (Python 9×, native 3×) unless `rock.effective_radius` uses the base accessor. Probably the strongest real-scene guard. |
| `tests/host/test_native_beam_trace.py:161-171` `_pose`, `:283-296` `test_scaled_ship_matches` | Yes: scale in {1, 2.5, 0.5}, then {3, 8.5, 0.25, 0, -2, NaN, inf} | `beam_trace.cc` sphere tier -> `world_radius` | Breaks unless `collisions.world_radius` uses base + keeps guard. |
| `tests/unit/test_native_beam_geometry.py:519-528` `test_world_radius_matches` | Yes, including 0/-2/NaN/±inf | `world_radius` hex-exact | Same. |
| `tests/unit/test_native_beam_geometry.py:292, 349, 626` | Yes | shield bubble / hull box (N/A) and `world_radius` | `:626` is likely world_radius-dependent **(inferred: line not read in full)**. |
| `tests/unit/test_native_projectile_geometry.py:276-301` `test_bubble_bound_matches`, `:417-475`, `:518`, `:539` | Yes | `bubble_bound_radius` hex-exact | Same as world_radius. |
| `tests/integration/test_native_damage_differential.py:150-166` | Yes (`SetScale(scale)` on a `_radius = 3.0` ship) | `damage.cc shield_face` (hull box, N/A); subsystem overlap uses subsystem radius | Not radius-affected **(inferred: the ship radius is not read by apply_hit's native path)**. |
| `tests/unit/test_native_part_pose_geometry.py:296-358, 448`, `test_native_weapon_geometry.py:421-507`, `test_native_posed_flag.py:201`, `test_native_combat_world.py:315` | Yes | `body_point_world` / target offset (N/A) | Unaffected. |
| `tests/unit/test_native_k4_eligibility.py` (all) | **No SetScale anywhere** (radii via `SetRadius`, `:83, :141, :158, :290, :305-307`) | `k4_eligibility.cc` | Stays green either way, so **it does not pin the change.** Add cases with `SetScale` (finite, 0, negative, NaN, inf) once K4 is changed. `:279` asserts "six largest by `GetRadius()`", which follows the new GetRadius automatically. |
| `tests/helpers/k3_fight.py:173-180` | — | Recorder recomputes K4 via `de._radius` | Follows `damage_eligibility._radius` automatically. |
| `tests/host/test_native_k3_differential.py:196, 221` | combat_stress ships at scale 1 **(inferred from the scene)** | test-side aim uses `target.GetRadius() * target.GetScale()` | Test code is DOUBLE: it would aim/size the nebula at r·s² for a scaled ship. Harmless at scale 1; change it to `GetRadius()`. |
| `tests/host/test_native_k3_differential.py`, `tests/integration/test_native_{k0,k1,k3,posed,combat_step}_differential.py`, `test_native_off_lock_stress.py`, `test_native_damage_kernel_guard.py`, `tests/host/test_native_{k2,posed}_differential.py`, `test_native_combat_scene_audit.py` | combat_stress: no SetScale found (`grep` of combat_stress.py and the helpers). Radii seeded with `SetRadius(_NOMINAL_HULL_RADIUS_GU)` only when `GetRadius() <= 0` (`combat_stress.py:232-256`) | all kernels | Neutral at scale 1. `test_native_off_lock_stress.py:191` churns `_radius` / `_scale` writes from another thread (mirror plumbing only). |
| `tests/unit/test_native_combat_mirror.py:134-137`, `test_native_deferred_frees.py:230-245` | `SetScale(1.5)` / `_scale = 2.25` | row equals the raw attributes | Pins "push the base attribute". Would break if a scaled radius were pushed. |

##### C++ unit tests (`native/tests/combat/`)

| Test | Pins | Effect |
|---|---|---|
| `beam_geometry_test.cc:170-181` `WorldRadiusScalesOnlyForAFinitePositiveScale` | `world_radius` = 4×2.5 = 10, bad scale -> 4 | Unchanged under base push. |
| `beam_geometry_test.cc:250-263` | bubble semi-axis underflow at scale 1e-30 | N/A. |
| `sensor_detect_test.cc:528-548` | `effective_radius` base × scale (2.0), hull fallback 3.0 | Unchanged under base push. |
| `k3_projectiles_test.cc:113-114, 1006`, `k2_beams_test.cc:99-100`, `beam_trace_test.cc:37-38`, `projectile_geometry_test.cc:50, 138`, `damage_test.cc:46, 84`, `part_pose_test.cc:267`, `mirror_test.cc:28-103` | set `o_radius` / `_scale` directly | Unchanged under base push. |
| `k4_eligibility_test.cc:32, 108` | sets `o_radius` only (scale default 1.0) | Will need scale cases after the K4 change. |

---

#### Summary of required native-side work (base-push design)

1. **`native/src/combat/src/k4_eligibility.cc:86-89, 104`**: read the world radius (`_radius * _scale`, or `world_radius(m, h)` if GetRadius adopts the guard), with the finiteness check on the result. Add scale cases to `k4_eligibility_test.cc` and `tests/unit/test_native_k4_eligibility.py`.
2. **No other C++ kernel changes.** `world_radius`, `effective_radius`, `bubble_bound_radius`, the beam-trace sphere tier and the K3 sphere/back-off are DOUBLE and stay correct, **provided** their Python twins `collisions.world_radius` (`collisions.py:132`) and `rocks.rock.effective_radius` (`rock.py:66`) switch to the base accessor (keeping world_radius's guard).
3. Guards: add the base accessor's name to `_K2_OBJECT_NAMES` / `_STEP_SHIP_PATCHES` (and the K3 comment's list) **(inferred)**.
4. Python->C++ planet draw scale (`host_loop.py:7168-7172, 8484-8488`) must use the base accessor, or a SetScale'd planet double-scales.
5. Stale comment: `projectile_geometry.cc:133` cites `combat.py:916`; the function is at `combat.py:948`. `sensor_detect.cc:432` cites `rock.py:59`; it is at `:60`.

