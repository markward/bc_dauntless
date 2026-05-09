# Per-Feature Protocols

Detailed wire formats and validation logic for the feature-specific
opcodes that don't fit the bulk-state pattern: `CollisionEffect`
(`0x15`), `SetPhaserLevel` (`0x12`), `DeletePlayerUI` (`0x17`), plus
the CompressedFloat16 precision analysis that matters for the
explosion opcode (`0x29`).

For the broad opcode catalogue and stream primitives, see
`wire-format-and-opcodes.md`. For the polymorphic `TGEvent` factory
system that several of these opcodes use, see `state-and-events.md`.

---

## `CollisionEffect` (opcode `0x15`)

Client → host only. Carries collision event data from the detecting
client to the host. The host validates the report, then applies
authoritative collision damage and broadcasts visual effects.

The server **never relays** `0x15` packets — collision processing
is local on the host, and damage results go out as `PythonEvent`
(`0x06`) messages instead. Verified across 138,695 packets in a
33.5-min stock-dedi trace.

| Item                  | Value                                              |
|-----------------------|----------------------------------------------------|
| Direction             | C → S (only)                                       |
| Handler               | `Handler_CollisionEffect_0x15` at `0x006A2470`     |
| Write method          | `CollisionEvent::WriteToStream` at `0x005871A0` (vtable+0x34) |
| Read method           | `CollisionEvent::ReadFromStream` at `0x00587300` (vtable+0x38) |
| Frequency             | ~84 per 15-min stock session (4th most common combat opcode) |

### Wire format

```
Offset  Size  Type    Field                    Notes
------  ----  ----    -----                    -----
0       1     u8      opcode                   = 0x15
1       4     i32     event_type_class_id      = 0x00008124 (CollisionEvent factory ID)
5       4     i32     event_code               = 0x00800050 (ET_OBJECT_COLLISION)
9       4     i32v    source_object_id         other colliding object (0 = environment / NULL)
13      4     i32v    target_object_id         ship reporting the collision
17      1     u8      contact_count            number of contact points (typically 1–2)
[repeated contact_count times:]
  +0    1     s8      dir_x                    compressed direction X (signed byte)
  +1    1     s8      dir_y                    compressed direction Y
  +2    1     s8      dir_z                    compressed direction Z
  +3    1     u8      magnitude_byte           compressed distance from ship centre
+0      4     f32     collision_force          IEEE 754 impact force magnitude
```

Total: `22 + contact_count * 4` bytes (typically 26 for 1 contact,
30 for 2). All multi-byte values little-endian.

### Constant prefix

The first 13 bytes are the same in every observed CollisionEffect
packet:

```
15  24 81 00 00  50 00 80 00  00 00 00 00
^^  ^^^^^^^^^^^  ^^^^^^^^^^^  ^^^^^^^^^^^
|   class_id     event_code   source = 0 (environment)
opcode 0x15      ET_COLLISION_EFFECT
```

### Contact-point compression

Each contact point is 4 bytes — a "CompressedVec4_Byte" format
representing a ship-relative position.

Write path (`vtable+0xA0` at `0x006D29A0`):

1. **Ship-relative transform.** World-space contact position is
   transformed to ship-local coords:
   - Subtract ship NiNode world position (`NiNode+0x88/8C/90`).
   - Apply inverse rotation (matrix multiply via `FUN_00813AA0`
     with rotation matrix at `NiNode+0x64`).
   - Scale by `DAT_00888860 / NiNode+0x94` (bounding-sphere
     normalisation).
2. **Direction compression.** Compute magnitude = sqrt(x² + y² + z²);
   if above threshold, normalise each component by `(SCALE / magnitude)`,
   convert to signed bytes via `ftol`. Output: 3 signed direction bytes.
3. **Magnitude compression** (`vtable+0xAC` at `0x006D2D10`).
   Divide by reference (bounding radius), multiply by
   `DAT_0088B9AC` (255.0), convert to unsigned byte.

Read path (`vtable+0x9C` at `FUN_006D30E0`):

1. Read 4 bytes (ReadByte × 4).
2. Get bounding-sphere radius from target object (vtable `+0xE4`
   `GetBoundingBox`, radius at `bbox+0x0C`).
3. If target not found: default radius 1.0; if radius is 0: 0.01.
4. `vtable+0xBC` decompresses 4 bytes → `Vec3`.
5. Allocate `Vec3` (12 bytes), store in contact array at
   `event+0x2C`.

### Two serialisation paths

`CollisionEvent` has *two* serialisation formats:

| Path        | Write          | Read           | Format                                        |
|-------------|----------------|----------------|-----------------------------------------------|
| **Network** (vtable `+0x34`/`+0x38`) | `0x005871A0`  | `0x00587300`  | Compressed: u8 count, 4-byte contacts, f32 force |
| **Persistence** (vtable `+0x10`/`+0x14`)| `0x00586FB0` | `0x00587030` | Full: u32 count, 12-byte Vec3 contacts, f32 force, all base TGEvent fields |

