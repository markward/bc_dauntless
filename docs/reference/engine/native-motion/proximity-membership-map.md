# Proximity query table: membership map (spec §5.1 step 1c)

Branch read: `project/combat_threading` at `2369cba41`, through `git show` / `git grep`. SDK = `sdk/Build/scripts/` of the configured BC SDK.
Abbreviations: PL = `engine/appc/planet.py`, SETS = `engine/appc/sets.py`, OBJ = `engine/appc/objects.py`, NC = `engine/appc/native_combat.py`, CI = `engine/appc/contact_index.py`, PT = `engine/appc/proximity_table.py`, PRJ = `engine/appc/projectiles.py`, SD = `engine/appc/ship_death.py`, HL = `engine/host_loop.py`, LP = `engine/core/loop.py`, MH = `native/src/combat/include/dauntless/combat/mirror.h`.
Line numbers are this branch's. Anything I did not read directly in code is marked **inferred**. Nothing was run.

Goal: name every event that changes what `ProximityManager._candidates()` (PL:319-363) returns, or the order it returns it in, so a native per-set table can stay identical to it (minus ProximityChecks, ruling 1).

---

## 0. What `_candidates()` computes today (the target)

PL:338-363, in order:

1. **Set section.** If the set is a `SetClass` and `projectiles.sized_torpedo_in(pSet)` is false: `list(pSet._non_torpedo.values())`. Otherwise `pSet.GetObjectList()` = `list(pSet._objects.values())` (SETS:546-554), torpedoes included. Each member is kept if `id(obj)` is not already seen **and** `_is_proximity_participant(obj)` (PL:355-358).
2. **Manager section.** Every entry of `self._objects` (a list) whose `id()` was not seen in step 1, in list order (PL:359-362). **No participant test and no liveness test here.**

Consequences that a table has to reproduce:

- The dedupe only "sees" set members that **passed** the participant test (PL:356-357). A set member that is not a participant but is also in the manager list appears at its **manager-list** position. Since the participant test reads `GetRadius()` live, which section an object lands in can change with its radius.
- A set member stored under two keys appears once, at the first key's slot.
- An object that leaves the set but stays in the manager list moves from its set slot to its manager-list slot.
- `GetNearObjects` (PL:365-410) then filters by distance: stored objects through one `within_radius` call (`native/src/transforms/src/proximity_query.cc:18-30`, inclusive `<=`, contract off), others through `GetWorldLocation()` (skipped when `hasattr` fails or it returns `None`, PL:402-404).
- `GetLineIntersectObjects` (PL:412-462) calls `GetWorldLocation()` on **every** candidate (no `location_is_stored` split) and `reach = r + float(obj.GetRadius())`, with `reach = r` if that raises (PL:456-459).

---

## 1. Set membership: every path that changes `_objects` / `_non_torpedo`

### 1.1 The three methods are the only writers

`git grep` over `engine/`, root `App.py` and `tools/mission_harness.py` finds writes to a set's `_objects` / `_non_torpedo` only in SETS:206, :265, :269, :272, :292-293, :311-312. CI:24-39 relies on that invariant too. In tests, only `tests/test_aggregate_planets.py:9` builds an `_objects` dict by hand, on a fake set. Every other site reads (`ship_iter`, `warp.py:932/1035`, `mission_change.py:193`, HL:7743, `sim_restore.py:212`, `apply_map.py:164`, NC:530).

