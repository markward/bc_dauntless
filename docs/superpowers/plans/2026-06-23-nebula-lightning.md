# Nebula Lightning (Thunder & God-Rays) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Periodic distant lightning flashes inside a nebula that light the cloud + the player hull, with screen-space crepuscular god-rays during each flash and a delayed thunder rumble — behind a dedicated "Nebula Lightning" Modern VFX toggle.

**Architecture:** A seeded Python **flash driver** (`nebula_thunder.py`) ticks while the player is in a nebula, producing active **flashes** (`dir`, `intensity`, `color`) and scheduling delayed audio. The host loop merges each flash as a transient directional into the existing `set_lighting` path (lighting cloud + hull for free) and plays due thunder one-shots. A native **god-ray pass** (mirroring the volumetric pass) projects each flash direction to a screen anchor and radially scatters the bright HDR cloud, additively composited — only while a flash is live.

**Tech Stack:** Python 3 (driver, host loop), pytest; C++17 + OpenGL/GLSL (god-ray pass), pybind11, CMake shader embedding, CTest FrameTest; the existing `TGSoundManager` audio one-shot path.

## Global Constraints

- **No gameplay coupling.** Lightning is purely visual/audio. The "Nebula Lightning" toggle (Modern VFX, **default on**) gates it; off → the driver never spawns, zero cost.
- **Inert outside a nebula.** The driver only spawns while the player is inside a nebula; the god-ray pass and audio are no-ops with no active flash.
- **4-light budget.** The renderer caps directionals at `MAX_DIRECTIONALS = 4` (`engine/appc/lights.py:109`, `frame.h` `MaxDirectionals`). Thunder directionals are appended after truncating the scene's own directionals so the total never exceeds 4 and the sun (first entry) is never dropped.
- **Determinism.** The driver uses a seeded RNG; given the same seed + in-nebula timeline it produces identical flashes (unit-testable without GL/audio). Reset on mission swap (`reset_sdk_globals`).
- **Shader rebuild:** any `.vert`/`.frag` change needs `cmake -B build -S .` BEFORE `cmake --build build -j` (shaders embedded at configure). Build from project root, never inside `native/`.
- **host_bindings.cc / renderer changes** need the full `dauntless` rebuild (binary + module).
- **No desktop interaction on Mark's workstation** — live verification is handed off.
- **God-ray reads HDR colour → must avoid the feedback loop** (read into a scratch target / mirror the bloom read-then-additive-composite pattern; never read+write the bound HDR target).

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `engine/appc/nebula_thunder.py` | Create | `NebulaThunderDriver` — seeded flash state machine + audio scheduling. Pure logic. |
| `tests/unit/test_nebula_thunder.py` | Create | Driver unit tests (seeded, deterministic). |
| `engine/host_loop.py` | Modify | Tick driver; merge thunder directionals before `set_lighting`; play due thunder; feed god-ray descriptors; reset on swap; toggle wiring. |
| `engine/renderer.py` | Modify | `nebula_lightning_enabled()/set_…`; `set_nebula_godrays(list)`. |
| `native/src/renderer/frame.cc` | Modify | `dauntless_nebula_lightning` toggle namespace. |
| `native/src/host/host_bindings.cc` | Modify | Toggle bindings; `g_nebula_godray_pass` + `g_nebula_godrays`; `set_nebula_godrays`; render call. |
| `native/src/renderer/include/renderer/nebula_godray_pass.h` / `nebula_godray_pass.cc` | Create | Screen-space radial god-ray pass. |
| `native/src/renderer/shaders/nebula_godray.vert` / `nebula_godray.frag` | Create | Fullscreen radial-scatter shader. |
| `native/src/renderer/CMakeLists.txt`, `pipeline.cc` | Modify | Embed + construct the god-ray shader. |
| `engine/ui/configuration_panel.py`, `native/assets/ui-cef/js/configuration_panel.js` | Modify | "Nebula Lightning" config row. |
| `native/tests/renderer/frame_test.cc` | Modify | God-ray FrameTest. |

---

## Task 1: Thunder flash driver (Python, seeded)

**Files:**
- Create: `engine/appc/nebula_thunder.py`
- Test: `tests/unit/test_nebula_thunder.py`

**Interfaces:**
- Produces:
  - `class Flash` — a small object with `.dir` (unit `(x,y,z)` world), `.color` `(r,g,b)`, `.intensity` (float ≥ 0, the current envelope value).
  - `class NebulaThunderDriver`:
    - `__init__(self, seed=1337)`
    - `update(self, in_nebula: bool, dt: float, game_time: float, camera_forward=(0.0,1.0,0.0)) -> None` — advance cadence + envelopes; spawn/expire flashes; schedule audio. Does nothing (and clears flashes) when `in_nebula` is False.
    - `active_flashes(self) -> list[Flash]` — current flashes with `intensity > 0`.
    - `pop_due_audio(self, game_time: float) -> list[str]` — sound-asset names whose delayed trigger time has arrived (and removes them from the queue).
    - `reset(self) -> None` — clear flashes, audio queue, and cadence timer.
