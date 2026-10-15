# Loading `.pyc`-only mod modules: design

**Status:** design, awaiting Mark's review. Nothing is implemented.
**Date:** 2026-10-15
**Branch:** `docs/pyc-mod-loading-spec` (worktree `.claude/worktrees/pyc-mod-loading`, based on local `main` at `a9a1897f`)
**Supersedes, once built:** the photon substitution as the *normal* outcome for the LC Intrepid's torpedoes. It stays as the fallback for bytecode this design cannot load. See `weapon_subsystems._resolve_projectile_module` and branch `fix/torp-ammo-fallback-script` (`be914a7b`, not merged).

---

## 1. Goal

Mod scripts that ship **only** as Python 1.5 bytecode (`.pyc`, magic `0x4E99`, no `.py`) must import and run in Dauntless the way they do in `stbc.exe`. The first consumer is the LC Intrepid Pack's two torpedo projectiles, `Tactical.Projectiles.ZZ_VoyPhoton` and `Tactical.Projectiles.ZZ_Tricobalt`. Both hardpoints (`LCintrepidHP.py:128,130`, `LCvoyagerHP.py:128,130`) name them by dotted path in `SetTorpedoScript`. Today both resolve to the stock photon.

### What Mark asked for, and what this spec assumes

| | |
|---|---|
| **Asked** | Brainstorm only; restore the mod's own torpedoes; answer six questions with evidence; never commit decompiled mod code; anything derived is produced on the user's machine from their installed mod; an unloadable `.pyc` still falls back to the photon with a clear one-time log line naming the module. |
| **Assumed** | "Behaves like BC" means the module's *observable effects*: the calls `Create(pTorp)` makes and the getters' return values. It does not mean bit-identical Python 1.5 runtime semantics; §4.6 lists the places those differ, and we inherit them from the existing source pipeline on purpose. |
| **Assumed** | A loaded `.pyc` must behave exactly as its `.py` would through our existing source pipeline. The `.pyc` is not held to a higher standard than SDK source. |

---

## 2. Evidence, measured 2026-10-15

All of this was produced in the session scratchpad. No decompiled or lifted mod text was written into the repo.

### 2.1 Corpus survey: what ships `.pyc`-only

| Location | `.pyc` files | `.pyc`-only (no sibling `.py`) |
|---|---|---|
| `mods/` (LC Intrepid Pack, DCMPv2) | 2 | **2**: `ZZ_VoyPhoton`, `ZZ_Tricobalt` |
| `bc_mod_tools/extracted` (6 packs) | 9 | the same 2 (a copy of the Intrepid pack); CGSovereign ships 7 `.pyc` **with** their `.py` |
| BC install, game scripts | **1201** | 1201: the retail game ships *every* script as `.pyc` only |
| BC install, SDK scripts | 4 | n/a |

All 11 mod `.pyc` files carry magic `99 4e 0d 0a` (Python 1.5). Every one of the 1201 stock `.pyc` has a matching SDK `.py` at the same relative path, so the stock game has no `.pyc`-only module we cannot already run from source.

**Answer to Q1 (what kinds of module).** Measured, the class is small data-plus-call modules, and today it is exactly one kind: torpedo projectiles. Disassembly shows both Intrepid modules use **13 opcodes and no jumps**, the same 13 as the stock `PhotonTorpedo.pyc`: `SET_LINENO LOAD_CONST LOAD_GLOBAL LOAD_FAST LOAD_ATTR STORE_NAME STORE_FAST CALL_FUNCTION BINARY_DIVIDE POP_TOP RETURN_VALUE IMPORT_NAME MAKE_FUNCTION`.

How common that straight-line shape is across the stock corpus, by directory:

| Directory | jump-free / total |
|---|---|
| `Tactical/Projectiles` | **16 / 16** |
| `Maelstrom/Episode1-8` (mostly mission placement `_P` files) | 306 / 494 |
| `ships/Hardpoints` | **1 / 51** |
| `ships` | **1 / 51** |
| whole stock corpus | 530 / 1201 |

