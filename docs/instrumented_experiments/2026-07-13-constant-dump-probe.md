# Engine constant dump — ground-truth values for every `App` constant

Status: ANSWERED — menu + battle phases captured & analyzed 2026-07-13. Surface
        confirmed state-invariant. Shim fix pass (226 wrong + ~1600 unique
        missing) is the remaining follow-up work, tracked separately.
Author: Claude session (q13 constant-surface probe plan)
Created: 2026-07-13
Closed:  2026-07-13

## Goal

Produce ground-truth integer / long / float / string values for **every constant
the real `App` module exposes**, across **both** namespaces that carry them:

1. **Module scope** — `App.ET_TORPEDO_FIRED`, `App.WC_TAB`, `App.MASK_*`, …
2. **Class scope** — `App.TGUIObject.ALIGN_UL`, `App.EngRepairPane.REPAIR_AREA`,
   `App.STButton.STBSF_SIZE_TO_TEXT`, …

The dump lets us (a) replace guessed or dynamically-allocated constant values in
our repo `App.py` shim with the real ones, and (b) directly kill the **silent
stub-constant** bug class documented in [`docs/stub_heatmap.md`](../stub_heatmap.md):
an undefined `App.<NAME>` or `App.<CLASS>.<CONST>` degrades to a truthy `_Stub`
or coerces to `int()==0`, which has already produced ≥4 real bugs (`WC_*`
keycodes, `TGUIObject.ALIGN_*` collapsing every `AlignTo` to `ALIGN_UL`,
`EngRepairPane.REPAIR_AREA`, `STTopLevelMenu_GetOpenMenu`).

## Background

Our shim (`App.py` at repo root) defines the constants it has needed so far by
hand, and — critically — with **values it made up**:

```python
ET_AI_TIMER = 100
ET_ACTION_COMPLETED = 101
...
ET_CHARACTER_ANIMATION_DONE = 112   # "112 is the next free contiguous value"
```

The real engine sources these from the compiled binary:

```python
# sdk/Build/scripts/App.py
ET_AI_TIMER      = Appc.ET_AI_TIMER
ET_TORPEDO_FIRED = Appc.ET_TORPEDO_FIRED
WC_TAB           = Appc.WC_TAB
class TGUIObject:
    ALIGN_UL = Appc.TGUIObject_ALIGN_UL
```

`sdk/Build/scripts/App.py` is the SWIG *interface* — it tells us the **names**
(`Appc.ET_TORPEDO_FIRED`) but not the **values**, because the values live in the
compiled `Appc.dll`. Static reading of the SDK can enumerate the surface; only a
running engine can report the numbers. Two consequences we are chasing:

- Where our shim guessed a value (e.g. `ET_*` in the 100–200 band), that value is
  almost certainly **wrong** versus BC. It has not mattered yet because the shim
  is internally self-consistent, but it breaks the moment we touch anything that
  compares against a real engine value (save files, event-type maths that the SDK
  hard-codes, bitmask constants combined with `|`).
- Where our shim never defined a constant at all, it silently stubs. A stubbed
  **bitmask** or **enum** is worse than a wrong scalar: `WC_TAB` as a truthy stub
  makes *every* key compare equal; `ALIGN_UL == ALIGN_UR == …` as stubs collapse
  every alignment.

`sdk/Build/scripts/App.py` is 14,078 lines with ~1,597 module-level assignments,
plus per-class constant blocks. The real scalar-constant count is unknown until
we dump it — which drives the volume-handling design below.

## Specific questions

- **Q13-1** — For every **module-scope** scalar `App.<NAME>` (int / long / float /
  string), what is its exact value? (Primary payload.)
- **Q13-2** — For every **class** in `dir(App)`, for every **class-scope** scalar
  `App.<CLASS>.<NAME>`, what is its exact value? (The scope a naïve `dir(App)`
  misses — and the scope that produced the `ALIGN_*` / `REPAIR_AREA` bugs.)
- **Q13-3** — What is the `type()` of every name in `dir(App)`? We want an
  inventory: how many scalars vs classes vs functions vs instances (the `g_k*`
  singletons). This tells us the shape of the surface and guards the dump against
  silently skipping a category.
