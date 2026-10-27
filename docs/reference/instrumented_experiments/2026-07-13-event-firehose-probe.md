# Event firehose — a census of every event the engine actually fires (q15)

Status: DONE (both scenarios captured + analyzed)
Author: Claude session (q15 event firehose plan)
Created: 2026-07-13
Closed:  2026-07-13
Depends on: q13 (the `ET_*` name list), q14 (`probe_harness` persistent owner)

## Goal

q12 observed **5** torpedo/weapon events by hand. The SDK declares **363** `ET_*`
constants. This probe answers: **which of the 363 events actually fire during real
gameplay, who sends each one to whom, and how often** — across both canonical
scenarios — so we build Dauntless's event system to match what the engine really
does, not the handful of events we happen to have looked at.

## Background

Our `engine/appc/` event system implements the events the SDK scripts we've read
happen to consume. That is inference, and it has two blind spots:

- **Events that fire but no SDK script we've read listens for** — engine-internal
  or UI events we may still need to emit for other listeners to work.
- **Events we assume matter but that never actually fire** in normal play — effort
  we could deprioritise.

A live census replaces both guesses with a frequency-ranked, source→destination-
annotated list. Combined with q13 (which gives the numeric ID and name of every
`ET_*`), it is the definitive map of the event layer.

## The load-bearing design decision — ONE handler, not 363

q12 registered a *named* handler per event because it watched 5. That does not
scale, and `AddBroadcastPythonFuncHandler` resolves handlers by the string
`"module.FunctionName"` — you cannot bind the event-type into a closure.

Instead: define **one** handler `q15_firehose.OnEvent(TGObject, pEvent)` and
register that *same* string as a broadcast handler for **every** `ET_*` type. When
any event fires, `OnEvent` reads `pEvent.GetEventType()` to learn which type it was
and tallies it. This is O(1) source code for O(363) coverage and is the crux of the
probe.

```python
# registration loop (Install)
for name in _ALL_ET_NAMES:            # every "ET_*" in dir(App)
    try:
        itype = getattr(App, name)
        App.g_kEventManager.AddBroadcastPythonFuncHandler(
            itype, _owner, "q15_firehose.OnEvent")
        _TYPE_NAME[itype] = name       # reverse map id -> name for the report
    except:
        _skipped.append(name)
```

Enumerate `ET_*` names **dynamically** from `dir(App)` (filter `name[:3] == "ET_"`)
so the probe needs no hard-coded 363-entry list and automatically covers whatever
q13 reveals — including any runtime-registered types q13-Q4 finds.

## What `OnEvent` records — bounded, so it survives a firehose

Some events (heartbeats, UI/mouse, per-frame ticks) fire *constantly*. Recording a
line per event would blow the `SaveConfigFile` budget in seconds. So `OnEvent`
keeps **aggregates**, not a raw log:

Per event type, a small record:
- `count` — total firings.
- `first_t`, `last_t` — game-time of first and last firing.
- `first_src`, `first_dst` — the `_describe()` cast-ladder identification (from
  q12/q16) captured **only on the first firing** of that type (bounded work).
- `n_distinct_src`, `n_distinct_dst` — cheap cardinality via a small dict of objids
  seen (capped, e.g. first 16, then stop growing).

Total memory is O(number of *distinct* event types that fire) ≈ tens, not the raw
event count — safe for an entire E1M1 run.

**`OnEvent` must be print-free and record-free.** It fires on *every* event, every
frame — a firehose. It may touch **only in-memory dicts** (the per-type tallies);
it must never call `print`, `_record`, `_emit`, or `_section` (all of which the
q14 harness keeps buffer-only anyway, but `OnEvent` should not even buffer per
event). The `_describe()` cast-ladder call is bounded to the *first* firing of each
type, so it runs tens of times total, not per event. This is the q13 console-cost
lesson applied to the hottest possible loop: a single stray `print` in `OnEvent`
would reproduce — and dwarf — q13's 30-minute stall. `Focus` mode's raw log
buffers into a capped list; it does **not** print either. Only `Install()` and
`Dump()` echo, and only their handful of status/summary lines (via the harness
`_echo`).

## Specific questions

- **Q15-1** — Which `ET_*` types fire at all in Scenario A (Galaxy v Galaxy QB)?
  Ranked by count.
- **Q15-2** — Which fire in Scenario B (E1M1) that do **not** fire in A? (The
  mission/script/AI/set-transition layer QuickBattle never exercises.)