**Only the network format appears on the wire.** The persistence
format is for `NiStream` save/load.

### Example packets

**P1** (26 bytes, Sovereign hitting an asteroid in Multi1):

```
15                    opcode = 0x15
24 81 00 00           class_id = 0x00008124
50 00 80 00           event_code = 0x00800050 (ET_COLLISION_EFFECT)
00 00 00 00           source = 0 (environment)
FF FF FF 3F           target = 0x3FFFFFFF (Player 0)
01                    contact_count = 1
0D 7E 00 D9           contact[0]: dir = (+13, +126, +0), mag = 217
BB 20 A0 44           force = 1281.02 (0x44A020BB)
```

**P4** (30 bytes, two contact points):

```
15
24 81 00 00
50 00 80 00
00 00 00 00
FF FF FF 3F
02                    contact_count = 2
0F 7E 00 DA           contact[0]: (+15, +126, +0) mag 218
00 7E FF D8           contact[1]: (+0,  +126, -1) mag 216
51 C3 67 44           force = 927.05 (0x4467C351)
```

### Class layout (`CollisionEvent`, 0x44 bytes)

```
+0x00  vtable_primary    0x0089395C
+0x04  ni_refcount
+0x08  source_object     ptr (resolved from ID)
+0x0C  target_object     ptr (resolved from ID)
+0x10  event_type        0x00800050
+0x14  time_stamp
+0x18  flags_a / flags_b
+0x1C  reserved
+0x20  reserved
+0x24  parent_event
+0x28  vtable_secondary  0x0089399C  (embedded base)
+0x2C  point_array       Vec3** (heap-allocated array of point ptrs)
+0x30  array_capacity    init = 1
+0x34  point_count_alloc number of allocated points
+0x38  num_points        serialised count (GetNumPoints)
+0x3C  (unknown)         init = 1, possibly max_points
+0x40  collision_force   GetCollisionForce
```

Constructor `0x00586D00`:

```
this+0x28 = 0x0089399C   (embedded vtable)
this+0x2C = NiAlloc(4)    (initial capacity 1)
this+0x30 = 1
this+0x34 = 0
this+0x38 = 0
this+0x3C = 1
this+0x40 = 0.0
this[0]   = 0x0089395C    (primary vtable, set last)
```

Destructor `0x00586E20` frees each `Vec3` in the array, then the
array, then calls `FUN_006D5D70` (base destructor).

Python SWIG API:

| Function                                     | C++ target     | Field         |
|----------------------------------------------|----------------|----------------|
| `CollisionEvent_GetNumPoints(event)`          | `this+0x38`     | point count    |
| `CollisionEvent_GetPoint(event, idx)`         | `FUN_00595410`  | copies `Vec3` from array |
| `CollisionEvent_GetCollisionForce(event)`     | `this+0x40`     | float force    |

### Handler logic

```
Handler_CollisionEffect_0x15(TGMessage* msg):
  1. Extract buffer (FUN_006B8530).
  2. Create StreamReader (vtable 0x00895C58); init (buffer+1, size-1).
  3. Deserialize CollisionEvent via FUN_006D6200:
     a. Read class_type_id (u32) = 0x8124
     b. Factory lookup (FUN_006F13E0) → CollisionEvent ctor (0x44 bytes)
     c. Call CollisionEvent::ReadFromStream (vtable+0x38 = 0x00587300)
  4. Resolve object refs (FUN_006F13C0).
  5. Call PostProcess (vtable+0x3C = 0x005874A0).
  6. Clear parent_event (this+0x24 = 0).
  7. Get sender's ship: GetShipFromPlayerID(msg+0x0C) (FUN_006A1AA0).

  VALIDATION 1 — Ownership:
  8. sender_ship MUST equal event.source OR event.target.
     If neither matches → REJECT (free event, return).

  VALIDATION 2 — Self-collision filter:
  9. If sender_ship == event.source:
       target = CastToShipClass(event.target)  (FUN_005AB670)
       if IsLocalPlayerShip(target)            (FUN_005AE140):
         REJECT (prevents double-processing).

  VALIDATION 3 — Distance:
  10. positions  = vtable+0x94 GetWorldTranslation
      bounding   = vtable+0xE4 GetModelBound, radius at +0xC
      gap = distance(s1, s2) - r1 - r2
      if gap >= DAT_008955C8: REJECT (too far apart).

  ACCEPT:
  11. Set event_type = 0x008000FC (ET_HOST_OBJECT_COLLISION).
  12. Post to event queue at DAT_0097F838.
```

The event-type transformation (`0x00800050 → 0x008000FC`) lets the
host's event handlers distinguish *locally-detected* collisions
from *network-reported* ones. The same handler chain
(`ShipClass::HostCollisionEffectHandler`) takes care of both.

