# Warp VFX — ST Warp (Dust Streak + Prism) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the warp VFX on `feat/warp-vfx-flythrough` into the Star-Trek look: revert the background-star-streak + galaxy-vantage flythrough; instead the camera dust streaks past with prism-colored tips during a 4-phase warp (align+turn+spool → boom flash → prism dust streaks → exit boom + shrink). Reuse the flash, WarpVFX manager, timed transit, and toggle already on the branch.

**Architecture:** The warp `TGSequence` gains an align phase before the distance-scaled transit. The `WarpVFX` manager owns the clock + envelopes (streak/flash/turn). Native: the dust pass adds a warp **drift** (fast streaming along travel, reusing the `sun_drift` fold-into-wrap) + **elongation** (smear stretch) + **prism tip** (procedural hue) keyed to the existing `dauntless_warp_vfx::streak_intensity()`; the backdrop star-streak + vantage are reverted. Python drives the dust feed, a sun **dim**, a cinematic ship **turn** (nlerp), slow-down, and enter/exit **SFX**.

**Tech Stack:** native OpenGL/GLSL + pybind (cmake reconfigure for shaders), Python engine, pytest.

## Global Constraints

- Never edit `sdk/Build/scripts/`. Python tests: `uv run pytest`.
- **Shader edits need `cmake -B build -S .` (reconfigure) then `cmake --build build -j`** (shaders embed at configure time). `host_bindings.cc`/`frame.cc` compile into both `build/dauntless` and `_dauntless_host` — build the `dauntless` target. Native ctest: `ctest --test-dir build`.
- **Off-path parity (mandatory):** with the warp toggle OFF and `streak_intensity()==0`, the dust, backdrop, resolve, suns, and ship motion must be byte-identical to today. Every warp effect gated behind `streak_intensity() > 0` / `WarpVFX.is_active()`.
- **Fail-open:** the turn/SFX/dust/dim never block the warp — the set-swap always completes and control is always restored (mirror the spine).
- Headless / flythrough-off ⇒ the instant Stage-1 warp path runs unchanged (existing warp tests stay green).
- Reuse the already-present `dauntless_warp_vfx` namespace (`streak_intensity()`, `flash_intensity()`, `travel_dir()`) and `engine/renderer.py` setters (`set_warp_streak_intensity`, `set_warp_flash_intensity`, `set_warp_travel_dir`) — the dust reads the SAME channel the backdrop used; no new bindings needed.

**Verbatim current code + revert points (verified — use these exact lines):**
- `dust.vert` (full, 1-66): smear line `offset += 0.5 * a_corner.y * u_smear;` (line 58); wrap `local = a_particle.xyz - u_camera_pos + u_sun_drift;` (line 34) then `mod`; outs `v_uv/v_brightness/v_local`.
- `dust.frag` (full, 1-22): `out_color = vec4(tex.rgb * v_brightness * tint, tex.a * fade);` (line 21).
- `dust_pass.cc render()` (165-234): sets `u_smear`, `u_sun_drift` (`shader.set_vec3("u_sun_drift", sun_drift)`), `u_sun_tint`; has the `sun_drift_phase_` accumulator pattern (advance + `fmod` to `2*kVolumeRadius`); `glDrawElementsInstanced(...)`. `dust_pass.h render()` decl (114-126).
- Dust frame() call `host_bindings.cc:569-570`: `g_dust_pass->render(cam, dt, *g_pipeline, g_suns, g_dust_planets);`
- **Revert (backdrop star-streak):** `backdrop.frag` uniforms `u_warp_streak`/`u_warp_travel` (17-18) + the `if (u_warp_streak > 0.0){...}` block in `proc_stars` (43-53) → restore `float d = length(delta);`. `backdrop_pass.h render()` (31-37) + `draw_backdrops()` (56-63) trailing `float warp_streak, glm::vec3 warp_travel` params. `backdrop_pass.cc` `shader.set_float("u_warp_streak",...)`/`set_vec3("u_warp_travel",...)` (97-98) + the `draw_backdrops(...)` call args (81-82). `host_bindings.cc` backdrop `render()` call passing `dauntless_warp_vfx::streak_intensity()/travel_dir()` (545-549) → revert to `(g_backdrops, cam, *g_pipeline, dauntless_procedural_sky::enabled(), static_cast<float>(now))`; and the `if (warp_active) sky_use_cubemap = false;` bypass (in the bake block) → REMOVE (sky is static during warp now).
- **Revert (host_loop):** vantage override `host_loop.py:1950-1951` `if vantage is not None and _w.is_active(): vantage = _w.vantage()` → remove. Suns/planets DROP `host_loop.py:4376-4380` (`suns = [] if _w.is_active() else _aggregate_suns()` etc.) → restore plain aggregation (the DIM is added in Task 2, not a drop).
- Ship rotation: `player.GetWorldRotation() -> TGMatrix3`, `player.SetMatrixRotation(R)`, `player.AlignToVectors(fwd, up)` (objects.py:126), `engine/core/interpolate.py:nlerp_rotation(a, b, alpha)` (33-69), `GetCol(1)`=forward/`GetCol(2)`=up. `player.SetSpeed(float)`. Control: `MissionLib.RemoveControl()`/`ReturnControl()` (toggle `TopWindow.AllowKeyboardInput`).
- SFX: `import App; App.g_kSoundManager.PlaySound(name)` (plays a registered sound by name; returns handle or None). Loaded names come from `LoadBridge.LoadSounds()` — confirm the registered names for enter/exit warp, else `g_kSoundManager.LoadSound(path, name, App.TGSound.LS_2D).Play()`.
- `engine/warp_vfx.py` (full) + `engine/appc/warp.py` `WarpSequence_Create`/`_WarpVfxBegin/End`/`configure_warp_vfx`/`_transit_duration` — see the brief.

