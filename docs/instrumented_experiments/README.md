# Instrumented experiments

Per-question runbooks for instrumentation we want to carry out *inside the
running BC game* (stbc.exe with our `tools/appc_logger.py`-style snippet
appended to `App.py`). Each experiment is a self-contained markdown file
that a fresh Claude session can pick up, run on a Windows machine with BC
installed, and analyse without re-deriving the setup from scratch.

## Convention

Each experiment file follows this skeleton:

```
# <title>

Status: PENDING | IN-PROGRESS | DONE
Author: <name or session>
Created: <YYYY-MM-DD>
Closed:  <YYYY-MM-DD> (set when Status moves to DONE)

## Goal
(one paragraph — what question are we trying to answer?)

## Background
(why this experiment exists; pointers to docs/gap_analysis.md OQs etc.)

## Specific questions
(Q-x bullets — each one needs a concrete answer from the captured data)

## Snippet
(path to the Python 1.5 snippet that gets appended to App.py)

## How to run
(exact commands, including any swap-in of the snippet path in tools/setup.py)

## Expected output
(what BC<Name>Log.cfg should look like, sections and keys)

## Analysis
(commands or scripts to interpret the cfg, with worked examples if possible)

## Cleanup
(every file or in-place edit that needs to be reverted; uninstall steps)

## Findings
(filled in once the experiment runs)
```

Status meanings:

- **PENDING** — designed and instrumented, never run. A future session can
  search this directory for `Status: PENDING` to find runnable experiments.
- **IN-PROGRESS** — captured at least one cfg, analysis incomplete.
- **DONE** — questions answered. Findings section populated. Cleanup
  applied so the workspace is back to a known good state.

## Index

| File | Status | Topic |
|------|--------|-------|
| [2026-05-12-system-scale-investigation.md](2026-05-12-system-scale-investigation.md) | PENDING | What unit/scale convention does BC's C++ engine use for ships vs planets vs suns? |

## Constraints inherited from `CLAUDE.md`

- BC embeds Python 1.5 (magic `0x4E99`); snippets must avoid 1.6+ syntax
  (`import X as Y`, f-strings, `True`/`False`).
- The only confirmed working write path from inside the game is
  `g_kConfigMapping.SaveConfigFile("<name>.cfg")`, which writes to the
  game's working directory (`game/`).
- `os` is not importable; treat every `import` as potentially absent and
  guard with `try/except ImportError`.
- `tools/setup.py` is the canonical installer; `tools/uninstall.py` is the
  canonical restorer. Most experiments will only differ in which snippet
  `setup.py` is told to install.