| Method | Lines | Effect on dict order |
|---|---|---|
| `AddObjectToSet(obj, identifier)` | SETS:200-229 | `self._objects[identifier] = obj` at SETS:206. A **new key** goes to the end. An **existing key** keeps its slot and its value is **replaced**: the previous object leaves `_objects` without any removal call, broadcast, `contact_index.on_removed` or `_containing_set` clear. Re-adding the same object under the same key changes nothing in order. Re-adding the same object under a **different** key leaves it in the dict twice. Nothing removes it from any other set first. |
| `_index_member` | SETS:262-272 | Torpedo → `_non_torpedo.pop(identifier)` (drops a non-torpedo previously under that key). Previous value was a torpedo, new is not → **rebuild**: `_non_torpedo` is rebound to a fresh dict comprehension over `_objects` (SETS:269-270). Otherwise `_non_torpedo[identifier] = obj` (same keep-the-slot rule as `_objects`). These rules keep `_non_torpedo` equal to `_objects` minus torpedoes, in the same order. |
| `RemoveObjectFromSet(name)` | SETS:277-293 | By **name**. When the key exists: `contact_index.on_removed` (:281), subscribers (:282), `ET_EXITED_SET` (:283), `sensor_contacts.on_exited_set`, `ObjectGroup` membership, then `_clear_containing_set` (:291). The dict pops happen **last** (SETS:292-293), after every handler ran. |
| `DeleteObjectFromSet(name)` | SETS:295-312 | Same as Remove, plus `broadcast_object_deleted` (:309). Pops at SETS:311-312, last. `BridgeSet` overrides it only to clear `_viewscreen` (`bridge_set.py:793-799`). |

Timing facts that matter for a hook:

- **Insert is first, broadcasts after.** SETS:206-207 mutate before `contact_index.on_added` (:216), `ship_lifecycle.publish_added`, player identity, subscribers, `ET_ENTERED_SET` (:226) and `ObjectGroup` (:228). `AddEvent` dispatches synchronously (the docstring at SETS:244-248 relies on it), so a handler that runs a proximity query, or adds or removes other objects, sees the new member already in place. A handler that raises leaves the object inserted (the `rocks/promotion.py:173-179` `finally` exists for exactly this).
- **Remove is last.** During the exit handlers the object is still in `_objects` and `_non_torpedo`. A handler that re-adds it under the same name is undone by the final pop (**inferred** from the code order; no such handler found).
- **Removal is by name.** After an object's `SetName` (OBJ:176-200), its dict key is unchanged, so `RemoveObjectFromSet(obj.GetName())` pops nothing and the object stays. Engine movers guard with `s.GetObject(ship.GetName()) is ship` (`warp.py:801`, :944; SD:256; `sim_restore.py:158`, :311). A renamed ship is therefore **not** removed from its old set and ends up in two sets (**inferred**; no live case seen).
- **Key `None`.** `MissionLib.py:3255` and :3356 call `pSet.AddObjectToSet(pTorp, None)`, so `_objects[None]` exists and a second such torpedo replaces the first in place.

### 1.2 Call sites

"Combat?" = can it fire during a fight (inside or between ticks).