---

### Task 1: Native — revert backdrop streak, add dust warp streak (drift + elongation + prism)

Move the warp streak from the background stars to the dust. Revert the backdrop star-streak + cubemap-bypass; add a dust warp drift (fly-past) + elongation (streak) + prism tip, keyed to the existing `dauntless_warp_vfx` channel. Off-parity at streak 0.

**Files:**
- Modify: `native/src/renderer/shaders/backdrop.frag`, `native/src/renderer/backdrop_pass.{cc,h}`, `native/src/host/host_bindings.cc` (revert backdrop; add dust feed)
- Modify: `native/src/renderer/shaders/dust.vert`, `native/src/renderer/shaders/dust.frag`, `native/src/renderer/dust_pass.{cc,h}`
- Test: native ctest (compile + off-parity); a `DustPass`/`BackdropPass` test if present

**Interfaces:** consumes `dauntless_warp_vfx::streak_intensity()` / `travel_dir()`. `DustPass::render(...)` gains `float warp_streak=0.0f, glm::vec3 warp_travel=glm::vec3(0,1,0)`. `BackdropPass::render` loses its two warp params (revert).

- [ ] **Step 1: Revert the backdrop star-streak.**
  - `backdrop.frag`: delete uniforms `u_warp_streak`/`u_warp_travel` (17-18) and the `if (u_warp_streak > 0.0){...}` block (43-53); the line after becomes the original `float d = length(delta);` (verify `delta = g - starPos;` remains so the restored line equals the pre-warp `length(g - starPos)`).
  - `backdrop_pass.h`: remove the trailing `float warp_streak`, `glm::vec3 warp_travel` from `render()` (31-37) and `draw_backdrops()` (56-63).
  - `backdrop_pass.cc`: remove the two `shader.set_*("u_warp_streak"/"u_warp_travel",...)` (97-98) and the trailing args in the `draw_backdrops(...)` call (81-82).
  - `host_bindings.cc`: revert the `g_backdrop_pass->render(...)` call (545-549) to `(g_backdrops, cam, *g_pipeline, dauntless_procedural_sky::enabled(), static_cast<float>(now))`; REMOVE the `if (warp_active) sky_use_cubemap = false;` bypass line in the bake block (the sky is static during warp now). Leave the rest of the bake logic intact.