- **Q15-3** — For each fired type, first source→destination (via the cast ladder) —
  a who-talks-to-whom map of the event graph.
- **Q15-4** — Which of the 363 declared types **never fire** in either scenario?
  (Candidates to deprioritise — with the caveat "not in these two scenarios".)
- **Q15-5** — Ordering/coupling spot-checks the aggregate can seed (e.g. does
  `ET_OBJECT_DELETED` always follow an `ET_..._DESTROYED`?), confirmed by a short
  targeted per-type raw log if warranted (see "focus mode").

## Handler-lifetime — the E1M1 trap

The broadcast handler's owner (`probe_harness.persistent_owner()`) is the episode,
which outlives set transitions. **But** to be safe against the case where the
engine drops handlers on a set unload, `Install()` also registers for
`ET_SET_LOAD_FILE` / the set-transition events and, in `OnEvent`, if it sees one,
**re-arms** any handler that came back missing. Simplest robust version: expose a
`Rearm()` the operator can call manually at each E1M1 checkpoint (the runbook says
when), and treat auto-rearm as a stretch. A firehose that quietly went deaf halfway
through E1M1 is the failure mode we must engineer against.

## The probe — `tools/probes/q15_firehose.py`

**Imported, not `execfile`'d** (same reason as q12: the engine resolves
`"q15_firehose.OnEvent"` by importing the module). Console flow:

```python
import q15_firehose
q15_firehose.Install()      # prints owner + N handlers armed
# ... play the scenario to its checkpoints ...
q15_firehose.Rearm()        # (E1M1 only) at each set-transition checkpoint
q15_firehose.Dump()         # writes BCProbe_q15_<scenario>.cfg
```

`Install()` prints the armed count and any skipped types. `Dump()` emits, sorted by
descending count: `NAME (0xID) | count=N | t=[first..last] | src0=… dst0=… |
nsrc=… ndst=…`, plus a trailing block listing the **never-fired** declared types
for Q15-4.

### Focus mode (optional, for Q15-5)

A `Focus(["ET_FOO", "ET_BAR"])` call switches those specific types from aggregate
to **raw per-event logging** (like q12), capped at `_MAX_FOCUS = 300` lines, for
ordering/coupling questions the aggregate can only hint at. Off by default.

## How to run

Push `probe_harness.py` + `q15_firehose.py`. Then per scenario:

**Scenario A — Galaxy v Galaxy QB.** Start the battle, fly, `import q15_firehose;
Install()`, acquire target and fight for ~60 s (fire weapons, take damage, destroy
the enemy so death/cleanup events fire), then `Dump()`. Writes
`BCProbe_q15_A.cfg`.

**Scenario B — E1M1 full run.** `Install()` right after the mission loads and you
have a ship. Play the mission through; call `Rearm()` at each set transition /
major checkpoint named in the E1M1 runbook (undock, arrival, combat, docking).
`Dump()` at the end. Writes `BCProbe_q15_B.cfg`.

Collect (`collect_q15.py`, phase/scenario-suffixed like collect_q13) and commit
both.

## Expected output

```
-- provenance ------------------------------------------------
scenario = A (Galaxy vs Galaxy QB?)
...
-- fired events (by count) -----------------------------------
ET_WEAPON_FIRED (0x0080007C) | count=214 | t=[51.2..147.5] | src0=ShipSubsystem(Forward Beam) dst0=ShipClass(Keldon-1) | nsrc=6 ndst=2
ET_CANT_FIRE (0x00800037)    | count=58  | ...
ET_TORPEDO_FIRED (0x00800066)| count=11  | ...
...
-- never fired (declared but silent this scenario) -----------
ET_LOAD_EPISODE, ET_SAVE_GAME, ET_CHARACTER_ANIMATION_DONE, ...
```

## Analysis

