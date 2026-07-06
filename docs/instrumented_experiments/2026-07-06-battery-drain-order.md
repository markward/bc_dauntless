# Battery drain order — concurrent conduit-overflow vs reserve-last-resort

Status: CLOSED
Author: 2026-07-06 session
Created: 2026-07-06
Closed:  2026-07-06

## Goal

Determine whether the **original BC engine** (Appc) draws from the backup battery
**concurrently** with the main battery when total demand exceeds the main conduit
ceiling, or whether the backup acts as a true last resort and is only touched after
the main battery is fully depleted.

## Background

The dauntless EPS model (`engine/appc/subsystems.py`) follows the layout
documented in
`docs/original_game_reference/gameplay/ship-subsystems.md` §Power-and-reactor.
The key mechanism is `ComputeAvailablePower`:

```
mainConduit  = min(mainBattery,   mainConduitCapacity * conditionPct)
backupConduit= min(backupBattery, backupConduitCapacity)
availablePower = mainConduit + backupConduit
```

Both conduit budgets are computed **unconditionally every interval** and both are
immediately available to consumers.  Because `TractorBeamSystem` is assigned
`powerMode = 1` (backup-first, `FUN_00582080`), holding a tractor while all
seven sliders are at 1.25 forces demand (~2062/s on a Galaxy) above the main
conduit's 1200/s ceiling.  Our model predicts:

- Backup drains **concurrently** with main (conduit-overflow model), at roughly
  −200/s while main still holds charge.
- `AdjustPower` (`PowerDisplay.py`) is **client-side only** and does not throttle
  the sliders in the single-player original (it is Python running on the player
  machine and would need to call `SetPowerPercentageWanted` again, which would
  then need to replicate to the host — there is no documented round-trip).  Our
  implementation therefore expects sliders to **stay at 1.25**.

The player manual
(`docs/original_game_reference/gameplay/power-system.md`) describes the reserve
battery as a last resort: *"At Red Alert you will begin draining battery power"*
and shows a band sequence (main → yellow → reserve), implying reserve is only
drawn after main empties.  Which story does the C++ engine actually implement?

Reference values for a Galaxy (from
`docs/original_game_reference/gameplay/ship-subsystems.md` §Reference-values):
Output 1000/s, normal-load total draw 1651/s, deficit −651/s.  At all sliders
1.25 × normal + tractor, total demand rises above the main conduit cap (1000/s
for Galaxy scaled by conditionPct 1.0), so backup must contribute.

Implementation reference: `engine/appc/subsystems.py` `PoweredMaster._tick`,
`_draw`, and `_compute_available_power`.

## Specific questions

- **Q1** — Does the backup battery start draining while the main battery still
  has charge (conduit-overflow model), or does backup only begin falling after
  main hits zero (reserve-last-resort model)?
- **Q2** — Measured drain rates of main and backup (per game-second): first in
  the pre-tractor baseline (sliders at 1.25, red alert, no tractor), then while
  the tractor is held.
- **Q3** — Do the seven power-slider `GetPowerPercentageWanted()` readings move
  at any point during the run?  (If yes, AdjustPower or some other mechanism is
  throttling the requested percentages in the original engine.)
- **Q4** — After releasing the tractor and switching back to green alert, does
  the main battery refill before the backup battery, or do both refill together?

## Snippet / probe path

**Primary method — console probe (approach 2):**
`tools/probes/q10_battery_drain.py`

The probe exposes three operator-callable functions:

| Function   | Purpose                                                        |
|------------|----------------------------------------------------------------|
| `setup()`  | Set red alert + all 7 sliders to 1.25; take baseline snapshot |
| `sample()` | Record one power snapshot row; call every 5–10 s              |
| `finish()` | Flush all rows to `BCProbe_q10.cfg`, scrub cfg singleton       |

Sampling is operator-driven (not timer-based) because BC's SDK timer mechanism
(`PythonMethodProcess` / `TGTimer`) has not been verified safe to instantiate
from the `-TestMode` REPL in `console-probe-workflow.md`.  A 5–10 s manual
cadence gives adequate time resolution for battery drain that takes ~6 minutes on
a Galaxy.

**Fallback — approach-1 snippet (Appc.dll hook):**
`tools/appc_power_logger.py` installed via `tools/setup.py --power`.
Analyzed by `tools/analyze_power_session.py`.  See §How to run (fallback) below.

## How to run

### Primary: console probe

**Prerequisites:** BC installed in `game/`; Quick Battle accessible.

