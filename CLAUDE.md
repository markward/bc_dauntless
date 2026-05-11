# open_stbc — Claude Context

## What this project is

Open reimplementation of the Star Trek: Bridge Commander (BC) engine, targeting modern operating systems. The long-term deliverable is a new C++ engine that runs BC's original Python game scripts without the original Windows-only `Appc.dll`.

The original engine is a compiled C++ binary exposed to Python via a SWIG-generated interface (`App.py`). Everything the game does crosses that boundary. The plan is to reverse-engineer and replace `Appc` with a modern, cross-platform C++ engine that embeds CPython.

## Current stage

**Discovery complete. Ready to begin Phase 1 implementation.** All open questions blocking Phase 1 are resolved. See `docs/gap_analysis.md` for the full record. The repo is set up on a Windows machine; the instrumentation tooling in `tools/` remains available for Phase 2 questions.

## Implementation phases

**Phase 1 — Headless logic engine** (3–6 months)
- Replace `Appc` with a Python shim
- Physics via PyBullet
- Event system from scratch
- No renderer
- Goal: run the SDK tutorial missions and validate all game logic

**Phase 2 — Full C++ engine** (18 months+)
- OpenMW NIF renderer extended with BC-specific block types (NifSkope has BC support)
- OpenAL audio
- Character animation
- CPython embedding layer

## Key reference material

| Resource | Location | Purpose |
|---|---|---|
| Appc interface spec | `sdk/Build/scripts/App.py` | Complete surface of every engine call — SWIG-generated, fully readable |
| SDK Python source | `sdk/Build/scripts/` | 1228 files; ground truth for all game logic |
| Physics parameters | `sdk/Build/scripts/GlobalPropertyTemplates.py` | Mass, rotational inertia per ship class |
| Ship hardpoints | `sdk/Build/scripts/ships/Hardpoints/` | Per-ship physics, weapons, arc geometry |
| Ship construction | `sdk/Build/scripts/loadspacehelper.py:54–135` | Integration point between Appc and physics |
| Mission lib | `sdk/Build/scripts/MissionLib.py` | Timer lifecycle, two-tier timer architecture |
| Gap analysis | `docs/gap_analysis.md` | 8 gaps, 21 open questions, solution paths |
| Open questions | `docs/open_questions.md` | 4 instrumentation questions — Q4 closed |
| Live game | `game/` | BC installation (gitignored) — needed for instrumentation |
| UI components | `engine/ui/`, `docs/superpowers/specs/2026-05-11-ui-components-design.md` | Reusable Button + CollapsibleList; theme registries mirror LoadInterface.py |

## Open questions status

### Instrumentation questions (require running game)

| Q | Topic | Status |
|---|---|---|
| Q1 | Tick rate — fixed or variable? what Hz? | ✅ **60 Hz fixed** (16.67 ms/tick) |
| Q2 | Subsystem update ordering within a tick | ✅ **AI/Python first** (~2% into tick), then physics, then render |
| Q3 | Time scale interaction with physics/AI/timers | ✅ **Game time scales** (0.204 measured); real time does not |
| Q4 | TimeSliceProcess priority semantics | ✅ Closed — static analysis sufficient |

### Gap analysis OQs (21 total)

- Closed by static analysis: OQ-1.1, 1.2, 1.3, 2.1, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3, 6.2, 7.4, 8.1, 8.2 (15)
- Closed by instrumentation: OQ-7.1, OQ-7.2, OQ-7.3 (3)
- Partially answered: OQ-2.2 (teleport confirmed; warp-exit velocity Phase 2), OQ-2.3 (arc/modes known; force law tuned by feel)
- Still open: OQ-3.1–3.3, OQ-6.1, OQ-8.3, OQ-8.4 — all Phase 2, all file-inspection or grep work
- **No remaining OQs require running the live game**

**Phase 1 blockers: all resolved. Ready to begin Phase 1 implementation.**

## Instrumentation approach

`tools/appc_logger.py` is the active instrumentation snippet. It is appended to `sdk/Build/scripts/App.py` by `tools/setup.py` and installed into `game/scripts/App.py`. The combined file runs inside the App module namespace, so all module-level names (`UtopiaModule`, `g_kSystemWrapper`, `g_kConfigMapping`, etc.) are available without qualification.

### How to instrument

```powershell
uv run python tools/setup.py            # normal: uses cached .pyc (no recompile)
uv run python tools/setup.py --recompile  # force Python 1.5 to recompile App.py
uv run python tools/setup.py --capture    # after a successful recompile, cache the new .pyc
uv run python tools/uninstall.py          # restore game to working state
```

### Critical constraints discovered during instrumentation

