# Wire Format and Opcodes

The bottom-of-stack protocol reference for `stbc.exe`: the
`TGBufferStream` primitives, the compressed numeric formats, the
seven transport-message types, and the complete game-opcode
catalogue (NetFile checksums + game opcodes + multiplayer-window
opcodes).

For higher-level state replication and event transport, see
`state-and-events.md`. For the smaller per-feature wire formats
(collision-effect, set-phaser-level, delete-player-ui,
cf16-explosion encoding), see `per-feature-protocols.md`. For
session lifecycle, AlbyRules! cipher, and GameSpy, see
`networking/transport-and-sessions.md`.

---

## TGBufferStream primitives

Stream layout:

| Offset  | Field                                                            |
|---------|------------------------------------------------------------------|
| `+0x00` | vtable pointer (`PTR_LAB_00895C58` for the derived reader)       |
| `+0x04` | error-code pointer                                                |
| `+0x1C` | buffer pointer                                                    |
| `+0x20` | buffer capacity                                                   |
| `+0x24` | current write/read position                                       |
| `+0x28` | bit-packing bookmark position                                     |
| `+0x2C` | bit-packing state (0 = no active bit group, >0 = current mask)   |

### Write functions (server → wire)

| Function       | Type        | Size       | Notes                                       |
|----------------|-------------|------------|---------------------------------------------|
| `FUN_006CF730` | `WriteByte` | 1 byte     | `uint8`                                     |
| `FUN_006CF770` | `WriteBit`  | 0–1 bytes  | Packs into shared byte (see "Bit packing")  |
| `FUN_006CF7F0` | `WriteShort`| 2 bytes    | `uint16` little-endian                      |
| `FUN_006CF870` | `WriteInt32`| 4 bytes    | `int32` / `uint32`                          |
| `FUN_006CF8B0` | `WriteFloat`| 4 bytes    | IEEE 754 single-precision                   |
| `FUN_006CF2B0` | `WriteBytes`| N bytes    | Raw `memcpy`                                |
| `FUN_006CF460` | `WriteCString`| 2+N bytes| `[u16 strlen][raw chars, no null]`         |
| `FUN_006CF9B0` | `GetPosition`| —          | Returns current stream position             |

### Read functions (wire → client)

| Function       | Type       | Size       | Notes                                  |
|----------------|------------|------------|----------------------------------------|
| `FUN_006CF540` | `ReadByte` | 1 byte     | `uint8`                                |
| `FUN_006CF580` | `ReadBit`  | 0–1 bytes  | Packed boolean                         |
| `FUN_006CF600` | `ReadShort`| 2 bytes    | `uint16` little-endian                 |
| `FUN_006CF670` | `ReadInt32`| 4 bytes    | `int32` / `uint32`                     |
| `FUN_006CF6B0` | `ReadFloat`| 4 bytes    | IEEE 754                               |
| `FUN_006CF6A0` | `ReadInt32v`| 4 bytes   | Read via vtable (variant)              |
| `FUN_006CF230` | `ReadBytes`| N bytes    | Raw memcpy                             |

All multi-byte numeric writes are **little-endian** (native x86
store).

### Bit packing

`WriteBit` / `ReadBit` use a compact format that packs up to 5
booleans per byte:

```
Byte layout:   [count:3][bits:5]
               MSB                LSB
count (bits 7-5): number of bits packed (1–5)
bits  (bits 4-0): the boolean values, one per bit position
```

State machine:

- First `WriteBit` allocates a new byte at the current position,
  sets bit 0, count = 1.
- Subsequent calls OR the value into the next bit position and
  increment the count.
- After 5 bits the byte is full; the next `WriteBit` starts a new
  byte.
- `+0x2C` on the stream tracks "mid-pack" (non-zero = currently
  packing).

Reads consume bits in order; when all packed bits in the current
byte are consumed, the next `ReadBit` starts a fresh byte.

---

## Compressed numeric formats

### CompressedFloat16 (CF16)

Logarithmic-scale 16-bit float. Used for speeds, damage amounts,
distances. Constants in `.rdata`:

| Address     | Constant         | Float value                    |
|-------------|------------------|--------------------------------|
| `0x00888B4C`| `BASE`           | `0.001` (`3A83126F`)           |
| `0x0088C548`| `MULT`           | `10.0` (`41200000`)            |
| `0x00895F50`| `ENC_SCALE`      | `4095.0` (encoder mantissa)    |
| `0x00895F54`| `DEC_SCALE`      | `1/4095 ≈ 0.000244200258` (decoder inverse) |

#### Encoding (`FUN_006D3A90`)

Format: `[sign:1][scale:3][mantissa:12]` — bit 15 = sign,
bits 14–12 = scale exponent (0–7), bits 11–0 = mantissa (0–4095).

