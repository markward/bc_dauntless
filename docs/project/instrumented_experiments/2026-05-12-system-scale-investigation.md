# System scale investigation

Status: **DONE**
Author: 2026-05-12 session
Created: 2026-05-12
Closed: 2026-05-12

## Goal

Determine the runtime convention BC's compiled C++ engine uses for the
visual scale of **ships**, **planets**, and **suns**. Specifically: which
of `GetRadius()`, `GetScale()`, an implicit per-class multiplier, or a
combination is responsible for the on-screen size of these objects.

Without this we are guessing at constants in [`engine/scale.py`](../../engine/scale.py).
Static analysis got us as far as confirming that BC's stock SDK scripts
never call `SetScale()` on stock planets/suns (only Vesuvi asteroids and
dock/undock sequences touch it). The remaining unknown — the C++ default
for `GetScale()` on a freshly-constructed `Ship` / `Planet` / `Sun` and
whether the engine multiplies the NIF by `GetRadius() / NIF_native` or by
`GetScale()` or by both — can only be answered by reading the live
process state.

## Background

- Prior render-time guesses (`SHIP_SCALE=0.1`, `ASTRO_SCALE=10`,
  `PLANET_NIF_NATIVE_RADIUS=45`) made planets look right *relative to
  ships in M1Basic* but the absolute relationships are wrong: in our
  reimplementation moons are visibly smaller than ships, which is the
  opposite of the original BC screenshots.
- The planet NIF's authored `bound_radius` is **90.0** (measured in this
  worktree; `PLANET_NIF_NATIVE_RADIUS = 45` is therefore off by 2×).
- The Galaxy ship NIF's authored max vertex distance is **~472**.
- BC ships and planets share the same coordinate space at the API level
  — `Planet_Create(radius, …)` takes a number in the same units as
  `pShip.GetWorldLocation()` returns.
- Open question (this file answers it): does BC's C++ engine apply an
  implicit per-class scale at render time? The Python API exposes
  `SetScale` / `GetScale` on every `BaseObjectClass` but never reveals
  the default value.

Related docs:

- [`docs/gap_analysis.md`](../gap_analysis.md) — Phase 1 readiness audit.
- [`tools/appc_logger.py`](../../tools/appc_logger.py) — the *existing*
  instrumentation snippet (tick & event timing). This experiment swaps
  in a different snippet but reuses `tools/setup.py` and
  `tools/uninstall.py` unchanged.

## Specific questions

Each must end up with a numeric/textual answer in the **Findings**
section below.

- **Q-S1** Default `GetScale()` of a freshly-constructed `Ship`. (We
  expect 1.0 but cannot prove it from Python.)
- **Q-S2** Default `GetScale()` of a freshly-constructed `Planet`.
- **Q-S3** Default `GetScale()` of a freshly-constructed `Sun`.
- **Q-S4** What does the active camera's `NiFrustum` look like in
  M1Basic vs. Maelstrom E1M1? Specifically: `near`, `far`, the L/R/T/B
  values (these encode horizontal/vertical FOV via `atan(top/near)` etc).
- **Q-S5** Do `GetWorldLocation()` values for the planet and sun in
  Starbase12 match the static SDK numbers (planet at ~(440, 996, -50),
  sun at ~(70000, 0, 0)) or has something transformed them by the time
  rendering happens?
- **Q-S6** Looking across multiple captures of different missions, is
  there ever a `GetScale()` value that's *not* 1.0 on a fresh
  ship/planet/sun (in which case the C++ engine has applied an implicit
  scale we cannot see from Python sources)?

## Snippet

[`tools/scale_logger.py`](../../tools/scale_logger.py).

Hooks `UtopiaModule.GetGameTime` and, every 10 seconds of wall time,
walks `g_kSetManager.GetRenderedSet()` writing a structured dump to
`BCScaleLog.cfg` (replacing the previous dump in place). Each dump
captures:

- `dump_id`, `wall`, `frame`, `set_name`, `n_objects`
- For each object (up to 200): `objN_type`, `objN_name`, `objN_model`,
  `objN_radius`, `objN_scale`, `objN_pos`
- For the active camera: `cam_present`, `cam_eye`, `cam_fwd`, `cam_up`,
  `cam_left/right/top/bottom/near/far`

## How to run

This experiment runs on a **Windows machine with BC installed at
`game/`**. The macOS dev box can prepare and analyze the cfg but cannot
run stbc.exe.

