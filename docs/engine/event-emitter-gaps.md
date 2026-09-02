# Event emitter gaps — all 12 closed

> **Status 2026-09-02 — 12 of 12 closed.** Tier A closed three
> (`ET_SET_WARP_SEQUENCE` #12, `ET_NAME_CHANGE` #3, `ET_IN_SYSTEM_WARP` #11 —
> the tier where *the post was the only missing piece*, no new state, no
> fidelity guess). This branch closed six more: `ET_CANT_FIRE` (#1, needed a
> prerequisite accessor plus a scoping decision), `ET_SET_TARGET` (#2, closed
> as a **documented non-emission** — the registration-pairing evidence says it
> must never be posted, not that we haven't gotten to it), the target-list
> membership pair `ET_TARGET_LIST_OBJECT_ADDED`/`_REMOVED` (#4/#5, needed a
> membership diff built from scratch), and the tractor-beam edge pair
> `ET_TRACTOR_BEAM_STARTED_FIRING`/`_STOPPED_FIRING` (#8/#9, needed an
> edge-detect built from scratch). Each is marked ✅ **DONE** (or, for #2,
> ✅ **Closed — deliberately NOT emitted**) below with what landed.
>
> **#6/#7 closed 2026-09-01** by promoting `Torpedo` from `TGObject` to
> `ObjectClass` and giving it real set membership. The blast radius feared
> here was wrong on both counts: `GetClassObjectList(CT_TORPEDO)` callers got
> `[]` before, so they could only go from dead to live, and render scoping
> goes through `iter_active_ships`, which filters to `ShipClass` and never
> saw torpedoes. The real prerequisite was the base class.
>
> **#10 closed 2026-09-02.** The reference server could not reach it (no
> object model for `STTargetMenu`, no reconstructed body for
> `ClearPersistentTarget`), so it went to the clean-room RE project, which
> reconstructed the restore routine. See §10 — the recovered mechanism
> contradicted our SDK-derived guess in a way that mattered.
>

Q13's constant sweep (Tasks 1-9) made all 17 previously-dead-handler event
types real ints. Five of them (`ET_FIRE`, `ET_OBJECTIVES`,
`ET_SHOW_MISSION_LOG`, `ET_LAUNCH_PROBE`, `ET_CONTACT_ENGINEERING`) now work
end to end because both the poster and the handler live in the SDK
(`BridgeUtils.CreateBridgeMenuButton` stamps the constant on the button and
posts it on click; a matching `AddPythonFuncHandlerForInstance` sits under the
same real int). That fix is verified by
`tests/integration/test_bridge_menu_events_live.py`.

The other twelve have a real int now too, which means
`engine.appc.events.undefined_event_type_summary_lines()` no longer reports
them — but for most of them that was a **reporting change, not a behaviour
change**. This document is the record so that silence is not mistaken for
completeness.