So "small data-plus-call" is right for projectiles and sound packs. It is **wrong for hardpoints and ship modules**, the most common mod content. Those use `if`/`try` and would need control-flow recovery (§9).

### 2.2 What the original game proves

1. **`.pyc`-only import is BC's normal path, not an edge case.** The retail install has 1201 `.pyc` and zero `.py`. A mod that ships only bytecode is doing exactly what Totally Games did.
2. **The mod's `.pyc` was compiled by `stbc.exe` itself.** Its embedded `co_filename` is `.\Scripts\Tactical\Projectiles\ZZ_VoyPhoton.py`, matching the in-game `sys.path[0]` of `.\\Scripts` measured by q14. Stock files carry `c:\utopia\current\build\scripts\...`, TG's build machine. So the author ran the game with a `.py`, let BC's own import write the `.pyc` beside it, and shipped only the `.pyc`.
3. **`.py` beside `.pyc`: source wins when they disagree.** This is stock CPython 1.5 `import.c` behaviour: the `.pyc` is used only if its embedded mtime matches the `.py`'s. CGSovereign is the live case. Its `.pyc` carries 2003 timestamps while the extracted `.py` mtimes are 2026, so BC would recompile from `.py`. All 5 CGSovereign pairs the spike could lift are AST-identical to their `.py` anyway (the 2 ship modules use jumps and were refused). Our "`.py` first" rule is therefore BC-faithful.
4. Not consulted: the `stbc-reference` MCP failed to connect this session (EHOSTDOWN). Nothing here rests on it. The import semantics above are CPython's, and items 1 and 2 are read straight off the install.

### 2.3 Approach (a): does a working Python 1.5 decompiler exist?

`uncompyle6` 3.9.3 (+ `xdis` 6.1.8, both GPL) is already in the main checkout's `.venv`. It is installed ad hoc and is **not** in `pyproject.toml` or `uv.lock`. Tested on the two Intrepid files, then round-tripped over all 1201 stock `.pyc` against their SDK `.py`. The comparison is a normalised Python 3 AST: trailing `return None` stripped, then the same `_fix_py2_syntax` the loader uses.

| Outcome | Files |
|---|---|
| AST identical to the SDK source | 568 |
| differs | 600 |
| **timed out (>30 s, 0.5–1.6 GB RSS per process)**, e.g. `App`, `KeyConfig`, `ships/Hardpoints/akira`, `ambassador`, `GenericTemplate` | 32 |
| emitted invalid Python | 1 |
| stock projectiles identical | **1 / 16** (only `__init__`) |

Two **silent wrong-output** bugs were confirmed against the raw bytecode. "2 okay, 0 failed" is reported for both Intrepid files regardless:

- **Dotted imports lose their submodule.** Bytecode `IMPORT_NAME 'Multiplayer.SpeciesToTorp'` decompiles as `import Multiplayer`. Every projectile does this, both Intrepid files included. In a sample of 60 mismatches, 46 were this bug alone.
- **Constants mis-indexed.** `AI/Compound/BasicAttack.pyc`'s module constants contain `'AvoidTorps'`, `'AggressivePulseWeapons'`, … but the output assigns `g_lAllFlags = [5, 6, 7, …]`.

The raw output is also not loadable as-is: it keeps 1.5's implicit trailing `return`, including a module-level `return`, which is a `SyntaxError` in Python 3.

**Verdict:** a decompiler does exist, but it is not trustworthy unattended. It fails on exactly the files that matter here, silently, and it blows up on the hardpoint class. Using it would need a verifier, and building that verifier is most of the work of approach (b).

### 2.4 Approach (b): a spike lifter (throwaway, scratchpad only)