| Site | What | Order effect | Combat? |
|---|---|---|---|
| `PRJ:599` (`kset.AddObjectToSet(torpedo, "Torpedo %d")`) | every torpedo launch | `_objects` append; `_non_torpedo` untouched (torpedo branch) | **yes, constantly** |
| `PRJ:635` (`expire`) | every torpedo end | pops both by name (`_non_torpedo` pop is a no-op) | **yes, constantly** |
| SDK `loadspacehelper.py:106` (`CreateShip`) and 256 SDK files / 397 calls of `.AddObjectToSet(` | ships, planets, waypoints, nebulae, grids, lights in region scripts and missions | append (new key) | yes: mission scripts spawn reinforcements from timers and events |
| SDK `.RemoveObjectFromSet(` (8 files, 19 calls), `.DeleteObjectFromSet(` (13 files, 22 calls) | e.g. `Actions/ShipScriptActions.py:40-70` (set move, or delete via a renamed warp-set entry), `AI/PlainAI/Warp.py:55`, :131 (tow-target move) | pop; re-add appends at the end of the destination | yes (AI Warp leaf runs inside `gl.ai`, LP:61) |
| SD:256 `_remove` (hulk eviction past `MAX_HULKS = 8`, SD:43, :184-195; and `retire`, SD:270-279, from `object_lifetime.py:63` and `rocks/death.py:372`) | dead ship leaves its set | pop | **yes**: `cb.death`, HL:1409, inside each combat tick |
| SD:148-182 (`advance`) | a dying ship becomes a **hulk and stays in its set** | none | — (dead ships are candidates today, up to 8 hulks) |
| HL:7729-7760 `_process_object_deletions` (called at HL:12477 in `sim.session_sync`, once per frame) | `SetDeleteMe(1)` objects (QuickBattle EndSimulation and 10 SDK files) | pop via `RemoveObjectFromSet` | per frame, after the ticks |
| `warp.py:800-803` (`_PlacePlayerAction`) | remove from every set holding it (by name), add to destination | append at the end of the destination | NPC and player warps; yes if a ship warps out mid-fight |
| `warp.py:943-946` (departure) | into BC's persistent `"warp"` set | append at the end of `"warp"` | same |
| `engine/systems/handoff.py:218-220` (`hand_off`) | player region move, in-system warp drop-out | pop + append at the end | per frame (`handoff.tick`, HL:12942; dash, HL:12930) |
| `engine/rocks/promotion.py:132`, :172 | field rock demote / promote | pop / append | per frame (`_pump_rock_promotion`, HL:12914), in rock fields |
| `engine/rocks/death.py:274` | breakup pieces | append | yes (`gl.rock_death`, LP:113) |
| `engine/quickbattle/sim_restore.py:161`, :168, :312 | battle-end restore (remove, then `AddObjectToSet` back home) | pop / append | at battle end |
| `engine/systems/shuttle_service.py:357`, :510, :527, :592, :726, :837 | Tau Ceti shuttles and their waypoints | pop / append | per tick (`gl.shuttles`, LP:101), Tau Ceti only |
| `engine/systems/apply_map.py:249`, `arrival_points.py:41`, `appc/asteroid_field.py:62`, `appc/lights.py:103`, `appc/placement.py:163`, :184, `bridge_set.py:791` | system bodies, markers, lights, viewscreen | append | set build only (**inferred**) |
| SDK `QuickBattle.py:2700-2702` (region change) | every ship: remove from old set, add to new, then `UpdateObject` (§2) | pop + append | QB region change |

### 1.3 Set lifetime and teardown

- `SetManager.DeleteSet` / `RemoveSet` (SETS:654-658) only pop the name. The `SetClass`, its `_objects` and its `ProximityManager` live on while anything refers to them. 103 SDK files call `DeleteSet`. Neither method calls `contact_index.forget_set`.
- A carry-over mission change (`engine/core/mission_change.py:176-205`) runs `DeleteSet` + `contact_index.forget_set` for every set except `"bridge"` and `"warp"`.
- A swap or reload (HL:4800 `contact_index.reset()`, HL:4824 `App.g_kSetManager._sets.clear()`; `tools/mission_harness.py:947`) drops the manager's references. The sets go when the GC collects them. The Set row is freed by its `weakref.finalize` (NC:1458-1460) at the next drain.
- `SetClass.SetName` (SETS:161-165) renames in place (QuickBattle's "Dupe", SDK `QuickBattle.py:2678`) and pushes the frame. Membership is unchanged.
- `AddSet` under an existing name orphans the old set (SETS:647-649) without touching its members.

---

## 2. The manager list (`ProximityManager._objects`)

| Method | Lines | Effect |
|---|---|---|
| `AddObject(obj)` | PL:286-303 | append if absent (`not in`: identity, because no engine object class defines `__eq__`, only `math.py:152`, :403). A ProximityCheck also goes into `_proximity_checks` and gets `_manager_set`. |
| `RemoveObject(obj)` | PL:305-307 | removes the first occurrence |
| `UpdateObject(obj)` | PL:309-314 | append if absent (BC repositions in place; ours is ensure-present) |

Callers:

- **SDK `AddObject`**, ProximityChecks only: `MissionLib.py:207`, `Conditions/ConditionInRange.py:221` (one per `ConditionInRange`, so 272 in the 64-ship fight), `E6M5.py:499`, `E6M3.py:665`. No SDK call adds a non-check.
- **SDK `UpdateObject`**: `QuickBattle.py:2726` (region change), :2830 (`GenerateShips`, every QB ship), :2915 (player). Also `Multiplayer/.../Mission5.py:1503` (a starbase).
- **Engine `UpdateObject`**: `engine/quickbattle/spawn.py:427-429` (every planned QB ship), `late_arrivals.py:328-330` (every late arrival), `sim_restore.py:172-174` (a restored object).
- **`RemoveObject`**: only `ai.py:1553` (`ProximityCheck.RemoveAndDelete`, on the **anchor's current set's** manager) and `sim_restore.py:162-164` (`_leave`). Nothing on death, eviction, delete-me, warp or set move calls it.

**Can a dead or removed object stay in the manager list? Yes.**

- **Quick Battle ships.** Every QB ship is `UpdateObject`'d into `g_pSet`'s manager at spawn. When it later leaves the set (hulk eviction, EndSimulation delete-me, a warp), it stays in the manager list, strongly referenced, so its transform slot and mirror row stay alive. It is still a candidate, at its last pose, in the manager section after every set member. While it is a hulk in the set, it is reported at its set slot.
  - This is the "dodge a hole in space" case the `_candidates` docstring (PL:330-332) says the design avoids. It holds only for ships nobody `UpdateObject`'d.
  - **Inferred** from code; I did not check whether QB recreates `g_pSet` between battles. `sim_restore._leave` removes only the objects it restores.
- **ProximityChecks.** `RemoveAndDelete` removes the check from the manager of the anchor's set **at removal time**. A check whose anchor moved set, or that has no anchor (E6M3's set-level check), stays in its original manager's list. It also stays in `_proximity_checks`, which `RemoveObject` never touches. After 1a this no longer matters for results, but the list still holds them.

