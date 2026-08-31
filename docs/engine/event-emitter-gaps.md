# Event emitter gaps — the 12 constants with no engine poster

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
them — but that is a **reporting change, not a behaviour change**. Nothing in
the engine posts these twelve; their SDK handlers are still unreachable. This
document is the record so that silence is not mistaken for completeness.

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
`ET_SET_TARGET` — but note `engine/ui/target_list_view.py:7-9` currently
CLAIMS `pPlayer.SetTarget(name)` "fires ET_SET_TARGET and
ET_TARGET_WAS_CHANGED via the engine's existing event machinery." That
comment is wrong as of this audit: `SetTarget` posts only
`ET_TARGET_WAS_CHANGED`. Flagging this here rather than silently fixing it —
fixing the comment is not in this task's scope, and correcting behaviour
without knowing what BC's actual ET_SET_TARGET/ET_TARGET_WAS_CHANGED split
means risks introducing a wrong distinction.

---

## 3. `ET_NAME_CHANGE` (0x800109)

**SDK handler:** `Bridge/ScienceMenuHandlers.py:96` registers `PropertyChange`
(defined `:272`) as a broadcast handler. It casts `pEvent.GetSource()` to
`ObjectClass`, re-runs `ExitedSet`/`ShipIdentified` bookkeeping so a renamed
ship's target-list row picks up the new name.

**Engine emitter candidate:** `engine/appc/objects.py:133`
(`ObjectClass.SetName`) is the single base-class setter used by ships and
every other object. Posting a broadcast `ET_NAME_CHANGE` from there, guarded
on `name != self._name` (mirroring the change-guard in `ships.py`'s
`SetTarget`), would cover every object type at once. Not implemented here.

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

---

## 5. `ET_TARGET_LIST_OBJECT_REMOVED` (0x8000a3)

Same site and same caveat as #4. **SDK handler:**
`Bridge/ScienceMenuHandlers.py:93` registers `ExitedSet` (defined `:205`) as
a broadcast handler.

---

## 6. `ET_TORPEDO_ENTERED_SET` (0x80005c)

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

## 7. `ET_TORPEDO_EXITED_SET` (0x80005e)

Same prerequisite gap as #6. **SDK handler:**
`Maelstrom/Episode8/E8M2/E8M2.py:4513` registers `TorpedoExitSet` (defined
`:1692`); `Conditions/ConditionIncomingTorps.py:182` registers the method
`ExitedSet` (defined `:257`).

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

---

## 10. `ET_RESTORE_PERSISTENT_TARGET` (0x80005b)

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

---

## 11. `ET_IN_SYSTEM_WARP` (0x8000ef)

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

---

## 12. `ET_SET_WARP_SEQUENCE` (0x8000ee)

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

---

## Summary table

| Event | SDK handler (file:line) | Engine emitter |
|---|---|---|
| `ET_CANT_FIRE` | `TacticalMenuHandlers.py:422/1990`, `TacticalCharacterHandlers.py:58/198` | `weapon_subsystems.py` `StartFiring` early-return gates (`:1001-1027`, `:1289-1301`, `:1796-1814`) |
| `ET_SET_TARGET` | `ScienceMenuHandlers.py:134/472`, `HelmMenuHandlers.py:281/309` | `ships.py:1565-1571` (`SetTarget`) — same site as `ET_TARGET_WAS_CHANGED`; a doc comment in `target_list_view.py:7-9` wrongly claims this already happens |
| `ET_NAME_CHANGE` | `ScienceMenuHandlers.py:96/272` | `objects.py:133` (`ObjectClass.SetName`) |
| `ET_TARGET_LIST_OBJECT_ADDED` | `ScienceMenuHandlers.py:94/244`, `E3M2.py:906/1638`, `E2M1.py:718` | `target_menu.py:147-203` (`set_contacts`) — right module, no diff logic exists yet |
| `ET_TARGET_LIST_OBJECT_REMOVED` | `ScienceMenuHandlers.py:93/205` | same as above |
| `ET_TORPEDO_ENTERED_SET` | `E8M2.py:4511/1643`, `ConditionIncomingTorps.py:180/228` | **none** — torpedoes are never added to a `SetClass` (prerequisite mechanism absent, `projectiles.py:167-180`, `sets.py:260-289`) |
| `ET_TORPEDO_EXITED_SET` | `E8M2.py:4513/1692`, `ConditionIncomingTorps.py:182/257` | same prerequisite gap |
| `ET_TRACTOR_BEAM_STARTED_FIRING` | `PowerDisplay.py:337/1010`, `ConditionFiringTractorBeam.py:26`, `E7M2.py:341/708`, `E8M2.py:528` | `weapon_subsystems.py:1870-1904` (`_engage_beam`) — needs edge-detect not yet built |
| `ET_TRACTOR_BEAM_STOPPED_FIRING` | `PowerDisplay.py:338/1010`, `ConditionFiringTractorBeam.py:27` | `weapon_subsystems.py:1906-1908` (`StopFiring`) / `:1856-1868` (re-acquire failure) — same missing edge-detect |
| `ET_RESTORE_PERSISTENT_TARGET` | `TacticalMenuHandlers.py:407/958` | **could not determine** — no code sets or reads `target_menu.py`'s `_persistent_target_name` for anything but clearing it |
| `ET_IN_SYSTEM_WARP` | `ScienceMenuHandlers.py:95/515` | `ships.py:756` (engage) / `:780` + `ship_motion.py:291,300,324` (disengage, 3 sites) |
| `ET_SET_WARP_SEQUENCE` | `ConditionWarpingToSet.py:33/69` | `subsystems.py:1491` (`WarpEngineSubsystem.SetWarpSequence`) — already tracked in `CLAUDE.md` |