```
1. If value < 0: set sign bit, negate.
2. Find scale (0–7) such that value < BASE * MULT^scale.
   Scale 0 = [0, 0.001),  Scale 1 = [0.001, 0.01),  …,  Scale 7 = [1000, 10000).
3. frac     = (value - range_lo) / (range_hi - range_lo)
4. mantissa = ftol(frac * 4095.0)            ; truncate toward zero
5. If scale overflows (>= 8): clamp to scale=7, mantissa=0xFFF.
6. Result = ((sign << 3) | scale) << 12 | mantissa
```

#### Decoding (`FUN_006D3B30`)

```
1. mantissa = encoded & 0xFFF
2. sign     = (encoded >> 15) & 1
3. scale    = (encoded >> 12) & 0x7
4. lo, hi = 0, BASE
   for i in 0..scale: lo, hi = hi, lo * MULT
5. result   = (hi - lo) * mantissa * (1/4095) + lo
6. if sign: result = -result
```

8 logarithmic decades from 0 to 10000, 4096 levels per decade
(~0.022 % relative precision per level). The decoder uses `1/4095`,
not `1/4096`, so mantissa `4095` decodes to exactly the top of the
range. Encoding is **lossy** — values always round down.

### CompressedVector3

Used for position deltas, velocity components.

```
Algorithm (FUN_006D2AD0 — write):
    magnitude = sqrt(dx² + dy² + dz²)
    if magnitude <= eps: magnitude = 0
    dirX = ftol(dx / magnitude * scale)        ; normalised → byte
    dirY = ftol(dy / magnitude * scale)
    dirZ = ftol(dz / magnitude * scale)
    magnitude_compressed = CF16(magnitude)

Wire (5 bytes total):
    [dirX:u8][dirY:u8][dirZ:u8][magnitude:u16]
```

`FUN_006D2EB0` is the read path (3 dir bytes + magnitude
decompression).

### CompressedVector4

Used for position+rotation, position+scale.

`param4 == 0` → 4th component is `float32`. `param4 != 0` → 4th
component is `uint16` (CF16-encoded).

```
Wire (param4 = 1): [dirX:u8][dirY:u8][dirZ:u8][magnitude:u16]   = 5 bytes
Wire (param4 = 0): [dirX:u8][dirY:u8][dirZ:u8][magnitude:f32]   = 7 bytes
```

`FUN_006D2F10` writes; `FUN_006D2FD0` reads.

---

## Transport layer

UDP only. AlbyRules! cipher operates on bytes from offset 1 onward
(byte 0 — direction flag — is unencrypted). After decryption, every
datagram has the framing:

```
Offset  Size  Field
------  ----  -----
0       1     peer_id        (0x01 = server, 0x02 = first client, 0xFF = unassigned/init)
1       1     msg_count      (number of transport messages in this packet)
2+      var   messages       (sequence of self-describing transport messages)
```

`ProcessIncomingPackets` (`FUN_006B5C90`) reads `peer_id` from byte
0, `msg_count` from byte 1, then loops `msg_count` times — for each
sub-message it reads a type byte and dispatches through the factory
table at `DAT_009962D4` (indexed by `type * 4`).

### Transport message types (factory table)

| Type   | Class                  | Factory       | Constructor   | Vtable        | Registration   |
|--------|------------------------|---------------|---------------|---------------|----------------|
| `0x00` | `TGDataMessage`        | `FUN_006BC6A0`| `FUN_006BC5B0`| `0x0089598C`  | `FUN_006BC5A0` |
| `0x01` | `TGHeaderMessage` (ACK)| `FUN_006BD1F0`| `FUN_006BD120`| `0x008959AC`  | `FUN_006BD110` |
| `0x02` | `TGConnectMessage`     | `FUN_006BDD10`| `FUN_006BDC40`| `0x008959CC`  | `FUN_006BDC30` |
| `0x03` | `TGConnectAckMessage`  | `FUN_006BE860`| `FUN_006BE730`| `0x008959EC`  | `FUN_006BE720` |
| `0x04` | `TGBootMessage`        | `FUN_006BADB0`| `FUN_006BAC70`| `0x0089596C`  | `FUN_006BAC60` |
| `0x05` | `TGDisconnectMessage`  | `FUN_006BF410`| `FUN_006BF2E0`| `0x00895A0C`  | `FUN_006BF2D0` |
| `0x32` | `TGMessage` (base)     | `FUN_006B83F0`| `FUN_006B82A0`| `0x008958D0`  | `FUN_006B8290` |

**`0x32` is the workhorse** — every game-layer payload is wrapped in
a type-0x32 transport message. Types `0x00`–`0x05` handle the
connection lifecycle.

### Wire formats

#### Type `0x32` — data (game payloads)

```
Offset  Size  Field
------  ----  -----
0       1     type           = 0x32
1       2     flags_len      LE uint16 (see bit layout below)
[if reliable:]
3       2     seq_num        LE uint16 reliable sequence number
[if fragmented:]
+0      1     frag_idx       Fragment index (0-based)
[if frag_idx == 0:]
+1      1     total_frags    Total number of fragments
+N      var   payload        Game opcode + data
```

`flags_len` bit layout (LE uint16):

