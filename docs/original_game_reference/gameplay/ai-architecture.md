# AI Architecture

Reverse-engineered structure of the Bridge Commander AI system: the
hierarchical behaviour tree, the C++ runtime classes that drive it,
the Python scripting bridge, the tick scheduler, and the catalogue
of shipped AI scripts.

Crucially, **stock multiplayer has no AI opponents**. AI is single-
player / campaign only. The whole AI subsystem is client-local —
the C++ AI tick scheduler runs only on the machine that owns the
ship.

---

## C++ class hierarchy

```
BaseAI                    (vtable 0x0088BB54)
 ├── PlainAI              (vtable 0x0088C0D8)
 ├── ConditionalAI        (vtable 0x0088BC84)
 ├── PriorityListAI       (vtable 0x0088C188)
 ├── RandomAI             (vtable 0x0088C1DC)
 ├── SequenceAI           (vtable 0x0088C230)
 └── PreprocessingAI      (vtable 0x0088C12C)
       └── BuilderAI      (vtable 0x0088BBE0)
```

Constructors (`__thiscall`) and the `__cdecl` `AllocAndConstruct`
wrappers used by SWIG (`App.PlainAI_Create`, etc.):

| Class            | Constructor   | Vtable        |
|------------------|---------------|---------------|
| `BaseAI`         | `0x00470520`  | `0x0088BB54`  |
| `PlainAI`        | `0x0048CC40`  | `0x0088C0D8`  |
| `ConditionalAI`  | `0x00478A50`  | `0x0088BC84`  |
| `PriorityListAI` | `0x0048FCB0`  | `0x0088C188`  |
| `RandomAI`       | `0x00491370`  | `0x0088C1DC`  |
| `SequenceAI`     | `0x004927D0`  | `0x0088C230`  |
| `PreprocessingAI`| `0x0048E2B0`  | `0x0088C12C`  |
| `BuilderAI`      | `0x00475FB0`  | `0x0088BBE0`  |

---

## Vtable

The `BaseAI` vtable defines the dispatch points for the behaviour
tree:

| Slot | Method        | Description                                           |
|------|---------------|-------------------------------------------------------|
| 0    | `SetActive`   | Node becomes active in the tree                       |
| 1    | `SetInactive` | Node deactivated                                      |
| 2    | `GotFocus`    | Node gains execution focus from its parent             |
| 3    | `LostFocus`   | Node loses focus (higher-priority sibling took over)  |
| 4    | `Update`      | Main tick — returns `ACTIVE` / `DORMANT` / `DONE`     |
| 5    | `IsDormant`   | Returns dormancy state                                |

Each subclass overrides as needed. `PlainAI::Update` dispatches to
the Python script's `Update()`; `ConditionalAI::Update` evaluates
conditions before invoking its child; `PriorityListAI::Update`
iterates children by priority.

### Return states

```c
enum UpdateStatus {
    US_ACTIVE  = 0,    // currently executing
    US_DORMANT = 1,    // temporarily inactive
    US_DONE    = 2,    // completed or failed
};
```

Exposed to Python as `App.ArtificialIntelligence.US_ACTIVE`,
`US_DORMANT`, `US_DONE`.

---

## Tick scheduling

Each ship has its own AI scheduler that invokes the root AI node's
`Update()` at a configurable rate. There is **no global AI
coordinator** — schedulers are per-ship.

| Function                | Address     | Description                                                     |
|-------------------------|-------------|------------------------------------------------------------------|
| `Ship::AITickScheduler` | `0x004721B0`| Checks elapsed time, decides whether to run `ProcessAITick`     |
| `Ship::ProcessAITick`   | `0x004722D0`| Calls root AI's `Update()`, processes the return value          |

The tick rate is **not fixed**. Individual scripts request their
own next-update interval — for example `CircleObject.GetNextUpdateTime()`
returns 0.5 s, while `Intercept.GetNextUpdateTime()` returns
0.4 ± 0.2 s (randomised to prevent synchronised updates across ships).

---

## Python ↔ C++ bridge

### `pCodeAI` handle

Every Python AI script receives a `pCodeAI` reference to its C++ AI
object. This is the bridge:

```python
class BaseAI:
    def __init__(self, pCodeAI):
        self.pCodeAI = pCodeAI
```

Key methods on `pCodeAI`:

- `GetShip()` — the ship this AI controls.
- `RegisterExternalFunction(name, dict)` — register a callable for
  the C++ runtime.
- `StopCallingActivate()` — optimisation: tells C++ to skip
  `Activate()` calls if the base-class version has nothing to do.

### Lifecycle

1. **Creation** — `App.PlainAI_Create(pShip, "Name")` allocates the
   C++ object; the Python script's `__init__(pCodeAI)` runs.
2. **Configuration** — Python calls setup methods (e.g.
   `SetFollowObjectName`, `SetCircleSpeed`).
3. **Activation** — when the node becomes active, `Activate()`
   validates required parameters.
4. **Update loop** — `Update()` runs each AI tick; returns
   `US_ACTIVE` / `US_DORMANT` / `US_DONE`.