### Validation summary

| Check          | Purpose                                         | Anti-abuse                                            |
|----------------|-------------------------------------------------|-------------------------------------------------------|
| Ownership       | Sender must own source or target object         | Prevents spoofing damage to unrelated ships           |
| Self-collision  | Skip if target is local player's ship            | Prevents double-counting when both sides report       |
| Distance        | Objects must be within bounding-sphere proximity | Prevents phantom collisions at range                  |

### Send-side flow

When a client detects a collision locally:

1. Collision detection fires `ET_OBJECT_COLLISION` (`0x00800050`).
2. `ShipClass::CollisionEffectHandler` (`0x005AF9C0`) handles it.
3. The handler calls `CollisionEvent::WriteToStream`
   (vtable `+0x34` = `0x005871A0`):
   - Transform contact points to ship-relative.
   - Compress as CompressedVec4_Byte (4 B per contact).
   - Write `collision_force` as raw `f32`.
4. Wrap in a `TGMessage` with opcode `0x15`, send to host via
   `TGWinsockNetwork`.

### Host-side damage application

After the handler re-posts as `ET_HOST_OBJECT_COLLISION`:

1. `ShipClass::HostCollisionEffectHandler` (`0x005AFAD0`):
   - If multiplayer: create secondary `0x00800053` event for
     effect broadcast.
   - Iterate contact points, transform relative to ship NiNode.
   - **Per-contact damage**:
     ```
     raw = (collisionEnergy / ship.mass) / contactCount
     if raw > 0.01:                       ; dead-zone filter
         scaled = raw * 900.0 + 500.0     ; absolute HP damage
         SubsystemDamageDistributor(ship, dir, &scaled, 1.5, attacker, 1)
     ```
   - Output range: 500.0+ absolute HP (NOT fractional like the
     `DoDamage_CollisionContacts` path described in
     `gameplay/combat-and-damage.md`).
2. `DamageableObject::CollisionEffectHandler` also fires (registered
   for both `0x00800050` and `0x008000FC`).
3. `Effects.CollisionEffect` (Python) creates visual explosions at
   contact points.

### Event registrations

`ShipClass` (registered in `FUN_005AB7C0`):

```
ET_OBJECT_COLLISION       (0x00800050) → ShipClass::CollisionEffectHandler     (0x005AF9C0)
ET_HOST_OBJECT_COLLISION  (0x008000FC) → ShipClass::HostCollisionEffectHandler (0x005AFAD0)
```

`DamageableObject` (registered in `FUN_00590BB0`):

```
ET_OBJECT_COLLISION       (0x00800050) → DamageableObject::CollisionEffectHandler
ET_HOST_OBJECT_COLLISION  (0x008000FC) → DamageableObject::CollisionEffectHandler  (same)
ET_OBJECT_COLLISION       (0x00800050) → "Effects.CollisionEffect" (Python, via FUN_006D92D0)
```

### `CollisionEvent` vtable (`0x0089395C`)

| Offset  | Target       | Name                                |
|---------|--------------|-------------------------------------|
| `+0x00` | `0x00586DF0` | `scalar_deleting_dtor`               |
| `+0x10` | `0x00586FB0` | `WriteStream` (persistence)          |
| `+0x14` | `0x00587030` | `ReadStream`  (persistence)          |
| `+0x24` | `0x00586DC0` | `GetClassName` → `"CollisionEvent"`  |
| `+0x30` | `0x00586E70` | `CopyFrom`                           |
| `+0x34` | `0x005871A0` | **`WriteToStream` (network, compressed)** |
| `+0x38` | `0x00587300` | **`ReadFromStream` (network, compressed)** |
| `+0x3C` | `0x005874A0` | `PostProcess` / `ResolveLinks`       |

---

## `SetPhaserLevel` (opcode `0x12`)

Carries the phaser-intensity (LOW / MED / HIGH) toggle from the
originating player to all other peers — **not** the engineering
power-distribution sliders, which use a different mechanism (the
`StateUpdate` flag-`0x20` round-robin, with no dedicated opcode).

| Item                  | Value                                              |
|-----------------------|----------------------------------------------------|
| Direction             | Bidirectional (any peer → all others, host relays) |
| Sender thunk          | `MultiplayerGame::SetPhaserLevelHandler` at `0x006A1970` |
| Serialiser            | `SendEventMessage` at `0x006A17C0`                  |
| Receiver              | `FUN_0069FDA0` (generic event-forward)              |
| Applier               | `PhaserSystem::SetPhaserLevelHandler` at `0x00574180`|
| Frequency             | ~33 per 15-min stock session                       |

### Wire format

