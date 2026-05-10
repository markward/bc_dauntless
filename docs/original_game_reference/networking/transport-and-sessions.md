# Transport, Sessions, and Discovery

How `stbc.exe` carries gameplay over the network: the UDP transport
that `TGWinsockNetwork` provides, the AlbyRules! cipher that wraps
every packet, the GameSpy LAN/Internet discovery and master-server
flow, the connection lifecycle from join through ship-death and
disconnect, and the relay rules every multiplayer message has to
honour.

The on-the-wire byte layouts of game opcodes themselves live in
`protocol/wire-format-and-opcodes.md`,
`protocol/state-and-events.md`, and
`protocol/per-feature-protocols.md`.

---

## Topology

A pure star: every client maintains a single connection to the host;
the host maintains connections to every client. There are no
client-to-client connections.

```
Client A  ←→  HOST  ←→  Client B
                ↑
Client C  ←─────┘
```

The host acts as an opaque relay: when it receives any game-layer
message from a client via the transport layer, it **automatically
relays** that message to every other connected client. The relay is:

- **Unconditional** — every game message is relayed regardless of
  opcode or content.
- **Opaque** — the host doesn't read or interpret the message
  payload.
- **Immediate** — happens during the network update tick, before
  dispatch.

So a client `SendTGMessage(0, msg)` (broadcast) effectively reaches
every other client through the host's relay, even though the client
only had a single peer (the host) to send to.

---

## Transport layer

UDP only. Both gameplay and GameSpy traffic share the same socket
(`WSN+0x194`); they are demultiplexed by inspecting the first byte —
GameSpy queries are always plaintext starting with `\` (0x5C);
gameplay packets are encrypted (and start with a binary direction
flag).

### Packet framing

Each UDP datagram:

```
byte 0       direction flag (1=server, 2=client, 0xFF=initial contact) — NOT encrypted
byte 1       sender peer ID
byte 2       count of sub-messages
…            N sub-messages, each starting with a transport-type byte
```

Bytes from offset 1 onward are encrypted with AlbyRules! (see
"Cipher" below). The first byte is *not* passed through the cipher.

### Transport message types (256-wide; 7 defined)

| Type   | Purpose                                                |
|--------|--------------------------------------------------------|
| `0x00` | Game-data message (carries an application-layer payload)|
| `0x01` | Acknowledgement (reliable-delivery tracking)            |
| `0x02` | Connection request                                     |
| `0x03` | Connection acknowledgement                             |
| `0x04` | Boot / forced disconnect                               |
| `0x05` | Graceful disconnect                                    |
| `0x32` | General-purpose data message (with fragmentation)      |

`TGNetwork_RegisterMessageType` (a SWIG entry point) lets code add
custom transport types at runtime, but stock content never calls it.
**Packets with undefined transport types are silently dropped** at
the transport layer — no error, no crash.

### The 0x32 boundary

Two reliable-delivery channels coexist, partitioned by message type:

- **Types `0x00`–`0x31`** — game-message channel. Uses the
  send-counter at `peer+0x26` and expected-seq at `peer+0x24`. Goes
  through the queue at `WSN+0x8C`.
- **Types `0x32`+** — session/lobby channel. Uses send-counter
  `peer+0x2A`, expected-seq `peer+0x28`, queue at `WSN+0x54`.

The split is visible in `FUN_006B5080` (`SendHelper`),
`FUN_006B6AD0` (`QueueForDispatch`), and `FUN_006B6CC0`
(`ReassembleFragments`).

### `TGMessage` vtable

The TGMessage virtual interface is exactly 8 slots (32 bytes):

| Slot | Offset | Purpose                                                     |
|------|--------|--------------------------------------------------------------|
| 0    | `+0x00`| `GetType()` → `u8` message type                              |
| 1    | `+0x04`| `scalar_deleting_destructor(flag)`                            |
| 2    | `+0x08`| `WriteToBuffer(buf, maxSize)` — bytes written, 0 on failure   |
| 3    | `+0x0C`| `Supersedes(other)` / `IsExpired()` — discard stale unreliables when newer reliable arrives |
| 4    | `+0x10`| `IsOrderedDelivery()` / `HasOrdering()`                       |
| 5    | `+0x14`| `GetSize()` — serialised byte count                           |
| 6    | `+0x18`| `Clone()` — `FUN_006B8610`, alloc 0x40 + copy-construct       |
| 7    | `+0x1C`| `FragmentMessage(&fragCount, maxPayload)` — `FUN_006B8720`    |

ACK matching and sequence comparison are **not** virtual — they
read peer fields directly (`peer+5` for seq, `+0xF` for
`is_fragmented`, `+0x39` for `frag_idx`, `+0x40` for
`is_below_0x32`).

### Reliability

`TGNetwork::Update` (`FUN_006B4560`) is one of the per-tick
updateables registered with the frame-budget scheduler. It calls
three sub-functions unconditionally per tick:

```
FUN_006B55B0  SendOutgoingPackets   (ACKs + retransmit + first-send)
FUN_006B5C90  ProcessIncomingPackets (recvfrom loop, ACK creation)
FUN_006B5F70  DispatchIncomingQueue  (sequence validation, app dispatch)
```

There is one tick of latency between receiving fragments and sending
ACKs (intentional).

### Fragmentation

`Clone()` (`FUN_006B8610`) preserves the source message's vtable, so
fragments share `GetType()` and `is_ordered`. `FragmentMessage`
inserts each fragment as its own first-send queue entry; if the
source is `is_ordered`, fragments insert at the **head** in
fragmenting order, which means they transmit in **reverse** order.
The receiver reassembles by `frag_idx` (not arrival order), so this
works correctly.

Reliability sequencing handles fragments correctly because all three
fragments share the same `seq`. The check is window-based:

```
delta = incoming_seq - expected_seq
if (-0x4001 < delta) && (delta < 0 || 0x3FFF < delta):
    out-of-window — drop, no ACK
