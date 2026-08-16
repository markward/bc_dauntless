# Contact index and perception query — design

**Date:** 2026-08-16
**Status:** design approved, spec under review
**Supersedes:** nothing. Replaces the per-set target-menu subscription introduced with
`_wire_target_menu_to_player_set`.

## Problem

Ships loaded in QuickBattle appear in the target list after the player has warped to a
different star system, despite being in the set the player left.

### Root cause

The target menu is an eagerly-maintained *mirror* of one set, bound once and never rebound.

`_wire_target_menu_to_player_set` (`engine/host_loop.py:5810`) subscribes
`_on_bridge_set_event` to the player's containing set, and is called only from the
mission-load path (`host_loop.py:6452`). Nothing re-subscribes on warp — the warp path
moves the player between sets (`engine/appc/warp.py:344`) and contains no target-menu
rewiring.

QuickBattle spawns into `g_pSet`, a module global assigned once at QB setup
(`sdk/Build/scripts/QuickBattle/QuickBattle.py:724`, or via QB's own region change at
`:2686`). Our Set Course warp never touches it, so new ships keep landing in the original
region — correctly, as far as the SDK is concerned. `SetClass.AddObjectToSet` fires
`"added"` to that set's subscribers (`engine/appc/sets.py:192`), the still-attached target
menu builds a row, and the contact appears.

Nothing culls it afterwards. `update_target_list_visibility`
(`engine/ui/target_list_visibility.py:63`) iterates the *player's current* set and looks
each ship up in the menu, so a row whose ship is not in that list is never visited and
keeps `_visible = True` (`engine/appc/characters.py:60`) indefinitely.

### The general fault

This is not a QuickBattle quirk. The target list has no concept of set scoping, so the
bug is symmetric:

- Ships added to the set the player *left* get phantom rows.
- Ships already in the destination set get **no** rows, because the subscription is still
  on the old set and nothing rebuilds on arrival. Warp engage clears the list
  (`warp.py:138`) and nothing repopulates it. Predicted from the code, not yet observed
  live.

The radar is unaffected because it already queries the player's current set every render
(`engine/ui/sensors_panel.py:96-113`) and uses the target menu only as a side-table join.
**The target list is the one consumer that mirrors instead of queries.** That is the
defect, and the fix is to make it query.

## Design

### Principle

> **The store holds what exists. The read answers what an observer perceives.**

The split is forced, not chosen: the store serves multiple observers (AI ships ask the
same question) and multiple lists (target, hail, scan). Range and nebula concealment are
inherently per-observer — the same ship is visible to one ship and not another at the same
instant — so perception can never be baked into stored state.

State is partitioned by how often it changes:

| Changes | Kind | Where it lives |
|---|---|---|
| On discrete events (spawn, set change, destroy) | membership | the index |
| On script events (rarely) | authored flags | read through to the object |
| Every frame | position, range, concealment | computed at read |

Nothing is duplicated into the index, so nothing can drift. Notably **positions are not
stored**: they have 100% turnover per frame, so a maintained copy is a duplicate with a
staleness risk rather than a cache.

### Units

**`engine/appc/contact_index.py` — `ContactIndex`** *(new)*
Ships bucketed by set. Maintained by events that already fire: `SetClass` add/remove
(`sets.py:126`) and `ship_lifecycle.publish_destroyed`. Only `ShipClass` instances enter,
so waypoints, grids, planets and the bridge-interior `ObjectClass` never appear. Knows
nothing about menus, UI, or observers.

Also caches the per-set nebula list. Nebulae essentially never spawn or despawn
mid-mission, so this is genuinely event-maintained state — see *Nebula hoist* below.

**`engine/appc/perception.py` — `perceived_by(observer)`** *(new)*
The single entry point. Takes the observer (not a loose `(system, location, radius)`
triple, so callers cannot pass an inconsistent set). Returns finished records:

```python
Contact(ship, dist_sq_gu, surface_gu, perceivable: bool, targetable: bool)
```

`perceivable` is the perception core shared by every list. `targetable` is the target
list's own gate composed on top (`perceivable ∧ _targetable ∧ alive-or-wreck ∧ not self`)
— carried on the record rather than left to the caller so the target list and SDK
`CycleTarget` cannot disagree. Hail and scan add their one-line gates the same way when
they adopt this.

Consumers do no further arithmetic. Distance is computed **once per contact per frame**
and reused by every consumer.

