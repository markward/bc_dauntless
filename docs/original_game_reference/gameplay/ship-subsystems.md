# Ship Subsystems

Reference for the C++ subsystems that hang off a `Ship`: the
`PowerSubsystem` reactor and `Powered` master that drive the EPS grid,
the `RepairSubsystem`, the `CloakingSubsystem`, the self-destruct
pipeline, and ship navigation/movement plumbing.

The combat-related subsystems (shields, weapons) live in
`combat-and-damage.md`.

---

## Power and reactor

### Three-class architecture

```
ShipSubsystem (vtable 0x892FC4)
 ├── PowerSubsystem (vtable 0x892C98)             ← reactor / "Warp Core"
 │     ctor: FUN_00560470          ship+0x2C4    type ID 0x8138
 │     does NOT inherit from PoweredSubsystem
 │     does NOT override Update (uses ShipSubsystem::Update)
 │
 └── PoweredSubsystem (vtable 0x892D98)           ← base for all power consumers
       ctor: FUN_00562240 → FUN_0056B970
       Update: FUN_00562470 (vtable slot 25)
       │
       ├── "Powered" master (vtable 0x88A1F0)     ← EPS distributor
       │     ship+0x2B0   type ID 0x813E
       │     Update override: FUN_00563780  (MAIN POWER SIM TICK)
       │
       ├── ShieldGenerator   (vtable 0x893598)
       ├── PhaserController  (vtable 0x893240)
       ├── SensorArray       (vtable 0x893040)
       ├── ImpulseEngineSubsystem
       ├── WarpEngineSubsystem
       ├── RepairSubsystem
       ├── CloakingSubsystem
       ├── TractorBeamSystem
       ├── TorpedoSystem
       └── PulseWeaponSystem
```

Two distinct objects live on the ship: the **reactor** (`ship+0x2C4`)
holds HP and is damageable, and the **EPS distributor** (`ship+0x2B0`)
holds batteries and the consumer list. Both are constructed from the
same `PowerProperty` template — the reactor inherits MaxCondition and
position; the distributor inherits battery / conduit / output values.

### Field layouts

`PowerProperty` (read-only template):

| Offset | Field                    |
|--------|--------------------------|
| `+0x48`| `MainBatteryLimit`       |
| `+0x4C`| `BackupBatteryLimit`     |
| `+0x50`| `MainConduitCapacity`    |
| `+0x54`| `BackupConduitCapacity`  |
| `+0x58`| `PowerOutput`            |

Stock Sovereign: 200,000 / 100,000 / 1,450 / 250 / 1,200.

`PowerSubsystem` (reactor) at `ship+0x2C4`, vtable `0x892C98`:

| Offset | Field                              |
|--------|------------------------------------|
| `+0x18`| `PowerProperty*`                   |
| `+0x30`| `condition` (current HP, float)    |
| `+0x34`| `conditionPct = condition / max`   |

The reactor has no batteries of its own. `GetPowerOutput()` returns
`property+0x58 * conditionPct`.

`Powered` master (EPS distributor) at `ship+0x2B0`, vtable `0x88A1F0`:

| Offset | Field                                      |
|--------|--------------------------------------------|
| `+0x18`| `PowerProperty*`                           |
| `+0x30`| `condition`                                |
| `+0x34`| `conditionPct`                             |
| `+0x40`| `Ship*` owner                              |
| `+0xA0`| `availablePower` (total this interval)     |
| `+0xA4`| `mainConduitCurrent` (remaining this tick) |
| `+0xA8`| `backupConduitCurrent`                     |
| `+0xAC`| `mainBatteryPower`                         |
| `+0xB0`| `mainBatteryPct`                           |
| `+0xB4`| `backupBatteryPower`                       |
| `+0xB8`| `backupBatteryPct`                         |
| `+0xBC`| `powerDispensed` (this tick)               |
| `+0xC0`| `lastUpdateTime`                           |
| `+0xC4`| `consumerCount`                            |
| `+0xC8`/ `+0xCC` | consumer list head/tail (linked list of `PoweredSubsystem*`) |
| `+0xD0`| consumer-node free pool                    |

Consumer-list nodes are 12 bytes (`subsystem`, `prev`, `next`).

`PoweredSubsystem` (consumer base) — fields shared by every consumer:

| Offset | Field                                                                |
|--------|----------------------------------------------------------------------|
| `+0x18`| subsystem-specific `Property*`                                       |
| `+0x30`| `condition`                                                          |
| `+0x34`| `conditionPct`                                                       |
| `+0x40`| `Ship*`                                                              |
| `+0x88`| `powerReceived` (this tick)                                          |
| `+0x8C`| `powerWanted` (this tick)                                            |
| `+0x90`| `powerPercentageWanted` (player slider, 0.0–1.25)                    |
| `+0x94`| `efficiency = powerReceived / powerWanted`                           |
| `+0x98`| `conditionRatio = powerReceived / (normalPower * dt)`                |
| `+0x9C`| `isOn` (1 = enabled)                                                 |
| `+0xA0`| `powerMode` — 0 main-first, 1 backup-first, 2 backup-only            |
| `+0xA4`| `isNetworkable`                                                      |

### Tick

Once per **interval** (`INTERVAL = 1.0 s` at `0x892E20`),
`PoweredMaster::Update` (`FUN_00563780`) runs the main power
simulation:

1. Advance condition tracking via base `ShipSubsystem::Update`.
2. Compute elapsed game time. If past one interval:
   - `powerDispensed = 0` (reset per-tick counter).
   - If reactor not disabled: `recharge = GetPowerOutput() * ticks`,
     `AddPowerToBatteries(recharge)`.
   - `availablePower = ComputeAvailablePower(ticks)`.
   - Wrap `lastUpdateTime` to prevent drift.
3. Update battery-percentage caches at `+0xB0`/`+0xB8`.
4. Update FPU watcher containers.

`AddPowerToBatteries` fills the main battery first (capped at
`MainBatteryLimit`), spills overflow to backup (capped at
`BackupBatteryLimit`), discards the rest. Host-only in MP (gated on
`g_IsHost` at `0x0097FA89`).

`ComputeAvailablePower(ticks)`:

```
mainMax    = property+0x50 * conditionPct * ticks   ; main capacity scaled by health
backupMax  = property+0x54           * ticks         ; backup NOT health-scaled
mainAvail  = min(mainBatteryPower,   mainMax)
backupAvail= min(backupBatteryPower, backupMax)
mainConduitCurrent   = mainAvail
backupConduitCurrent = backupAvail
return mainAvail + backupAvail
```