```

So `delta == 0` (first arrival) and `delta == -1` (subsequent
fragments after the expected counter advances by 1) both pass.

### ACK retransmit backoff

`SetRetransmitCount` (`FUN_006B8670`) supports three backoff modes:

| Mode | Behaviour                              |
|------|----------------------------------------|
| 0    | Fixed interval (used for ACK messages) |
| 1    | Linear backoff (regular messages)       |
| 2    | Exponential backoff (clamped at `+0x34`)|

### Peer object layout (selected)

| Offset  | Field                                    |
|---------|-------------------------------------------|
| `+0x18` | Peer ID (network-assigned)               |
| `+0x1C` | Peer IP                                   |
| `+0x24` | Expected seq (game channel, type < 0x32) |
| `+0x26` | Send counter (game channel)              |
| `+0x28` | Expected seq (session channel, ≥ 0x32)   |
| `+0x2A` | Send counter (session channel)           |
| `+0x2C` | Keepalive send timestamp                  |
| `+0x30` | Last-receive timestamp                    |
| `+0x7C` | Unreliable send queue                     |
| `+0x98` | Reliable send queue                       |
| `+0x9C` | Priority reliable queue head (ACK tracker)|
| `+0xB8` | Disconnect timestamp                      |
| `+0xBC` | `IsDisconnected` flag                     |

Connection-state values on `TGNetwork`:

| State | Meaning                            |
|-------|------------------------------------|
| 2     | Hosting                             |
| 3     | Joining (client)                   |
| 4     | Disconnected                       |

Counter-intuitively, **state 2 means host, state 3 means client**.

---

## AlbyRules! cipher

Every UDP gameplay packet (after the unencrypted direction-flag byte
0) is wrapped with a custom stream cipher. The cipher key is the
hardcoded ASCII string **`"AlbyRules!"`** (10 bytes:
`41 6C 62 79 52 75 6C 65 73 21`) at `0x0095ABB4` in `.rdata`. The
name is almost certainly a Totally Games developer's in-joke that
shipped to retail.

### Cipher functions

| Address     | Function                | Role                                                 |
|-------------|-------------------------|------------------------------------------------------|
| `0x006C2280`| `Reset`                 | Copy `"AlbyRules!"` into cipher object, zero PRNG state |
| `0x006C22F0`| Key schedule            | Derive 5 key-words from 10 key bytes; 5 PRNG rounds   |
| `0x006C23C0`| PRNG step               | LCG variant, multiplier `0x4E35`, addend `0x15A`      |
| `0x006C2490`| Encrypt                 | Per-byte mask + plaintext feedback (before XOR)       |
| `0x006C2520`| Decrypt                 | Inverse — feedback after XOR                         |

### How it works

A stream cipher with **plaintext feedback**. Per-packet behaviour:

1. **Reset** — every encrypt/decrypt call starts from the same
   initial state (a fresh copy of `"AlbyRules!"`).
2. **Key schedule** — 10 key bytes are paired into 5 key words,
   each XORed with its predecessor; 5 PRNG rounds produce an
   accumulator.
3. **Per-byte encryption** — for each byte: re-run the key schedule,
   extract `mask_low` and `mask_high` from the PRNG, XOR plaintext
   with both masks, then **feed the plaintext byte back into all 10
   key bytes** so the next byte sees a different key state.
4. **Decrypt** is identical except the feedback step happens *after*
   XOR — both operations feed back the *plaintext*, ensuring the
   same keystream.

Critical properties:

- **Static key.** Same for every session, every player, every
  packet. No nonce, no key exchange.
- **Per-packet reset.** Same plaintext always produces the same
  ciphertext.
- **Byte-0 quirk.** The first PRNG output happens to XOR to `0x00`
  with the `"AlbyRules!"` key, so byte 1 of the encrypted region
  passes through unchanged.
- **Byte-0 of the datagram is unencrypted** (direction flag) — the
  cipher operates from byte 1 onward.
- **No authentication.** Packets can be forged or modified
  undetected.

It's an obfuscation layer, not a security mechanism.

---

## Connection lifecycle

### Initialisation (`UtopiaModule::InitMultiplayer`, `FUN_00445D90`)

`__thiscall` on `UtopiaModule` (`0x0097FA00`):

```
1. new TGWinsockNetwork(0x34C bytes) → UtopiaModule+0x78 (0x0097FA78)
2. FUN_006B9BB0(WSN, port, 0)        → WSN+0x338 = port
3. If IsMultiplayer: force addr=0, port=0x5655 (host path)
4. If password empty: param_2 = NULL
5. TGNetwork::HostOrJoin(WSN, addr, password)
       addr=0:  HOST  — sets WSN+0x10E=1, state=2, fires event 0x60002
       addr!=0: JOIN  — sets WSN+0x10E=0, state=3, sets WSN+0x10F=1
       calls vtable+0x60 to create UDP socket
       calls FUN_006B7070 to set address info
