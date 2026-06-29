# Console probe workflow (instrumentation approach 2)

This is the operational doc for **instrumentation approach 2**: the BC dev
console driven by **`stbc.exe -TestMode`**. It is the document a remote Claude
session reads to understand how to *construct* a probe, and the document the
Windows operator reads to understand how to *run* one and report findings.

It pairs with [`README.md`](README.md), which gives the higher-level overview
of approach 1 vs approach 2.

## The discovery in one paragraph

Launching the BC binary with the `-TestMode` flag opens an embedded **Python
1.5 REPL** that `exec()`s input line by line, with `game/` on `sys.path`. That
means a remote machine can author a complete Python 1.5 probe file, commit it
to the repo, and the Windows operator only has to copy it into `game/` and
type a single `execfile('<probe>.py')` in the console. Results stream back via
`print` *and* via the engine's `SaveConfigFile` channel, so probes leave a
durable artifact even after the game closes.

## The round-trip

```
remote Claude                  git                 Windows operator (BC machine)
─────────────                  ───                 ─────────────────────────────
write tools/probes/q0X_*.py ─► commit ─► push ─► pull ─► cp to game/
                                                       │
                                                       ▼
                                                  stbc.exe -TestMode
                                                       │
                                                       ▼
                                                  execfile('q0X_*.py')
                                                       │
                                                       ▼
                                                  game/BCProbe_q0X.cfg
                                                       │
                                                       ▼
                                                  collect.py q0X
                                                       │
                                                       ▼
                                                  tools/probes/results/q0X_*.txt
                                                       │
read findings, update doc ◄─ pull ◄─ push ◄─ commit ◄──┘
```

Each side commits cleanly. The probe file, the result file, and the doc
findings are all in the repo; nothing important lives only in `game/`.

## Locations and naming

```
tools/probes/
  README.md                  short pointer back to this doc
  _template.py               canonical probe skeleton — copy this to start
  push.py                    convenience: copy a probe file into game/
  collect.py                 strip the [BCProbe_qXX] section out of game/*.cfg
  q01_<name>.py              actual probes; one per question or question cluster
  q02_<name>.py
  ...
  results/
    q01_<name>.txt           operator commits these
    q02_<name>.txt
```

- Probe ID is `q0N` (two-digit, zero-padded) and matches the question it
  answers in whichever runbook owns it.
- Result file mirrors the probe filename with `.txt` instead of `.py`.
- The cfg section a probe writes is **`[BCProbe_q0N]`** — `collect.py` keys
  off this name to extract only the relevant block.

## Constraints — the things that will bite you if you forget

These are *not* defaults from modern Python. They apply to **every line** of
every probe file because the host is genuinely Python 1.5.

| Constraint | Why | What to write instead |
|---|---|---|
| No `import X as Y` | Python 1.6+ syntax | `import X` then `Y = X` |
| No f-strings | Python 3.6+ syntax | `"%s %d" % (s, n)` |
| No `True` / `False` | added in Python 2.3 | `1` / `0` |
| `except SomeError, e:` (comma, not `as`) | Python 1.5 syntax | always use comma form |
| `print` is a *statement* | Python 2.x and below | `print x` not `print(x)` |
| No `os`, `socket`, `mmap`, `_winreg`, `msvcrt`, `select`, `tempfile`, `posix` | not compiled into the static build | use `__import__('name')` if unsure; guard with `try: ... except ImportError:` |
| All file I/O is blocked | C-level "Securelevel" intercept on `open()`, `nt.open()`, `nt.listdir()` | `App.g_kConfigMapping.SaveConfigFile` is the **only** write path |
| `file` removed from builtins | part of the securelevel sandbox | n/a — use cfg |

What **does** work: `sys`, `time`, `struct`, `App`, partial `nt` (no I/O),
`print`, `sys.stdout.write()` (in `-TestMode` only — crashes outside it),
`sys.stdout.getvalue()` (StringO buffer accumulator).

### Two SDK-specific gotchas the template already handles

1. **Singletons vs classes.** `App.UtopiaModule` is a *class*; calling
   `App.UtopiaModule.GetGameTime()` gives an unbound-method error. Use the
   `g_k*` singletons: `App.g_kUtopiaModule.GetGameTime()`,
   `App.g_kConfigMapping.SaveConfigFile(...)`, etc. The class name only
   appears in `class XYZ:` blocks in `sdk/Build/scripts/App.py`; the
   accompanying `g_kXYZ = XYZPtr(Appc.globals.g_kXYZ)` at the end of the
   file is the one you call methods on.