```
bits 12-0  (0x1FFF): total message size including the 0x32 type byte
bit 13     (0x2000): is_fragment — fragment metadata follows seq_num
bit 14     (0x4000): ordered (priority delivery)
bit 15     (0x8000): reliable (ACK required, has seq_num)
```

Common high bytes you'll see in traces (just the high byte of the
uint16):

| `flags_hi` | Meaning                                                  |
|------------|----------------------------------------------------------|
| `0x80`     | reliable, no fragment, length bits 12–8 = 0              |
| `0x81`     | reliable, no fragment, length bit 8 set                  |
| `0xA0`     | reliable + fragment, length bits 12–8 = 0                |
| `0xA1`     | reliable + fragment, length bit 8 set                    |
| `0x00`     | unreliable, no fragment                                  |

There is **no "more fragments" bit** — the receiver detects the
last fragment by checking that all indices `0..total_frags-1` have
arrived. Fragment 0 always carries the `total_frags` count.

Old documentation sometimes mislabels `flags_hi & 0x01` as a "more
fragments" flag. That's bit 8 of the 13-bit length, **not** a
fragment marker.

#### Type `0x00` — control data (small, no fragments)

```
Offset  Size  Field
------  ----  -----
0       1     type           = 0x00
1       2     flags_len      LE uint16 (14-bit length, see below)
[if reliable:]
3       2     seq_num        LE uint16
+N      var   payload
```

`flags_len` for type `0x00`:

```
bits 13-0  (0x3FFF): total message size (14-bit, max 16383)
bit 14     (0x4000): ordered
bit 15     (0x8000): reliable
                 (NO fragment bit — type 0x00 doesn't fragment)
```

`FUN_006BC610` serialises; `FUN_006BC6A0` deserialises.

#### Type `0x01` — ACK / header

```
Offset  Size  Field
------  ----  -----
0       1     type           = 0x01
1       2     seq_num        LE uint16 sequence being ACKed
3       1     flags          bit 0 = is_fragment, bit 1 = is_below_0x32
[if is_fragment:]
4       1     frag_idx       Fragment index of the ACKed message
```

4 bytes for a normal ACK, 5 bytes for a fragment ACK.

#### Types `0x02`–`0x05` — connection management

Each uses a derived class with its own serialiser. Wire format is
`[type:1][type-specific data]`.

### Fragmentation

`FragmentMessage` (vtable slot 7, `FUN_006B8720`):

1. If the message fits in `max_size`, return a 1-element array
   (no fragmentation).
2. If too large, force `reliable = 1` on the message.
3. Create clones via `Clone` (vtable slot 6, `FUN_006B8610`):
   - `+0x3C = 1` (`is_fragment`)
   - `+0x39 = fragment_index` (0, 1, 2, …)
4. Fragment 0 gets `+0x38 = total_fragment_count` set **after** the
   loop completes.

Receiver (`FUN_006B6AD0` checks `+0x3C`; if set, calls
`FUN_006B6CC0` to reassemble):

1. Allocate a 256-element array indexed by `fragment_index`.
2. Scan the pending-message queue for fragments with matching `seq`.
3. Place each fragment into the array by `+0x39`.
4. Check fragment 0 (it carries `total_frags` at `+0x38`).
5. When all fragments are present, allocate a combined buffer,
   concatenate fragments in order.
6. Replace the message buffer with reassembled data via
   `FUN_006B89A0`.
7. Clear `is_fragment` (`+0x3C = 0`).
8. Remove consumed fragments from the queue.

Clone preserves the source's vtable, so all fragments share
`GetType()` and `is_ordered`.

### Reliability

When `ProcessIncomingPackets` sees a reliable message
(`+0x3A = 1`), it calls `FUN_006B61E0`, which builds a
`TGHeaderMessage` (type `0x01`) ACK carrying the sequence and
(if a fragment) the fragment index.

Two separate sequence counters per peer:

| Address       | Used by                                      |
|---------------|----------------------------------------------|
| `peer + 0x98` | Types `< 0x32` (connection management)       |
| `peer + 0xA8` | Types `>= 0x32` (game data)                  |

### Backoff modes

`SetRetransmitCount` (`FUN_006B8670`):

| Mode | Behaviour                                                |
|------|----------------------------------------------------------|
| 0    | Fixed interval (used for ACK messages)                   |
| 1    | Linear backoff (regular game messages, including fragments via Clone) |
| 2    | Exponential backoff (clamped at `+0x34`)                 |

### `TGMessage` object layout (complete)