6. new NetFile(0x48 bytes) → UtopiaModule+0x80 (0x0097FA80)
       creates 3 hash tables (A/B/C), registers ReceiveMessageHandler
       for event 0x60001 (ET_NETWORK_MESSAGE_EVENT)
7. new GameSpy(0xF4 bytes) → UtopiaModule+0x7C (0x0097FA7C)
```

Default port is `0x5655` = 22101.

### Two opcode dispatchers

Once a peer is registered, every incoming game message fires
`ET_NETWORK_MESSAGE_EVENT` (`0x60001`). **Two C++ handlers** are
registered for it independently:

| Object          | Handler                       | Opcodes handled |
|-----------------|-------------------------------|------------------|
| `NetFile`        | `FUN_006A3CD0`                | `0x20`–`0x27` (checksums, file transfer) |
| `MultiplayerGame`| `0x0069F2A0` `ReceiveMessage` | `0x02`–`0x2A` (game objects, events, combat, players) |

A third opcode space — `0x00`/`0x01`/`0x16` — is handled by the
`MultiplayerWindow` event handler. **Python event handlers** also
register on the same event ID and process opcodes above the C++
range (chat, scoring, mission init).

Three independent dispatchers, each looking at the first byte; all
filter by what they recognise and **silently ignore** anything they
don't.

### Checksum exchange

When a new peer connects, `MultiplayerGame::NewPlayerHandler`
(`FUN_006A0A30`) assigns a player slot and triggers
`FUN_006A3820` (`ChecksumRequestSender`). It builds 5 requests and
sends round 0 immediately:

| # | Directory                | Filter           | Recursive |
|---|--------------------------|------------------|-----------|
| 0 | `scripts/`               | `App.pyc`        | No        |
| 1 | `scripts/`               | `Autoexec.pyc`   | No        |
| 2 | `scripts/ships/`         | `*.pyc`          | **Yes**   |
| 3 | `scripts/mainmenu/`      | `*.pyc`          | No        |
| 0xFF | `Scripts/Multiplayer/`| `*.pyc`          | **Yes**   |

`scripts/Custom/` and `scripts/Local.py` are exempt (modders' working
directories).

Each request is opcode `0x20`:

```
[byte:0x20]
[byte:index]
[ushort:dir_len][bytes:dir]
[ushort:filter_len][bytes:filter]
[byte:recursive]
```

Reliable delivery.

Client receives `0x20` in `FUN_006A5DF0`:

1. Parse index, dir, filter, recursive.
2. If `index == 0`, run client init (`FUN_006A6630`).
3. `FUN_0071F270` computes file checksums for the directory.
4. If files found, build response opcode `0x21` and send via
   `TGNetwork::Send`.
5. **If no files match, the response is silently dropped** — no
   negative-response opcode exists.

Server response handler (`FUN_006A4260` → `FUN_006A4560`):

1. Look up the queued request in NetFile hash table B.
2. Compute server-side checksum.
3. For index 0, also verify the reference-string hash
   (`PTR_DAT_008D9AF4`).
4. Match → `FUN_006A5290` (success), dequeue, send the next
   request.
5. Mismatch → `FUN_006A4A00` fires `ET_SYSTEM_CHECKSUM_FAILED`
   (`0x8000E7`), sends opcode `0x22` (file mismatch) or `0x23`
   (reference mismatch).
6. Queue empty → `FUN_006A4BB0` fires `ET_CHECKSUM_COMPLETE`
   (`0x8000E8`).

The full checksum flow completes in ~66 ms in stock traces. Round 2
(`scripts/ships/`, recursive) and round 0xFF (`Scripts/Multiplayer/`,
recursive) produce large fragmented responses (~400-441 bytes each).

### Settings + GameInit

`MultiplayerGame::ChecksumCompleteHandler` (`0x006A1B10`) runs on the
host, verifies the new client's checksums against existing players',
and emits two reliable opcodes:

```
0x00 Settings     [f32:gameTime][u8:settingsByte1][u8:settingsByte2]
                  [u8:playerSlot][u16:mapNameLen][bytes:mapName][u8:checksumFlag]
                  [if flag != 0: checksum match data]