- [ ] **Step 2: Dust vertex shader — drift + elongation varying.** In `dust.vert`:
  - Add uniforms: `uniform float u_warp_streak;` and `uniform vec3 u_warp_drift;` (a fast world-space translation accumulated C++-side; folded into the wrap like `u_sun_drift`).
  - Fold the warp drift into the wrap — change line 34 to:
    `vec3 local = a_particle.xyz - u_camera_pos + u_sun_drift + u_warp_drift;`
  - Elongate along the smear during warp — change line 58 to:
    `offset += 0.5 * a_corner.y * (u_smear + u_warp_streak * 6.0 * u_smear_dir_or_travel);`
    where the warp stretch is along the world-space travel axis. To get the travel axis in world space, add `uniform vec3 u_warp_travel;` and use:
    `vec3 wstretch = u_warp_streak * (4.0) * normalize(u_warp_travel + 1e-5);`
    `offset += 0.5 * a_corner.y * (u_smear + wstretch);`
    (the `4.0` GU base stretch is tunable). Add `out float v_streak;` and write `v_streak = u_warp_streak * max(a_corner.y, 0.0);` (leading-edge param for the prism).

- [ ] **Step 3: Dust fragment shader — prism tip + brightness.** In `dust.frag` add `in float v_streak;` and, before the final write, blend the leading tip toward a procedural prism hue and brighten with streak:
```glsl
    vec3 base = tex.rgb * v_brightness * tint;
    if (v_streak > 0.0) {
        // Procedural prism: sweep hue along the streak's leading edge.
        float h = fract(v_uv.y * 0.5 + v_streak);    // hue 0..1 along streak
        vec3 prism = clamp(abs(fract(h + vec3(0.0, 0.3333, 0.6667)) * 6.0 - 3.0) - 1.0, 0.0, 1.0);
        base = mix(base, base + prism, v_streak);     // tint tips, fade in with streak
        base *= (1.0 + 1.5 * v_streak);               // brighten streaks
    }
    out_color = vec4(base, tex.a * fade);
```

- [ ] **Step 4: Dust pass — warp drift accumulator + uniforms.** In `dust_pass.cc render()` (mirror the `sun_drift_phase_` pattern): add a member `float warp_drift_phase_ = 0.0f;` (dust_pass.h). In render(), after the sun-drift block, accumulate the warp drift along travel while warping:
```cpp
    if (warp_streak > 0.0f && dt_seconds > 0.0f && dt_seconds < kVelocityClampSeconds) {
        warp_drift_phase_ += kWarpDriftSpeed * warp_streak * dt_seconds;  // GU/s, tunable const
        warp_drift_phase_ = std::fmod(warp_drift_phase_, 2.0f * kVolumeRadius);
    } else if (warp_streak <= 0.0f) {
        warp_drift_phase_ = 0.0f;
    }
    const glm::vec3 warp_drift = -glm::normalize(warp_travel + glm::vec3(1e-5f)) * warp_drift_phase_;
    shader.set_float("u_warp_streak", warp_streak);
    shader.set_vec3 ("u_warp_travel", warp_travel);
    shader.set_vec3 ("u_warp_drift",  warp_drift);
```
  Add `static constexpr float kWarpDriftSpeed = 600.0f;` (tunable) near the other dust consts. Extend `DustPass::render` decl (dust_pass.h) with the two defaulted params.

- [ ] **Step 5: Feed the dust warp from frame().** In `host_bindings.cc` (569-570):
```cpp
if (!for_viewscreen && g_dust_pass)
    g_dust_pass->render(cam, dt, *g_pipeline, g_suns, g_dust_planets,
                        dauntless_warp_vfx::streak_intensity(),
                        dauntless_warp_vfx::travel_dir());
```

- [ ] **Step 6: Reconfigure + build + ctest**

Run: `cmake -B build -S . && cmake --build build -j && ctest --test-dir build --output-on-failure`
Expected: shaders compile; no NEW ctest failures vs base (the scorch/heat-glow + bake_sector_model are pre-existing). Report the pass/fail list.

