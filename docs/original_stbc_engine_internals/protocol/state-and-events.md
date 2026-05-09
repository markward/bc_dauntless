# State Replication and Event Transport

How the engine moves state and events across the wire: `StateUpdate`
(opcode `0x1C`), object creation (`ObjCreate` / `ObjCreateTeam`,
opcodes `0x02` / `0x03`), `PythonEvent` polymorphic event transport
(`0x06` / `0x0D`), and the `TGEvent` factory system that backs them.

For lower-level wire primitives and the full opcode catalogue see
`wire-format-and-opcodes.md`. For per-feature protocol layouts
(collision effect, set-phaser-level, delete-player-UI, CF16 explosion)
see `per-feature-protocols.md`.

---

## ObjCreate / ObjCreateTeam (`0x02` / `0x03`)

Carry serialised game objects (ships, torpedoes, asteroids,
stations) over the network. Both go to the same handler;
`0x03` adds a team-assignment byte. Bidirectional in stock content,
relayed by the host.

### Envelope

```
Offset  Size  Type    Field
------  ----  ----    -----
0       1     u8      opcode             0x02 or 0x03
1       1     i8      owner_player_slot  0–15
[if opcode == 0x03:]
2       1     i8      team_id            (typically 2 or 3)
+0      var   data    serialized_object  factory-created object stream
```

Header size: 2 bytes for `0x02`, 3 bytes for `0x03`.

The `serialized_object` blob is produced by
`obj->vtable[0x10C]` (`WriteStream`) on the sender; consumed by
`Ship_Deserialize` (`0x005A1F50`) on the receiver.

### Object stream header (8 bytes, common to all object types)

```
Offset  Size  Type    Field
------  ----  ----    -----
0       4     i32     factory_class_id    TG factory class ID
4       4     i32     object_id           Network object ID
```

The class ID is looked up in the TG object factory
(`DAT_0099A67C`) to instantiate the correct C++ class. If an object
with the given `object_id` already exists, deserialisation aborts
(duplicate protection).

| Class ID    | Hex bytes (LE)     | Object type                | Network tracker      |
|-------------|--------------------|----------------------------|----------------------|
| `0x00008008`| `08 80 00 00`      | Ship / Station             | Yes (pos/vel tracker)|
| `0x00008009`| `09 80 00 00`      | Torpedo / Projectile       | No (uses fire msgs)  |

After construction:

1. `obj->vtable[0x118](stream)` — `ReadStream`: deserialise fields.
2. `obj->vtable[0x11C](stream)` — `PostLoad`: finalise.

### Ship body (`class_id = 0x8008`)

```
Offset  Size  Type      Field               Notes
------  ----  ----      -----               -----
8       1     u8        species_type        SpeciesToShip enum (1=Akira, 5=Sovereign, …)
9       4     f32       position_x          world X
13      4     f32       position_y          world Y
17      4     f32       position_z          world Z
21      4     f32       orientation_w       quaternion W
25      4     f32       orientation_x       quaternion X
29      4     f32       orientation_y       quaternion Y
33      4     f32       orientation_z       quaternion Z
37      4     f32       speed               magnitude (typically 0.0 at spawn)
41      3     u8[3]     reserved            always observed as 0x00 0x00 0x00
44      1     u8        player_name_len     length of player name
45      var   ascii     player_name         not null-terminated
+0      1     u8        set_name_len        length of star-system name
+1      var   ascii     set_name            e.g. "Multi1"
+0      var   data      subsystem_state     ship-type-dependent health data
```

`set_name` is the **star-system name**, not the ship class — the
ship class comes from `species_type`. It maps into
`Multiplayer.SpeciesToSystem`:

| ID | Constant     | System name |
|----|--------------|-------------|
| 1  | `MULTI1`     | Multi1      |
| 2  | `MULTI2`     | Multi2      |
| 3  | `MULTI3`     | Multi3      |
| 4  | `MULTI4`     | Multi4      |
| 5  | `MULTI5`     | Multi5      |
| 6  | `MULTI6`     | Multi6      |
| 7  | `MULTI7`     | Multi7      |
| 8  | `ALBIREA`    | Albirea     |
| 9  | `POSEIDON`   | Poseidon    |

(`MAX_SYSTEMS = 10`; only 1–9 are valid.)

The 3 reserved bytes at offset 41 are always observed as zero. They
may encode initial flags (cloak / warp / shield state) but that's
not confirmed.

### Torpedo body (`class_id = 0x8009`)

Same `species_type` byte at the start, indexing into
`Multiplayer.SpeciesToTorp` instead. **No spatial-tracking data** —
torpedo position/movement come through dedicated fire messages
(`0x19` TorpedoFire, `0x1A` BeamFire).

### Species → Ship (full table)

`Multiplayer/SpeciesToShip.py`. `MAX_FLYABLE_SHIPS = 16` (IDs 1–15
playable); `MAX_SHIPS = 46` (IDs 0–45).

Playable (1–15):

| ID | Constant     | Faction      | Script        |
|----|--------------|--------------|---------------|
| 1  | AKIRA        | Federation   | Akira         |
| 2  | AMBASSADOR   | Federation   | Ambassador    |
| 3  | GALAXY       | Federation   | Galaxy        |
| 4  | NEBULA       | Federation   | Nebula        |
| 5  | SOVEREIGN    | Federation   | Sovereign     |
| 6  | BIRDOFPREY   | Klingon      | BirdOfPrey    |
| 7  | VORCHA       | Klingon      | Vorcha        |
| 8  | WARBIRD      | Romulan      | Warbird       |
| 9  | MARAUDER     | Ferengi      | Marauder      |
| 10 | GALOR        | Cardassian   | Galor         |
| 11 | KELDON       | Cardassian   | Keldon        |
| 12 | CARDHYBRID   | Cardassian   | CardHybrid    |
| 13 | KESSOKHEAVY  | Kessok       | KessokHeavy   |
| 14 | KESSOKLIGHT  | Kessok       | KessokLight   |
| 15 | SHUTTLE      | Federation   | Shuttle       |