0x01 GameInit     [byte:0x01]
```

Stock observation: the host bundles `0x28` (transport ack), `0x00`
Settings, and `0x01` GameInit in a single 65-byte packet at T+66 ms.

### `NewPlayerInGame` (`0x2A`)

Triggered by `MultiplayerGame::NewPlayerInGameHandler`
(`FUN_006A1E70`). Replicates every alive object, calls Python
`mission.InitNetwork(connID)` (which sends `MISSION_INIT_MESSAGE`
0x35 + `SCORE_MESSAGE` 0x37 per player), and adds the new connID to
both `"NoMe"` and `"Forward"` network groups. See
`architecture/runtime-and-main-loop.md` for the full handler.

### Verified handshake timeline (stock dedi)

```
T+0ms     Connect (0x03)             C → S
T+2ms     Connect ACK + ChecksumReq round 0   S → C
T+9ms     ACK + Keepalive (player name) ====> S
T+17ms    ChecksumResp round 0 ====>          → ACK + ChecksumReq round 1
T+26ms    ChecksumResp round 1 ====>          → ACK + ChecksumReq round 2
T+38ms    ChecksumResp round 2 (3 fragments)
T+41ms    → ACK + ChecksumReq round 3
T+53ms    ChecksumResp round 3 ====>          → ACK + ChecksumReq round 0xFF
T+63ms    ChecksumResp round 0xFF (fragmented)
T+66ms    ← 0x28 ChecksumComplete + 0x00 Settings + 0x01 GameInit
T+113ms   ACKs for seq 5,6,7 ====>
T+140ms   0x2A NewPlayerInGame ====>
T+142ms   ← ACK + 0x35 GameState + 0x17 DeletePlayerUI (clear stale UI)
T+5006ms  ConnectAck (transport-level 0x05) ====>
T+10084ms HEARTBEAT to master ====>           (333networks)
T+16s     ← Master verify query :27901
…
```

Five checksum rounds (0, 1, 2, 3, 0xFF), two are recursive (2
and 0xFF). Settings + GameInit are bundled into one packet
immediately after `0x28`.

### Network-event types

| ID         | Constant                          | Meaning                              |
|------------|-----------------------------------|---------------------------------------|
| `0x60001`  | `ET_NETWORK_MESSAGE_EVENT`        | Incoming game message                 |
| `0x60002`  | (host start)                       | Connection established                |
| `0x60003`  | `ET_NETWORK_DISCONNECT`           | Full network shutdown (not per-peer)  |
| `0x60004`  | `ET_NETWORK_NEW_PLAYER`           | New peer connected                    |
| `0x60005`  | `ET_NETWORK_DELETE_PLAYER`        | Peer removed                          |
| `0x008000C8`| (object created)                  | Game object created                   |
| `0x008000E6`| `ET_CHECKSUM_RESULT`              | Individual checksum done              |
| `0x008000E7`| `ET_SYSTEM_CHECKSUM_FAILED`       | Checksum mismatch                     |
| `0x008000E8`| `ET_CHECKSUM_COMPLETE`            | All checksums passed                  |
| `0x008000E9`| `ET_KILL_GAME`                    | Game killed                           |
| `0x008000F6`| `ET_BOOT_PLAYER`                  | Anti-cheat kick                       |
| `0x008000FF`| (retry connect)                   | Connection retry                      |

---

## Disconnect

Three paths converge on a single peer-deletion entry point:

```
TIMEOUT (~45 s)
  TGNetwork::Update (FUN_006B4560)
    iterate peers; if currentTime - peer+0x30 > timeout:
      create TGBootPlayerMessage (bootReason=1)
      → FUN_006B75B0(WSN, peerID)

GRACEFUL (transport 0x05)
  ProcessIncomingPackets (FUN_006B5C90)
    receive type-0x05 message
    dispatch to FUN_006B6A20
    read peer ID
    → FUN_006B75B0(WSN, peerID)

BOOT / KICK
  ET_BOOT_PLAYER (0x8000F6) event
    BootPlayerHandler (FUN_00506170)
    send kick to target peer
    target disconnects
    → FUN_006B75B0(WSN, peerID)
```

### Timeout detection (`FUN_006B4560`)

For each peer in the WSN peer array, while `peer+0xBC == 0`
(connected), if `currentTime - peer+0x30 > connectionTimeout` (the
last receive is older than the timeout):

- Create a `TGBootPlayerMessage` (bootReason=1).
- Call `FUN_006B75B0` to delete the peer.
- Send the boot message to other peers.

Constants:

- Keepalive send interval: **5.0 s** (`DAT_0088BD58`).
- Peer timeout: **45.0 s** (`WSN+0xB8`, set in WSN constructor).

So a peer needs 9 missed keepalives before it gets timed out. Note:
keepalives only send when no other game data is flowing; in active
gameplay you won't see explicit keepalives.

### Graceful disconnect (`FUN_006B6A70`)

```c
char *data = FUN_006B8530(msg, NULL);  // payload
int peerID = (int)*data;
if (peerID == -1) {                    // host disconnected from us
    WSN+0x10D = 1;                     // shutdown flag
    WSN+0x100 = msg+0x40;              // reason
    state    = 2;
    return;
}
FUN_006B75B0(WSN, peerID);
if (peerID == WSN+0x18) {              // it WAS the host peer
    WSN+0x10D = 1;
    WSN+0x100 = msg+0x40;
}
```

Reaches the deletion entry point immediately (no timeout wait).

### Convergence — `FUN_006B75B0`

Single entry point. Binary-searches the peer array, posts an event,
marks the peer disconnected (does **not** immediately remove it):

```c
void FUN_006B75B0(WSN* this, int peerID) {
    if (this->peerArray == NULL) goto fallback;
    int idx = FUN_00401CC0(this->peerArray, peerID);
    if (idx < 0) goto fallback;
    Peer* peer = this->peerArray[idx];
    if (peer == NULL) goto fallback;

    TGEvent* event = new TGEvent(0x2C);
    event = FUN_006BB840(event);
    event->eventType = 0x60005;             // ET_NETWORK_DELETE_PLAYER
    event->field_0x28 = peerID;
    SetSource(event, this);
    SetDest  (event, this);
    PostEvent(&eventManager, event);

    peer->isDisconnected = 1;               // peer+0xBC
    peer->disconnectTime = currentTime;     // peer+0xB8
    return;

fallback:
    FUN_006B7590(this, peerID);
}
```

Actual array removal happens in `FUN_006B7660` on the next WSN
tick — it locates the peer, calls its destructor, and shifts the
array down.

### Event cascade

`ET_NETWORK_DELETE_PLAYER` (`0x60005`) has two registered handlers:

- **C++** — `MultiplayerGame::DeletePlayerHandler` (`FUN_006A0CA0`,
  registered by `MultiplayerGame` constructor).
- **Python** — every mission script registers a `DeletePlayerHandler`
  via `App.g_kEventManager.AddBroadcastPythonFuncHandler`.

Note: `ET_NETWORK_DISCONNECT` (`0x60003`) registers a handler at
`FUN_006A0A20`, but that handler is **empty** — a single `RET`. It
fires only on full network shutdown, not per-peer.

`DeletePlayerHandler` (C++) sends three opcodes to remaining clients:

| Opcode | Name                | Effect                                  |
|--------|---------------------|------------------------------------------|
| `0x14` | `DestroyObject`     | Removes the disconnected player's ship  |
| `0x17` | `DeletePlayerUI`    | Removes player from scoreboard          |
| `0x18` | `DeletePlayerAnim`  | "Player X has left" floating text       |

It also cleans up the player slot in the MultiplayerGame array and
any pending NetFile state (checksum/file-transfer).

`DestroyObject` (`0x14`) wire format:

```
[byte:0x14][int32:object_id]
```

`DeletePlayerAnim` reads the player name from the message stream,
looks up `Delete_Player` in `data/TGL/Multiplayer.tgl` (a format
string), creates a text animation via `FUN_0055C790`, sets opacity
`0x3FA00000` (1.25) and duration `0x40A00000` (5.0 s).

### Python `DeletePlayerHandler`

All four shipped missions have an identical implementation:

```python
def DeletePlayerHandler(TGObject, pEvent):
    pNetwork = App.g_kUtopiaModule.GetNetwork()
    if (pNetwork):
        if (pNetwork.GetConnectStatus() == App.TGNETWORK_CONNECTED
            or pNetwork.GetConnectStatus() == App.TGNETWORK_CONNECT_IN_PROGRESS):
            # We do not remove the player from the dictionary.
            # This way, if the player rejoins, his score will
            # be preserved.
            Mission1Menus.RebuildPlayerList()
    return
