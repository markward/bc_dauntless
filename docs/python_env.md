# Python Runtime Environment

Findings from live instrumentation of `stbc.exe`. Updated as new data arrives.

## Runtime

| Field | Value |
|---|---|
| Version | Python 1.5.2 (#0, Jan 17 2002, 03:24:04) [MSC 32 bit (Intel)] |
| Platform | win32 |
| sys.path | `['.\Scripts', '.', 'C:\projects\open_stbc\game']` |

CWD at import time is `game\` (confirmed — `SaveConfigFile` writes there).

## Built-in modules

Statically compiled into `stbc.exe`. Only these are importable:

```
Appc  __builtin__  __main__  _locale  array  binascii
cPickle  cStringIO  cmath  errno  imp  marshal  math
new  nt  operator  regex  strop  struct  sys  thread  time
```

Notable absences: **`os`** (not available — use `nt` directly), **`socket`** (no UDP option).

## nt module

The raw Windows API module that `os` normally wraps. Available functions:

```
access  close  dup  dup2  environ  error  fdopen  fstat
listdir  lseek  lstat  mkdir  open  read  remove  rename
rmdir  stat  times  unlink  utime  write
```

Constants: `O_RDONLY O_RDWR O_WRONLY O_CREAT O_TRUNC O_APPEND O_BINARY O_TEXT O_EXCL`  
Access flags: `F_OK R_OK W_OK X_OK`  
Spawn flags: `P_WAIT P_NOWAIT P_NOWAITO P_OVERLAY P_DETACH`

`nt.getcwd` does **not** exist in this build.  
`nt.open()` status: **under test** (awaiting result).

## Appc module

Built-in C extension — 5802 exported names. SWIG-generated Python 1.5 bindings.

**Note:** `UtopiaModule.GetGameTime = wrapper` is the confirmed working approach for
per-tick instrumentation. See `tools/appc_logger.py` (commit `180e3f1`) for the working
implementation used to answer Q1.

Appc name sample (first quarter, alphabetical):
```
ADD_TO_REPAIR_LIST_MESSAGE  AIScriptAssist_GetIncomingTorpIDsInSet
AIScriptAssist_TorpIsIncoming  AT_FOUR  AT_MAX_NUM_AMMO_TYPES  AT_ONE
AT_THREE  AT_TWO  AnimTSParticleController_Create
AnimTSParticleController_SetDrawOldToNew  ...
```

Appc name ranges (alphabetical, 4 quarters of ~1450 names each):
- Q0 (0–1449): `ADD_TO_REPAIR_LIST_MESSAGE` … `AnimTSParticleController_*`
- Q1 (1450–2899): `GridClass_*` … `ImageManagerClass_*`
- Q2 (2900–4349): `ShipClass_Set*` …
- Q3 (4350–5801): `TGUIObject_*` …

IO-related names: **none found**. Exhaustive sampling of all 16 alphabetical windows and
their tail boundaries found no `Log*`, `Debug*`, `Write*`, `File*`, `Print*`, or `Trace*`
names. Appc exposes no Python-level logging interface.

## g_k* engine globals

All defined in `sdk/Build/scripts/App.py` lines 13179–14020. Available at import time.

**Core subsystems**
| Name | Type | Purpose |
|---|---|---|
| `g_kSystemWrapper` | TGSystemWrapperClass | System-level calls |
| `g_kConfigMapping` | TGConfigMapping | Config file I/O — only confirmed write path |
| `g_kPoolManager` | TGPoolManager | Memory pool management |
| `g_kLocalizationManager` | TGLocalizationManager | String localisation |
| `g_kAnimationManager` | TGAnimationManagerClass | Skeletal animation |
| `g_kModelManager` | TGModelManager | 3D model loading |
| `g_kEventManager` | TGEventManager | Event dispatch |
| `g_kTimerManager` | TGTimerManager | Game-time timers |
| `g_kRealtimeTimerManager` | TGTimerManager | Wall-clock timers |
| `g_kInputManager` | TGInputManager | Keyboard/mouse input |

**Game modules**
| Name | Type | Purpose |
|---|---|---|
| `g_kUtopiaModule` | UtopiaModule | Core game loop (`GetGameTime`, `GetUpdateNumber`, etc.) |
| `g_kSetManager` | SetManager | Rendered object sets |
| `g_kVarManager` | VarManagerClass | Script variables |
| `g_kImageManager` | ImageManagerClass | Texture management |
| `g_kFocusManager` | FocusManager | UI focus |
| `g_kLODModelManager` | LODModelManager | Level-of-detail models |
| `g_kTextureAnimManager` | TextureAnimManager | Texture animation |
| `g_kInterfaceModule` | InterfaceModule | Main game interface |
| `g_kKeyboardBinding` | KeyboardBinding | Key bindings |

**Rendering / UI**
| Name | Type |
|---|---|
| `g_kRootWindow` | TGRootPane |
| `g_kIconManager` | TGIconManager |
| `g_kFontManager` | TGFontManager |
| `g_kUIThemeManager` | TGUIThemeManager |
| `g_kSoundManager` | TGSoundManager |
| `g_kRedbook` | TGRedbookClass |
| `g_kMusicManager` | TGMusic |
| `g_kModelPropertyManager` | TGModelPropertyManager |
| `g_kTGActionManager` | TGActionManager |
| `g_kMovieManager` | TGMovieManager |

`g_kUtopiaModule` is the same object as the `UtopiaModule` name used in SDK scripts.

## Write paths

| Method | Status |
|---|---|
| `g_kConfigMapping.SaveConfigFile(name)` | **Works** — only confirmed write path. Writes to `game\`. |
| `open()` | Blocked — fails silently (IOError) |
| `nt.open()` | Blocked — `OSError: (0, 'Error', 'nt_test.txt')`. Same process-level block as `open()`. |
| `os.system()` / `os.popen()` | Not available (`os` not importable) and would crash as GUI process |
| `sys.stdout.write()` | Crashes game (no console handle) |
| UDP socket | Not available (`socket` not built-in) |

## Instrumentation constraints

- Code runs at **module import time** (appended to end of `App.py`) — engine globals
  (`g_kConfigMapping`, `Appc`, `g_kSystemWrapper`) are all accessible at that point.
- `UtopiaModule.GetGameTime` wrapping works — confirmed via Q1 instrumentation session.
- Iterating large lists with per-item string operations crashes — applies to `dir(Appc)`
  (5802 names) and `globals().keys()` (thousands of App module names). Use fixed-index
  slices instead; do not loop over these collections in snippet code.
- `import os` raises `ImportError` — use `nt` for any OS-level operations.
- All snippet imports that could fail must be inside `try/except` blocks — do **not** put
  potentially-absent imports at the outer try level where failure aborts the whole snippet.