2. **String exceptions.** Python 1.5 can `raise "some message"` — the raised
   object is a string, which has no `__class__`, so
   `except Exception, e: e.__class__.__name__` blows up the error handler
   itself. Use the template's `_exc_name(e)` helper, which falls back to
   `type(e)` when `__class__` is missing.

3. **TGPoint3 construction.** `App.TGPoint3(x, y, z)` fails with
   `new_TGPoint3 requires exactly 0 arguments; 3 given`. The SWIG ctor is
   zero-arg; construct, then assign:
   ```python
   p = App.TGPoint3()
   p.x = 1.0; p.y = 2.0; p.z = 3.0
   ```
   Or reuse a live point via `obj.GetWorldLocation()` and mutate its
   `.x`/`.y`/`.z`.

## The two pollution traps and how to avoid them

`g_kConfigMapping` is a **singleton**. There is no `TGConfigMapping()`
constructor and no `RemoveKey` / `ClearSection` method. Anything you stuff
into the singleton with `SetStringValue(section, key, ...)` survives until the
process dies — and **gets written into `Options.cfg` whenever the game saves
its own config**, which corrupts the user's options file.

`LoadConfigFile` merges, it does not replace, so reloading `Options.cfg`
does **not** evict your keys.

**The fix: write-then-scrub in the same Python execution slice.** Because
BC's game loop is single-threaded from Python's perspective, nothing can
interleave between your `SaveConfigFile` and your scrub loop:

```python
# write
for i in range(n):
    cfg.SetStringValue(SECTION, "r%d" % i, lines[i])
cfg.SetIntValue(SECTION, "n", n)
cfg.SaveConfigFile("BCProbe_q0N.cfg")           # data on disk
# scrub (still single-threaded — game can't interleave)
for i in range(n):
    cfg.SetStringValue(SECTION, "r%d" % i, "")
cfg.SetIntValue(SECTION, "n", 0)
```

Verified empirically (see commit history on `feature/instrumentation_approach_2`):
`BCProbe_*.cfg` keeps the payload; `Options.cfg` only ever sees the empty
shells. The template enforces this — don't bypass it.

## Authoring a probe (remote-Claude perspective)

1. Copy `tools/probes/_template.py` to `tools/probes/q0N_<short_name>.py`.
2. Edit the metadata header: question reference, what the probe measures.
3. Replace the `# === PROBE BODY ===` section with your queries. Use `_record(label, value)` for everything you want in the result file. Do *not* call `print` or `cfg.SetStringValue` directly — `_record` does both.
4. Commit and push.

If a probe needs a setter (e.g. `sh.SetCurShields(0, 0.0)`) keep it inside a
`try: ... except Exception, e: _record("error", e)` so a missing target ship
doesn't blow up the whole probe before any data is captured.

## Running a probe (operator perspective)

1. `git pull` — get the latest probe file.
2. `uv run python tools/probes/push.py q0N` — copies `tools/probes/q0N_*.py` to `game/`. (Or copy by hand — `push.py` is just a convenience.)
3. Launch `game/stbc.exe -TestMode`.
4. **If the probe needs a live target**, start Quick Battle and acquire a target (Tab) *before* running it. The metadata header at the top of each probe says whether it needs combat state.
5. In the REPL: `execfile('q0N_<short_name>.py')` — wait for `done` message.
6. Quit BC (or leave it running; the data is already on disk).
7. `uv run python tools/probes/collect.py q0N` — extracts `[BCProbe_q0N]` out of `game/BCProbe_q0N.cfg` and writes it to `tools/probes/results/q0N_<short_name>.txt`.
8. `git add tools/probes/results/q0N_*.txt && git commit && git push`.

That is the entire operator loop. No editing, no transcription, no copying out
of screenshots. If something goes wrong (probe raises early, console crash,
console output reveals a quirk), commit a screenshot or the partial cfg into
`tools/probes/results/` and note it.

## Updating findings

Once a result file lands, the next remote Claude session:

1. Reads `tools/probes/results/q0N_*.txt`.
2. Fills in the corresponding entry in the experiment doc's `## Findings`
   section.
3. Updates the experiment doc's `Status: PENDING` line if the question is
   now answered.

Findings updates are doc edits, not code edits — they should be quick.

## Why this is the path forward

Approach 1 (App.py snippet + SaveConfigFile) is still valid for things that
genuinely need a running mission and a tick-by-tick stream — frame timing,
combat AI traces, hooks on hot loops. But for any question of the form *"what
does this C++ function actually do?"*, approach 2 turns it into a one-shot
deterministic call with read-back, which is strictly cheaper and strictly more
trustworthy. The remaining gap-analysis OQs that fit that shape should all
move to this workflow.
