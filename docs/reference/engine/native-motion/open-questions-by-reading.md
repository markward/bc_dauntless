# Native motion and proximity: three open questions, settled by reading

**Status:** static reading only, 2026-11-03. Nothing was built, run or measured. bc_dauntless code is read from `project/combat_threading` (`2369cba41`). `.claude/worktrees/native-combat-k3` (`ws/native-default`, `5f1e67065`) has byte-identical `radiation.py`, `ai.py`, `planet.py` and `objects.py`. The SDK is read from `sdk/Build/scripts` and the clean-room reference from `stbc_reference/spec/` (its MCP server was down, so the files were read directly).

**Spec this serves:** `docs/superpowers/specs/2026-11-03-native-motion-and-proximity-design.md`: §5.2 "Check first (inferred divergence)", §8 open questions 2 and 3, and §5.1 step 1d.

**Evidence labels used below:** **stated** means the reference or the code says it in so many words. **derived** means it follows from stated facts with no extra assumption. **inferred** means it needs an assumption, which is named.

---

## Q1. Can the fused `impulse_fractions` walk ever differ from the two separate calls?

**Verdict: refuted for today's code. The fused walk always returns what the separate calls return. The gap is latent: one more writer of `_radiation_out` would open it, and no test pins it. Confidence: high.**

### The suspected gap

- `impulse_fractions` (`engine/appc/subsystems.py:3705-3768`) uses a fast path whenever `implements(ies, "GetParentShip")` (`:3749`), and every real IES takes it. Per pod, that path tests only `IsDisabled() or IsDestroyed()` (`:3755-3756`).
- `impulse_online_fraction` (`:186-209`) calls `_is_offline(pod)` (`:207`). `_is_offline` (`:150-183`) also tests:
  - the pod's own `_radiation_out is True` (`:165`);
  - the pod's parent's `_radiation_out` (`:167-169`);
  - whether the parent ship is out of action (`:180-182`).
- The fast path's comment (`:3734-3748`) explains why skipping the ship clause is safe. It never mentions the radiation clauses.

### Why the two can never differ today

1. **Parent clause.** `AddChildSubsystem` sets `pod._parent_subsystem = self` (`subsystems.py:1242-1243`), so a pod's parent is the IES. All three functions call `_is_offline(ies)` first (`:197`, `:260`, `:3728`), and that tests the IES's own `_radiation_out`. If it is set, all three return 0 before reaching any pod. Skipping the parent clause per pod is therefore exact.
2. **The pod's own flag.** Only two places write `_radiation_out` in non-test code:
   - `ShipSubsystem.__init__` sets it False (`subsystems.py:387`; the field is declared at `:333`);
   - `RadiationDriver` sets it True when an outage starts (`engine/appc/radiation.py:103`) and False when it ends (`:81`).
   Native code only reads the mirrored field (`native/src/combat/src/sensor_detect.cc:187-190`; `mirror.cc:62,402`) and never writes it back. `native_combat.py:96` is a comment.
3. **The outage pool holds top-level subsystems only.** `_maybe_start_outage` picks from `ship.GetSubsystems()` minus Hull and Power (`radiation.py:95-99`). `ShipClass.GetSubsystems` (`engine/appc/ships.py:1210-1231`) returns the twelve top-level slots (sensor, impulse, warp, torpedo, phaser, pulse, tractor, shield, power, repair, cloak, hull). It does not descend into children, and it is the only `GetSubsystems` definition in `engine/`.
   - Impulse pods are plain `ShipSubsystem`s built by `ships.py` Pass 5 (`:1592-1630`) and attached only via `parent.AddChildSubsystem(pod)` (`:1630`). They are never in a top-level slot.
   - The local-nebula path (`on_local_event` → `apply_chunk` → `_maybe_start_outage`, `radiation.py:134-170`) uses the same pool.
   - So a radiation outage can land on the **IES** (which zeroes online and output in both versions alike), but **never on a pod**. Within `engine/`, pods' `_radiation_out` stays False.