A ~200-line symbolic stack walker turns **jump-free** 1.5 bytecode into a Python 3 `ast.Module` and *refuses* any opcode it does not know. It used `xdis` for unmarshal and opcode tables. Against the same 1201-file oracle:

| Outcome | Files |
|---|---|
| refused cleanly (jumps 453, `SETUP_EXCEPT` 106, `BUILD_CLASS` 63, `SETUP_LOOP` 38, other 27) | 687 |
| AST identical to the SDK source | **511** |
| differs only in ways bytecode cannot carry (a `global` for a name the function only reads; a `pass`) | 3 |
| wrong | **0** |
| stock projectiles identical | **16 / 16** |

Both Intrepid modules lift and compile under Python 3, and keep `import Multiplayer.SpeciesToTorp`. One real 1.5 trap surfaced: `None` is a *name lookup* in 1.5 (`LOAD_GLOBAL None`), not a constant. Python 3 refuses to compile `Name('None')`, so the lifter maps it to `Constant(None)`. Without that fix, 96 placement files mismatched.

### 2.5 Engine readiness for these two modules

- Every call the Intrepid `Create` makes on `pTorp` is implemented in `engine/appc/projectiles.py`: `CreateTorpedoModel`, `SetDamage`, `SetDamageRadiusFactor`, `SetGuidanceLifetime`, `SetMaxAngularAccel`, `SetLifetime` (`:208`, which the stock photon never calls), and `SetNetType` (a deliberate no-op). None of them appears in `docs/stub_heatmap.md`.
- The textures they name exist under `mods/LC Intrepid Pack/data/Textures/Tactical/`. Launch sounds: one is registered by the pack's Autoload `SoundDef`, the other is a stock name.

---

## 3. Approaches compared (Q2)

| | (a) Decompile once, offline | **(b) Lift bytecode → Python 3 AST in the loader** | (c) Py1.5 bytecode interpreter | (d) Hand-written replacement |
|---|---|---|---|---|
| Works on the two Intrepid files | yes, but **wrong** (`import a.b` → `import a`) | **yes, verified** | yes | yes |
| Trust | silent wrong output measured on stock files; needs a verifier | correct by construction for a closed opcode set; **511/511 exact** on the stock oracle; refuses everything else | must re-implement 1.5 name lookup, import, call and frame semantics | as good as the transcriber |
| Goes through our AST transforms (`_FixDottedImport`, `_MoveGlobalsToTop`, …) | yes, after a text fix-up | **yes, same pipeline as source** | **no**, it bypasses them | yes |
| Licensing | writes decompiled mod source to disk on the user's machine; one stray `git add` from committing it | **in memory only; never produces source text** | in memory | **forbidden**: replacements live in `native/assets/replacements/` in this repo, so this *is* committing derived mod content |
| New dependency | uncompyle6 + xdis + spark (GPL), known to hang on large files | **none** (own 1.5 unmarshal and opcode table) | none | none |
| User step | someone must run a tool | none, it happens at import | none | none |
| Reach | everything, unreliably | straight-line modules now; growable under the same oracle | the implemented subset | one module per hand edit |
| Failure mode | silently wrong behaviour | **loud refusal → named log line → photon** | runtime error deep in the VM | n/a |

**Recommendation: (b).** It is the only option that is both verified and licence-clean by construction. (c) accepts the same inputs as (b) but hands back an opaque VM instead of ordinary Python 3 code, and skips every compatibility transform the SDK already relies on. (a)'s value is real but belongs in tests, not in the loader. (d) is ruled out by the licensing constraint, not just by scale.

---

## 4. Design

### 4.1 Units

One new package, imported by **both** loader copies so the lifter itself is never duplicated:

