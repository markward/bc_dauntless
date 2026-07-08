# Planet render-scale investigation

Status: **PENDING** (probe written; needs a Windows -TestMode run)
Author: 2026-07-07 session
Created: 2026-07-07

## Goal

Explain why the Haven colony planet (Vesuvi 6, E1M2) renders at a **noticeably
larger apparent size in our build than in the original game**, despite the HUD
range readout being nearly identical (~25-27 km surface distance) in both.

We have a screenshot pair (ours vs. original) at Haven orbit. Ours shows a large
planet disc filling ~40% of the frame; the original shows a much smaller / near-
invisible body at the same reticle.

## What static analysis already settled (no run needed)

- **Haven is `App.Planet_Create(90.0, ".../GreenPurplePlanet.nif")`**
  (`sdk/.../Systems/Vesuvi/Vesuvi6_S.py:17`) → `GetRadius() == 90` GU.
- **`GreenPurplePlanet.NIF` is a UV sphere, native radius 90.01**, authored
  `NiTriShapeData.bound_radius = 90.01` (measured with `dump_nif_tree`).
- **Our render path** (`engine/host_loop.py`): planets are scaled by
  `natural_scale = GetRadius() / extent`, where
  `extent = _model_extent_from_aabb = |center| + |half_extents|`
  = 90.01·√3 = **155.9** for this sphere. So our rendered planet radius is
  `90.01 · (90/155.9)` ≈ **52 GU** — NOT 90.
  - This is a real divisor bug: ships use BC's flat `BC_MODEL_SCALE`, but the
    intended planet formula (per the 2026-05-12 scale experiment) is
    `GetRadius() / NIF_bound_radius`. Using the AABB **corner** distance
    (√3× the bound sphere) instead of the authored bound radius shrinks our
    planet by 1/√3.
- **Our exterior camera FOV** is `EXTERIOR_FOV_Y_RAD = 60°` vertical
  (`engine/cameras/__init__.py`).
- **Prior scale experiment (2026-05-12, E1M1 DryDock):** every object had
  `GetScale() == 1.0`; the camera frustum measured **21.2° vertical FOV**.
  *Caveat:* that capture was the **DryDock cinematic** (M1Basic), which is very
  plausibly a zoomed cinematic camera, NOT the normal tactical gameplay view.

## The paradox this experiment must break

Our side is self-consistent: rendered radius 52 GU, FOV 60°, center distance
~242 GU (HUD 26.65 km surface + 15.75 km GetRadius) → angular diameter ≈ 24.8°
→ ~41% of screen height. That matches our screenshot.

But if BC renders Haven at `GetRadius = 90 GU` (as the 2026-05-12 experiment
concluded) at a **similar** distance and a **normal** FOV, BC's planet should be
*bigger* than ours — the opposite of what the screenshots show. So exactly one
of these must be true, and the probe will tell us which:

1. **BC's tactical FOV is much wider than 60°** (the 21.2° was a cinematic; the
   real gameplay FOV is wide) → wide FOV shrinks apparent size. *(But a plain
   FOV widening can't by itself make 90 GU look smaller than our 52 GU unless
   the FOV is implausibly large — watch the number.)*
2. **BC does NOT render planets at `GetRadius`** — there is a per-planet render
   scale (or a different divisor) that makes Haven's rendered radius much
   smaller than 90 GU. In that case our whole planet-scale model is wrong and
   the 2026-05-12 conclusion (`render_scale = GetRadius/NIF_bound`) is refuted.
3. **The distances aren't actually similar** — the original screenshot is
   farther out than its HUD readout implies.

## Specific questions

- **Q-P1** Haven `GetRadius()` and `GetScale()` at E1M2 orbit (confirm 90 / 1.0).
- **Q-P2** The **active tactical camera** vertical + horizontal FOV in E1M2 (from
  the live `NiFrustum`) — is it 60-ish, 21°, or something wider?
- **Q-P3** Exact **player ↔ Haven center distance** (GU + km), to cross-check the
  HUD readout and the screenshot.
- **Q-P4** Same for Moon 1 (`Planet_Create(80.0, RockyPlanet.nif)`) as a second
  data point.
- **Q-P5** Predicted **on-screen angular diameter / screen-fraction IF rendered
  at GetRadius**, computed in-probe from FOV + distance. Compare against the
  actual fraction in the original screenshot: if the prediction is far bigger
  than the screenshot, BC renders planets smaller than GetRadius (hypothesis 2).

## Probe

[`tools/probes/q11_planet_scale.py`](../../tools/probes/q11_planet_scale.py).
One-shot console probe (instrumentation **approach 2**, see
[`console-probe-workflow.md`](console-probe-workflow.md)). Captures, for the
currently-rendered set: player pos/radius/scale, the active camera frustum
(→ FOV), and every Planet/Sun's radius/scale/position/atmosphere, plus derived
distances and the predicted at-GetRadius angular size. Writes
`[BCProbe_q11]` to `game/BCProbe_q11.cfg`.

## How to run (Windows operator)

1. `git pull`.
2. `uv run python tools/probes/push.py q11` (copies the probe into `game/`).
3. Launch `game/stbc.exe -TestMode`.
4. Start **Single Player → Maelstrom → Episode 1 → Mission 2 (E1M2)** and fly to
   **Haven orbit** — i.e. reproduce the screenshot: Haven targeted, range
   ~25-27 km, tactical (external) view. Getting close to that distance matters
   for Q-P3/Q-P5; the FOV (Q-P2) is distance-independent.
   - If E1M2 is awkward to reach, a **QuickBattle with any planet** still answers
     Q-P1/Q-P2 (radius + tactical FOV); only the Haven-specific distance needs
     the real mission.
5. Drop to the console and run: `execfile('q11_planet_scale.py')` — wait for
   `done`.
6. `uv run python tools/probes/collect.py q11` → writes
   `tools/probes/results/q11_planet_scale.txt`.
7. `git add tools/probes/results/q11_planet_scale.txt && git commit && git push`.
8. (Optional but ideal) drop the matching screenshot into
   `tools/probes/results/` so the on-screen fraction can be measured against
   Q-P5's prediction.

## Cleanup

The probe scrubs its own cfg keys (write-then-scrub, single-threaded) so
`Options.cfg` is not polluted. No `setup.py`/App.py edits are involved — nothing
to revert.

## Findings

_(pending run — fill in from `tools/probes/results/q11_planet_scale.txt`)_

### Q-P1 — Haven GetRadius / GetScale
### Q-P2 — Active tactical-view FOV
### Q-P3 — Player ↔ Haven distance
### Q-P4 — Moon 1
### Q-P5 — Predicted vs. actual on-screen size
### Conclusion
