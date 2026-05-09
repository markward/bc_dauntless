# Python and Binding Layer

Reference for the embedded Python 1.5.2 interpreter, the SWIG-generated
`App` / `Appc` bindings, and the C++/Python interop quirks that any
compatible engine has to honour.

The binary embeds Python 1.5.2 statically (no separate `python15.dll`).
The interpreter is the same one Python released in April 1999 — not a
"slightly older" Python; many things modern eyes take for granted are
genuinely absent.

---

## Python 1.5.2 language facts

These are the language-level constraints. Code violating them either
fails to parse (silent fatal error during module import — see further
down) or raises `TypeError`/`NameError` at runtime.

### Syntax that does not exist

```python
print("hello")             # SyntaxError — print is a statement
print "hello"              # OK

except Exception as e:     # SyntaxError — must use comma
except Exception, e:       # OK

[x*2 for x in items]       # SyntaxError — no list comprehensions
result = []
for x in items:            # OK
    result.append(x*2)

x if cond else y           # SyntaxError — no ternary
if cond: x = a             # OK
else:    x = b

x += 1                     # SyntaxError — no augmented assignment
x = x + 1                  # OK

import X as Y              # SyntaxError — `as` not supported (Python 1.6+)
import X
Y = X                      # OK
```

### Closures

There are **no nested scopes**. An inner function cannot see names in
an enclosing function unless they are explicitly passed as default
arguments:

```python
def outer():
    captured = 42
    def inner():
        return captured           # NameError at call time
    def inner_ok(_v=captured):
        return _v                 # works — captured at def time
    return inner_ok
```

This is why `DedicatedServer.py` in stock content uses default
arguments so heavily — it's the only way to bind names into nested
helpers.

### Missing / different builtins