- **Q13-4** — Is the constant surface **state-invariant**? Almost everything
  `App` exposes is bound at `import App` from compiled-in `Appc.dll` values, so
  loading a mission should not change it — **except** possibly runtime-registered
  event types (our shim fakes these with a dynamic `Game_GetNextEventType()`
  allocator, hinting BC may allocate some `ET_*` at runtime). So we dump in two
  states and diff: a menu dump could be a strict *subset* of an in-battle dump. If
  identical → surface proven state-invariant. If the battle dump is a superset →
  we have discovered runtime-registered constants, itself a finding.
- **Q13-5** *(stretch, separate probe q13b)* — For every class, what **method**
  names does it expose (`dir(cls)` minus the scalars)? Lets us diff our shim's
  method coverage independently of the constant work. Kept in a separate file so
  the constant dump stays focused.

## Probe

`tools/probes/q13_constants.py` — one-shot `execfile()` probe (like q11). q13
needs **no** event handlers and **no** combat state; it only reads static module
and class attributes, so the `import`-a-module pattern that q12 needed (for
`AddBroadcastPythonFuncHandler` resolution) is unnecessary here. `execfile()` in
the REPL is correct and simplest.

`tools/probes/q13b_method_surface.py` *(stretch)* — same skeleton, dumps method
(callable) names per class instead of scalar values. Phase-less (method surface
is bound at import, so state-invariant): run once at the menu with
`execfile('q13b_method_surface.py')`, collect with
`uv run python tools/probes/collect_q13.py methods` →
`tools/probes/results/q13b_method_surface.txt`. Same `_CHUNK = 1` fallback if the
single-file write truncates.

### Two phases, auto-detected (Q13-4)

The operator runs the *same* probe twice — once at the boot menu, once after
starting a battle — and the probe **derives its own phase** from live state, so
there is no flag to edit and no way to mislabel a run:

```python
_player = None
try:
    _player = App.Game_GetCurrentPlayer()
except:
    _player = None
if _player is not None:
    _PHASE = "battle"                # a ship exists -> a mission/battle is live
else:
    _PHASE = "menu"                  # boot menu, nothing loaded
```

`_PHASE` becomes a suffix on the section name and output file
(`BCProbe_q13_menu` / `BCProbe_q13_battle`), so the two dumps never overwrite
each other and can be diffed off-box. The dump logic below is identical for both
phases.

### What the probe does

1. **Build Python-1.5 type sentinels** (no reliance on the `types` module, which
   may be absent from the static build — guard the import and fall back):

   ```python
   _T_INT   = type(0)
   _T_LONG  = type(0L)          # 0L literal is valid in 1.5
   _T_FLOAT = type(0.0)
   _T_STR   = type('')
   class _Probe:                # a throwaway old-style class
       def _m(self): pass
   _T_CLASS = type(_Probe)      # <type 'class'>
   _T_INST  = type(_Probe())    # <type 'instance'>
   _SCALARS = (_T_INT, _T_LONG, _T_FLOAT, _T_STR)
   ```

   Classification (do **not** assume `isinstance`-on-tuple semantics; use `in`):
   `type(v) in _SCALARS` → scalar; `type(v) == _T_CLASS` → class;
   `type(v) == _T_INST` → instance (the `g_k*` singletons); everything else
   ("function", "builtin_function_or_method", "None", …) → other.

2. **Module scope (Q13-1 / Q13-3).** Iterate `dir(App)`. For each name, a
   **bare-`except`-guarded** `getattr(App, name)` (a bad SWIG attribute must not
   abort the dump). Classify by type. For scalars, emit a dump line. Tally every
   category for the inventory summary.

3. **Class scope (Q13-2).** For each name classified as a class, iterate
   `dir(cls)`. Python 1.5 `dir(cls)` does **not** reliably walk base classes, so
   also walk `cls.__bases__` recursively (guarded) and union the names, so a
   constant defined on a base is still reached. For each attribute name,
   guarded `getattr(cls, name)`; if scalar, emit `App.<CLASS>.<NAME>`. Dedup by
   fully-qualified name (a constant reached via two inheritance paths is emitted
   once).

4. **Output line format** — one line per constant, fully-qualified, so the
   result diffs cleanly off-box:

   ```
   App.ET_TORPEDO_FIRED = 8388728 (0x800078) int
   App.PI = 3.14159265358979 float
   App.TGUIObject.ALIGN_UL = 0 (0x0) int
   App.SomeString = 'photon' str
   ```

   - ints / longs: decimal, then `(0x…)` hex (both guarded — negative or huge
     values fall back to decimal-only), then the `type().__name__`.
   - floats: `repr(v)` (full precision — `str()` truncates in 1.5), then typename.
   - strings: `repr(v)` (repr escapes embedded newlines/`=`/control chars that
     would otherwise corrupt the line-based cfg format), **truncated to 200 chars**,
     then typename.
   - All names **sorted** before emission (module block sorted, then each class
     block sorted, classes in sorted order) for a stable, diffable artifact.