```

Three deliberate decisions:

1. **Score preservation** — the disconnecting player's entries are
   intentionally *not* removed from scoring dictionaries. If they
   reconnect, scores survive.
2. **Connection guard** — the handler bails out if the network is
   torn down (game-end), so the final scoreboard isn't wiped.
3. **Minimal cleanup** — only the UI player list is rebuilt; the
   C++ side handles game-object cleanup.

### Stock graceful-disconnect timeline (verified)

A `0x05` disconnect is multiplexed with stale ACKs in the same UDP
datagram (the ACK-outbox accumulates retransmits). Server responds
with an ACK, then retransmits it ~7 times at ~0.67 s intervals
(another effect of the same accumulation issue). Total processing
time to GameSpy notification: ~4.2 s.

Then a GameSpy heartbeat fires:

```
\heartbeat\0\gamename\bcommander\statechanged\1
```

`statechanged=1` tells the master server the player count has
changed; this is the only externally visible artifact.

---

## Ship death lifecycle (multiplayer)

Two important findings, verified across stock traces:

1. **`DestroyObject` (`0x14`) is NOT used for any ship death** —
   neither combat kills nor self-destruct. The handler exists at
   `FUN_006A01E0` but is never invoked for MP ship deaths.
2. **The server NEVER auto-respawns.** Every `ObjCreateTeam`
   (`0x03`) message in stock traces is a client-initiated relay
   through the host's star topology. There are zero
   server-originated `ObjCreateTeam` messages after any death.

### Combat kill

```
HP → 0 (weapon / collision / explosion damage)
  → ObjectExplodingHandler (0x006A1240)
       serializes ET_OBJECT_EXPLODING (0x0080004E) as PythonEvent (0x06,
                                       factory 0x8129)
       payload: source = killer ship, dest = dying ship, lifetime = 9.5 s
       sends reliably to "NoMe" group
  → Explosion (0x29):
       [int32: target_obj_id]
       [CompressedVec4: position]
       [CF16: damage]
       [CF16: radius]
  → SCORE_CHANGE (0x36) — kill + death credit (collision kills observed; weapon
                          kills MAY NOT fire SCORE_CHANGE on the host —
                          0 in 33.5-min battle trace with 59 weapon kills)
  → after 9.5 s explosion animation, client returns to ship selection
  → client picks new ship and sends ObjCreateTeam (0x03)