- Tunable module constants (dials): `INTERVAL=12.0`, `INTERVAL_JITTER=6.0`, `RISE=0.3`, `HOLD=0.15`, `DECAY=2.0`, `PEAK_MIN=0.7`, `PEAK_MAX=1.3`, `CONE_DEG=45.0` (direction spread around camera-forward), `AUDIO_DELAY_MIN=0.5`, `AUDIO_DELAY_MAX=2.0`, `THUNDER_SOUND="AtmosphereRumble"`, `BASE_COLOR=(0.85,0.9,1.0)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_nebula_thunder.py`:

```python
from engine.appc.nebula_thunder import NebulaThunderDriver


def _run(driver, ticks, in_nebula=True, dt=1.0/60.0, fwd=(0.0, 1.0, 0.0)):
    """Advance `ticks` frames; return total flashes ever seen (by spawn count)."""
    t = 0.0
    seen = 0
    prev = 0
    for _ in range(ticks):
        t += dt
        driver.update(in_nebula, dt, t, fwd)
        n = len(driver.active_flashes())
        if n > prev:
            seen += (n - prev)
        prev = n
    return seen


def test_no_flashes_outside_nebula():
    d = NebulaThunderDriver(seed=1)
    # 60 s outside a nebula → never spawns.
    for i in range(60 * 60):
        d.update(False, 1.0/60.0, i/60.0)
    assert d.active_flashes() == []


def test_spawns_over_time_in_nebula():
    d = NebulaThunderDriver(seed=1)
    # ~60 s inside → at the ~12s cadence, several flashes spawn.
    seen = _run(d, 60 * 60)
    assert seen >= 2


def test_flash_envelope_rises_then_decays():
    d = NebulaThunderDriver(seed=1)
    # Force a deterministic single flash and sample its intensity curve.
    f = d._spawn_flash(game_time=0.0, camera_forward=(0.0, 1.0, 0.0))
    i_rise = d._envelope(f, 0.15)     # mid-rise
    i_peak = d._envelope(f, 0.35)     # just after rise+hold start
    i_late = d._envelope(f, 2.0)      # deep in decay
    assert 0.0 < i_rise < i_peak
    assert i_late < i_peak
    assert d._envelope(f, 100.0) == 0.0   # fully decayed → gone


def test_determinism_same_seed():
    a = NebulaThunderDriver(seed=42)
    b = NebulaThunderDriver(seed=42)
    for i in range(600):
        t = i/60.0
        a.update(True, 1.0/60.0, t)
        b.update(True, 1.0/60.0, t)
    da = [(round(f.intensity, 6), tuple(round(x, 6) for x in f.dir)) for f in a.active_flashes()]
    db = [(round(f.intensity, 6), tuple(round(x, 6) for x in f.dir)) for f in b.active_flashes()]
    assert da == db


def test_audio_scheduled_and_due_after_delay():
    d = NebulaThunderDriver(seed=1)
    d._spawn_flash(game_time=10.0, camera_forward=(0.0, 1.0, 0.0))
    # Nothing due immediately at spawn time.
    assert d.pop_due_audio(10.0) == []
    # By spawn + max delay, the rumble is due exactly once.
    due = d.pop_due_audio(10.0 + 2.5)
    assert due == ["AtmosphereRumble"]
    assert d.pop_due_audio(20.0) == []   # not re-fired


def test_reset_clears_state():
    d = NebulaThunderDriver(seed=1)
    _run(d, 60 * 60)
    d.reset()
    assert d.active_flashes() == []
    assert d.pop_due_audio(1e9) == []


def test_direction_biased_toward_camera_forward():
    d = NebulaThunderDriver(seed=7)
    fwd = (0.0, 1.0, 0.0)
    dots = []
    for _ in range(50):
        f = d._spawn_flash(game_time=0.0, camera_forward=fwd)
        dx, dy, dz = f.dir
        dots.append(dx*fwd[0] + dy*fwd[1] + dz*fwd[2])
    # Most flash directions point into the forward hemisphere (dot > 0).
    assert sum(1 for x in dots if x > 0.0) >= 40
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_nebula_thunder.py -v`
Expected: FAIL — `ModuleNotFoundError: engine.appc.nebula_thunder`.

- [ ] **Step 3: Implement `engine/appc/nebula_thunder.py`**