5. **Inventory header (Q13-3), emitted FIRST** so truncation is detectable
   off-box:

   ```
   -- inventory ------------------------------------------------
   dir_App_names = 812
   module_scalars = 634
   classes = 141
   instances = 22
   others = 15
   class_scalars = 1180
   total_dump_lines = 1814          <-- the invariant
   ```

   `total_dump_lines` is the load-bearing number: after collection, if the
   result file has fewer dump lines than this, the write **truncated** and the
   run is invalid. This is the anti-silent-truncation guard.

### Volume + `SaveConfigFile` strategy — the critical design point

`SaveConfigFile` rewrites the **entire** config (all of `Options.cfg`) and
appends our section on every call, and `g_kConfigMapping` has **no `RemoveKey`**,
so keys only accumulate. The unknown is whether a `[BCProbe_q13]` section with
~2,000 short string keys serialises cleanly, or hits an internal per-section cap.

All file/section names below carry the `_PHASE` suffix — `BCProbe_q13_menu` or
`BCProbe_q13_battle`. `_SECTION` and `_CFG_FILE` are built from it.

**Primary mode — single file, single flush, count-checked.**
Emit everything into one `[BCProbe_q13_<phase>]` section,
`SaveConfigFile("BCProbe_q13_<phase>.cfg")` once, then scrub (write-then-scrub in
the same execution slice, per `console-probe-workflow.md`). The `total_dump_lines`
invariant makes truncation **loud, not silent**: the collected line count must
equal it. If `SaveConfigFile` raises, or the count check fails, fall to chunked
mode.

**Fallback mode — chunked multi-file (`_CHUNK = 1` at the top of the probe).**
Split the sorted dump into chunks of `_CHUNK_SIZE = 400` rows. For chunk *k*:
renumber rows `r0..`, `SaveConfigFile("BCProbe_q13_<phase>.cfg")` for chunk 0 and
`"BCProbe_q13_<phase>_<k>.cfg"` for *k*≥1, then **scrub this chunk's keys before
building the next** so no single section ever holds more than one chunk of live
values. Cap at `_MAX_CHUNKS = 50` (20,000 rows); if the dump would exceed that,
emit an explicit `OVERFLOW at N` marker row rather than dropping rows silently.
`tools/probes/collect_q13.py` (a dedicated merger — generic `collect.py` only
reads a single unnumbered file) globs `game/BCProbe_q13_<phase>*.cfg` in filename
order for each phase, extracts `[BCProbe_q13_<phase>]` from each, and
concatenates. The chunk-0 header still carries `total_dump_lines`, so the same
invariant validates the merge.

Operator runs primary mode first; only flips `_CHUNK = 1` if the primary run
errors or fails the count check (the runbook says exactly when).

## How to run

### On the dev machine (author + push)

```bash
uv run python tools/probes/push.py q13          # copies q13_constants.py into game/
# (stretch) uv run python tools/probes/push.py q13b
```

### On the Windows BC machine

**Step 1 — get the probe into `game/`.**

```
git pull
uv run python tools/probes/push.py q13
```
Confirm `game\q13_constants.py` exists.

**Step 2 — launch BC with the dev console.**

```
cd game
stbc.exe -TestMode
```

**Step 3 — dump the MENU phase, immediately, before loading anything.** In the
REPL:

```python
execfile('q13_constants.py')
```

The probe detects no current player and labels itself `menu`. It prints the
`-- inventory --` block first (note `total_dump_lines`), streams the dump, then
one of:

- `wrote BCProbe_q13_menu.cfg with <N> lines` + `done (phase=menu)` — **primary
  mode wrote.** (Whether it truncated is confirmed off-box in Step 5 — the probe
  cannot read its own file back, `open()` is blocked.)
- a `save FAILED: …` line — **`SaveConfigFile` raised.** Re-run in chunked mode:
  edit `game\q13_constants.py`, set `_CHUNK = 1` at the top,
  `execfile('q13_constants.py')` again. It writes `BCProbe_q13_menu.cfg`,
  `BCProbe_q13_menu_1.cfg`, … and prints `done (phase=menu, chunked, K files)`.
