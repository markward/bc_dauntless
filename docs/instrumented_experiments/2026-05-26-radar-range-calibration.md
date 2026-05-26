# Radar range calibration

Status: **PENDING**
Author: 2026-05-26 session
Created: 2026-05-26
Closed:

## Goal

Measure the world-space radius of the bottom-left radar disc as it appears in **stock BC** (stbc.exe + unmodified `Appc.dll`), so the Dauntless `SensorsPanel` can be calibrated to match. The dauntless default lives at [`engine/ui/sensors_panel.py`](../../engine/ui/sensors_panel.py) (`DEFAULT_RANGE_M`) and [`engine/appc/radar.py`](../../engine/appc/radar.py) (`_RadarDisplay._range_m`) and is currently **3000 m by feel**.

## Background

The original radar range is hardcoded inside `Appc.dll`. The SDK Python surface ([`sdk/Build/scripts/App.py:8513-8533`](../../sdk/Build/scripts/App.py)) exposes only `SetColorBasedOnFlags`, `ResizeUI`, `RepositionUI` on `RadarDisplay` — **no `SetRange` method exists**. Static analysis can't recover the value.

Observational bounds from screenshots reviewed in conversation on 2026-05-26:
- A comm array at **38 km** distance was **off-disc** → original range < 38 km.
- A hostile ship within "a few km" of the player was **on-disc** near the centre → original range > approximately 3-5 km.

So the original disc radius is somewhere in `[5, 38]` km, with the lower bound being soft.

Related context:
- The Dauntless redesign spec at [`docs/ui_designs/05-sensors-radar.md`](../ui_designs/05-sensors-radar.md) shows an example `pRadar.SetRange(8000)` — that was an *aspirational* API the redesign would add, not a measurement.
- The radar implementation plan [`docs/superpowers/plans/2026-05-26-radar-sensors-panel.md`](../superpowers/plans/2026-05-26-radar-sensors-panel.md) defers this calibration to a follow-up (this doc).

## Specific questions

Each must end up with a numeric answer in **Findings**.

- **Q-R1** What world-space radius (in metres) does the original disc's outer ring correspond to? I.e. what distance does a contact need to be at, along the player's forward axis, to sit *exactly* on the outer ring?
- **Q-R2** Is the disc range fixed, or does it scale with ship class / sensor subsystem health / `g_kRadarRange` global / mission flag?
- **Q-R3** Are the two inner range rings at fixed fractions of the outer ring (the redesign assumes 0.65 and 0.35 — `docs/ui_designs/05-sensors-radar.html:32-34`)? Or are they at specific distances?
- **Q-R4** Does the disc range respond to a UI control we haven't found? (The LCARS icon atlas at [`sdk/Build/scripts/Icons/LCARS_1024.py:236-243`](../../sdk/Build/scripts/Icons/LCARS_1024.py) defines zoom-in / zoom-out icon slots 90-102 that appear unused by stock BC — but might be bound by C++.)

## Snippet

Two viable approaches:

### Option A: Visual calibration (no code, fastest)

Use the in-game UI to bracket the value:
1. Load a save with one isolated hostile ship at a known distance (the targetable HUD shows distance in km).
2. Manoeuvre so the hostile is near the outer ring's far edge.
3. Read the HUD distance. That's the disc radius (within ~10% — the eye is the measurement instrument).
4. Repeat at multiple distances to confirm the disc range is fixed (Q-R2).
5. Confirm Q-R3 by reading distances of contacts at the middle and inner rings.

No snippet needed; no instrumentation.

### Option B: Instrumented capture (definitive)

Snippet: `tools/radar_range_logger.py` (to be created).

Hooks `UtopiaModule.GetGameTime` and, every 2 seconds of wall time, walks `g_kSetManager.GetRenderedSet()` for ships, computes `dist = ||ship.GetWorldLocation() - player.GetWorldLocation()||`, and for each writes:

```
[BCRadarLog]
sample_N_ship_name      = "USS Galaxy"
sample_N_dist_m         = 4321.5
sample_N_on_radar       = 1 | 0     ; from inspecting the RadarBlip's parent BlipPane child list
```

Determining `on_radar` requires resolving the actual `RadarBlip` instances — see [`sdk/Build/scripts/Tactical/Interface/RadarScope.py:42-47`](../../sdk/Build/scripts/Tactical/Interface/RadarScope.py) for how the blip pane is constructed. The C++ side adds/removes children per tick; the snippet would walk the blip pane and match each blip's `GetShipID()` to the rendered-set ship.

The smallest distance where `on_radar == 0` and the largest where `on_radar == 1` bracket Q-R1.

## How to run

### Option A (visual)

1. Launch stbc.exe (no instrumentation; stock game).
2. Load a save with a ship at a known starting distance — Maelstrom M2 or M5 work well as they start with isolated hostile encounters.
3. Pause, screenshot, measure.

### Option B (instrumented)

```powershell
# Stop game if running, restore from any prior instrumentation
uv run python tools/uninstall.py

# Edit tools/setup.py to point at radar_range_logger.py instead of appc_logger.py
# (or pass a --snippet flag if/when that's added)

uv run python tools/setup.py --recompile
# launch the game, fly around a mission with several ships
uv run python tools/setup.py --capture
uv run python tools/uninstall.py

# Pull the log
cp game/BCRadarLog.cfg docs/instrumented_experiments/captures/
```

## Expected output

Option A: a screenshot per measurement with the HUD-reported distance visible plus the contact's position on the disc. Annotate with the measured ring fraction.

Option B: `BCRadarLog.cfg` with sections like:

```
[BCRadarLog]
n_samples = 1234
sample_1_ship_name = "Renegade1"
sample_1_dist_m = 2150.2
sample_1_on_radar = 1
sample_2_ship_name = "Renegade1"
sample_2_dist_m = 2200.1
sample_2_on_radar = 1
...
sample_N_ship_name = "Renegade1"
sample_N_dist_m = 8125.7
sample_N_on_radar = 0
```

## Analysis

Option A: read distances directly from screenshots.

Option B: a small Python script that walks `BCRadarLog.cfg` and computes, per ship, the largest `dist_m` with `on_radar == 1` and the smallest with `on_radar == 0`. The disc radius is the midpoint (with bounds error of half the gap). Across multiple ships, the variance answers Q-R2 (fixed vs. dynamic).

## Cleanup

Option A: nothing — no game files touched.

Option B: `uv run python tools/uninstall.py` restores `game/scripts/App.py` and `App.pyc` to the originals from `App.pyc.bak`. Standard cleanup.

## Findings

(unfilled — experiment is PENDING)

## Action on close

When this experiment moves to DONE:
- Update `DEFAULT_RANGE_M` in [`engine/ui/sensors_panel.py`](../../engine/ui/sensors_panel.py).
- Update the initial-value in `_RadarDisplay.__init__` in [`engine/appc/radar.py`](../../engine/appc/radar.py).
- Strip the "chosen by feel" comments in both files; reference this experiment's findings instead.
- If the two inner rings turn out to be at non-standard fractions, update `.sensors__ring-mid` / `.sensors__ring-inner` `width`/`height` percentages in [`native/assets/ui-cef/css/sensors.css`](../../native/assets/ui-cef/css/sensors.css).
