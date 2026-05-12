# System scale investigation

Status: **PENDING**
Author: 2026-05-12 session
Created: 2026-05-12

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

   ```
   cp game/BCScaleLog.cfg game/BCScaleLog.m1basic.cfg
   ```

5. **Load Maelstrom Episode 1 Mission 1** in BC (Single Player → Custom
   → Maelstrom → E1M1). Wait 30s after the scene appears.

6. **Stash the second capture**:

   ```
   cp game/BCScaleLog.cfg game/BCScaleLog.e1m1.cfg
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
obj1_model=data/models/environment/GreenPurplePlanet.nif
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
should reveal.)

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

   ```
   mkdir -p docs/instrumented_experiments/captures
   mv game/BCScaleLog*.cfg docs/instrumented_experiments/captures/
   ```

   The captures are small text and worth committing alongside the
   findings.

4. **Update this file**: set `Status: DONE`, set `Closed:` date,
   populate `Findings`.

## Findings

*(empty until the experiment runs)*