- [ ] **Step 7: Off-parity argument in the report** — with `warp_streak==0`: dust elongation term is `+0`, drift is 0 (phase reset), prism branch skipped (`v_streak==0`) ⇒ dust byte-identical; backdrop reverted to original `proc_stars` ⇒ identical; no cubemap bypass ⇒ baked sky as before.

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/shaders/backdrop.frag native/src/renderer/backdrop_pass.cc native/src/renderer/include/renderer/backdrop_pass.h native/src/renderer/shaders/dust.vert native/src/renderer/shaders/dust.frag native/src/renderer/dust_pass.cc native/src/renderer/include/renderer/dust_pass.h native/src/host/host_bindings.cc
git commit -m "feat(warp-vfx): move warp streak from backdrop stars to dust (drift+elongation+prism)"
```

---

### Task 2: WarpVFX manager rework (phases + turn) + host feed (dust, dim, turn)

Rework the manager to the 4-phase model (align→transit) with a turn fraction, drop the vantage; revert the host's vantage override + suns/planets drop; feed the dust streak/flash/travel, dim suns during transit, and apply the cinematic turn slerp.

**Files:**
- Modify: `engine/warp_vfx.py`, `engine/host_loop.py`
- Test: `tests/unit/test_warp_vfx.py` (rewrite to the new API)

**Interfaces produced:** `WarpVFX.start(heading, t_align, t_transit, now)`, `tick(now)`, `stop()`, `is_active()`, `phase()` ("align"|"transit"), `turn_fraction()`, `streak_intensity()`, `flash_intensity()`, `travel_dir()` (=heading). Host: per-frame feed + `_warp_apply_turn(player)`.

- [ ] **Step 1: Rewrite the manager test (failing)**

```python
# tests/unit/test_warp_vfx.py  (replace the vantage tests)
from engine.warp_vfx import WarpVFX


def test_phases_and_turn():
    w = WarpVFX()
    w.start(heading=(1.0, 0.0, 0.0), t_align=2.0, t_transit=4.0, now=0.0)
    w.tick(0.0)
    assert w.phase() == "align" and w.turn_fraction() == 0.0
    assert w.streak_intensity() == 0.0          # no streak during align
    w.tick(1.0); assert 0.0 < w.turn_fraction() < 1.0
    w.tick(2.0); assert w.turn_fraction() == 1.0 and w.phase() == "transit"
    w.tick(4.0); assert w.streak_intensity() > 0.5   # streaking mid-transit
    w.tick(6.0); assert w.is_active() is False        # done at align+transit
    assert w.travel_dir() == (1.0, 0.0, 0.0)


def test_flash_booms_at_burst_and_exit():
    w = WarpVFX(); w.start((1, 0, 0), 2.0, 4.0, 0.0)
    w.tick(2.0); assert w.flash_intensity() > 0.5     # burst boom at align end
    w.tick(4.0); assert w.flash_intensity() < 0.2     # quiet mid-transit
    w.tick(5.9); assert w.flash_intensity() > 0.3     # exit boom near end


def test_stop_resets():
    w = WarpVFX(); w.start((1, 0, 0), 2.0, 4.0, 0.0)
    w.stop()
    assert (w.is_active(), w.streak_intensity(), w.flash_intensity()) == (False, 0.0, 0.0)
```

- [ ] **Step 2: Run red** — `uv run pytest tests/unit/test_warp_vfx.py -v` → FAIL (new API).

- [ ] **Step 3: Rewrite `engine/warp_vfx.py`** (replace the class; drop the vantage lerp):

```python
"""WarpVFX — per-frame warp animator (Stage 2: ST warp dust streak).

Owns the 4-phase warp clock and the streak/flash/turn envelopes. Ticked each
frame by the host loop; started/stopped by the WarpSequence. Pure math,
headless-safe. The speed sensation comes from the DUST pass (driven by
streak_intensity + travel_dir); the camera/ship turn is applied by the host
using turn_fraction.

Spec: docs/superpowers/specs/2026-06-22-warp-vfx-dust-streak-design.md
"""


def _smooth(t):
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return t * t * (3.0 - 2.0 * t)