```python
"""Nebula lightning — the thunder flash driver.

A seeded state machine: while the player is inside a nebula, it spawns
occasional distant flashes (transient directional lights biased toward the
view) with a brighten→dim envelope, and schedules a delayed thunder rumble per
flash. Pure logic — emits plain Flash objects + due-audio names; the host loop
turns flashes into directionals (cloud + hull lighting) and god-ray descriptors
and plays the audio. No GL, no audio calls here. Deterministic given the seed.
"""
import math
import random

INTERVAL = 12.0          # mean seconds between flashes
INTERVAL_JITTER = 6.0    # +/- jitter on the interval
RISE = 0.3               # envelope rise time (s)
HOLD = 0.15              # hold at peak (s)
DECAY = 2.0              # decay time (s)
PEAK_MIN = 0.7
PEAK_MAX = 1.3
CONE_DEG = 45.0          # direction spread (deg) around camera-forward
AUDIO_DELAY_MIN = 0.5
AUDIO_DELAY_MAX = 2.0
THUNDER_SOUND = "AtmosphereRumble"
BASE_COLOR = (0.85, 0.9, 1.0)   # cold-white lightning


class Flash:
    __slots__ = ("dir", "color", "peak", "born", "life", "intensity")

    def __init__(self, dir_, color, peak, born):
        self.dir = dir_           # unit (x,y,z) world
        self.color = color
        self.peak = peak
        self.born = born          # game_time at spawn
        self.life = RISE + HOLD + DECAY
        self.intensity = 0.0      # set each tick by the driver


class NebulaThunderDriver:
    def __init__(self, seed=1337):
        self._rng = random.Random(seed)
        self._flashes = []
        self._audio = []          # list of (due_time, sound_name)
        self._next_at = None      # game_time of the next spawn (lazy)

    def reset(self):
        self._flashes = []
        self._audio = []
        self._next_at = None

    # ── envelope ──────────────────────────────────────────────────────────
    def _envelope(self, flash, age):
        if age < 0.0 or age >= flash.life:
            return 0.0
        if age < RISE:
            # rise with a small secondary flicker so it reads as lightning
            base = age / RISE
            flick = 0.85 + 0.15 * math.sin(age * 60.0)
            return flash.peak * base * flick
        if age < RISE + HOLD:
            return flash.peak
        decay_age = age - RISE - HOLD
        return flash.peak * max(0.0, 1.0 - decay_age / DECAY)

    # ── spawning ──────────────────────────────────────────────────────────
    def _rand_dir_in_cone(self, forward):
        # Normalize forward; fall back to +Y.
        fx, fy, fz = forward
        flen = math.sqrt(fx*fx + fy*fy + fz*fz)
        if flen < 1e-6:
            fx, fy, fz, flen = 0.0, 1.0, 0.0, 1.0
        fx, fy, fz = fx/flen, fy/flen, fz/flen
        # Sample a direction within CONE_DEG of forward (uniform on the cap).
        cos_max = math.cos(math.radians(CONE_DEG))
        ct = 1.0 - self._rng.random() * (1.0 - cos_max)
        st = math.sqrt(max(0.0, 1.0 - ct*ct))
        phi = self._rng.random() * 2.0 * math.pi
        # Build a basis around forward.
        up = (0.0, 0.0, 1.0) if abs(fz) < 0.9 else (1.0, 0.0, 0.0)
        rx = fy*up[2] - fz*up[1]; ry = fz*up[0] - fx*up[2]; rz = fx*up[1] - fy*up[0]
        rl = math.sqrt(rx*rx + ry*ry + rz*rz) or 1.0
        rx, ry, rz = rx/rl, ry/rl, rz/rl
        ux = ry*fz - rz*fy; uy = rz*fx - rx*fz; uz = rx*fy - ry*fx
        dx = ct*fx + st*(math.cos(phi)*rx + math.sin(phi)*ux)
        dy = ct*fy + st*(math.cos(phi)*ry + math.sin(phi)*uy)
        dz = ct*fz + st*(math.cos(phi)*rz + math.sin(phi)*uz)
        return (dx, dy, dz)

    def _spawn_flash(self, game_time, camera_forward):
        peak = self._rng.uniform(PEAK_MIN, PEAK_MAX)
        d = self._rand_dir_in_cone(camera_forward)
        f = Flash(d, BASE_COLOR, peak, game_time)
        self._flashes.append(f)
        delay = self._rng.uniform(AUDIO_DELAY_MIN, AUDIO_DELAY_MAX)
        self._audio.append((game_time + delay, THUNDER_SOUND))
        return f

    # ── tick ──────────────────────────────────────────────────────────────
    def update(self, in_nebula, dt, game_time, camera_forward=(0.0, 1.0, 0.0)):
        if not in_nebula:
            # Leave the nebula → storm stops; drop transient state.
            if self._flashes:
                self._flashes = []
            self._next_at = None
            return
        if self._next_at is None:
            self._next_at = game_time + self._rng.uniform(
                INTERVAL - INTERVAL_JITTER, INTERVAL + INTERVAL_JITTER)
        if game_time >= self._next_at:
            self._spawn_flash(game_time, camera_forward)
            self._next_at = game_time + self._rng.uniform(
                INTERVAL - INTERVAL_JITTER, INTERVAL + INTERVAL_JITTER)
        # Update envelopes; expire dead flashes.
        alive = []
        for f in self._flashes:
            f.intensity = self._envelope(f, game_time - f.born)
            if f.intensity > 0.0:
                alive.append(f)
        self._flashes = alive

    def active_flashes(self):
        return list(self._flashes)

    def pop_due_audio(self, game_time):
        due = [name for (t, name) in self._audio if t <= game_time]
        self._audio = [(t, name) for (t, name) in self._audio if t > game_time]
        return due
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_nebula_thunder.py -v`
Expected: PASS (8 tests). If `test_spawns_over_time_in_nebula` is flaky for `seed=1`, it won't be — the first interval is ≤18 s and 60 s covers ≥2 spawns.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/nebula_thunder.py tests/unit/test_nebula_thunder.py
git commit -m "feat(nebula): thunder flash driver (seeded state machine + audio scheduling)"
```

---

## Task 2: "Nebula Lightning" Modern VFX toggle

**Files:** `native/src/renderer/frame.cc`, `native/src/host/host_bindings.cc`, `engine/renderer.py`, `engine/ui/configuration_panel.py`, `native/assets/ui-cef/js/configuration_panel.js`, `engine/host_loop.py` (panel construction)

**Interfaces:**
- Produces: `dauntless_nebula_lightning::enabled()/set_enabled(bool)` (C++); `_h.nebula_lightning_enabled()/_set_enabled()`; `engine.renderer.nebula_lightning_enabled()/set_nebula_lightning_enabled()`; a "Nebula Lightning" config row (default on).

This mirrors the "Volumetric Nebulae" toggle exactly (added in the volumetric project). Copy that toggle's 7 layers, renaming `volumetric_nebulae`→`nebula_lightning` and "Volumetric Nebulae"→"Nebula Lightning", default **on**.

- [ ] **Step 1: C++ namespace** — in `frame.cc`, mirror `dauntless_volumetric_nebulae` (~line 117):
```cpp
namespace dauntless_nebula_lightning {
namespace { bool g_enabled = true; }
    bool enabled() { return g_enabled; }
    void set_enabled(bool v) { g_enabled = v; }
}
```

- [ ] **Step 2: host_bindings.cc** — forward-declare alongside the other toggles (~line 133), and add the two `m.def`s next to the volumetric ones (~line 2101):
```cpp
    m.def("nebula_lightning_set_enabled",
          [](bool enabled) { dauntless_nebula_lightning::set_enabled(enabled); },
          py::arg("enabled"), "Toggle Nebula Lightning (Modern VFX). Default: on.");
    m.def("nebula_lightning_enabled",
          []() { return dauntless_nebula_lightning::enabled(); },
          "Read the Nebula Lightning toggle (Modern VFX). Default: on.");
