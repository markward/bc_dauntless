# Instrumented experiments

Per-question runbooks for instrumentation we want to carry out *inside the
running BC game* (stbc.exe). Each experiment is a self-contained markdown file
that a fresh Claude session can pick up, run on a Windows machine with BC
installed, and analyse without re-deriving the setup from scratch.

## Two instrumentation approaches

- **Approach 1 — `App.py` snippet + `SaveConfigFile`.** Append a
  `tools/appc_logger.py`-style snippet to `App.py`; it can only hook
  `GetGameTime` and dump downsampled rows to a `.cfg`. Blind, statistical, and
  the only write path that works from inside the snippet. Older experiments use
  this.
- **Approach 2 — the game's Python dev console.** Drive the *same embedded
  Python 1.5* interactively from BC's dev console: live read-back of return
  values and **deterministic, scripted** state setup (call `AddDamage`/setters
  directly instead of flying-and-firing). Far cleaner for anything that can be
  driven by direct API calls. The Python-1.5 syntax constraints below still
  apply. **Operational details:** [console-probe-workflow.md](console-probe-workflow.md).
  First runbook: [2026-06-29-weapon-exchange-console-probe.md](2026-06-29-weapon-exchange-console-probe.md).

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
| [2026-07-12-torpedo-event-probe.md](2026-07-12-torpedo-event-probe.md) | PENDING | Who posts `ET_TORPEDO_FIRED`, and what are its Source/Destination? Blocks the `TorpedoTube` reimplementation — Episode 7 **destroys** the event's Destination subsystem, so we cannot guess. Also captures the numeric IDs of the five torpedo/weapon events. **Approach 2**, but an *event-driven* probe: `import`ed and armed, not `execfile`'d. |
| [2026-06-29-weapon-exchange-console-probe.md](2026-06-29-weapon-exchange-console-probe.md) | PENDING | **#1 question** — what curve converts range→damage, and how does a hit split across shield/subsystem/hull? (+ charge unit). Uses **approach 2** (dev console); subsumes the two combat experiments below. |
| [2026-05-12-system-scale-investigation.md](2026-05-12-system-scale-investigation.md) | PENDING | What unit/scale convention does BC's C++ engine use for ships vs planets vs suns? |
| [2026-05-26-radar-range-calibration.md](2026-05-26-radar-range-calibration.md) | PENDING | What world-space radius does the bottom-left radar disc represent in stock BC? |
| [2026-05-15-damage-routing-investigation.md](2026-05-15-damage-routing-investigation.md) | PENDING | (subsumed by the console probe above) Damage falloff + shield/subsystem/hull routing via App.py-snippet fly-and-fire. |
| [2026-05-15-phaser-charge-dynamics.md](2026-05-15-phaser-charge-dynamics.md) | PENDING | (subsumed by the console probe above) Phaser discharge/recharge rates, units, thresholds via App.py-snippet sampling. |

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
