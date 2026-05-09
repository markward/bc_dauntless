# Event System

The TG event system is the dispatch backbone for game logic in
`stbc.exe`. Every BC object that wants to react to anything —
weapon hits, button clicks, network messages, timers — registers a
handler with the singleton `TGEventManager`, and the engine drains a
queue of `TGEvent` objects every `MainTick`. The same machinery
serves the C++ side and (via callback wrappers) the Python side.

This document describes the moving parts and the dispatch flow. It is
not a per-event-type catalogue; for the concrete event-ID registrations
that build a multiplayer session, see
`architecture/runtime-and-main-loop.md`.

---

## Components

```
TGEventManager (singleton)
 ├── TGEventHandlerTable       — global, broadcast handlers keyed by event type
 │    └── TGConditionHandler   — sorted array of entries for one event type
 │         └── TGHandlerListEntry  — { object, callback } node
 │              └── TGCallback     — wrapper for C++ fn-ptr OR Python "module.function"
 ├── TGInstanceHandlerTable     — per-object handlers (lives at TGEventHandlerObject+0x10)
 ├── TGEventQueue               — pending events: head/tail linked list with count
 └── TGEvent                    — { type, source, dest, type-specific data }
```

The two handler tables (global "broadcast" and per-instance "targeted")
share a structure: a 37-bucket hash by event-type ID, with each bucket
chaining `TGConditionHandler` objects. The global table sits on the
event manager; the per-instance table lives at `TGEventHandlerObject+0x10`.

### `TGCallback`

A 0x14-byte object that holds either a C++ function pointer or a
Python `"module.function"` string. Vtable: `0x008960F4`.

| Offset | Size | Field                                                  |
|--------|------|--------------------------------------------------------|
| `+0x00`| 4    | vtable pointer                                         |
| `+0x04`| 4    | flags (bit0=isMethod, bit1=isPython, bit2=active, bit3=pendingDelete) |
| `+0x08`| 4    | next (chain pointer)                                   |
| `+0x0C`| 4    | sentinel value                                         |
| `+0x10`| 4    | function pointer (or string pointer, when `isPython`)  |

When `isPython` is set, `+0x10` points to a string of the form
`"module.function"`. The callback resolves it on every invocation by
calling `__import__` plus `getattr` — the lookup is done at dispatch
time, not at registration. That's how live Python reloads work: the
callback always picks up the current bound function.

### `TGHandlerListEntry`

A 0xC-byte linked-list cell holding one (object, callback) pair:

| Offset | Size | Field                                  |
|--------|------|----------------------------------------|
| `+0x00`| 4    | object pointer (`TGEventHandlerObject*`) |
| `+0x04`| 4    | callback pointer (`TGCallback*`)         |
| `+0x08`| 4    | deleted flag                            |

### `TGConditionHandler` (vtable `0x00896104`)

The thing that actually owns the handler entries for one (object,
event-type) combination. Internally it keeps **two sorted arrays** —
one for broadcast listeners, one for per-object targeted listeners —
each maintained with binary-search insertion so a lookup is O(log n).

The implementation is *reentrant*: it supports deferred add/remove
during dispatch, so a handler can register or unregister handlers
mid-iteration without invalidating the walk.

Its key methods:

- `AddEntry(node)` — binary-search insert by priority key.
- `InsertSorted` — internal helper.
- `FindFirstByKey` — binary search.
- `RemoveByName(nameHash)` — removes by name hash.
- `RemoveAllForObject(obj)` — removes every handler belonging to a
  given object (used during destruction).

### `TGEvent` (factory ID `0x02`, size `0x28`)

The base event type. Carries a type ID, source and destination
references, and a type-specific payload. Subclasses (`TGCharEvent`,
`TGFloatEvent`, `TGIntEvent`, `TGObjPtrEvent`, `TGStringEvent`, etc.)
add typed payload fields. Notable methods:

- `SetSource` / `SetDestination`
- `Duplicate` — clones the event, used when forwarding
- `LookupInEventTable` / `RegisterInEventTable` — for serialised
  events that reference objects by ID

### `TGEventQueue`

A simple linked-list queue (head/tail/count). Events post here for
deferred processing on the next `ProcessEvents`.

---

## Dispatch flow

Per-frame, `MainTick` step 4 calls
`TGEventManager::ProcessEvents` (`FUN_006DA2C0`). The pump body:

```
while (queue not empty) {
    evt = dequeue();
    DispatchSingleEvent(evt);     // FUN_006DA300
    free(evt);
}
```

`DispatchSingleEvent` calls `FUN_006DB620(this+0x2C, event)` —
`this+0x2C` is the global handler-registry sub-object — which:

1. Hashes the event type (`type % 37`).
2. Walks the bucket chain for a matching `TGConditionHandler`.
3. Walks the condition handler's sorted array and invokes each
   callback in priority order.
4. Each `TGCallback` is either:
   - **C++:** plain function-pointer call.
   - **Python:** `__import__("module.function")` + `getattr`, then
     invoke via the SWIG bridge.

### Posting an event

The standard pattern from C++:

```cpp
TGEvent* evt = new TGEvent();      // or a typed subclass
evt->eventType = 0x008000F1;       // ET_NEW_PLAYER_IN_GAME
evt->charData  = connID;
evt->SetDest(this);
PostEvent(evt);                    // queue, returns immediately
```