class WarpVFX:
    def __init__(self):
        self._active = False
        self._heading = (0.0, 1.0, 0.0)
        self._t_align = 0.0
        self._t_transit = 0.0
        self._t0 = 0.0
        self._turn = 0.0
        self._streak = 0.0
        self._flash = 0.0

    def start(self, heading, t_align, t_transit, now):
        self._heading = tuple(heading)
        self._t_align = max(0.01, float(t_align))
        self._t_transit = max(0.01, float(t_transit))
        self._t0 = float(now)
        self._active = True
        self._turn = 0.0
        self._streak = 0.0
        self._flash = 0.0

    def _elapsed(self, now):
        return now - self._t0

    def phase(self):
        return "align" if self._turn < 1.0 or self._streak == 0.0 else "transit"

    def tick(self, now):
        if not self._active:
            return
        e = self._elapsed(now)
        total = self._t_align + self._t_transit
        if e < self._t_align:
            # ALIGN: turn ramps 0->1, no streak, engine-spool (no flash yet).
            self._turn = _smooth(e / self._t_align)
            self._streak = 0.0
            self._flash = 0.0
            self._phase = "align"
        else:
            self._turn = 1.0
            tp = (e - self._t_align) / self._t_transit   # transit progress 0..1
            # streak: fast ramp at burst, hold, shrink at exit.
            self._streak = min(_smooth(tp / 0.12), _smooth((1.0 - tp) / 0.15))
            # flash: burst boom (decays over first 10% of transit) + exit boom.
            burst = max(0.0, 1.0 - tp / 0.10)
            exit_ = max(0.0, (tp - 0.90) / 0.10)
            self._flash = min(1.0, burst + exit_)
            self._phase = "transit"
        if e >= total:
            self._active = False
            self._turn = 1.0
            self._streak = 0.0
            self._flash = 0.0

    def stop(self):
        self._active = False
        self._turn = 0.0
        self._streak = 0.0
        self._flash = 0.0

    def is_active(self):        return self._active
    def phase(self):            return getattr(self, "_phase", "align")
    def turn_fraction(self):    return self._turn
    def streak_intensity(self): return self._streak
    def flash_intensity(self):  return self._flash
    def travel_dir(self):       return self._heading


_singleton = WarpVFX()


def get():
    return _singleton
```

> Note: keep `phase()` as the method returning `self._phase`; remove the earlier stub `phase()` definition (only one). Verify the test's `phase()` reads correctly.

- [ ] **Step 4: Run green** — `uv run pytest tests/unit/test_warp_vfx.py -v` → PASS.

- [ ] **Step 5: Revert host_loop flythrough bits + add the new feed.**
  - `_aggregate_backdrops` (~1950-1951): remove the vantage override (and the now-unused `from engine import warp_vfx as _wv; _w = _wv.get()` if only used there).
  - Suns/planets (~4376-4380): restore plain aggregation (remove the `[] if _w.is_active()` drop).
  - Per-frame feed (where the old streak/flash feed was, ~4315): while active, feed travel/streak/flash AND apply the dim + turn:
```python
        from engine import warp_vfx as _wv
        _w = _wv.get()
        if _w.is_active():
            _w.tick(_now_game_time())   # same clock the swap delay uses (GetGameTime)
            r.set_warp_streak_intensity(_w.streak_intensity())
            r.set_warp_flash_intensity(_w.flash_intensity())
            r.set_warp_travel_dir(_w.travel_dir())
            if player is not None:
                _warp_apply_turn(player, _w.turn_fraction(), _w.travel_dir())
        else:
            r.set_warp_streak_intensity(0.0)
            r.set_warp_flash_intensity(0.0)
            _warp_clear_turn()
```
  - Sun dim during transit: in the suns feed, scale each sun's brightness/radius by `(1.0 - DIM * _w.streak_intensity())` while active (DIM≈0.7, tunable) — read the real sun-descriptor brightness field and scale it (or scale radius if that's the brightness lever, as the flythrough-investigation noted sun_pass dims by radius). Keep it gated on `is_active()`.
  - Add the turn helpers near the other host helpers:
```python
_warp_turn_start_R = None  # captured player rotation at align start