---

## 3. Participant status (`_is_proximity_participant`, PL:216-247)

`isinstance(obj, PhysicsObjectClass)` → always. Otherwise `float(obj.GetRadius()) > 0.0`, and any exception → False. This applies to **set members only** (§0).

**PhysicsObjectClass classes:** `PhysicsObjectClass` (OBJ:626) → `DamageableObject` (OBJ:878) → `ShipClass` (`ships.py:8`) → `RockClass` (`rocks/rock.py:16`). A plain `DamageableObject` is created by `rocks/rock.py:237` (`DamageableObject_Create` for a non-asteroid model). The mirror's `is_ship_class` flag (NC:1969) therefore does **not** cover every physics object: a native table needs its own `is_physics` flag. Rocks change class in place (`ship.__class__ = RockClass`, `rock.py:87`, :187; `native_combat.reclassify`). That does not change physics status.

**Non-physics classes that appear in sets** (all `ObjectClass`, so all have a transform slot):

| Class | Where | Radius |
|---|---|---|
| `Planet`, `Sun` (PL:24, :82) | region scripts, `apply_map.py:249` | `Planet_Create(radius)` → `SetRadius` in `__init__` (PL:27). Overwritten by host realise `planet.SetRadius(extent × BC_MODEL_SCALE)` (HL:7165, :8481) and `apply_map.py:198`, :229 (`radius_gu`). **Changes after insertion.** Headless keeps the SDK value. |
| `Torpedo` (PRJ:28) | PRJ:599, `MissionLib.py:3255` | `_radius` is a property over `_rad` (PRJ:307-319). Nothing in the engine or stock SDK gives a torpedo a radius: the SDK's only `.SetRadius(` callers outside hardpoints are ProximityChecks (`MissionLib.py:216`, `ConditionInRange.py:102`, :214, E6M5, E6M3). |
| `Nebula` / `MetaNebula` (`App.py:382`, `nebula.py:16`) | SDK nebula setup | never set (0), so not a participant |
| `AsteroidField` (`asteroid_field.py:13`) | `:62` | `_field_radius` only; `_radius` 0, not a participant |
| `Waypoint`, `PlacementObject`, `LightPlacement` (`placement.py:19`, :99; `lights.py:74`) | placements, lights | 0 |
| `GridClass` (`App.py:387`) | every region | 0 |
| `ProximityCheck` (`ai.py:1207`) | manager list only; never `AddObjectToSet` (grep) | `GetRadius` **overridden** to the trigger radius (`ai.py:1274`) |
| `CharacterClass`, `STMenu` (`characters.py:440`, :141) | bridge set | 0 |
| `BridgeObjectClass`, `ViewScreenObject` (`bridge_set.py:51`, :86) | bridge set, not `ObjectClass` | no `GetRadius` / `_LoudStub` → `None` → exception → False |