**`TargetRowCache`** *(new, beside `STTargetMenu`)*
Owns `STSubsystemMenu` lifecycle only: create a row, rebuild its subsystem tree on
`RebuildShipMenu`, evict on `publish_destroyed`. Rows survive leaving a system, so a warp
round-trip keeps subsystem trees warm. Knows nothing about sets or detectability.

**`STTargetMenu`** *(modified)*
Stays the SDK-facing façade. Gains `set_contacts()`; every child accessor becomes a
projection of the row cache over the perception result.

Dependencies run one way with no cycles:
`ContactIndex` ← `perception` ← `STTargetMenu` → `TargetRowCache`, UI reads the façade.

### Why derived accessors

The SDK **only reads** the target menu's children — `GetFirstChild`, `GetNextChild`,
`GetPrevChild`, `GetLastChild`, `GetObjectEntry`, `GetNumChildren`, `GetSubmenuW`
(`TacticalInterfaceHandlers.py:692`, `E2M0.py:3692`). Its only mutations are
`ClearTargetList`, `ClearPersistentTarget` and `RebuildShipMenu`. No SDK script calls
`AddChild` on the target menu. So the children can become a computed projection without
any SDK consumer noticing.

Our own UI survives it too: all top-level traversal goes through the accessors
(`target_list_view.py:218/278`, `ships.py:1515`), the only direct `_children` read is on
sub-rows, and accordion expansion state is keyed by ship-name strings
(`target_list_view.py:246`) rather than row identity.

Row objects are cached per ship so identity stays stable — `CycleTarget` calls
`GetObjectEntry(target)` then walks `GetNextChild` from it. Only *membership* is derived.

`IsVisible()` becomes derived membership. This is load-bearing: SDK `CycleTarget` skips
rows where `not IsVisible()` (`TacticalInterfaceHandlers.py:701-730`), and today the
visibility pass and the panel filters use **different rules** — the flag pass ignores
death entirely while `target_list_view.py:225` drops dead non-wrecks. Tab-cycling can
therefore select a contact the target list refuses to display. Deriving both from one
answer removes the divergence by construction.

### Reasons a contact is not listed

Ordered as evaluated. 1, 2 and 4 are answered by the index structure alone — no test runs
at read. 3 is a single identity comparison.

1. **Not in the observer's system** — different set, including ships mid-warp in
   `_WarpTransit` (`warp.py:459`) *(structural)*
2. **Not a contact type** — waypoint, grid, planet, bridge interior *(structural: only
   `ShipClass` enters a bucket)*
3. **It is the observer** *(target-list gate)*
4. **Destroyed and past the wreck-linger window** *(structural: see eviction below)*
5. **A mission hid it** — `SetTargetable(0)` *(target-list gate; see Gap below)*
6. **Cloaked** — beyond the cloak-perception range *(perception)*
7. **Beyond effective sensor range** — `base × condition% × power%`, so 0 when sensors are
   dead or unpowered, which empties the list entirely *(perception)*
8. **Nebula concealment** above threshold, with per-pair hysteresis *(perception)*

6–8 form `perceivable`; 3 and 5 plus the wreck rule form the target list's `targetable`
gate on top. Both are computed in `perceived_by` and carried on the record.

**Eviction timing.** A wreck must stay listed through its linger window
(`ship_death.py:162`). That is automatic: `publish_destroyed` fires from `_mark_dead` at
the *end* of the throes/linger, immediately before `_remove` takes the ship out of its set
— not at death onset, where `ET_OBJECT_EXPLODING` fires instead. Both signals therefore
coincide with removal, and evicting on either is correct. Do not hook the explosion
event: that would drop the row while the wreck is still meant to be selectable.

Evaluation order is cheapest-and-most-selective first: bucket lookup, then the observer
skip, then cheap bools (targetable, cloak), then squared distance (no `sqrt`), then the
nebula sample last — so the expensive term runs on the smallest surviving candidate set.

A single check precedes all of it: if the observer's effective sensor range is 0, return
empty without iterating.

### Not exclusions

- **Unidentified** contacts display as "Unknown"; they do not disappear
  (`sensor_identification.py`)
- **`IsHailable` / `IsScannable`** gate the Hail menu and Science scan menu — the same
  contacts, a different one-line predicate

The decomposition:

```
perceivable(O,S) = same system ∧ not cloak-hidden ∧ in range ∧ not nebula-concealed
targetable(O,S)  = perceivable ∧ _targetable ∧ alive-or-wreck ∧ not self
hailable(O,S)    = perceivable ∧ _hailable
scannable(O,S)   = perceivable ∧ _scannable
```