```
Offset  Size  Type    Field                Notes
------  ----  ----    -----                -----
0       1     u8      opcode               = 0x12
1       4     i32     factory_id           = 0x00000105 (TGCharEvent)
5       4     i32     event_type           = 0x008000E0 (ET_SET_PHASER_LEVEL)
9       4     i32     source_object_ref    Object ID of the ship (or 0)
13      4     i32     target_object_ref    Related ref (-1 sentinel, 0 NULL)
17      1     u8      phaser_level         0 = LOW, 1 = MED, 2 = HIGH
```

Total: 18 bytes (fixed). Multi-byte LE.

### Phaser-level values

| Value | Constant     | Python API                   | Effect                                  |
|-------|--------------|------------------------------|-----------------------------------------|
| 0     | `PP_LOW`      | `App.PhaserSystem.PP_LOW`    | Less damage, lower power draw           |
| 1     | `PP_MEDIUM`   | `App.PhaserSystem.PP_MEDIUM` | Balanced                                |
| 2     | `PP_HIGH`     | `App.PhaserSystem.PP_HIGH`   | More damage, higher power draw          |

Stored as a single byte on the wire (`event+0x28`) and as `int` in
the `PhaserSystem` object (`PhaserSystem+0xF0`).

### Example wire (HIGH, Player 0)

```
12                    opcode = 0x12
05 01 00 00           factory_id = 0x00000105 (TGCharEvent)
E0 00 80 00           event_type = 0x008000E0 (ET_SET_PHASER_LEVEL)
FF FF FF 3F           source = 0x3FFFFFFF (Player 0 ship)
00 00 00 00           target = NULL
02                    phaser_level = 2 (PP_HIGH)
```

### Sender flow

`PhaserSystem::SetPowerLevel` (`0x00574200`) — local action when
the player toggles intensity:

```
SetPowerLevel(int level):
  1. Allocate TGCharEvent (NiAlloc 0x2C bytes).
  2. TGCharEvent::ctor (FUN_00574C20).
  3. event+0x28 = (byte) level.
  4. SetSource(event, this PhaserSystem).
  5. event+0x10 = 0x008000E0.
  6. PostEvent.
  7. Loop child subsystems (this+0x1C count):
     a. GetChildSubsystem(i)               (FUN_0056C570)
     b. dynamic_cast<EnergyWeapon*>(child) (FUN_00570B20)
     c. If cast succeeds: child->SetPowerSetting(level)  (vtable+0x90)
  8. PhaserSystem+0xF0 = level.
```

The sender immediately applies the level locally; step 6 triggers
the MultiplayerGame thunk for network forwarding.

`MultiplayerGame::SetPhaserLevelHandler` (`0x006A1970`) — MP bridge:

```
SetPhaserLevelHandler(TGCharEvent* event):
  1. If event->source == NULL: return.
  2. If event->source->objectID != localPlayerObjectID: return.
       (Only forward OUR events — prevents echoing received events.)
  3. SendEventMessage(event, 0x12).
```

`SendEventMessage` (`0x006A17C0`):

```
1. Store opcode byte (0x12) in local 1023-byte buffer.
2. Create TGBufferStream wrapping the buffer.
3. event->WriteToStream(stream)              # vtable+0x34
4. Get position (bytes written).
5. Allocate TGMessage (NiAlloc 0x40 bytes).
6. Copy [opcode][stream_data] into message (position + 1 bytes).
7. msg+0x3A = 1                               # reliable
8. If multiplayer: SendTGMessageToGroup("NoMe").
   Else:           SendTGMessage to host peer.
```

### Receiver flow

The MultiplayerGame dispatcher reads opcode `0x12`, subtracts 2 to
get jump-table index 16, and lands on the entry shared with `0x0B`,
`0x0C`, `0x11`:

```asm
push  0x0              ; event-type override = 0 (preserve original)
push  esi              ; TGMessage*
call  FUN_0069FDA0     ; generic event forward
```

`override = 0` — the event keeps its original type `0x008000E0`.
There is no sender/receiver code pairing for this event.

`FUN_0069FDA0` (generic event-forward, shared with opcodes
`0x07`–`0x12`, `0x1B`):

```
1. If multiplayer: relay (forward to "Forward" group):
     a. Clone/extract message data.
     b. Look up "Forward" group in WSN+0xF4.
     c. Remove sender from group (prevent echo).
     d. Forward to all remaining group members.
     e. Re-add sender.
2. If sender != self: dispatch locally:
     a. Extract message buffer (FUN_006B8530).
     b. Create TGBufferStream from buffer + 1.
     c. ReadObjectFromStream (FUN_006D6200):
          - Read factory_id (0x105) → TGCharEvent factory
          - Allocate TGCharEvent (0x2C bytes)
          - TGCharEvent::ReadFromStream (vtable+0x38)
     d. Resolve object refs.
     e. Clear event+0x24.
     f. If override != 0: event+0x10 = override.  (For 0x12: override = 0.)
     g. PostEvent (FUN_006DA300).
```