Asymmetry: **main conduit is health-scaled, backup conduit isn't**.
A damaged reactor reduces main delivery but not backup.

`PoweredSubsystem::Update` (`FUN_00562470`) runs **per frame** for each
consumer:

```
powerWanted = NormalPowerWanted * powerPercentageWanted * dt
powerReceived = master.Draw…(powerWanted)            ; per powerMode
efficiency    = powerReceived / powerWanted
conditionRatio = powerReceived / (NormalPowerWanted * dt)   ; or 1.0 if dt=0
```

The three draw functions share a pattern — try one conduit first,
fall back to the other if not satisfied:

| Mode | Address       | Behaviour                                              |
|------|---------------|--------------------------------------------------------|
| 0    | `FUN_00563A70`| Main first, then backup                                |
| 1    | `FUN_00563BB0`| Backup first, then main                                |
| 2    | `FUN_00563CB0`| Backup only — no fallback                              |

Per-mode subsystem assignments (verified by exhaustive search for
`mov DWORD PTR [reg+0xA0], N`):

| Subsystem                | Mode | Notes                                |
|--------------------------|------|--------------------------------------|
| (default base ctor)      | 0    | `FUN_00562240`                       |
| ImpulseEngineSubsystem   | 0    | inherited                            |
| SensorSubsystem          | 0    | inherited                            |
| PhaserSystem             | 0    | inherited                            |
| TorpedoSystem            | 0    | inherited                            |
| PulseWeaponSystem        | 0    | inherited                            |
| ShieldGenerator          | 0    | inherited                            |
| WarpEngineSubsystem      | 0    | inherited                            |
| RepairSubsystem          | 0    | inherited                            |
| **TractorBeamSystem**    | **1**| `FUN_00582080` — backup-first        |
| **CloakingSubsystem**    | **2**| `FUN_0055E2B0` — backup-only         |

Cloaking is the only subsystem that's locked off the main grid: when
the backup battery is depleted, the cloak's `efficiency` drops below
the auto-decloak threshold and the device disengages.

A separate code path in `ShieldClass::Update` calls
`DrawFromBackupBattery` directly (bypassing `powerMode`) when the
shield generator itself is dead but individual facings still need
recharge — damaged shields preferentially drain backup batteries
during recovery.

### Initialization

A ship spawns with batteries full and every subsystem at 100 % power.
The four-stage sequence:

1. `PoweredSubsystem` constructor (`FUN_00562240`) sets
   `+0x90 = 1.0`, `+0x9C = 1`, `+0xA0 = 0`, plus per-tick zeroes.
2. `SetupFromProperty` (`FUN_00562390`) computes
   `powerWanted = normalPower * 1.0`. For the master,
   `FUN_005636D0` sets `mainBatteryPower = MainBatteryLimit` and
   `backupBatteryPower = BackupBatteryLimit`.
3. `Ship::SetupProperties` (`FUN_005B0110`) iterates every consumer
   and calls `SetPowerPercentageWanted(1.0)` — redundant safety net.
4. Reactor enable guard (`FUN_0055F7F0`) forces `+0x90 = 1.0` if it
   somehow ended up `<= 0.0`.

### Player adjustment (F5 panel)

Two input paths converge on `SetPowerPercentageWanted`
(`FUN_00562430`). The slider C++ widget (`EngPowerCtrl`,
`HandlePowerChange` at `FUN_0054DDE0`) and the keyboard hotkeys
(Python `EngineerMenuHandlers.ManagePower`) both eventually call:

```c
void SetPowerPercentageWanted(PoweredSubsystem* this, float pct) {
    float old = this->powerPercentageWanted;            // +0x90
    this->powerPercentageWanted = pct;
    if (old != 0.0f)
        this->powerWanted = (this->powerWanted * pct) / old;
}
```

This is **purely local**. The SWIG path posts an
`ET_SUBSYSTEM_POWER_CHANGED` (`0x0080008C`) event, but **that event
is not registered with any network forwarder** — the
`MultiplayerGame` constructor doesn't touch it. Power slider changes
have **no dedicated network message**.

The valid range is 0 % – 125 %. Enforcement happens at three layers:

| Layer            | Mechanism                                                            |
|------------------|----------------------------------------------------------------------|
| Python keyboard  | Explicit `if < 0.0 or > 1.25` clamp                                  |
| C++ slider       | `HandlePowerChange` validates against constant `1.25f` at `0x0088BEC0` |
| Network wire     | Power encoded as `(int)(pct * 100.0)` — naturally fits in a byte     |
| Server           | **No enforcement** — host applies what client sends                  |

The 125 % "overload" zone is visible in the F5 panel as the
orange/red region above 100 %.

### Network propagation (StateUpdate flag 0x20 only)

Power percentages travel **inside the StateUpdate flag-0x20 block**
through the `PoweredSubsystem::WriteState` / `ReadState` virtuals.
Two distinct interfaces:

#### Interface A — round-robin (vtable `+0x70`/`+0x74`)

Used in the StateUpdate flag 0x20 block (subsystem health
round-robin):

```
WriteState (FUN_00562960):
    ShipSubsystem.WriteState                    ; condition byte + children
    if !isOwnShip:
        WriteBit(stream, 1)                     ; hasData = 1
        WriteByte((int)(pctWanted * 100.0))     ; 0..125
    else:
        WriteBit(stream, 0)                     ; owner has local state
    EndMarker

ReadState  (FUN_005629D0):
    saved = lastNetworkUpdate                   ; +0x84  saved BEFORE base ReadState
    ShipSubsystem.ReadState                     ; condition byte + children
    if ReadBit:
        b = ReadByte
        if saved < timestamp:                   ; only apply if newer
            SetPowerPercentageWanted(b * 0.01f)
    EndMarker
```

The "save timestamp before base call" is essential — base ReadState
mutates `lastNetworkUpdate` from the incoming timestamp, so the
*previous* timestamp is what determines whether the incoming data is
fresh.

#### Interface B — sign-bit (vtable `+0x68`/`+0x6C`)

Used during `ObjCreate` (opcode `0x02`/`0x03`) and in weapon
round-robin (flag `0x80`). Always includes power data; packs on/off
state into the sign bit:

```
WriteState_SignBit:
    ShipSubsystem.WriteState
    b = (int)(pctWanted * 100.0)
    if !isOn: b = -b
    WriteByte(b)

ReadState_SignBit:
    ShipSubsystem.ReadState
    b = ReadByte
    if b < 1:
        b = -b
        isOn = 0
    else:
        isOn = 1
    pctWanted = b * 0.01f
```

#### isOwnShip

Decided in `Ship::WriteStateUpdate` (`FUN_005B17F0`) by comparing
`ship+0x04` (object ID) against `peer+0x0C` (the peer's
`shipObjectID`). When the host writes ship X's state for the player
who owns ship X, `isOwnShip = 1` and power data is omitted — keeps
the host from overwriting the owner's local slider with stale data.

#### Round-robin

A 10-byte budget per flag-0x20 block, per peer per tick. Cursor
persists across ticks at `(per-peer) +0x30`/`+0x34`. With ~11
top-level subsystems on a Sovereign, full power-state convergence
takes 3–5 ticks ≈ 0.3–0.5 s at the ~10 Hz StateUpdate rate.

#### TurnOn/TurnOff

`SetPowerToSubsystem(0)` in Python calls `TurnOff`; `SetPowerToSubsystem(>0)`
on a disabled subsystem calls `TurnOn`. Both fire opcode `0x0A`
(`SubsystemStatus`) — that one *is* network-forwarded immediately,
unlike the percentage slider.

### Power flow summary

```
Per-second tick (FUN_00563780 — Powered master):
  GENERATE  : powerOutput * conditionPct → main battery, overflow → backup
  COMPUTE   : mainConduit   = min(mainBattery,   mainCapacity * condPct)
              backupConduit = min(backupBattery, backupCapacity)
              availablePower = mainConduit + backupConduit

Per-frame (FUN_00562470 — each consumer):
  DEMAND    : normalPowerPerSecond * pctWanted * dt
  DRAW      : per powerMode (main-first / backup-first / backup-only)
  RATIO     : efficiency = received / wanted   (0.0–1.0)
  EFFECT    : subsystem behaviour scales by efficiency
```

### Low-power behaviour

- **Graceful degradation.** Subsystems take partial power; their
  internal logic scales by `efficiency`.