- **A vs B diff** is the headline: intersection = combat-universal events (build
  these first, they're load-bearing); B-only = mission/script/AI events; A-only =
  pure-combat events. This directly prioritises event-system work in Dauntless.
- **Cross-reference the fired set against `engine/appc/` handlers** — any
  high-count fired event we do **not** post or handle is a gap; any event we post
  that never appears here is possibly speculative.
- **Feed Q15-3's src→dst map into the object model** — it says which object *types*
  originate which events (subsystem vs ship vs projectile vs system), which
  constrains where we emit them.
- Numeric IDs cross-check q13 (`GetEventType()` here must equal q13's dumped value
  for the same name).

## Cleanup

Delete `game\q15_firehose.py`, `game\BCProbe_q15_*.cfg`, and `probe_harness.py` if
unused elsewhere. The probe registers broadcast handlers on a throwaway
episode/player object for the session only; they die with the set. Makes no game-
file modification.

## Findings

Ran 2026-07-13. Results: `tools/probes/results/q15_firehose_{A,B}.txt`.
Scenario A = Galaxy vs Galaxy QuickBattle (fight to a kill). Scenario B = the
campaign run through E1M1 into the start of E1M2.

### Coverage

**106 of 377 declared `ET_*` types fired** across both scenarios — 86 in A, 53
in B, 33 shared. The two canonical scenarios cover the core single-player loop;
the ~271 silent types need other contexts (multiplayer, cloak, tractor, nebula,
save/load, other missions).

### Q15-1/Q15-3 — the census validates against known ground truth

q15 independently reproduced **every** q12 torpedo finding (numeric IDs and
source→destination), confirming the one-handler-for-all-types design:
`ET_TORPEDO_FIRED 0x00800066` src=`Torpedo` dst=`TorpedoTube`; `ET_TORPEDO_RELOAD
0x00800065` src=`None` dst=`TorpedoTube`; `ET_WEAPON_FIRED 0x0080007C`
src=subsystem dst=ship. It also captured the full **kill cascade** (`ET_OBJECT_
EXPLODING → CONVERTED_TO_HULK → OBJECT_DESTROYED → EXITED_SET → AI_DONE`) and the
**subsystem-damage lifecycle** (`SUBSYSTEM_DAMAGED → DISABLED → COMPLETELY_
DISABLED → DESTROYED → COMPLETELY_DESTROYED`, src=subsystem dst=ship).

### Q15-2 — the A-vs-B diff (the substrate split)

- **B-only (mission / nav / script layer):** `ET_MISSION_START`,
  `ET_LOAD_MISSION`, the warp cycle (`SET_WARP_SEQUENCE`, `START_WARP_NOTIFY`,
  `IN_SYSTEM_WARP`, `EXITED_WARP`, `SET_COURSE`, `WARP_BUTTON_PRESSED`), `ET_DOCK`
  + `ET_PLAYER_DOCKED_WITH_STARBASE`, `ET_AI_REACHED_WAYPOINT`,
  `ET_AI_FINISHED_BUILDING`, `ET_PROXIMITY_PLANET`, `ET_CAMERA_ANIMATION_DONE`,
  `ET_SUBSYSTEM_STATE_CHANGED`, `ET_NAME_CHANGE`, `ET_GAME_SAVED`.
- **A-only (combat):** the phaser fire/hit cycle, the subsystem-damage cascade,
  the death sequence, shields, and manual-flight input (`ET_INPUT_TURN_*`,
  `ET_INPUT_ROLL_*`).

This tells Dauntless which events belong to the combat subsystem vs. the
mission/navigation subsystem.

### Q15-4 — object lifecycle uses `ET_DELETE_OBJECT_PUBLIC`, not `ET_OBJECT_DELETED`

`ET_OBJECT_DELETED` never fired in either scenario despite kills and object
churn; `ET_DELETE_OBJECT_PUBLIC (0x00000001)` carried it (57× in A, 194× in B).
A "don't implement the obvious-looking one" signal.

### Structural / process findings

- **Handler persistence proven.** B captured events across the whole
  E1M1→E1M2 run (MISSION_START early → warp mid → docking → Haven proximity
  late), so **episode-owned broadcast handlers survive set transitions** as
  `persistent_owner()` intended. `Rearm()` was available but the episode owner
  made it largely unnecessary; re-arming only inflates counts, never the fired
  type-set.
- **ID bands:** script `0x0080xxxx`, input `0x008001xx–02xx` + `ET_KEYBOARD/
  MOUSE 0x0003xxxx`, low-level `0x0000xxxx`, audio `0x0002xxxx`.
- **The SaveConfigFile crash lesson.** The first Dump() hard-crashed the game:
  the never-fired section `string.join`ed ~300 names into a single ~6000-char
  cfg value, overflowing the writer's line buffer. Fixed by batching + a hard
  180-char cap in `probe_harness.emit()`. Recorded in
  `console-probe-workflow.md` so q16/q17 authors keep lines short.