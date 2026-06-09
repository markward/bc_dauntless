# Faithful Hardpoint Subsystem Loading — Design

**Date:** 2026-06-09
**Status:** Approved (design); pending implementation plan
**Finding origin:** Surfaced by the Ship Property Viewer (only 23 subsystems shown for the
Galaxy; engine nacelles/pods missing from the viewer and the target list).

## Problem

Ship construction builds the live subsystem tree from hardpoint-registered property
templates via an **allow-list**: `ShipClass.SetupProperties` (`engine/appc/ships.py`)
has `isinstance` branches for a fixed set of top-level subsystems, and `_CHILD_DISPATCH`
materializes only four weapon child types (`PhaserProperty`, `PulseWeaponProperty`,
`TractorBeamProperty`, `TorpedoTubeProperty`). Anything the allow-list does not handle
is silently dropped.

The hardpoint files (ground truth: `sdk/Build/scripts/ships/Hardpoints/Galaxy.py`)
register a consistent **aggregator + targetable-leaf** pattern. Several leaf categories
have no construction path:

| Hardpoint group | Aggregator (`Targetable=0`) | Leaves (`Targetable=1`) | Built today? |
|---|---|---|---|
| Phasers | `Phasers` (WST_PHASER) | 8× `PhaserProperty` banks | yes (`_CHILD_DISPATCH`) |
| Torpedoes | `Torpedoes` (WST_TORPEDO) | 6× `TorpedoTubeProperty` | yes |
| **Impulse** | `Impulse Engines` | **Port/Star/Center Impulse** (`EngineProperty` EP_IMPULSE) | **no — dropped** |
| **Warp** | `Warp Engines` | **Port/Star Warp** (`EngineProperty` EP_WARP) | **no — dropped** |
| **Tractors** | `Tractors` (WST_TRACTOR) | 4× `TractorBeamProperty` | aggregator maps, but omitted from viewer/damage getters |
| Object emitters | — | Shuttle Bay, Probe Launcher (`ObjectEmitterProperty`) | **no — not built** |
| Bridge | 2nd `HullProperty` (`Primary=0`) | — | **no — dropped (only 1st Hull kept)** |

The five `EngineProperty` leaves (all `Targetable=1`) have no leaf class and no
construction path, so they are absent from the viewer, the 2D damage schematic, the
player target list, and gameplay targeting/damage.

## Decisions (from brainstorming)

1. **Scope:** everything registered in the hardpoint files must load.
2. **Integration depth:** newly-loaded targetable subsystems are player-targetable and
   damageable, and shown in the viewer/damage panel.
3. **AI:** unchanged in this work, and unchanged *for free*. `ShipSubsystem.IsTargetable()`
   is currently hardcoded to return `1` (`engine/appc/subsystems.py:920`), so the SDK AI
   loop (`GetTargetableSubsystems`, which only recurses into children of *non-targetable*
   parents) never recurses into any children. Attaching pods/emitters/bridge as children
   therefore does not reach the AI path at all — no parallel hierarchy required. Full
   stock-BC AI fidelity (enemies targeting individual nacelles/pods) requires a broad
   `IsTargetable()` overhaul touching every ship; that is **deferred** to a follow-up,
   documented in `docs/superpowers/specs/2026-06-09-subsystem-targetability-fidelity-followup.md`.
4. **Object emitters:** mount-only. Created as non-targetable, non-damageable mount
   markers, surfaced in the Property Viewer as informational pins, excluded from the
   target list and damage panel. No launch gameplay in this work.
5. **Target menu:** hierarchical. Aggregators (Phasers, Torpedoes, Impulse Engines, Warp
   Engines, Tractors) remain parent rows; expanding one reveals its child leaves
   (banks / tubes / pods / nacelles / emitters) as a second accordion level. Nothing
   currently targetable stops being targetable.

## Enumeration landscape (why the fix touches several paths)

Our engine has four divergent subsystem-enumeration paths (stock BC has one unified tree):

| Path | Walks | Sees children? |
|---|---|---|
| AI rating loop (`sdk/.../AI/Preprocessors.py:865`) | `GetSubsystems()` → `GetTargetableSubsystems()` | yes — recurses into children of **non-targetable** parents only |
| Player target menu (`engine/appc/target_menu.py:156`) | `StartGetSubsystemMatch(CT_SHIP_SUBSYSTEM)` | **no — top-level slots only** |
| Combat damage (`engine/appc/combat.py:279`) | `GetSubsystems()` + one level of `_children` | yes |
| Viewer / damage panel (`engine/ui/ship_display_panel.py:447`) | `_DAMAGE_SOURCE_GETTERS` + one level of children | yes — but the getter list **omits tractors** |

The BC-faithful model is a single tree: leaves are children of their aggregators.