def _warp_apply_turn(player, frac, heading):
    """Slerp the player's rotation toward the warp heading by `frac` (0..1)."""
    global _warp_turn_start_R
    import App
    from engine.appc.math import TGMatrix3, TGPoint3   # confirm real import path
    from engine.core.interpolate import nlerp_rotation
    R0 = player.GetWorldRotation()
    if _warp_turn_start_R is None:
        _warp_turn_start_R = R0
    up = _warp_turn_start_R.GetCol(2)
    fwd = TGPoint3(heading[0], heading[1], heading[2])
    target = TGMatrix3(); target.AlignToVectors(fwd, up)
    player.SetMatrixRotation(nlerp_rotation(_warp_turn_start_R, target, frac))

def _warp_clear_turn():
    global _warp_turn_start_R
    _warp_turn_start_R = None
```

> Implementer: confirm the REAL import path for `TGMatrix3`/`TGPoint3`/`AlignToVectors` (the dust-streak brief shows `AlignToVectors` on the OBJECT, `objects.py`; you may build the target via `player.AlignToVectors(fwd, up)` on a throwaway then read its rotation, OR construct a `TGMatrix3` directly — use whichever real API exists). Confirm `nlerp_rotation` signature `(a, b, alpha)`. Confirm `_now_game_time()` is the real game-time accessor (`App.g_kUtopiaModule.GetGameTime()`), matching the sequence-delay clock.

- [ ] **Step 6: Run tests + host import**

Run: `uv run pytest tests/unit/test_warp_vfx.py tests/ -k "warp or host_loop or backdrop" -q`
Expected: PASS (existing warp tests green — the sequence still uses the old `start(...)` until Task 3, so update the `configure_warp_vfx` `start` adapter there; if Task 2 breaks the start signature, gate it so `warp.py` still calls the OLD signature until Task 3 — OR do Task 2+3 atomically. Prefer: Task 2 changes the manager + host feed; Task 3 changes warp.py's start call to the new signature. To keep tests green between, have the host `_vfx_start` adapter translate. See Step 7.)
Run: `PYTHONPATH=build/python uv run python -c "import engine.host_loop"` → no error.

- [ ] **Step 7: Bridge the start signature.** Until Task 3 reworks `warp.py`, the host `_vfx_start` (wired via `configure_warp_vfx`) must call the NEW `WarpVFX.start(heading, t_align, t_transit, now)`. Update the host `_vfx_start` to accept whatever `warp.py` passes and call the new API (Task 3 finalizes the warp.py side). If this can't be cleanly bridged, fold Task 3 into Task 2 (do them together) — note the decision in the report.

- [ ] **Step 8: Commit**

```bash
git add engine/warp_vfx.py engine/host_loop.py tests/unit/test_warp_vfx.py
git commit -m "feat(warp-vfx): 4-phase WarpVFX manager (align/turn/transit) + dust feed + sun dim + turn"
```

---

### Task 3: Sequence — heading + align/transit timing + slow + SFX + control

Rework `WarpSequence_Create` to the 4-phase sequence: compute the warp heading, remove control + slow + play enter SFX at align start, hold the swap for `T_align + T_transit`, play exit SFX + restore control on arrival.

**Files:**
- Modify: `engine/appc/warp.py`, `engine/host_loop.py` (configure_warp_vfx wiring)
- Test: `tests/unit/test_warp_vfx_sequence.py` (rewrite), `tests/unit/test_warp_spine.py` (stays green)

**Interfaces produced:** `_T_ALIGN` const; `WarpSequence_Create` builds align+transit when flythrough live; `_vfx_start(heading, t_align, t_transit)`; enter/exit `_WarpSoundAction`; slow + control via fail-open actions.

- [ ] **Step 1: Rewrite the sequence test (failing)**

```python
# tests/unit/test_warp_vfx_sequence.py
import App
from engine.appc import warp
from engine.appc.sets import SetClass_Create


def setup_function(_):
    App.g_kSetManager._sets.clear()
    warp.configure_warp_hooks(realize=None, teardown=None)
    warp.configure_warp_vfx(start=None, stop=None, enabled=None, vantage_of=None)