| Offset  | Size | Field                  | Set by                                   |
|---------|------|------------------------|------------------------------------------|
| `+0x00` | 4    | vtable                 | ctor (`= 0x008958D0`)                    |
| `+0x04` | 4    | `data_ptr`             | `SetData` / `SetDataFromStream` / `BufferCopy` |
| `+0x08` | 4    | `data_length`          | same                                     |
| `+0x0C` | 4    | `from_id`              | send path (sender peer ID)               |
| `+0x10` | 4    | (connection context)    |                                          |
| `+0x14` | 2    | `sequence_number`      | `FUN_006B5080` (send helper)             |
| `+0x18` | 4    | (from address)          |                                          |
| `+0x1C` | 4    | `first_resend_time`    | retry timing                             |
| `+0x20` | 4    | `first_send_time`      | retry timing                             |
| `+0x24` | 4    | `timestamp`            | retry timing                             |
| `+0x28` | 4    | (to_id on wire)         |                                          |
| `+0x2C` | 4    | `num_retries`          | init 0                                   |
| `+0x30` | 4    | `backoff_time`         | init `1.0`                               |
| `+0x34` | 4    | `backoff_factor`       | init `1.0`                               |
| `+0x38` | 1    | `total_fragments`      | fragment 0 only                          |
| `+0x39` | 1    | `fragment_index`       | which fragment this is (0-based)          |
| `+0x3A` | 1    | `is_guaranteed`        | `SetGuaranteed` (0 = unreliable, 1 = reliable) |
| `+0x3B` | 1    | `is_high_priority`     | `SetHighPriority` (0 = normal, 1 = priority) |
| `+0x3C` | 1    | `is_fragment`          | 0 = complete, 1 = fragment piece          |
| `+0x3D` | 1    | (override-old-packets flag, init 1) |                                |
| `+0x3E` | 1    | (is_multipart flag)     |                                          |
| `+0x3F` | 1    | (is_aggregate flag)     |                                          |

Constructor `FUN_006B82A0` allocates 0x40 bytes from the pool
(`FUN_00717B70`). SWIG type name: `"_TGMessage_p"`.

### Vtables (cross-reference)

`TGMessage` base (`0x008958D0`):

| Slot | Offset | Function       | Name                          |
|------|--------|----------------|-------------------------------|
| 0    | `+0x00`| `0x006B9430`   | `GetType` (returns `0x32`)    |
| 1    | `+0x04`| `0x006B82F0`   | Destructor                    |
| 2    | `+0x08`| `0x006B8340`   | `WriteToBuffer` (serialiser)  |
| 3    | `+0x0C`| `0x006B9440`   | (returns 0)                   |
| 4    | `+0x10`| `0x006B9450`   | (unknown)                     |
| 5    | `+0x14`| `0x006B8640`   | `GetSize`                     |
| 6    | `+0x18`| `0x006B8610`   | `Clone`                       |
| 7    | `+0x1C`| `0x006B8720`   | `FragmentMessage`             |

`TGDataMessage` (`0x0089598C`, overrides):

| Slot | Offset | Function       | Name                          |
|------|--------|----------------|-------------------------------|
| 0    | `+0x00`| `0x006BD100`   | `GetType` (returns `0x00`)    |
| 1    | `+0x04`| `0x006BC5D0`   | Destructor                    |
| 2    | `+0x08`| `0x006BC610`   | `WriteToBuffer` (14-bit length)|
| 5    | `+0x14`| `0x006BC770`   | `GetSize`                      |
| 6    | `+0x18`| `0x006BC740`   | `Clone`                        |

### Network-tracker layout (per-ship, per-peer)

Each ship has a per-peer tracker for state-update bookkeeping
(addressed via the network-tracker hash table):

| Offset | Size | Field                                                |
|--------|------|------------------------------------------------------|
| `+0x00`| 4    | `next` (linked list)                                  |
| `+0x04`| 4    | `last_force_update_time`                             |
| `+0x0C`| 4    | `last_speed_value`                                   |
| `+0x10`| 12   | `saved_pos_{x,y,z}` (delta-compression reference)    |
| `+0x1C`| 4    | `saved_delta_magnitude`                              |
| `+0x20`| 3    | `saved_delta_dir{X,Y,Z}` (bytes)                     |
| `+0x24`| 4    | `last_orientation_update_time`                       |
| `+0x28`| 3    | `saved_fwd_dir{X,Y,Z}`                               |
| `+0x2B`| 3    | `saved_up_dir{X,Y,Z}`                                |
| `+0x2E`| 1    | `saved_cloak_state`                                  |
| `+0x30`| 4    | `subsystem_list_iterator` (for round-robin)          |
| `+0x34`| 4    | `subsystem_round_robin_index`                        |
| `+0x38`| 4    | `weapon_list_iterator`                               |
| `+0x3C`| 4    | `weapon_round_robin_index`                           |
| `+0x40`–`+0x4C`| various | weapon hash-table data                       |

---

## Game opcode catalogue

Three independent dispatchers register on the same
`ET_NETWORK_MESSAGE_EVENT` (`0x60001`); each reads the first
payload byte and silently ignores anything outside its range.

| Dispatcher          | Address      | Opcodes        | Notes                                   |
|---------------------|--------------|----------------|-----------------------------------------|
| `MultiplayerWindow` | `FUN_00504C10`| `0x00`/`0x01`/`0x16` | UI / settings; gated on `this+0xB0 != 0` |
| `MultiplayerGame`   | `0x0069F2A0` | `0x02`–`0x2A`  | Jump table at `0x0069F534` (41 entries) |
| `NetFile`           | `FUN_006A3CD0`| `0x20`–`0x27` | Checksums + file transfer               |
| Python              | (broadcast)  | any            | Python handlers fire on every message; range `>= 0x2B` is the convention |

