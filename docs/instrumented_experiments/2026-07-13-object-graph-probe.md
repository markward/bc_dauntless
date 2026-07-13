# Object & subsystem graph — the live space-side tree (q16)

Status: PENDING
Author: Claude session (q16 object-graph plan)
Created: 2026-07-13
Closed:  —
Depends on: q14 (`probe_harness` provenance preamble)

## Goal

Dump the **full live object graph of the tactical (space) side** in the two
canonical scenarios: every object in the rendered set, downcast to its real type,
and for every ship the complete recursive subsystem tree with its identifying
properties. This is ground-truth to validate Dauntless's ship construction
(`loadspacehelper.py` integration) and subsystem model — and, on the symmetric
Galaxy-vs-Galaxy matchup, a free correctness oracle: anything asymmetric between two
identical hulls is a bug or a player-vs-AI code-path difference, not a ship
difference.

## Background

We build ships in `engine/appc/` from the SDK hardpoint files and
`GlobalPropertyTemplates.py`, but we have never compared the **assembled** result
against what the real engine holds in memory. q11 walked the set for *planets*;
q12 walked a torpedo system's *tubes*. Nobody has dumped the whole set × the whole
subsystem tree in a pinned, reproducible state.

The APIs are known and already used piecemeal:

- Set walk: `g_kSetManager.GetRenderedSet()` (or `GetSet(name)` / `GetAllSets()`),
  then `pSet.GetFirstObject()` / `pSet.GetNextObject(iter)` (q11's proven loop).
- Object identity: the RTTI `_Cast` ladder (`ShipClass_Cast`, `Planet_Cast`,
  `Sun_Cast`, `Torpedo_Cast`, plus the subsystem casts). Set iteration hands back
  **base** `ObjectClass` wrappers, so a cast is mandatory before type-specific
  methods (q11 gotcha #4).
- Subsystem tree: `ShipClass.GetNumChildSubsystems()` +
  `GetChildSubsystem(i)` (q12), recursing via each child's own
  `GetNumChildSubsystems()`. Named accessors exist too (`GetHull`,
  `GetPowerSubsystem`, `GetImpulseEngineSubsystem`, `GetTorpedoSystem`,
  `GetPhaserSystem`) as cross-checks.

## Specific questions

- **Q16-1** — What is the full object roster of the rendered set: objid, real
  (cast) type, name, world position, for every object? (Ships, projectiles,
  planets, sun, waypoints, debris.)
- **Q16-2** — For each ship, the complete subsystem tree: each node's type (via the
  cast ladder), name, parent, and identifying scalars — hull/shield/charge values,
  positions/offsets, per-tube reload where applicable. (Reuses q12's tube dump,
  generalised to every subsystem type.)
- **Q16-3** *(Scenario A symmetry oracle)* — Do the two Galaxies' subsystem trees
  match structurally and in authored stats (modulo objids, live damage, and the
  player-input path)? Any asymmetry is flagged for investigation.
- **Q16-4** — Are there multiple sets (`GetAllSets`)? What lives in each? (Confirms
  whether the space set and any others — bridge, ambient — are siblings under one
  manager, informing q17.)
- **Q16-5** — Which subsystem **types** actually appear on a Galaxy, and what is the
  cast-ladder coverage? (Any object that matches *no* cast is a type we haven't
  wrapped — a gap.)

## The probe — `tools/probes/q16_object_graph.py`

One-shot `execfile()` probe (pure read of live state, no handlers). Needs a loaded
scenario. Uses `probe_harness.provenance()` for the self-identifying header and the
harness flush (chunked-capable — a full E1M1 set can be large).

Structure:

0. **Console discipline (q13 lesson).** This probe emits the most lines of the four
   — every object plus every subsystem of every ship, easily hundreds to low
   thousands. It relies entirely on the q14 harness's **buffer-only** helpers: the
   per-object and per-subsystem loops call `_record`/`_emit` (which append to `_log`
   without printing) and **never** `print`. Only a final one-line summary echoes.
   Printing each line here would reproduce q13's ~30-minute stall.

1. **provenance()** header (scenario, set, roster, game_time).
2. **Set enumeration.** `GetAllSets()` for Q16-4; then walk the rendered set with
   the q11 `GetFirstObject`/`GetNextObject` loop, bounded (`_MAX_OBJECTS`, e.g.
   2000) against a runaway iterator.
3. **Per object:** run `_describe()` — the cast ladder from q12, extended to the
   full subsystem-type set — to get real type + identity, and record
   `objid | type | name | pos_gu`.
4. **Per ship** (object that casts to `ShipClass`): recurse the subsystem tree.
   For each subsystem, record type/name/parent and a **type-appropriate property
   bundle** (a small dispatch: TorpedoTube → maxready/numready/reload/lastfire as
   in q12; Hull/Shield → current/max; PowerSubsystem → power; ImpulseEngine →
   speeds; generic → GetName + position). Guard **every** getattr (bare `except`)
   so one missing accessor never aborts the tree.
5. **Flush.**

### Reusable `_describe()` / cast ladder

q16 is the natural home for the **canonical cast ladder** — a single ordered list
of `(App.<Type>_Cast, formatter)` pairs that identifies any object by asking the
engine (never guessing). q12 and q15 both hand-rolled a subset; lift q16's into
`probe_harness` so all three share it. Order most-derived → least-derived so the
first successful cast wins.

### Iterator nuance

The SDK shows two `GetNextObject` forms — `GetNextObject(pIterator)` and
`GetNextObject(pIteratedObject.GetObjID())`. q11 passed the object and it worked;
mirror that, but if the loop returns nothing/loops forever at implementation time,
fall back to the objid form. Record `n_objects_scanned` so a broken walk is
visible in the output.

## How to run

Push `probe_harness.py` + `q16_object_graph.py`.

**Scenario A — Galaxy v Galaxy QB.** Start the battle, fly into space (both ships
present, ideally before much damage so the symmetry check is clean), then:
```python
execfile('q16_object_graph.py')
```
Writes `BCProbe_q16_A.cfg`.

**Scenario B — E1M1.** Run at the E1M1 runbook checkpoints (post-undock, arrival,
combat) so the roster includes Starbase 12, shuttles, and Devore. `execfile` at
each; the phase/checkpoint goes in the provenance header. Writes
`BCProbe_q16_B.cfg` (one section per checkpoint, or suffixed files).

Collect (`collect_q16.py`) and commit.

## Expected output

```
-- provenance ------------------------------------------------
scenario = A (Galaxy vs Galaxy QB?)
roster = 13323 ShipClass 'Player' | 15013 ShipClass 'Keldon-1' | ...
-- objects (rendered set) ------------------------------------
obj000 = 13323 | ShipClass 'Player' | pos=(...)
obj001 = 15013 | ShipClass 'Keldon-1' | pos=(...)
...
-- ship 13323 'Player' subsystems ----------------------------
ss000 = TorpedoSystem 'Torpedoes' parent=<hull> nchild=6
ss001 =   TorpedoTube 'Forward Torpedo 1' maxready=1 numready=1 reload=40.0 ...
ss007 = PowerSubsystem 'Warp Core' power=... maxpower=...
ss008 = ImpulseEngineSubsystem 'Impulse' curmaxspeed=... 
...
```

## Analysis

- **Q16-3 symmetry diff:** structurally diff the two Galaxies' subsystem sub-trees.
  Identical authored stats expected; investigate any mismatch (likely a player-only
  code path or a genuine bug).
- **Validate against our build:** run the *same* scenario headless through the
  harness (`tools/mission_harness.py`) and diff our assembled subsystem tree against
  this dump — the whole point of pinning the scenario (per
  `canonical-probe-scenarios.md`). Missing subsystems, wrong parents, or wrong
  authored scalars surface immediately.
- **Q16-5 cast coverage:** any `UNKNOWN(no cast matched)` object is an engine type
  we don't wrap — feed it to the class list from q13 to identify and prioritise.
- **Feeds q15:** the src→dst object types in the firehose should all appear as real
  nodes here, tying the event graph to the object graph.

## Cleanup

Delete `game\q16_object_graph.py` and `game\BCProbe_q16_*.cfg` (and
`probe_harness.py` if unused elsewhere). Read-only probe; no game-file
modification.

## Findings

(To be filled in when the probe runs.)