`Backdrop`s go to `_backdrops` (SETS:498-502) and cameras to `_cameras`. Neither is in `_objects`.

**Radius writers** for `ObjectClass` objects: `OBJ:213-214` `SetRadius`. Callers: HL:6566 (ship realise, `r × BC_MODEL_SCALE`), `rocks/rock.py:147`, :195, `dev_missions/combat_stress.py:233`, :256, `felix_destroy.py:89`, and the planet sites above. Headless ships keep radius 0, which is why physics objects bypass the radius test. That radius is also the line query's reach.

---

## 4. `location_is_stored` false cases (PT:48-58)

It is true iff the object has a `__dict__` holding `_xform`, has no instance-level `GetWorldLocation`, and `type(obj).GetWorldLocation is ObjectClass.GetWorldLocation`.

Classes that define their own `GetWorldLocation`:

| Class | Line | Set member / AddObject'd? |
|---|---|---|
| `DebrisChunk` (not `ObjectClass`; `_loc`) | `debris_chunk.py:86` | **no**: no `AddObjectToSet` or `AddObject` call anywhere. It is a collision body (`collisions.iter_collidables`) only. |
| `ShipSubsystem` (not `ObjectClass`) | `subsystems.py:1028` | no |
| `CameraObjectClass` (`_LoudStub`) | `bridge_set.py:485` | cameras go to `_cameras`, not `_objects` |
| `_ObjectNodeRef` | OBJ:50 | no (a node handle) |
| camera director target | `engine/cameras/director.py:44` | no |
| reticle helper | `engine/ui/target_reticle.py:63` | no |

Also false: anything without `_xform` (`BridgeObjectClass`; `ViewScreenObject`, whose `_LoudStub` `GetWorldLocation` returns `None` and is skipped). These are bridge-set members, never in a space set. No engine code assigns an instance `GetWorldLocation` (grep `.GetWorldLocation = `: none), and `_xform` is assigned once (OBJ:103). Torpedoes have `__slots__` but still a `__dict__` holding `_xform`, so they are stored.

**Conclusion (inferred from the grep):** in a space set in a fight, no candidate is non-stored. The per-entry "ask Python" marker exists only for mods and tests.

---

## 5. `GetRadius` overrides (the line query's reach)

`def GetRadius` exists at `OBJ:210` (base: `_radius`, unscaled), `ai.py:1274` (ProximityCheck: trigger radius), `debris_chunk.py:90`, `subsystems.py:932`, `properties.py:296`, `events.py:439` (an event), `director.py:46`. No `GetRadius =` assignments. Of these, only **ProximityCheck** is ever a candidate, and 1a removes it. `RockClass` and `ShipClass` do not override, so every remaining candidate's reach is the mirror's `_radius`. That is pushed by `ObjectClass._radius = NativeField(float)` (OBJ:80) on every write, but only while the switch is on (NC:1461-1462 pushes at register when on; enabling resyncs every row). The flag "class overrides `GetRadius`" is stable per class except under `__class__` swaps, and the only swap (ShipClass → RockClass) does not change it.

---

## 6. Torpedoes