```

### Self-destruct

See `gameplay/ship-subsystems.md` for the full pipeline. Key
network-side differences from a combat kill:

- **No `Explosion` (`0x29`)** — only `ObjectExplodingEvent` triggers
  the animation.
- **No `DestroyObject` (`0x14`)** — ship persists as wreckage during
  the animation.
- `source = NULL` in the explosion event (no attacker).
- Death counted, no kill credit.
- 6 `TGSubsystemEvent` (`ET_ADD_TO_REPAIR_LIST`) for the primary
  subsystems (4 immediate + 2 late at T+9.5 s during debris
  collisions). **Stock only sends events for primary subsystems**,
  *not* per-bank/per-tube — sending 18-25 of them overflows the
  16-entry reliable retransmit queue.

### Stock packet counts (reference)

Collision-test session (28 s, 2 players, 1 collision kill):

| Opcode | Name           | Count |
|--------|----------------|------:|
| `0x29` | Explosion      |     1 |
| `0x03` | ObjCreateTeam  |     1 (client-initiated relay) |
| `0x14` | DestroyObject  |     0 |
| `0x36` | SCORE_CHANGE   |     1 |

Battle of Valentine's Day session (33.5 min, 3 players, 59 weapon
deaths):

| Opcode | Name           | Count |
|--------|----------------|------:|
| `0x29` | Explosion      |    59 |
| `0x03` | ObjCreateTeam  |    62 (3 initial + 59 client-initiated respawns) |
| `0x14` | DestroyObject  |     0 |
| `0x36` | SCORE_CHANGE   |     0 |

The SCORE_CHANGE asymmetry (1 collision-kill vs 0 weapon-kills) is
worth flagging — appears to be a stock BC bug where the scoring
handler is not registered for the weapon-kill destruction event
path. A reimplementation that wants accurate scoring should not rely
on `SCORE_CHANGE` for combat kills.

---

## Routing rules and groups

### Sending API (Python)

Two primary send functions:

```python
TGNetwork.SendTGMessage(target_id, message)
   target_id = 0   # broadcast to all peers
   target_id = N   # unicast to specific peer

TGNetwork.SendTGMessageToGroup(group_name, message)
   group "NoMe"    # all peers except the local one
   group "Forward" # all peers including the local one