### Master opcode table

#### `MultiplayerWindow` dispatcher (`FUN_00504C10`)

| Op   | Name                | Direction | Handler        | Payload summary                                             |
|------|---------------------|-----------|----------------|--------------------------------------------------------------|
| `0x00`| Settings            | S → C     | `FUN_00504D30` | `gameTime`, settings bits, player slot, mapName, checksumFlag |
| `0x01`| GameInit            | S → C     | `FUN_00504F10` | (empty payload)                                             |
| `0x16`| UICollisionSetting  | S → C     | `FUN_00504C70` | collisionDamageFlag (1 bit)                                  |

#### `MultiplayerGame` dispatcher (`0x0069F2A0`, jump table at `0x0069F534`)

| Op   | Name                  | Direction        | Handler        | Payload summary                                                  |
|------|-----------------------|------------------|----------------|------------------------------------------------------------------|
| `0x02`| ObjCreate              | S → C           | `FUN_0069F620` | Type tag `2`, `ownerSlot`, serialised object                       |
| `0x03`| ObjCreateTeam          | S → C           | `FUN_0069F620` | Type tag `3`, `ownerSlot`, `teamId`, serialised object             |
| `0x04`| (dead — default)       | —               | DEFAULT        | Boot is at the transport layer                                     |
| `0x05`| (dead — default)       | —               | DEFAULT        |                                                                  |
| `0x06`| PythonEvent            | any             | `FUN_0069F880` | `eventCode`, event payload (see `state-and-events.md`)            |
| `0x07`| StartFiring            | any             | `FUN_0069FDA0` | `objectId`, event data → event `0x008000D7`                       |
| `0x08`| StopFiring             | any             | `FUN_0069FDA0` | → event `0x008000D9`                                              |
| `0x09`| StopFiringAtTarget     | any             | `FUN_0069FDA0` | → event `0x008000DB`                                              |
| `0x0A`| SubsysStatus           | any             | `FUN_0069FDA0` | → event `0x0080006C`                                              |
| `0x0B`| AddToRepairList        | any             | `FUN_0069FDA0` | → event `0x008000DF`                                              |
| `0x0C`| ClientEvent            | any             | `FUN_0069FDA0` | → event read from stream (preserve = 0)                           |
| `0x0D`| PythonEvent2           | any             | `FUN_0069F880` | Same as `0x06`                                                    |
| `0x0E`| StartCloaking          | any             | `FUN_0069FDA0` | → event `0x008000E3`                                              |
| `0x0F`| StopCloaking           | any             | `FUN_0069FDA0` | → event `0x008000E5`                                              |
| `0x10`| StartWarp              | any             | `FUN_0069FDA0` | → event `0x008000ED`                                              |
| `0x11`| RepairListPriority     | any             | `FUN_0069FDA0` | → event `0x00800076`                                              |
| `0x12`| SetPhaserLevel         | any             | `FUN_0069FDA0` | → event `0x008000E0`                                              |
| `0x13`| HostMsg                | C → S           | `FUN_006A01B0` | Host-specific (self-destruct, etc.)                                |
| `0x14`| DestroyObject          | S → C           | `FUN_006A01E0` | `objectId`. **Not observed for MP ship deaths** — they go via `0x29` + `0x03` |
| `0x15`| CollisionEffect        | C → S only      | `FUN_006A2470` | TG event: `[u8 0x15][i32 classID 0x8124][i32 evt 0x800050][srcObj][tgtObj][count][N×cv4][f32 force]` |
| `0x16`| (default)              | —               | DEFAULT        | Handled by MultiplayerWindow above                                |
| `0x17`| DeletePlayerUI         | S → C           | `FUN_006A1360` | Serialised `TGEvent` (factory `0x866`); 18 B                      |
| `0x18`| DeletePlayerAnim       | S → C           | `FUN_006A1420` | Player-deletion text / floating animation                          |
| `0x19`| TorpedoFire            | owner → all     | `FUN_0069F930` | `objId`, flags, velocity (cv3), [`targetId`, impact (cv4)]         |
| `0x1A`| BeamFire               | owner → all     | `FUN_0069FBB0` | `objId`, flags, dir (cv3), more flags, [`targetId`]                |
| `0x1B`| TorpTypeChange         | any             | `FUN_0069FDA0` | → event `0x008000FD`                                              |
| `0x1C`| StateUpdate            | owner → all     | `FUN_0069FF50` | `objectId`, `gameTime`, dirty flags, fields (see `state-and-events.md`) |
| `0x1D`| ObjNotFound            | S → C           | `FUN_006A0490` | `objectId` (`0x3FFFFFFF` queries are normal)                       |
| `0x1E`| RequestObject          | C → S           | `FUN_006A02A0` | `objectId` — server replies with `0x02`/`0x03`                     |
| `0x1F`| EnterSet               | S → C           | `FUN_006A05E0` | `objectId`, set data                                              |
| `0x20`–`0x28`| (default)        | —               | DEFAULT        | Handled by NetFile dispatcher                                     |
| `0x29`| Explosion              | S → C           | `FUN_006A0080` | `objectId`, impact (cv4), damage (CF16), radius (CF16)             |
| `0x2A`| NewPlayerInGame        | C → S (verified)| `FUN_006A1E70` | Sent by client after ship selection                                 |

