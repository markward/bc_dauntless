# Engine environment census + shared probe harness (q14)

Status: PENDING
Author: Claude session (q14 environment & harness plan)
Created: 2026-07-13
Closed:  —

## Goal

Two jobs in one probe, because they share a preamble:

1. **Environment census (the payload).** Dump exactly what the *embedded* Python
   1.5 runtime looks like inside `stbc.exe`: which modules are compiled into the
   static binary, which are importable, which the engine has already imported, and
   the interpreter's own vitals. This permanently answers the "is `X` importable?"
   question that **every** prior probe hedges against with `try/except ImportError`.

2. **Ship the shared harness (`probe_harness.py`).** q15, q16, and q17 all need
   the same two things: a **scenario-provenance preamble** (so a live dump is
   self-identifying and diffable) and a **persistent event-handler owner** (so an
   event probe survives an E1M1 set transition). q14 authors those once, as an
   importable module, and proves them out on itself before the heavier probes
   depend on them.

## Background

CLAUDE.md and `console-probe-workflow.md` record a pile of hard-won facts about
the runtime — Python 1.5.2 (magic `0x4E99`), `os` absent, `open()` blocked,
`string` present, `math` "may be absent" — but these were discovered
*ad hoc*, one crash at a time. Nobody has ever dumped the authoritative list. As a
result every probe carries defensive scaffolding for imports that may or may not
be a real risk, and we still guess.

`sys` is always available, and it exposes the ground truth directly:

- `sys.builtin_module_names` — modules compiled **into the binary** (C-level).
- `sys.modules` — every module **currently loaded** (a superset that grows as the
  game imports SDK scripts).
- `sys.path` — where a bare `import` will look (confirms `game/` is on it, which is
  what makes importable probes like q12/q15 work).
- `sys.version`, `sys.copyright`, `sys.platform`, `sys.maxint`, `sys.argv`.

The `sys.modules` list is **phase-sensitive** (a loaded mission has imported far
more than the boot menu), which is itself informative: diffing menu vs battle
`sys.modules` reveals the import graph a mission pulls in. `builtin_module_names`
and `sys.path` are phase-invariant.

## Specific questions