`PostEvent` enqueues; the actual dispatch happens during
`ProcessEvents` at the start of the next `MainTick` cycle.

### Handler registration pattern

Every class that inherits from `TGEventHandlerObject` exposes two
virtual methods used by the event-manager bookkeeping at construction
time:

1. **`RegisterHandlerNames`** — calls
   `TGObject::RegisterHandlerWithName(name)` for each handler the
   class will register, supplying the *string identifier* compiled
   from the original source. These strings are the
   `"MultiplayerGame :: ChecksumCompleteHandler"`-style names you can
   see throughout the binary; they're debug labels that survive into
   handler-list entries.
2. **`RegisterHandlers`** — calls
   `RegisterEventHandler(eventTypeID, callback)` for each handler.

A single class therefore declares *what* it handles via the names
function and *how* it handles them via the handlers function. The
catalogued name set spans 50+ classes.

This pattern matters in practice because the names function looks
suspicious to a static-analysis pass that scans for handler functions
by looking for "handler-shaped" strings: it walks a list of literals.
An automated annotation script that conflates the names function with
the handler functions themselves will mis-tag every handler in the
binary.

---

## Event-type ID encoding

Event-type IDs are 32-bit values with hierarchical namespacing:

| Range                  | Domain                                       |
|------------------------|----------------------------------------------|
| `0x00030001`–`0x00040001`| Input events (mouse, keyboard, gamepad, control) |
| `0x00800XXX`           | Game events (the `MultiplayerGame` handler   |
|                         | table is here — see runtime-and-main-loop.md)|
| `0x008000E0`–`0x008000E5`| Combat (SetPhaserLevel, StartCloak, StopCloak) |
| `0x00800058`–`0x0080005A`| Targeting (TARGET_WAS_CHANGED, TARGET_SUBSYSTEM_SET) |
| `0x00060001`–`0x00060005`| Network events (ReceiveMessage, Disconnect, NewPlayer, DeletePlayer, etc.) |

Some commonly referenced single-IDs:

| ID         | Name                       | Notes                                 |
|------------|----------------------------|---------------------------------------|
| `0x60001`  | `ET_NETWORK_MESSAGE_EVENT` | NetFile registers on this for opcode dispatch |
| `0x60002`  | (HostOrJoin host event)    | Fired by `TGNetwork::HostOrJoin` when state→2 |
| `0x60003`  | `DisconnectHandler`        | MultiplayerGame                       |
| `0x60004`  | `NewPlayerHandler`         | MultiplayerGame                       |
| `0x60005`  | `DeletePlayerHandler`      | MultiplayerGame                       |
| `0x008000C5`| `ExitedWarp`              |                                       |
| `0x008000C8`| `ObjectCreated`           |                                       |
| `0x008000DD`| `SubsystemStatus`         |                                       |
| `0x008000DF`| `AddToRepairList`         | Routes through `HostEventHandler`     |
| `0x008000E6`| `ChecksumComplete`        | Triggers Settings + GameInit          |
| `0x008000E7`| `SystemChecksumFailed`    | NetFile fires after mismatch          |
| `0x008000E8`| `SystemChecksumPassed`    |                                       |
| `0x008000F1`| `NewPlayerInGame`         | Posted by handler `0x2A`              |

UI-specific event IDs (used by `TGUIObject`/`TGRootPane`) are listed
in `cpp-runtime.md` under "UI hierarchy"; they include the
`0x800494`-`0x800498` toggles, `0x8000CE`-`0x8000D1` dialog buttons,
`0x8000B6`-`0x8000BA` resolution changes, etc.

---

## Save/load

The whole handler-table system can be persisted, since save games
(and online state-transfer in some cases) include the dispatcher
configuration:

| Class                      | Save / Load methods                       |
|----------------------------|-------------------------------------------|
| `TGEventHandlerTable`      | `SaveBroadcastHandlers` / `LoadBroadcastHandlers` |
| `TGInstanceHandlerTable`   | `SaveToStream` / `LoadFromStream`         |
| `TGConditionHandler`       | `SaveHandlerEntries` / `LoadHandlerEntries` |
| `TGEventQueue`             | `SaveToStream` / `LoadFromStream`         |

After load, `FixupReferences` (phase 1) followed by `FixupComplete`
(phase 2) resolves persisted object IDs back to live pointers. The
two-phase split is the standard "deserialise everything, then patch
cross-references" approach — both the class-load code and the handler
tables go through it.

---

## Notable functions

| Address     | Function                                  |
|-------------|-------------------------------------------|
| `0x006D9060`| Timer base method (target of many thunks) |
| `0x006D9240`| `TGEventHandlerObject::HandleEvent` (vtable slot 20) |
| `0x006DA040`| —                                          |
| `0x006DA130`| Register named handler function (global)   |
| `0x006DA2C0`| `TGEventManager::ProcessEvents` (`__fastcall`) |
| `0x006DA300`| Dispatch single event                       |
| `0x006DA4E0`| `RegisterConditionHandler` (TGEventHandlerObject) |
| `0x006DB380`| `RegisterEventHandler` (binds handler to event type) |
| `0x006DB620`| Dispatch to handler chain                   |
| `0x0097F838`| `TGEventManager` global                     |
| `0x0097F864`| Handler registry (`TGEventManager+0x2C`)    |