5. **Deactivation** — `LostFocus()` if interrupted; `SetInactive()`
   when fully removed.

### Save / load

AI state persists via Python `pickle`:

- `__getstate__()` returns `__dict__` copy and converts module
  references to strings.
- `__setstate__(dict)` restores the dict and re-imports modules.
- `FixCodeAI(pCodeAI)` is called after load to update the C++
  pointer (which is invalid after deserialisation).

| Helper                  | Address      |
|-------------------------|--------------|
| `SaveGame::InitPickler` | `0x006F9FB0` |
| `SaveGame::FlushPickler`| `0x006FA020` |

---

## Node behaviours

### `PlainAI` — leaf

Wraps a Python script class. The C++ runtime calls the script's
`Update()` each tick; the script controls the ship via SWIG calls
(`SetImpulse`, `TurnTowardLocation`, etc.).

27 shipped `PlainAI` scripts (`reference/scripts/AI/PlainAI/`):

| Script                  | Behaviour                                              |
|-------------------------|--------------------------------------------------------|
| `CircleObject`          | Orbit a target; fuzzy logic for distance / facing      |
| `IntelligentCircleObject`| `CircleObject` with shield-aware facing               |
| `Intercept`             | Predicted-intercept vector + obstacle avoidance         |
| `Flee`                  | Disengage and run                                       |
| `FollowObject`          | Maintain formation distance behind a leader             |
| `FollowThroughWarp`     | Follow target through warp / set transitions            |
| `FollowWaypoints`       | Sequence of waypoints with per-waypoint speed           |
| `GoForward`             | Fly straight at configured speed                        |
| `Stay`                  | Hold position (zero throttle)                           |
| `TorpedoRun`            | Approach from optimal torpedo angle, fire, break away   |
| `PhaserSweep`           | Maintain phaser arc, sweep beam across target           |
| `StationaryAttack`      | Attack without moving (turret mode)                     |
| `StarbaseAttack`        | Attack approach optimised for large stationary targets  |
| `Ram`                   | Direct collision course                                 |
| `Defensive`             | Defensive maneuvering (shield-management priority)      |
| `ManeuverLoop`          | Pre-defined manoeuvre pattern                           |
| `MoveToObjectSide`      | Position on a specific side of target                   |
| `TurnToOrientation`     | Rotate to face a specific direction                     |
| `Warp`                  | Engage warp drive                                       |
| `SelfDestruct`          | AI self-destruct via `DestroySystem(hull)`              |
| `TriggerEvent`          | Fire a game event                                       |
| `RunAction`             | Execute a timed action sequence                         |
| `RunScript`             | Run arbitrary Python script as AI behaviour             |
| `EvadeTorps`            | Dodge incoming torpedoes                                |
| `EvilShuttleDocking`    | Hostile shuttle docking approach                        |

### `ConditionalAI`

Holds one child AI plus one or more `ConditionScript` objects. Per
tick:

1. Evaluate all conditions to booleans.
2. Python evaluation function maps results to `US_*`.
3. If `ACTIVE`, dispatch to the child's `Update()`.

### `PriorityListAI`

Ordered children by priority. Highest priority wins. First child
returning `US_ACTIVE` claims execution; lower-priority children are
interrupted (when `SetInterruptable(1)`).

### `SequenceAI`

Children run in order. When one returns `US_DONE`, advance. Sequence
completes when every child is done.

### `RandomAI`

Picks one child at random; on completion, picks another.

### `PreprocessingAI`

Wraps a child AI with a preprocessing step that runs *before* the
child each tick. Used for cross-cutting concerns:

- `FireScript` — auto-fire weapons at target.
- `AvoidObstacles` — steer away from nearby objects.
- `ShieldManager` — adjust shield facing.
- `WarpBeforeDeath` — emergency warp at low hull.

### `BuilderAI`

Meta-node extending `PreprocessingAI`. Used by compound scripts
(`FedAttack`, `NonFedAttack`) to build large (~30-node) trees
declaratively:

```python
pBuilderAI = App.BuilderAI_Create(pShip, "Name", __name__)
pBuilderAI.AddAIBlock("TorpRun", "BuilderCreate1")
pBuilderAI.AddDependencyObject("TorpRun", "sTarget", sTarget)
```

---

## Compound behaviours

15 shipped Compound AI scripts (`reference/scripts/AI/Compound/`):

| Script                    | Purpose                                                                   |
|---------------------------|---------------------------------------------------------------------------|
| `BasicAttack`             | Entry point — selects FedAttack / NonFedAttack / CloakAttackWrapper       |
| `FedAttack`               | Federation attack — torpedo runs, phaser sweeps, shield management        |
| `NonFedAttack`            | Non-Federation attack — more aggressive maneuvering                        |
| `CloakAttack`             | Cloak → approach → decloak → alpha strike → recloak                       |
| `CloakAttackWrapper`      | Wraps `CloakAttack` with non-cloak fallback                               |
| `Defend`                  | Protect a target — follow + engage attackers                              |
| `DockWithStarbase`        | Full docking sequence (approach, dock, repair/rearm, undock)              |
| `UndockFromStarbase`      | Undocking sub-behaviour                                                   |
| `StarbaseAttack`          | Stationary-target attacks with varied angles                              |
| `ChainFollow`             | Formation-following                                                       |
| `ChainFollowThroughWarp`  | Formation through warp transitions                                         |
| `FollowThroughWarp`       | Through-warp follow (simpler than ChainFollow)                            |
| `TractorDockTargets`      | Tractor-beam docking                                                      |
| `CallDamageAI`            | Switch to damage-appropriate AI when hit                                  |