```

- [ ] **Step 3: renderer.py** — after the volumetric wrappers:
```python
def nebula_lightning_enabled() -> bool:
    """Read the Nebula Lightning toggle (Modern VFX). Default: on."""
    return _h.nebula_lightning_enabled()


def set_nebula_lightning_enabled(enabled: bool) -> None:
    """Toggle Nebula Lightning (Modern VFX). Default: on."""
    _h.nebula_lightning_set_enabled(enabled)
```

- [ ] **Step 4: Config UI** — in `configuration_panel.py` add `nebula_lightning_on: bool = True` to the snapshot, a `set_nebula_lightning` constructor param + storage, snapshot init from `renderer.nebula_lightning_enabled()`, the `toggle:nebula_lightning` dispatch, and the focusables entry — all mirroring the volumetric rows. In `configuration_panel.js` add the `{kind:'ctrl', target:'nebula_lightning'}` focus entry and a "Nebula Lightning" `cp-row` in the Modern VFX group. In `host_loop.py` where `ConfigurationPanel(...)` is constructed, pass `nebula_lightning_on=r.nebula_lightning_enabled()` and `set_nebula_lightning=r.set_nebula_lightning_enabled`.

- [ ] **Step 5: Reconfigure + build + round-trip**

Run: `cmake -B build -S . && cmake --build build -j`
```bash
PYTHONPATH=build/python uv run python -c "import engine.renderer as r; r.set_nebula_lightning_enabled(False); print(r.nebula_lightning_enabled()); r.set_nebula_lightning_enabled(True); print(r.nebula_lightning_enabled())"
```
Expected: `False` then `True`.

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/frame.cc native/src/host/host_bindings.cc engine/renderer.py engine/ui/configuration_panel.py native/assets/ui-cef/js/configuration_panel.js engine/host_loop.py
git commit -m "feat(nebula): Nebula Lightning Modern VFX toggle"
```

---

## Task 3: Host-loop integration — flash lighting + thunder audio

**Goal:** Tick the driver, merge thunder flashes as transient directionals (lighting cloud + hull), and play due thunder one-shots. After this, **flashes work visually + audibly** even before god-rays.

**Files:** `engine/host_loop.py`
**Test:** manual (no new unit test; verified live) + existing suites unaffected.

**Interfaces:**
- Consumes: `NebulaThunderDriver` (Task 1); `r.nebula_lightning_enabled()` (Task 2); the in-nebula signal from `_nebula_tracker._inside`; `TGSoundManager` for playback; `_aggregate_lights` result at `host_loop.py:4595`.
- Produces: module global `_nebula_thunder = None` (lazy, mirroring `_nebula_tracker`); thunder directionals merged before `set_lighting`; due thunder played; driver reset in `reset_sdk_globals`.