`PhaserSystem::SetPhaserLevelHandler` (`0x00574180`) — applier on
the receiving side:

```
1. Read event+0x28 as signed byte → sign-extend to int.
2. Store into PhaserSystem+0xF0.
3. Release event (FUN_006D90E0).
```

**Critical asymmetry**: the receiver does *not* call
`SetPowerSetting()` on child `EnergyWeapon` subsystems — it only
stores the level value at `+0xF0`. The actual intensity change on
remote machines propagates separately, either through
`PhaserSystem::Update()` reading `+0xF0` each tick, or through
individual weapon-intensity values carried in `StateUpdate` (opcode
`0x1C`) round-robin.

### Event registrations

`PhaserSystem` (in `FUN_00573DE0` + `FUN_00573E40`):

```
Handler:    PhaserSystem::SetPhaserLevelHandler (0x00574180)
Trigger:    ET_SET_PHASER_LEVEL (0x008000E0)
Registered: FUN_006D92B0 with name "PhaserSystem::SetPhaserLevelHandler"
```

`MultiplayerGame` (in ctor `0x0069E590`):

```
Handler:    MultiplayerGame::SetPhaserLevelHandler thunk (0x006A1970)
Trigger:    ET_SET_PHASER_LEVEL (0x008000E0)
Registered: FUN_006DB380 with name "MultiplayerGame::__SetPhaserLevelHandler"
Flags:      priority = 1, enabled = 1
```

Both fire for the same event type. On the **sender**, both run —
the MP handler serialises and sends, the PhaserSystem handler
applies locally. On the **receiver**, only the PhaserSystem handler
runs because the MP handler's gate check rejects events from
non-local sources.

### Shared opcode table (full pairing, for reference)

`SetPhaserLevel` is part of the `0x07`–`0x12`/`0x1B` family that
all share `FUN_0069FDA0`:

| Opcode | Name              | Override? | Override code |
|--------|-------------------|-----------|---------------|
| `0x07` | StartFiring       | Yes       | `0x008000D7`  |
| `0x08` | StopFiring        | Yes       | `0x008000D9`  |
| `0x09` | StopFiringAtTarget| Yes       | `0x008000DB`  |
| `0x0A` | SubsysStatusChanged| Yes      | `0x0080006C`  |
| `0x0B` | AddToRepairList   | No        | `0`           |
| `0x0C` | ClientEvent       | No        | `0`           |
| `0x0E` | StartCloak        | Yes       | `0x008000E3`  |
| `0x0F` | StopCloak         | Yes       | `0x008000E5`  |
| `0x10` | StartWarp         | Yes       | `0x008000ED`  |
| `0x11` | RepairListPriority| No        | `0`           |
| **`0x12`** | **SetPhaserLevel** | **No** | **`0`**     |
| `0x1B` | TorpedoTypeChange | Yes       | `0x008000FD`  |

Opcodes with `override = 0` use the event's wire type. Opcodes with
an override replace the deserialised event's type before posting
locally — this is how the sender/receiver event-code pairing
described in `state-and-events.md` works.

---

## `DeletePlayerUI` (opcode `0x17`)

Generic player-list-update event transport. Despite the name, it
carries **both** player-add events (at join time) and player-remove
events (at disconnect time).

The handler at `FUN_006A1360` deserialises a `TGEvent` from the
wire using the factory system (`FUN_006D6200`) and posts it to the
global event manager. The engine's `NewPlayerInGameHandler` at
`0x006A1590` (registered for `ET_NEW_PLAYER_IN_GAME` /
`0x008000F1`) processes the event and adds the player to the
internal `TGPlayerList`.

### Wire format

```
Offset  Size  Type     Field           Notes
------  ----  ----     -----           -----
0       1     u8       opcode          = 0x17
1       4     u32le    factory_id      = 0x00000866 (base TGEvent class)
5       4     u32le    event_code      see "Event codes" below
9       4     u32le    src_obj_id      typically 0x00000000
13      4     u32le    tgt_obj_id      ship or player object ID
17      1     u8       wire_peer_id    1-based wire peer slot
```

Total: 18 bytes (1 opcode + 17 payload).

### Factory ID

`0x00000866` identifies the base `TGEvent` class. The handler calls
`FUN_006D6200` (TGStreamedObject factory deserializer) which looks
up class ID `0x866` and constructs a `TGEvent` from the stream.
This is the same factory system `PythonEvent` (`0x06`) uses — see
`state-and-events.md`.

### Event codes

| Context           | Event code   | Constant                       | Effect                                |
|-------------------|--------------|--------------------------------|---------------------------------------|
| Player join       | `0x008000F1` | `ET_NEW_PLAYER_IN_GAME`        | Adds player to `TGPlayerList`         |
| Player disconnect | `0x00060005` | `ET_NETWORK_DELETE_PLAYER`     | Removes player from `TGPlayerList`    |

### Field values by context