One perception core, three thin authored gates. This spec rewires the target list and the
radar; hail and scan adopt it later without re-plumbing.

### Distance: computed once

The same player→contact vector is currently derived in five places per frame under two
conventions:

| Site | Convention |
|---|---|
| `target_list_visibility.py:72` | centre |
| `sensor_detection.py:165` | centre |
| `sensors_panel.py:110` | centre |
| `reticle_text.py:47` | **surface** (− `GetRadius`) |
| `ship_display_panel.py:554` | **surface** (− `GetRadius`) |

`perceived_by` computes it once and carries both: squared centre distance for the range
tests, surface distance for the readouts.

**Detection measures to centre**, unchanged. The surface convention is confirmed only for
the *readout* (`reticle_text.py:50-58`, verified against the original game by orbiting
Haven); there is no evidence BC measures detection that way. The split becomes explicit
rather than accidental.

**The radar keeps its own display clip.** Radar range is a zoom setting read from
`RadarDisplay.GetRange` (default 1,000 GU) while the target list uses the player's actual
sensor range (2,000 GU on a Galaxy). The target list legitimately lists contacts the radar
does not draw. Display scale and perception are different concepts; the shared query owns
perception only. Collapsing them would break radar zoom.

### Nebula hoist

`concealment_at` calls `pSet.GetClassObjectList(App.CT_NEBULA)` — a full set scan to find
nebulae — **once per ship, per frame** (`sensor_detection.py:99`). Twenty contacts means
twenty scans a frame to rediscover the same list, which is usually empty.

The `ContactIndex` caches the per-set nebula list. Sets with no nebulae then skip the term
entirely on one check.

The density function already early-outs before the expensive fBm when the sample point is
outside the sphere union (`nebula_density.py:81-83`), so no further broad-phase is needed.

Concealment cannot be a stored flag: it is a scalar that *scales* effective range rather
than gating it, and the noise field drifts with time (`nebula_density.py:85`), so a
stationary ship's concealment changes with no movement event to hang an update on.

## Behaviour changes

Three, all deliberate. Each gets a test that **pins** it, with a comment stating it is
intended, so a later reader does not "fix" it back.

### 1. Nebula concealment reaches the UI

Today `update_target_list_visibility` uses range + cloak + sensors-offline, while
`can_detect` additionally applies nebula concealment with hysteresis. Consolidating on
`can_detect` means a nebula-concealed ship drops off the target list and radar, not just
out of weapons lock.

This makes the codebase honest about a claim it already makes:
`clear_undetectable_player_lock` documents "the target list empties (its gate consults the
sensors)" (`sensor_detection.py:171`), which is not true today.

### 2. Cloak becomes range-defeatable

Cloak stops being an early return and becomes a range multiplier:

```python
if cloak is not None and cloak.IsCloaked():
    r = r * CLOAK_RANGE_FACTOR   # 0.01, was: return False
```

At 1% of effective sensor range:

| Ship | Sensor range | Cloak detection |
|---|---|---|
| Galaxy | 2,000 GU | 20 GU (3.5 km) |
| Sovereign | 2,400 GU | 24 GU |
| Warbird | 3,000 GU | 30 GU |

Galaxy phaser range is 60 GU, so detection sits at one third of weapons range — the
observer must be effectively on top of the target. Because it is a percentage of
*effective* range, it scales with sensor condition and power: boosting sensor power
extends it, wrecked sensors remove it.

**Symmetric** — AI ships get the same capability, and since `can_detect` is also the AI
target-selection and firing gate, cloaked attack runs become detectable at close range.
1% was chosen over 1.5% specifically to keep cloak viable.

The per-pair hysteresis band (`_broken`, `HYSTERESIS`) is what keeps a contact near the
threshold fading rather than strobing per frame. Cloak inherits it by becoming a
concealment term.

### 3. Divergence toggle

Both of the above diverge from stock BC, where cloak is absolute and nebulae do not affect
the target list. They go behind a toggle in the same shape as the Modern VFX work —
enhancement on by default, off returns stock behaviour — rather than silently redefining
what cloak means.

## Gap closed: object-level `SetTargetable`

`ObjectClass.IsTargetable` and `ShipClass.IsTargetable` are real published Appc surface
(`sdk/Build/scripts/App.py:3924`, `:5480`), but `engine/appc/objects.py` implements only
`IsHailable` and `IsScannable`. `SetTargetable` therefore hits `TGObject.__getattr__`,
returns a silent `_Stub`, and no-ops; `IsTargetable()` returns a truthy `_Stub`.