```
engine/py15/
  __init__.py      public: is_py15_pyc(path) -> bool, lift(path) -> ast.Module,
                   class Py15Unsupported(ImportError)
  marshal15.py     Python 1.5 .pyc reader: magic + mtime header, then the 1.5
                   marshal stream (None, int, long, float-as-text, complex,
                   string, tuple, list, dict, code; 16-bit code-object fields).
                   Pure, no engine imports. ~100 lines.
  opcodes15.py     The 1.5 opcode number → name table (HAVE_ARGUMENT = 90).
  lift.py          Bytecode → ast.Module for the supported subset (§4.2).
                   Raises Py15Unsupported(module_path, reason, opcode, offset).
```

`xdis` is **not** a dependency; it was a spike convenience. The unmarshal reader is small and is proved by a test that it reads all 1201 stock files (§7).

### 4.2 The supported subset, and the rule that grows it

**Rule:** an opcode or code shape enters the subset only when stock-corpus modules exercise it and the oracle test (§7, T2) proves them AST-identical to their SDK source. Anything else raises `Py15Unsupported`.

Initial subset, which is what the spike proved on 511 files:

- **Module/function bodies:** straight-line only, with no jump of any kind and no `SETUP_*`, `FOR_LOOP` or `BREAK_LOOP`.
- **Loads/stores:** `LOAD_CONST LOAD_NAME LOAD_GLOBAL LOAD_FAST LOAD_ATTR`; `STORE_NAME STORE_FAST STORE_GLOBAL` (emitting a `global` declaration) `STORE_ATTR STORE_SUBSCR BINARY_SUBSCR`. `None` loads become `Constant(None)`.
- **Expressions:** `BINARY_*` and `UNARY_NEGATIVE/POSITIVE/INVERT/NOT`; `COMPARE_OP`; `CALL_FUNCTION` (positional + keyword); `BUILD_TUPLE`, `BUILD_LIST`; `BUILD_MAP` and the 1.5 dict-literal pattern (`DUP_TOP` … `ROT_TWO` … `STORE_SUBSCR`) and no other `DUP_TOP`.
- **Statements:** `POP_TOP` (expression statement), `RETURN_VALUE` (the trailing implicit `return None` is dropped), `PRINT_ITEM`/`PRINT_NEWLINE` → `print(...)`.
- **`IMPORT_NAME`** followed by a store of its root name → `import a.b`. Any other store is refused as an alias.
- **`MAKE_FUNCTION`** stored to a name → `def`, with positional parameters and constant defaults. A 1.5 docstring is `co_consts[0]` when it is a string.
- **Refused:** varargs/kwargs flags, tuple parameters, `<lambda>` code (`def` would change `__name__`), nested functions (1.5 has no closures; a nested Python 3 `def` would capture outer locals), `BUILD_CLASS`, `IMPORT_FROM`, `UNPACK_*`, `EXEC_STMT`, `UNARY_CONVERT` (backticks), `RAISE_VARARGS`, `DELETE_*`, slices.

The lifter emits the AST that `ast.parse(_fix_py2_syntax(source))` would produce for the same module. The only textual fix that still applies to bytecode is `.has_key(` → `.__contains__(`, so `LOAD_ATTR has_key` is emitted as `__contains__`. The others (`<>`, octal literals, `print`, old `raise`) are already resolved in bytecode or are outside the subset.

### 4.3 Where it plugs in (Q3)

**Rule:** everywhere the SDK finder asks "does a module file exist here?", a 1.5 `.pyc` counts **when there is no `.py` for the same logical path in the same layer**.