- If Step 5's `collect_q13.py` later prints `COUNT MISMATCH` (collected `App.`
  lines < the header's `total_dump_lines`), the single-file write **truncated** —
  re-run that phase in chunked mode.

**Step 4 — dump the BATTLE phase.** Start a **QuickBattle** (Galaxy vs. Galaxy is
the canonical matchup — see the canonical-scenarios doc) and fly until you are in
space. Then, in the console:

```python
execfile('q13_constants.py')
```

Now the probe detects a current player and labels itself `battle`, writing
`BCProbe_q13_battle.cfg` and printing `done (phase=battle)`. Same chunked
fallback if it fails to write cleanly.

> If Step 4 is inconvenient on a given run, the menu dump alone still answers
> Q13-1/2/3 — it is only Q13-4 (state-invariance) that needs both phases.

**Step 5 — collect and commit both phases.**

Primary mode:
```
uv run python tools/probes/collect_q13.py           # merges both phases + chunks
```
(`collect_q13.py` handles the single-file case too; use it, not the generic
`collect.py`, because of the phase suffix.) Then:
```
git add tools/probes/results/q13_constants_menu.txt tools/probes/results/q13_constants_battle.txt
git commit -m "probe: q13 engine constant dump (menu + battle)"
git push
```

> **Sanity gate before committing:** open each
> `tools/probes/results/q13_constants_<phase>.txt`, read `total_dump_lines` in the
> inventory header, and confirm the file has at least that many `App.` lines. If
> short, the run truncated — do **not** commit it as final; re-run that phase in
> chunked mode.

## Expected output

`tools/probes/results/q13_constants_menu.txt` and
`tools/probes/results/q13_constants_battle.txt` — each the inventory header, then
the module-scope scalar block (sorted), then one block per class (sorted). E.g.:

```
-- inventory ------------------------------------------------
python_version = 1.5.2 ...
dir_App_names = ...
module_scalars = ...
classes = ...
instances = ...
class_scalars = ...
total_dump_lines = ...
-- module scalars -------------------------------------------
App.ET_AI_TIMER = ... (0x...) int
App.ET_TORPEDO_FIRED = ... (0x...) int
App.ET_WEAPON_FIRED = ... (0x...) int
App.PI = 3.14159265358979 float
App.WC_TAB = ... (0x...) int
...
-- class TGUIObject -----------------------------------------
App.TGUIObject.ALIGN_UL = 0 (0x0) int
App.TGUIObject.ALIGN_UR = ... (0x...) int
...
-- class EngRepairPane --------------------------------------
App.EngRepairPane.REPAIR_AREA = ... (0x...) int
...
```

## Analysis

Read the result files directly for spot-checks; the systematic pass is the
off-box diff (specified below, **not** run in-game):

**Q13-4 first — diff the two phases.** `diff` the `menu` and `battle` result
files. Identical (modulo the `total_dump_lines`/inventory header) → the surface
is **state-invariant**, and `menu` is the canonical dump to use everywhere.
`battle` a strict superset → the extra names are **runtime-registered
constants** (likely event types); record them in Findings and prefer `battle` as
the source of truth.

`tools/probes/analyze_q13_constants.py` — parses the result file (`battle` if it
is a superset, else `menu`), parses the repo `App.py` shim's own constant
definitions, and cross-references `docs/stub_heatmap.md`, emitting three buckets:

1. **WRONG** — constants the shim defines with a value that disagrees with the
   dump (e.g. `ET_*` guessed in the 100–200 band). Highest priority: these are
   live latent bugs.
2. **MISSING** — constants present in the dump that the shim does not define at
   all (so they hit the `_Stub` / `_NamedStub` path). Cross-referenced against the
   heatmap's coercion/truthiness tables to rank by observed live hit count.
3. **RESOLVABLE COERCION SITES** — heatmap truthiness / `int()==0` call sites
   whose underlying undefined constant now has a real value in the dump, i.e. the
   sites this probe directly unblocks.

The analyzer is a reporting tool; applying its output (editing the shim) is
follow-up work, one constant/bucket at a time with the test gate between.

## Cleanup