- [ ] **Step 1: Lazy global + reset**

Near `_nebula_tracker = None` (~`host_loop.py:1912`) add `_nebula_thunder = None`. In `reset_sdk_globals` (~line 1796, beside the nebula-tracker reset) add:
```python
    if _nebula_thunder is not None:
        _nebula_thunder.reset()
```

- [ ] **Step 2: Tick the driver each sim tick**

Immediately after the `_nebula_tracker.update(...)` call (~`host_loop.py:4331`, inside `if _neb_set is not None:` and the enclosing `if not pause.is_open:`), add:
```python
                # Nebula lightning: tick the thunder driver while the player is
                # in a nebula. Visual/audio only; gated by the toggle. Lazy
                # construct (mirrors _nebula_tracker; nebula_thunder imports App
                # at module level).
                global _nebula_thunder
                if r.nebula_lightning_enabled():
                    if _nebula_thunder is None:
                        from engine.appc.nebula_thunder import NebulaThunderDriver
                        _nebula_thunder = NebulaThunderDriver()
                    player_id = id(player) if player is not None else None
                    in_neb = player_id is not None and any(
                        player_id in ships for ships in _nebula_tracker._inside.values())
                    fwd = player.GetWorldForwardTG() if player is not None else None
                    fwd_t = (fwd.x, fwd.y, fwd.z) if fwd is not None else (0.0, 1.0, 0.0)
                    _nebula_thunder.update(in_neb, TICK_DT, TICK_DT * ticks_so_far_or_gametime, fwd_t)
                    for name in _nebula_thunder.pop_due_audio(_game_time_now()):
                        try:
                            from engine.audio.tg_sound import TGSoundManager
                            TGSoundManager.instance().PlaySound(name)
                        except Exception:
                            pass
```
Use the loop's real game-time source for the `update`/`pop_due_audio` time argument (find the existing game-time variable used by the tracker / timers at this site — e.g. `App.g_kTimerManager.GetGameTime()`; do NOT invent `_game_time_now`/`ticks_so_far_or_gametime` — substitute the actual expression). `GetWorldForwardTG` is the CLAUDE.md-blessed forward accessor.

- [ ] **Step 3: Merge thunder directionals before `set_lighting`**

At `host_loop.py:4595-4596`:
```python
            ambient, directionals = _aggregate_lights(active_set)
            r.set_lighting(ambient, directionals)
```
Replace the `set_lighting` line with a merge that respects the 4-slot cap (sun/scene lights first, thunder appended):
```python
            ambient, directionals = _aggregate_lights(active_set)
            if _nebula_thunder is not None:
                flashes = _nebula_thunder.active_flashes()
                if flashes:
                    thunder = [((f.dir[0], f.dir[1], f.dir[2]),
                                (f.color[0]*f.intensity, f.color[1]*f.intensity,
                                 f.color[2]*f.intensity)) for f in flashes]
                    keep = max(0, 4 - len(thunder))
                    directionals = list(directionals)[:keep] + thunder[:4]
            r.set_lighting(ambient, directionals)
```
(`active_flashes()` is empty whenever the toggle is off — the driver is never ticked — so this is a no-op then.)

- [ ] **Step 4: Verify no regressions**

Run: `uv run pytest tests/unit/test_nebula_thunder.py tests/unit/test_nebula.py -v` (pass).
Run: `uv run python -c "import engine.host_loop"` (imports cleanly — catches NameError/indent).
Run: `bash scripts/run_tests.sh` (full suite; confirm 0 NEW failures vs the known pre-existing set).

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(nebula): drive thunder flashes into lighting + play delayed rumble"
```

---

## Task 4: God-ray pass plumbing (binding + empty pass)

**Goal:** A `set_nebula_godrays` binding + a native `NebulaGodrayPass` constructed/destroyed and called in `render_space` (gated by the toggle + an active flash) that draws **nothing** yet — proving descriptors reach C++.

**Files:** `engine/renderer.py`, `engine/host_loop.py`, `native/src/renderer/include/renderer/nebula_godray_pass.h` + `nebula_godray_pass.cc`, `native/src/renderer/CMakeLists.txt`, `native/src/host/host_bindings.cc`.

**Interfaces:**
- Produces:
  - Python `engine.renderer.set_nebula_godrays(flashes: list)` where each item is `{"dir": (x,y,z), "intensity": float, "color": (r,g,b)}`.
  - C++ `renderer::GodrayFlash { glm::vec3 dir; float intensity; glm::vec3 color; }` + `renderer::NebulaGodrayPass` with `render(const scenegraph::Camera&, Pipeline&, const std::vector<GodrayFlash>&, std::uint32_t hdr_color_tex)`, `set_enabled(bool)`.
  - binding `set_nebula_godrays(list[dict])` → `g_nebula_godrays`.

- [ ] **Step 1: Python wrapper + per-frame feed**

In `engine/renderer.py`:
```python
def set_nebula_godrays(flashes: list) -> None:
    """Active lightning flashes for the god-ray pass. Each: {"dir": (x,y,z),
    "intensity": float, "color": (r,g,b)}. Empty list = no god-rays."""
    _h.set_nebula_godrays(flashes)