**Targetability nuance (decisive for "AI unchanged"):** in stock BC the AI recurses into
children of `Targetable=0` aggregators, so pods/emitters would become AI targets. But our
`ShipSubsystem.IsTargetable()` is hardcoded to `1`, so the SDK AI loop sees *every* parent
as targetable and never recurses into children. Adding children therefore leaves the AI
path untouched with no special-casing. (See decision 3 and the deferred follow-up.)

Note also that `StartGetSubsystemMatch(CT_SHIP_SUBSYSTEM)` returning top-level subsystems
only is **BC-faithful**: the SDK's own `MissionLib.HideSubsystems:2187` iterates it
top-level and then recurses children *manually* (`HideSubsystem:2172`). So §5 does not
change the iterator — the menu *builder* recurses, matching the canonical SDK pattern.

## Design

### Section 1 — Core principle: one faithful tree, type-driven dispatch

Generalize `SetupProperties`' child pass from a 4-entry allow-list to complete dispatch
over the property set, so every leaf property finds its home. The aggregator→leaf shape is
already proven for phasers; extend the same shape to engines, tractors, and the bridge.

| Leaf property | Attaches as child of | Leaf runtime class |
|---|---|---|
| `EngineProperty` EP_IMPULSE | `_impulse_engine_subsystem` | `ShipSubsystem` |
| `EngineProperty` EP_WARP | `_warp_engine_subsystem` | `ShipSubsystem` |
| `TractorBeamProperty` | `_tractor_beam_system` | `TractorBeam` (exists) |
| 2nd+ `HullProperty` | primary `_hull` | `HullSubsystem` |

BC uses no dedicated engine-leaf class — `EngineProperty` leaves are plain `ShipSubsystem`
instances (confirmed: `sdk/.../App.py` has `EngineProperty` but no `EngineSubsystem`
class). Engine pods dispatch on `GetEngineType()`, so the child pass needs an
`EngineProperty` branch that reads EP_IMPULSE/EP_WARP and selects the aggregator.

**Prerequisite:** add real `GetEngineType`/`SetEngineType` to `EngineProperty`
(`engine/appc/properties.py:804`). Today they fall through to a `_NamedStub`, so the
hardpoint's `SetEngineType(EP_WARP)` value is lost. Mirror the SDK accessor
(`App.py:9869-9870`). Default engine type before being set: EP_IMPULSE (0).

### Section 2 — Engine pods

The five `EngineProperty` leaves become `ShipSubsystem` leaves under their aggregator,
copying name, `MaxCondition`, `Position`, `Position2D`, `Targetable`, `Critical`,
`DisabledPercentage`, `Radius`, `RepairComplexity`.

Result: they appear in the viewer (aggregators already in `_DAMAGE_SOURCE_GETTERS`, which
recurses one level), in the 2D damage schematic (non-zero `Position2D`), and become
damageable (combat walks `_children`). Player-targetability arrives with Section 5.

### Section 3 — Tractors

`_tractor_beam_system` is pre-allocated (`ships.py:1099`) and `WST_TRACTOR` maps to it in
`SetupProperties`, so the aggregator likely already survives — but the finding reported it
as `None`. **Step one is a failing test that pins the actual runtime state** before
changing anything.

Then:
- Ensure the 4 `TractorBeamProperty` emitters (Aft/Forward Tractor 1/2) materialize as
  `TractorBeam` children — the `_CHILD_DISPATCH` entry exists; verify it is not skipped
  (e.g. by Pass-3 scrubbing of the parent slot).
- Add `GetTractorBeamSystem` to `_DAMAGE_SOURCE_GETTERS`
  (`engine/ui/ship_display_panel.py:423`) so the aggregator + emitters surface in the
  viewer and damage panel (currently omitted).

### Section 4 — Bridge (second hull)

The 2nd `HullProperty` ("Bridge", `Primary=0`, `Targetable=1`) becomes a `HullSubsystem`
attached as a **child of the primary hull**. `GetHull()` still returns the primary
(unchanged — `SetupProperties` already keeps only the first `HullProperty` as the
primary). Because the primary hull is `Targetable=1`, the AI loop does not recurse into
it, so the bridge is player-targetable + damageable + shown in the viewer without
perturbing AI.

### Section 5 — Hierarchical target menu (aggregators expand to children)

`StartGetSubsystemMatch(CT_SHIP_SUBSYSTEM)` stays unchanged (top-level only — BC-faithful).
The fix lives in the menu *builder* and the CEF renderer, producing a two-level accordion:
**ship → subsystem (aggregator) → child leaf**.