Non-playable (16–45): `CARDFREIGHTER`, `FREIGHTER`, `TRANSPORT`,
`SPACEFACILITY`, `COMMARRAY`, `COMMLIGHT`, `DRYDOCK`, `PROBE`,
`DECOY`, `SUNBUSTER`, `CARDOUTPOST`, `CARDSTARBASE`, `CARDSTATION`,
`FEDOUTPOST`, `FEDSTARBASE`, `ASTEROID`, `ASTEROID1`/`2`/`3`,
`AMAGON`, `BIRANUSTATION`, `ENTERPRISE`, `GERONIMO`, `PEREGRINE`,
`ASTEROIDH1`/`2`/`3`, `ESCAPEPOD`, `KESSOKMINE`, `BORGCUBE`.

### Species → Torp (full table)

`Multiplayer/SpeciesToTorp.py`. `MAX_TORPS = 16` (IDs 0–15; only
1–15 are valid).

| ID | Constant            | Script              |
|----|---------------------|---------------------|
| 1  | DISRUPTOR           | Disruptor           |
| 2  | PHOTON              | PhotonTorpedo       |
| 3  | QUANTUM             | QuantumTorpedo      |
| 4  | ANTIMATTER          | AntimatterTorpedo   |
| 5  | CARDTORP            | CardassianTorpedo   |
| 6  | KLINGONTORP         | KlingonTorpedo      |
| 7  | POSITRON            | PositronTorpedo     |
| 8  | PULSEDISRUPT        | PulseDisruptor      |
| 9  | FUSIONBOLT          | FusionBolt          |
| 10 | CARDASSIANDISRUPTOR | CardassianDisruptor |
| 11 | KESSOKDISRUPTOR     | KessokDisruptor     |
| 12 | PHASEDPLASMA        | PhasedPlasma        |
| 13 | POSITRON2           | Positron2           |
| 14 | PHOTON2             | PhotonTorpedo2      |
| 15 | ROMULANCANNON       | RomulanCannon       |

### Object-ID allocation

```
Player N base = 0x3FFFFFFF + (N * 0x40000)        # 262,143 IDs per slot
slot_from_id  = (object_id - 0x3FFFFFFF) >> 18
```

Each player slot gets 262,144 IDs. Subsystem IDs are *not* derived
from this base — they come from the global counter at `0x0095B078`
(see "TGObject hash table" below).

### Receiver pipeline (`FUN_0069F620`)

```
Handler_ObjCreate_0x02_0x03(MultiplayerGame*, TGMessage*, char isTeam)
  ├─ Extract raw buffer: FUN_006B8530(msg) → data_ptr + size
  ├─ Read owner_slot (byte 1), team_id (byte 2 if isTeam)
  ├─ Swap active player context:
  │    save DAT_0097FA84 (current slot) and DAT_0097FA8C (current obj-ID base)
  │    set DAT_0097FA84 = owner_slot
  │    load DAT_0097FA8C from MultiplayerGame+0x84[owner_slot * 0x18]
  │
  ├─ Ship_Deserialize(data + header_len, size - header_len)  [0x005A1F50]
  │    ├─ StreamReader::Init                   [0x006CF180]
  │    ├─ ReadInt32 → class_id                  [0x006CF670]
  │    ├─ ReadInt32 → object_id
  │    ├─ FUN_00430730(NULL, object_id) → duplicate check
  │    ├─ FUN_006F13E0(class_id) → TG factory create
  │    ├─ obj->vtable[0x118](stream) → ReadStream
  │    │    ├─ FUN_005A2030: read species byte → ship+0xEC
  │    │    ├─ Python: SpeciesToShip.InitObject(ship, species)
  │    │    │    ├─ GetShipFromSpecies(species) → load ship module
  │    │    │    ├─ ship.SetupModel(name) → load NIF
  │    │    │    ├─ Hardpoints.LoadPropertySet()
  │    │    │    ├─ ship.SetupProperties() → create subsystems
  │    │    │    └─ ship.UpdateNodeOnly()
  │    │    └─ Continue: position, orientation, velocity, name, set, subsystems
  │    ├─ obj->vtable[0x11C](stream) → PostLoad
  │    └─ return ship*
  │
  ├─ Restore player context
  ├─ If isTeam: ship+0x2E4 = team_id
  │
  ├─ Relay to other peers (iterate 16 slots):
  │    for each connected peer != sender && != self:
  │      clone message, send via FUN_006B4C10(WSN, peer_connID, cloned_msg, 0)
  │    For sender's slot: update stored object_id
  │
  ├─ If obj->vtable[0x04]() != 0x8009:                  # skip for torpedoes
  │    NiAlloc(0x58) → network tracker
  │    FUN_0047DAB0(tracker, ship, "Network")
  │    ship->vtable[0x134](tracker, 1, 1)
  │
  └─ ship+0xF0 = 0
```

The player-context swap is what makes the per-slot object-ID
allocator correct — the deserialiser needs `DAT_0097FA8C` set to
the owner's base before the ship's subsystems claim IDs.

### Stock packet examples (verified)

Akira at (88, -66, -73), player 0, team 2:

```
03 00 02 08 80 00 00 FF FF FF 3F 01 00 00 B0 42 00 00 84 C2 00 00 92 C2 …
^^ ^^ ^^ ^^^^^^^^^^^ ^^^^^^^^^^^ ^^ ^^^^^^^^^^^ ^^^^^^^^^^^ ^^^^^^^^^^^
|  |  |  class 8008  obj 3FFF…   |  X=88.0      Y=-66.0     Z=-73.0
|  |  team=2                     species=1 (Akira)
|  owner=0 (host)
opcode 0x03
```

Sovereign at (38, -49, -35), same player, same team:

```
03 00 02 08 80 00 00 FF FF FF 3F 05 00 00 18 42 00 00 44 C2 00 00 0C C2 …
                                  ^^ species=5 (Sovereign)
```

Same player and team but different ship and spawn position —
consistent with a player changing ship selection (the second
creation replaces the first).

### Functions

