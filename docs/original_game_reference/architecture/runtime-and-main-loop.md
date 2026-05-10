# Runtime, Main Loop, and Mission Infrastructure

Reference notes on how the stock `stbc.exe` runtime is structured: the
application class hierarchy, the per-frame loop, the engine's two time
streams, the `MultiplayerGame` object that hosts a session, and the
two-layer (C++ / Python) mission system that actually runs gameplay.

The intent here is "what the binary does" — not how to instrument it,
not how to patch it, not how a third-party dedicated server bolts onto
it. Where memory addresses appear they are from the stock 1.0 retail
binary; the executable is not ASLR-enabled, so the values are stable.

---

## Application class hierarchy

The engine layers on top of NetImmerse 3.1 (Gamebryo's pre-1.2 ancestor).
Three classes form the application stack:

```
NiApplication           # NI engine base class (vtable @ 0x008988d4)
  └── TGApp             # Totally Games' application layer (vtable @ 0x00889a98)
        └── UtopiaApp   # BC-specific app (vtable @ 0x00895b8c)
```

Each subclass overrides only the slots it needs; everything else falls
through to the base. Notable slots in the final `UtopiaApp` vtable:

| Slot | Offset | Function          | Owner       | Notes                                                |
|------|--------|-------------------|-------------|------------------------------------------------------|
| 1    | 0x04   | `Initialize`      | NiApp base  | Not overridden by `UtopiaApp`                        |
| 12   | 0x30   | `EnableFrameRate` | UtopiaApp   | Toggles the on-screen FPS counter                    |
| 21   | 0x54   | `UpdateInput`     | UtopiaApp   |                                                      |
| 24   | 0x60   | `OnIdle`          | UtopiaApp   | Called every frame; does the game step               |
| 29   | 0x74   | `MeasureTime`     | NiApp base  | **Stub in BC's NI 3.1 build — always returns false** |
| 30   | 0x78   | `Process`         | NiApp base  | The main-loop body (PeekMessage)                     |
| 31   | 0x7C   | `OnWindowResize`  | UtopiaApp   |                                                      |
| 37   | 0x94   | `UpdateTime`      | TGApp       | TGApp time scaling                                   |

`UtopiaApp` itself is `0xBC` bytes; it is allocated and constructed by
`FUN_00437f50`, then `Initialize` is invoked, then `MainLoop`, then
`Terminate`.

---

## The main loop

The whole program is the standard `NiApplication` PeekMessage idle
loop. There is no `Sleep`, no `WaitMessage`, no vsync wait — tick rate
is whatever the CPU can manage, modulated only by a soft frame-rate
limiter that gates *rendering readiness* and not game logic.

`MainLoop` (`FUN_007ba5a0`) just spins on `Process`:

```c
void MainLoop() {
    int retval;
    while (this->Process(&retval)) { /* loop */ }
}
```

`NiApplication::Process` (`FUN_007b8790`, vtable slot 30) is the
canonical Win32 message-pump idle loop, *not* overridden by BC:

```c
bool NiApplication::Process(int* pRetval) {
    MSG msg;
    if (PeekMessage(&msg, NULL, 0, 0, PM_REMOVE)) {
        if (msg.message == WM_QUIT) { *pRetval = msg.wParam; return false; }
        TranslateAccelerator(...); TranslateMessage(&msg); DispatchMessage(&msg);
    } else {
        this->OnIdle();   // vtable slot 24 — UtopiaApp's per-frame step
    }
    return true;
}
```

Because there is no yield, `OnIdle` runs as fast as the host can call
it. With a renderer attached, the GPU's `Present`/swap eventually
blocks; without one (a stock dedicated server), the loop saturates a
core at thousands of frames per second.

### `OnIdle` (UtopiaApp override, `FUN_006cdd20`)

The frame step:

1. `UpdateTime()` — vtable slot 37, advances the clocks.
2. Frame-rate gate: if `m_fLastFrame + m_fMinFramePeriod ≤ m_fAccumTime`,
   set `readyToRender = true` and update `m_fLastFrame`. Otherwise
   `readyToRender = false`. **This gates rendering only**; logic still
   runs on every iteration.
3. Frame-rate display sample/update (when enabled).
4. Sound module update (`FUN_006e6420`, `FUN_006e6430`).
5. Increment frame counter (`m_iClicks`, `+0x64`).
6. App-state machine: transition `BeginGame()` and `EndGame()` when
   `appState` flips.

`MeasureTime` (slot 29) is a stub that always returns `false`. The
Gamebryo 1.2 base implementation of `OnIdle` consults it as a frame
gate; BC's overridden `OnIdle` ignores it and does the comparison
itself directly against `m_fAccumTime`/`m_fMinFramePeriod`.

### MainTick (`FUN_0043b4f0`)

The actual per-frame game step runs in `MainTick`, reached through the
scene-graph update path. Its sequence:

1. `NiClock::Update` — read `timeGetTime()` / QPC, advance the clock.
2. `TGTimerManager#1.Update(gameTime)` — game-time timers.
3. `TGTimerManager#2.Update(frameTime)` — wall-clock timers.
4. `TGEventManager.ProcessEvents` — drain the event queue.
5. Generic update at `0x9817a8`.
6. Frame budget scheduler (`FUN_0046f420`) — runs registered updateables.
7. Save-game processing.
8. Load-game filename + load-game data.
9. Scene-graph update + Python `OnIdle`.
10. (If renderer present) renderer update.
11. Render / display.
12. Scene-manager update + post-frame update.

Network is *not* pumped directly from `MainTick`. `TGWinsockNetwork::Update`
(`0x006b4560`) is registered as an updateable in the frame budget
scheduler with a 15-second time budget for incoming-message processing
before yielding (see `NET_TIME_BUDGET = 15.0f` at `0x008958cc`).

---

## Time

Two clock objects, two related-but-distinct time fields, and two timer
managers. Confusing them is easy.

### `NiClock` (`0x0099c6b0`)

Global timer object, separate from the `NiApplication` singleton. It
gets touched once per `MainTick` and is the source of the per-frame
delta:

| Offset | Type           | Field          | Notes                                            |
|--------|----------------|----------------|--------------------------------------------------|
| +0x08  | `DWORD`        | `lastTimeMs`   | Previous `timeGetTime()`                         |
| +0x0C  | `float`        | `accumTimeSec` | Running wall-clock seconds                       |
| +0x10  | `DWORD`        | `accumTimeMs`  | Running wall-clock milliseconds                  |
| +0x14  | `float`        | `deltaTimeSec` | Frame delta, seconds                             |
| +0x18  | `DWORD`        | `deltaTimeMs`  | Frame delta, milliseconds                        |
| +0x1C  | `bool`         | `useQPC`       | Use `QueryPerformanceCounter` instead of `tGT()` |
| +0x20  | `LARGE_INTEGER`| `qpcBase`      | QPC base, set on first update                    |
| +0x28  | `LONGLONG`     | `qpcFreq`      | From `QueryPerformanceFrequency`                 |
| +0x34  | `bool`         | `resetFlag`    | Forces re-read of base time on next update       |
| +0x38  | `int`          | `frameCount`   | Incremented per update                           |

`NiClock::Update` (`FUN_0071a9e0`) increments `frameCount`, samples
`timeGetTime()`, computes `deltaMs = now - lastTimeMs`, and folds the
delta into `accumTime{Ms,Sec}` and `deltaTime{Ms,Sec}`. Constant
`MS_TO_SEC = 0.001f` lives at `0x00894a1c`.

### `NiApplication` time fields (`g_Clock = 0x009a09d0`)

These live on the application singleton itself:

| Offset | Type    | Field               | Notes                                                  |
|--------|---------|---------------------|--------------------------------------------------------|
| +0x54  | `float` | `m_fCurrentTime`    | Wall-clock seconds, fed into TGTimerManager#2          |
| +0x58  | `float` | `m_fLastTime`       | Previous `m_fCurrentTime` (-1.0 = uninitialised)       |
| +0x5C  | `float` | `m_fDeltaTime`      | Frame delta in seconds                                 |
| +0x60  | `float` | `m_fAccumTime`      | Accumulated time in seconds                            |
| +0x64  | `int`   | `m_iClicks`         | Frame counter                                          |
| +0x74  | `float` | `m_fMinFramePeriod` | **`1/60 = 0.01667f`** (BC override of NiApp's `1/100`) |
| +0x78  | `float` | `m_fLastFrame`      | Previous accum-time at which a render was admitted     |

The frame-rate cap constant is encoded in BC's `UtopiaApp` constructor
as the literal `0x3c888889` (`1/60`). The base `NiApplication`
constructor uses `0x3c23d70a` (`1/100`).

### TGApp time fields (`g_Clock + 0x8C`)

Layered on top, the TGApp section adds the *scaled* game clock used by
gameplay:

| Offset | Type    | Field          | Notes                                                                    |
|--------|---------|----------------|--------------------------------------------------------------------------|
| +0x90  | `float` | `gameTime`     | Scaled game time, fed into TGTimerManager#1                              |
| +0x94  | `float` | `timeScaleMax` | Time scale upper bound                                                   |
| +0x9C  | `float` | `timeRate`     | Game-time rate multiplier (default 1.0; SWIG: `UtopiaModule.SetTimeRate`)|
| +0xA0  | `float` | `maxTimeRate`  | Maximum allowed time rate (default 1.0)                                  |

`gameTime` advances as `gameTime += deltaTime * timeRate`; with
`timeRate = 1.0` it tracks wall time. Setting it to `0.0` freezes the
scaled clock without touching wall time, which is how the engine gates
the AI and Python timers without affecting wall-clock things like
sound or input.

---

## TGTimerManager

Two instances live in static memory:

- `0x0097F898` — driven by `gameTime` (`g_Clock+0x90`); these are the
  *game-logic* timers, scaled by `timeRate`.
- `0x0097F810` — driven by `frameTime` (`g_Clock+0x54`); these are the
  *wall-clock* timers, unaffected by time scaling.

`TGTimerManager::Update` (`FUN_006dc490`) walks a sorted list of
`TGTimer` objects. For every timer whose fire time is `<= now`, it
posts the timer's event to the `TGEventManager` (`0x0097F838`).
Repeating timers are rescheduled.

Python sees these as `g_kTimerManager` (game time) and
`g_kRealtimeTimerManager` (wall clock). They are completely
independent.

---

## Frame budget scheduler (`FUN_0046f420`)

The scheduler that actually runs registered updateables — ships, AI,
physics, network pump, etc. Its design lets heavy objects coexist with
light ones without starvation:

- A 16-sample ring buffer of past frame times lives at `DAT_00981560`.
- The average frame time (with min/max excluded) becomes the budget.
- Updateables are organised into 4 priority tiers (0..3, with tier 0
  being the highest-priority "always run" tier).
- Each tier is time-sliced: objects update until the budget is
  exhausted.
- A round-robin counter at `DAT_009815e4` rotates which tier gets the
  first pick of the budget.
- If the first tier finishes inside its slice, leftover budget cascades
  to subsequent tiers.

This is why Python only meaningfully uses `NORMAL` and `LOW` priorities —
the other levels are bookkeeping for the C++ side of the scheduler.

---

## Sleep usage

The binary issues `Sleep` from exactly four call sites, and *none of
them are in the main loop*:

| Address     | Context                                      | Duration |
|-------------|----------------------------------------------|----------|
| `0x006acda5`| GameSpy query response loop (`FUN_006aa680`) | 10 ms    |
| `0x00768988`| `py_time_sleep` (Python `time.sleep()`)      | variable |
| `0x0085867b`| CRT thread sync                              | 1 ms     |
| `0x0085cd47`| CRT thread sync                              | 1 ms     |

A reimplementation that wants a target tick rate has to add its own
yield; the stock engine simply runs flat-out.

---

## Engine globals

A handful of well-known addresses inside `stbc.exe` are load-bearing
and stable across runs. Anything that reaches across the C++/Python
boundary or pokes engine state goes through these.

| Address      | Type    | Name / Purpose                                                  |
|--------------|---------|-----------------------------------------------------------------|
| `0x0097FA00` | struct  | `UtopiaModule` base — root of the engine object hierarchy       |
| `0x0097FA78` | ptr     | `TGWinsockNetwork*` (UtopiaModule+0x78) — network singleton     |
| `0x0097FA7C` | ptr     | `GameSpy*` (+0xDC = `qr_t`) — LAN discovery                     |
| `0x0097FA80` | ptr     | `NetFile` / checksum manager (UtopiaModule+0x80)                |
| `0x0097FA88` | byte    | `IsClient` (0=host, 1=client)                                   |
| `0x0097FA89` | byte    | `IsHost`   (1=host, 0=client)                                   |
| `0x0097FA8A` | byte    | `IsMultiplayer`                                                 |
| `0x0097FA84` | int     | This client's player slot (0–15)                                |
| `0x0097FA8C` | int     | This client's base object ID (`slot*0x40000 + 0x3FFFFFFF`)      |
| `0x0097FAA2` | byte    | Settings byte 2 (friendly-fire toggle)                          |
| `0x008E5F59` | byte    | `g_SettingsByte1` (collision-damage toggle, etc.)               |
| `0x0097E238` | ptr     | Active `MultiplayerGame` / TopWindow                            |
| `0x009A09D0` | ptr     | Application clock (`+0x54` frameTime, `+0x90` gameTime)         |
| `0x0097F838` | ptr     | `TGEventManager`                                                |
| `0x0097F898` | obj     | TGTimerManager #1 (game time)                                   |
| `0x0097F810` | obj     | TGTimerManager #2 (wall time)                                   |
| `0x0097E9C8` | int*    | Set list pointer (game sets / map regions)                      |
| `0x0097E9CC` | int     | Set count                                                       |
| `0x0099EE38` | int     | Python nesting counter (must be `0` for `PyRun_String`)         |

---

## Engine-side network/multiplayer initialization

Independent of any third-party bootstrap, the engine itself initialises
the network subsystem via `UtopiaModule::InitializeNetwork`
(`FUN_00445D90`). Called as a `__thiscall` on `UtopiaModule`
(`0x0097FA00`), it:

1. Allocates a `TGWinsockNetwork` (`0x34C` bytes), stores the pointer
   at `UtopiaModule+0x78` (`0x0097FA78`).
2. Sets the listen port (`+0x338`) via `FUN_006B9BB0` (default
   `0x5655` = 22101).
3. Calls `TGNetwork::HostOrJoin` (`0x006B3EC0`) which creates the
   socket and sets the connection state.
4. Allocates `NetFile` (`0x48` bytes) via `FUN_006A30C0`, stores at
   `UtopiaModule+0x80` (`0x0097FA80`).
5. Allocates `GameSpy` (`0xF4` bytes), stores at `UtopiaModule+0x7C`
   (`0x0097FA7C`).

Later, `TopWindow_SetupMultiplayerGame` (`FUN_00504F10`) constructs
the `MultiplayerGame` session object and stores its pointer at
`0x0097E238`. This is the function the `0x01 GameInit` opcode handler
calls on a joining client.

A counter-intuitive detail: `TGNetwork`'s connection state is `2` for
the host and `3` for the client, *not* the other way round.

GameSpy and the gameplay traffic share a single UDP socket (stored at
`WSN+0x194`), so any inbound peek that sees a leading `\` is a
GameSpy query and everything else is encrypted gameplay traffic.

---

## `MultiplayerGame` object layout

`MultiplayerGame` (vtable `PTR_FUN_0088B480`) inherits from `Game` and
hosts a single multiplayer session. Key fields:

| Offset | Type      | Field                | Notes                                                   |
|--------|-----------|----------------------|---------------------------------------------------------|
| +0x00  | vtable*   | `vtable`             | `0x0088B480`                                            |
| +0x70  | ptr       | `episodePtr`         | Current `Episode` (mission script via `+0x3C+0x14`)     |
| +0x74  | slot[16]  | `playerSlots`        | 16 × 0x18-byte player-slot structs                      |
| +0x1F8 | byte      | `readyForNewPlayers` | 1 = accepting connections                               |
| +0x1FC | int       | `maxPlayers`         | Capped at 16 in the constructor                         |

Each player slot is `0x18` bytes:

```
+0x00 byte  inGameFlag      (initialized = 1)
+0x04 byte  active          (1 if connected)
+0x08 int   connID          (peer ID)
+0x10 int   baseObjectID    (slot*0x40000 + 0x3FFFFFFF — 262,144 IDs/slot)
```

The constructor (`FUN_0069E590`):

1. Initialises 16 slots via `FUN_006A7770` (one helper per slot).
2. Stamps the vtable, clamps `maxPlayers` to 16.
3. Registers a fixed table of C++ event handlers (see below).
4. If multiplayer:
   - Creates network groups `"NoMe"` (`0x008E5528`) and `"Forward"`
     (`0x008D94A0`).
   - Registers eight host-only handlers in addition to the always-on
     ones.
5. Final loop: temporarily clears `g_IsHost` to drain any pending
   actions, restores it.
6. Copies `g_SettingsByte2` to the settings pane.

Two object-ID arithmetics are worth keeping in mind:

- Allocate a slot's IDs: `baseID = slot * 0x40000 + 0x3FFFFFFF`.
- Recover slot from ID: `slot = (objID - 0x3FFFFFFF) >> 18`.

### Network groups

Stored on the `TGWinsockNetwork`:

- `WSN+0xF4` — group-array pointer
- `WSN+0xF8` — group count
- `WSN+0xFC` — group capacity

Each group is a sorted `{name, memberList}` searched by binary search.
The two used by the game:

| Group       | Address      | Membership                          | Used for                                |
|-------------|--------------|-------------------------------------|------------------------------------------|
| `"NoMe"`    | `0x008E5528` | All peers **except** the local one  | Score broadcasts (don't echo to yourself)|
| `"Forward"` | `0x008D94A0` | All peers including the local one   | Event relay (StartFiring etc.)           |

---

## Event handler registration

The `MultiplayerGame` constructor registers a fixed catalogue of C++
event handlers with `TGEventManager`. The complete table:

| Event ID    | Handler                       | Mode      | Purpose                              |
|-------------|-------------------------------|-----------|---------------------------------------|
| `0x60001`   | `ReceiveMessage`              | Always    | Network message dispatch              |
| `0x60003`   | `DisconnectHandler`           | Always    | Player disconnect                     |
| `0x60004`   | `NewPlayerHandler`            | Always    | New player detected                   |
| `0x60005`   | `DeletePlayerHandler`         | Always    | Player removed                        |
| `0x008000C8`| `ObjectCreatedHandler`        | Always    | Object creation notify                |
| `0x008000DF`| `HostEventHandler`            | MP only   | `AddToRepairList` forwarding          |
| `0x00800074`| `HostEventHandler`            | MP only   | Event forwarding                      |
| `0x00800075`| `HostEventHandler`            | MP only   | Event forwarding                      |
| `0x008000E8`| `SystemChecksumPassedHandler` | MP only   | Checksum pass                         |
| `0x008000E7`| `SystemChecksumFailedHandler` | MP only   | Checksum fail                         |
| `0x008000E6`| `ChecksumCompleteHandler`     | MP only   | All checksums done                    |
| `0x0080005D`| `EnterSetHandler`             | MP only   | Set transition                        |
| `0x008000C5`| `ExitedWarpHandler`           | MP only   | Warp complete                         |
| `0x0080004E`| `ObjectExplodingHandler`      | Always    | Object death/explosion                |
| `0x008000F1`| `NewPlayerInGameHandler`      | Always    | Player join handshake (opcode 0x2A)   |
| `0x008000D8`| `StartFiringHandler`          | Always    | Weapon fire start                     |
| `0x008000DA`| `StopFiringHandler`           | Always    | Weapon fire stop                      |
| `0x008000DC`| `StopFiringAtTargetHandler`   | Always    | Stop fire at target                   |
| `0x008000DD`| `SubsystemStatusHandler`      | Always    | Subsystem toggle                      |
| `0x00800076`| `RepairListPriorityHandler`   | Always    | Repair priority                       |
| `0x008000E0`| `SetPhaserLevelHandler`       | Always    | Phaser intensity                      |
| `0x008000E2`| `StartCloakingHandler`        | Always    | Cloak engage                          |
| `0x008000E4`| `StopCloakingHandler`         | Always    | Cloak disengage                       |
| `0x008000EC`| `StartWarpHandler`            | Always    | Warp engage                           |
| `0x008000FE`| `TorpedoTypeChangeHandler`    | Always    | Torpedo type switch                   |
| `0x00800058`| `ChangedTargetHandler`        | SP only   | Target change (single-player)         |

---

## Game startup flow

Once both peers' file checksums pass, the host drives the joining
client through the rest of session setup with two opcodes followed by
`InitNetwork`.

```
Host                                         Joining Client
 │                                                │
 │── 0x00 Settings (gameTime, settings, slot, ──>│
 │   mission name, checksum flag)                │  FUN_00504D30
 │── 0x01 GameInit (single byte) ─────────────→ │  CreateMultiplayerGame
 │                                                │   ↳ both sides build MultiplayerGame
 │                                                │   ↳ Python: AI.Setup.GameInit
 │                                                │   ↳ Python: Episode loads mission
 │                                                │
 │── 0x35 MISSION_INIT (limits, system, time) ─→│  Python: <Mission>.InitNetwork
 │── 0x37 SCORE × N (existing players) ───────→ │  ditto
 │── 0x2A NewPlayerInGame (object replication) →│  FUN_006A1E70
 │                                                │
 │   <══ 0x06 PythonEvent (gameplay events) ══>  │  Bidirectional via Forward group
 │   <══ 0x07–0x12 action events ═══════════>  │
 │   <══ 0x15 CollisionEffect (host-only) ═══>  │
 │   <══ 0x29 Explosion (host-only AoE) ═════>  │
 │                                                │
 │── 0x36 SCORE_CHANGE (per kill, NoMe group) ─→│
 │── 0x38 END_GAME (broadcast) ───────────────→ │
 │── 0x39 RESTART_GAME (broadcast) ───────────→ │
```

### Phase 1 — Settings (opcode `0x00`, `FUN_00504D30`)

The host's `ChecksumCompleteHandler` (`0x006A1B10`) builds the
Settings packet with these fields, in order:

```
float    gameTime              (g_Clock+0x90 — sync the scaled clock)
byte     g_SettingsByte1       (collision toggle etc.)
byte     UtopiaModule+0xB4     (extra settings)
byte     playerSlotIndex
short    mapNameLen
bytes    mapName               (mission script path)
byte     checksumFlag
[…]      checksum match data   (only if flag != 0)
```

The client's handler stores `gameTime`, the settings bytes, the
assigned slot, and crucially writes the mission name to
`g_kVarManager.SetStringVariable("Multiplayer", "Mission", mapName)`
via `FUN_0044B500`. That's the channel by which the *client* learns
which mission script to load — Python reads it back later out of
`VarManager`.

### Phase 2 — GameInit (opcode `0x01`, `FUN_00504F10`)

A single byte. On receipt:

1. `TG_CallPythonFunction("AI.Setup", "GameInit")` — preloads ~73 AI
   modules so subsequent script imports don't hitch.
2. `new MultiplayerGame("Multiplayer.MultiplayerGame", 16)` — runs the
   constructor described above; this also triggers
   `MultiplayerGame.Initialize` on the Python side, which loads the
   episode and ultimately the mission.
3. Reads `Multiplayer.MissionMenusShared.g_iPlayerLimit` via
   `FUN_006F8650` and writes it to `MultiplayerGame+0x1FC`.

### Phase 3 — `NewPlayerInGame` (opcode `0x2A`, `FUN_006A1E70`)

The most complex handler. For each joining `connID`:

1. Reads a `team` byte from the stream into the slot.
2. Posts an `ET_NEW_PLAYER_IN_GAME` event to itself.
3. Calls Python: `mission.InitNetwork(connID)` on the active mission
   script (e.g. `Multiplayer.Episode.Mission1.Mission1`). That call
   sends the Python-level `MISSION_INIT` and `SCORE` messages.
4. Iterates every set in `0x0097E9C8`, every alive object with
   `+0xEC != 0`, and replicates it to the new peer:
   - Opcode `0x02` (`ObjCreate`) or `0x03` (`ObjCreateTeam` if the
     object has a team byte at `+0x2E4`).
   - The object's vtable slot `+0x10C` (`WriteToStream`) serialises
     the body.
   - Reliable, **unordered** (`preserveOrder = 0`).
5. If the object is type `0x8007`, sends supplemental data via
   `FUN_00595C60`.
6. Adds `connID` to both `"NoMe"` and `"Forward"` groups.

### Phase 4 — Steady state

The MainTick loop pumps the network, drains the event queue, and runs
updateables. Score changes, ship-ability messages, and gameplay
broadcasts all flow over the same `TGWinsockNetwork` socket through
the registered handlers above.

---

## The C++ / Python split

The C++ engine is *mission-agnostic*: it provides object lifecycle,
event dispatch, network transport, state synchronisation, collision,
and the main loop. Game-mode rules (team rules, time/frag limits,
scoring) live entirely in Python under `scripts/Multiplayer/`.

There are exactly three C++→Python call points during session setup:

1. `AI.Setup.GameInit()` — during `CreateMultiplayerGame`.
2. `Multiplayer.MissionMenusShared.g_iPlayerLimit` — variable read.
3. `<mission>.InitNetwork(connID)` — during `NewPlayerInGame`.

The bridge function is `TG_CallPythonFunction` (`0x006F8AB0`):

```c
int TG_CallPythonFunction(
    const char* modulePath,    // dotted path, e.g. "Multiplayer.Episode.Mission1.Mission1"
    const char* functionName,  // e.g. "InitNetwork"
    const char* formatString,  // Py_BuildValue format, e.g. "i"
    int         argPtr,        // pointer to the args
    const char* typeString);   // optional validation
```

It acquires the GIL via `FUN_0074BBF0(1)`, imports, fetches the
attribute, builds an args tuple (when `typeString` is present),
invokes, and releases the GIL. `FUN_006F8650` is a thinner wrapper
for "read a Python variable into C".

### Module hierarchy

```
Multiplayer/
  MultiplayerGame.py      # game-level (loaded by C++ ctor)
  MissionShared.py        # message types, scoring, timers
  MissionMenusShared.py   # ship-select / end-game UI
  SpeciesToShip.py
  SpeciesToSystem.py
  SpeciesToTorp.py
  Modifier.py             # damage class modifiers
  Episode/
    Episode.py            # reads "Mission" var, loads mission
    Mission1/Mission1.py  # FFA deathmatch
    Mission2/Mission2.py  # team deathmatch (generic team labels)
    Mission3/Mission3.py  # team deathmatch (faction labels)
    Mission5/Mission5.py  # Starbase Defense (requires StarbaseAI)
```

The script loading chain is straight: C++ instantiates `MultiplayerGame`
from `"Multiplayer.MultiplayerGame"`, which calls `Initialize`, which
calls `LoadEpisode("Multiplayer.Episode.Episode")`, which reads the
mission name from `g_kVarManager` and calls `LoadMission`, which
calls the mission's `Initialize`. `MissionShared.Initialize` is
called from each mission's `Initialize` for common setup
(`ET_NETWORK_MESSAGE_EVENT` handler, scan UI handler, etc.).

### Available stock missions

| ID        | Script                                    | Type                      | Teams | AI required           | Shipped |
|-----------|-------------------------------------------|---------------------------|-------|-----------------------|---------|
| Mission1  | `Multiplayer.Episode.Mission1.Mission1`   | FFA deathmatch            | No    | No                    | Yes     |
| Mission2  | `Multiplayer.Episode.Mission2.Mission2`   | Team deathmatch (generic) | 2     | No                    | Yes     |
| Mission3  | `Multiplayer.Episode.Mission3.Mission3`   | Team deathmatch (faction) | 2     | No                    | Yes     |
| Mission4  | —                                         | —                         | —     | —                     | Cut     |
| Mission5  | `Multiplayer.Episode.Mission5.Mission5`   | Starbase Defense          | 2     | Yes (`StarbaseAI`)    | Yes     |
| Mission6  | —                                         | Starbase variant          | —     | Yes                   | Cut     |
| Mission7  | —                                         | Borg Hunt                 | —     | Yes                   | Cut     |
| Mission9  | —                                         | Enterprise Defense        | —     | Yes                   | Cut     |

Mission2 vs Mission3 is purely cosmetic: same code, different team
labels (generic `"Team N"` vs localised `"Federation Team Name"` /
`"NonFed Team Name"`). Team membership in both is player-chosen, not
inferred from species.

---

## Python-level message catalogue

These messages bypass the C++ dispatcher entirely. They are sent via
`TGNetwork.SendTGMessage` from Python and arrive at a Python
`ET_NETWORK_MESSAGE_EVENT` handler. Type values are
`App.MAX_MESSAGE_TYPES + N` where `MAX_MESSAGE_TYPES = 0x2B`.

| Hex    | Constant                | Direction              | Size       | Purpose                                  |
|--------|-------------------------|------------------------|------------|------------------------------------------|
| `0x35` | `MISSION_INIT_MESSAGE`  | Host → joiner          | 4 or 8 B   | Mission limits + assigned star system    |
| `0x36` | `SCORE_CHANGE_MESSAGE`  | Host → "NoMe"          | 10+ B      | Per-kill score broadcast                 |
| `0x37` | `SCORE_MESSAGE`         | Host → joiner          | 17 B       | Per-player score sync on join            |
| `0x38` | `END_GAME_MESSAGE`      | Host → all (broadcast) | 5 B        | End round with reason code               |
| `0x39` | `RESTART_GAME_MESSAGE`  | Host → all (broadcast) | 1 B        | Restart round                            |
| `0x3F` | `SCORE_INIT_MESSAGE`    | Host → joiner (team)   | 18 B       | `0x37` plus team byte                    |
| `0x40` | `TEAM_SCORE_MESSAGE`    | Host → all (team)      | 10 B       | Per-team kills/score                     |
| `0x41` | `TEAM_MESSAGE`          | Client → host → all    | 6 B        | Team selection (host forwards to "NoMe") |

All carry `SetGuaranteed(1)` (reliable). Wire layouts:

```
0x35 MISSION_INIT
  byte   playerLimit          (1..8)
  byte   systemSpecies        (SpeciesToSystem index)
  byte   timeLimit            (255 = no limit, else minutes)
  [int   endTime]             (only if timeLimit != 255 — absolute gameTime)
  byte   fragLimit            (255 = no limit, else frag count)

0x36 SCORE_CHANGE
  long   killerPlayerID       (0 = self-destruct/AI)
  [long  killerKills]
  [long  killerScore]         (the [..] block only if killerPlayerID != 0)
  long   killedPlayerID
  long   killedDeaths
  byte   additionalScoreCount (N damage contributors)
  N × { long playerID; long playerScore }

0x37 SCORE
  long   playerID
  long   kills
  long   deaths
  long   score

0x38 END_GAME
  int    reason               (END_* enum below)

0x39 RESTART_GAME
  (no payload)

0x3F SCORE_INIT (team modes)
  long   playerID
  long   kills
  long   deaths
  long   score
  byte   teamID               (0 or 1; 255 = INVALID_TEAM)

0x40 TEAM_SCORE (team modes)
  byte   teamID
  long   teamKills
  long   teamScore

0x41 TEAM (team modes)
  long   playerID
  byte   teamID
```

End-game reason codes:

| Code | Constant                  | Notes                              |
|------|---------------------------|------------------------------------|
| `0`  | `END_ITS_JUST_OVER`       | Generic                            |
| `1`  | `END_TIME_UP`             | Time limit expired                 |
| `2`  | `END_NUM_FRAGS_REACHED`   | Frag limit reached                 |
| `3`  | `END_SCORE_LIMIT_REACHED` | Score limit reached                |
| `4`  | `END_STARBASE_DEAD`       | Mission5                           |
| `5`  | `END_BORG_DEAD`           | Cut Mission7 (referenced in code)  |
| `6`  | `END_ENTERPRISE_DEAD`     | Cut Mission9 (referenced in code)  |

`endTime` in `MISSION_INIT` is computed as
`g_iTimeLeft + int(GetGameTime())` — an absolute scaled-clock value the
client subtracts from `GetGameTime()` to display the remaining time.

---

## Scoring system

All scoring runs server-side; clients are passive receivers.

### Damage accumulation (host only)

`DamageEventHandler` listens on `ET_WEAPON_HIT`. It only tracks damage
to player ships (`IsPlayerShip() == 1`). Storage is a per-victim,
per-attacker dictionary:

```
g_kDamageDictionary[shipObjID][attackerPlayerID] = [shieldDmg, hullDmg]
```

Every accumulation is multiplied by
`Modifier.GetModifier(attackerClass, targetClass)`. The stock modifier
table:

```python
g_kModifierTable = (
    (1.0, 1.0, 1.0),   # class 0 (unknown) attacking 0/1/2
    (1.0, 1.0, 1.0),   # class 1 (every stock ship)
    (1.0, 3.0, 1.0))   # class 2 (none in stock) — 3x bonus killing class 1
```

Every stock ship is class 1, so the modifier is always `1.0` in
vanilla. The `class 2 → class 1` 3x is a modding hook that never fires
in the shipped game.

In team modes, if attacker and target are on the same team, the damage
is **negated** (`fDamage = -fDamage`), so accumulating same-team
damage subtracts from the attacker's score.

### Kills and frag/score limits

`ObjectKilledHandler` listens on `ET_OBJECT_EXPLODING` (host only):

- Awards the kill to `event.GetFiringPlayerID()`; awards the death to
  `ship.GetNetPlayerID()`.
- Score accrues to **every** player who damaged the destroyed ship as
  `score = (shieldDmg + hullDmg) / 10.0`.
- Sends `SCORE_CHANGE_MESSAGE` (`0x36`) to the `"NoMe"` group.
- In team modes, only awards the frag if attacker and victim are on
  *different* teams; otherwise increments the team-kills counter only.

After every kill, `CheckFragLimit()` runs:

- FFA (Mission1): if `g_iUseScoreLimit`, check
  `score >= fragLimit * 10000`; otherwise check `kills >= fragLimit`.
- Team (Mission2/3): same comparison against the team's totals.

If the limit is reached, the host calls `EndGame(END_SCORE_LIMIT_REACHED)`
— the same reason constant is used for both score and frag limits.

### Score preservation on disconnect

When `ET_NETWORK_DELETE_PLAYER` fires, scoring-dictionary entries are
**not** removed. A reconnecting player keeps their previous score and
it gets re-synced via `SCORE`/`SCORE_INIT` on rejoin.

### EndGame flow

1. Host calls `EndGame(reason)`.
2. Builds `END_GAME_MESSAGE` (`0x38`), broadcasts to `targetID = 0`,
   guaranteed.
3. Host sets `ReadyForNewPlayers(0)` so no new connections come in.
4. Each client's `MissionShared.ProcessMessageHandler`:
   - Sets `g_bGameOver = 1`.
   - Calls `ClearShips()` (removes player ships and torpedoes).
   - Shows the end-game dialog with the localised reason text.
   - For mission-specific endings (Starbase/Borg/Enterprise dead),
     stamps the corresponding mission globals.

### RestartGame flow

1. Host receives `ET_RESTART_GAME` (UI button).
2. Sends `RESTART_GAME_MESSAGE` (`0x39`) to all peers (broadcast).
3. Every node executes `RestartGame`:
   - Zeros all scoring dictionaries (kills, deaths, scores, damage —
     keys preserved).
   - Zeros team dictionaries.
   - Clears `g_bGameOver`.
   - Calls `ClearShips()`.
   - Resets `g_iTimeLeft = g_iTimeLimit * 60`.
   - Returns to ship-selection UI.

### Time management

`CreateTimeLeftTimer(iTimeLeft)` arms a 1-second countdown timer.
`UpdateTimeLeftHandler` decrements `g_iTimeLeft` per tick. When it
hits 0, the host calls `EndGame(END_TIME_UP)`. `g_iTimeLeft` is
stored in seconds (`g_iTimeLimit * 60`).

---

## Mission system specifics

### Other in-band C++ handlers

A few additional handlers are worth knowing about even though they
don't fit the `MultiplayerGame` event table — they appear on the same
opcode dispatcher:

| Opcode | Function     | Purpose                                                      |
|--------|--------------|--------------------------------------------------------------|
| `0x13` | `FUN_006A01B0`| Host-only "self-destruct" via overloading the power subsystem |
| `0x1F` | `FUN_006A05E0`| `EnterSet` — set/map transition; relays if object isn't local |
| `0x29` | `FUN_006A0080`| AoE explosion damage (server → client, see below)            |

`HostEventHandler` (`0x006A1150`) is the standard outbound serialise:

1. Buffer `[opcode 0x06]` (`PythonEvent`).
2. Call `event->WriteToStream(buf+1, 0x3FF)` (vtable `+0x34`).
3. Wrap in a `TGHeaderMessage`, mark reliable, send to the `"NoMe"`
   group via `SendTGMessageToGroup` (`0x006B4DE0`).

`ObjectExplodingHandler` (`0x006A1240`) has two paths:

- Multiplayer: same `0x06`-PythonEvent serialise to `"NoMe"`.
- Single-player: sets the ship's `+0x14C` lifetime from the event and
  triggers the local explosion visual via `FUN_005AC250`.

### Explosion (opcode `0x29`)

```
int    targetObjectID
{x,y,z} compressed-vector-4 position
ushort  rawRadius   (CF16)
ushort  rawDamage   (CF16)
```

The handler decodes the CF16-encoded radius and damage, allocates an
`AoEDamage` (`0x38` bytes), and calls the same `ProcessDamage`
(`0x00593E50`) used by collision and weapon paths.

### Friendly fire

```python
App.g_kUtopiaModule.SetFriendlyFireWarningPoints(100)
```

This C++ threshold drives a UI warning. The actual scoring penalty is
the negative-damage convention described above — same-team hits show
up as negative entries in `g_kDamageDictionary`, which subtracts from
the attacker's eventual score.

---

## Reimplementation implications

A few facts that have actual consequences for a reimplementation:

- **Variable timestep is baked in.** Every physics, damage, repair and
  power calculation in the engine multiplies by a per-frame `dt`. A
  fixed-timestep replacement has to either accept this and run at
  variable `dt` itself, or carefully convert all the per-tick rates.
- **Network is a registered updateable, not a direct call.**
  `TGWinsockNetwork::Update` runs out of the frame budget scheduler
  with a 15-second time slice. A replacement that pumps the network
  directly from MainTick will starve other systems under heavy load.
- **Two timer streams matter.** `g_kTimerManager` (game time) and
  `g_kRealtimeTimerManager` (wall clock) are completely separate.
  `UtopiaModule.SetTimeRate` only affects the first.
- **The mission/gamemode layer is entirely Python.** The C++ side
  contributes the `ET_OBJECT_EXPLODING` event and the network
  transport; everything else (kill attribution, score, frag limits,
  end-game) is in Python and can be replaced without touching C++.
- **VarManager is the channel for the mission name.** The host
  doesn't tell the client "load mission X"; it sends the mission name
  in the Settings packet, the client writes it to
  `VarManager("Multiplayer", "Mission")`, and `Episode.py` reads it
  back. Any reimplementation has to keep that variable store on the
  client.
- **Two network groups must exist.** `"NoMe"` and `"Forward"` are
  load-bearing — score and event relay use them respectively.

---

## Engine assumptions and fragility points

A list of places where the engine assumes it is running in a
fully-initialised, GPU-equipped environment. Headless or
fault-tolerant reimplementations have to either preserve these
assumptions or guard the relevant code paths.

### Renderer is assumed present

- Per-frame render dispatch (`0x004433EA`) sits on a conditional
  jump that, when the condition fails, falls through into rendering
  code that crashes without a valid `IDirect3DDevice7`. Stock dedi
  servers lack a renderer; the engine doesn't gracefully tolerate
  that.
- `NiDX7Renderer`'s pipeline reads **236 bytes (59 DWORDs)** directly
  out of the `IDirect3DDevice7` object for hardware caps
  (`0x007D2119`). Any proxy `Device7` must pad the struct enough to
  satisfy the read or the engine faults.
- The renderer setup path includes `SetCameraData` and frustum
  computations (`0x007E8780`, `0x007C2A10`, `0x007C16F0`) that touch
  scene state during pipeline setup; they require the scene to be
  partially initialised before the renderer is.
- The device-lost recovery path (`0x007C1346`) recreates the renderer
  end-to-end. Without a real D3D device returning success codes, this
  path infinite-loops.
- `DirectDrawCreateEx` results are cached at `0x009A12A4` — first call
  populates, every later call reads from the cache.

### State update assumes ship subsystems exist

- The state-update loop iterates a ship's subsystem linked list at
  `ship+0x284`. If the list head is NULL, the iteration crashes
  unrecoverably at `0x005B1EDB` because of a `MOV EAX,[ECX] / CALL
  [EAX+0x70]` chain through a zeroed vtable.
- The "send state update" path at `0x005B1D57` sets `SUB`/`WPN`
  flags expecting subsystems to populate the rest of the message;
  with no subsystems, the flag still fires and the corresponding
  payload code crashes.
- Subsystem-status hash check at `0x005B22B5` triggers an anti-cheat
  rejection (kicks the offender) when subsystems are NULL. The check
  treats "no data" as "tampered data".

### Mission UI calls must succeed

Two functions at `0x0055C810` and `0x0055C860` are mission UI
entry points that crash when invoked headless (no UI present). They
are reachable through the normal initialization path.

### Object init can call `abort()`

`FUN_0043B1D2` is a `JMP` to an `abort()` wrapper called when init
fails. Any initialization failure terminates the process via `SIGABRT`
without going through the normal Python or event-system paths.

### `__import__` and the App module

Python's `__import__` runs at startup and looks for a SWIG-generated
`App` module to register the C++ surface area. The module has to be
created **before** init starts importing it; otherwise `import App`
during early bootstrap fails fatally (and triggers `Py_FatalError`).

### `Py_FatalError` aborts the process

`Py_FatalError` calls `abort()` directly. Any code path that returns
to it (uncaught Python exception in a critical-section import, fatal
syntax error in a stock script, etc.) terminates the process via
`SIGABRT`.

### `TGLFindEntry` assumes non-NULL `this`

`FUN_006D1E10` (TGL string-table lookup) does not validate `this`;
calling it on a NULL receiver crashes. In stock content the call
sites all guarantee non-NULL, but reimplementations that allow
TGL-less running need to add the check.

### Compressed-vector reads assume valid vtable

Functions at `0x006D2EB0` and `0x006D2FD0` read a vtable through a
pointer that the calling code has not validated. With a partially
initialised object (typical during early reconnect / partial state
sync), the read faults.

### NiDX7 surface validation has a known JNZ-displacement bug

The `GGM` constructor at `0x007CB322` uses `JNZ +5` where it should
be `JNZ +6`, skipping a NULL check on a surface pointer. Any code
path that hits this constructor with a NULL surface — most of the
headless paths do — crashes inside the `JNZ`'d-over block.

### Anti-cheat / checksum behaviour

- The checksum-pass flag `0` does not mean "checksums failed"; it
  means "no mismatches" and is the *correct* value for the very first
  player.
- Reference-string hash is checked only for index 0 of the four
  bootstrap requests.
- The client-side checksum response is silently dropped if no files
  match the directory/filter combination — there's no negative
  response opcode, so the server side simply sees nothing.

### `Sleep` is missing where you would expect it

- The main loop has no `Sleep`. With no renderer or vsync to gate
  it, a pure-headless build of stock BC saturates a CPU core.
- `TGNetwork::Update` runs out of the frame-budget scheduler with a
  15-second time slice but does not yield within it; long incoming
  queues will starve other updateables.

### Save/load cross-references

Save games re-look up engine handles after load (`FixupReferences`
then `FixupComplete`). The two-phase resolve assumes every Python
object that `__setstate__`s during load can re-acquire its engine
handle by name or ID. Engine objects that don't survive load (e.g.
`PythonMethodProcess`) must be reconstructed by the wrapper.

These fragility points are mostly diagnostic for what a compatible
engine has to provide. A clean reimplementation can avoid most of
them by structuring the rendering, state, and subsystem subsystems
with explicit "exists or doesn't" predicates and routing requests
through them.