- **No hard cutoff.** A subsystem doesn't switch off at 0 % — it
  simply stops being functional (shields don't recharge, weapons
  don't charge, engines produce no thrust).
- **Battery depletion.** Both conduits → 0 → all consumers receive 0.
- **Priority is by draw order.** Whichever consumer's `Update` runs
  first gets first crack at the conduit pool. This is the linked-list
  insertion order on the master's consumer list.
- **Health-scaling asymmetry** (repeated for emphasis): reactor
  `PowerOutput` and the *main* conduit cap are scaled by reactor
  health; the *backup* conduit cap is not.

### Constants

| Address     | Value     | Meaning                                                  |
|-------------|-----------|----------------------------------------------------------|
| `0x892E20`  | `1.0f`    | `INTERVAL` — power simulation runs once per second       |
| `0x0088BEC0`| `1.25f`   | Max `powerPercentageWanted` (125 % overload cap)         |
| `0x0088CE78`| `100.0f`  | WriteState encoding multiplier                           |
| `0x0088D4E4`| `0.01f`   | ReadState decoding multiplier                            |
| `0x0088B9AC`| `255.0f`  | Condition byte: `(condition / max) * 255.0`              |

### Reference values (Sovereign battery cycle)

Stock ships are designed to run at a power deficit under full combat
load, slowly draining their main battery:

| Ship          | Output | Total draw  | Deficit | Main-battery drain time |
|---------------|-------:|------------:|--------:|------------------------:|
| Sovereign     |  1,200 |       2,051 |    -851 |              ~3 m 55 s  |
| Galaxy        |  1,000 |       1,651 |    -651 |              ~6 m 24 s  |
| Warbird       |  1,500 |       2,151 |    -651 |              ~2 m 34 s  |
| Warbird (cloaked) | 1,500 |    3,151 |  -1,651 |              ~1 m 1 s   |
| Vor'cha       |    800 |       1,301 |    -501 |              ~3 m 20 s  |
| Marauder      |    700 |       2,651 |  -1,951 |              ~1 m 12 s  |
| Bird of Prey  |    400 |         411 |     -11 |                  ~2 h   |

Drain time = `MainBatteryLimit / deficit`. Real drain is slower
because not every consumer is always active.

### Auto-balance (Python)

`PowerDisplay.AdjustPower` (in `PowerDisplay.py`) runs **client-side
only** to throttle subsystems when demand exceeds supply. The
algorithm normalises each subsystem's share of total normal power,
detects deficit (`> 1 % of total`), and scales every subsystem's
percentage proportionally — but never below 20 % or below the user's
desired setting. It also keeps weapon types (phasers/torpedoes/disruptors)
locked together, and engine types (impulse/warp) locked together.

---

## Repair

`RepairSubsystem` lives at `ship+0x2D8`. Class chain:
`ShipSubsystem` → `PoweredSubsystem` → `RepairSubsystem` (vtable
`0x00892E24`, size `0xC0`).

### Layout

Inherited from base classes (selected):

| Offset  | Field                                                            |
|---------|------------------------------------------------------------------|
| `+0x04` | TGObject network ID (auto-assigned from global counter)           |
| `+0x18` | `RepairSubsystemProperty*`                                        |
| `+0x30` | `condition` (HP)                                                  |
| `+0x34` | `conditionPercentage`                                             |
| `+0x40` | parent `Ship*`                                                    |
| `+0x9C` | `isOn`                                                            |

RepairSubsystem-specific:

| Offset | Field                                          |
|--------|------------------------------------------------|
| `+0xA8`| queue count                                    |
| `+0xAC`| queue head (`ListNode*`)                       |
| `+0xB0`| queue tail (`ListNode*`)                       |
| `+0xB4`| free list (recycled nodes)                     |
| `+0xB8`| block list (for bulk deallocation)             |
| `+0xBC`| pool growth size (default 2)                   |

`RepairSubsystemProperty` (read-only):

| Offset | Field             | Sovereign |
|--------|-------------------|----------:|
| `+0x20`| `MaxCondition`    |     8,000 |
| `+0x3C`| `RepairComplexity`|       1.0 |
| `+0x4C`| `MaxRepairPoints` |      50.0 |
| `+0x50`| `NumRepairTeams`  |         3 |

### Queue

A doubly-linked list of 12-byte nodes (`{ data, next, prev }`),
allocated from a per-subsystem pool. **No maximum size**, no hard cap;
the pool grows as needed. Duplicates are rejected — `AddSubsystem`
walks the list before insertion. 0-HP subsystems are also rejected
(explicit `condition > 0.0f` check); they fall through to a UI
"destroyed" notification path.

### Repair tick

`RepairSubsystem::Update` (`FUN_005652A0`) runs every frame on host /
standalone. The complete formula:

```
rawRepair = MaxRepairPoints * (condition / maxCondition) * dt
divisor   = min(queueCount, NumRepairTeams)
perItem   = rawRepair / divisor
hpGain_i  = perItem / subsystem_i.RepairComplexity        ; per item
```

Properties of the algorithm:

1. The repair system's **own health scales output** — a damaged
   repair bay = slower repairs.
2. **Multiple subsystems repaired simultaneously** — up to
   `NumRepairTeams` of them.
3. The repair amount is **divided equally** among `min(queueCount,
   numTeams)` items.
4. `RepairComplexity` is a **final divisor** — higher = slower
   repair.
5. **Destroyed subsystems** (condition `<= 0`) are *skipped*, not
   removed; they get an `ET_REPAIR_CANNOT_BE_COMPLETED` event but
   don't consume a repair team.

Worked example — Sovereign, healthy repair bay, 2 items in queue,
30 fps:

```
rawRepair = 50.0 * 1.0 * 0.033 = 1.65 / tick
divisor   = min(2, 3) = 2
perItem   = 0.825
phaser  (complexity = 3.0)  → +0.275 HP / tick
tractor (complexity = 7.0)  → +0.118 HP / tick
```

Ship death is *not* repaired through this system — see "Self-destruct"
below for the death cascade.

### Priority toggle

`HandleIncreasePriority` (`FUN_00565B50`) is **not** "move up by one".
It's a **binary toggle**:

- If the subsystem is currently being **actively repaired** (within
  the first `NumRepairTeams` nodes): **demote to tail**.
- If the subsystem is **waiting** (further down the queue): **promote
  to head**.

Determined by `IsBeingRepaired` (`FUN_00565890`), which walks the
first `NumRepairTeams` nodes and tests for a match. The reorder
removes the node and re-inserts at head/tail accordingly.

### Network paths

The repair system has **three** distinct network paths:

#### Path 1 — opcode `0x06` (PythonEvent), host → all (NoMe group, reliable)

Host-driven notifications generated automatically during the repair
tick. Factory `0x0101` (`TGSubsystemEvent`), 17 bytes total:

```
[u8 ] 0x06                         ; PythonEvent opcode
[i32] 0x00000101                   ; TGSubsystemEvent factory
[i32] event_type                   ; 0x008000DF / 0x00800074 / 0x00800075
[i32] source_obj_id                ; damaged subsystem's TGObject ID
[i32] dest_obj_id                  ; RepairSubsystem's TGObject ID
```

Three event types share this format:

| Event                              | Trigger                                |
|------------------------------------|----------------------------------------|
| `ET_ADD_TO_REPAIR_LIST` (`0x008000DF`)| Subsystem damaged → added to queue   |
| `ET_REPAIR_COMPLETED`   (`0x00800074`)| Subsystem reached max HP             |
| `ET_REPAIR_CANNOT_BE_COMPLETED` (`0x00800075`)| Subsystem destroyed while queued |

Both `source_obj_id` and `dest_obj_id` are **subsystem-level
network IDs** auto-assigned from the global counter `DAT_0095B078`
at construction time. They are **not ship IDs**, and there is no
fixed-offset formula to compute them from the ship base — they're
sequential globals. The receiving end resolves them through the
hash table at `0x0099A67C` via `FUN_006F0EE0` (lookup-by-ID).

#### Path 2 — opcode `0x0B` (`AddToRepairList`), client → host → all

Routes through `GenericEventForward` (`FUN_0069FDA0`). Sent when a
player manually requests repair from the Engineering panel. Standard
`TGCharEvent` serialisation (factory `0x0105`), 18 bytes.

#### Path 3 — opcode `0x11` (`RepairListPriority`), client → host → all

Also through `GenericEventForward`. Triggered by a player click in
the repair queue UI. `TGObjPtrEvent` serialisation (factory
`0x010C`), 21 bytes — adds an extra `int32 obj_ptr` to the base
event format. The payload is the target subsystem's TGObject network
ID; on the receiving side, `HandleIncreasePriority` runs the toggle
algorithm.

### Collision → repair chain

```
ProximityManager detects collision
  → ET_COLLISION_EFFECT (0x00800050)
  → ShipClass::CollisionEffectHandler (0x005AF9C0)
       sends opcode 0x15 to "NoMe", then applies damage
  → per-subsystem damage path:
      ShipSubsystem::SetCondition (FUN_0056C470)
        if newCondition < max && ship alive:
          POST ET_SUBSYSTEM_HIT (0x0080006B) as TGObjPtrEvent (factory 0x10C)
              source = NULL, dest = ship, obj_ptr = subsystem.objectID
  → RepairSubsystem::HandleHitEvent
      lookup subsystem by obj_ptr
      AddToRepairList_MP (FUN_00565900)
        if added && host && multiplayer:
          POST ET_ADD_TO_REPAIR_LIST (0x008000DF) as TGEvent (factory 0x101)
              source = damagedSub, dest = repairSubsystem
  → HostEventHandler (0x006A1150)
      serialize as opcode 0x06 → reliable → "NoMe"
```

A typical mid-combat collision generates ~14 PythonEvent messages
(two ships × ~7 hit subsystems each, after duplicate rejection).

### Engineering panel UI

The `EngRepairPane` (global at `0x0098B188`) presents three areas:

| Area         | Content                                                         |
|--------------|-----------------------------------------------------------------|
| `REPAIR_AREA`| First `NumRepairTeams` items from queue head (active repairs)   |
| `WAITING_AREA`| Remaining items                                                 |
| `DESTROYED_AREA`| 0-HP subsystems that can't be queued                          |

Player clicks:

- **REPAIR_AREA click** → `ET_REPAIR_INCREASE_PRIORITY` → demotes
  to tail.
- **WAITING_AREA click** → same event → promotes to head.
- **DESTROYED_AREA click** → no action.

### Sovereign reference values

| Subsystem      | MaxCondition | RepairComplexity |
|----------------|-------------:|-----------------:|
| Repair         |        8,000 |              1.0 |
| Sensor Array   |        8,000 |              1.0 |
| Warp Core      |        7,000 |              2.0 |
| Impulse System |        3,000 |              3.0 |
| Bridge         |       10,000 |              4.0 |
| Tractor System |        3,000 |              7.0 |
| Hull           |       12,000 |              3.0 |

(More entries in `combat-and-damage.md` under "Sovereign-class
reference values".)

---

## Cloaking

`CloakingSubsystem` at `ship+0x2DC`. Inherits `PoweredSubsystem`
(vtable `0x00892EAC`); constructor `FUN_00566D10`.

### Object layout

| Offset  | Field                                                       |
|---------|-------------------------------------------------------------|
| inherited | (PoweredSubsystem fields up through `+0xA4`)              |
| `+0xA8` | `cloakEffectNode` (`NiNode*`)                               |
| `+0xAC` | `isFullyCloaked` byte (1 only when state = `CLOAKED`)      |
| `+0xAD` | `tryingToCloak` byte (1 = user wants cloak ON)             |
| `+0xB0` | `state` (int — see below)                                   |
| `+0xB4` | `timer` (float)                                             |
| `+0xC0` | render-mode int (init 2)                                    |

### State machine — 4 active states (and 2 ghost states)

| Value | Name        | Timer behaviour    | Entered from         | Exits to              |
|-------|-------------|--------------------|----------------------|-----------------------|
| 0     | DECLOAKED   | irrelevant         | `FUN_0055F7F0`       | state 2               |
| 2     | CLOAKING    | counts up by `dt`  | `FUN_0055F110(1)`    | state 3 when full     |
| 3     | CLOAKED     | irrelevant         | `FUN_0055F6D0`       | state 5               |
| 5     | DECLOAKING  | counts down by `dt`| `FUN_0055F110(0)`    | state 0 when empty    |

States 1 and 4 are **ghost states** — checked in `IsCloaking()` /
`IsDecloaking()` SWIG wrappers and the visibility function, but
**never actually written**. Vestiges of a planned 6-state design
collapsed to 4.

### Transition flow

```
DECLOAKED(0) ─StartCloak→ CLOAKING(2) ─timer full→ CLOAKED(3) ─StopCloak→ DECLOAKING(5) ─timer 0→ DECLOAKED(0)
                                                       │
                                                       └─energy failure─→ DECLOAKING(5)
```

### Tick (`FUN_0055E500`)

```c
void CloakingSubsystem::Update(this, dt) {
    PoweredSubsystem::Update(this, dt);
    if (state == 2) {                       // CLOAKING — count up
        timer += dt;
        progress = timer / CloakTime;
        if (progress >= 1.0) { progress = 1.0; CloakComplete(); }
    } else if (state == 5) {                // DECLOAKING — count down
        timer -= dt;
        progress = timer / CloakTime;
        if (progress <= 0.0) { progress = 0.0; DecloakComplete(); }
    }
    UpdateVisibility(progress);             // FUN_0055E640
    if (!isOn) { PoweredSubsystem::Update(this, dt); return; }
    // Honour user intent
    if (tryingToCloak == 1 && state in {0,4,5})  BeginCloaking();
    else if (state == 3 && efficiency < ENERGY_THRESHOLD)
                                             StopCloaking();         // auto-decloak
    if (tryingToCloak == 0 || state in {1,2,3}) BeginDecloaking();
}
```

`CloakTime` (`DAT_008E4E1C`) and `ShieldDelay` (`DAT_008E4E20`) are
**class-level globals**, not per-instance fields. Every cloaking
device in the session shares the same values; modifying them via
`CloakingSubsystem.SetCloakTime` / `SetShieldDelay` affects every
ship.

### Begin transition (`FUN_0055F110`)

When `param == 1` (cloaking):

1. Energy check via `FUN_0056C350` (recursive power validation).
   If insufficient, return without transition.
2. Create `NiTimeController` animation sequences.
3. If ship has shield subsystem (`ship+0x2C0`), schedule a delayed
   shield-hide event `0x0080007B` at `gameTime + ShieldDelay`.
4. Start "Cloak" sound.
5. `state = 2`, `timer = 0`.
6. Play "Cloak" animation on the NiNode.

When `param == 0` (decloaking):

1. Post `ET_DECLOAK_BEGINNING` (`0x00800079`).
2. If `state != 2`, set `timer = CloakTime` (count down from full).
3. `state = 5`.
4. Play "Uncloak" animation.

### Completion functions

`CloakComplete` (`FUN_0055F6D0`):

```
state = 3
post ET_CLOAK_BEGINNING (0x00800078)
isFullyCloaked = 1
make ship invisible: ship.sceneNode.vtable[0x50](1)
```

`DecloakComplete` (`FUN_0055F7F0`):

```
state = 0
post ET_DECLOAK_COMPLETED (0x0080007A)
if shield subsystem:
    schedule delayed event 0x0080007B at gameTime + ShieldDelay
        re-enables shield visual (flag |= 0x01)
        if shield HP <= 0: reset HP to 1.0
RestoreNiNode
```

### Shield interaction (summary)

Shields **don't drop to 0 HP** when a ship cloaks. Instead:

- The shield subsystem is functionally disabled (`shieldClass+0x9C
  = 0`) so absorption stops, recharge stops, the visual fades.
- HP is preserved.
- After decloak, there's an additional `ShieldDelay` before shields
  reactivate.
- If shield HP went to 0 during cloak, it resets to 1.0 on decloak.
- All the state lives in cloak code; shield code itself doesn't read
  cloak state.

(Full detail in `combat-and-damage.md` under "Cloak / shield
interaction".)

### Weapon interaction

Weapon firing is **not directly gated** by cloak state in C++ weapon
code. The connection happens through:

1. **Subsystem disable** — `FUN_00562630` is called with event
   `0x0080006C` (`ET_SUBSYSTEM_STATUS`), setting `+0x9C = 0` on
   weapon systems.
2. **AI/Python checks** — scripts call `ShipClass.IsCloaked()` before
   ordering fire. `IsCloaked` (`FUN_005AC450`) returns
   `cloak.isFullyCloaked` (`+0xAC`), which is **only true when state
   == 3**, not during transitions.

### Network handling

Two MP opcodes:

| Opcode | Event                          | Handler                                |
|--------|--------------------------------|----------------------------------------|
| `0x0E` | `ET_START_CLOAKING` (`0x008000E3`) | `CloakingSubsystem::StartCloakingHandler` |
| `0x0F` | `ET_STOP_CLOAKING`  (`0x008000E5`) | `CloakingSubsystem::StopCloakingHandler`  |

These route through the generic event-forwarder `FUN_0069FDA0`. The
MultiplayerGame constructor registers `0x008000E2` and `0x008000E4`
(the request versions sent by the player); those handlers convert
local cloak events into network opcodes `0x0E`/`0x0F`.

### StateUpdate (flag 0x40)

Cloak state propagates in StateUpdate flag `0x40`:

```
WRITE (server, FUN_005B17F0):
    cloak = ship.cloakSubsystem
    if cloak && cloak.isOn != prevCloakState:
        dirtyFlags |= 0x40
        prevCloakState = cloak.isOn

    if (flags & 0x40) && cloak:
        WriteBit(stream, cloak.isOn)        ; +0x9C, single bit

READ  (client, FUN_005B2660):
    if (flags & 0x40):
        cloakOn = ReadBit(stream)
        if cloakOn: StartCloaking(cloak)    ; FUN_0055F360
        else:       StopCloaking(cloak)     ; FUN_0055F380
```

The wire serialises `isOn` (`+0x9C`), **not the state machine value**
(`+0xB0`). The receiver runs its own local state machine including
visual transitions and the timer.

### Visual effect

`UpdateVisibility(progress)` (`FUN_0055E640`) and the recursive
`UpdateNodeAlpha` (`FUN_0055EE10`) walk the ship's NiNode tree and
adjust alpha on `NiMaterialProperty` nodes, with a `rand()`-based
shimmer/ripple effect tuned by:

| Address    | Constant                                              |
|------------|--------------------------------------------------------|
| `0x0088C5AC`| Shimmer threshold                                     |
| `0x00892C94`| Random scale factor                                   |
| `0x00892C90`| Decloak scale factor                                  |
| `0x0088CB58`| Alpha offset                                          |
| `0x0088BA90`| Alpha scale (cloak effect node)                       |

### Energy-failure auto-decloak

While `CLOAKED`, if `efficiency` drops below `DAT_0088D4EC`, the
cloak auto-decloaks. Combined with the backup-only power mode and a
finite backup battery, this gives the cloak a natural duration limit:
the device runs solely on backup, and when backup empties,
`efficiency = 0`, which trips the threshold.

### Collision while cloaked

`ET_CLOAKED_COLLISION` (`0x00910A60`) exists in the string table but
has **0 xrefs** — dead/unused. Collisions while cloaked go through
the normal pipeline with no special-case logic.

### Notable cloak addresses

| Address     | Function                              |
|-------------|---------------------------------------|
| `0x00566D10`| `CloakingSubsystem` ctor              |
| `0x0055E500`| Update / state-machine tick           |
| `0x0055F360`| `StartCloaking` (user-facing)         |
| `0x0055F380`| `StopCloaking`  (user-facing)         |
| `0x0055F110`| Begin (cloak/decloak transitions)     |
| `0x0055F6D0`| `CloakComplete`                       |
| `0x0055F7F0`| `DecloakComplete`                     |
| `0x0055F3E0`/`0x0055F560`| Instant cloak / decloak    |
| `0x0055E640`| `UpdateVisibility`                    |
| `0x0055EE10`| `UpdateNodeAlpha`                     |
| `0x0055F930`| `DeathWhileCloaked`                   |
| `0x005AC450`| `ShipClass::IsCloaked`                |
| `0x0056C350`| Recursive energy check                |

---

## Self-destruct

A shipped, working feature: Ctrl+D destroys the player's own ship.
**No confirmation, no countdown, no abort.**

### Trigger and entry

| Item                                | Address / value                              |
|-------------------------------------|----------------------------------------------|
| Keyboard binding                    | `WC_CTRL_D` → `ET_INPUT_SELF_DESTRUCT` (`0x8001DD`) |
| `TopWindow::SelfDestructHandler`    | `0x0050D070`                                 |
| MP opcode                           | `0x13` (`HostMsg`)                           |
| Server-side handler (opcode `0x13`) | `FUN_006A01B0`                               |
| Core damage                         | `FUN_005AF5F0` (`DoDamageToSelf`)            |
| Inner damage application            | `FUN_005AF4A0`                               |
| Death cascade                       | `FUN_005AFEA0` (`ShipDeathHandler`)          |

### Three execution paths

```
TopWindow::SelfDestructHandler
 ├── (host && multiplayer)  → DoDamageToSelf(playerShip, ship+0x2C4) locally
 ├── (!host && multiplayer) → send opcode 0x13 to host  (1-byte message)
 └── (singleplayer)         → DoDamageToSelf locally    (gated on !TestMenuState 2/3)
```

The MP wire format is the **smallest possible game message**: a
single byte. The sender's identity comes from the `TGMessage`
envelope (`+0x0C` = sender connection ID); the host maps it back to
a ship via `GetShipFromPlayerID` (`0x006A1AA0`).

### `DoDamageToSelf`

```c
float DoDamageToSelf(Ship* ship, PowerSubsystem* powerSS) {
    if (powerSS == NULL) return 0.0f;
    float maxHP = GetMaxHP(powerSS);                           // FUN_0056C310
    return DoDamageToSelf_Inner(ship, powerSS, maxHP, NULL, 1);
}
```

The trick: it passes the reactor's full `MaxCondition` as damage,
with `force_kill = 1`. Effectively one-shots the warp core.

### `DoDamageToSelf_Inner` (`FUN_005AF4A0`)

```c
float DoDamageToSelf_Inner(Ship* ship, Subsystem* sub,
                           float damage, int* attacker, char force_kill) {
    if (ship == playerShip && g_TopWindow.godMode) return 0.0f;     // gate 1
    if (ship+0x2EA == 0)                            return 0.0f;    // gate 2: damage disabled

    float curHP    = sub+0x30;
    float maxHP    = GetMaxHP(sub);
    float excess   = curHP - damage;
    float applied  = 0.0f;
    if (excess <= 0)            applied = -excess;
    else if (!force_kill)       goto skip;

    // Cascade: if power dies and ship has auto-destruct flag
    if (ship+0x2E9 == 1 && IsDead(sub)) {
        excess = GetMaxHP(sub) * DAT_00888A78;
        force_kill = 0;
    }
    // Subsystem minimum-HP threshold
    if (sub+0x44 == 1) {
        float minRatio = GetMinHPRatio(sub);
        if (excess / maxHP < minRatio)
            excess = (minRatio + DAT_00888A78) * maxHP;
    }
    SetCondition(sub, excess);
    if ((excess <= 0 || force_kill) && IsDead(sub))
        ShipDeathHandler(ship, attacker);
    return applied;
}
```

`SetCondition` (`FUN_0056C470`) fires `ET_SUBSYSTEM_HIT`
(`0x0080006B`) when HP drops below max — same event used for weapon
damage, so the notification path is identical.

### Death cascade (`ShipDeathHandler`, `FUN_005AFEA0`)

After lethal damage:

1. Gate checks (`ship+0x14C >= threshold`,
   `ship+0x150` already-dying flag false).
2. `ship+0x244 = 0`.
3. `FUN_005AE1B0(ship, 0)` — explosion visuals/sounds.
4. Cleanup: `FUN_005B0BB0` (ship state), `FUN_005AF460`
   (subsystem shutdown), `FUN_005AC250` (AI removal).
5. Create `ET_OBJECT_EXPLODING` (`0x0080004E`) `TGEvent` with
   `dest = ship`, `charData = ship.hullHP`, post to event manager.
6. Stamp attacker's object ID into the event if available.

The OBJECT_EXPLODING event triggers Python `ObjectKilledHandler`
(scoring), `HostEventHandler` → opcode `0x06` to "NoMe" (network
forwarding), and the visual destruction on every client.

### Scoring implications

Self-destruct sets the attacker pointer to NULL, so:

- `FiringPlayerID = 0` → no kill credit.
- A death **is** counted for the self-destructing player.
- In team modes (Mission5), the opposing team gets a team-kill —
  Mission5.py handles this explicitly.

### Host-trace counts (verified)

A typical self-destruct produces (`T+0.000` is the inbound `0x13`):

```
T+0.000  C → S    0x13 HostMsg  (1 byte, unreliable)
T+0.004  S → C    0x06 ObjectExplodingEvent (factory 0x8129, lifetime=9.5s)
T+0.004  S → C    0x36 SCORE_CHANGE (deaths+1, kills=0)
T+0.004  S → C   ~4×0x06 TGSubsystemEvent (ET_ADD_TO_REPAIR_LIST)
                  e.g. PowerReactor, ShieldGenerator, PhaserController, PulseWeapon
   --- 9.5 s of explosion animation, debris collisions ---
   --- client returns to spawn menu, picks ship, sends ObjCreateTeam (0x03) ---
```

What **isn't** sent:

- `0x29` (Explosion) — sent for combat kills, **not** for self-destruct.
- `0x14` (DestroyObject) — never sent for either kill type in stock.
- `0x03` (server-initiated ObjCreateTeam) — there is no server-side
  auto-respawn. Every respawn is client-initiated when the player
  picks a new ship.

### AI self-destruct (parallel implementation)

`AI/PlainAI/SelfDestruct.py` uses a **different** mechanism for
AI-controlled ships:

```python
class SelfDestruct(BaseAI.BaseAI):
    def Update(self):
        pShip = App.ShipClass_Cast(self.pCodeAI.GetObject())
        if pShip:
            pHull = pShip.GetHull()
            if pHull:
                pShip.DestroySystem(pHull)        # 100% damage to hull
                bDead = 1
        if not bDead:
            pObject.SetDeleteMe(1)                # fallback: delete
```

Goes through `DestroySystem(hull)` — direct hull damage, not
PowerSubsystem-based. Used in campaign missions (E3M2, E3M4,
E4M5, E4M6).

### Five known callers of `FUN_005AF5F0`

| Address    | Context                                                   |
|------------|-----------------------------------------------------------|
| `0x0050D132`| `TopWindow::SelfDestructHandler` (Ctrl+D, SP and MP-host) |
| `0x006A01D3`| `HostMsgHandler` opcode `0x13`                            |
| `0x005AFD56`| Cascading damage / shield-failure path                    |
| `0x006A0E18`| MultiplayerGame player-slot reset                         |
| `0x005B355B`| Ship subsystem-iteration loop                             |

The first two are user-initiated; the rest are internal reuse of the
"apply lethal damage via PowerSubsystem" primitive.

### Related events

| Event       | Name                          | Role in self-destruct                              |
|-------------|-------------------------------|----------------------------------------------------|
| `0x8001DD`  | `ET_INPUT_SELF_DESTRUCT`      | Input trigger (keyboard)                           |
| `0x0080006B`| `ET_SUBSYSTEM_HIT`            | Fired when PowerSubsystem HP changes               |
| `0x0080004E`| `ET_OBJECT_EXPLODING`         | Death — triggers scoring + visuals                 |

---

## Ship navigation

The C++ functions that AI scripts and player input call to control
ship movement.

### Targeting pipeline

```
Ship::SetTarget               (0x005AE1E0)
 ├── TGSceneGraph::FindObjectByID  (0x00434E70)   resolve name → object
 └── Ship::SetTargetInternal  (0x005AE210)
       ├── post ET_TARGET_WAS_CHANGED (0x800058) as TGObjPtrEvent (old target)
       ├── Ship::StopFiringWeapons (0x005B0BB0)   stop current fire
       └── Ship::OnTargetChanged   (0x005AE2C0)
             ├── Ship::UpdateWeaponTargets (0x005AE430)  walks +0x284
             └── post ET_TARGET_SUBSYSTEM_SET (0x80005A)
```

### Target fields on `Ship`

| Offset  | Type      | Field                                          |
|---------|-----------|------------------------------------------------|
| `+0x87` | byte      | Target-list cycle index                        |
| `+0x21C`| int32     | Current target object ID                        |
| `+0x220`| int32     | Target subsystem ID (precision targeting)       |
| `+0x228`| `TGPoint3`| Target offset (aim point relative to origin)    |

`Ship::GetNextTarget` (`0x005AE6D0`) cycles through a sorted target
list using the `+0x87` index; it's what the "next target" key calls.

### Turn computation

Three entry points:

| Function                         | Address    | Input                                |
|----------------------------------|------------|--------------------------------------|
| `Ship::TurnTowardLocation`        | `0x005AD3A0`| TGPoint3 world position             |
| `Ship::TurnTowardDirection`       | `0x005AD450`| TGPoint3 unit direction             |
| `Ship::TurnTowardDifference`      | `0x005AD4D0`| TGPoint3 direction delta (SWIG)     |

All three converge on `Ship::ComputeTurnAngularVelocity`
(`0x005AD910`) — quaternion slerp-style rotation that:

- Uses quaternion interpolation for smooth rotation.
- Constrains rotation to preserve the ship's up axis (no roll).
- Forward axis is the primary alignment target.
- Caps angular velocity by `ImpulseEngineSubsystem` properties.
- Outputs a 3-component angular velocity applied to the physics
  object.

`Ship::SetTargetAngularVelocityDirect` (`0x005AD290`) — SWIG entry
point that bypasses turn computation and sets angular velocity
directly. Used by AI scripts that compute their own rotation (e.g.
manual maneuver patterns).

Supporting math (selected):

| Function                                      | Address     |
|------------------------------------------------|-------------|
| `NiMatrix3::TransformVector`                   | `0x00813A40`|
| `NiMatrix3::TransposeTransformVector`          | `0x00813AA0`|
| `TGPoint3::Cross`                              | `0x0045C1A0`|
| `TGPoint3::UnitCross`                          | `0x00581E60`|
| `TGPoint3::MultMatrix`                         | `0x0045E8D0`|
| `GetForwardDirection` (returns `DAT_00980DF0`) | `0x00434CD0`|

### Impulse movement

```
Ship::SetImpulse (0x005AC470)   normalized speed (0.0–1.0) + direction + space flag
                                stores +0x1F8 (dir), +0x1FC (speed scalar)
Ship::SetSpeed   (0x005AC590)   absolute speed → /max → SetImpulse
```

`SetImpulse` clamps to `[0, 1]`. `SetSpeed` divides by `GetMaxSpeed()`
and delegates.

Effective speed, `ImpulseEngineSubsystem::GetEffectiveSpeed`
(`0x00561330`):

```
effective_max_speed = base_max_speed
                    × health_factor      (impulse-engine child aggregate)
                    × power_efficiency   (received / wanted, [0, 1])
```

`PoweredSubsystem::GetEfficiency` (`0x005822D0`) returns
`+0xFC / +0xF8` clamped to `[0, 1]`. Acceleration uses the same
pattern at `0x00561230`.

Velocity fields:

| Offset       | Field                                                |
|--------------|------------------------------------------------------|
| `ship+0x1F8` | impulse direction (`float[3]`, model or world space) |
| `ship+0x1FC` | impulse speed scalar (0.0–1.0)                       |

These are the *commanded* values. Actual velocity sits on the NiAVObject
at the standard offsets (`+0x98`/`+0x9C`/`+0xA0` via `ship+0x18`).

### In-system warp

| Function                  | Address     | Purpose                                  |
|---------------------------|-------------|------------------------------------------|
| `Ship::InSystemWarp`      | `0x005AC6E0`| SWIG entry; pathfinding + obstacle avoid |
| `Ship::StopInSystemWarp`  | `0x005ACDB0`| Clears warp state, fires `ET_EXITED_WARP`|

In-system warp moves a ship at very high speed to a distant target
within the same set. Used by the Intercept AI when distance exceeds
`fInSystemWarpDistance` (default 295 units). Includes obstacle
avoidance against planets and large ships.

Network opcode `0x10` (`StartWarp`) exists in the multiplayer dispatch
table but is **unused** in stock multiplayer — in-system warp is only
triggered by AI in single-player.

### Weapon target update

`Ship::UpdateWeaponTargets` walks the `+0x284` subsystem linked list
and updates each `WeaponSystem`'s target entry. The weapon target
list at `WeaponSystem+0xC4` maps object IDs to aim data:

| Function                                      | Address     |
|------------------------------------------------|-------------|
| `WeaponSystem::FindTargetEntry`                | `0x00585360`|
| `WeaponSystem::FindTargetByObjectID`           | `0x00584080`|
| `WeaponSystem::SetTargetOffset`                | `0x00585580`|
| `Subsystem::AsWeaponSystem` (IsA `0x801D`)     | `0x00583F60`|

### Network authority

Position and orientation are **client-authoritative** in stock BC
multiplayer. Each client controls its own ship's movement; the host
does not validate or simulate other players' physics:

```
client: AI / input → SetImpulse / TurnTowardLocation → physics
client: serialise position/orientation/velocity into StateUpdate (0x1C)
        flags 0x01 (position) + 0x02 (orientation)
host:   forward to all other clients (relay-all)
others: apply received transforms to remote ship objects
```

There is no server-side movement simulation or desync correction.

Relevant opcodes:

| Opcode | Name             | Notes                                              |
|--------|------------------|----------------------------------------------------|
| `0x1C` | `StateUpdate`    | Position (flag `0x01`) + orientation (flag `0x02`) |
| `0x10` | `StartWarp`      | In-system warp (defined but unused in stock MP)    |
| `0x07` | `StartFiring`    |                                                    |
| `0x08` | `StopFiring`     |                                                    |

### Subsystem helpers

| Function                                | Address     |
|-----------------------------------------|-------------|
| `Ship::StartGetSubsystemMatch`           | `0x005AC370`|
| `Ship::GetNextSubsystemMatch`            | `0x005AC390`|
| `Ship::AddSubsystem`                     | `0x005B3E50`|
| `Subsystem::IsActive` (reads `prop+0x25`)| `0x0056C340`|
| `Subsystem::GetRadius` (reads `prop+0x44`)|`0x0056B940`|
| `Subsystem::GetChild`                    | `0x0056C570`|
| `Subsystem::GetProperty`                 | `0x00560FC0`|
| `PoweredSubsystem::GetEfficiency`         | `0x005822D0`|

### Collision queries (used by AI obstacle avoidance)

| Function                       | Address     |
|--------------------------------|-------------|
| `CollisionQuery::Execute`      | `0x005A7CF0`|
| `CollisionQuery::GetNextResult`| `0x005A8320`|
| `CollisionQuery::Destroy`      | `0x005A8350`|
| `RaySphereIntersect`           | `0x004570D0`|

The `ProximityManager` (`pSet.GetProximityManager()`) provides
`GetLineIntersectObjects()` for line-of-sight checks.
