# Bridge & character graph — the live interior tree (q17)

Status: PENDING
Author: Claude session (q17 bridge-graph plan)
Created: 2026-07-13
Closed:  —
Depends on: q14 (`probe_harness`), q16 (shared cast ladder / subsystem-tree walker)

## Goal

The interior counterpart to q16. Dump the **live bridge set**: the bridge object
graph, the officer roster at each station, the viewscreen, and — crucially for the
active Phase 2 work — **whatever character animation state the console can reach**.
q16 walks the space set and never touches any of this; the bridge is a distinct
object family (`BridgeSet`, `BridgeObjectClass`, `BridgeWindow`, `Character`) with
its own cast ladder.

## Background

Phase 2's actively-worked areas — character animation, bridge rendering, lift-door
behaviour (recent `fix(bridge)` commits) — are comparatively **under-observed**. We
have the SDK `Bridge/` scripts but no dump of what the real engine holds when a
bridge is live.

Static analysis already answers most of the "is it reachable?" question, so this
probe starts from a strong position rather than a blind one:

- **The bridge set:** `g_kSetManager.GetSet("bridge")` → `BridgeSet_Cast`.
- **The officer roster:** the bridge exposes `GetBridgeCharacter(station)` for the
  standard stations — `"Helm"`, `"Tactical"`, `"Science"`, `"Engineer"`, `"XO"`
  (confirmed usages across `Bridge/*.py`). So the roster is enumerable by name.
- **Character surface:** `Character` exposes `GetCharacterName()`, and the scene-
  graph / animation handles `GetAnimNode()`, `GetRootNode()`, `GetNode()`,
  `FindNode()`. So a character's **node graph is reachable** — the open question is
  narrowed to *what queryable state hangs off `GetAnimNode()`* (current clip? a
  playhead/time? just a transform?).
- **The viewscreen:** `BridgeWindow_Cast`.
- **Bridge objects:** walk the bridge set with the same `GetFirstObject` /
  `GetNextObject` loop q16 uses, casting each via `BridgeObjectClass_Cast`.

The one accessor still to confirm at implementation time is **how you obtain "the
bridge" object** to call `GetBridgeCharacter` on — SDK code uses
`GetBridge().GetBridgeCharacter(...)`; resolve the exact `GetBridge` origin
(module function vs. a method on the bridge set/player) when writing the probe.

## Scope decision (the q17 open question, now bounded)

q17 is **"bridge layout + node-graph existence + an animation-state
reconnaissance"**, not a blind "can we even see the bridge." Concretely:

- **Definitely in scope** (static analysis confirms reachable): station roster,
  character names, bridge object roster, viewscreen, each character's root/anim
  node existence and transform.
- **Reconnaissance sub-task** (Q17-4): dump `dir(GetAnimNode())` (and
  `dir(GetRootNode())`) for one character to *discover* the animation-state surface,
  then record whatever scalar/pose state those objects expose. This turns "is live
  animation queryable?" from an unknown into a one-shot finding — and decides
  whether a future q17b (animation sampling over time) is worth it.

## Specific questions

- **Q17-1** — Does `GetSet("bridge")` return a live set in each scenario, and what
  does it contain (object roster via the bridge cast ladder)?
- **Q17-2** — The officer roster: for each of the 5 standard stations, is there a
  `Character`, and what is its name / placement (world or node-local transform)?