#### `NetFile` dispatcher (`FUN_006A3CD0`, opcodes `0x20`–`0x28`)

| Op   | Name                | Direction        | Handler                              | Payload summary                       |
|------|---------------------|------------------|--------------------------------------|---------------------------------------|
| `0x20`| ChecksumRequest    | S → C           | `FUN_006A5DF0`                       | `index`, dir, filter, recursive       |
| `0x21`| ChecksumResponse   | C → S           | `FUN_006A4260` → `FUN_006A4560`       | `index`, hashes                       |
| `0x22`| VersionMismatch    | S → C           | `FUN_006A4C10`                       | `filename` (length-prefixed)          |
| `0x23`| SystemChecksumFail | S → C           | `FUN_006A4C10`                       | `filename` (length-prefixed)          |
| `0x25`| FileTransfer       | S → C           | `FUN_006A3EA0`                       | `filename`, raw file data             |
| `0x27`| FileTransferACK    | C → S           | `FUN_006A4250`                       | (empty)                               |
| `0x28`| ChecksumComplete   | S → C           | (no dedicated handler)                | (empty — sentinel before Settings/GameInit) |
| `0x24`/`0x26` | unused      | —               | —                                    | Slots exist but no handler / trace    |

#### Python-level message space (handled by Python-registered handlers, bypass C++ dispatchers)

| Op   | Name                  | Direction       | Handler                          | Notes                              |
|------|-----------------------|-----------------|----------------------------------|-------------------------------------|
| `0x2C`| `CHAT_MESSAGE`        | relayed         | `MultiplayerMenus.ProcessMessageHandler` | Python-side selective relay |
| `0x2D`| `TEAM_CHAT_MESSAGE`   | relayed         | same                             | Same as `0x2C`, team-only display   |
| `0x35`| `MISSION_INIT_MESSAGE`| S → C           | `Mission*.ProcessMessageHandler` | Sent during `InitNetwork`           |
| `0x36`| `SCORE_CHANGE_MESSAGE`| S → C           | same                             | Per-kill score deltas               |
| `0x37`| `SCORE_MESSAGE`       | S → C           | same                             | Full per-player sync on join         |
| `0x38`| `END_GAME_MESSAGE`    | S → C           | `MissionShared`                  | Game over, reason code              |
| `0x39`| `RESTART_GAME_MESSAGE`| S → C           | same                             | Restart                              |
| `0x3F`| `SCORE_INIT_MESSAGE`  | S → C (team)    | `Mission2/3/5.ProcessMessageHandler` | Score + team byte               |
| `0x40`| `TEAM_SCORE_MESSAGE`  | S → C (team)    | same                             | Per-team kills/score                 |
| `0x41`| `TEAM_MESSAGE`        | C → S → all     | same                             | Team selection (host forwards)      |

`App.MAX_MESSAGE_TYPES = 0x2B` (43) — the count of C++-dispatched
opcodes. By convention, Python message types are `MAX_MESSAGE_TYPES + N`,
but mods can use any 0–255 value.

### Opcode `0x00` — Settings (full layout)

Sent by the host's `ChecksumCompleteHandler` (`FUN_006A1B10`) after
all checksum rounds pass.

```
Offset  Size  Type     Field                    Notes
------  ----  ----     -----                    -----
0       1     u8       opcode = 0x00
1       4     f32      game_time                from g_Clock+0x90
2       bit   bool     settings_byte1           DAT_008e5f59 (collision damage toggle)
3       bit   bool     settings_byte2           DAT_0097faa2 (friendly fire toggle)
4       1     u8       player_slot              assigned slot, 0–15
5       2     u16      map_name_length
7       var   string   map_name                 mission TGL path
+0      bit   bool     checksum_result_flag     1 = checksums passed with corrections
[if flag == 1:]
+1      var   data     checksum_correction_data via FUN_006F3F30
```

Stream-write sequence (from `FUN_006A1B10`):

```c
WriteByte(0x00);
WriteFloat(gameTime);           // clock+0x90
WriteBit(DAT_008e5f59);         // settings 1
WriteBit(DAT_0097faa2);         // settings 2
WriteByte(playerSlot);
WriteShort(mapNameLen);
WriteBytes(mapName, len);
WriteBit(checksumFlag);
if (checksumFlag) FUN_006F3F30(stream);
```

### Opcode `0x01` — GameInit

Single byte, no payload. Triggers, on the client side:

1. Python `AI.Setup.GameInit()` (preloads 73 AI modules).
2. `MultiplayerGame` C++ object construction (max 16 players).
3. Reads `g_iPlayerLimit` from `Multiplayer.MissionMenusShared`.
4. Shows "Connection Completed" UI.