| Site | Change |
|---|---|
| `_mod_override_spec` in **both** `tools/mission_harness.py` and `tests/conftest.py` | Suffix order becomes `.py`, `/__init__.py`, `.pyc`, `/__init__.pyc`. The `.pyc` arms build the same `_SDKLoader`, flagged `bytecode=True`. Every branch that already calls `_mod_override_spec` inherits the change: the dotted path (the Intrepid case), the parent-`__path__` branch and the bare-name stock-match branch. |
| Bare-name mod-index loop at the end of `_SDKFinder.find_spec` (both copies) | Its `fullname.lower() + ".py"` key match also accepts `.pyc` when no `.py` key exists for that stem. |
| `_implicit_relative_fixer` / `_FixImplicitRelativeImport` sibling check (both copies) | `(d / (name + ".py")).exists()` also accepts a `.pyc` sibling. |
| `_SDKLoader.exec_module` (both copies) | The only branch: `tree = engine.py15.lift(path)` instead of read → `_fix_py2_syntax` → `ast.parse`. From `_MoveGlobalsToTop` onward the pipeline is unchanged and shared: every transform, the `apply`/`reload`/`BORG` injections, `also_register_as`, and the `sdk_overrides` second pass all apply to a lifted module exactly as to source. |
| `tests/unit/test_sdk_finder_twins_stay_in_sync.py` | Extended to compare `_mod_override_spec`, the loader's tree-source branch and the sibling check, as well as `find_spec`. |
| Mod overlay file index (`engine/mods.py`) | **No change to resolution.** It already indexes every file, `.pyc` included (`sdk_override("tactical/projectiles/zz_voyphoton.pyc")` hits today). Only the boot report changes (§4.5). |

The stock SDK path is untouched. Stock `.pyc` live in the game install, not the SDK tree, and every stock module has its `.py` (§2.1).

**Precedence**, unchanged in shape; `.pyc` just joins at each layer's tail:

1. project-root shim `.py` (ours always wins)
2. mod `.py`, then mod `/__init__.py`, then **mod `.pyc`**, then **mod `/__init__.pyc`**
3. stock SDK `.py` / `/__init__.py`

A mod `.pyc` therefore beats the stock SDK `.py` of the same module. That matches BC, where the mod's `.pyc` overwrites the retail `.pyc` in the game scripts directory and no stock `.py` exists to recompile from. Between two mods, a `.py` from either beats a `.pyc` from either, because the finder asks for `.py` across the whole index first. That also matches BC: with both files in the scripts directory, the mismatched-mtime `.py` is recompiled.

### 4.4 Failure handling (Q6)

- `lift()` raises `Py15Unsupported` (an `ImportError`) naming the dotted module, the file, the reason and the first offending opcode and offset. Raised in `exec_module`, so importlib removes the half-made module from `sys.modules` as for any failed import.
- **One-time log line, in production, not only `--developer`.** The loader prints once per path, in the existing `[sdk-loader]` style. For example: `[sdk-loader] mod module Tactical.Projectiles.ZZ_Tricobalt (LC Intrepid Pack) is Python 1.5 bytecode this engine cannot load yet (JUMP_IF_FALSE at offset 42); importers fall back where they can`. `dev_mode.log_swallowed` is dev-only and cannot meet "clear one-time log line" alone, but its existing calls at the two fallback sites stay.
- **Projectiles still fall back to the photon.** `_resolve_projectile_module` and `_resolve_torpedo_ammo` (as fixed by `be914a7b`) keep their behaviour unchanged. Only their docstrings change: the photon is now the outcome for *unsupported bytecode*, not for every `.pyc`.
- **A non-projectile `.pyc` that cannot be lifted is an `ImportError`. It does not fall through to the stock module of the same name.** See decision D1 (§8).

### 4.5 Boot report

`mods.report()` gains one line per mod with `.pyc`-only modules, so the player is told at boot rather than mid-battle. Example: `LC Intrepid Pack: 2 bytecode-only scripts, 2 loadable`, or `… 1 not loadable: Tactical/Projectiles/X (JUMP_IF_FALSE)`. The verdict comes from running `lift()` at boot. Cost is O(`.pyc`-only files), currently 2 files, each a few ms. Lifting has no side effects; nothing is executed.

### 4.6 Python 1.5 semantics we inherit, on purpose