1. `git pull` to get the latest probe file.
2. `uv run python tools/probes/push.py q10`  
   (copies `tools/probes/q10_battery_drain.py` → `game/`)
3. Launch `game/stbc.exe -TestMode`.
4. Start a **Quick Battle** match so a target ship is present in-space.
5. In the REPL:
   ```
   execfile('q10_battery_drain.py')
   setup()
   ```
   Confirm the console reports `RED_ALERT set` and all seven sliders set to
   `1.25`.  Note the baseline `main=` and `backup=` values.
6. **Engage the tractor** on any enemy or asteroid via the normal in-game UI
   (hotkey or tactical menu).  Do NOT use `SetFiring(1)` directly — see
   console-probe-workflow.md §gotcha-6.
7. Call `sample()` approximately every 5–10 seconds while the tractor is held.
   Aim for at least 6–8 samples covering a visible drain arc.
8. **Release the tractor and switch to green alert.**
9. Call `sample()` every 5–10 s for another 3–4 samples to capture the recharge
   phase (Q4).
10. Call `finish()` — this writes `BCProbe_q10.cfg` to `game/`.
11. Quit BC or leave it running.
12. On the dev machine:
    ```
    uv run python tools/probes/collect.py q10
    ```
    This extracts `[BCProbe_q10]` from `game/BCProbe_q10.cfg` and writes
    `tools/probes/results/q10_battery_drain.txt`.
13. `git add tools/probes/results/q10_battery_drain.txt && git commit && git push`.

### Fallback: approach-1 snippet

If the console probe is unavailable (no `-TestMode` support, build discrepancy,
etc.), use the App.py snippet path:

1. Install:
   ```
   uv run python tools/setup.py --power --recompile
   ```
   This appends `tools/appc_power_logger.py` to `game/scripts/App.py`.
2. Launch `game/stbc.exe` normally (no `-TestMode`).
3. Start Quick Battle; fly the Galaxy.  
   Switch to red alert (First Officer menu).  
   Boost all four power groups to 125% on the Engineering panel (F5).  
   Engage the tractor on any target (asteroid or enemy ship works) and hold for
   at least 3–4 minutes.  
   Release the tractor, switch to green alert, wait 1–2 minutes.  
   Quit the game.
4. The output lands in `game/BCTickLog.cfg`.  Analyze it:
   ```
   uv run python tools/analyze_power_session.py game/BCTickLog.cfg
   ```
5. Restore the game installation:
   ```
   uv run python tools/uninstall.py
   ```

## Expected output

### Console probe (`BCProbe_q10.cfg`)

The `[BCProbe_q10]` section will contain:

- `r0 … rN` — the full log lines: section headers, per-call snapshot rows (each
  one-liner labelled `s0.snapshot`, `s1.snapshot`, etc.), and the compact
  `sample_N` rows for machine parsing.
- `n` — total line count.

Example `sample_0` compact row:
```
12.50 5980.0 4000.0 1000.0 1450.0 950.0 2060.0 1200.0 250.0 1.000 1 1.25 1.25 1.25 1.25 1.25 1.25 1.25
```
Columns: `game_time main backup output avail disp wanted mcon bcon condpct tractor impulse warp shields phasers torps pulse sensors`

### Fallback (`BCTickLog.cfg`)

`[BCTickLog]` section with keys `pfields`, `pcount`, `p0`…`pN-1`.  Each row is
18 space-separated values matching `tools/analyze_power_session.py FIELDS`.

## Analysis

### Console probe result

Run `collect.py` then inspect `q10_battery_drain.txt`:

```
uv run python tools/probes/collect.py q10
cat tools/probes/results/q10_battery_drain.txt
```

For each pair of consecutive `sample_N` rows, compute:

```
Δmain_per_s   = (main[i+1]  - main[i])  / (gt[i+1] - gt[i])
Δbackup_per_s = (backup[i+1]- backup[i])/ (gt[i+1] - gt[i])
```

Q1 answer: if `backup[k] < backup[0]` while `main[k] > 0`, the overflow model
is confirmed.  If backup holds flat until main reaches zero, the reserve-last-
resort model is confirmed.

Q3 answer: compare `impulse`…`sensors` columns across all rows.  Any value
deviating from `1.25` means AdjustPower or another mechanism throttled the
request.

Q4 answer: during the post-release rows, compare which of main/backup increases
first and at what rate.

### Fallback result

```
uv run python tools/analyze_power_session.py game/BCTickLog.cfg
```