### Opcode `0x04`/`0x05` — dead

Default jump-table entries; not used. Boot/kick is dispatched at
the **transport** layer via `TGBootPlayerMessage` (sent by
`FUN_00506170`, the `BootPlayerHandler` registered for
`ET_BOOT_PLAYER`), not as a game opcode.

### Opcodes `0x07`–`0x0C`, `0x0E`–`0x12`, `0x1B` — event forwards

All share the generic envelope:

```
Offset  Size  Type    Field
------  ----  ----    -----
0       1     u8      opcode
1       4     i32     object_id          ship/object generating the event
5+      var   data    event-specific payload (variable)
```

Event-code pairing — sender uses one event code locally, receiver
uses a paired version:

```
0xD8 → 0xD7  StartFiring
0xDA → 0xD9  StopFiring
0xDC → 0xDB  StopFiringAtTarget
0xDD → 0x6C  SubsystemStatus
0xE2 → 0xE3  StartCloaking
0xE4 → 0xE5  StopCloaking
0xEC → 0xED  StartWarp
0xFE → 0xFD  TorpedoTypeChange
```

`0x12 SetPhaserLevel` is the **exception** — uses `0x008000E0` on
both sides, no pairing/override. See
`per-feature-protocols.md` for its full wire layout.

### Opcode `0x06`/`0x0D` — Python event

```
Offset  Size  Type    Field
------  ----  ----    -----
0       1     u8      opcode             0x06 or 0x0D
1       4     u32     event_code         e.g. ET_OBJECT_EXPLODING
5+      var   data    Python event payload
```

`FUN_0069F880` strips the opcode byte, builds a `TGBufferStream`
from the rest, instantiates a `TGEvent` via `FUN_006D6200`, and
posts it. Both `0x06` and `0x0D` go to the same handler. Full
payload formats live in `state-and-events.md` under "PythonEvent".

### Opcode `0x13` — HostMsg

Tiny client-to-host message used for host-authority actions
(self-destruct in particular). The full self-destruct flow is in
`gameplay/ship-subsystems.md`.

### Opcode `0x14` — DestroyObject

```
[byte:0x14][int32: object_id]    ; ReadInt32v
```

If the looked-up object has an owner (`obj[8] != NULL`), call
`owner->vtable[0x5C](object_id)`; otherwise call cleanup +
destructor.

**Not observed for ship deaths in stock MP traces** (0 occurrences
across 138,695 packets in a 33.5-min combat session with 59 ship
deaths). Ships die via `Explosion (0x29)` plus client-initiated
`ObjCreateTeam (0x03)` respawn. `0x14` may be reserved for
non-ship objects (torpedoes/projectiles) and player-disconnect
cleanup.

### Opcodes `0x17`/`0x18` — DeletePlayerUI / DeletePlayerAnim

See `per-feature-protocols.md` for the `DeletePlayerUI` (`0x17`)
wire format; `0x18` is a player-deletion floating-text animation
that consults `data/TGL/Multiplayer.tgl` for its format string.

### Opcode `0x19` — TorpedoFire

```
[byte:0x19]
[int32: object_id]                ; torpedo subsystem object ID
[byte: flags1]                    ; subsystem index / type info (observed: 0x02)
[byte: flags2]                    ; bit 0 = has_arc, bit 1 = has_target

[3 bytes: velocity (cv3)]         ; torpedo direction

[if has_target (flags2 bit 1):]
  [int32: target_id]              ; ReadInt32v
  [5 bytes: impact_point (cv4)]   ; 3 dir bytes + CF16 magnitude
```

Observed flag values: photon torpedoes `flags2 = 0x05` (has_arc,
no target); quantum torpedoes with target lock `flags2 = 0x07`
(has_arc + has_target). Dual-spread torpedoes send 2
`TorpedoFire` messages simultaneously with paired object IDs.
Torpedoes are also replicated via `0x02`/`0x03` and tracked via
`0x1C`.

### Opcode `0x1A` — BeamFire

```
[byte:0x1A]
[int32: object_id]                ; phaser subsystem object ID
[byte: flags]                     ; observed: 0x02
[3 bytes: target_position (cv3)]  ; direction
[byte: more_flags]                ; bit 0 = has_target_id

[if has_target_id (more_flags bit 0):]
  [int32: target_object_id]       ; ReadInt32v
```

Two-turret ships (e.g. Klingon Bird of Prey) send 2 `BeamFire`
messages simultaneously.

### Opcode `0x1D` — ObjNotFound

```
[byte:0x1D][int32: object_id]
```

Server tells client "object X doesn't exist here" — common during
EnterSet relays; `0x3FFFFFFF` queries are normal.

### Opcode `0x1E` — RequestObject

```
[byte:0x1E][int32: object_id]
```

Client asks server to send the full state of `object_id`. Server
responds with `0x02`/`0x03` (the standard ObjCreate format).

### Opcode `0x1F` — EnterSet