def test_heading_is_normalized_src_to_dst():
    h = warp._warp_heading((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    assert abs(h[0] - 1.0) < 1e-6 and abs(h[1]) < 1e-6
    # unmapped -> default forward
    assert warp._warp_heading(None, (1.0, 0.0, 0.0)) == (0.0, 1.0, 0.0)


def test_flythrough_on_holds_swap_and_starts_vfx():
    started = {}
    warp.configure_warp_vfx(
        enabled=lambda: True,
        start=lambda heading, t_align, t_transit: started.update(
            align=t_align, transit=t_transit, heading=heading),
        stop=lambda: None,
        vantage_of=lambda key: (0.0, 0.0, 0.0))
    src = SetClass_Create(); App.g_kSetManager.AddSet(src, "Src")
    player = App.ShipClass_Create(); player.SetName("player")
    src.AddObjectToSet(player, "player")
    import types, sys
    mod = types.ModuleType("FakeSys.D"); mod.Initialize = lambda: (
        App.g_kSetManager.AddSet(SetClass_Create(), "D"))
    sys.modules["FakeSys.D"] = mod
    warp.WarpSequence_Create(player, "FakeSys.D", placement="Player Start").Play()
    assert started.get("align") == warp._T_ALIGN
    assert started.get("transit") > 0.0
    assert App.g_kSetManager.GetSet("Src") is src   # swap DEFERRED


def test_flythrough_off_is_instant():
    warp.configure_warp_vfx(enabled=lambda: False)
    src = SetClass_Create(); App.g_kSetManager.AddSet(src, "Src2")
    player = App.ShipClass_Create(); player.SetName("player")
    src.AddObjectToSet(player, "player")
    import types, sys
    mod = types.ModuleType("FakeSys.D2"); mod.Initialize = lambda: (
        App.g_kSetManager.AddSet(SetClass_Create(), "D2"))
    sys.modules["FakeSys.D2"] = mod
    warp.WarpSequence_Create(player, "FakeSys.D2", placement=None).Play()
    assert App.g_kSetManager.GetSet("Src2") is None   # instant swap
```

- [ ] **Step 2: Run red** → FAIL (`_warp_heading`/`_T_ALIGN`/new start signature missing).

- [ ] **Step 3: Rework `engine/appc/warp.py`.**
  - Add `_T_ALIGN = 1.5` near the duration consts. Add:
```python
def _warp_heading(src_vantage, dst_vantage):
    if src_vantage is None or dst_vantage is None:
        return (0.0, 1.0, 0.0)
    dx = dst_vantage[0]-src_vantage[0]; dy = dst_vantage[1]-src_vantage[1]; dz = dst_vantage[2]-src_vantage[2]
    m = math.sqrt(dx*dx+dy*dy+dz*dz)
    return (0.0, 1.0, 0.0) if m < 1e-6 else (dx/m, dy/m, dz/m)
```
  - Change `_WarpVfxBeginAction` to start with the new args + remove control + slow + enter SFX, and a `_WarpSoundAction`:
```python
class _WarpSoundAction(TGAction):
    def __init__(self, name): super().__init__(); self._name = name
    def _do_play(self):
        try:
            import App
            App.g_kSoundManager.PlaySound(self._name)
        except Exception:
            pass

class _WarpVfxBeginAction(TGAction):
    def __init__(self, ship, heading, t_align, t_transit):
        super().__init__()
        self._a = (heading, t_align, t_transit); self._ship = ship
    def _do_play(self):
        try:
            import MissionLib; MissionLib.RemoveControl()
        except Exception: pass
        try:
            if hasattr(self._ship, "SetSpeed"): self._ship.SetSpeed(0.0)
        except Exception: pass
        if _vfx_start is not None:
            try: _vfx_start(*self._a)
            except Exception: pass
```
  - `_WarpVfxEndAction` already exists (stops the manager); keep it (the host `stop()` + `_ArriveFinalizeAction.ReturnControl` restore control; the turn clears via the host else-branch).
  - In `WarpSequence_Create` flythrough branch, replace the body:
```python
    if flythrough:
        src_v = _vfx_vantage_of(source) if (_vfx_vantage_of and source) else None
        dst_v = _vfx_vantage_of(dest_module) if _vfx_vantage_of else None
        heading = _warp_heading(src_v, dst_v)
        t_transit = _transit_duration(src_v, dst_v)
        total = _T_ALIGN + t_transit
        seq.AddAction(_WarpVfxBeginAction(ship, heading, _T_ALIGN, t_transit))
        seq.AppendAction(_WarpSoundAction("enter warp"))   # confirm registered name
        seq.AppendAction(ChangeRenderedSetAction_Create(dest_module), total)
        seq.AppendAction(_PlacePlayerAction(ship, dest_name, placement))
        seq.AppendAction(_ArriveFinalizeAction(source, ship))
        seq.AppendAction(_WarpSoundAction("exit warp"))    # confirm registered name
        seq.AppendAction(_WarpVfxEndAction())
        return seq
```
  - `configure_warp_vfx` unchanged; `_vfx_start` now receives `(heading, t_align, t_transit)`.

> Implementer: confirm the REGISTERED sound names for enter/exit warp (grep `LoadBridge`/`LoadTacticalSounds` for the names mapped to `enter warp.wav`/`exit warp.wav`). If they're registered under specific names, use those; if not loaded, load them once (`g_kSoundManager.LoadSound("sfx/enter warp.wav", "WarpEnter", App.TGSound.LS_2D)`) at host init and play by that name. Document the names used. SFX failure is fail-open (try/except) so a wrong name never blocks warp.

- [ ] **Step 4: Update the host `_vfx_start` wiring.** In `host_loop.py` `configure_warp_vfx(...)`, the `start` hook now takes `(heading, t_align, t_transit)`:
```python
        def _vfx_start(heading, t_align, t_transit):
            _wv.get().start(heading, t_align, t_transit, _now_game_time())
        _wp.configure_warp_vfx(start=_vfx_start, stop=_wv.get().stop,
                               enabled=_flythrough_enabled, vantage_of=_vantage_of)
```

- [ ] **Step 5: Run tests + host import**

Run: `uv run pytest tests/unit/test_warp_vfx_sequence.py tests/unit/test_warp_spine.py tests/ -k "warp" -q`
Expected: PASS (warp_spine instant path unchanged; new sequence tests green).
Run: `PYTHONPATH=build/python uv run python -c "import engine.host_loop"` → no error.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/warp.py engine/host_loop.py tests/unit/test_warp_vfx_sequence.py
git commit -m "feat(warp-vfx): 4-phase warp sequence (heading+align+slow+SFX+control)"
```

---

## Final verification

- [ ] `cmake -B build -S . && cmake --build build -j && ctest --test-dir build` → no NEW failures (scorch/heat-glow + bake_sector_model pre-existing).
- [ ] `uv run pytest tests/ -k "warp or configuration or backdrop or dust" -q` → green.
- [ ] `bash scripts/run_tests.sh` → green.
- [ ] **Human gate (Mark):** relaunch `./build/dauntless`, warp from exterior: ship slows + turns, engine-spool SFX, lightspeed boom flash, bright prism-tipped dust streaks fly past (galaxy/suns dimmed behind), exit boom + SFX, streaks shrink to normal dust, arrive in the new system; far hops longer than near. Toggle "Warp Flythrough" off → instant cut. Tune: dust stretch (`dust.vert` 4.0, `kWarpDriftSpeed`), prism, flash booms, `_T_ALIGN`, sun DIM.

## Self-review notes

- **Spec coverage:** dust streak+prism+drift (Task 1), boom flash (kept; envelope retuned Task 2), 4-phase timeline + turn + dim (Task 2), heading + align + slow + SFX + control (Task 3), revert backdrop/vantage (Task 1+2), toggle/distance-duration (reused). Out-of-scope (mesh stretch, burst lunge) untouched.
- **Off-parity:** every warp effect gated on `streak_intensity()>0` / `is_active()`; streak-0 native path argued byte-identical (Task 1 Step 7); toggle-off = instant sequence (Task 3).
- **No-placeholder:** verbatim shader/revert/manager code; flagged "verify the real API" notes (TGMatrix3/AlignToVectors import; registered SFX names; `_now_game_time`) instruct reading the real signature.
- **Risk:** the dust drift+elongation visual is tuned-by-feel; the plan ships sane starting constants and Mark tunes live. The Task 2/3 start-signature handoff is called out (Step 7) — bridge or fold together.