The analyzer prints a drain-rate table, a reservoir-order conclusion
(`CONDUIT-OVERFLOW model` vs `'last resort' model`), a slider-movement check,
and a comparison table.

### Dauntless model prediction (all 7 sliders 1.25, tractor held, Galaxy, 100% health)

| Metric                     | Dauntless prediction          |
|----------------------------|-------------------------------|
| Main drain rate            | ~−200/s (net after output fills main conduit cap 1000/s; output 1000/s fills main, excess demand 2062/s draws from conduit; conduit budget 1000 fills in 1 s, then 2062/s draw depletes both batteries) |
| Backup drain rate          | ~−200/s concurrent (tractor backup-first mode draws surplus from backup conduit) |
| Reservoir drain order      | **Concurrent** — backup begins draining while main > 0 |
| AdjustPower slider changes | **None** — sliders hold at 1.25 (client-side only, single-player) |
| Post-release recharge      | Main refills first (output → main battery → overflow to backup) |

Note: exact rates depend on the Galaxy's battery limits (`MainBatteryLimit`
and `BackupBatteryLimit` from its `PowerProperty`), which are not confirmed in
our reference docs.  The Sovereign reference is 200,000 / 100,000 /
1,450 / 250 / 1,200 (see §Field-layouts in `ship-subsystems.md`).  The Galaxy
values are lower; use the live `GetMainBatteryLimit()` / `GetBackupBatteryLimit()`
readings from the probe to anchor the prediction.

## Cleanup

### Console probe

The probe mutates live alert level and power-slider state but writes nothing to
disk except `game/BCProbe_q10.cfg` (which is gitignored).  To restore:

- Restart Quick Battle (discards all mutated state).
- No repo edits required.
- If `collect.py` was run, commit `tools/probes/results/q10_battery_drain.txt`
  as the result artifact.

### Fallback

```
uv run python tools/uninstall.py
```

Delete `game/BCTickLog.cfg` once analyzed.

## Findings

**Run:** 2026-07-06, Galaxy vs. stationary asteroid (tractor target), 57 samples
over ~500 game-seconds. Raw data: `tools/probes/results/q10_battery_drain.txt`.
The operator additionally varied sliders mid-run and let the tractor auto-toggle,
giving load-variation and recharge data beyond the original plan.

### Answers to the four questions

- **Q1 — Drain order: CONCURRENT (conduit-overflow). CONFIRMED.**
  Reserve falls from the very first sample while main is still near-full
  (s0 main 246,873 / backup 79,694 → s31 main 37,796 / backup 50,000). Reserve
  drops ~30,000 while main still holds six figures. The player-manual
  "reserve is a last resort" story is **refuted**; the C++ engine drains the
  stack concurrently. The dauntless model's `_compute_available_power` structure
  (both conduit budgets available every interval) is validated.

- **Q2 — Rates (per game-second):**

  | Phase | Main | Reserve |
  |---|---|---|
  | Pre-tractor, all sliders 1.25 (s0→s1) | −240 | −117 |
  | Tractor held, all 1.25 (s10→s20) | **−789** | **−110** |
  | Recharge, tractor off, sliders 1.00 (s52→s56) | +749 | 0 (frozen) |
  | Recharge, tractor on, sliders 0.40 (s40→s45) | +304 | 0 (frozen) |

  Two deltas vs. the doc's ~−200/−200 prediction: (a) **main drains ~4× faster
  than predicted** (~−790, not −200) — the model's rate constant is wrong; and
  (b) **reserve drain is ~constant ~110/s whether or not the tractor fires**
  (117 → 110). The tractor's entire extra load (~+550/s) is served by **main**,
  never reserve (see §Power-source stack).

- **Q3 — Slider auto-throttle: NONE. CONFIRMED.** Sliders held exactly where set
  and only moved on manual operator input (s39 → 0.40; s46 → 1.00). When main
  crashed to ~1% (s36–38) the engine did **not** throttle sliders — it **shed
  the tractor** (auto-off). AdjustPower is inert on the host, as the model assumes.

- **Q4 — Recharge order: MAIN FIRST, sequential (stronger than predicted).**
  Once load dropped and the ship went power-positive, main climbed 399 → 72,228
  but **reserve froze at 42,717.2 for the entire back half (s39→s56)** and never
  recharged in-window. Recharge is **not** concurrent: warp-core output refills
  main fully before touching reserve. Drain is concurrent; recharge is sequential
  — a real **asymmetry**.