- `sized_torpedo_in(pSet)` (PRJ:434-442) scans the global weak `_sized` set (PRJ:431) for `t._cset is pSet`. `_sized` gets a torpedo only from the `_radius` setter with `r > 0` (PRJ:312-319), so in stock play it is always empty (§3).
- With a sized torpedo present, the set section is the **full** `_objects` order: torpedoes interleaved, unsized ones dropped by the participant test, the sized one kept.
- **Confirmed: torpedoes have no Object row.** `register` returns early when `_hidden_fields(type(obj))[1]` is non-empty (NC:1445-1446). Torpedo hides the mirrored scalar `_radius` (NC:1402-1431; PRJ:307), and it also hides `_containing_set` (a ref, PRJ:321). `_velocity` is not hidden because Torpedo is not a `PhysicsObjectClass`.
- Torpedoes are mirrored instead in K3's torpedo table, kept in `projectiles._active` order (`torpedo_row_add`, NC:3195-3205). That table carries no radius and is not set-ordered.
- I found no other class that hides a mirrored scalar (grep for class-level or property shadowing of `_radius`, `_scale`, `_velocity`, `_dead`, `_dying`, `_life_time`, `_splash_damage*`: only Torpedo). So every other `ObjectClass` gets a row whenever the bindings are built.

---

## 7. Mapping native entries back to Python objects

- `_registry` (NC:89) is a `WeakValueDictionary` keyed by **row handle** → object. It is **not** keyed by `id()`.
- `ObjectRow.py_id` (MH:190-192) holds `id(obj)`, but nothing maps a `py_id` back to an object: it is used only as K4's sort key (`k4_eligibility.cc:133-147`) and by the audit (NC:3362).
- **So the query should return row handles** (or indices into a Python-side list held in the same order), not py ids. The spec's "matching py ids … mapped through `_registry`" needs that correction.
- `find_by_obj_id` / `set_obj_id_findable` (MH:439-444; NC:1674-1701) map BC `GetObjID()` to a handle, gated on the id registry. That suits probes, not this table.

**Which candidates have rows:** every `ObjectClass` except `Torpedo`, provided the bindings are built (`available()`) and the row was not **dropped**.

- `_drop` (NC:491-538) removes a row when a mirrored value cannot be represented. From then on the object "takes the Python path" with no row and no `_nslot`.
- No rows at all: `DebrisChunk`, subsystems, `BridgeObjectClass`, `_LoudStub` objects, and test doubles.
- Row values are written only while the switch is on (`_enabled`). With it off, the native table has nothing true to read, so the Python query has to stay the path.

---

## 8. Existing native pushes, and whether the Set row can carry this

`SetRow` (MH:318-328) holds `ships` and `nebulae`: Object handles in **`contact_index` bucket order**, with `kRefUnrepresentable` for an unnameable entry, plus the resolved profile frame. How it is kept:

- `CI.on_added` (CI:61-77, called at SETS:216) and `CI.on_removed` (CI:80-100, called at SETS:281 / :298) mutate the bucket and call `push_set_members` (NC:2728-2741), which re-sends both whole lists (`_members` / `_list_entry`, NC:2711-2725).
- `CI.reset` (CI:143-150) and `forget_set` (CI:153-159) push empties.
- `_drop` of an Object row re-pushes every set in `CI.sets_holding(obj)` (NC:532-536; CI:131-140).
- `_containing_set` is a `NativeRefField` (OBJ:82), so `AddObjectToSet`'s `_containing_set = self` and `_clear_containing_set` push.
- `_radius` / `_scale` push on write (OBJ:80-81).

Why `ships` + `nebulae` cannot stand in for the candidate list:

1. **Wrong members.** Ships and nebulae only. Planets and suns are missing (participants), nebulae are included (never participants), and ProximityChecks and manager entries are absent.
2. **Wrong order under slot reuse.** A bucket appends on first `on_added` and has no notion of a dict key. `AddObjectToSet` under an existing key keeps the **key's** slot and silently drops the previous object, and `on_removed` is never called for it. Example: ships A (`"a"`) and B (`"b"`), then C added as `"a"`. `_objects` = C, B. Bucket = A, B, C, with A still listed (**inferred** from SETS:205-216 and CI:68-71).
3. **Wrong timing.** The bucket drops an object at the **start** of `RemoveObjectFromSet` (SETS:281). `_objects` drops it at the **end** (SETS:292-293), after the synchronous exit handlers.
4. **Wrong reverse index.** `sets_holding` scans only the ship and nebula buckets, so a dropped Planet row would never trigger a re-push of a members list.