**Join time** (sent alongside `MISSION_INIT_MESSAGE` (`0x35`) after
`NewPlayerInGame` (`0x2A`)):

```
factory_id    = 0x00000866
event_code    = 0x008000F1
src_obj_id    = 0x00000000
tgt_obj_id    = (varies — ship/player object ID)
wire_peer_id  = joining player's wire peer slot
```

**Disconnect time** (sent to remaining clients when a player
leaves):

```
factory_id    = 0x00000866
event_code    = 0x00060005
src_obj_id    = 0x00000000
tgt_obj_id    = disconnecting player's object ID
wire_peer_id  = disconnecting player's wire peer slot
```

### Stock trace example (join time, packet #25 in self-destruct test)

S → C, sent after `NewPlayerInGame` (`0x2A`) and alongside
`MISSION_INIT` (`0x35`):

```
17 66 08 00 00 F1 00 80 00 00 00 00 00 4F 06 00 00 02
```

Decoded:

| Bytes        | Field          | Value                                |
|--------------|----------------|---------------------------------------|
| `17`         | opcode         | `0x17` (DeletePlayerUI)               |
| `66 08 00 00`| factory_id     | `0x00000866` (TGEvent)                |
| `F1 00 80 00`| event_code     | `0x008000F1` (`ET_NEW_PLAYER_IN_GAME`)|
| `00 00 00 00`| src_obj_id     | `0x00000000` (no source)              |
| `4F 06 00 00`| tgt_obj_id     | `0x0000064F` (session-specific)       |
| `02`         | wire_peer_id   | 2 (joining client)                    |

### Trace frequency (verified)

| Trace                                    | `0x17` count | Context                                |
|------------------------------------------|--------------|----------------------------------------|
| Stock dedi self-destruct test            | 1            | Join time (player 2 joins)             |
| Battle of Valentine's Day (33.5 min)     | 6            | All at join time (3 players, slot reuse)|
| Stock dedi 91-second session             | 1            | Join time                              |

**Zero** `0x17` instances observed at disconnect time across
available traces — disconnect cleanup may use it (the C++
`DeletePlayerHandler` at `FUN_006A0CA0` sends it), but the captured
sessions didn't include a disconnect with remaining clients to
observe.

### Handler chain

#### Sending (server side)

- **At join time**: server processes `NewPlayerInGame` (`0x2A`),
  constructs a `TGEvent` with `ET_NEW_PLAYER_IN_GAME`, serialises,
  sends alongside `MISSION_INIT` (`0x35`).
- **At disconnect time**: C++ `DeletePlayerHandler` (`FUN_006A0CA0`,
  registered for `ET_NETWORK_DELETE_PLAYER`) sends `0x17` to
  remaining clients as part of the disconnect cleanup cascade
  (along with `0x14 DestroyObject` and `0x18 DeletePlayerAnim`).

#### Receiving (client side)

```
FUN_006A1360 (opcode 0x17 handler)
  ├── FUN_006D6200(stream)              — TGStreamedObject factory deserialise
  │     └── Look up factory_id (0x866)  — Construct TGEvent from stream
  │     └── Read event_code, src_obj_id, tgt_obj_id, wire_peer_id
  │
  ├── FUN_006DA2A0(eventMgr, event)     — Post event to global event manager
  │
  └── Event dispatched:
        ├── [if ET_NEW_PLAYER_IN_GAME (0x008000F1)]
        │     └── NewPlayerInGameHandler (0x006A1590)
        │           └── Adds player to TGPlayerList
        │
        └── [if ET_NETWORK_DELETE_PLAYER (0x00060005)]
              └── DeletePlayerHandler (0x006A0CA0)
                    ├── Removes player from TGPlayerList
                    └── Python RebuildPlayerList()
```

### Scoreboard population (subtle gotcha)

The client's scoreboard (`Mission1Menus.RebuildPlayerList`) requires
**both** of these to display a player:

1. **`TGPlayerList` entry** — populated by `0x17` carrying
   `ET_NEW_PLAYER_IN_GAME`.
2. **Score-dictionary entry** — populated by `SCORE_MESSAGE`
   (`0x37`) or `SCORE_CHANGE` (`0x36`).

```python
# Mission1Menus.py line 267
if (pDict.has_key(pPlayer.GetNetID()) and pPlayer.IsDisconnected() == 0):
```

Missing either keeps the player off the scoreboard:

- Missing `0x17` → `TGPlayerList` empty → no players to iterate.
- Missing `0x37`/`0x36` → dictionary empty → players filtered out.

On a fresh server with no kills, a new joiner won't see themselves
on the scoreboard until the first kill or death triggers a
`SCORE_CHANGE`. **Stock behaviour, not a bug.**

### Naming clarification