So, for every reachable state, `pod._radiation_out is True` is False, and the fast path's `disabled or IsDestroyed()` equals `_is_offline(pod)`. The fused walk and the separate calls agree. **derived**

### Test coverage

- `tests/unit/test_impulse_fractions_fused.py` does not cover radiation. Its `_Pod` double (`:15-23`) has no `_radiation_out` and no `_parent_subsystem`, so `getattr(..., False)` reads False on both paths. None of its 13 cases (`:80-94`) sets an outage on the master either.
- `tests/unit/test_radiation.py:220-225` pins `_is_offline(child)` for a child whose parent is out, but not `impulse_fractions`.
- The gap is therefore untested in both directions. A future writer that sets a pod's flag (a pool that walks children, a dev toggle, a save/restore of `__dict__`) would split the two silently.

### Why it still matters for the port

- The player's integrator still calls the **separate** `impulse_online_fraction` (`engine/host_loop.py:3400`), while AI motion calls the fused one (`engine/appc/ship_motion.py:248`). If the gap ever opened, the manual player and AI ships would disagree about the same engine.
- **Recommendation (not a ruling):** the native kernel reads the mirrored `_radiation_out` of the pod and of the master. The mirror row already carries the field, and today the result is the same. That keeps `_is_offline` the single definition. Pin it with one new case in `test_impulse_fractions_fused.py`: a pod double with `_radiation_out = True`, asserting fused == separate. That case fails on today's fused code. Either add the same clause to the Python fast path, or record the case as a deliberate difference, in that commit.

---

## Q2. Where does an attached ProximityCheck sit, and does anything read that position?

**Verdict: confirmed. An attached check's own `GetWorldLocation()` is its own transform slot: the set origin unless something calls `SetTranslate`. It does not follow its anchor, whereas in BC it does. The per-tick evaluation is unaffected because it centres on the anchor. Only the proximity queries read the check's own position, and after ruling 1 (queries drop checks) nothing in the engine or the SDK reads it except the anchorless case, which is correct. Confidence: high on our side; medium-high on BC's side (the reference states the scene-graph parenting; that the parented world position is what the index uses is inferred).**

### Ours

- **AttachObject only records the anchor.** `ObjectClass.AttachObject` (`engine/appc/objects.py:547-558`) sets `obj._anchor = self` for a ProximityCheck and nothing else. `DetachObject` (`:560`) and `UpdateNodeOnly` (`:541-542`) do nothing. `Planet.AttachObject` (`engine/appc/planet.py:65-71`) adds only an `_attached` list, which only `GetAttachedObjects` reads (`:78-79`). Nothing in `engine/` moves attached objects with their anchor: a grep for `_attached` and `GetAttachedObjects` finds only those lines.
- **A check's position is its own slot.** `ProximityCheck(ObjectClass)` (`engine/appc/ai.py:1207`) does not override `GetWorldLocation`. The base reads the object's own store slot (`objects.py:351-353`). A new slot starts at (0, 0, 0) with identity rotation, in both the Python store (`engine/appc/transform_store.py:44-56`) and the native one (`native/src/transforms/src/transform_store.cc:28-30`).
- **What writes a check's translate:**
  - E6M3's anchorless station check: `SetTranslate` + `UpdateNodeOnly`, then `ProximityManager.AddObject`, with no `AttachObject` (`Maelstrom/Episode6/E6M3/E6M3.py:654-665`).
  - SDK `DockWithStarbase`, which `SetTranslate`s every object its near query returns, except the ship and the starbase, to 300+ GU from the docking entry (`AI/Compound/DockWithStarbase.py:70-107`).
  - No other site found. The three attach sites (`Conditions/ConditionInRange.py:196-226`, `MissionLib.py:200-207`, `E6M5.py:481-499`) never translate the check.