Delete `game\q13_constants.py` and any `game\BCProbe_q13_*.cfg` (both phases, all
chunks). The probe scrubs its own cfg keys after writing (write-then-scrub), so
`Options.cfg` is not polluted. It makes **no** modification to `App.py` or any
game file.

## Findings

### Menu phase — captured 2026-07-13 (`results/q13_constants_menu.txt`)

The single-file write handled the full section cleanly (232 KB, 4156 lines,
**no truncation** — collector reported `3831/3831 rows (complete)`), so chunked
mode was not needed. The probe ran for a few minutes with **no console output
until the end** (it gathers everything before printing); the game window looks
frozen throughout because the dump runs on the single game-loop thread. Not a
hang — just slow and silent. (A future revision should print progress markers
and cut per-line console spam.)

**Q13-3 inventory (menu):** `dir(App)` = 2681 names → 1319 module scalars,
2512 class scalars across 630 classes, 128 instances, 604 others.
`total_dump_lines = 3831`.

**Q13-1/Q13-2 — analyzer buckets vs. our shim** (`analyze_q13_constants.py`,
735 shim constants): `wrong=226  missing=3298  live=1  extra=202`.

Headline results:

- **`CharacterClass` state constants are BITFLAGS; our shim made them
  sequential.** `CS_TURNED=4, CS_UI_DISABLED=8, CS_HIDDEN=16, … CS_UI_ENABLED=2048`
  are consecutive powers of two meant to be OR'd/masked, and
  `CS_STOP_INITIATIVE=4056` is a composite mask. Our shim's `3,4,5,…` breaks any
  bitwise character-state logic. `CAT_*` has the **inverse** error (we used
  bitflags; engine is sequential 0–6). `CSP_MISSION_CRITICAL`/`CSP_SPONTANEOUS`
  are **swapped** (engine 0 / 2, shim 2 / 0).
- **Every `ET_*` value is wrong.** Engine events live in the `0x800000+` band
  (base 8388608), e.g. `ET_AI_TIMER=8388640` (shim `100`),
  `ET_DELETE_OBJECT_PUBLIC=1` (shim `200`). Incidentally answers q12:
  `ET_TORPEDO_FIRED=8388710`, `ET_WEAPON_FIRED=8388732`.
- **Bucket 3 (live-hit, the payoff):** `WeaponHitEvent.TRACTOR_BEAM=2` — 16,023
  recorded stub hits (heatmap rank #6), currently stubbed. High-priority fix.

Read-correctly caveats:
- `missing=3298` is **inflated by SWIG `*Ptr` twins** — every `App.Foo.BAR` also
  appears as `App.FooPtr.BAR`. Unique count is roughly half; the fix pass should
  dedupe on the non-`Ptr` class.
- `live=1` is **expected**: the heatmap's high-hit rows are mostly *methods*
  (`UpdateCharge`, `GetMaxCharge`), which are not constants, so only
  constant-shaped stubs can match.
- `extra=202` (shim defines, engine dump lacks) does **not** shrink in the battle
  phase (see Q13-4 below), so these are genuinely shim-invented — our fabricated
  `ET_*` (e.g. `ET_SET_PLAYER`, `ET_EXITED_SET`, `ET_OBJECT_GROUP_*`) and other
  shim-only additions that have no engine counterpart. When replacing shim values
  with real ones, drop / re-home these rather than assign them fake values.

### Battle phase — Q13-4 (state-invariance): ANSWERED — surface is invariant

Battle dump (`results/q13_constants_battle.txt`) = 3832 constants, clean, no
truncation. Diff against the menu dump (3831):

- **Zero value changes. Zero constants dropped.**
- **Exactly one name added in battle: `App.iNumFires = 0`** — and it is **not an
  engine constant.** `sdk/Build/scripts/Bridge/BridgeMenus.py:22` does
  `App.iNumFires = 0`, an SDK script hanging a global fire-counter onto the `App`
  module namespace; it appears only because the bridge ran during the battle.

Conclusions:

- The engine constant surface is **state-invariant**. The
  runtime-registered-event-type hypothesis (Q13-4's motivation — our shim's
  dynamic `Game_GetNextEventType()` allocator) is **disproven**: every `ET_*` is
  compiled-in and already present at the boot menu.
- **`menu` is the canonical dump** — it is the real engine surface without the
  `iNumFires` script-noise. Use `results/q13_constants_menu.txt` for the shim fix
  pass. (Any future static-surface probe can dump in a single state.)