```
In `host_loop.py`, in the per-frame render block (right after the `r.set_lighting(...)` merge from Task 3 / near `r.set_nebulae(...)`), add:
```python
            godrays = []
            if _nebula_thunder is not None and not _warp_streaking:
                godrays = [{"dir": f.dir, "intensity": f.intensity, "color": f.color}
                           for f in _nebula_thunder.active_flashes()]
            r.set_nebula_godrays(godrays)
```

- [ ] **Step 2: Create `nebula_godray_pass.h`**

```cpp
// native/src/renderer/include/renderer/nebula_godray_pass.h
#pragma once
#include <glm/glm.hpp>
#include <vector>

namespace scenegraph { struct Camera; }
namespace renderer {

class Pipeline;

/// One active lightning flash for the screen-space god-ray pass.
struct GodrayFlash {
    glm::vec3 dir       = glm::vec3(0.0f, 1.0f, 0.0f);  // world dir light comes FROM
    float     intensity = 0.0f;
    glm::vec3 color     = glm::vec3(1.0f);
};

/// Screen-space radial scatter ("crepuscular rays"). For each flash, projects
/// `dir` to a screen anchor and radially smears the bright HDR colour outward
/// from it, additively composited. Early-outs on empty/disabled.
class NebulaGodrayPass {
public:
    NebulaGodrayPass();
    ~NebulaGodrayPass();
    NebulaGodrayPass(const NebulaGodrayPass&) = delete;
    NebulaGodrayPass& operator=(const NebulaGodrayPass&) = delete;

    void render(const scenegraph::Camera& camera,
                Pipeline& pipeline,
                const std::vector<GodrayFlash>& flashes,
                std::uint32_t hdr_color_tex);

    void set_enabled(bool e) { enabled_ = e; }
    bool enabled() const { return enabled_; }

private:
    bool enabled_ = true;
    bool initialized_ = false;
    unsigned int vao_ = 0;          // empty VAO (fullscreen triangle)
    void initialize_gl();
};

}  // namespace renderer
```

- [ ] **Step 3: Create `nebula_godray_pass.cc` (stub)**

```cpp
// native/src/renderer/nebula_godray_pass.cc
#include "renderer/nebula_godray_pass.h"
#include "renderer/pipeline.h"
#include <scenegraph/camera.h>
#include <glad/glad.h>

namespace renderer {

NebulaGodrayPass::NebulaGodrayPass() = default;
NebulaGodrayPass::~NebulaGodrayPass() {
    if (vao_) glDeleteVertexArrays(1, &vao_);
}

void NebulaGodrayPass::initialize_gl() {
    glGenVertexArrays(1, &vao_);
    initialized_ = true;
}

void NebulaGodrayPass::render(const scenegraph::Camera& camera,
                              Pipeline& pipeline,
                              const std::vector<GodrayFlash>& flashes,
                              std::uint32_t hdr_color_tex) {
    (void)camera; (void)pipeline; (void)hdr_color_tex;
    if (!enabled_ || flashes.empty()) return;
    if (!initialized_) initialize_gl();
    // Task 5 draws the radial scatter here.
}

}  // namespace renderer
```

- [ ] **Step 4: CMake source** — add `nebula_godray_pass.cc` to the renderer `add_library` list (next to `nebula_volumetric_pass.cc`). (No shader yet.)

- [ ] **Step 5: host_bindings.cc wiring**

Include `<renderer/nebula_godray_pass.h>`; add globals near the volumetric pass:
```cpp
std::vector<renderer::GodrayFlash> g_nebula_godrays;
std::unique_ptr<renderer::NebulaGodrayPass> g_nebula_godray_pass;
```
Construct in `init`, reset in `shutdown` (beside `g_nebula_volumetric_pass`). Binding (near `set_nebulae`):
```cpp
    m.def("set_nebula_godrays",
          [](const std::vector<py::dict>& descs) {
              g_nebula_godrays.clear();
              g_nebula_godrays.reserve(descs.size());
              for (const auto& d : descs) {
                  renderer::GodrayFlash g;
                  auto dir = d["dir"].cast<std::tuple<float,float,float>>();
                  g.dir = glm::vec3(std::get<0>(dir), std::get<1>(dir), std::get<2>(dir));
                  g.intensity = d["intensity"].cast<float>();
                  auto c = d["color"].cast<std::tuple<float,float,float>>();
                  g.color = glm::vec3(std::get<0>(c), std::get<1>(c), std::get<2>(c));
                  g_nebula_godrays.push_back(g);
              }
          },
          py::arg("flashes"), "Set active lightning flashes for the god-ray pass.");