```

Behaviour by role:

| Sender | `SendTGMessage(0, msg)`                       | `SendTGMessageToGroup("NoMe", msg)`            |
|--------|------------------------------------------------|------------------------------------------------|
| Client | Goes to host only (the client has 1 peer)      | Goes to host only                              |
| Host   | Goes to all clients                           | Goes to all clients (host excluded)            |

### Automatic relay

Whenever the host receives any game message via the transport layer,
it relays the message to all other clients. **Unconditional, opaque,
immediate** — no opcode inspection. This is what turns
`SendTGMessage(0, msg)` from a client into an effective broadcast.

### Python-level relay (selective)

A handful of messages get extra Python-side forwarding *on top of*
the C++ auto-relay:

- **`CHAT_MESSAGE` (`0x2C`)** — host's Python handler explicitly
  forwards via `SendTGMessageToGroup("NoMe", copy)`. Result: clients
  receive the chat twice (once via C++ relay, once via Python). Stock
  clients tolerate the duplicate.
- **`TEAM_CHAT_MESSAGE` (`0x2D`)** — host's Python forwards
  selectively to teammates only. The C++ auto-relay still sends to
  everyone, but only teammates display it.

### Filtering rules

What *does* get filtered:

1. **Transport type** — unknown transport types (no factory entry)
   silently drop at the transport layer.
2. **Connection state** — messages from disconnecting peers don't
   relay.
3. **Python handlers** ignore opcodes they don't recognise.

What does **not** get filtered:

- Game opcode value — no bounds check, no whitelist.
- Payload content — never examined during relay.
- Message size — only subject to transport-layer length limits
  (13- or 14-bit, with fragmentation for type `0x32`).

### `MAX_MESSAGE_TYPES` and Python message space

`App.MAX_MESSAGE_TYPES = 0x2B` (43) — the count of C++-dispatched
game opcodes. Python-level message types are conventionally defined
as offsets from this:

```python
CHAT_MESSAGE         = MAX_MESSAGE_TYPES + 1   # 44 = 0x2C
TEAM_CHAT_MESSAGE    = MAX_MESSAGE_TYPES + 2   # 45 = 0x2D
MISSION_INIT_MESSAGE = MAX_MESSAGE_TYPES + 10  # 53 = 0x35
```

This is convention only. Mods can use any value 0–255 — the C++
dispatchers ignore anything they don't recognise, and Python
handlers run for *every* incoming message and filter by reading the
opcode byte themselves. Known opcode-range usage:

| Range            | Used by                                         |
|------------------|--------------------------------------------------|
| `0x00`–`0x2A`    | C++ dispatchers (stock game opcodes)             |
| `0x2C`–`0x2D`    | Stock Python: chat                               |
| `0x2E`–`0x34`    | **Unused** — available for mods                  |
| `0x35`–`0x39`    | Stock Python: scoring / game flow                |
| `0x3A`–`0x3E`    | **Unused** — available for mods                  |
| `0x3F`–`0x41`    | Stock Python: team-mode scoring                  |
| `0x42`–`0xFF`    | **Unused** — available for mods                  |

Known mod allocations: Kobayashi Maru uses 205, 211–214; BC
Remastered replaces stock Python handlers at 53–57.

### Behavioural guarantees for a reimplementation

1. The host **must** relay every game message to every other client,
   regardless of opcode.
2. The opcode byte **must not** be inspected during relay.
3. Unknown opcodes **must** be silently ignored at the C++ layer.
4. Python handlers **must** fire for every incoming message — even
   ones the C++ side recognised — so mod handlers see them.
5. `"NoMe"` and `"Forward"` are routing-only groups; don't filter
   content.
6. `SendTGMessage(0, msg)` from a client **must** reach the host,
   which **must** relay to the other clients.
7. No type-byte enforcement beyond `0–255`.

---

## GameSpy

BC integrates the GameSpy QR (Query / Reporting) SDK for server-side
query response and the GameSpy ServerList SDK for client-side
browsing. All GameSpy traffic shares the game's UDP socket — packets
are demultiplexed by the leading `\` (0x5C) byte.

| Item                       | Value                                       |
|----------------------------|---------------------------------------------|
| Game name                  | `"bcommander"` (`0x00959C24`)               |
| Game version               | `60` (in status responses) / `"1.6"` (in master auth) |
| Master server (original)   | `stbridgecmnd01.activision.com` (`0x0095A4FC`, dead) |
| Master server (333networks)| Resolved from `masterserver.txt`            |
| Heartbeat port             | UDP 27900 (server → master)                 |
| Master list port           | TCP 28900 (client → master, browsing)       |
| Master verify port         | UDP 27901 (master → server, status verify)  |
| Game port (default)        | UDP 22101 (`0x5655`)                        |
| LAN scan range             | UDP 22101–22201 (`0x5655`–`0x56B9`)         |

### LAN discovery

Client click "Start Query" in `Multiplayer/MultiplayerMenus.py` →
`ET_REFRESH_SERVER_LIST` → `FUN_006AB620` dispatches by mode
(case 0 = Internet, case 2/3 = LAN) → `FUN_006AD430`.

Then `FUN_006AA720` creates a UDP socket with `SO_BROADCAST`, and
`FUN_006AA770` broadcasts `\status\` (8 bytes) to
`255.255.255.255` on every port from 22101 through 22201 — that's
**101 UDP broadcasts**.

The server's peek-based UDP router (in the C++ game loop) handles
the demultiplex:

1. `select()` checks for pending data on the shared game socket.
2. `recvfrom(MSG_PEEK)` reads the first byte.
3. If it's `\` (0x5C), consume the full packet and dispatch to
   `qr_handle_query` (`FUN_006AC1E0`).
4. Otherwise, leave it for `TGNetwork::Update`.

The query type is matched against a table at `0x0095A71C` (8 entries:
`basic`, `info`, `rules`, `players`, `status`, `packets`, `echo`,
secure-challenge). `\status\` (case 4) calls **all four** builders
sequentially.

#### Query response field order (verified)

```
\gamename\bcommander
\gamever\60
\location\1
\hostname\<server-name>           (or \hostname\*<name> if password-protected)
\missionscript\<script>           e.g. "Multiplayer.Episode.Mission1.Mission1"
\mapname\<displayName>            from Python GetMissionShortName() (e.g. "DM")
\numplayers\<count>
\maxplayers\<limit>               from Multiplayer.MissionMenusShared.g_iPlayerLimit
\gamemode\<mode>                  e.g. "openplaying" or "settings"
\timelimit\<value>                from Python g_iTimeLimit (-1 = none)
\fraglimit\<value>                from Python g_iFragLimit (-2 = none)
\system\<systemScript>            from SpeciesToSystem.GetScriptFromSpecies(g_iSystem)
\password\<0|1>
\player_<N>\<name>                one per connected player
\final\
\queryid\N.M                      N = qr_t+0x37, M = fragment counter
```

Total response is typically ~267 bytes for a 0-player server.
Fragmentation kicks in past 1349 bytes (`0x545`), splitting at
backslash boundaries; each fragment carries `\queryid\N.M` with `M`
incrementing.

The `*` prefix on hostname signals password-protection.
`gamemode` values: `"openplaying"` (in progress, accepting players),
`"settings"` (in lobby).

### Master server registration (UDP)

The master-server registration is **entirely UDP** — the dedicated
server **never uses TCP**. Clients use TCP for browsing (port 28900);
servers use UDP for heartbeats (port 27900) and verification queries
(port 27901).

Heartbeat (`qr_send_heartbeat`, `FUN_006ACA60`) format:

```
\heartbeat\<port>\gamename\bcommander
```

With state-change:

```
\heartbeat\<port>\gamename\bcommander\statechanged\<N>
```

Stock traces show `\heartbeat\0` — port 0 means "use the default
query port" (22101). The master uses this to pick the verify port.

Heartbeat timing (`qr_heartbeat_tick`, `FUN_006ABD80`):

- Every **30 s** (30000 ms check).
- Counter at `qr_t+0xE8` — stops after **10 heartbeats**.
- Heartbeat socket at `qr_t+0x04` must not be `INVALID_SOCKET`.

Verification queries arrive on UDP 27901 from one or more master
servers (e.g. 333networks's `81.205.81.173`,
`150.230.23.146`, `116.202.247.76`, `49.13.114.72`); they are
identical `\status\` queries handled by the same response builder.

### Client master-server browsing (TCP)

```
CLIENT                                           MASTER (81.205.81.173:28900)
  T+0     TCP connect ===========================>
  T+6 s   <==== \basic\\secure\<6-char challenge>     (21 bytes)
  T+6 s   Auth ===================================>
          \gamename\bcommander\gamever\1.6
          \location\0\validate\<8-char hash>
          \final\\queryid\1.1\                         (81 bytes)
  T+6 s   List request ==========================>
          \list\cmp\gamename\bcommander\final\         (36 bytes)
  T+6.5 s <==== Binary server list                    (37 bytes)
          5 entries × 6 bytes (4-byte IP BE + 2-byte port BE)
          + \final\
  T+6.6 s Client queries each server via UDP =====> (\status\ to each entry)