**Python version:** stbc.exe embeds Python 1.5 (magic `0x4E99`), statically compiled into the binary alongside Appc. No separate `python15.dll`.

**Python 1.5 syntax:** `import X as Y` is Python 1.6+ and causes a fatal `SyntaxError` crash at startup. All snippet code must use plain `import X` and save aliases manually (`_time_func = time.time`). No f-strings, no `True`/`False` literals.

**Static build — limited stdlib:** `os` is not compiled into the binary and is not importable. `sys` is always available. Treat every `import` in snippet code as potentially absent and guard with `try/except ImportError`. Do not put any `import` that could fail at the outer module level — put them inside the GetGameTime wrapper where failures are caught.

**Timestamp trick:** `setup.py` writes `App.py` with its mtime set to match the value stored in `App.pyc` (bytes 4–7, little-endian Unix seconds), then copies `App.pyc.bak` as `App.pyc`. Python sees matching timestamps and loads from `.pyc` without recompiling. `--recompile` deliberately skips this trick for one launch to compile new snippet changes; `--capture` then caches the result.

**Python-level file I/O is blocked:** `open()` fails silently for all paths from within the game process (absolute, relative, `%TEMP%`). `os.system()` (cmd.exe subprocess) is also blocked. `sys.stdout.write()` crashes the game (stbc.exe is a GUI subsystem binary with no console handle). Do not use any of these in the snippet.

### Output mechanism: SaveConfigFile

The only confirmed working write path is the C++ engine's own file I/O, accessed via:

```python
g_kConfigMapping.SetStringValue("BCTickLog", "key", "value")
g_kConfigMapping.SetIntValue("BCTickLog", "count", n)
g_kConfigMapping.SaveConfigFile("BCTickLog.cfg")
```

`SaveConfigFile` writes to the game's working directory (`game/`), so the output lands at `game/BCTickLog.cfg`. The file is a full dump of all config state (all sections from `Options.cfg` plus the custom `[BCTickLog]` section appended). `tools/analyze_session.py` parses only the `[BCTickLog]` section.

The ConfigMapping API (argument order confirmed from SDK scripts):
- `SetStringValue(section, key, value)` / `GetStringValue(section, key)`
- `SetIntValue(section, key, value)` / `GetIntValue(section, key)`
- `SetFloatValue(section, key, value)` / `GetFloatValue(section, key)`
- `SaveConfigFile(filename)` / `LoadConfigFile(filename)`

### Current snippet behaviour

`appc_logger.py` wraps `UtopiaModule.GetGameTime` (the per-tick heartbeat called by AI scripts). Each unique `GetUpdateNumber()` frame is recorded as `"%f %d %f" % (wall_time, frame, game_time)` and buffered in a Python list. Every 30 seconds of wall time the buffer is flushed to `BCTickLog.cfg` via `SaveConfigFile`. On any exception, the error type and value are written to `[BCTickLog]` and the file is saved, so failures are visible without needing a debugger.

## Key architectural facts

- Object hierarchy: `ObjectClass → PhysicsObjectClass → DamageableObject → ShipClass`
- Python owns Appc objects it creates; must explicitly clean up in `__del__` via engine calls
- Save/load: 39 classes use `__getstate__`/`__setstate__`; saves Python-side state only, re-looks up Appc handles on restore
- `PythonMethodProcess` cannot be pickled — must be recreated in `__setstate__`
- Two independent time streams: `g_kTimerManager` (game time) and `g_kRealtimeTimerManager` (wall clock)
- Loop is single-threaded from Python's perspective (`sys.setcheckinterval(200)` in `Autoexec.py`)
- Python priority levels actually used: `NORMAL` (most things) and `LOW` (2 scripts only); `CRITICAL`/`UNSTOPPABLE` are C++ internal

## Project-root SDK shims

Some Python files at the project root exist specifically to **shadow SDK modules of the same name**. SDK scripts use bare imports (`import App`, `import LoadBridge`), and `tests/conftest.py` configures `_SDKFinder` to check `PROJECT_ROOT` before falling back to `sdk/Build/scripts/`. This is how Phase 1 swaps real SDK behaviour for headless stubs without forking the SDK tree.

Current shims:
- `App.py` — Phase 1 replacement for `Appc.dll` / `sdk/Build/scripts/App.py`
- `LoadBridge.py` — empty `SetClass` registration so `g_kSetManager.GetSet("bridge")` works headless

Add new SDK-name shadows at the root only when needed; keep application code in `engine/`. If a third shim shows up, consider grouping them into a `shims/` directory and updating `_SDKFinder` accordingly.

## Setup

```bash
# Drop BC installation into game/, BC SDK v1.1 into sdk/
uv sync
uv run pytest
```