| Address      | Function                          |
|--------------|-----------------------------------|
| `0x0069F620` | `Handler_ObjCreate_0x02_0x03`     |
| `0x005A1F50` | `Ship_Deserialize`                |
| `0x005A2030` | `ReadSpeciesByte` (`ship+0xEC`)   |
| `0x005B0E80` | `Ship::InitObject`                |
| `0x006F13E0` | `TGFactoryCreate` (class ID lookup)|
| `0x00430730` | `ObjectLookupByID` (duplicate check)|
| `0x006CF670` | `StreamReader::ReadInt32`         |
| `0x006B4C10` | `SendToPeer`                      |
| `0x0047DAB0` | `InitNetworkTracker`              |

---

## StateUpdate (`0x1C`)

Per-ship per-tick state replication, sent at ~10 Hz on the owning
peer. The most complex and most frequent message in the system.

### Wire format

```
Offset  Size  Type     Field
------  ----  ----     -----
0       1     u8       opcode = 0x1C
1       4     i32      object_id        ship's network object ID
5       4     f32      game_time        current game-clock timestamp
9       1     u8       dirty_flags      bitmask of which fields follow
10+     var   data     fields (in order, per dirty bit)
```

### Dirty flags

| Bit  | Constant            | Field                                         |
|------|---------------------|-----------------------------------------------|
| `0x01`| `POSITION_ABSOLUTE`| Full position + optional subsystem hash       |
| `0x02`| `POSITION_DELTA`   | Compressed position delta                     |
| `0x04`| `ORIENTATION_FWD`  | Forward vector (CompressedVector3)            |
| `0x08`| `ORIENTATION_UP`   | Up vector (CompressedVector3)                 |
| `0x10`| `SPEED`            | Current speed (CompressedFloat16)             |
| `0x20`| `SUBSYSTEM_STATES` | Subsystem health/status round-robin           |
| `0x40`| `CLOAK_STATE`      | Cloaking device on/off                        |
| `0x80`| `WEAPON_STATES`    | Weapon health round-robin (client → server)   |

### Direction-based split (verified)

In stock dedicated server traces, flags `0x20` and `0x80` are
**mutually exclusive by direction**:

| Direction | Used         | Never used      | Packet count (verified) |
|-----------|--------------|-----------------|-------------------------|
| C → S     | `0x80` (WPN) | `0x20` (SUB)    | 10,459                  |
| S → C     | `0x20` (SUB) | `0x80` (WPN)    | 19,997                  |

Common observed combinations:

- **C → S:** `0x9E` (DELTA+FWD+UP+SPD+WPN), `0x96`, `0x92`, `0x9D`, `0x8E`.
- **S → C:** `0x20` (SUB only), `0x3E` (DELTA+FWD+UP+SPD+SUB), `0x36`, `0x3D`, `0x32`.

The decision logic in `Ship::WriteStateUpdate` (`FUN_005B17F0`):

```c
// SP path:    flags |= 0x80
// MP path:    flags |= 0x20
//   exception: if friendly fire enabled and enough other players,
//              skip subsystem states
```

`DAT_0097FA8A == 0` (not multiplayer) drives the `0x80` branch.
Stock traces show clients send `0x80` in multiplayer — apparently
the **client-side `IsMultiplayer` value differs from the host's**
during this serialisation, so clients hit the SP path even in MP.

### Flag `0x01` — absolute position

```
+0      4     f32      pos_x
+4      4     f32      pos_y
+8      4     f32      pos_z
+12     bit   bool     has_subsystem_hash
[if has_subsystem_hash AND is_multiplayer:]
  +0    2     u16      subsystem_hash    XOR-folded 32-bit hash
[else:]
  (nothing)
```

Sent when the position-delta tracker overflows (`uStack_494._3_1_`
non-zero). When sent, it clears the delta-compression reference:
`saved_pos = current_pos`, `delta_dir_bytes = 0,0,0`,
`delta_magnitude = 0`.

The subsystem hash is anti-cheat dead code in MP — see
"Subsystem integrity hash" at the bottom of this doc.

### Flag `0x02` — position delta (compressed)

```
+0      5     cv4      position_delta    CompressedVector4(dx, dy, dz, param4=1)
                                          uses uint16 magnitude
                                          d{x,y,z} = current - saved
```

Written via `FUN_006D2F10(stream, dx, dy, dz, 1)`.

Sent when delta direction bytes have changed from cached values, OR
the periodic force-update timer fires.

### Flag `0x04` — forward orientation

```
+0      3     cv3      forward_vector    3 signed bytes / 127.0, direction only
```

Written via `FUN_006D2E50`. Read from `ship->vtable[0xAC]`
(`GetForwardVector`).

### Flag `0x08` — up orientation

```
+0      3     cv3      up_vector         3 signed bytes / 127.0, direction only
```

Same primitives. Read from `ship->vtable[0xB0]` (`GetUpVector`).

### Flag `0x10` — speed

```
+0      2     u16      speed_compressed  CompressedFloat16
```

Speed is computed as `sqrt(vx² + vy² + vz²)`, negated if `IsReversing`
(`FUN_005AC4F0`), then CF16-encoded.

### Flag `0x20` — subsystem states (round-robin)

Server-to-client only. Subsystems serialise in a round-robin from
the ship's top-level subsystem linked list (`ship+0x284`); each
update sends a few subsystems starting from where the previous
update left off.

```
+0      1     u8       start_index    position in subsystem list
+1      var   data     subsystem_data per-subsystem WriteState output
```

**No count field** — the receiver reads until the stream is
exhausted (`streamPos >= dataLength`).

#### Subsystem list order

There is **no fixed index table**. `start_index` is a position in
the ship's serialisation linked list at `ship+0x284`, whose
contents and order are determined by the hardpoint script's
`LoadPropertySet()` call order. Only **top-level system containers**
remain in the list after `LinkAllSubsystemsToParents`
(`FUN_005B3E20`) removes children. Individual weapons (phaser banks,
torpedo tubes, etc.) and engines are serialised **recursively**
within their parent's `WriteState`.

#### Per-subsystem WriteState formats (vtable `+0x70`)

Three distinct implementations:

**Format 1 — base `ShipSubsystem` (`0x0056D320`)** — Hull,
ShieldGenerator, individual children:

```
[condition: u8]              # (int)(condition / GetMaxCondition() * 255.0)
                              #   0xFF = full, 0x00 = destroyed
[child_0 WriteState]          # recursive
[child_1 WriteState]
…
```