The opcode is fundamentally a `TGEvent` transport — the same handler
processes both join and disconnect events. The "DeletePlayerUI" name
reflects its role in the disconnect flow (where it was first
identified). A more accurate name would be `PlayerListEvent` or
`PlayerEvent`.

---

## CompressedFloat16 (CF16) and explosion encoding

The `Explosion` opcode (`0x29`) carries both `radius` and `damage`
as CF16 (16-bit floats with logarithmic scaling). This section
documents the encoding precisely and analyses what it means for
mod compatibility — particularly the BC Remastered convention of
using specific damage values as weapon-type identifiers.

### CF16 constants (`.rdata`)

| Symbol     | Address       | Hex bytes      | Float        | Purpose                                  |
|------------|---------------|----------------|--------------|------------------------------------------|
| `BASE`     | `DAT_00888B4C`| `6F 12 83 3A`  | `0.001`       | First scale boundary                      |
| `ZERO`     | `DAT_00888B54`| `00 00 00 00`  | `0.0`         | Negative check / range_lo for scale 0     |
| `MULT`     | `DAT_0088C548`| `00 00 20 41`  | `10.0`        | Scale multiplier                          |
| `ENC_MULT` | `DAT_00895F50`| `00 F0 7F 45`  | `4095.0`      | Encoder mantissa multiplier               |
| `DEC_MULT` | `DAT_00895F54`| `01 08 80 39`  | `1/4095`      | Decoder mantissa divisor                  |

### Wire format

```
[sign:1] [scale:3] [mantissa:12]   = 16 bits
```

- `sign` (bit 15): 0 = positive, 1 = negative.
- `scale` (bits 14–12): 3-bit index, 0–7.
- `mantissa` (bits 11–0): 12-bit value within the selected range,
  0–4095.

### Scale table

| Scale | Range low | Range high | Step size  | Notes               |
|-------|-----------|------------|------------|---------------------|
| 0     | 0.0       | 0.001      | 2.44e-7    | Sub-thousandths     |
| 1     | 0.001     | 0.01       | 2.20e-6    | Thousandths         |
| 2     | 0.01      | 0.1        | 2.20e-5    | Hundredths          |
| 3     | 0.1       | 1.0        | 2.20e-4    | Fractions           |
| 4     | 1.0       | 10.0       | 2.20e-3    | Single digits       |
| 5     | 10.0      | 100.0      | 2.20e-2    | Tens                |
| 6     | 100.0     | 1000.0     | 2.20e-1    | Hundreds            |
| 7     | 1000.0    | 10000.0    | 2.20       | Thousands           |

Each scale covers one decimal order of magnitude; the 4096 mantissa
values divide each range into equal steps.

### Encoder (`FUN_006D3A90`)

```c
uint16_t CF16_Encode(float value) {
    bool negative = (value < 0.0f);
    if (negative) value = -value;

    uint32_t scale = 0;
    float boundary = BASE;
    float prev_boundary = ZERO;

    while (scale < 8) {
        if (value < boundary) {
            int mantissa = (int)((value - prev_boundary)
                                / (boundary - prev_boundary)
                                * 4095.0f);
            break;
        }
        prev_boundary = boundary;
        boundary *= MULT;          // *= 10.0
        scale++;
    }

    if (scale == 8) {              // overflow
        mantissa = 0xFFF;
        scale    = 7;
    }

    if (negative) scale |= 0x8;
    return (uint16_t)((scale << 12) | mantissa);
}
```

**Truncation, not rounding.** The encoder uses x87 `__ftol`, so the
encoded value is always `<=` the original within its bin.

### Decoder (`FUN_006D3B30`)

```c
float CF16_Decode(uint16_t encoded) {
    uint32_t mantissa     = encoded & 0xFFF;
    uint8_t  scale_nibble = (encoded >> 12) & 0xF;

    bool negative = (scale_nibble & 0x8) != 0;
    if (negative) scale_nibble &= 0x7;

    float range_lo = 0.0f;
    float range_hi = 0.001f;
    for (int i = 0; i < scale_nibble; i++) {
        range_lo = range_hi;
        range_hi = range_lo * 10.0f;
    }

    float result = (range_hi - range_lo) * (float)mantissa
                 * (1.0f/4095.0f) + range_lo;

    if (negative) result = -result;
    return result;
}
```

The decoder uses `1.0f/4095.0f` (constant at `0x00895F54`), **not
`1/4096`**. Mantissa 4095 decodes to exactly the top of the range.

### Explosion (`0x29`) wire format

```
[byte:0x29]
[u32le: object_id]                 ; target ship
[CompressedVector4: position]      ; 5 bytes (3 dir + CF16 magnitude) or 7 bytes
[u16: radius]                      ; CF16
[u16: damage]                      ; CF16
```

Sender (`FUN_00595C60`): iterates the explosion list at
`this+0x13C`, reads radius from explosion struct `+0x14`, damage
from `+0x1C`. Called from `FUN_006A02A0` (`RequestObj`) and
`Handler_NewPlayerInGame_0x2A`.