- **Q14-1** — What is in `sys.builtin_module_names`? (The definitive "what C
  modules exist" list — invariant.)
- **Q14-2** — For a fixed candidate list of stdlib modules we care about (`os`,
  `string`, `math`, `re`, `time`, `types`, `cPickle`, `pickle`, `struct`,
  `marshal`, `copy`, `random`, `operator`, `traceback`), which actually
  `import` cleanly, and which raise? (Turns "may be absent" into a table.)
- **Q14-3** — What is in `sys.modules` at menu vs. in a battle, and what does the
  **diff** reveal about a mission's import graph?
- **Q14-4** — Interpreter vitals: `sys.version`, `sys.maxint` (16- vs 32-bit int
  boundary — matters for the hex formatting in q13 and any bitmask work),
  `sys.platform`, `sys.path`.
- **Q14-5** *(harness validation, not a question about the engine)* — Does
  `probe_harness.py`'s provenance preamble and persistent-owner helper import and
  run cleanly from both an `execfile()` probe and an `import`ed probe?

## The shared harness — `probe_harness.py`

Pushed to `game/` alongside the probes (it is on `sys.path`, so both
`execfile('q1N_*.py')` probes and `import q1N_*` probes can `import probe_harness`).
It is **not** itself a probe — it defines helpers and records nothing on its own.

It must be Python-1.5 clean (see constraints below) and **defensive**: a missing
SDK symbol must degrade to a recorded `"?"`, never an exception that aborts the
caller.

### `probe_harness.provenance()` → list of `"key = value"` strings

The self-identifying header every live-state probe emits first. Returns (does not
print) so the caller controls the section:

- `scenario` — best-effort classification: `"A (Galaxy vs Galaxy QB?)"` /
  `"B (mission)"` / `"menu"` / `"unknown"`. Derived from live state, **not** a flag:
  no player → `menu`; a player + `MissionLib.GetEpisode()` naming a Maelstrom
  mission → `B`; a player but no scripted episode → `A`. The trailing `?` on
  Scenario A is deliberate — the probe cannot *prove* both ships are Galaxies, so
  it reports the roster (below) and lets the operator/analyst confirm.
- `set_name` — `g_kSetManager.GetRenderedSet().GetName()`.
- `mission_module` — episode/mission module name if reachable.
- `game_time`, `frame` — `g_kUtopiaModule.GetGameTime()`,
  `g_kSystemWrapper.GetUpdateNumber()`.
- `roster` — one line per ship in the rendered set: `objid | cast-type | name`
  (reuses the `_describe`-style cast ladder; see q16). This is what makes
  "Scenario A" checkable after the fact and what lets q15/q16 tie events/objects
  to named ships.

### `probe_harness.persistent_owner()` → a TGObject

The `self` handed to `AddBroadcastPythonFuncHandler`. Returns the **episode**
(`MissionLib.GetEpisode()`) when one exists, because it outlives individual set
transitions in E1M1; falls back to the player ship (QuickBattle has no episode),
then to `None`. q15's runbook additionally re-arms on set-change events as a belt-
and-braces measure — see that doc. Documented here so there is one owner policy,
not three.

### `probe_harness` shared plumbing

Re-export the `_record` / `_section` / `_flush` / `_exc_name` helpers from
`_template.py` so q15/16/17 stop copy-pasting them. Keep the single-file **and**
the q13-style chunked flush (with the `total_dump_lines` truncation invariant) —
q15's tally is small but q16/q17's graph dumps can be large.

### Console output discipline — the q13 friction lesson (MANDATORY)

q13 taught us that **printing to the in-game console is the dominant cost**:
`print` is a synchronous write to the `-TestMode` console, and the `_template.py`
helpers `print` **every buffered line** (`_record` does `_log.append(line)` *and*
`print line`). A ~2000-line dump therefore did ~2000 console writes and took **~30
minutes**; removing the per-line prints cut it to **~10 seconds**. Every q14–q17
probe emits many lines through these helpers, so this is a cross-cutting hazard,
not a q13 quirk.

The harness fixes it **once, for all four probes**, by decoupling buffering from
echoing:

- `_record` / `_emit` / `_section` append to `_log` **only — no `print`.** This is
  the change from `_template.py`. The result file is unaffected (it is built from
  `_log`); only the console spam goes away.
- A separate `_echo(msg)` is the *only* thing that prints, reserved for a **handful
  of status lines**: armed/owner confirmation, `wrote <file> with N lines`,
  `save FAILED`, `done`, and `FATAL`. Never call `_echo` inside a data loop.
- Optional `_VERBOSE = 0` knob: when set to `1`, `_record` also echoes, for
  interactive debugging of a *small* run only. Ships as `0`.

**Rule for q15/q16/q17:** nothing that runs per-object, per-subsystem, per-event, or
per-constant may `print`. Emit into `_log`; print a one-line summary at the end.

> **push.py note:** the operator must push `probe_harness.py` into `game/` too.
> Either extend `push.py` to always copy `probe_harness.py` alongside any `q1[4-7]`
> probe, or document `uv run python tools/probes/push.py probe_harness` as an
> explicit first step in each runbook. Decide at implementation time; the plans
> below assume it is present in `game/`.

## The probe — `tools/probes/q14_env.py`

One-shot `execfile()` probe. No combat state needed for the payload, but run it in
both phases for Q14-3. Uses the two-phase auto-detection pattern from q13 (`_PHASE`
from "does a current player exist"), so output lands in
`BCProbe_q14_<phase>.cfg`.

What it does:

1. `import probe_harness` and emit `probe_harness.provenance()` (validates Q14-5).
2. **Q14-1** — dump `sys.builtin_module_names` (sorted).
3. **Q14-2** — loop the fixed candidate list; for each, `try: import <m>` inside a
   guarded block and record `available` / `ABSENT: <exc>`. (Import names are a
   *fixed literal list* in the source, not dynamic — a 1.5 dynamic `__import__`
   dance is unnecessary and riskier.)
4. **Q14-3** — dump `sys.modules.keys()` (sorted). Large in battle; route through
   the harness flush so it can chunk if needed.
5. **Q14-4** — record `sys.version`, `sys.maxint`, `sys.platform`, `sys.copyright`,
   `sys.path` (list, one entry per line).
6. Flush.

## How to run

Push `probe_harness.py` + `q14_env.py` into `game/` (see push.py note). In the
`-TestMode` REPL:

**Menu phase (before loading anything):**
```python
execfile('q14_env.py')
```
Writes `BCProbe_q14_menu.cfg`, prints `done (phase=menu)`.

**Battle phase (Scenario A — start Galaxy vs Galaxy QuickBattle, fly, then):**
```python
execfile('q14_env.py')
```
Writes `BCProbe_q14_battle.cfg`, prints `done (phase=battle)`.

Collect (a dedicated `collect_q14.py` mirroring `collect_q13.py`, because of the
phase suffix + possible chunks) and commit both result files.

## Expected output

Per phase: a provenance block, then `builtin_modules`, the `stdlib availability`
table, `sys_modules` (large in battle), and the interpreter-vitals block. The
`stdlib availability` table is the headline — a permanent reference like:

```
os      = ABSENT: ImportError: No module named os
string  = available
math    = available            <- resolves the "may be absent" hedge
types   = available
cPickle = available            <- relevant to the BCS save-format work
```

## Analysis

- **Q14-2 promoted to a doc.** Copy the availability table into
  `console-probe-workflow.md` as the authoritative "what you may import" reference,
  so future probes stop guarding imports that were never at risk (and *do* guard
  the ones that genuinely are).
- **Q14-3 diff** menu vs battle `sys.modules` → the mission import graph. Cross-
  check against our `_SDKFinder` shim resolution order (project-root shadows vs
  `sdk/Build/scripts/`) — anything the real engine imports that we don't stub
  could be a headless-gap.
- **Q14-4 `sys.maxint`** confirms the int width behind q13's hex formatting and any
  bitmask constant math. If `maxint == 2147483647`, 32-bit; the `ET_*` values
  (~0x0080_0000) sit comfortably inside it.

## Cleanup

Delete `game\q14_env.py`, `game\probe_harness.py` (unless a later probe run needs
it), and `game\BCProbe_q14_*.cfg`. Write-then-scrub keeps `Options.cfg` clean. No
game file is modified.

## Findings

(To be filled in when the probe runs.)