```
[byte:0x1F][int32: object_id]
[int32: set_size][bytes: set_data]
```

Move an object into a new game set (scene region). If the object
isn't found locally, the server replies with `0x1D` (not found).

### Opcode `0x29` — Explosion

```
Offset  Size  Type    Field
------  ----  ----    -----
0       1     u8      opcode = 0x29
1       4     i32/id  object_id           target ship — ReadInt32v
5       5     cv4     impact_position     3 dir bytes + CF16 magnitude
10      2     u16     radius_compressed   CF16
12      2     u16     damage_compressed   CF16
Total: 14 bytes
```

Field order verified from sender: **radius first**, **damage
second**. Receiver passes them to an `ExplosionDamage(pos, radius,
damage)` constructor that stores `radius` at `+0x14`, `radius²` at
`+0x18`, `damage` at `+0x1C`, then calls
`ProcessDamage(ship, explosionObj)`.

Both fields are CF16 (lossy). `per-feature-protocols.md` covers
the precision implications and mod compatibility.

### NetFile / checksum opcodes (full layouts)

#### `0x20` — Checksum Request (S → C)

```
Offset  Size  Type    Field
------  ----  ----    -----
0       1     u8      opcode = 0x20
1       1     u8      request_index            (0–3, or 0xFF for final round)
2       2     u16     directory_name_length
4       var   string  directory_name           e.g. "scripts/"
+0      2     u16     filter_name_length
+2      var   string  filter_name              e.g. "App.pyc"
+0      bit   bool    recursive_flag
```

5 checksum rounds, sent sequentially (server waits for each
response before sending the next):

| Round | Index | Directory                | Filter         | Recursive | Purpose                |
|-------|-------|--------------------------|----------------|-----------|------------------------|
| 1     | `0x00`| `scripts/`               | `App.pyc`      | No        | Core application module|
| 2     | `0x01`| `scripts/`               | `Autoexec.pyc` | No        | Startup script         |
| 3     | `0x02`| `scripts/ships`          | `*.pyc`        | **Yes**   | All ship .pyc          |
| 4     | `0x03`| `scripts/mainmenu`       | `*.pyc`        | No        | Menu modules           |
| 5     | `0xFF`| `Scripts/Multiplayer`    | `*.pyc`        | **Yes**   | MP mission scripts     |

#### `0x21` — Checksum Response (C → S)

```
Offset  Size  Type    Field
------  ----  ----    -----
0       1     u8      opcode = 0x21
1       1     u8      request_index             (echoes the request)
2+      var   data    hash_data                 (variable, opaque)
```

Server uses `byte[1]`:

- `byte[1] == 0xFF` — final round (Multiplayer scripts), main path.
- `byte[1] != 0xFF` — standard round, `FUN_006A4560`.

Round 2 / 0xFF responses are typically **fragmented** (~400+
bytes); the others fit in one message.

#### `0x22` / `0x23` — Checksum Fail (S → C)

```
Offset  Size  Type    Field
------  ----  ----    -----
0       1     u8      sub_opcode (0x22 or 0x23)
1       2     u16     filename_length
3       var   string  failing_filename
```

`0x22` = file/version mismatch (`"VersionDifferent"`),
`0x23` = system checksum fail (`"SystemChecksumFail"`). Client
shows an error dialog.

#### `0x25` — File Transfer (S → C)

Initial entry (server's `this+0x14 == 0`): sets up the
"Receive File Warning" dialog.

Transfer data:

```
Offset  Size  Type    Field
------  ----  ----    -----
0       1     u8      opcode = 0x25
1       2     u16     filename_length
3       var   string  filename
+0      var   data    file_data                 remainder of the packet
```

After the file is written, the client checks if it's a `.pyc` in
`Scripts/` and re-imports the module. Client replies with `0x27`.

#### `0x27` — File Transfer ACK (C → S)

```
[byte:0x27]
```

`FUN_006A4250` calls `FUN_006A5860` to either continue file
transfer or signal completion.

#### `0x28` — Checksum Complete (S → C)

Single byte. No dedicated handler — fires immediately before the
host's `0x00` (Settings) and `0x01` (GameInit) messages, signalling
that all 5 checksum rounds passed.

### Event-handler registration (cross-reference)

The `MultiplayerGame` constructor (`FUN_0069E590`) registers a
fixed catalogue (29 entries) — see
`architecture/runtime-and-main-loop.md` for the complete event
table.

---

## Cross-references

- **Higher-level state replication** — `state-and-events.md`
  (StateUpdate `0x1C`, ObjCreate `0x02`/`0x03`, PythonEvent
  `0x06`/`0x0D`, TGMessage routing).
- **Per-feature protocols** — `per-feature-protocols.md`
  (CollisionEffect `0x15`, SetPhaserLevel `0x12`,
  DeletePlayerUI `0x17`, CF16 explosion encoding analysis).
- **Session / cipher / GameSpy** —
  `networking/transport-and-sessions.md`.
- **Engine globals & MultiplayerGame state** —
  `architecture/runtime-and-main-loop.md`.