**Could it be extended? Yes, as a third list, not by reusing these two (inferred design note).**

- Add `members`: `_non_torpedo` in order, as Object handles, or −2 for a member without a row. Push it from `_index_member` (SETS:262-272) and the two pops (SETS:292, :311), i.e. at the dict mutation itself.
- Add `manager`: the manager's `_objects` list, pushed from `AddObject`, `RemoveObject` and `UpdateObject`. Skip checks after 1a, but keep their slots out of the dedupe.
- Per entry, from the class at push time: `is_physics`, `stored` (`location_is_stored`), `overrides_get_radius`. The radius stays a live row read.
- The dedupe (first participant set member wins, §0) is evaluated at query time.
- Torpedo launches and expiries never touch `_non_torpedo` or the manager list, so the hot add/remove path costs nothing extra. The re-send is whole-list (as `push_set_members` does today), which is fine at a fight's non-torpedo mutation rate.
- `_drop` needs a reverse index (object → sets and managers holding it) to re-push those lists.

---

## Hook list

| Event | Where to hook | Effect on the table |
|---|---|---|
| Non-torpedo added under a new key | SETS:272 (`_index_member` else branch), i.e. right after SETS:206 | append to the set section |
| Non-torpedo added under an existing key (same or different object) | SETS:272 | replace the entry **in its slot**. The previous object silently leaves the set section; it may still sit in the manager section. |
| Torpedo added under a key that held a non-torpedo | SETS:265 | remove that key's entry |
| Non-torpedo added under a key that held a torpedo | SETS:269-270 (rebuild) | rebuild the set section from `_non_torpedo` |
| Torpedo added or expired (normal case) | none (`_index_member` torpedo branch; SETS:292 pop of a missing key) | no change. Watch `projectiles._sized` instead (§6). |
| `RemoveObjectFromSet` / `DeleteObjectFromSet` | SETS:292 / SETS:311, the `_non_torpedo` pop, **after** the handlers, by **name** | remove that key's entry (nothing if the key is absent, e.g. after a rename) |
| A torpedo gains or loses radius > 0 | PRJ:312-319 (`_radius` setter → `_sized`) | that torpedo's set (`_cset`) switches to "run Python whole" while any sized torpedo is in it |
| `ProximityManager.AddObject` / `UpdateObject` | PL:287-288 / PL:313-314 | append to the manager section if absent. A ProximityCheck still takes a slot but is never reported (1a). |
| `ProximityManager.RemoveObject` | PL:306-307 | remove the first occurrence from the manager section |
| Object radius changes | none in the table: the participant test and the line reach read the row's `_radius` at query time (OBJ:80 push) | — |
| Object row dropped (`_drop`) | NC:491-538 (needs a new reverse index; `sets_holding` covers ships and nebulae only) | mark the entry unrepresentable → Python answers that entry, or the whole query |
| Object class swapped (`__class__ =`) | `native_combat.reclassify` (`rock.py:87`, :187) | recompute the per-entry class flags (today's only swap changes none) |
| Native switch turned on | `_push_all` / resync | push every set's lists |
| Set renamed | SETS:161-165 | none |
| Set deleted / cleared (`DeleteSet`, `_sets.clear`, `forget_set`) | Set row finalizer (NC:1458-1460) | the table dies with the `SetClass`. A deleted set that is still referenced keeps its table, as it keeps `_objects`. |
| Object death (dying, hulk) | none | dead ships stay in the set (SD:148-182). They leave only through SD:256 → SETS:292. |
| Mission swap | HL:4824 / `mission_change.py:203` → set collection | as set deletion |
