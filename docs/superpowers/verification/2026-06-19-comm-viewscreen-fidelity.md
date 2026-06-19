# Manual Verification: Comm-viewscreen Static + Brightness Fidelity

**Date:** 2026-06-19
**Branch:** feat/comm-viewscreen-static
**Operator:** Mark (no synthetic desktop input)

---

## What this verifies

- Analog static/"snow" overlay scales correctly with the SDK's `fMinStatic` / `fMaxStatic`
  arguments passed to `MissionLib.ViewscreenOn(...)`.
- A ~0.3 s brightness fade-in plays on every feed transition (ViewOn / ViewOff).
- Dev-gated log lines corroborate the visual.

---

## Launch

```
./build/dauntless --developer
```

The `--developer` flag enables the change-gated viewscreen log.

---

## Scenario A — E1M2 Static Test Bed

**Mission:** Maelstrom Episode 1, Mission 2 ("The Rescue")

### A1 — Heavy static (fmin=0.8, fmax=1.0)

**SDK call site:** `E1M2.py:3998`
```python
App.TGScriptAction_Create("MissionLib", "ViewscreenOn", "MiscEng", "Soams", 0.8, 1, 1)
```

**How to reach it:** Play through E1M2 until the distress signal from Haven is
intercepted (late in the mission). Soams appears on the viewscreen with heavy snow.

**Expected visual:** Dense animated snow covers the entire comm frame. The noise
flickers between frames at full saturation — the feed under the snow is
barely / not visible.

**Expected dev log line:**
```
[viewscreen] feed=comm:<set_id> static=on min=0.80 max=1.00 intensity=<value>
```
`intensity` will vary randomly in [0.80, 1.00] between frames; the log only
emits when the state key changes (feed or static-on flag), so you will see
one line on hail open and another if static turns off on hang-up.

### A2 — Clean hails (fmin=0, fmax=0) — no snow

**SDK call sites (representative):**
- `E1M2.py:2528` — `ViewscreenOn("MiscEng", "Soams", 0, 0, 0)`
- `E1M2.py:3562` — `ViewscreenOn("MiscEng", "Soams", 0, 0, 0)`
- `E1M2.py:3767` — `ViewscreenOn("MiscEng", "Soams", 0, 0, 0)`

**Expected visual:** Soams visible on the viewscreen with no snow overlay. The
static pass is fully transparent.

**Expected dev log line:**
```
[viewscreen] feed=comm:<set_id> static=off
```

---

## Scenario B — E1M1 Clean Baseline + Fade-in

**Mission:** Maelstrom Episode 1, Mission 1 ("Where No Man Has Gone Before")

### B1 — Liu hail (fmin=0, fmax=0) — no snow

**SDK call site:** `E1M1.py:1846`
```python
App.TGScriptAction_Create("MissionLib", "ViewscreenOn", "StarbaseSet", "Liu")
```
(default `fMinStatic=0, fMaxStatic=0`)

**Expected visual:** Liu on the viewscreen, zero snow.

**Expected dev log line on hail open:**
```
[viewscreen] feed=comm:<set_id> static=off
```

### B2 — Brightness fade-in (~0.3 s)

On every ViewOn / ViewOff transition the feed signature changes, triggering
`ViewscreenBrightnessRamp`. The ramp starts at 0 and reaches 1.0 in
`DURATION_S = 0.3` seconds (linear).

**How to observe:**
1. Wait until the bridge viewscreen is dark (feed=off).
2. Trigger any hail. Watch the first ~0.3 s: the frame should brighten from
   black to full rather than snap-cutting.
3. On hang-up (ViewscreenOff), the feed reverts to "forward"; the ramp
   restarts, producing the same fade-in on the forward-view feed.

**Expected dev log lines at transition:**
```
[viewscreen] feed=off static=off         # screen dark before hail
[viewscreen] feed=comm:<set_id> static=off   # hail opens → ramp starts
[viewscreen] feed=forward static=off     # hang-up → ramp restarts on forward view
```

**Compare against BC reference footage:** In the original game the viewscreen
briefly brightens from dark on each incoming hail (the "tune-in" effect from
analogue TV). The fade duration in BC is approximately 0.3 s, matching our
`DURATION_S` constant. The static is visually similar to analogue snow:
random-textured, animated frame-to-frame.

---

## Dev log reference

All log lines are emitted only when:
1. `--developer` is passed at launch, AND
2. the state key `(signature, static_on, round(intensity, 2))` changed since
   the last emission.

This means you will see at most one line per state transition, not per frame.

| Line pattern | Meaning |
|---|---|
| `[viewscreen] feed=off static=off` | Viewscreen is dark (IsOn=0) |
| `[viewscreen] feed=forward static=off` | Forward camera, no static |
| `[viewscreen] feed=comm:<id> static=off` | Comm scene, clean signal |
| `[viewscreen] feed=comm:<id> static=on min=M max=X intensity=I` | Comm scene with snow |

---

## Known pre-existing issues (not this work)

- **Lego head:** Character heads render as untextured placeholders. This is a
  separate open renderer bug tracked in
  `memory/project_bc_character_rigid_skinning.md`. It does not affect the
  static overlay or brightness fade verification.

---

## Test results (automated)

| Suite | Result |
|---|---|
| Python: `scripts/run_tests.sh` | 3399 passed, 3 skipped, peak 429 MB |
| Native: `Viewscreen*` tests | PASSED (both in batch and individually) |
| Native: `FrameTest.*` / `SkinnedRenderTest.*` | Pre-existing GL-readback batch flakiness — pass individually |