```

Important details:

- Master TCP port is **28900**, not 28964 as some generic GameSpy
  docs claim.
- Auth `gamever` is the string `"1.6"`, not the numeric `"60"` used
  in status responses.
- TCP `connect()` returns immediately; the challenge takes ~6 s
  (master-server processing time).

### Validate hash (GameSpy QR1 crypto)

The crypto is the well-known GameSpy QR1 SDK — modified RC4 followed
by base64. Used both server-side (responding to a master `\secure\`
challenge) and client-side (auth in the master TCP handshake).

| Item                  | Value / Address                             |
|-----------------------|---------------------------------------------|
| Secret key            | `"Nm3aZ9"` (6 bytes)                        |
| Where it's stored     | `qr_t+0x48` and `ServerList+0x2C`           |
| Constructed at        | `GameSpy::InitBrowser` (`0x0069C3A0`)        |
| Modified RC4 cipher   | `gs_rc4_cipher` (`0x006AC050`)              |
| Base64 encode         | `gs_validate_encode` (`0x006ABF70`)         |

Modified RC4: the difference from standard RC4 is in the PRGA loop
— instead of `i = (i + 1) % 256`, GameSpy uses
`i = (data[n] + 1 + i) % 256`, mixing the plaintext byte into the
S-box index before encryption. Otherwise the KSA is identical, and
the key/encrypted output goes through standard base64 (RFC-4648
alphabet).

Six input bytes produce eight output base64 chars (e.g. challenge
`"LRPOPQ"` → `"hMwdTNWS"`). Server response is
`\validate\hMwdTNWS` appended before `\final\`.

### `GameSpy` object layout (`0x0097FA7C`, 0xF4 bytes)

| Offset | Type      | Field                                        |
|--------|-----------|----------------------------------------------|
| `+0x00`| vtable*   | `PTR_FUN_00895564`                           |
| `+0x14`| `char[]`  | gameMode string ("settings", "openplaying", …) |
| `+0xDC`| `qr_t*`   | Server-side QR struct (NULL when not hosting) |
| `+0xE0`| `ServerList*`| Client-side server browser (NULL when not browsing) |
| `+0xE4`| float     | Last ServerList poll time                     |
| `+0xE8`| `void*`   | TGL file handle (`Multiplayer.tgl`)           |
| `+0xEC`| byte      | Initialised flag                              |
| `+0xED`| byte      | Active flag (tick processing enabled)         |
| `+0xEE`| byte      | `isHost` (1 server, 0 client)                 |
| `+0xEF`| byte      | `queryOnly` (skip heartbeat, LAN-only)        |

`qr_t` (selected fields, sizes inferred from accesses):

| Offset  | Field                                       |
|---------|---------------------------------------------|
| `+0x00` | Query socket                                 |
| `+0x04` | Heartbeat socket                             |
| `+0x37` | Query sequence counter (queryid `N`)        |
| `+0x38` | Fragment counter within current query        |
| `+0x48` | Secret key buffer (`"Nm3aZ9"`)               |
| `+0xC8`–`+0xD4` | basic / info / rules / players callbacks (4 fn ptrs) |
| `+0xD8` | Last heartbeat timestamp (`GetTickCount`)    |
| `+0xE4` | Packet counter for queryid generation        |
| `+0xE8` | Heartbeat repetition counter (stops at 10)   |

### `GameSpy::Tick` (`FUN_0069C440`)

```
if (+0xED == 0)         return                            ; not enabled
if (+0xEE != 0)                                            ; QR mode
    if (+0xEF != 0)     FUN_006ABCC0(+0xDC)                ; queries only
    else                FUN_006ABCA0(+0xDC)                ; queries + heartbeat
else                                                       ; browser mode
    if (enough time elapsed && +0xEC == 0)
                        FUN_006AAB40(+0xE0)                ; process server list
```

### Important caveats

- **Dead code**: `0x006AB558`–`0x006AB5BF` references
  *"Unable to resolve master"* and *"Connection to master reset"*.
  Looks like the missing init step (resolve master, fill heartbeat
  sockaddr, create/bind QR socket), but **Ghidra finds no xrefs** —
  it's unreachable. The QR system therefore never self-activates;
  the static `qr_t` at `0x0095A740` stays zeroed, sockets are 0
  (not -1), and `sendto()` to `0.0.0.0:0` fails silently. Stock
  hosted games work because the constructor wires the QR sockets
  through an alternate path; a from-scratch headless server has to
  set this up itself.
- **Heartbeat silent failure**: in stock dedi traces, `sendto()` for
  the heartbeat returned `-1` (`SOCKET_ERROR`). Despite that, three
  333networks master servers still queried back on port 27901 —
  evidently they had cached the server from a previous session or
  discovered it through other clients' query traffic.
- **Subtle field overload**: `qr_t+0x48` (secret key) overlaps with
  what Ghidra naively types as `SOCKET[]` when it auto-types
  `param_1` as `SOCKET*`. The struct is mixed-type; the secret key
  *is* there at byte offset 0x48 from the qr_t base.

---

## Cross-references

The on-the-wire layouts of all the opcodes mentioned here live in
the protocol docs:

- `protocol/wire-format-and-opcodes.md` — opcode dispatch table,
  stream primitives, transport layer detail.
- `protocol/state-and-events.md` — StateUpdate variants, ObjCreate,
  PythonEvent, TGMessage routing.
- `protocol/per-feature-protocols.md` — collision-effect,
  set-phaser-level, delete-player-ui, CF16 explosion encoding.

For self-destruct / death scoring details:
`gameplay/ship-subsystems.md` and `gameplay/combat-and-damage.md`.

For the runtime that calls `TGNetwork::Update` and the registered
handler tables: `architecture/runtime-and-main-loop.md`.