Confirmed live: `docs/stub_heatmap.md:175` — rank 161, 18 hits across 3 sessions.

The SDK relies on it in ten-plus places to narratively hide a contact until a reveal beat:
E3M1's Amagon, E3M2's Warbird and Kessok, E6M4's Kessok and Keldon, E6M2's probe, E5M2's
outpost, E3M5's Gon device, and the E2M1/Belaruz4/Cebalrai1 asteroid fields. Every one of
those ships is currently still targetable.

Implemented alongside the existing hailable/scannable pair, following the same shape:
default on the class, missions override, and a change broadcast — `ET_HAILABLE_CHANGE` and
`ET_SCANNABLE_CHANGE` have targetable's equivalent, so a reveal updates immediately rather
than at the next rebuild.

Kept as a **separate stored flag from cloak**, deliberately. The mission owns the authored
flag; the cloaking subsystem owns cloak state. One shared boolean would mean decloak
writing `1` and wiping a mission's `0` — and E6M4's Kessok is both cloaked *and*
`SetTargetable(0)` at once (`E6M4.py:1932`), so the clash is real, not hypothetical.

## Consequences

**Warp needs no target-list code.** During transit the player is in `_WarpTransit`, so the
query returns empty and the list clears itself; on arrival it populates from the
destination set. `_clear_all_targets` loses its `ClearTargetList()` call. This is the test
of whether the model is right.

**`ClearTargetList` changes meaning.** It is SDK surface (`MissionShared.py:352`). Under a
derived list it can only clear the row cache and the persistent target, not the contents.

**`engine/ui/target_list_visibility.py` is deleted.** Writing `IsVisible` per row is
exactly what becomes derived.

**`sensors_panel` and `target_list_view` stop re-deriving their own filters** and read the
perception result. Net line count should fall.

## Designed for, not built

**Cloak as a concealment contributor** is already the shape above, so a future
sensor-strength contest is confined to `can_detect` alone. Moving the UI onto
`can_detect(observer, target)` is the enabling step: today's `is_hidden_by_cloak(ship)`
has no observer parameter and *cannot* express "visible to this ship but not that one".

**Partial-lock UI** is deferred. The concealment scalar is the natural input for a partial
contact strength; nothing here blocks it.

No speculative parameters or hooks are added now. The value is that nothing else needs to
move later.

## Staging

Four landings, so a structural fix and a gameplay change are never bisected together.

1. **Index + membership** — fixes the reported bug. No behaviour change.
2. **`SetTargetable`** — closes the live gap. Independently testable.
3. **Detectability consolidation** — one predicate, still on the current rule. Deletes
   `target_list_visibility.py`; folds in the distance-computed-once and nebula hoist.
4. **Gameplay changes** — nebula in the UI, cloak at 1%, behind the toggle.

## Risks

**Hysteresis latch coupling.** `can_detect` mutates a module-global `_broken` set keyed by
`(id(observer), id(target))` (`sensor_detection.py:156-162`). Once the UI calls it, the UI
drives the same latch the weapons read. The query must call it **once per contact per
frame** — this is a correctness requirement, not an optimisation.

**Blast radius.** Roughly 30 target-list tests, plus `target_list_visibility`'s own tests,
which are deleted rather than updated. `scripts/check_tests.sh` is the gate; never call a
failure pre-existing by eyeball.

**New per-frame cost.** Nebula sampling joins the UI path, which it is not on today. The
hoist above is the mitigation. No cost claim in this document has been measured — at tens
of ships per system none is expected to matter, but this is reasoning, not evidence.

**Behaviour changes must stay pinned.** See *Behaviour changes*.

## Out of scope

- **`FALLBACK_RANGE_GU = 30000`** is 15× a Galaxy's real sensor range and is what any ship
  without a resolvable sensor subsystem receives. Worth confirming the player never lands
  on that path. Separate investigation.
- **`GetTranslate()` vs `GetWorldLocation()`** — `reticle_text` reads one,
  `ship_display_panel` the other. If they ever diverge, two HUD elements disagree about
  the same range. Unifying falls out of stage 3 for free.
- **QuickBattle asteroids** flying and announcing "simulated enemy ship destroyed" is
  stock BC: `QuickBattle.py:601` authors `ST_ASTEROID` with `QuickBattleAI` and
  `QBEnemyGenericShipDestroyed`. Not a ship/asteroid conflation in our engine. Whether the
  asteroid should physically move is a separate open question.