**Format 2 — `PoweredSubsystem` (`0x00562960`)** — Sensors,
Engines, Weapons, Cloak, Repair, Tractors:

```
[base WriteState]             # condition byte + recursive children
if (isOwnShip == 0):          # remote ship — include power data
    [hasData: bit=1]          # WriteBit(1)
    [powerPctWanted: u8]      # (int)(powerPercentageWanted * 100.0); 0..100
else:                         # own ship — owner has local state
    [hasData: bit=0]
```

**Format 3 — `PowerSubsystem` (`0x005644B0`)** — reactor / warp
core only:

```
[base WriteState]
[mainBatteryPct: u8]          # (int)(mainBatteryPower / mainBatteryLimit * 255)
[backupBatteryPct: u8]        # (int)(backupBatteryPower / backupBatteryLimit * 255)
```

`PowerSubsystem` **always** writes both battery bytes regardless of
`isOwnShip`.

#### Round-robin

From `Ship::WriteStateUpdate` (`0x005B17F0`), the per-object
tracking structure (`iVar7+0x30` cursor and `+0x34` index) persists
across ticks:

```
if cursor == NULL:
    cursor = ship->subsystemListHead    # ship+0x284
    index  = 0

initialCursor = cursor
WriteByte(stream, index)                # startIndex

while (streamPos - budgetStart) < 10:   # 10-byte budget incl. startIndex
    subsystem = cursor->data
    cursor    = cursor->next
    subsystem->WriteState(stream, isOwnShip)
    index++
    if cursor == NULL:                  # end of list — wrap
        cursor = ship->subsystemListHead
        index  = 0
    if cursor == initialCursor:
        break                           # full cycle complete
```

Receive (flag `0x20` in `FUN_005B21C0`):

```
startIndex = ReadByte(stream)
node       = ship->subsystemListHead
for i in range(startIndex): node = node->next     # skip to start

while streamPos < dataLength:
    subsystem = node->data
    node      = node->next
    subsystem->ReadState(stream, timestamp)       # vtable+0x74
    if node == NULL: node = ship->subsystemListHead   # wrap
```

Budget: 10 bytes per flag-0x20 block per tick. With ~11 top-level
subsystems on a Sovereign, full state convergence takes 3–5 ticks
≈ 0.3–0.5 s at the ~10 Hz update rate.

### Flag `0x40` — cloak state

```
+0      bit   bool     cloak_active    0 = decloaked, 1 = cloaked
```