Receiver (`Handler_Explosion_0x29` at `0x006A0080`): decodes
position then two CF16s, allocates an `ExplosionDamage` struct
(`+0x14 = radius`, `+0x18 = radius²` precomputed, `+0x1C = damage`),
calls `ProcessDamage`.

### Mod compatibility — BC Remastered weapon-type IDs

BC Remastered uses specific damage float values as weapon-type
identifiers: **15.0**, **25.0**, **273.0**, **2063.0**.

Round-trip through CF16:

| Original | Encoded | Scale | Mantissa | Decoded   | Error  | Rel error |
|----------|---------|-------|----------|-----------|--------|-----------|
| 15.0     | `0x50E3`| 5     | 227      | 14.989012 | 0.011  | 0.073 %   |
| 25.0     | `0x52AA`| 5     | 682      | 24.989013 | 0.011  | 0.044 %   |
| 273.0    | `0x6313`| 6     | 787      | 272.967056| 0.033  | 0.012 %   |
| 2063.0   | `0x71E3`| 7     | 483      | 2061.538623| 1.461 | 0.071 %   |

All four values produce **unique** uint16 encodings — no collisions.
However, the *decoded* values are not equal to the originals.

`round(decoded) == original` works for **3 of 4** values:

| Value  | round(decoded) | Matches? |
|--------|----------------|----------|
| 15.0   | 15             | YES      |
| 25.0   | 25             | YES      |
| 273.0  | 273            | YES      |
| 2063.0 | **2062**       | **NO**   |

`2063.0` fails because at scale 7 the step size is ~2.198 — `2062`
and `2063` map to the same mantissa (483), and the decoded value
2061.54 rounds to 2062, not 2063.

### Integer collisions at scale 7

```
mantissa 482  →  integers 2060, 2061  →  decoded 2059.34
mantissa 483  →  integers 2062, 2063  →  decoded 2061.54   ← collision pair
mantissa 484  →  integers 2064, 2065  →  decoded 2063.74
```

### Recommended matching strategies

#### 1 — Tolerance window (recommended)

```python
def identify_weapon_type(decoded_damage):
    targets = {15.0: "type_A", 25.0: "type_B",
               273.0: "type_C", 2063.0: "type_D"}
    for target, name in targets.items():
        if abs(decoded_damage - target) < 1.5:
            return name
    return "unknown"
```

A tolerance of 1.5 covers all four values. Minimum inter-value
distance is 10.0 (between 15.0 and 25.0), so no overlap risk.

#### 2 — Encode target and compare uint16 (exact)

```python
EXPECTED = {0x50E3: "type_A", 0x52AA: "type_B",
            0x6313: "type_C", 0x71E3: "type_D"}

def identify_weapon_type(received_cf16_uint16):
    return EXPECTED.get(received_cf16_uint16, "unknown")
```

Perfectly reliable but requires the raw `uint16` before decoding —
only available via C-level hooks, not from Python.

#### 3 — Range-based matching

```python
def identify_weapon_type(decoded_damage):
    if 14.0 < decoded_damage < 16.0: return "type_A"
    if 24.0 < decoded_damage < 26.0: return "type_B"
    if 272.0 < decoded_damage < 274.0: return "type_C"
    if 2060.0 < decoded_damage < 2064.0: return "type_D"
    return "unknown"
```

### Extended precision reference

| Value  | Encoded | Decoded   | round() | Match? |
|--------|---------|-----------|---------|--------|
| 0.5    | `0x371B`| 0.4998    | 0       | YES    |
| 1.0    | `0x3FFE`| 0.9998    | 1       | YES    |
| 5.0    | `0x471B`| 4.9978    | 5       | YES    |
| 10.0   | `0x4FFE`| 9.9978    | 10      | YES    |
| 15.0   | `0x50E3`| 14.9890   | 15      | YES    |
| 25.0   | `0x52AA`| 24.9890   | 25      | YES    |
| 100.0  | `0x5FFE`| 99.9780   | 100     | YES    |
| 273.0  | `0x6313`| 272.967   | 273     | YES    |
| 1000.0 | `0x6FFE`| 999.780   | 1000    | YES    |
| 1500.0 | `0x70E3`| 1498.90   | 1499    | **NO** |
| 2000.0 | `0x71C6`| 1997.80   | 1998    | **NO** |
| 2063.0 | `0x71E3`| 2061.54   | 2062    | **NO** |
| 5000.0 | `0x771B`| 4997.80   | 4998    | **NO** |
| 9999.0 | `0x7FFE`| 9997.80   | 9998    | **NO** |

**General rule**: `round(decoded) == original` is reliable below
~1000. Above 1000 (scale 7), the ~2.2 step size causes frequent
mismatch. Mods picking new weapon-type IDs in scale 7 should space
them at least **3 apart**.