- `STSubsystemMenu.RebuildShipMenu` (`engine/appc/target_menu.py:130`): for each top-level
  subsystem matched, add its row; then recurse into `GetNumChildSubsystems()` /
  `GetChildSubsystem(i)` (the canonical `HideSubsystem` pattern) and add each child as a
  nested row beneath it. `STMenu` rows gain child rows.
- `TargetListView` (`engine/ui/target_list_view.py`): the per-ship `subsystems` snapshot
  entries gain an optional `children: [{name, condition}]` list and a per-subsystem
  `expanded` flag; track expanded subsystems keyed by `"<ship>/<subsystem>"`. Add a
  subsystem-level toggle action `target/<ship>/<subsystem>/__toggle__`.
- `target_list.js` (`native/assets/ui-cef/js/target_list.js`): render child rows with their
  own caret + toggle when the parent subsystem row is expanded; clicking a child emits
  `target/<ship>/<subsystem-or-child-name>`. `_resolve_subsystem_by_name` already resolves
  by name; extend it to also search child subsystems so a child click locks the leaf.
- CSS: a nested-indent style for the third accordion level (target-list CSS).

Nothing currently targetable stops being targetable; this is purely additive (children
become reachable by expanding their aggregator).

### Section 6 — Object emitters (viewer-only mounts)

`ObjectEmitterProperty` (Shuttle Bay, Probe Launcher) are not subsystems (no condition, no
targetable). Add:
- A lightweight `ObjectEmitter` runtime object (name, position, orientation,
  emitted-object-type), stored in a new `ship._object_emitters` list populated during
  `SetupProperties`, exposed via `GetObjectEmitters()`.
- The Property Viewer's own iterator (`engine/ui/ship_property_viewer.py:_iter_subsystems`)
  yields these as a distinct "mount marker" descriptor with an informational pin style —
  **separate** from `_iter_damage_subsystems`, so emitters never appear in the damage
  panel or the target list.

Mount markers need a pin glyph fallback: `ObjectEmitter` has no `IconNum`, so
`damage_icons.icon_num_for_subsystem` needs a sensible default (or the viewer uses a
dedicated emitter glyph). Engine pods / tractors / bridge likewise lack weapon-style icons
in the hardpoint and need an icon fallback in the viewer pin path.

## Components and boundaries

- `engine/appc/properties.py` — add `EngineProperty.GetEngineType/SetEngineType`; add
  `ObjectEmitter` runtime class (or reuse an existing mount type if one fits).
- `engine/appc/ships.py` — generalized child dispatch in `SetupProperties`; `_object_emitters`
  storage + `GetObjectEmitters()`; full-tree recursion in `StartGetSubsystemMatch`.
- `engine/appc/subsystems.py` — no new leaf class required (engine pods are `ShipSubsystem`);
  confirm `AddChildSubsystem` / child-walk APIs cover the new children (they do).
- `engine/ui/ship_display_panel.py` — add `GetTractorBeamSystem` to `_DAMAGE_SOURCE_GETTERS`.
- `engine/ui/ship_property_viewer.py` — viewer iterator yields emitter mount markers;
  icon fallback for pins without a weapon icon.

## Testing posture

TDD throughout. Each section begins with a focused failing test, then implementation:

- Galaxy has 3 impulse-pod `ShipSubsystem` children under the impulse aggregator, 2 warp
  nacelle children under the warp aggregator, each with the hardpoint's `Position` /
  `MaxCondition` / `Targetable`.
- `EngineProperty.GetEngineType()` returns the value set by the hardpoint.
- Tractor aggregator survives with 4 `TractorBeam` emitter children; tractor system is
  reachable from the damage/viewer getters.
- Bridge is a `Targetable=1` `HullSubsystem` child of the primary hull; `GetHull()` still
  returns the primary; AI walk does not include the bridge.
- `RebuildShipMenu` produces nested rows: the impulse aggregator row has 3 child rows
  (Port/Star/Center Impulse), the warp aggregator 2 (Port/Star Warp), the tractor aggregator
  4 emitters, the phaser aggregator 8 banks. `_resolve_subsystem_by_name` resolves a child
  leaf (e.g. "Port Warp") to the live subsystem instance.
- Galaxy exposes exactly 2 `ObjectEmitter`s (Shuttle Bay, Probe Launcher), and they do
  **not** appear in `_iter_damage_subsystems` or the target list.

**Run only focused pytest subsets — the full `bc_dauntless` suite OOMs the host.**

## Staging

§1+§2 (engine pods) → §3 (tractors) → §4 (bridge) → §5 (player-menu recursion) →
§6 (emitters). Each stage is independently mergeable.

## Out of scope

- Shuttle/probe launch gameplay (emitters are mount-only here).
- Render-scale / hardpoint-coordinate mismatch (Finding 2 — separate investigation).
- Re-tuning enemy AI for the now-larger targetable-subsystem set (accepted as stock-BC).