5 Compound Parts (sub-behaviours reused across compounds):
`EvadeTorps`, `ICOMove`, `SweepPhasers`, `WarpBeforeDeath`,
`NoSensorsEvasive`.

### Difficulty system

AI difficulty is a `0.0–1.0` float. The `g_lFlagThresholds` table
maps difficulty ranges to enabled-behaviour flags:

| Difficulty | Enabled flags                                                                                                     |
|------------|--------------------------------------------------------------------------------------------------------------------|
| 1.0        | All 18 (torpedo selection, phaser optimisation, subsystem targeting, etc.)                                         |
| 0.5        | 8: `UseRearTorps`, `UseSideArcs`, `SmartShields`, `ChooseSubsystemTargets`, `AvoidTorps`, `NeverSitStill`, `PowerManagement`, `SmartTorpSelection` |
| 0.0        | 2: `InaccurateTorps`, `DumbFireTorps`                                                                              |

Three presets (`Easy_`, default, `Hard_`) with per-game-difficulty
overrides.

---

## Fleet commands

5 shipped fleet-command scripts:

| Command         | Script                       | Behaviour                                |
|-----------------|------------------------------|------------------------------------------|
| `DefendTarget`  | `AI.Fleet.DefendTarget`      | `Compound.Defend` in `ConditionalAI`     |
| `DestroyTarget` | `AI.Fleet.DestroyTarget`     | `BasicAttack` in `ConditionalAI`         |
| `DisableTarget` | `AI.Fleet.DisableTarget`     | `BasicAttack` with `DisableOnly=1`       |
| `HelpMe`        | `AI.Fleet.HelpMe`            | Come to player's aid                     |
| `DockStarbase`  | `AI.Fleet.DockStarbase`      | Order wingman to dock for repair         |

Each wraps its core AI in a `ConditionalAI` checking
`ConditionAllInSameSet` (target + player + ship).

---

## Player AI

26 player-AI scripts (`reference/scripts/AI/Player/`). Used when the
human player issues high-level commands from the tactical UI; full
behaviour trees that auto-pilot the player's ship.

Categories:

- **Destroy** variants — `DestroyFreely`, `DestroyFore`,
  `DestroyAft`, `DestroyFromSide`, `DestroyFaceSide` plus
  `Close` / `Maintain` / `Separate` range variants.
- **Disable** variants — mirror of Destroy with `DisableOnly=1`.
- **Movement** — `FlyForward`, `InterceptTarget`, `OrbitPlanet`,
  `PlayerWarp`, `Stay`, `StaySelectTarget`.
- **Defense** — `Defense`, `DefenseNoTarget`.

---

## Condition system

36 shipped condition scripts (`reference/scripts/Conditions/`), used
by `ConditionalAI` nodes:

```python
App.ConditionScript_Create("Conditions.ConditionName", "Name", ...args)
```

Common conditions: `ConditionInRange`, `ConditionFacingToward`,
`ConditionAttacked`, `ConditionSystemBelow`, `ConditionTorpsReady`,
`ConditionIncomingTorps`, `ConditionShipDisabled`,
`ConditionAllInSameSet`, `ConditionInLineOfSight`, `ConditionInNebula`,
`ConditionTimer`, `ConditionFlagSet`.

---

## AI preloading

`AI.Setup.GameInit()` (called from C++ via `CreateMultiplayerGame` at
`0x00504F10`) pre-imports **73** AI modules to prevent hitching
during gameplay:

- 27 `PlainAI` scripts
- 15 Compound AI scripts + 5 Parts
- 5 Fleet commands
- 36 Condition scripts (`DockStarbase` is omitted, intentionally)

This is the AI subsystem's engagement with multiplayer setup — the
pre-import runs even though stock MP doesn't actually use AI, because
the same code path serves both modes.

---

## Fuzzy logic

`CircleObject` uses `App.FuzzyLogic()` for distance/facing decisions.
The fuzzy system has 4 input sets (far-facing-away, far-facing-toward,
near-facing-good, near-facing-bad) and 4 output sets
(stop-turn-toward, fast-turn-toward, stop-turn-side, fast-turn-side).
Membership percentages are computed from dot products and distance,
then blended into a speed/turn command.

Other AIs use simpler threshold-based logic.

---

## Multiplayer note

For a reimplementation considering MP AI, AI state would need to be
either replicated or made server-authoritative. The stock design
gives you neither — the C++ AI tick scheduler runs purely on the
ship's owning machine.