A lifted module runs under Python 3 exactly as its source would through our pipeline, including that pipeline's known departures from 1.5. The main one is `BINARY_DIVIDE` on two ints, which floors in 1.5 but is true division in Python 3. Neither `_fix_py2_syntax` nor any AST transform corrects it for SDK source today. Fixing it for `.pyc` alone would make a module behave differently depending on whether its author shipped source. If it is ever fixed, it gets fixed once, as a transform both paths share. Both Intrepid modules divide floats only.

---

## 5. Data flow, LC Intrepid torpedo

```
hardpoint: Torpedoes.SetTorpedoScript(0, "Tactical.Projectiles.ZZ_VoyPhoton")
  → ships._resolve_torpedo_ammo → importlib.import_module(name)
     → _SDKFinder.find_spec → _mod_override_spec(".../ZZ_VoyPhoton")
        .py? no   /__init__.py? no   .pyc? YES (mod index) → _SDKLoader(bytecode=True)
     → exec_module: engine.py15.lift(path) → ast.Module
        → _MoveGlobalsToTop → _implicit_relative_fixer → _FixDottedImport → … → compile → exec
  → ammo type: GetName / GetLaunchSpeed / GetPowerCost from the MOD module
  → TorpedoTube.Fire → _resolve_projectile_module(name) → same module (sys.modules)
     → _spawn_projectile → mod Create(pTorp) → engine/appc/projectiles.py setters
```

---

## 6. Licensing and redistribution (Q4)

1. **No source text is ever produced.** The lifter outputs an `ast.Module` straight to `compile()`. No decompiled `.py` is written to disk, cached, or logged.
2. **No on-disk cache.** Lifting costs milliseconds, so there is no reason to persist anything derived. If profiling ever says otherwise, a cache goes under the user's per-machine state directory, never in the tree. That would be a separate decision.
3. **Tests commit no mod-derived values.** Tests that touch the Intrepid files read them from the user's `mods/` (gitignored, per tree) and compare them against the module's own getters or a committed *digest* (§7, T6), never a literal damage or speed.
4. **Probe results for mod modules are hashed before commit** (§7, T6). Stock-content results follow the existing probe convention.
5. **The lifter, unmarshal reader and opcode table are our own code** and contain no mod content. The scratchpad spike is discarded; nothing from it is copied into the tree verbatim without review.

---

## 7. Testing and fidelity (Q5)

| # | Test | Needs BC content? | Proves |
|---|---|---|---|
| T1 | `marshal15` reads all 1201 stock `.pyc`: header magic `0x4E99`, code objects well-formed | yes (asset-backed, via `engine/paths.py`) | the reader handles everything BC itself shipped |
| T2 | **Stock oracle:** for every stock `.pyc` `lift()` accepts, the AST equals `ast.parse(_fix_py2_syntax(sdk .py))` under a **documented, closed** normalisation (strip trailing `return None`; drop bare string statements and `pass`; drop `global` for names never stored). Floors: accepted ≥ **511**, all 16 `Tactical/Projectiles` accepted. A ratchet in the style of the stub-hardening one: the floor only goes up. | yes | the lifter is right on every shape it accepts |
| T3 | **Synthetic bytecode fixtures:** a *test-only* 1.5 marshal **writer** assembles tiny `.pyc` from our own opcodes, one per supported opcode plus one per refusal class (jump, class, varargs, lambda, nested def, alias import) | **no** | lifter coverage and refusal messages on a machine with no BC install |
| T4 | **Loader integration, both twins:** a temp `mods/` with a synthetic `.pyc`-only module (new, and overriding a stock module) resolves through the real finder; precedence cases from §4.3 (mod `.py` vs mod `.pyc` vs stock `.py`; two mods); bare-name and sibling-import shapes; an unsupported `.pyc` gives `Py15Unsupported` and exactly one log line | no | §4.3 wiring and §4.4 behaviour in both import worlds |
| T5 | **Intrepid E2E:** with `mods/` present, `import Tactical.Projectiles.ZZ_VoyPhoton` / `ZZ_Tricobalt` → `__spec__.origin` ends `.pyc` and the module is not the photon; `_resolve_torpedo_ammo` reports the module's own `GetName()`/`GetLaunchSpeed()`; `_spawn_projectile` yields a torpedo whose damage, guidance lifetime, angular accel and lifetime equal the module's getters; no `Py15Unsupported`, no fallback log | mods/ (worktree setup step 4 clones it) | the bug is fixed end to end, with no mod literal in the repo |
| T6 | **BC differential probe (`q20`)**, per `docs/instrumented_experiments/console-probe-workflow.md`: in `stbc.exe -TestMode` with the Intrepid pack installed, import each of the 16 stock projectiles plus the 2 Intrepid ones, call every getter, and call `Create(rec)` with a Python 1.5 **recorder** instance whose `__getattr__` logs `(method, args)` (`TGColorA` arguments serialised as RGBA). Results go to `[BCProbe_q20]`. `collect_q20.py` commits stock traces in full and replaces each mod trace with the **sha256 of its canonical text**. The matching Dauntless test runs the same recorder through our loader and compares: full text for stock, digest for mod. | operator run on the Windows BC machine | lifted modules make the **same calls with the same values as in BC**. This is the direct answer to "behaves like BC". |