| Operation                | Python 1.5.2 equivalent                        |
|--------------------------|-------------------------------------------------|
| `key in dict`            | `dict.has_key(key)`                            |
| `"sub" in "string"`      | `strop.find(string, sub) >= 0`                 |
| `s.replace(a, b)`        | `strop.replace(s, a, b)`                       |
| `s.startswith(p)`        | `s[:len(p)] == p`                              |
| `s.endswith(p)`          | `s[len(s)-len(p):] == p`                       |
| `True` / `False`         | `1` / `0` (the literals don't exist)           |
| `os.path.join(a, b)`     | `a + "\\" + b` (paths are stringly-typed)      |
| List comprehension       | `map`/`filter` or explicit loops               |

The single biggest gotcha is **`in` does not work on dictionaries**.
Modern Python treats `key in d` as a key-lookup; in 1.5.2 it raises
`TypeError`. Use `has_key`.

`strop` is the C-implementation string-ops module that 1.5.2 ships;
it is the right replacement for the methods that don't exist on the
`str` type yet.

### Available stdlib

The interpreter is *statically built* into `stbc.exe` with a curated
stdlib subset. **Treat every `import` as potentially absent** —
`os` in particular is not compiled in and not importable. `sys` is
always available; `strop`, `string`, `time` are reliable; module
imports beyond that should be guarded:

```python
try:
    import time
    _now = time.time
except ImportError:
    _now = None
```

---

## File I/O is blocked from Python

`open()` for write modes raises `IOError` — paths checked include
absolute, relative, and `%TEMP%`. Read mode also fails for content
outside the game's expected resource directories. `os.system()`
(which would fork `cmd.exe`) is also blocked. `sys.stdout.write()`
crashes the game outright because `stbc.exe` is a GUI subsystem
binary with no console handle attached.

The only working write paths from Python are routed through the
engine's own C++ file I/O. The most useful one is
`TGConfigMapping.SaveConfigFile`, accessed via:

```python
App.g_kConfigMapping.SetStringValue("Section", "key", "value")
App.g_kConfigMapping.SaveConfigFile("filename.cfg")
```

Argument order on `TGConfigMapping`:

- `SetStringValue(section, key, value)` / `GetStringValue(section, key)`
- `SetIntValue(section, key, value)` / `GetIntValue(section, key)`
- `SetFloatValue(section, key, value)` / `GetFloatValue(section, key)`
- `SaveConfigFile(filename)` / `LoadConfigFile(filename)`

The file lands in the game's working directory (`game/`). The full
config gets written — `SaveConfigFile` dumps every section the
mapping currently holds, not just the one you wrote.

### `print` works (but mind the binding)

`print` succeeds *if* the embedding has set up a stdout target.
Implementations that swap in their own debug-console-to-file redirect
get all `print` output. A hosted environment with no redirect will
crash on the first `print` for the same reason `sys.stdout.write` does.

---

## Py_FatalError and the abort path

The embedded interpreter calls `Py_FatalError` (which itself calls
`abort()`) on conditions a normal Python install would just raise:

- **`SyntaxError` during the `App.py` import** — a Python 1.5.2 syntax
  error inside an imported module is fatal at import time. The trick
  some headless implementations use is to redirect `Py_FatalError`'s
  entry to an immediate `RET` so the interpreter survives the error,
  but that is a workaround, not engine behaviour.
- **`SIGABRT` during `Py_FatalError`** is the typical actual exit:
  CRT `signal()` is registered for signal 22 inside the interpreter.

For a reimplementation: do not rely on Python error reporting; an
unhandled exception in stock BC can corrupt interpreter state or
trigger the abort path. **Always wrap risky operations in
`try/except`** in scripts that need to survive errors.

---

## SWIG 1.x binding layer

C++ classes are exposed to Python via SWIG-generated wrappers. The
binding is the `App` / `Appc` module — there are no Python shadow
classes; everything is flat C functions following the pattern
`ClassName_MethodName(self, args...)` or just `FunctionName(args...)`:

```python
# Wrong — no shadow classes exist
network = App.TGWinsockNetwork()
network.HostOrJoin(addr, pw, port)

# Right — functional API
import App
wsn = App.UtopiaModule_GetNetwork(um)
App.TGNetwork_HostOrJoin(wsn, addr, pw, port)
```

### Strict pointer-type checking

SWIG validates pointer arguments by their string suffix
(`_p_TGNetwork`, `_p_TGWinsockNetwork`, etc.) and **refuses to coerce
between distinct types** even when the underlying C++ types are
related by inheritance. Returned pointer types matter:

```python
# After UtopiaModule_InitializeNetwork, the global is _p_TGNetwork
wsn = App.UtopiaModule_GetNetwork(um)

App.TGWinsockNetwork_SetPortNumber(wsn, 22000)
# TypeError: Type error in argument 1 of TGWinsockNetwork_SetPortNumber.
# Expected _p_TGWinsockNetwork
```

There is no Python-level cast. If the binding wants
`_p_TGWinsockNetwork` and you have `_p_TGNetwork`, the only way out
is to find an API that returns the type the call wants.

### Roughly 114 SWIG-bound classes, ~1,340 methods

The largest interfaces by method count: `TGUIObject` (94), `TGSound`
(63), `TGMessage` (53), `TGNetwork` (50), `TGInputManager` (41).
Full class catalogue is in `engine/cpp-runtime.md`.

---

## Notable SWIG functions

A useful selection of bindings, organised by subsystem. The point of
this list isn't to be exhaustive — the binding tables in the binary
contain everything — but to anchor the names a script reader will
encounter most often.

### Process-wide globals

The `App` module exposes the engine's main singletons at module load:

| Name                    | Type                  |
|-------------------------|-----------------------|
| `App.g_kConfigMapping`  | `TGConfigMapping`     |
| `App.g_kUtopiaModule`   | `UtopiaModule`        |
| `App.g_kVarManager`     | `VarManagerClass`     |
| `App.g_kEventManager`   | `TGEventManager`      |

### `TGNetwork` / `TGWinsockNetwork`

```
new_TGWinsockNetwork()                       # construct
TGWinsockNetwork_SetPortNumber(wsn, port)    # _p_TGWinsockNetwork only

TGNetwork_AddClassHandlers()                 # 0 args — class-level handlers
TGNetwork_RegisterHandlers()                 # 0 args — network handlers
TGNetwork_Connect(net)                       # returns 0 = success
TGNetwork_Disconnect(net)
TGNetwork_HostOrJoin(net, addr, pw, port)    # see runtime-and-main-loop.md
TGNetwork_Update(net)                        # main network tick
TGNetwork_AddGroup / DeleteGroup / GetGroup
TGNetwork_CreateLocalPlayer(net, name)       # don't use when hosting

TGNetwork_GetConnectStatus(net)              # 2 = hosting, 3 = client
TGNetwork_GetHostID / GetLocalID / IsHost
TGNetwork_GetHostName / GetName / GetCName
TGNetwork_GetLocalIPAddress
TGNetwork_GetPlayerList                      # _p_TGPlayerList
TGNetwork_GetNumPlayers / GetTimeElapsedSinceLastHostPing

TGNetwork_GetNextMessage(net)                # manual polling — None when empty
TGNetwork_SendTGMessage(net, msg)
TGNetwork_SendTGMessageToGroup(net, group, msg)
TGNetwork_RegisterMessageType
TGNetwork_GetEncryptor / SetEncryptor
TGNetwork_SetConnectionTimeout(net, secs)
TGNetwork_SetSendTimeout(net, secs)
TGNetwork_GetBootReason / SetBootReason
TGNetwork_EnableProfiling(net, flag)
TGNetwork_GetIPPacketHeaderSize

# Boot-reason / status constants
TGNetwork_DEFAULT_BOOT, INCORRECT_PASSWORD, SERVER_BOOTED_YOU,
TIMED_OUT, TOO_MANY_PLAYERS, YOU_ARE_BANNED,
TGNETWORK_GAMESPY_PLAYER_ID, TGNETWORK_INVALID_ID, TGNETWORK_NULL_ID,
TGNETWORK_MAX_LOG_ENTRIES, TGNETWORK_MAX_SENDS_PENDING,
TGNETWORK_MAX_SEQUENCE_DIFFERENCE
```

Important: after `UtopiaModule_InitializeNetwork`, the global network
is a `_p_TGNetwork`, not `_p_TGWinsockNetwork`. The
`TGWinsockNetwork_*` family will reject it; use the `TGNetwork_*`
family on the global pointer.

### Event system

```
TGEvent_Create()
TGEvent_SetEventType(evt, type_int)          # e.g. App.ET_START = 0x800053
TGEvent_SetDestination(evt, target_obj)

TGEventHandlerObject_Cast(obj)
TGEventHandlerObject_AddPythonFuncHandlerForInstance(eho, type, "Mod.Func")
TGEventHandlerObject_AddPythonMethodHandlerForInstance(eho, type, "Mod.Func")
TGEventHandlerObject_CallNextHandler(eho, evt)
TGEventHandlerObject_ProcessEvent(eho, evt)
TGEventHandlerObject_RemoveHandlerForInstance(eho, ...)
TGEventHandlerObject_RemoveAllInstanceHandlers(eho)
delete_TGEventHandlerObject(eho)

TGEventManager_AddEvent(em, evt)
TGEventManager_AddBroadcastPythonFuncHandler(em, type, "Mod.Func")
TGEventManager_AddBroadcastPythonMethodHandler(em, type, "Mod.Func")
TGEventManager_RemoveBroadcastHandler(em, ...)
TGEventManager_RemoveAllBroadcastHandlersForObject(em, obj)

TGConditionHandler_AddCondition / RemoveCondition / ConditionChanged
TGCondition_AddHandler / RemoveHandler
```

Event-type constants follow the `App.ET_*` namespace. Selected ones:

| Constant                        | Hex          |
|---------------------------------|--------------|
| `ET_START`                      | `0x800053`   |
| `ET_CREATE_SERVER`              | `0x80004A`   |
| `ET_CHECKSUM_COMPLETE`          | `0x8000E6`   |
| `ET_SYSTEM_CHECKSUM_COMPLETE`   | (TBD)        |
| `ET_SYSTEM_CHECKSUM_FAILED`     | `0x8000E7`   |
| `ET_NETWORK_NEW_PLAYER`         | (`0x60004`)  |
| `ET_NETWORK_DELETE_PLAYER`      | (`0x60005`)  |
| `ET_NETWORK_MESSAGE_EVENT`      | `0x60001`    |
| `ET_NETWORK_CONNECT_EVENT`      | (TBD)        |
| `ET_NETWORK_DISCONNECT_EVENT`   | (`0x60003`)  |
| `ET_LOAD_EPISODE`               | (TBD)        |
| `ET_KILL_GAME`                  | (TBD)        |

### `Game` / `MultiplayerGame`

```
Game_GetCurrentGame()
Game_LoadEpisode(game, episode_str)

MultiplayerGame_Cast(game)
MultiplayerGame_Create(game)                 # creates MP game from base
MultiplayerGame_GetNumberPlayersInGame(mg)
MultiplayerGame_IsReadyForNewPlayers(mg)
MultiplayerGame_SetMaxPlayers(mg, n)
MultiplayerGame_SetReadyForNewPlayers(mg, flag)

LoadEpisodeAction_Create(game)
LoadEpisodeAction_Play(lea)
```

### `UtopiaModule`

```
UtopiaModule_InitializeNetwork(um, wsn, name)   # 3 args
UtopiaModule_GetNetwork(um)                     # returns _p_TGNetwork
UtopiaModule_CreateGameSpy(um, ...)
UtopiaModule_GetCamera(um)
UtopiaModule_GetCaptainName(um)
UtopiaModule_GetCurrentFriendlyFire(um)
UtopiaModule_GetDataPath(um)
UtopiaModule_SetGameName(um, name)
UtopiaModule_SetTimeRate(um, rate)              # game-time scale
```

### `TGConfigMapping`

```
TGConfigMapping_GetIntValue(cm, section, key)              # 3 args, NOT 4
TGConfigMapping_GetStringValue / GetTGStringValue / GetFloatValue
TGConfigMapping_HasValue(cm, section, key)
TGConfigMapping_SetIntValue(cm, section, key, value)
TGConfigMapping_SetStringValue / SetTGStringValue / SetFloatValue
TGConfigMapping_LoadConfigFile(cm, filename)
TGConfigMapping_SaveConfigFile(cm, filename)
```

### `VarManagerClass`

Note the naming inconsistency — the module path uses `VarManagerClass_`,
not `VarManager_`:

```
VarManagerClass_SetStringVariable(vm, scope, key, value)
VarManagerClass_SetFloatVariable(vm, scope, key, value)
VarManagerClass_GetStringVariable(vm, scope, key)
VarManagerClass_GetFloatVariable(vm, scope, key)
VarManagerClass_DeleteAllScopedVariables(vm, scope)
VarManagerClass_DeleteAllVariables(vm)
VarManagerClass_MakeEpisodeEventType(vm, ...)
```

### `TopWindow`

```
TopWindow_GetTopWindow()
TopWindow_Initialize(tw)
# child windows:
tw.FindMainWindow(App.MWT_MULTIPLAYER)         # MWT_8 = MultiplayerWindow
```

### Strings

```
new_TGString("text")
```

---

## Python ↔ engine bridge specifics

### `TG_CallPythonFunction` (`0x006F8AB0`)

The C++→Python entry point used for the three call points described
in `architecture/runtime-and-main-loop.md`. Acquires the GIL via
`FUN_0074BBF0(1)`, imports the module by name, fetches the attribute,
optionally builds an args tuple from a `Py_BuildValue` format string,
invokes, and releases the GIL.

```c
int TG_CallPythonFunction(
    const char* modulePath,    // e.g. "Multiplayer.Episode.Mission1.Mission1"
    const char* functionName,  // e.g. "InitNetwork"
    const char* formatString,  // e.g. "i"
    int         argPtr,        // pointer to the args
    const char* typeString);   // optional validation string
```

`FUN_006F8650` is the simpler "read a Python global into C" wrapper —
used for `Multiplayer.MissionMenusShared.g_iPlayerLimit` and similar.

### Python nesting counter at `0x0099EE38`

Must be `0` for `PyRun_String` to be safe. The engine increments it
during script-import and decrement-on-return; trying to invoke
`PyRun_String` while non-zero is the canonical way to deadlock the
interpreter.

### `__import__` returns the top-level package

```python
mod = __import__("A.B.C")            # returns A, not C
__import__("A.B.C")
mod = sys.modules["A.B.C"]           # right
```

### Replacing event handlers means replacing `func_code`

The event system holds *direct references* to function objects.
Re-binding a module attribute does not replace handlers that have
already been registered against the old function object. To replace
behaviour without re-registering, swap `func_code` and
`func_defaults`:

```python
def wrapper(orig=original_func):
    try:
        orig()
    except:
        pass

original_func.func_code     = wrapper.func_code
original_func.func_defaults = wrapper.func_defaults
```

This is how stock content (and any wrapper layer above it) installs
error handling around mission handlers.

### Object lifecycle and `__del__`

Python objects that wrap engine handles must clean up the engine
side themselves — the engine does not know the wrapper is gone.

- Python owns the engine objects it creates; `__del__` must call the
  appropriate engine destructor / unregister.
- Save/load: 39 classes use `__getstate__`/`__setstate__`; only the
  Python-side state is saved, and engine handles are looked up again
  on restore.
- `PythonMethodProcess` cannot be pickled; it has to be recreated
  in `__setstate__`.

### Threading

Single-threaded from Python's perspective. `Autoexec.py` calls
`sys.setcheckinterval(200)` so the (theoretical) thread switch
happens every 200 bytecode operations; no script in stock content
relies on this.

### Process priority levels

The Python-visible priority levels actually *used* by stock content
are `NORMAL` (almost everything) and `LOW` (two scripts). The
`CRITICAL` and `UNSTOPPABLE` constants exist but are reserved for
C++ internal use and never appear in Python registrations.

---

## Engine-quirk reference

A few facts about how the embedded interpreter behaves that are
neither Python-language facts nor SWIG facts but matter for
compatibility:

- Magic number is `0x4E99` (Python 1.5.2). `.pyc` files compiled by a
  later Python won't load.
- The interpreter is statically compiled into the executable; there
  is no separate `python15.dll` to swap.
- The CRT signal handler for `SIGABRT` (signal 22) is registered
  inside the interpreter. Anything that triggers `abort()` will hit
  it, including `Py_FatalError`.
- `time.time` is fine; `time.sleep` works (one of the four `Sleep`
  call sites in the binary is `py_time_sleep` at `0x00768988`).