- **Q17-3** — The viewscreen (`BridgeWindow`): present? what does it expose
  (dimensions, what it's showing)?
- **Q17-4** *(the reconnaissance)* — What state does `Character.GetAnimNode()` /
  `GetRootNode()` expose? Enumerate it (`dir`) and dump reachable scalars. Is a
  current animation clip / playhead / bone transform readable from Python at all?
- **Q17-5** — Lift/door objects and any bridge-specific subsystems in the set
  (relevant to the recent lift-door work) — do they appear as `BridgeObjectClass`
  nodes, and with what identifying state?

## The probe — `tools/probes/q17_bridge_graph.py`

One-shot `execfile()` probe, read-only. Reuses `probe_harness.provenance()` and the
q16 subsystem-tree walker / cast ladder, extended with the bridge cast set
(`BridgeSet_Cast`, `BridgeObjectClass_Cast`, `BridgeWindow_Cast`, `Character` cast).

Structure:

1. **provenance()** header. Also record whether a bridge set exists at all
   (`GetSet("bridge")` may be `None` if the bridge isn't loaded in this state —
   see runbook).
2. **Bridge object roster:** walk the bridge set (`GetFirstObject`/`GetNextObject`,
   bounded), cast each, record `objid | type | name | transform`.
3. **Officer roster (Q17-2):** obtain the bridge, loop the 5 station names, and for
   each present `Character` record name + placement.
4. **Character node recon (Q17-4):** for the **first** character found, dump
   `dir(GetAnimNode())` and `dir(GetRootNode())` (guarded), then attempt to read any
   scalar-looking members those expose. Keep this to one character to stay bounded —
   the goal is to *map the surface*, not sample all officers.
5. **Viewscreen (Q17-3):** `BridgeWindow_Cast` on the relevant object; dump its
   reachable properties.
6. **Flush** (chunked-capable via the harness).

Python-1.5 constraints as always (`console-probe-workflow.md`): guard every
accessor with bare `except`, no f-strings, `print` is a statement, `SaveConfigFile`
is the only write path. **Console discipline (q13 lesson):** the object/officer/dir
loops use the q14 harness's **buffer-only** helpers and never `print` per line —
only a final summary echoes. q17's volume is smaller than q16's, but the rule is
the same.

## How to run

Push `probe_harness.py` + `q17_bridge_graph.py`. **The bridge set must be loaded** —
starting any battle/mission loads the player's bridge, but you may need to have
**switched to bridge view at least once** for the set to be populated. The runbook
should have the operator flip to the bridge (the in-game bridge-view key), confirm
they see the bridge, then run the probe from the console.

**Scenario A — Galaxy v Galaxy QB.** Start the battle, flip to bridge view, then:
```python
execfile('q17_bridge_graph.py')
```
Writes `BCProbe_q17_A.cfg`. If the header shows `bridge_set = None`, the bridge
wasn't loaded — flip to bridge view and re-run.

**Scenario B — E1M1.** E1M1 has scripted bridge scenes (the Starbase 12 docking
dialogue) — run at those beats to capture characters mid-scene, which is also the
best chance to catch a non-idle animation for Q17-4. Writes `BCProbe_q17_B.cfg`.

Collect (`collect_q17.py`) and commit.

## Expected output

```
-- provenance ------------------------------------------------
scenario = B (mission)
bridge_set = present ('bridge')
-- bridge objects --------------------------------------------
bobj000 = ... | BridgeObjectClass 'Viewscreen' | ...
bobj001 = ... | Character 'Brex' | ...
-- officers (by station) -------------------------------------
Helm      = Character 'Ensign ...' pos=(...)
Tactical  = Character 'Brex' pos=(...)
Science   = Character '...' 
Engineer  = Character 'Graff'
XO        = Character '...'
-- character node recon (Brex) -------------------------------
GetAnimNode.dir = ['GetName', 'GetTime', 'GetActiveSequence', ...]   <- Q17-4 payload
GetAnimNode.GetTime = 3.20
...
-- viewscreen ------------------------------------------------
BridgeWindow present: shows=<...>
```

## Analysis

- **Q17-4 is the decisive one:** the `dir(GetAnimNode())` dump tells us whether
  live animation (current clip + playhead) is Python-readable. If **yes** →
  green-light **q17b** (sample animation state over a scripted E1M1 scene to
  ground-truth our character-animation timing). If **no** (transform-only) →
  Dauntless's animation validation must be done at the C++/NIF layer, not via the
  console, and we record that boundary.
- **Roster + placement** validate our bridge construction (the `LoadBridge` shim
  currently registers an empty bridge headless) — the real station→character
  mapping and transforms are the reference.
- **Q17-5 lift/door objects** cross-check the recent `fix(bridge)` lift-door work
  against the real object set (are doors first-class `BridgeObjectClass` nodes with
  queryable open/close state?).
- **Bridge cast coverage** mirrors q16-Q5: any bridge object matching no cast is an
  interior type we haven't wrapped.

## Cleanup

Delete `game\q17_bridge_graph.py` and `game\BCProbe_q17_*.cfg` (and
`probe_harness.py` if unused elsewhere). Read-only probe; no game-file
modification.

## Findings

(To be filled in when the probe runs.)