- **The per-tick evaluation centres on the anchor.**
  - `ProximityCheck._centre` (`ai.py:1364-1376`) returns `self._anchor.GetWorldLocation()` when an anchor exists, and its own location only when it does not.
  - `_evaluate_one` (`:1434-1512`) measures from `_centre()`. The compare is `<= r²` at `:1491`.
  - The cached pair table builds each pair from `check._anchor if check._anchor is not None else check` (`engine/appc/proximity_table.py:160`), and the store-side report reads that slot.
  - So an attached check fires against its anchor's live position. The stale own slot does not affect firing.
- **The queries read the check's own slot.**
  - `ProximityManager.AddObject` puts the check in `_objects` (`planet.py:286-288`) as well as `_proximity_checks`.
  - `_candidates` appends `_objects` without the participant filter (`:359-362`).
  - `GetNearObjects` tests the check's own slot: it is `location_is_stored` (`proximity_table.py:48-58`), so the test goes through `within_radius` (`planet.py:388-394`).
  - `GetLineIntersectObjects` reads `obj.GetWorldLocation()` and adds `obj.GetRadius()` to the reach (`:443-460`). For a check, that radius is the trigger radius (`ai.py:1274-1275`). E1M1's Starbase 12 check, for example, uses 690 GU.
  - Result: queries report every attached check as a sphere of its trigger radius at the set origin.

### BC (stbc_reference)

- **AttachObject is scene-graph parenting.** **stated, BE.** `BaseObjectClass::AttachObject` (`0x00430c10`) invokes the anchor scene node's attach virtual with the child object's scene node (`spec/BaseObjectClass.md` §4.1 lines 163-170, and §5.1).
  - **inferred** (standard Gamebryo node semantics; the reference does not spell out the world-transform composition): the check's world position is then the anchor's world transform times the check's local transform, which is the identity offset at the three SDK attach sites.
- **The SDK authors relied on that.**
  - E6M5: `# Make sure the check is centered around the planet.` immediately before `pObject.AttachObject(pProximityCheck)` (`E6M5.py:494-495`).
  - ConditionInRange: `pObject1.AttachObject(self.pProx)` followed by `# Need to update it...  :/` and `self.pProx.UpdateNodeOnly()` (`ConditionInRange.py:223-226`). That call only makes sense if the check's world node is derived from its new parent.
- **The index uses the check's own position.** **stated.** A check "is registered in the manager's object table like any other world object, with its own position and radius, and it participates in the same sweep" (`spec/ProximityManager.md` lines 22-23, §3.2). A collision pair involving a check is evaluated "against the other object" (§6, §7). So in BC the check's own (parented) world position is the centre, which is the anchor's position. Our `_centre` reaches the same point by a different route. **derived**
- **Queries never return checks.** **stated.** "Both query paths of §8 test the candidate's class and skip checks" (§7 lines 224-226; §8.1 lines 236-247).
  - Counter-evidence worth recording: the SDK still filters `CT_PROXIMITY_CHECK` itself in `AI/Preprocessors.py:1660-1661` (`lDontAvoidTypes`) and `MissionLib.py:4917-4920` (`g_lWarpDontAvoidTypes`). That is consistent with defensive scripting and does not contradict the reference.

### Consequences

**Today**, an attached check's own position is read only through the two query producers. The SDK consumers handle it as follows:

| Consumer | What it does with a check | Effect |
|---|---|---|
| AvoidObstacles (`Preprocessors.py:1749-1762`) | `NeedToAvoid` discards it via `lDontAvoidTypes` | Cost only (the spec's ≈87% of returns) |
| Warp-obstacle helpers (`MissionLib.py:4930`, `:5035`) | Discard via `g_lWarpDontAvoidTypes` | Cost only |
| Intercept (`AI/PlainAI/Intercept.py:269-290`) | Reads the check's own location, then keeps only planets and large ships | Cost only |
| Helm collision alert (`Bridge/HelmMenuHandlers.py:2493-2508`) | Planet, Ship or PhysicsObject casts all fail for a check | Cost only |
| ConditionInLineOfSight (`Conditions/ConditionInLineOfSight.py:128-136`) | Matches by name only | Cost only, unless a blocking-object name ever equals a check's name |
| FireScript occlusion (`Preprocessors.py:373-395`) | Would count a check as an occluder: it filters only `CT_TORPEDO` | Dead code: stock `TargetVisible` returns at `:344-347` before reaching it, and we replace it (`engine/appc/ai_sensor_gate.py:206-223,279-282`) |
| **DockWithStarbase** (`DockWithStarbase.py:70-107`) | `SetTranslate`s every returned check to ≥ 300 GU from the docking entry | See below |

- **DockWithStarbase.** An *attached* check is moved harmlessly, because its evaluation ignores its own slot. An *anchorless* check (E6M3's pattern) within 300 GU of a docking entry would have its **trigger centre moved**. BC never does this, because its query never returns the check. No stock mission was found that combines the two: E6M3 never docks, and the DockWithStarbase users are E1M1 and E4M4.
- **After ruling 1** (queries drop checks, spec §5.1 step 1a):
  - no query returns a check, so no SDK script can read or move a check's own position through one;
  - no SDK script reads a check's `GetWorldLocation` directly (a grep for `pProx*.GetWorldLocation/SetTranslate` finds only E6M3's own `SetTranslate`);
  - the only remaining reader is `_centre`'s anchorless branch, which is the correct use.
  - The origin discrepancy then has **no observable effect**, so §8 open question 3 can close as "real but unobservable after 1a". Making `AttachObject` parent the transform is not needed for this project.
- **Two side findings**, outside this question and not checked further:
  1. `SetIgnoreObjectSize` is stored (`ai.py:1237,1277-1281`) but `_evaluate_one` never reads it. BC's evaluation subtracts the watched object's radius unless that flag is set (`ProximityManager.md` §7 step 3, lines 216-217). ConditionInRange sets the flag (`ConditionInRange.py:215`), so it matches BC. `MissionLib.ProximityCheck`, E6M3 and E6M5 never set it, so in BC those fire when the watched object's surface, not its centre, crosses the radius.
     - **inferred**: the flag's default is 0; the reference does not state the constructor default.
  2. The reference says a check "remembers what it last saw" per object and fires "on the transition" (§7 steps 2 and 4, lines 214-219), which reads as edge-triggered. Our `_evaluate_one` is deliberately level-triggered (`ai.py:1434-1461`, with SDK evidence in its docstring). The two readings conflict, and that conflict deserves its own look.

---

## Q3. BC's GetNearObjects size rule

**Verdict:**
- (a) **confirmed**: centre distance less bounding radius, within the query radius.
- (b) **partly settled**: the flag is stated to widen the near query's axis prune only, and the line query's exact test as well.
- (c) **confirmed by derivation**: GetRadius is the world bound with scale applied. That the proximity index uses that same value is inferred.
- (d) **still open**.
- (e) **still open**.

Confidence: high for what is marked stated, low for the inferences.

### What the reference states

From `stbc_reference/spec/ProximityManager.md`, graded `faithful` for the index and query paths (lines 8-11). `GetNearObjects` is wrapper `0x00614AC0`, implementation `0x005A78E0` (§8.2a line 347). `GetLineIntersectObjects` is `0x00614BB0` / `0x005A7CF0` (line 348).

- **Index entries are boxes.** "Every registered object contributes an axis-aligned bounding box; the box's two endpoints on each of the three world axes are threaded into three sorted lists" (§1 lines 43-45). Each tick "recompute its axis-aligned bounds and write the six endpoint coordinates" (§4 step 2, lines 140-141).
- **Near query broad phase.** It "sweeps all three endpoint arrays, and on each axis marks every object whose interval on that axis comes within the radius (plus, optionally, the object's own size) of the centre — skipping proximity checks. Only objects marked on all three axes are carried forward" (§8.1 lines 237-240).
- **Near query exact test.** "distance from the centre to the object's position, less the object's bounding radius, must be within the query radius" (lines 240-241). **The flag is not mentioned in the exact test.**
- **Line query.** It prunes on the single thinnest axis of the segment's box, then projects the object's centre onto the segment clamped to its ends. It compares the squared distance "against the squared sum of the object's bounding radius, its optional own size, and the query radius" (lines 243-249). **Here the flag does reach the exact test.**
- **Argument contract.**
  - `GetNearObjects(centre, radius, [includeSize])`, flag default 0.
  - `GetLineIntersectObjects(from, to, [radius = 0.0f, includeSize = 0])`.
  - The flag is "narrowed to a boolean at the call", and vectors are copied by value (§8.1a lines 268-283; §8.2a lines 360-363).
- **The iterator stores the flag.** It holds "a cursor, the size flag, and a growable array of the objects that survived" (§8.1 lines 256-257). No reader of the stored flag is described.

### Per question

**(a) The per-object near test.**
- **stated:** `|position − centre| − boundingRadius` is "within" `radius`.
- Whether the comparison is `≤` or `<` is **not stated**. Our compares are all `<=`.
- "Position" is **not stated** to be the transform translation rather than the world-bound centre. For an off-centre NIF bound these differ. Ours uses `GetWorldLocation()` (translation).
- Matches spec §5.1 1d's statement, except that the spec writes `≤` as if it were stated.

**(b) What `includeSize` adds.**
- **stated:** in the near query, the size flag appears **only in the axis prune**. In the line query, it appears **in the exact test**.
- **derived**, assuming the stated near test is complete: in the near query the flag cannot change the result. Widening a broad phase that the exact test then filters only admits candidates the exact test still judges without the flag. This needs one more assumption: that the unflagged prune is already a superset of the exact test. It is, if each interval is the box of the world bound sphere (half-extent = bounding radius), as §1 and `ObjectClass.md` §4.4 suggest (next point).
- If instead the intervals were narrower than the bounding sphere, the unflagged prune could drop objects the exact test would keep, and the flag would matter. That reading is **not supported** by the text.
- SDK callers that pass the flag:
  - near: `MissionLib.py:5035`;
  - line: `MissionLib.py:4930` and `AI/PlainAI/Intercept.py:269`.
  - All others pass nothing or 0: `DockWithStarbase.py:71`, `HelmMenuHandlers.py:2493`, `Preprocessors.py:1749` (near); `ConditionInLineOfSight.py:128`, `Preprocessors.py:373` (dead) (line).
  - So **only the two flagged line queries are affected by (d)**.

**(c) What "bounding radius" is.**
- **stated (`spec/CameraModes.md` §3.1, lines 108-121, graded faithful):** the per-object size every scaling site reads is the object's virtual at `+0xe4`. That virtual goes to the scene node's **world bound**, a sphere, and reads its radius. It is "the NIF model's bounding-sphere radius in world units, with world scale applied — exactly the value the published `ObjectClass_GetRadius` returns to script". `ObjectClass.md` line 447 agrees: `GetRadius(obj)` is `obj->(+0xe4)()` then the float at `+0x0c`.
- **stated (`spec/ObjectClass.md` §4.4, lines 223-229):** `ObjectClass::Update` recomputes "the object's world-space axis-aligned bounding box from its bounding sphere" each frame. That body is shared, unchanged, by `ProximityCheck`, `Planet`, `Sun` and others.
- **inferred:** that ProximityManager's "bounding radius" is this same `+0xe4` world-bound radius, and that its boxes are the cached world AABB. ProximityManager.md does not name the accessor. It is the obvious reading, not a stated one.
- **So BC's GetRadius includes scale. Ours does not:**
  - `ObjectClass.GetRadius` returns `_radius` (`objects.py:210-211`) and `GetScale` is separate (`:216-220`).
  - Ships are seeded at realise with the **AABB corner distance**, unscaled (`engine/host_loop.py:6507-6525`). Its docstring says "Both are unscaled: the collision and hit code multiply by GetScale()".
  - BC's value is the **bounding-sphere** radius, scaled.
  - Rocks have a separate `effective_radius = base × GetScale()` (`engine/rocks/rock.py:60-70`), written for E1M2's 3.7-8.5× rocks.
  - This divergence reaches every SDK `GetRadius()` reader, not just proximity: for example ConditionInRange's trigger radius `fDistance + pObject1.GetRadius()` (`ConditionInRange.py:214`).

**(d) What "own size" is.**
- **Still open.** The reference uses the phrase twice: §8.1 lines 238 and 247, and the "§8.1 calls it the object's own size" note in the design spec. It never defines it, and it is listed separately from "bounding radius" in the line test.
- Nothing else in `stbc_reference` (spec, model, tools) mentions `0x005A78E0`, `0x005A7CF0`, `includeSize` or an object "own size". A full-repo grep turned up only ProximityManager.md, plus `ShieldFacingDamage.md:766`, which calls `0x005A7CF0` for the phaser beam without describing the flag.
- Candidates, none supported by text: the box half-extent, a second copy of the bound radius, or a per-object size field.
- Needs a reading of `0x005A7CF0` (and `0x005A78E0` for completeness) when the reference server is back.

**(e) Result order.**
- **Still open. Not stated** for either producer.
- **inferred** from the structure:
  - The near query "marks" objects per axis and carries forward those marked three times.
  - The line query keeps a "process-global scratch array of per-object counters" (line 253), which implies indexing by object-table slot.
  - A final pass over the object table, in slot order, is the natural way to collect survivors. That would give **registration (AddObject) order**, not sweep order.
- How slots are reused after `RemoveObject` (`0x005A7720`) is not described. Whether a removal compacts, swaps the last entry in, or leaves a hole would change the order after deletions.
- Ours:
  - set members in insertion order, via `_non_torpedo` or `GetObjectList()` (`planet.py:346-358`);
  - then `AddObject` entries in registration order, deduplicated with first occurrence winning (`:359-362`).

### Comparison with ours

| Aspect | BC (reference) | Ours (`planet.py`) | Status |
|---|---|---|---|
| Near exact test | dist − boundingRadius within r (**stated**) | dist ≤ r, centre only (`:377-409`) | Diverges; ruling 4 / step 1d |
| Near: flag | prune only (**stated**); no result effect (**derived**) | accepted, ignored (`:365`, docstring `:373-375`) | Equivalent if (b)'s derivation holds |
| Line exact test | ‖clamped offset‖² vs (boundingRadius + [ownSize] + r)² (**stated**) | `≤ (r + GetRadius())²` (`:438-461`) | Matches for flag 0, if bounding radius = GetRadius; flag 1 lacks own size (open, d) |
| Line: radius default | 0.0 (**stated**) | 0.0 (`:412`) | Matches |
| Bounding radius | world bound sphere, scale applied (**stated** for GetRadius; **inferred** for the index) | `_radius`: AABB corner, unscaled; rocks have a separate scaled helper | Diverges (corner vs sphere, scale) |
| Checks in results | never (**stated**) | returned (`_objects`, `:359-362`) | Ruling 1 / step 1a |
| Compare | "within" (≤ or < not stated) | `<=` | Open, low impact |
| Order | not stated; registration order **inferred** | set insertion order, then AddObject order | Open |
| Admission | header flag bit (§3.1, **stated**) | `PhysicsObjectClass` or `GetRadius() > 0` (`:216-247`), set members only | Different mechanism, same intent |

### What this means for step 1d

1. Add the radius to the **near** exact test only, and keep `includeSize` ignored there. For the near query that is what the reference states. The line query already adds the radius.
2. Decide which radius before coding, as a separate ruling. BC uses one number, `GetRadius()`, scaled. Ours has `GetRadius()` (unscaled corner distance) and `effective_radius` (rocks, scaled). Using unscaled `GetRadius()` makes E1M2's rocks reach about 1/4-1/8 of their true size. Using `_radius × _scale` departs from the SDK-visible `GetRadius()`, which still feeds ConditionInRange and every other script. The faithful fix would make `GetRadius()` itself scaled, but that is a wider change than this project.
3. Leave the line query's flag-1 "own size" term out until (d) is read from `0x005A7CF0`. Record it as a known gap affecting Intercept and the warp-obstacle path.