Read from `ship[0xB7]+0x9C` (cloaking device's `isOn` byte). Sent
only when the value changes from cached state. The wire serialises
`isOn`, **not** the state-machine value (`+0xB0`); the receiver
runs its own local state-machine transitions including the visual
effects and timer.

### Flag `0x80` — weapon states (round-robin)

```
[repeated while stream_bytes_written < 6:]
  weapon = list_node->data
  if weapon->vtable[0x08](0x801C):   # IsType(weapon)
    [weapon_index: u8]
    [weapon_health_byte: u8]         # ftol(health * scale_factor)
[end repeat]
```

2 bytes per entry, ~6-byte budget. Iterates the weapon linked list
(also `ship+0x284`).

### Receiver (`FUN_005B21C0`)

```
1. ReadByte → opcode (0x1C)
2. ReadInt32 → object_id
3. ReadFloat → game_time
4. ReadByte → dirty_flags

if (flags & 0x01):                     # absolute position
    pos_x = ReadFloat …
    has_hash = ReadBit
    if has_hash && multiplayer:
        received = ReadShort
        if XOR-fold(received) != XOR-fold(local_hash):
            POST ET_BOOT_PLAYER       # anti-cheat kick

if (flags & 0x02):                     # position delta
    ReadCompressedVector4(&dx, &dy, &dz, param4=1)
    new_pos = saved_pos + delta

if (flags & 0x04):                     # forward
    ReadCompressedVector3 → apply

if (flags & 0x08):                     # up
    ReadCompressedVector3 → apply

if (flags & 0x10):                     # speed
    DecompressFloat16(ReadShort) → physics

if (flags & 0x40):                     # cloak
    cloak = ReadBit
    if cloak: FUN_0055F360             # activate
    else:     FUN_0055F380             # deactivate

if (flags & 0x20):                     # subsystem round-robin
    startIndex = ReadByte
    iterate from startIndex …

if (flags & 0x80):                     # weapon round-robin
    while streamPos < total:
        weapon_idx = ReadByte
        health     = ReadByte
        if weapon[idx].vtable[0x08](0x801C):
            weapon[idx]->vtable[0x84](health * SCALE, gameTime)
```

Force-update timing: per-field timestamps live at
`trackerObj+0x04`–`+0x2E`. A field is force-sent if
`gameTime - lastSentTime > DAT_00888860` (the global threshold). When
all dirty fields are sent simultaneously, the master timestamp at
`trackerObj+0x04` is updated.

---

## PythonEvent (`0x06` / `0x0D`)

Polymorphic event transport — carries arbitrary `TGEvent`-derived
objects. The first 4 bytes after the opcode are a factory ID that
selects which event class to construct.

**Direction**: typically host → all clients (via "NoMe" group),
reliable. Stock dedi traces show ~251 of these per 15-min 3-player
session — the most frequent game opcode. Clients essentially never
send `0x06` in stock content; if they did, the host's MultiplayerGame
dispatcher would hit jump-table entry 4 and relay to "Forward" before
falling through to the local handler (`FUN_0069F880`).

`0x0D` shares the same handler and identical wire format — alternate
opcode, same decode.

### Common header (17 bytes minimum)

```
Offset  Size  Type    Field
------  ----  ----    -----
0       1     u8      opcode             0x06 or 0x0D
1       4     i32     factory_id         event class factory
5       4     i32     event_type         event-type constant
9       4     i32     source_obj_id      source object (encoded as below)
13      4     i32     dest_obj_id        dest/related object
[class-specific extension follows]
```

Multi-byte: little-endian.

### Object reference encoding

`WriteObjectRef`:

| Case                                   | Wire value      |
|----------------------------------------|-----------------|
| NULL pointer                           | `0x00000000`    |
| Sentinel (global at `0x0095ADFC`)      | `0xFFFFFFFF` (-1) |
| Valid object                           | `*(int*)(obj + 0x04)` (TGObject network ID) |

`ReadObjectRef` performs the inverse: ID → hash-table lookup via
`FUN_006F0EE0`.

### Four event classes

| Factory ID  | Class                       | Wire size | Extension fields                     |
|-------------|-----------------------------|-----------|--------------------------------------|
| `0x00000101`| `TGSubsystemEvent`           | 17 bytes  | (none — base TGEvent only)           |
| `0x00000105`| `TGCharEvent`                | 18 bytes  | `+1 byte: char_value`                |
| `0x0000010C`| `TGObjPtrEvent`              | 21 bytes  | `+4 int32: obj_ptr_id`               |
| `0x00008129`| `ObjectExplodingEvent`       | 25 bytes  | `+4 int32: firing_player_id`, `+4 float: lifetime` |

#### `TGSubsystemEvent` (factory `0x101`, 17 bytes)

Most common in the collision-damage chain. Used for repair-list
events:

| Event type    | Constant                          | Meaning                                      |
|---------------|-----------------------------------|----------------------------------------------|
| `0x008000DF`  | `ET_ADD_TO_REPAIR_LIST`           | Subsystem damaged, queued                     |
| `0x00800074`  | `ET_REPAIR_COMPLETED`             | Subsystem reached max condition              |
| `0x00800075`  | `ET_REPAIR_CANNOT_BE_COMPLETED`   | Subsystem destroyed while in queue           |

Both `source_obj_id` and `dest_obj_id` are **subsystem-level
TGObject IDs** (auto-assigned from the global counter
`DAT_0095B078`), not ship IDs. `source` is the damaged subsystem,
`dest` is the `RepairSubsystem`.

Memory layout (size `0x28`, vtable `0x008932A4`):

```
+0x00  vtable
+0x04  ni_refcount
+0x08  source_object   ptr
+0x0C  related_object  ptr
+0x10  event_type      uint32
+0x14  timestamp       float (-1.0 init)
+0x18  flags_a / flags_b (uint16 × 2)
+0x1C  reserved
+0x20  reserved
+0x24  parent_event    cleared to 0 on receive
```

Class hierarchy:

```
NiObject
  └── TGEvent (factory 0x02, size 0x28)
        └── TGSubsystemEvent (factory 0x101, size 0x28)
              ├── TGCharEvent (factory 0x105, size 0x2C, +0x28 = byte)
              └── TGObjPtrEvent (factory 0x10C, size 0x2C, +0x28 = int32)
        └── ObjectExplodingEvent (factory 0x8129, size 0x30,
                                  +0x28 = int32, +0x2C = float)
```

#### `TGCharEvent` (factory `0x105`, 18 bytes)

Adds a single byte payload at `+0x28`. Used by opcodes `0x07`–`0x12`
and `0x1B` (the event-forward family) — see the
`SetPhaserLevel (0x12)` example in `per-feature-protocols.md`.

```
[0x06] [factory: 0x00000105] [event_type] [source_obj] [dest_obj] [byte]
```

Memory layout (size `0x2C`, vtable `0x008932DC`): same as
`TGSubsystemEvent` plus `+0x28: char` and 3 bytes of struct padding.

#### `TGObjPtrEvent` (factory `0x10C`, 21 bytes)

Adds a third `int32` object reference at `+0x28`. **Most common
event class during weapon combat** — 45 % of all PythonEvents in a
33.5-min battle trace (1,718 / 3,825).

```
[0x06] [factory: 0x0000010C] [event_type] [source_obj] [dest_obj] [obj_ptr_id]
```

Memory layout (size `0x2C`, vtable `0x0088869C`): same as
`TGSubsystemEvent` plus `+0x28: int32`.

**`TGCharEvent` vs `TGObjPtrEvent`**: both are `0x2C` bytes in
memory, both extend `TGSubsystemEvent`, and both use slot `+0x28` —
but `TGCharEvent` writes/reads a byte while `TGObjPtrEvent` writes/reads
an `int32`. They are distinct classes with different vtables and
constructors.

Network-forwarded events using `TGObjPtrEvent`:

| Event type    | Constant                          | Producer                             | `obj_ptr` |
|---------------|-----------------------------------|--------------------------------------|-----------|
| `0x0080007C`  | `ET_WEAPON_FIRED`                 | `FUN_00571F40`, `FUN_0057C9E0`, `FUN_0057F580` | Target ID or 0 |
| `0x00800081`  | `ET_PHASER_STARTED_FIRING`        | `FUN_00571F40` (Phaser::Fire)         | Target ID |
| `0x00800083`  | `ET_PHASER_STOPPED_FIRING`        | vtable xref ~`0x005712FE`             | Target ID |
| `0x0080007D`  | `ET_TRACTOR_BEAM_STARTED_FIRING`  | `FUN_0057F580` (Tractor::Fire)        | Target ID |
| `0x00800076`  | `ET_REPAIR_INCREASE_PRIORITY`     | `FUN_005519E0`                        | Subsystem ID |
| `0x008000DC`  | `ET_STOP_FIRING_AT_TARGET_NOTIFY` | `FUN_00574010`, `FUN_005825A0`        | Target ID (host-only) |

Local-only `TGObjPtrEvent` types (never serialised to wire):

| Event type    | Constant                          | `obj_ptr`                                  |
|---------------|-----------------------------------|--------------------------------------------|
| `0x0080000E`  | `ET_SET_PLAYER`                   | New player ship ID                          |
| `0x00800058`  | `ET_TARGET_WAS_CHANGED`           | **Previous** target ID                      |
| `0x0080006B`  | `ET_SUBSYSTEM_HIT`                | Subsystem's own ID                          |
| `0x00800085`  | `ET_TRACTOR_TARGET_DOCKED`        | Docked ship ID                              |
| `0x00800088`  | `ET_SENSORS_SHIP_IDENTIFIED`      | Identified ship ID                          |

Dual-fire pattern: phaser fire creates `ET_PHASER_STARTED_FIRING`
**and** `ET_WEAPON_FIRED` simultaneously. Tractor fire does the same.
Torpedo creates only `ET_WEAPON_FIRED`. Every phaser/tractor cycle
generates ~4 `TGObjPtrEvent` messages (start-specific + weapon-fired
+ stopped-specific + stop-notify).

Python scripts use `TGObjPtrEvent` for ~27 additional local-only
event types (~72 call sites). The SWIG functions `SetObjPtr`,
`GetObjPtr`, `Create` have **zero C++ xrefs** — they're Python-only.

#### `ObjectExplodingEvent` (factory `0x8129`, 25 bytes)

Carries ship destruction. Adds firing player ID and explosion
lifetime.

```
[0x06] [factory: 0x00008129] [event_type: 0x0080004E] [source_obj] [dest_obj]
[firing_player_id: int32] [lifetime: float32]
```

| Field            | Notes                                                  |
|------------------|--------------------------------------------------------|
| `event_type`     | Always `0x0080004E` (`ET_OBJECT_EXPLODING`)            |
| `source_obj_id`  | Object that is exploding                                |
| `dest_obj_id`    | Target (typically NULL or sentinel)                     |
| `firing_player_id`| Connection ID of the killer (0 for self-destruct/AI)   |
| `lifetime`       | Explosion-effect duration, seconds (typically 9.5 in stock) |

Memory layout (size `0x30`, vtable `0x0088A178`): base TGEvent
plus `+0x28: int32 firing_player_id`, `+0x2C: float lifetime`.

`ObjectExplodingEvent::IsA` returns true for `0x8129` and `0x02`
(skips the intermediate factory).

Constructor at `0x0043F8B0`:
`firing_player_id = 0`, `lifetime = 0.0f`, vtable `= 0x0088A178`.

Example wire (25 bytes, ship 0x3FFFFFFF dies, killed by player 2,
1 s explosion):

```
06                    opcode
29 81 00 00           factory  = 0x00008129
4E 00 80 00           type     = 0x0080004E (ET_OBJECT_EXPLODING)
FF FF FF 3F           source   = 0x3FFFFFFF (Player 0's ship)
FF FF FF FF           dest     = sentinel (-1)
02 00 00 00           killer   = player 2
00 00 80 3F           lifetime = 1.0
```

### Producers

#### `HostEventHandler` (`0x006A1150`)

Handles repair events. Registered by `MultiplayerGame` constructor
**only when `g_IsMultiplayer != 0`** for:

- `ET_ADD_TO_REPAIR_LIST` (`0x008000DF`)
- `ET_REPAIR_COMPLETED` (`0x00800074`)
- `ET_REPAIR_CANNOT_BE_COMPLETED` (`0x00800075`)

Behaviour:

```
1. Read g_TGWinsockNetwork from [0x0097FA78]; if NULL, return.
2. Create TGBufferStream; store opcode 0x06 in buffer.
3. event->WriteToStream(stream)        # via vtable+0x34
4. Get position (bytes written).
5. Allocate TGMessage (0x40 bytes).
6. Copy [opcode][stream_data] into message (position + 1 bytes).
7. Mark reliable (msg+0x3A = 1).
8. SendTGMessageToGroup(WSN, "NoMe", msg)
```

#### `ObjectExplodingHandler` (`0x006A1240`)

Registered for `ET_OBJECT_EXPLODING` (`0x0080004E`). Two paths:

- **Multiplayer**: identical to `HostEventHandler` — serialise as
  opcode `0x06` to "NoMe", reliably.
- **Single-player**: directly sets `ship+0x14C = event->lifetime`
  and calls `FUN_005AC250` (which invokes `Effects.ObjectExploding(ship)`
  via Python).

### Receivers

`FUN_0069F880` — opcodes `0x06` and `0x0D`. Generic event deserializer:

```
1. Extract buffer pointer + length from TGMessage (FUN_006B8530).
2. Create TGBufferStream from buffer + 1 (skip opcode byte).
3. FUN_006D6200 (ReadObjectFromStream):
     a. Read factory_id via stream->ReadSmallInt (vtable+0x60)
     b. Look up factory in hash table (FUN_006F13E0)
     c. Allocate and construct event of the correct class
     d. event->ReadFromStream(stream)         # vtable+0x38
4. FUN_006F13C0 — resolve object references.
5. Clear event+0x24 (parent event ptr).
6. PostEvent(event)                            # FUN_006DA300
7. Release event (free if refcount = 0).
```

Does NOT relay — repair PythonEvents originate on the host and go
straight to "NoMe", so no relay is needed. (Client-originated `0x06`
messages, rare in stock content, hit a different jump-table entry
that does relay to "Forward" before falling through here.)

`FUN_0069FDA0` — generic event-forward for opcodes `0x07`–`0x12`,
`0x1B`. Performs host relay (forward to "Forward" group) **and**
applies an event-type override before local dispatch:

| Opcode | Sender event   | Receiver override | Notes                     |
|--------|----------------|-------------------|---------------------------|
| `0x07` | `0x008000D8`   | `0x008000D7`      | StartFiring               |
| `0x08` | `0x008000DA`   | `0x008000D9`      | StopFiring                |
| `0x09` | `0x008000DC`   | `0x008000DB`      | StopFiringAtTarget        |
| `0x0A` | `0x0080006C`   | `0x0080006C` (no change) | SubsysStatus       |
| `0x0B` | `0x008000DF`   | `0` (preserve)    | AddToRepairList           |
| `0x0C` | varies         | `0` (preserve)    | ClientEvent               |
| `0x0E` | `0x008000E2`   | `0x008000E3`      | StartCloak                |
| `0x0F` | `0x008000E4`   | `0x008000E5`      | StopCloak                 |
| `0x10` | `0x008000EC`   | `0x008000ED`      | StartWarp                 |
| `0x11` | `0x00800076`   | `0` (preserve)    | RepairListPriority        |
| `0x12` | `0x008000E0`   | `0` (preserve)    | SetPhaserLevel            |
| `0x1B` | `0x008000FE`   | `0x008000FD`      | TorpTypeChange            |

`override = 0` means the event keeps its original wire type. Sender
codes that *do* differ from receiver codes mean the event "request"
on one side becomes a "notify" on the other.

### Vtables

`TGEvent` base (`0x00895FF4`):

| Slot | Offset | Address      | Name                           |
|------|--------|--------------|--------------------------------|
| 0    | `+0x00`| `0x006D5D40` | `scalar_deleting_dtor`          |
| 1    | `+0x04`| `0x006D5CE0` | `GetFactoryID` → factory type   |
| 2    | `+0x08`| `0x006D5CF0` | `IsA(id)`                       |
| 3    | `+0x0C`| `0x006F1650` | (no-op, inherited from NiObject)|
| 4    | `+0x10`| `0x006D5EC0` | `WriteToStream_Full` (persistence)|
| 5    | `+0x14`| `0x006D5FF0` | `ReadFromStream_Full` (persistence)|
| 9    | `+0x24`| `0x006D5D10` | `GetClassName` → `"TGEvent"`     |
| 10   | `+0x28`| `0x006D5D20` | `GetSWIGName` → `"_p_TGEvent"`   |
| 11   | `+0x2C`| `0x006D5D30` | `GetPtrName` → `"TGEventPtr"`    |
| 12   | `+0x30`| `0x006D6230` | `CopyFrom`                       |
| 13   | `+0x34`| `0x006D6130` | **`WriteToStream` (network)**    |
| 14   | `+0x38`| `0x006D61C0` | **`ReadFromStream` (network)**   |

`ObjectExplodingEvent` (`0x0088A178`):

| Slot | Offset | Address      | Name                                    |
|------|--------|--------------|-----------------------------------------|
| 0    | `+0x00`| `0x0043F950` | `scalar_deleting_dtor`                   |
| 1    | `+0x04`| `0x0043F8E0` | `GetFactoryID` → `0x8129`                |
| 2    | `+0x08`| `0x0043F8F0` | `IsA` → true for `0x8129`, `0x02`        |
| 9    | `+0x24`| `0x0043F920` | `GetClassName` → `"ObjectExplodingEvent"` |
| 13   | `+0x34`| `0x0043F990` | **`WriteToStream` (network)**            |
| 14   | `+0x38`| `0x0043F9C0` | **`ReadFromStream` (network)**           |

`TGCharEvent` (`0x008932DC`):

| Slot | Offset | Address      | Name                              |
|------|--------|--------------|-----------------------------------|
| 0    | `+0x00`| `0x00574CB0` | `scalar_deleting_dtor`             |
| 1    | `+0x04`| `0x00574C40` | `GetFactoryID` → `0x105`           |
| 2    | `+0x08`| `0x00574C50` | `IsA` → true for `0x105`, `0x101`, `0x02` |
| 9    | `+0x24`| `0x00574C80` | `GetClassName` → `"TGCharEvent"`    |
| 12   | `+0x30`| `0x006D6920` | `CopyFrom`                          |
| 13   | `+0x34`| `0x006D6940` | **`WriteToStream` (network)**       |
| 14   | `+0x38`| `0x006D6960` | **`ReadFromStream` (network)**      |

`TGObjPtrEvent` (`0x0088869C`):

| Slot | Offset | Address      | Name                              |
|------|--------|--------------|-----------------------------------|
| 0    | `+0x00`| `0x00403310` | `scalar_deleting_dtor`             |
| 1    | `+0x04`| `0x004032B0` | `GetFactoryID` → `0x10C`           |
| 2    | `+0x08`| `0x004032C0` | `IsA` → true for `0x10C`, `0x101`, `0x02` |
| 9    | `+0x24`| `0x004032F0` | `GetClassName` → `"TGObjPtrEvent"`  |
| 12   | `+0x30`| `0x006D6DA0` | `CopyFrom` (base + obj_ptr)         |
| 13   | `+0x34`| `0x006D6DC0` | **`WriteToStream` (network)**       |
| 14   | `+0x38`| `0x006D6DF0` | **`ReadFromStream` (network)**      |

### Collision → PythonEvent chain

A typical mid-combat collision generates ~14 PythonEvents (verified
across stock traces; range 12–14 depending on collision geometry
and pre-existing repair-queue state):

```
1. ProximityManager detects collision.
2. Posts ET_COLLISION_EFFECT (0x00800050).
3. ShipClass::CollisionEffectHandler (0x005AF9C0):
     a. Validate sender is host.
     b. Send CollisionEffect (opcode 0x15) to "NoMe".
     c. Fall through to FUN_005AFAD0 (collision damage).
4. FUN_005AFAD0 → per-contact → FUN_005AF4A0 (per-subsystem damage):
     reduce subsystem condition; SetCondition (FUN_0056C470).
5. SetCondition: if newCondition < max && ship alive,
     POST ET_SUBSYSTEM_HIT (0x0080006B).
6. RepairSubsystem::HandleHitEvent (0x005658D0):
     AddToRepairList_MP (FUN_00565900).
     If host && multiplayer: POST ET_ADD_TO_REPAIR_LIST.
7. HostEventHandler (0x006A1150): serialise as opcode 0x06,
     send to "NoMe".
```

Two ships × ~7 hit subsystems each = ~14 PythonEvents per
collision. A *ship-destruction* collision adds one
`ObjectExplodingEvent` ahead of the repair events.

Stock-trace dump (single non-lethal collision):

| #     | Factory  | Event type   | Meaning                  |
|-------|----------|--------------|--------------------------|
| 1–14  | `0x0101` | `0x008000DF` | `ADD_TO_REPAIR_LIST` × 14|

For lethal:

| #   | Factory  | Event type   | Meaning                       |
|-----|----------|--------------|-------------------------------|
| 1   | `0x8129` | `0x0080004E` | `ObjectExplodingEvent`         |
| 2–14| `0x0101` | `0x008000DF` | `ADD_TO_REPAIR_LIST` × 13      |

### Notable functions

| Address      | Function                                                  |
|--------------|-----------------------------------------------------------|
| `0x006A1150` | `HostEventHandler` — serialise repair events as `0x06`    |
| `0x006A1240` | `ObjectExplodingHandler` — serialise explosion as `0x06`  |
| `0x006A17C0` | `SendEventMessage` — generic: serialize event + opcode    |
| `0x0069F880` | PythonEvent receiver (opcodes `0x06`/`0x0D`)              |
| `0x0069FDA0` | `GenericEventForward` — relay + deserialise (`0x07`–`0x12`,`0x1B`) |
| `0x006D6130` | `TGEvent::WriteToStream`                                   |
| `0x006D61C0` | `TGEvent::ReadFromStream`                                  |
| `0x006D6200` | `ReadObjectFromStream` — factory-based event construction  |
| `0x006DA300` | `EventManager::PostEvent`                                  |
| `0x006F13E0` | `TGEventFactory::Create`                                   |
| `0x006F0EE0` | `LookupObjectByID` (TGObject hash-table lookup)            |

---

## TGObject hash table (cross-reference)

All persistent game objects (ships, subsystems, etc.) carry a
network ID at `+0x04`. IDs come from two sources:

- **Auto-assigned globals** — every subsystem at construction time
  pulls the next value from `DAT_0095B078`. Stored in the global
  hash table at `DAT_0099A67C` for ID-to-pointer lookup via
  `FUN_006F0EE0`.
- **Player-base offsets** — ships use `Player N base = 0x3FFFFFFF +
  N * 0x40000` (262,144 IDs per slot).

**Subsystem IDs are sequential globals, not derived from ship IDs.**
The mapping depends on construction order; the only way to resolve a
subsystem ID on the receive side is the hash-table lookup.

Constructor pattern (`FUN_006F0A70`):

```c
void TGObject_ctor(void* this, int objectID) {
    if (objectID == 0) {
        *(int*)(this + 0x04) = DAT_0095B078;       // auto-assign
        objectID = DAT_0095B078;
    } else {
        *(int*)(this + 0x04) = objectID;
        if (DAT_0095B07D == 0 || objectID < DAT_0095B078) goto skip;
    }
    DAT_0095B078 = objectID + 1;                    // increment
skip:
    FUN_006F0F30(this);                             // register in hash table
}
```

`SetOwnerShip` (`0x0056BC50`) sets the ship pointer:

```c
void SetOwnerShip(void* this, void* ship) {
    *(void**)(this + 0x40) = ship;
    FUN_0056BDE0(this);            // additional setup
}
```

In `Ship::SetupProperties` (`FUN_005B3FB0`), each subsystem is
created with `param_1 = 0` (auto-assign).

| Address       | Symbol                 | Description                          |
|---------------|------------------------|--------------------------------------|
| `0x006F0A70`  | `TGObject::ctor`       | Assigns `+0x04` = network ID         |
| `0x0095B078`  | `g_NextObjectID`       | Global auto-increment counter        |
| `0x0099A67C`  | `g_ObjectHashTable`    | Hash table: ID → object pointer      |
| `0x006F0EE0`  | `LookupObjectByID`      | Hash-table lookup                    |
| `0x006F0F30`  | (registration)          | Hash-table insert at construction    |

---

## Subsystem integrity hash (anti-cheat)

The optional `subsystem_hash` carried in the StateUpdate
flag-`0x01` block is computed by `FUN_005B5EB0` from the ship's
subsystem table at `ship+0x27C`. It walks 12 named slots in this
exact order, each NULL-checked (NULL slots skipped):

| # | Offset from `+0x27C` | Ship offset | Subsystem        | Hash method           | Extra fields                                  |
|---|----------------------|-------------|------------------|-----------------------|-----------------------------------------------|
| 1 | `+0x48`              | `+0x2C4`    | Power Reactor    | `base_subsystem_hash`  | none                                          |
| 2 | `+0x44`              | `+0x2C0`    | Shield Generator | base + type-specific   | 12 floats: 6 maxShield + 6 chargePerSecond    |
| 3 | `+0x34`              | `+0x2B0`    | Powered Master    | base + type-specific   | 5 property floats                              |
| 4 | `+0x4C`              | `+0x2C8`    | Cloak Device      | base + type-specific   | 1 property float                               |
| 5 | `+0x50`              | `+0x2CC`    | Impulse Engine    | base + type-specific   | 4 property floats                              |
| 6 | `+0x54`              | `+0x2D0`    | Sensor Array      | `base_subsystem_hash`  | none                                          |
| 7 | `+0x5C`              | `+0x2D8`    | Warp Drive        | base + type-specific   | 1 property float                               |
| 8 | `+0x60`              | `+0x2DC`    | Crew / Unknown-A  | `base_subsystem_hash`  | side-effect getter                             |
| 9 | `+0x38`              | `+0x2B4`    | Torpedo System    | `weapon_system_hash`   | children + torpedo types                       |
| 10| `+0x3C`              | `+0x2B8`    | Phaser System     | `weapon_system_hash`   | children                                       |
| 11| `+0x40`              | `+0x2BC`    | Pulse Weapon      | `weapon_system_hash`   | children                                       |
| 12| `+0x58`              | `+0x2D4`    | Tractor Beam      | `weapon_system_hash`   | children                                       |

The Repair subsystem does **not** appear in the hash. The receiver
XOR-folds the incoming 32-bit hash and compares to the local
computation; mismatch fires `ET_BOOT_PLAYER` (`0x008000F6`) which
kicks the player.

In stock content this is mostly a curiosity — the hash check needs
all the player's subsystems initialised correctly on both sides,
which only holds in normal gameplay. Headless implementations that
don't fully populate subsystems can trip this anti-cheat path
inadvertently.

---

## TGMessage routing rules (cross-reference)

A few rules every reimplementation needs to follow:

1. The host MUST relay every game message to every other client,
   regardless of opcode. **Unconditional, opaque, immediate.**
2. The opcode byte MUST NOT be inspected during relay.
3. Unknown opcodes MUST be silently ignored at the C++ layer.
4. Python handlers MUST fire for *every* incoming message, not just
   ones the C++ side recognised — this is how mods register
   handlers for custom types (any value 0–255 is valid).
5. `"NoMe"` and `"Forward"` are routing-only groups. They select
   recipients; they do not filter or validate content.
6. `SendTGMessage(0, msg)` from a client MUST reach the host, which
   MUST relay it to all other clients.
7. No type-byte enforcement beyond the byte width.

Full discussion in `networking/transport-and-sessions.md`.