All twelve are now closed: eleven have engine emitters and #2 is a documented
non-emission. Every handler above is reachable (#2 excepted, by design).

For each: the SDK handler waiting for the event, and either the engine call
site that should post it, or an explicit statement that none could be
identified with confidence.

---

## 1. `ET_CANT_FIRE` (0x800037)

**SDK handler:** `Bridge/TacticalMenuHandlers.py:422` registers
`PlayerCantFire` (defined `:1990`); `Bridge/TacticalCharacterHandlers.py:58`
registers a second `PlayerCantFire` (defined `:198`). Both read
`pEvent.GetSource()` and cast it to `TorpedoSystem`/`PhaserSystem`/
`TractorBeamSystem` to decide which Tactical dialogue line to play, gated by a
per-source cooldown so BC doesn't repeat the line every failed trigger-pull.

**Engine emitter candidate:** `engine/appc/weapon_subsystems.py`, the early
`return` gates inside `WeaponSystem.StartFiring` (`:1001-1027` — not-on,
disabled, cloak-blocks-fire, target-undetectable, can't-engage), the ammo
gate in `TorpedoSystem.StartFiring` (`:1289-1301`), and the equivalent gates
in `_HeldFireWeaponSystem`/`TractorBeamSystem.StartFiring` (`:1641-1656`,
`:1796-1814`). Every one of these is a point where a fire attempt is silently
dropped today. Posting `ET_CANT_FIRE` with `Source = self` (the weapon
system) and `Destination = self.GetParentShip()` from each `return` would
close the gap. Not implemented here — this is a design decision (which gates
count as "can't fire" vs. "not trying to fire", e.g. `IsOn()` false when the
system is just powered down) that Task 10 does not have scope to make.

**✅ Landed** in `engine/appc/weapon_subsystems.py`. `TorpedoSystem._post_cant_fire()`
posts `Source=self`, `Destination=self.GetParentShip()` from the existing
ammo-reserve gate in `StartFiring`. It needed a prerequisite:
`TorpedoSystem.GetNumReady()` did not exist — only `TorpedoTube.GetNumReady()`
did — so both SDK handlers' branch on the *system's* `GetNumReady()` resolved
through `TGObject.__getattr__` to a truthy `_Stub` (added, counting only child
tubes whose own `GetNumReady()` is non-zero). Deliberately torpedo-scoped
only: both handlers also cast the source to `PhaserSystem`/`TractorBeamSystem`
and then use neither, so posting from those gates would be observationally
inert while committing to an untested reading of "can't fire." Deliberately
unguarded (no try/except, no local cooldown) — both handlers self-cooldown (2 s
global, 10 s since Tactical last spoke), so a `StartFiring` call every tick
while the trigger is held cannot spam the line. Pinned by
`tests/unit/test_tier_bc_event_emitters.py`.

⚠️ **ONE of the handlers' three arms is live, not all three.** Both handlers
branch on `pTorps.GetNumReady() > 0` FIRST, and we post only from the
empty-magazine gate, so:

| Handler arm | Condition | Reachable? |
|---|---|---|
| "out of photons/quantums" + `UITorpsNoAmmo` | no rounds of the current type | ✅ yes — this is the gate we post from |
| `gt037` + `UITorpsNotLoaded` | rounds remain, tubes still cold | ❌ no — nothing posts on a cold-tube trigger pull |
| `gt030` "they're out of range" | tubes ready, target beyond 1000 | ❌ no — nothing posts on an out-of-range pull |

The live arm is correct: ammo is debited at fire, not at reload, so
`GetAvailable() == 0` implies `GetNumReady() == 0` and the handler takes the
"out of torps" branch. The other two need posts from the cold-tube and
range/arc rejection paths, which are NOT in `TorpedoSystem.StartFiring` — they
live in the per-tick BC fire path. Closing them is follow-up work, not part of
this gap's ✅.

⚠️ Also note `ET_CANT_FIRE` shares its int (0x800037) with our
`ET_WEAPON_FIRE_FAILED` alias, and `TorpedoTube._broadcast_weapon_fire_failed`
posts that int with no Source and the TUBE as destination. It is inert (the
handlers are player-instance handlers), deliberately so — see its docstring.

---

## 2. `ET_SET_TARGET` (0x8000e1)

**SDK handler:** `Bridge/ScienceMenuHandlers.py:134` and
`Bridge/HelmMenuHandlers.py:281` both register the SAME event name
(`App.ET_SET_TARGET`) against the SAME handler function name
(`TargetChanged`, defined at `ScienceMenuHandlers.py:472` and
`HelmMenuHandlers.py:309` respectively) that they *also* register under
`App.ET_TARGET_WAS_CHANGED`. In BC these are evidently two distinct signals
funnelled to the same handler — likely "target set programmatically" vs.
"target changed" — but no SDK comment states the distinction and this
sweep did not attempt to recover it from the reference.

**Engine emitter candidate:** `engine/appc/ships.py:1565-1571`
(`ShipClass.SetTarget`) already posts `ET_TARGET_WAS_CHANGED` on an actual
target change. The same call site is the natural place to also post
`ET_SET_TARGET` — `SetTarget` posts only `ET_TARGET_WAS_CHANGED` today.
`engine/ui/target_list_view.py:7-9`'s comment used to claim
`pPlayer.SetTarget(name)` "fires ET_SET_TARGET and ET_TARGET_WAS_CHANGED via
the engine's existing event machinery"; that was wrong as of the original
audit and was corrected in `cdc72fe2` to point back at this gap instead.
Correcting the actual *behaviour* is still out of scope here — without
knowing what BC's ET_SET_TARGET/ET_TARGET_WAS_CHANGED split means, adding an
emitter risks introducing a wrong distinction.

**✅ Closed — deliberately NOT emitted.** The registration-pairing evidence
above was confirmed, not just plausible: every SDK registration of
`ET_SET_TARGET` sits line-adjacent to an `ET_TARGET_WAS_CHANGED` registration
on the same object against the same handler function, and nothing anywhere
registers `ET_SET_TARGET` alone. Posting it from `ShipClass.SetTarget`
alongside the existing `ET_TARGET_WAS_CHANGED` post would double-dispatch
`TargetChanged` on the Science and Helm menus for every target change — a
double-fire, not new reachable behaviour. Pinned by
`tests/unit/test_tier_bc_event_emitters.py::test_set_target_posts_only_target_was_changed`,
whose docstring exists specifically to stop a future change from adding the
emitter without re-reading this reasoning first.

---

## 3. `ET_NAME_CHANGE` (0x800109) — ✅ DONE

**SDK handler:** `Bridge/ScienceMenuHandlers.py:96` registers `PropertyChange`
(defined `:272`) as a broadcast handler. It casts `pEvent.GetSource()` to
`ObjectClass`, re-runs `ExitedSet`/`ShipIdentified` bookkeeping so a renamed
ship's target-list row picks up the new name.

**Engine emitter candidate:** `engine/appc/objects.py:133`
(`ObjectClass.SetName`) is the single base-class setter used by ships and
every other object. Posting a broadcast `ET_NAME_CHANGE` from there, guarded
on `name != self._name` (mirroring the change-guard in `ships.py`'s
`SetTarget`), would cover every object type at once.

**✅ Landed** in `engine/appc/objects.py` `ObjectClass.SetName`. Guarded on the
OLD name being non-empty, **not** merely on the name differing: `SetName` is
also the spawn-time setter (backdrops, planets, asteroid fields, placements,
lights, `sets.py`, `ships.py`, plus 114 SDK files), so the bare guard suggested
above would still have fired for every object as it was constructed, running
`PropertyChange`'s bookkeeping before the object is necessarily in a set. In BC
the initial name is set inside Appc at construction rather than through a
broadcasting script call, so rename-only is the faithful reading. Pinned by
`tests/unit/test_tier_a_event_emitters.py`, and the spawn guard is
mutation-proved (dropping it turns `test_initial_naming_does_not_post` red).

---

## 4. `ET_TARGET_LIST_OBJECT_ADDED` (0x8000a2)

**SDK handler:** `Bridge/ScienceMenuHandlers.py:94` registers `ShipIdentified`
(defined `:244`) as a broadcast handler; mission scripts also listen directly
— `Maelstrom/Episode3/E3M2/E3M2.py:906` (`DetectBerkeley`), `:1638`
(`FindDerelict`), and `Maelstrom/Episode2/E2M1/E2M1.py:718`
(`ShipOnTargetList`, broadcast).

**Engine emitter candidate:** `engine/appc/target_menu.py:147-203`
(`STTargetMenu.set_contacts`), called once per frame from
`engine/host_loop.py:6231`, is where the player's contact/target list is
rebuilt from `perception.perceived_by` output. **This is the right module,
not an existing call site** — `set_contacts` does not currently diff this
frame's contact set against the previous one; it only ever adds rows
(`RebuildShipMenu` for a ship not yet in `_row_cache`) and never removes them
(see the method's own docstring: a contact that fails detection is dropped
by `_rows()` filtering, not by clearing `_row_cache`). Posting
`ET_TARGET_LIST_OBJECT_ADDED`/`_REMOVED` needs a genuine membership-diff
against the previous frame's contact set to be built first; there is no
single `return`/assignment today whose crossing IS "object entered the
target list."

**✅ Landed** in `engine/appc/target_menu.py`.
`STTargetMenu._post_membership_changes()` diffs this push's TARGETABLE ship
subset (`c.ship for c in self._contacts if c.targetable`) against the
previous push's, cached in `_listed`, and posts `ET_TARGET_LIST_OBJECT_ADDED`
for each ship that newly appears. Membership is the TARGETABLE subset
specifically because that is what this list shows — a perceivable-but-not-
targetable contact gets no row (`_rows()` filters on it), so it was never "on
the target list" in the sense the SDK handlers mean. Destination is the ship
itself, not the menu: `Maelstrom/Episode3/E3M2/E3M2.py:906` registers
`DetectBerkeley` as an INSTANCE handler on the Berkeley, and instance
dispatch only ever reaches the destination, so anything else would leave
that mission beat permanently dead. Row **lifetime is deliberately
unchanged** — `_row_cache` still keeps one row per ship for the life of the
menu; this method reports membership, it does not manage rows. `_listed` is
recorded *before* the post loops run, not after: `AddEvent` dispatches
synchronously and destination dispatch is deliberately unguarded, so a
handler runs *inside* the loop, and a re-entrant one would otherwise diff
against the stale set and double-post (fixed in a follow-up review pass,
`2897473b`). `ClearTargetList` resets `_listed` alongside `_row_cache`, or a
ship still present on the next push would be silently skipped even though
its row was destroyed and rebuilt. Pinned by
`tests/unit/test_tier_bc_event_emitters.py`.


### ⚠️ Cost: the emitter is free, the HANDLER is not (measured 2026-09-01)

The diff itself is negligible: `_post_membership_changes` costs
**0.4 / 0.7 / 1.1 us** at 8 / 17 / 32 contacts (~18% of `set_contacts`, itself
2.4 / 3.8 / 5.8 us) — under 0.002 ms of a 16.67 ms frame. Do not go looking
for the cost here.

It is in what the event now REACHES. `Bridge/ScienceMenuHandlers` is not
stubbed, and `CreateMenus:93-94` registers `ShipIdentified` / `ExitedSet` live.
`ShipIdentified` performs TWO `g_kLocalizationManager.Load("data/TGL/Bridge
Menus.tgl")` round trips at a measured **262 us each**, so:

* **~0.52 ms per ADDED**, paid in full even when the button already exists —
  both Loads precede `CreateScanButton`'s `GetButtonW` de-dupe.
* **>=262 us per REMOVED** via `ExitedSet`.

Two consequences worth knowing before reading a frame spike as a regression:

1. **Load/warp burst.** 32 targetable contacts is **~17 ms in one frame** — an
   entire 60 Hz frame. A warp pays it twice: mid-warp `perceived_by()` returns
   `()` (the player sits alone in `_WarpTransit`), giving N REMOVED, then
   arrival gives N ADDED. Nothing bounds this today.
2. **No range hysteresis — this is the worse one.** `sensor_detection`'s
   `HYSTERESIS` / `_latched` pair covers NEBULA concealment only; the RANGE
   gate has none. `set_contacts` runs every frame, so a contact
   station-keeping or moving tangentially at the sensor boundary flips
   `targetable` every frame: ~0.5 ms/frame per flapping contact, and a Scan
   Object button created and destroyed 60x/s. Measured with an oscillating
   contact: 10 frames -> 10 events, undamped.

Neither is caused by the membership diff — both are properties of the SDK
handler and of `can_detect` that the diff made REACHABLE. Range hysteresis in
`can_detect` is the obvious fix and is deliberately NOT done here: it changes
what the radar, the target list and the AI all perceive, so it wants its own
change and its own live check.

---

## 5. `ET_TARGET_LIST_OBJECT_REMOVED` (0x8000a3)

Same site and same caveat as #4. **SDK handler:**
`Bridge/ScienceMenuHandlers.py:93` registers `ExitedSet` (defined `:205`) as
a broadcast handler.

**✅ Landed** alongside #4 — same method, same commit, the opposite crossing:
`_post_membership_changes()` posts `ET_TARGET_LIST_OBJECT_REMOVED` for every
ship in the previous `_listed` set that is no longer in this push's
TARGETABLE subset. See #4 for the shared reasoning (destination-is-the-ship,
unchanged row lifetime, `_listed` recorded before posting, `ClearTargetList`
reset).

---

## 6. `ET_TORPEDO_ENTERED_SET` (0x80005c) — ✅ DONE

**SDK handler:** `Maelstrom/Episode8/E8M2/E8M2.py:4511` registers
`TorpedoEnterSet` (defined `:1643`); `Conditions/ConditionIncomingTorps.py:180`
registers the method `EnteredSet` (defined `:228`) on a
`TGPythonInstanceWrapper`.

**Engine emitter: could not determine — and here is why that is not a gap in
my search, it is a real prerequisite gap.** Per
`engine/appc/projectiles.py` (module-level `_active` registry, `:167-180`)
and the project's own recorded finding on the torpedo-evasion fix, torpedoes
in this engine are **never added to a `SetClass` at all** — they live only in
`projectiles._active`. `AddObjectToSet`/`RemoveObjectFromSet`
(`engine/appc/sets.py`) are never called for a torpedo, and
`sets.py:_broadcast_set_transition` (`:260-289`, the function that posts the
ship analogue `ET_ENTERED_SET`/`ET_EXITED_SET`) explicitly filters to
`isinstance(obj, ShipClass)` and returns early otherwise. There is no
"torpedo joins a set" event to hang a broadcast off — that mechanism itself
is the missing piece, not just the broadcast call. Wiring torpedoes into
`SetClass` membership is a separate, larger, already-acknowledged deferred
follow-up (it changes what every `GetClassObjectList(CT_TORPEDO)` caller and
the active-set render scoping see), not a one-line addition.

---

## 7. `ET_TORPEDO_EXITED_SET` (0x80005e) — ✅ DONE

Same prerequisite gap as #6. **SDK handler:**
`Maelstrom/Episode8/E8M2/E8M2.py:4513` registers `TorpedoExitSet` (defined
`:1692`); `Conditions/ConditionIncomingTorps.py:182` registers the method
`ExitedSet` (defined `:257`).

**✅ Landed 2026-09-01.** `Torpedo` now extends `ObjectClass` rather than
`TGObject`, and `projectiles.register()` / `expire()` join and leave the
firing ship's set, posting the pair with the torpedo as destination.

Three things the analysis above got wrong, worth keeping so the next
"prerequisite gap" is not over-estimated the same way:

* **The blast radius was smaller than feared.** `GetClassObjectList(CT_TORPEDO)`
  callers returned `[]`, so they could only go from dead to live — no existing
  answer changed. Render scoping goes through `iter_active_ships`, which
  filters to `ShipClass`, so torpedoes were never visible there.
  `contact_index.on_added` ignores non-ships, so they do not become contacts.
* **The real prerequisite was the BASE CLASS**, not set plumbing.
  `ConditionIncomingTorps.EnteredSet` opens with `ObjectClass_Cast`, which a
  `TGObject` fails, and `AddObjectToSet` needs `SetName`/`_containing_set`.
  The promotion was safe because `Torpedo` and `ObjectClass` already both
  stored the transform in `self._position`.
* **Two accessors were missing and would have read as truthy `_Stub`s** the
  moment the loop went live: `GetDamage` (only `SetDamage` existed) and
  `GetTargetID`. Without them `AI/Preprocessors.py:707`'s
  `pTorp.GetTargetID() == idTarget` is always False and the incoming-damage
  estimate silently stays 0.0.

Beyond the two events this makes `AI/Preprocessors.py:705`'s estimate live —
an AI now sees damage already inbound on a target before adding to it — and
gives `ConditionIncomingTorps.PeriodicCheck` real torpedoes to find. Evasion's
1 Hz polling path is unchanged and still works; the events are a faster gate
alongside it, removing ~1 s of latency.

Cost measured: **2.12 us -> 7.43 us per spawn+expire** (+5.3 us per torpedo).
At an absurd 100 spawns per frame that is 0.53 ms; at real fire rates it is
unmeasurable. Pinned by `tests/unit/test_torpedo_set_membership.py`.

---

## 8. `ET_TRACTOR_BEAM_STARTED_FIRING` (0x80007d)

**SDK handler:** `Bridge/PowerDisplay.py:337` registers `HandleTractor`
(defined `:1010`, target-filtered to the player) to light the tractor HUD
indicator; `Conditions/ConditionFiringTractorBeam.py:26` registers the method
`StartedFiring` (target-filtered to the watched ship);
`Maelstrom/Episode7/E7M2/E7M2.py:341` and `Maelstrom/Episode8/E8M2/E8M2.py:528`
both register `TractorHandler` (E7M2 defined `:708`) for mission beats.
`PowerDisplay.HandleTractor` casts `pEvent.GetDestination()` to `ShipClass`.

**Engine emitter candidate:** `engine/appc/weapon_subsystems.py`,
`TractorBeamSystem._engage_beam` (`:1870-1904`) is the function that actually
starts an emitter gripping a target and returns `True` on success; it is
called from `StartFiring` (`:1813`) and from the per-tick re-acquire path
(`:1868`). Posting `ET_TRACTOR_BEAM_STARTED_FIRING` with
`Destination = self.GetParentShip()` needs an edge-detect (only on the
transition from "no emitter firing" to "an emitter firing"), because
`_engage_beam` is called every tick while held and would otherwise spam the
event. That transition tracking does not exist today — `IsFiring()`
(`:1815-1819`) already computes the instantaneous state each call, but
nothing caches last tick's value to diff against.

**✅ Landed** in `engine/appc/weapon_subsystems.py`.
`TractorBeamSystem._sync_firing_event()` posts on a crossing of `IsFiring()`,
cached in a new `_was_firing` field — deliberately **not** derived from
`_fire_held`, because the beam drops and re-acquires (range, shields, arc)
while the ENGAGE intent stays continuously held, and each drop/re-acquire IS
a transition BC's `PowerDisplay` repaints for. `Destination =
self.GetParentShip()`: `PowerDisplay.py:1013` casts `GetDestination()` to
`ShipClass`, and `ConditionFiringTractorBeam.py:26-27` register broadcast
METHOD handlers filtered to the watched ship, which filters on the event's
destination. Called from `StartFiring`, every state-changing exit of
`update_weapons`, and `StopFiring`. The first pass missed one exit — the
`not self.IsOn()` bail — and that was a real, live latch bug, not a
theoretical gap: `TractorBeam.UpdateCharge` stops the emitter behind the
system's back whenever the parent loses power (the host loop pumps
`UpdateCharge` on every emitter every tick regardless of the parent's power
state), so cutting tractor power mid-grip left `_was_firing` stuck `True` —
the HUD latched "Tractor: On" permanently, and the next re-engage's
`STARTED` event was silently swallowed because the cache never saw the
drop. Fixed in a follow-up review pass (`f47033d8`). Pinned by
`tests/unit/test_tier_bc_event_emitters.py`, including the power-loss latch
and out-of-arc regression cases.

---

## 9. `ET_TRACTOR_BEAM_STOPPED_FIRING` (0x80007f)

Same site and same caveat as #8, on the opposite transition.
**SDK handler:** `Bridge/PowerDisplay.py:338` (same `HandleTractor`, defined
`:1010`); `Conditions/ConditionFiringTractorBeam.py:27` registers the method
`StoppedFiring`. Candidate engine sites: `TractorBeamSystem.StopFiring`
(`:1906-1908`, the explicit disengage) and the `return False` in the
per-tick re-acquire path (`:1856-1862`, `:1868`) when a previously-gripping
beam loses its target (out of range, shield back up, target destroyed) —
again needs the same edge-detect that doesn't exist yet.

**✅ Landed** alongside #8 — same method, same commits, the opposite
transition (`ET_TRACTOR_BEAM_STOPPED_FIRING` when `IsFiring()` crosses from
true to false). See #8 for the shared reasoning, including the power-loss
latch fix that this direction was the one actually missing.

---

## 10. `ET_RESTORE_PERSISTENT_TARGET` (0x80005b) — ✅ DONE

**SDK handler:** `Bridge/TacticalMenuHandlers.py:407` registers
`PersistentTargetRestored` (defined `:958`) so restoring a remembered target
doesn't count as the player manually retargeting (it must not clear Felix's
"Target At Will" setting).

**Engine emitter: could not determine.** `engine/appc/target_menu.py`
defines a `_persistent_target_name` field (`:143`, initialised `None`) and
`ClearPersistentTarget()` (`:394-397`, also only ever sets it to `None`). No
code anywhere in `engine/` ever *sets* `_persistent_target_name` to a real
value, and no code ever *reads* it to decide "restore this target now." The
feature this event represents — BC remembering the player's target across
some transition (a set warp? undocking? a save/load?) and re-selecting it —
has no implementation to hook an emitter into. I could not identify a call
site because the prerequisite decision logic (when does a target get
restored) does not exist, and I would be inventing a mechanism if I named
one.


**⛔ Confirmed blocked 2026-09-02, by the clean-room reference — not by lack of
effort.** The `stbc-reference` server was queried directly (four questions
across the `layout`, `api`, `behaviour` and `constant` areas). What it
established:

* **The published `STTargetMenu` API is exactly nine entries** — `Cast`,
  `ClearPersistentTarget`, `ClearTargetList`, `CreateW`, `GetObjectEntry`,
  `GetTargetMenu`, `RebuildShipMenu`, `RebuildShipMenus`,
  `ResetAffiliationColors`. **There is no setter and no restorer.** Graded
  `faithful` and described as an identity fact: read from the original
  program's own dispatch table, addresses included
  (`ClearPersistentTarget` = `0x0062DED0`). This is the strongest evidence
  tier the server issues.
* **The corpus holds no object model for `STTargetMenu`** — outcome
  `no-match`, a *measured* absence rather than a retrieval miss. So the field
  the persistent target lives in cannot be recovered.
* **`ClearPersistentTarget` has no reconstructed body.** Asking what the
  routine does returned only the entry roster, graded `partial`.
* The event constant itself scored **below the relevance floor** (0.35) in
  two different areas. Per the server's own wording that is "not a statement
  that the corpus is silent" — only that retrieval could not reach it.

**What this changes.** The entry above said the call site "could not be
determined". It is now stronger and better grounded: the restore mechanism is
*provably* absent from the scripted surface, so it is necessarily
engine-internal, and the engine internals for this class are unreconstructed.

**What it does NOT change: still do not add an emitter.** Nothing here reveals
when BC decides to restore a target, and `engine/appc/target_menu.py` still has
no writer for `_persistent_target_name` — only `ClearPersistentTarget`, which
matches the original's surface exactly. Inventing a trigger would be inventing
a mechanism, and it would be worse than the current honest gap because the SDK
handler (`TacticalMenuHandlers.PersistentTargetRestored`, :958) exists
precisely to suppress Felix's "Target At Will" reset — firing it at the wrong
moment would silently change tactical behaviour.

Re-open this only if the reference gains a `STTargetMenu` object model or a
reconstructed body for `0x0062DED0`.


**✅ Landed 2026-09-02 — mechanism RECOVERED by the clean-room RE project.**
The reference server could not reach it, so the question went to the RE
project, which reconstructed the restore routine. Their findings, and how each
shaped the implementation:

* **The restore is driven from the target menu's PERIODIC REFRESH**, not from
  an object-entered-set event. Our SDK-derived hypothesis — hook
  `ET_TARGET_LIST_OBJECT_ADDED` — was WRONG, and not harmlessly: an event hook
  restores and clears at different moments than a poll does.
* **The engine clears the memory in exactly one circumstance**: the remembered
  object no longer resolves, or resolves to something dead (two callers of the
  clear in the whole image — the SWIG wrapper, and the failure path inside the
  restore routine itself). **A not-currently-targetable object does NOT clear
  it — it skips the tick.** Invert that asymmetry and a ship that cloaks once
  is forgotten forever, with nothing to notice.
* **Nothing clears the memory after a successful restore.** It persists, so a
  target that leaves and returns twice is restored twice.
* **`0x80005B` is posted BEFORE the target changes**, and delivered first. The
  original relies on a FIFO queue-append ordering. Ours dispatches
  synchronously, which gives the invariant *more* strongly — the restore
  handler runs to completion before `SetTarget` is called — so this is
  deliberately NOT a queue. The invariant is what matters:
  `TacticalMenuHandlers.PersistentTargetRestored` increments a counter that
  the target-changed handler then consumes, and posted the other way round a
  re-selection the player never made silently cancels Felix's "Target At Will".
* **The restore carries the SUBSYSTEM, not a flag.** `spec/ShipClass.md 4.0`
  documents `SetTargetHandle`'s second argument as an int `iFlag`; the RE
  project corrected that — it is a `ShipSubsystem*`, proven by three
  independent dereferences, and the restore path is the only one of eight call
  sites that passes it non-null. So a restore re-targets the object *and* its
  subsystem.
* **Omitting the event parameter is safe.** Of six engine subscribers to
  `0x800058`, five read only the ship, and the multiplayer serializer reads the
  second field behind a null guard. Emitting an **integer** there would be the
  one unsafe choice — which is what we would have done on the corpus's
  mis-typing.

Implemented in `engine/appc/target_menu.py`
(`remember_player_target` / `attempt_persistent_restore`), driven per frame
from the host loop after the contact push. `ClearPersistentTarget` now clears
both halves of the pair. The liveness half of the clear reuses
`perception`'s `alive_or_wreck`, matching the original, where the clear is
gated on the same predicate the menu-membership scan uses.

The three existing engine clear-sites map onto the recovered rules without
new code: a dead target is cleared by the liveness guard; `warp._clear_all_targets`
already called `ClearPersistentTarget` (mirroring `PostWarpEnableMenu`, whose
comment describes exactly the behaviour BC's authors removed); and a cloaked or
out-of-range target is the skip-the-tick case.

⚠️ **TWO DEFAULTS ARE OURS, NOT RECOVERED** — both would be settled by one
live check, and both are pinned by tests so a change is deliberate:
1. **We restore only when the player has no current target.** Nothing
   establishes whether the original overrides a live selection.
2. **We resolve only within the player's current set.** The original uses a
   world-context handle, which may resolve more broadly — relevant to the
   "object follows you to the new set" case in the SDK comment.

⚠️ Still unestablished upstream: the semantics of the `0x008E5C18` float
threshold and the `+0x150` byte beyond "the same liveness test the
menu-membership scan uses". We use our canonical predicate, as advised.

---

## 11. `ET_IN_SYSTEM_WARP` (0x8000ef) — ✅ DONE

**SDK handler:** `Bridge/ScienceMenuHandlers.py:95` registers `InSystemWarp`
(defined `:515`) — reads `pEvent.GetBool()` and toggles the Launch Probe
button (`BridgeUtils.DisableLaunchProbe`/`EnableLaunchProbe`) while the
player is in an in-system warp.

**Engine emitter candidate — the most complete of the twelve.**
`engine/appc/ships.py:756` (`ShipClass.InSystemWarp`, the one-time
`self._insystem_warp_transit = (target, float(distance))` assignment,
reached only past the early-return guards at `:730-737`) is the single
engage point for `GetBool()==1`. The disengage side has THREE call sites
that all clear `_insystem_warp_transit`, none of which currently notify
anyone: `engine/appc/ships.py:780` (`StopInSystemWarp`, the explicit
abort — called by AI `LostFocus`), and `engine/appc/ship_motion.py:291,
:300, :324` inside `_step_in_system_warp` (natural transit completion).
Posting `ET_IN_SYSTEM_WARP` with `GetBool()==0` faithfully needs all three
covered, guarded on "was a transit active before this call" so a
no-op `StopInSystemWarp` (nothing was warping) doesn't post a spurious
stop. `Destination` should be the ship per the SDK read
(`App.ShipClass_Cast(pEvent.GetDestination())`).

**✅ Landed.** `ShipClass._post_in_system_warp(active)` posts a `TGBoolEvent`
with `Destination = self`; the engage site calls it with `True`. All four
disengage sites now route through `ShipClass._end_in_system_warp()`, which
clears the transit and posts `False` **only if one was active** — AI
`LostFocus` calls `StopInSystemWarp` unconditionally and usually cancels
nothing. Callers keep owning `_warp_consumed` (abort drops it, arrival sets
it). Pinned by `tests/unit/test_tier_a_event_emitters.py`, including "exactly
one stop per transit, not one per tick".

---

## 12. `ET_SET_WARP_SEQUENCE` (0x8000ee) — ✅ DONE

Already tracked as a known gap in `CLAUDE.md`'s "AI surface & gaps" row
(constant now real per this sweep; emitter still missing). Recorded here for
completeness of the twelve.

**SDK handler:** `Conditions/ConditionWarpingToSet.py:33` registers the
method `SequenceSet` (defined `:69`) on a `TGPythonInstanceWrapper`.
`SequenceSet` casts `pEvent.GetDestination()` to `WarpEngineSubsystem`,
resolves `GetParentShip()`, and re-reads `GetWarpSequence()` fresh off the
subsystem (the event carries no payload of its own — it is purely a
"something changed, go re-check" ping).

**Engine emitter candidate:** `engine/appc/subsystems.py:1491`
(`WarpEngineSubsystem.SetWarpSequence`) — post a broadcast `TGEvent` with
`Destination = self` (the subsystem instance) whenever this setter runs.
This is the most precisely located of all twelve gaps: the handler needs no
new decision logic, only the post itself.

**✅ Landed** in `engine/appc/subsystems.py` `WarpEngineSubsystem.SetWarpSequence`,
posted unguarded with `Destination = self`. `ConditionWarpingToSet` now
re-evaluates when the sequence changes instead of only at construction —
correct before, but never timely. This also closes the residual flagged in
`CLAUDE.md`'s "AI surface & gaps" row.

---

## Summary table

| Event | SDK handler (file:line) | Engine emitter |
|---|---|---|
| `ET_CANT_FIRE` | `TacticalMenuHandlers.py:422/1990`, `TacticalCharacterHandlers.py:58/198` | ✅ **DONE** — `weapon_subsystems.py` `TorpedoSystem._post_cant_fire()`, posted from the `StartFiring` ammo gate; torpedo-scoped only, unguarded by design |
| `ET_SET_TARGET` | `ScienceMenuHandlers.py:134/472`, `HelmMenuHandlers.py:281/309` | ✅ **Closed — deliberately NOT emitted** — same site as `ET_TARGET_WAS_CHANGED`; posting it would double-dispatch `TargetChanged`, not add behaviour |
| `ET_NAME_CHANGE` | `ScienceMenuHandlers.py:96/272` | ✅ **DONE** — `objects.py` `ObjectClass.SetName`, rename-only (old name non-empty) |
| `ET_TARGET_LIST_OBJECT_ADDED` | `ScienceMenuHandlers.py:94/244`, `E3M2.py:906/1638`, `E2M1.py:718` | ✅ **DONE** — `target_menu.py` `STTargetMenu._post_membership_changes()`, a TARGETABLE-subset membership diff against `_listed` |
| `ET_TARGET_LIST_OBJECT_REMOVED` | `ScienceMenuHandlers.py:93/205` | same as above |
| `ET_TORPEDO_ENTERED_SET` | `E8M2.py:4511/1643`, `ConditionIncomingTorps.py:180/228` | ✅ **DONE** — `projectiles.register`/`expire`; Torpedo promoted to ObjectClass |
| `ET_TORPEDO_EXITED_SET` | `E8M2.py:4513/1692`, `ConditionIncomingTorps.py:182/257` | ✅ **DONE** — same pair |
| `ET_TRACTOR_BEAM_STARTED_FIRING` | `PowerDisplay.py:337/1010`, `ConditionFiringTractorBeam.py:26`, `E7M2.py:341/708`, `E8M2.py:528` | ✅ **DONE** — `weapon_subsystems.py` `TractorBeamSystem._sync_firing_event()`, edge-detect on `IsFiring()` cached in `_was_firing` |
| `ET_TRACTOR_BEAM_STOPPED_FIRING` | `PowerDisplay.py:338/1010`, `ConditionFiringTractorBeam.py:27` | same as above, opposite transition — also covers the `not IsOn()` power-loss bail that latched the HUD before the review-pass fix |
| `ET_RESTORE_PERSISTENT_TARGET` | `TacticalMenuHandlers.py:407/958` | ✅ **DONE** — `target_menu.attempt_persistent_restore`, on the periodic refresh; mechanism recovered by the RE project |
| `ET_IN_SYSTEM_WARP` | `ScienceMenuHandlers.py:95/515` | ✅ **DONE** — `ships.py` engage + `_end_in_system_warp()` shared by all 4 disengage sites |
| `ET_SET_WARP_SEQUENCE` | `ConditionWarpingToSet.py:33/69` | ✅ **DONE** — `subsystems.py` `WarpEngineSubsystem.SetWarpSequence`, unguarded ping |