```
Render call in `render_space`, after the volumetric nebula pass, gated:
```cpp
        if (!for_viewscreen && dauntless_nebula_lightning::enabled()
            && g_nebula_godray_pass && !g_nebula_godrays.empty())
            g_nebula_godray_pass->render(cam, *g_pipeline, g_nebula_godrays,
                                         g_hdr_target->color_texture());
```
(Forward-declare `dauntless_nebula_lightning::enabled()` if not already.)

- [ ] **Step 6: Reconfigure + build + smoke**

Run: `cmake -B build -S . && cmake --build build -j` (clean).
```bash
PYTHONPATH=build/python uv run python -c "import build.python._dauntless_host as h; print(hasattr(h,'set_nebula_godrays'))"
```
Expected: `True` (adapt module path to the repo's convention if needed).

- [ ] **Step 7: Commit**

```bash
git add engine/renderer.py engine/host_loop.py native/src/renderer/include/renderer/nebula_godray_pass.h native/src/renderer/nebula_godray_pass.cc native/src/renderer/CMakeLists.txt native/src/host/host_bindings.cc
git commit -m "feat(nebula): god-ray pass plumbing + descriptors (empty pass)"
```

---

## Task 5: God-ray shader (screen-space radial scatter)

**Goal:** The actual crepuscular shafts — radially smear the bright HDR cloud outward from each flash's projected screen anchor, additively composited, scaled by flash intensity.

**Files:** `native/src/renderer/shaders/nebula_godray.vert` + `.frag`, `CMakeLists.txt`, `pipeline.cc` (construct the shader + accessor), `nebula_godray_pass.cc` (draw), `native/tests/renderer/frame_test.cc`.

**Approach:** a fullscreen pass. The pass computes each flash's screen anchor (project a far point along `dir` through the camera viewproj) and, when the anchor is on-screen, draws the radial scatter additively. For multiple flashes, sum (rare; usually 1). Reads the HDR colour as the "bright source" sampled along the radial march.

> **Live-tuning note:** start exposure/decay/sample-count strong, verify at Vesuvi4, dial. `u_exposure`, `u_decay`, `u_weight`, `u_samples` are the dials.

- [ ] **Step 1: Add the FrameTest (failing)**

In `frame_test.cc`, add `NebulaGodrayStreaksFromAnchor`: a scratch HDR colour texture with a bright spot near one edge, a single `GodrayFlash` whose projected anchor lands at that spot, render; assert the centre-ward pixels between the spot and screen-centre are brighter than a no-flash control (the streak), and that an **empty flash list** leaves the target byte-identical. Follow the volumetric/sun FrameTest pattern. If projecting a controlled anchor is awkward in the harness, drive the anchor directly via a test-only path or assert the radial accumulation on a known anchor and document the projection for live — do NOT fake it.

- [ ] **Step 2: Run to verify it fails** — `ctest --test-dir build -R FrameTest -V` → new test FAILs.

- [ ] **Step 3: `nebula_godray.vert`** (fullscreen triangle)

```glsl
#version 330 core
out vec2 v_uv;
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    v_uv = p;
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
```

- [ ] **Step 4: `nebula_godray.frag`** (radial scatter; GPU Gems crepuscular formulation)

```glsl
#version 330 core
in vec2 v_uv;
out vec4 frag;

uniform sampler2D u_scene;     // HDR colour (read-only; composited additively by blend)
uniform vec2  u_anchor;        // light screen pos in [0,1] (NDC*0.5+0.5)
uniform float u_on_screen;     // 1 if anchor usable, else 0
uniform vec3  u_color;
uniform float u_intensity;
// dials
uniform int   u_samples;       // default 48
uniform float u_decay;         // default 0.96
uniform float u_weight;        // default 0.5
uniform float u_exposure;      // default 0.25

void main() {
    if (u_on_screen < 0.5 || u_intensity <= 0.0) { frag = vec4(0.0); return; }
    vec2 delta = (v_uv - u_anchor) / float(u_samples);
    vec2 uv = v_uv;
    float illum = 1.0;
    vec3 accum = vec3(0.0);
    for (int i = 0; i < u_samples; ++i) {
        uv -= delta;                       // step toward the anchor
        vec3 s = texture(u_scene, uv).rgb; // bright flash-lit cloud
        accum += s * (illum * u_weight);
        illum *= u_decay;
    }
    // Tint by the flash colour, scale by exposure * intensity. Premultiplied
    // additive (alpha unused; blend is GL_ONE, GL_ONE).
    frag = vec4(accum * u_color * (u_exposure * u_intensity), 1.0);
}
```

- [ ] **Step 5: Register shader** — `embed_shader(SHADER_NEBULA_GODRAY_VS shaders/nebula_godray.vert nebula_godray_vs)` + `_FS` in `CMakeLists.txt`; `#include "embedded_nebula_godray_*.h"` + a `nebula_godray_` Shader member + accessor in `pipeline.cc` (mirror `nebula_volumetric_`).

- [ ] **Step 6: Implement the draw in `nebula_godray_pass.cc`**