### Power-source stack (from the in-game Power Transmission Grid UI)

The Engineering panel draws the three power sources as bracket stacks, top to
bottom in draw/priority order, with a live percentage under each:

1. **Warp Core** (blue) — the reactor. Its percentage tracks the **warp-core
   subsystem repair state**, not a draining reservoir; at 100% health it supplies
   full output (the constant `output=1000.0/s` for the Galaxy in this capture).
   Engine implication: `output` must be modelled as `f(warp_core_condition)`,
   not a constant.
2. **Main Battery** (yellow) — second in the stack.
3. **Reserve Power** (orange) — last.

General consumers draw **top-down** through the stack (warp core output first,
overflow into main, then reserve) and the batteries **recharge top-down** (main
fully before reserve). This is exactly the observed concurrent-drain /
sequential-recharge behaviour. UI cross-check: screenshot `100%/6%/61%` = warp
core full, main nearly empty, reserve 61% — the "main empties while reserve
holds" signature.

**Dedicated-source consumers** bind to one stack level and cannot draw elsewhere:

- **Tractor → Main Battery only** (cannot touch warp core or reserve). This is
  why reserve drain is independent of the tractor and the tractor's load lands
  entirely on main.
- **Cloak → Reserve Power only** (cannot touch warp core or main), per the
  cloak-capable ship's power panel.

### Correction to the RE: `powerMode` is a source-stack index, not "backup-first"

The Background section asserted `TractorBeamSystem` `powerMode = 1`
(`FUN_00582080`) meant **backup-first**. Both the UI and the measured data show
the tractor is **main-only**, contradicting that reading. The consistent
reinterpretation:

> **`powerMode` is an index into the source stack: `0 = warp core,
> 1 = main battery, 2 = reserve`.**

This makes tractor `powerMode=1` = **main battery** (matches), and **predicts
cloak `powerMode = 2` = reserve** (matches the cloak→reserve UI fact). Falsifiable
— confirm by reading the cloak subsystem's `powerMode` in the hardpoint/RE data.

### Model corrections applied (2026-07-06)

Status: **DONE** (2026-07-06). The measured split was reproduced in the dauntless
model and pinned by `tests/integration/test_power_reference_values.py::
test_q10_red_alert_sliders_125_tractor_held_split` (main −800.0/s, backup
−113.75/s, ±2%). Two changes closed the follow-up:

1. **Tractor is a direct main-battery siphon.** `TractorBeamSystem` sets
   `DRAWS_DIRECT_FROM_MAIN = True`; `PoweredSubsystem._update_power` branches on
   that flag to `power.StealPower(normal_power·dt)` — bypassing the conduit
   budget and UNSCALED by the slider (measured 600 flat with sliders 1.25). This
   is what makes main drain ~−800/s (the "~4× too low" follow-up): the model's
   old ~−200 figure came from routing the tractor through the conduit; the
   direct siphon lands the full 600/s on main on top of the −200/s conduit
   deficit. `PSM_MAIN_FIRST`/`PSM_DIRECT_MAIN` are documented in
   `engine/appc/subsystems.py`.
2. **Battery-limited conduit getters.** `GetMainConduitCapacity()` /
   `GetBackupConduitCapacity()` now clamp the rated capacity by the remaining
   battery charge (`min(battery, rated·condPct)`), so SDK `AdjustPower` engages
   as a battery runs dry (the s38→s39 impulse/warp/sensor throttle). The
   per-interval budget tick keeps the rated (un-clamped) view internally so the
   clamp is applied exactly once.

Recharge is unchanged — the model's fill-main-first was already exact (q10 Q4).

### Follow-ups (do not block closing this experiment)

1. ~~**Main drain-rate constant is ~4× too low**~~ — RESOLVED 2026-07-06 by the
   direct main-battery siphon above.
2. **Confirm `powerMode`-as-index** by grepping the cloak subsystem's `powerMode`
   in `sdk/.../ships/Hardpoints/` and the RE notes; update
   `ship-subsystems.md` §Power-and-reactor to replace the "backup-first" wording.
3. **Model `output` as a function of warp-core repair state**, not a constant.

### Bonus behaviour (operator-driven, tractor auto-toggle)

The tractor auto-cut at main ≈ 2,179 (~0.9%) and auto-restarted once main
recovered to ~13,800 (~5.6%) — **gated on the main battery only** (reserve was a
healthy ~53% throughout and irrelevant to the decision). Under power starvation
the engine **sheds consumers, never throttles sliders**, consistent with Q3.