T6 is the fidelity proof. T2 and T5 can land without it. T6's Dauntless half lands together with the probe result, so no test ever ships before its golden data exists (no known-failing tests).

**Live check (Mark):** Quick Battle with the LC Intrepid, both as player and as AI. Torpedoes fire with the mod's own visuals (the `ZZ_*` core/glow textures, not the stock photon look). No `[sdk-loader] … cannot load` line appears for these two modules. The AI still reaches its phasers, which is the `be914a7b` regression guard.

---

## 8. Decisions for Mark

- **D1. Unsupported `.pyc` that shadows a stock module.** *Recommended:* `ImportError` plus the log line, with **no** fall-through to the stock `.py`. A silent stock substitute is the same kind of infidelity as the photon, but without a caller choosing it, and a mod that ships its own version usually has other scripts that depend on it. *Alternative:* fall through to stock with the log line, which keeps a mod-patched stock screen running. The corpus has **zero** such files today, so this sets policy only.
- **D2. Scope: straight-line subset only.** *Recommended:* yes. It covers 100% of today's `.pyc`-only corpus and all 16 stock projectiles. Control-flow recovery (§9) waits for a real `.pyc`-only mod that needs it.
- **D3. Order relative to `be914a7b`.** *Recommended:* merge `fix/torp-ammo-fallback-script` first. This design keeps its fallback and only changes its docstrings.

---

## 9. Out of scope, and known limits

- **Control flow** (`if`/`while`/`for`/`try`, classes). This is what hardpoints, ship modules and most mission scripts would need: only 1/51 hardpoints is straight-line. It is a real decompiler problem. The T2 oracle (687 currently refused stock modules, each with its SDK source) is the test bed when a real mod needs it. `uncompyle6` may help *offline as a cross-check in tests*, never in the loader.
- **Foundation plugin enumeration** (`engine/foundation/loader.py:_scripts_in`, `.py` only, executed by `runpy.run_path`, which bypasses the SDK loader entirely). The same applies to `ship_catalog/gate_writer.py` and `mods.detect_frameworks`. There are zero `.pyc`-only plugins in the corpus; extending these is a separate change.
- **Python 1.5 runtime semantics** beyond what the source pipeline already does (§4.6).
- **Mod `.pyc` with a non-1.5 magic** (e.g. from a Python 2 tool). Detected by `is_py15_pyc` and reported as unsupported, not attempted.

---

## 10. Spike artefacts

Everything is in the session scratchpad: `roundtrip.py` and `driver.py` (the uncompyle6 oracle), `lifter.py` and `lift_corpus.py` (the (b) spike), `opsurvey*.py`, `roundtrip.json`. These are throwaway and are not committed. They contain decompiled stock and mod text and must not be copied into the repo.
