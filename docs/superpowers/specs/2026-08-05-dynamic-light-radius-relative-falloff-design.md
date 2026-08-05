# Radius-Relative Dynamic-Light Falloff (design)

**Date:** 2026-08-05
**Status:** approved-in-principle (Mark); spec for review
**Area:** dynamic-light attenuation (`native/src/renderer/dynamic_lights.cc` +
`opaque.frag`), the shared curve all point/strip/cone emitter lights use.

## Problem

Subsystem light emitters (and torpedo glow) can't light large objects. On a
starbase, a strip emitter with **radius 208 GU / intensity 17** casts no visible
light on the hull. The attenuation

```
att(d, radius) = (1 − (d/radius)⁴)²  ⁄  (d² + 1)
```

multiplies a **radius-relative window** `(1 − (d/radius)⁴)²` (≈1.0 until near
`radius`) by an **absolute inverse-square** `1/(d² + 1)` whose reference is a
fixed **1 GU**. The window isn't the limiter (it stays ≈1 for a 208 GU light);
the inverse-square is, and it does **not** scale with `radius`. So a 208 GU
light falls off exactly as fast as a 2 GU one:

| d (GU) | att·intensity(17) |
|---|---|
| 2 | 3.4 | 5 | 0.65 | 10 | 0.17 | 20 | 0.04 | 30 | 0.02 | 50–80 | ~0.005 |

Hull surfaces on a station sit 20–80 GU from the strip → invisible. Raising
`radius` doesn't help (window already ≈1); raising `intensity` enough to reach
50 GU blows out everything within 5 GU. Unwinnable with this curve. Same class
as the cone-reach fix and "BC suns → radius-relative ramps": the curve is tuned
for **ship-scale proximity** (torpedo glow, small hull strips at 1–5 GU).

## Fix — threshold-offset radius-relative reference

Keep today's curve for everything up to a **ship-scale ceiling `R0`**, and only
soften the inverse-square reference for lights bigger than that:

```
ref = 1 + max(0.0, radius − R0) · k       // R0 = kDynLightShipCeilingGU (~40)
                                          // k  = kDynLightFalloffK      (~0.3)
att(d, radius) = (1 − (d/radius)⁴)²  ⁄  ((d/ref)² + 1)
```

- **radius ≤ R0 → `ref = 1` → BYTE-IDENTICAL to today.** Torpedo glow (radius
  ~5–15), ship emitters (1–3), Galaxy warp cones (reach = length ≈ 1.3) — all
  unchanged, **no re-tune of any kind**.
- **radius ≫ R0 → usable.** radius 208, R0 40 → `ref = 1 + 168·0.3 ≈ 51`; a hull
  fragment 30 GU away reads ~0.78 instead of 0.02. The strip wraps the station.
- `att(0,·)=1`, `att(radius,·)=0`, `radius≤0→0` all preserved at every radius
  (d=0 and the window edge are ref-independent).
- **`R0` and `k` are the two tuning knobs** (shared C++/GLSL constants; rebuild
  to change). `R0` must sit above the largest ship/torpedo light radius —
  confirm the actual torpedo radius (`100 × max(glow_size_a, glow_size_b)`)
  during implementation and set `R0` with margin. `k` sets the station falloff.

### Why not the simpler `ref = max(1, radius·k)`
That global form has a ~3 GU threshold, so it brightens torpedo/medium lights
~7× and forces a torpedo re-tune. The threshold-offset avoids all of that by
gating on `R0`; it is the chosen design.

## Blast radius (intentional, contained)

Only lights with `radius > R0` shift — station-scale strips, plus two
deliberately large-light **frame tests** that turn out to be robust:

- The renderer frame tests are **assertion-based, not golden-image** (they read
  specific pixels and assert lit / cone-gated / no-GL-error). **`test_cone_light_frame.cc`**
  (`radius = 60`) asserts an on-axis fragment is lit (stays lit — brighter) and
  an off-axis fragment is dark because it's **cone-gated** (`spot = 0`), not
  falloff — unaffected. **`frame_test.cc`**'s `radius = 500` case only asserts
  `glGetError == GL_NO_ERROR`. So **no golden re-baseline is expected**; the
  task just confirms the whole suite stays green. The 7 already-baselined
  scorch/heat-glow FrameTests in `known_failures.txt` are independent.
- **`dynamic_light_attenuation` unit tests** (`dynamic_lights_test.cc`) hardcode
  values (e.g. `att(5,10)=0.0338…`). With `R0 ≈ 40`, radius 10 is **below** `R0`
  → `ref=1` → those rows are **unchanged**. ADD new rows proving the fix: a
  `radius > R0` case where `att` is far higher than the old curve (`att(30, 208)`),
  and a byte-identity assertion for a `radius ≤ R0` case.
- **Torpedo / ship-emitter runtime look**: unchanged (radius ≤ R0). No Python
  knob edit required; the torpedo intensity knob remains a backstop only.

## Non-goals

- No new per-emitter field, no data/persistence change (the curve alone changes;
  authored `radius`/`intensity` keep their meaning).
- No live-tunable `R0`/`k` uniforms this pass (shared constants + rebuild; a
  uniform is a possible follow-up if by-feel iteration proves painful).
- The emissive-suppression `refl_mask` (bright self-illum surfaces reject
  reflected light) is correct and unchanged — the fix lights the non-emissive
  hull structure, which is the goal.

## Global constraints

- **The C++ `dynamic_light_attenuation` and the GLSL in `opaque.frag` MUST stay
  bit-matched** (the existing contract comment; use `ratio*ratio*ratio*ratio`,
  not `pow`). `R0` and `k` are the same literals in both.
- `att(0, r) = 1`, `att(≥radius, r) = 0`, and `radius ≤ 0 → 0` invariants
  preserved at every radius.
- **`radius ≤ R0` behaviour byte-identical** — proven by keeping the existing
  sub-ceiling unit-test rows unchanged and asserting equality against the old
  formula for a `radius ≤ R0` case.
- Shader edit ⇒ `cmake -B build -S .` reconfigure before build; C++ change ⇒
  `dauntless` + ctest rebuild. Gate: `scripts/check_tests.sh`, re-baselining any
  newly-failing frame test.

## Testing

- **`dynamic_lights_test.cc`:** the existing `att(0,10)=1`, `att(5,10)=0.0338…`,
  `att(10,10)=0`, `att(20,10)=0`, `radius≤0→0` rows all stay GREEN unchanged
  (radius 10 ≤ R0 ⇒ `ref=1`) — this is the regression guard. ADD: `att(30, 208)`
  ≫ its old value (reach fix), and a byte-identity assertion for a `radius ≤ R0`
  case. The selection test (derives from `att(5,10)`) is unaffected.
- **Monotonic-decreasing** property test still holds (a bigger `ref` only
  flattens, never inverts, the curve).
- **Frame tests:** rebuild, run ctest; the assertion-based frame tests
  (`test_cone_light_frame`, `frame_test`) are expected to stay GREEN with no
  golden change (their assertions are litness / cone-gate / no-GL-error, robust
  to a brighter curve). If any assertion unexpectedly flips, that's a signal to
  investigate — not to blindly loosen it.
- Full gate green (1 known baseline).