In `render`: ensure the empty VAO; bind the god-ray shader; bind `hdr_color_tex` to unit 0 → `u_scene`; enable additive blend `glBlendFunc(GL_ONE, GL_ONE)`, depth test/write OFF, cull off. For each flash: project a far world point along `dir` to clip via `camera`'s viewproj → screen anchor `[0,1]`; set `u_on_screen` (1 if `w>0` and anchor within `[0,1]` padded), `u_anchor`, `u_color`, `u_intensity`, and the dial defaults (`u_samples=48`, `u_decay=0.96f`, `u_weight=0.5f`, `u_exposure=0.25f`); `glDrawArrays(GL_TRIANGLES,0,3)`. Restore GL state (blend off, depth test on, depth mask on, cull on) at the end. **Reads `hdr_color_tex` while writing the SAME HDR target via additive blend** — this is the bloom-upsample pattern (read texture + additive blend is safe; you are not sampling the exact texel you write in a feedback-dependent way, and the radial taps are offset). If GL flags a feedback hazard, render into a scratch target and composite (mirror the volumetric scratch) — note which you did.

- [ ] **Step 7: Reconfigure + build** — `cmake -B build -S . && cmake --build build -j` (clean; `cmake -B` required — shaders changed).

- [ ] **Step 8: Run the FrameTest** — `ctest --test-dir build -R FrameTest -V` → new test passes; report 0 new failures vs the pre-existing set.

- [ ] **Step 9: Commit**

```bash
git add native/src/renderer/shaders/nebula_godray.vert native/src/renderer/shaders/nebula_godray.frag native/src/renderer/CMakeLists.txt native/src/renderer/pipeline.cc native/src/renderer/nebula_godray_pass.cc native/tests/renderer/frame_test.cc
git commit -m "feat(nebula): god-ray radial scatter shader"
```

---

## Task 6: Live verification + tuning

**Files:** none (verification). Hand off to Mark — no desktop interaction on his workstation.

- [ ] **Step 1:** `cmake -B build -S . && cmake --build build -j` (clean).
- [ ] **Step 2:** Checklist for Mark (load Vesuvi4 / Multi5 via `--developer`, sit in the nebula):
  1. Occasional flashes light the **cloud** and the **player hull** (brighten→dim over a couple seconds).
  2. **Shafts** fan out from flashes that are roughly in front of you.
  3. A **thunder rumble** follows each flash a beat later.
  4. Toggle **Nebula Lightning** off → flashes/shafts/rumble stop; cloud still renders. On → back.
  5. Frame-rate holds (god-rays cost only during a flash); no stutter on a flash.
  6. Flashes don't break the scene lighting (sun still present — slot reservation works).
  7. Outside a nebula / no nebula → nothing fires.
- [ ] **Step 3:** Apply tuning (driver dials: cadence/peak/decay/cone/audio-delay; shader dials: `u_exposure`/`u_decay`/`u_weight`/`u_samples`), rebuilding with `cmake -B build -S .` after shader edits. Replace the placeholder `AtmosphereRumble` with a better thunder asset if sourced. Commit:
```bash
git add engine/appc/nebula_thunder.py native/src/renderer/
git commit -m "tune(nebula): lightning cadence + god-ray dials per live verification"
```

---

## Self-Review

**Spec coverage:**
- §5 flash driver (cadence, envelope, direction bias, audio scheduling) → Task 1 ✓
- §5 light injection + 4-slot reservation → Task 3 ✓
- §6 god-ray screen-space radial scatter → Tasks 4 (plumbing) + 5 (shader) ✓
- §7 delayed thunder audio (queue + reuse AtmosphereRumble) → Task 1 (schedule) + Task 3 (play) ✓
- §8 dedicated Nebula Lightning toggle (default on) → Task 2 ✓
- §8 integration (tick, merge, drain, reset) → Task 3 + Task 4 ✓
- §8 testing (driver pytest, god-ray FrameTest, live) → Tasks 1,5,6 ✓
- Global: no gameplay coupling (driver is visual/audio only); inert outside nebula / toggle off (driver not ticked, passes early-out); deterministic (seeded) ✓

**Placeholder scan:** No TBD/TODO. The two "substitute the real expression" notes (Task 3 game-time source; Task 5 anchor-projection in the harness) are explicit research-then-implement tied to named sites, not vague gaps. The driver + shader carry complete code; shader constants are live-tuning dials.

**Type consistency:** `Flash{.dir,.color,.intensity}` (Task 1) consumed in Task 3 (directionals) and Task 4 (godray descriptors); `NebulaThunderDriver.update/active_flashes/pop_due_audio/reset` consistent across Tasks 1,3,4; `set_nebula_godrays` dict shape `{dir,intensity,color}` (Task 4) matches `GodrayFlash{dir,intensity,color}` (Task 4) and the Task 5 draw; `nebula_lightning_enabled` naming consistent across C++/binding/Python/JS.

**Known risks flagged in-plan:** the HDR read-while-additive-blend in Task 5 (bloom pattern; scratch fallback noted); the game-time + forward-vector substitutions in Task 3; the thunder asset is a reused placeholder (`AtmosphereRumble`).