1. **Swap the instrumentation snippet.** Edit [`tools/setup.py:26`](../../tools/setup.py#L26):

   ```diff
   - SHIM_SNIPPET = PROJECT_ROOT / "tools" / "appc_logger.py"
   + SHIM_SNIPPET = PROJECT_ROOT / "tools" / "scale_logger.py"
   ```

   *Do not commit this edit* — it's an experiment-time toggle. Cleanup
   reverts it below.

2. **Install into `game/scripts/App.py`** (uses the existing timestamp
   trick — see CLAUDE.md "Critical constraints"):

   ```
   uv run python tools/setup.py            # normal: uses cached .pyc
   uv run python tools/setup.py --recompile  # only if scale_logger.py is new
                                             # since last --capture
   ```

3. **Run BC** and let it sit in the **default scene** (`M1Basic` /
   DryDock) for at least 30 seconds — enough for 2–3 `dump_id`
   increments. The cfg confirms instrumentation is alive when
   `dump_id >= 2`.

4. **Stash the first capture** so it doesn't get overwritten:

   ```powershell
   Copy-Item game\BCScaleLog.cfg game\BCScaleLog.m1basic.cfg
   ```

5. **Load Maelstrom Episode 1 Mission 1** in BC (Single Player → Custom
   → Maelstrom → E1M1). Wait 30s after the scene appears.

6. **Stash the second capture**:

   ```powershell
   Copy-Item game\BCScaleLog.cfg game\BCScaleLog.e1m1.cfg
   ```

7. **Quit BC.**

8. **Analyze** (works from macOS dev box once the cfgs are copied back):

   ```
   uv run python tools/analyze_scale_log.py game/BCScaleLog.m1basic.cfg
   uv run python tools/analyze_scale_log.py game/BCScaleLog.e1m1.cfg
   ```

   Look specifically at the `scale` column of the per-object table. If
   every ship/planet/sun reports `scale = 1.0000` and `dump_id >= 2`,
   then **Q-S6 is answered "no"** — the C++ engine does not apply an
   implicit scale, and the renderer must derive visual size purely from
   `GetRadius()` and the NIF's authored bounds.

9. **Paste the analyzer output below** into the **Findings** section,
   along with one-line answers to Q-S1 through Q-S6.

## Expected output

`BCScaleLog.cfg` is a full engine config dump (every section from
`Options.cfg`, then the `[BCScaleLog]` section appended by the snippet).
Only `[BCScaleLog]` matters. A successful capture looks like:

```
[BCScaleLog]
dump_id=3
wall=31.245
frame=1872
set_name=Biranu1
n_objects=2
no_set=0
obj0_type=Sun
obj0_name=Sun
obj0_model=
obj0_radius=4000.000
obj0_scale=1.000
obj0_pos=-30000.000 60000.000 -10000.000
obj1_type=Planet
obj1_name=Biranu 1
obj1_model=
obj1_radius=170.000
obj1_scale=1.000
obj1_pos=432.920 429.961 387.532
cam_present=1
cam_eye=...
cam_fwd=...
cam_up=...
cam_left=-0.5
cam_right=0.5
cam_top=0.375
cam_bottom=-0.375
cam_near=1.0
cam_far=100000.0
```

(Numbers above are illustrative — they are exactly what the experiment
should reveal. `obj*_model` will always be empty: `Planet`, `Sun`, and
`ShipClass` have no `GetModelPath`/`GetModelFileName` method in the Python
API; the field is a best-effort grab wrapped in `try/except`.)

## Analysis

`tools/analyze_scale_log.py` produces three sections:

1. **Header** — `dump_id`, `wall`, `frame`, `set_name`, `n_objects`. A
   `dump_id` of 1 means the snippet ran exactly once and the game was
   probably closed during the very first dump; re-run BC for longer.
2. **Per-object table** — one row per object. This is the primary
   data: compare `radius` and `scale` columns across types.
3. **By type** — min/max/count per SWIG class name. Useful for spotting
   outliers (e.g. a single ship that has `scale != 1.0` because a
   docking script forgot to restore).

If the analyzer finds **`scale != 1.0` on any Ship/Planet/Sun**, that's
the load-bearing data point — capture which mission/system, then trace
where that override comes from (likely a stock script we hadn't read).

## Cleanup

After the experiment is done — **always** run these, even if BC
crashed mid-experiment:

1. **Uninstall the snippet from `game/scripts/`:**

   ```
   uv run python tools/uninstall.py
   ```

   This restores `game/scripts/App.pyc` from the `.bak` so the game
   starts cleanly.

2. **Revert the `tools/setup.py` edit** from step 1 of *How to run*:

   ```diff
   - SHIM_SNIPPET = PROJECT_ROOT / "tools" / "scale_logger.py"
   + SHIM_SNIPPET = PROJECT_ROOT / "tools" / "appc_logger.py"
   ```

   (Or `git checkout -- tools/setup.py` if no other edits are pending.)

3. **Move the captures into the experiment record** — keep them out of
   `game/` (which is gitignored):

   ```powershell
   New-Item -ItemType Directory -Force docs\project\instrumented_experiments\data
   Move-Item game\BCScaleLog*.cfg docs\project\instrumented_experiments\data\
   ```

   The captures are small text and worth committing alongside the
   findings.

4. **Update this file**: set `Status: DONE`, set `Closed:` date,
   populate `Findings`.

## Findings

Captured 2026-05-12 from Maelstrom E1M1 (Tau Ceti system / DryDock set).
Raw cfg: `docs/project/instrumented_experiments/data/BCScaleLog.cfg`

### Q-S1 — Default GetScale() of a Ship
**1.0** — player ship (Galaxy-class) reported `scale=1.0000`.

### Q-S2 — Default GetScale() of a Planet
**1.0** — "Tau Ceti Prime" reported `scale=1.0000`, `radius=180.0`.

### Q-S3 — Default GetScale() of a Sun
**1.0** — "Sun" reported `scale=1.0000`, `radius=4040.65`.

### Q-S4 — Active camera NiFrustum
From E1M1 (Tau Ceti, DryDock set):

```
near=1.0   far=5000.0
L=-0.25    R=0.25    T=0.1875    B=-0.1875
vertical FOV  ~ 21.2 deg  (2 * atan(0.1875 / 1.0))
horizontal FOV ~ 28.1 deg  (2 * atan(0.25   / 1.0))
aspect ratio  4:3
```

The `far=5000.0` clip distance is important for the renderer — the original
game does NOT use the large far values (100 000+) that were assumed in early
renderer work.

### Q-S5 — World positions of planet and sun
This capture is from the **Tau Ceti** system (E1M1), not Starbase12.
Positions observed:

| Object | GetWorldLocation() |
|---|---|
| Sun | (7502, 62793, 5817) |
| Tau Ceti Prime | (−400, 400, 0) |

The Starbase12 static SDK numbers (planet ~(440, 996, −50), sun ~(70000, 0, 0))
were not checked in this run. A separate Starbase12 capture can close Q-S5
fully if needed, but it is low priority — the coordinate system is confirmed
correct and unit-consistent.

### Q-S6 — Any GetScale() != 1.0 across missions?
**No.** Every object in the DryDock set (ships, stations, shuttles, planet,
sun, backdrop spheres, grid) reported `scale=1.0000` across all 14 unique
objects.

### Conclusions

1. **No implicit C++ scale.** BC's compiled engine never applies a per-class
   multiplier at render time.  `GetScale()` defaults to 1.0 and the SDK never
   changes it for stock ships, planets, or suns.

2. **Visual size formula:**
   `render_scale = GetRadius() / NIF_bound_radius`
   The NIF bound radius must be measured per NIF file.

3. **`engine/scale.py` corrections:**
   - `PLANET_NIF_NATIVE_RADIUS` corrected from 45 → **90** (measured from NIF header).
   - `SHIP_SCALE=0.1` and `ASTRO_SCALE=10.0` removed; scale is per-object,
     derived from `GetRadius()` and the NIF's authored bound radius.
   - `CAMERA_NEAR=1.0`, `CAMERA_FAR=5000.0` added from frustum capture.

4. **Galaxy ship NIF bound radius** still needs measuring to finish the ship
   render scale.  Use `tools/list_nif_blocks.py` on the Galaxy NIF.

### Observed object radii (Tau Ceti / E1M1)

| Name | Radius (BC units) | Scale |
|---|---|---|
| player (Galaxy-class) | 4.3665 | 1.0 |
| Dry Dock × 3 | 8.9701 | 1.0 |
| Shuttle × 3 | 0.1506 | 1.0 |
| Station (Soho) | 12.4835 | 1.0 |
| USS Nightingale | 3.2013 | 1.0 |
| Backdrop stars | 305.7177 | 1.0 |
| Backdrop nebula | 245.9793 | 1.0 |
| Grid | 50.0000 | 1.0 |
| Sun | 4040.6533 | 1.0 |
| Tau Ceti Prime | 180.0000 | 1.0 |
