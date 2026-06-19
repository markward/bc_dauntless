# Comm-viewscreen Fidelity Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the authentic analog static/"snow" overlay on comm hails, scaled by the SDK's `fMinStatic`/`fMaxStatic`, plus a short ViewOn/ViewOff brightness-fade transition — driven entirely by `MissionLib.ViewscreenOn`/`ViewscreenOff`.

**Architecture:** Python records the SDK's static state on `ViewScreenObject` and, per frame, resolves the noise texture paths + computes a random flicker intensity and a feed-change brightness ramp, pushing them to the renderer. Native composites the noise over the viewscreen HDR target with an alpha-blended fullscreen quad (`out = mix(feed, noise, intensity)`) and multiplies the viewscreen sample by the brightness in `bridge.frag`.

**Tech Stack:** Python 3 (engine + pytest), C++17 OpenGL renderer (pybind11 host module, GLSL 330, gtest renderer_tests).

## Global Constraints

- **One build tree:** `cmake -B build -S . && cmake --build build -j` → `build/dauntless`. Never build from inside `native/`. (CLAUDE.md)
- **Shader edits need reconfigure:** any `.vert`/`.frag` change (new files or edits) requires `cmake -B build -S .` BEFORE `cmake --build build -j` — `--build` alone does not re-embed shaders. (memory `feedback_shader_rebuild`)
- **host_bindings.cc → full rebuild:** it compiles into both `build/dauntless` and the `_dauntless_host` module; rebuild the `dauntless` target. (memory `feedback_host_bindings_build_target`)
- **V-flip:** the viewscreen RTT is GL bottom-left origin; the existing single `u_flip_v` at the bridge-mesh sample handles the feed. Do NOT add a second flip. Noise is isotropic random so its orientation is irrelevant.
- **Game units / right-handed conventions** per CLAUDE.md.
- **Tests:** full Python suite via `scripts/run_tests.sh`. Native: `cmake --build build -j --target renderer_tests` then run the binary.
- **SDK-faithful** (memory `feedback_sdk_drives_everything`): per-mission behaviour (on/off, min, max) flows from the SDK calls; only the fixed `"View Screen Static"` → 3 noise tga paths is a constant, owned in Python with an SDK citation.
- **Production path identical** when static is off and brightness is 1.0.

---

### Task 1: `ViewScreenObject` records SDK static state

**Files:**
- Modify: `engine/appc/bridge_set.py:74-105` (the `ViewScreenObject` class)
- Test: `tests/unit/test_bridge_set_stubs.py` (add tests; the file already covers `ViewScreenObject` no-op behaviour around line 54)

**Interfaces:**
- Produces: `ViewScreenObject` instance attributes `_static_icon_group: str|None`, `_static_on: int`, `_static_min: float`, `_static_max: float`; methods `SetStaticTextureIconGroup(name)`, `SetStaticIsOn(on)`, `IsStaticOn() -> int`, `SetStaticVariation(fmin, fmax)`. `SetMenu`/`MenuUp`/etc. remain `_LoudStub` no-ops.

- [ ] **Step 1: Write failing tests**

Add to `tests/unit/test_bridge_set_stubs.py`:

```python
def test_viewscreen_records_static_state():
    from engine.appc.bridge_set import ViewScreenObject
    vs = ViewScreenObject("viewscreen.nif")
    # defaults: static off, no group, zero variation
    assert vs.IsStaticOn() == 0
    assert vs._static_icon_group is None
    assert vs._static_min == 0.0
    assert vs._static_max == 0.0
    # SDK drives state on
    vs.SetStaticTextureIconGroup("View Screen Static")
    vs.SetStaticIsOn(1)
    vs.SetStaticVariation(0.8, 1)
    assert vs._static_icon_group == "View Screen Static"
    assert vs.IsStaticOn() == 1
    assert vs._static_min == 0.8
    assert vs._static_max == 1.0


def test_viewscreen_static_off_clears():
    from engine.appc.bridge_set import ViewScreenObject
    vs = ViewScreenObject("viewscreen.nif")
    vs.SetStaticIsOn(1)
    vs.SetStaticIsOn(0)
    assert vs.IsStaticOn() == 0


def test_viewscreen_menu_methods_still_noop():
    # Deferred menu surface must keep falling through _LoudStub (no crash, None).
    from engine.appc.bridge_set import ViewScreenObject
    vs = ViewScreenObject("viewscreen.nif")
    assert vs.SetMenu(object()) is None
    assert vs.MenuUp() is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_bridge_set_stubs.py -q`
Expected: FAIL — `IsStaticOn()` returns the `_LoudStub` `None`/lambda, `_static_min` AttributeError.

- [ ] **Step 3: Implement**

In `engine/appc/bridge_set.py`, extend `ViewScreenObject.__init__` and add the four methods (the class stays a `_LoudStub` subclass so menu methods still no-op):

```python
    def __init__(self, nif):
        self.nif = nif
        self.render_instance = None    # host fills this in
        self._remote_cam = None
        self._is_on = 0
        # SDK static/"snow" overlay state (MissionLib.ViewscreenOn drives these
        # when fMaxStatic > 0; ViewscreenOff calls SetStaticIsOn(0)). Recorded
        # here and consumed by host_loop Step 5c. Menu methods stay _LoudStub.
        self._static_icon_group = None
        self._static_on = 0
        self._static_min = 0.0
        self._static_max = 0.0
```

Add after `IsOn` (keep the existing `GetRemoteCam`/`SetRemoteCam`/`SetIsOn`/`IsOn`):

```python
    def SetStaticTextureIconGroup(self, name):
        self._static_icon_group = name

    def SetStaticIsOn(self, on):
        self._static_on = on

    def IsStaticOn(self):
        return self._static_on

    def SetStaticVariation(self, fmin, fmax):
        self._static_min = float(fmin)
        self._static_max = float(fmax)
```

Also update the class docstring: drop `IsStaticOn` from the list of methods that "falls through `_LoudStub`" (it's now real).

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_bridge_set_stubs.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/bridge_set.py tests/unit/test_bridge_set_stubs.py
git commit -m "feat(viewscreen): record SDK static state on ViewScreenObject"
```

---

### Task 2: Icon-group → noise texture paths + intensity helper

**Files:**
- Create: `engine/appc/viewscreen_static.py`
- Test: `tests/unit/test_viewscreen_static.py`

**Interfaces:**
- Produces:
  - `static_texture_paths(icon_group: str) -> list[str]` — absolute paths to the noise tgas for the named group; `[]` for unknown groups.
  - `static_intensity(fmin: float, fmax: float, rng=random.random) -> float` — `clamp(fmin + (fmax-fmin)*rng(), 0.0, 1.0)`.

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_viewscreen_static.py`:

```python
import os
from engine.appc import viewscreen_static as vss


def test_paths_for_view_screen_static():
    paths = vss.static_texture_paths("View Screen Static")
    assert len(paths) == 3
    assert [os.path.basename(p) for p in paths] == [
        "Noise1.tga", "Noise2.tga", "Noise3.tga"]
    for p in paths:
        assert os.path.isabs(p)
        assert os.path.normpath("data/Textures/Effects") in os.path.normpath(p)


def test_paths_for_unknown_group_empty():
    assert vss.static_texture_paths("Nonexistent Group") == []
    assert vss.static_texture_paths(None) == []


def test_intensity_lerps_and_clamps():
    # midpoint
    assert vss.static_intensity(0.0, 1.0, rng=lambda: 0.5) == 0.5
    # min when rng=0
    assert vss.static_intensity(0.2, 0.6, rng=lambda: 0.0) == 0.2
    # max when rng=1
    assert vss.static_intensity(0.2, 0.6, rng=lambda: 1.0) == 0.6
    # E5M4 (5,5) clamps to 1.0
    assert vss.static_intensity(5.0, 5.0, rng=lambda: 0.5) == 1.0
    # never negative
    assert vss.static_intensity(0.0, 0.0, rng=lambda: 0.5) == 0.0
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_viewscreen_static.py -q`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

Create `engine/appc/viewscreen_static.py`:

```python
"""Viewscreen static/"snow" overlay support (Python side).

The SDK's `"View Screen Static"` icon group maps, via
`sdk/Build/scripts/Tactical/EffectTextures.py:262` (`LoadStatic`), to three
noise textures under the game data tree:

    data/Textures/Effects/Noise1.tga
    data/Textures/Effects/Noise2.tga
    data/Textures/Effects/Noise3.tga

Our `g_kIconManager` is not built, so this module owns that fixed mapping (and
cites its SDK source) while everything that varies per mission — on/off and the
fMin/fMax intensity range — stays driven by the SDK's SetStaticIsOn /
SetStaticVariation calls. If the icon manager is ever implemented, this constant
is the single thing to replace.
"""
import random
from pathlib import Path

# bridge_set.py-style root resolution: this file is engine/appc/ -> root is two
# parents up, then "game".
_GAME_ROOT = Path(__file__).resolve().parent.parent.parent / "game"

# icon-group name -> ordered list of texture file names (SDK: EffectTextures.LoadStatic)
_STATIC_TEXTURE_FILES = {
    "View Screen Static": ["Noise1.tga", "Noise2.tga", "Noise3.tga"],
}


def static_texture_paths(icon_group):
    """Absolute paths to the noise frames for `icon_group`, or [] if unknown."""
    files = _STATIC_TEXTURE_FILES.get(icon_group)
    if not files:
        return []
    base = _GAME_ROOT / "data" / "Textures" / "Effects"
    return [str(base / f) for f in files]


def static_intensity(fmin, fmax, rng=random.random):
    """Per-frame static intensity: a random flicker in [fmin, fmax], clamped to
    [0, 1] (so the SDK's E5M4 (5,5) reads as full snow). `rng` returns a float
    in [0, 1); injectable for deterministic tests."""
    value = float(fmin) + (float(fmax) - float(fmin)) * rng()
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_viewscreen_static.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/viewscreen_static.py tests/unit/test_viewscreen_static.py
git commit -m "feat(viewscreen): static texture-path + intensity helpers"
```

---

### Task 3: Viewscreen brightness ramp (ViewOn/ViewOff fade)

**Files:**
- Modify: `engine/host_loop.py` (add a small class near the other viewscreen helpers, ~line 2530 after `_viewscreen_feed_on`)
- Test: `tests/unit/test_viewscreen_brightness_ramp.py`

**Interfaces:**
- Produces: `class ViewscreenBrightnessRamp` in `engine.host_loop` with:
  - `DURATION_S = 0.3` (class attr)
  - `update(self, signature, dt) -> float` — when `signature` differs from the previous call, restart the ramp at 0; advance `elapsed += dt`; return `clamp(elapsed / DURATION_S, 0.0, 1.0)`.
- Consumes: nothing.

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_viewscreen_brightness_ramp.py`:

```python
from engine.host_loop import ViewscreenBrightnessRamp


def test_ramp_fades_in_from_zero_over_duration():
    r = ViewscreenBrightnessRamp()
    # first call establishes the signature and starts the ramp at ~0
    b0 = r.update(("comm", 7), 0.0)
    assert b0 == 0.0
    # halfway through DURATION_S -> ~0.5
    b1 = r.update(("comm", 7), ViewscreenBrightnessRamp.DURATION_S / 2)
    assert abs(b1 - 0.5) < 1e-6
    # past the end -> clamped to 1.0
    b2 = r.update(("comm", 7), ViewscreenBrightnessRamp.DURATION_S)
    assert b2 == 1.0
    # stays settled at 1.0
    assert r.update(("comm", 7), 1.0) == 1.0


def test_ramp_resets_on_signature_change():
    r = ViewscreenBrightnessRamp()
    r.update(("comm", 7), ViewscreenBrightnessRamp.DURATION_S)  # settle at 1.0
    # ViewscreenOff -> forward: signature changes, fade restarts
    b = r.update(("forward",), 0.0)
    assert b == 0.0
    b = r.update(("forward",), ViewscreenBrightnessRamp.DURATION_S / 2)
    assert abs(b - 0.5) < 1e-6
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_viewscreen_brightness_ramp.py -q`
Expected: FAIL — `ViewscreenBrightnessRamp` not defined.

- [ ] **Step 3: Implement**

In `engine/host_loop.py`, add after `_viewscreen_feed_on` (~line 2535):

```python
class ViewscreenBrightnessRamp:
    """Brightness fade-in that accompanies the ViewOn/ViewOff sounds. The
    viewscreen feed has a "signature" — one of ('off',), ('forward',) or
    ('comm', set_id). Whenever the signature changes (comm appears on
    ViewscreenOn, or reverts to forward on ViewscreenOff), the brightness
    restarts at 0 and ramps linearly to 1 over DURATION_S. The sounds already
    fire via TGSoundAction; this is the matching visual."""

    DURATION_S = 0.3

    def __init__(self):
        self._sig = None
        self._elapsed = 0.0

    def update(self, signature, dt):
        if signature != self._sig:
            self._sig = signature
            self._elapsed = 0.0
        else:
            self._elapsed += dt
        b = self._elapsed / self.DURATION_S
        if b < 0.0:
            return 0.0
        if b > 1.0:
            return 1.0
        return b
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_viewscreen_brightness_ramp.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/unit/test_viewscreen_brightness_ramp.py
git commit -m "feat(viewscreen): brightness ramp for ViewOn/ViewOff fade"
```

---

### Task 4: renderer.py wrappers for static + brightness

**Files:**
- Modify: `engine/renderer.py:360-368` (after `clear_viewscreen_comm_source`)
- Test: `tests/unit/test_renderer_viewscreen_wrappers.py`

**Interfaces:**
- Produces (thin passthroughs to `_h`):
  - `set_viewscreen_static_source(paths: list[str]) -> None`
  - `set_viewscreen_static(on: bool, intensity: float) -> None`
  - `set_viewscreen_brightness(b: float) -> None`
- Consumes: the native bindings of the same names (Tasks 6 & 7). At Python-test time `_h` is monkeypatched.

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_renderer_viewscreen_wrappers.py`:

```python
import engine.renderer as renderer


def test_viewscreen_wrappers_passthrough(monkeypatch):
    calls = {}

    class FakeH:
        def set_viewscreen_static_source(self, paths):
            calls["source"] = paths
        def set_viewscreen_static(self, on, intensity):
            calls["static"] = (on, intensity)
        def set_viewscreen_brightness(self, b):
            calls["brightness"] = b

    monkeypatch.setattr(renderer, "_h", FakeH())
    renderer.set_viewscreen_static_source(["a.tga", "b.tga"])
    renderer.set_viewscreen_static(True, 0.7)
    renderer.set_viewscreen_brightness(0.5)
    assert calls["source"] == ["a.tga", "b.tga"]
    assert calls["static"] == (True, 0.7)
    assert calls["brightness"] == 0.5
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_renderer_viewscreen_wrappers.py -q`
Expected: FAIL — wrapper functions not defined (AttributeError).

- [ ] **Step 3: Implement**

In `engine/renderer.py`, add after `clear_viewscreen_comm_source` (line 368):

```python
def set_viewscreen_static_source(paths) -> None:
    """Register the noise texture frames (absolute paths) for the viewscreen
    static overlay. Idempotent on the native side (cached by path)."""
    _h.set_viewscreen_static_source(paths)


def set_viewscreen_static(on, intensity) -> None:
    """Enable/disable the viewscreen static overlay and set this frame's
    intensity (0..1). Composited over the comm/forward feed in the RTT."""
    _h.set_viewscreen_static(on, intensity)


def set_viewscreen_brightness(b) -> None:
    """Multiplier (0..1) applied to the viewscreen content for the
    ViewOn/ViewOff fade. 1.0 = full brightness (no fade)."""
    _h.set_viewscreen_brightness(b)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_renderer_viewscreen_wrappers.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/renderer.py tests/unit/test_renderer_viewscreen_wrappers.py
git commit -m "feat(viewscreen): renderer.py wrappers for static + brightness"
```

---

### Task 5: host_loop Step 5c — drive static + brightness from SDK state

**Files:**
- Modify: `engine/host_loop.py:3614-3646` (Step 5c viewscreen block)
- Test: `tests/unit/test_host_loop_viewscreen_drive.py`

This task wires Tasks 1–4 into the per-frame loop. Because the real Step 5c block is deeply embedded in the gameloop, factor the new logic into a pure, testable function and call it from Step 5c.

**Interfaces:**
- Produces: `drive_viewscreen_static_and_brightness(r, controller, ramp, dt, *, intensity_fn=...) -> None` in `engine.host_loop`. It:
  1. Reads `vs = controller.viewscreen_obj`.
  2. Computes the feed signature: `('off',)` if `vs is None or not vs.IsOn()`; else `('comm', set_id)` if `_active_comm_feed(controller)` is not None; else `('forward',)`.
  3. `r.set_viewscreen_brightness(ramp.update(signature, dt))`.
  4. If `vs` and `vs.IsStaticOn()` and `getattr(vs, "_static_max", 0) > 0`:
     - resolve paths via `viewscreen_static.static_texture_paths(vs._static_icon_group)`; if paths differ from `controller._vs_static_paths_sent`, call `r.set_viewscreen_static_source(paths)` and store them.
     - `r.set_viewscreen_static(True, intensity_fn(vs._static_min, vs._static_max))`.
     - else `r.set_viewscreen_static(False, 0.0)`.
- Consumes: `ViewscreenBrightnessRamp` (Task 3), `viewscreen_static` (Task 2), `_active_comm_feed` (existing).

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_host_loop_viewscreen_drive.py`:

```python
import types
from engine.host_loop import (
    drive_viewscreen_static_and_brightness, ViewscreenBrightnessRamp)


class FakeRenderer:
    def __init__(self):
        self.brightness = None
        self.static = None
        self.source = None
    def set_viewscreen_brightness(self, b): self.brightness = b
    def set_viewscreen_static(self, on, intensity): self.static = (on, intensity)
    def set_viewscreen_static_source(self, paths): self.source = list(paths)


class FakeVS:
    def __init__(self, on=1, static_on=0, fmin=0.0, fmax=0.0,
                 group="View Screen Static"):
        self._on = on
        self._static_on = static_on
        self._static_min = fmin
        self._static_max = fmax
        self._static_icon_group = group
    def IsOn(self): return self._on
    def IsStaticOn(self): return self._static_on


def _controller(vs):
    c = types.SimpleNamespace()
    c.viewscreen_obj = vs
    c.comm_set_ids = {}
    c.comm_instances_by_set = {}
    return c


def test_static_off_sets_false_and_brightness():
    r = FakeRenderer()
    vs = FakeVS(on=1, static_on=0)
    drive_viewscreen_static_and_brightness(
        r, _controller(vs), ViewscreenBrightnessRamp(), 0.0,
        intensity_fn=lambda a, b: 0.5)
    assert r.static == (False, 0.0)
    assert r.brightness == 0.0   # forward feed, ramp just started


def test_static_on_resolves_paths_and_intensity():
    r = FakeRenderer()
    vs = FakeVS(on=1, static_on=1, fmin=0.8, fmax=1.0)
    drive_viewscreen_static_and_brightness(
        r, _controller(vs), ViewscreenBrightnessRamp(), 0.0,
        intensity_fn=lambda a, b: (a + b) / 2)
    assert r.static == (True, 0.9)
    assert r.source is not None and len(r.source) == 3   # noise frames sent


def test_static_max_zero_stays_off():
    r = FakeRenderer()
    vs = FakeVS(on=1, static_on=1, fmin=0.0, fmax=0.0)
    drive_viewscreen_static_and_brightness(
        r, _controller(vs), ViewscreenBrightnessRamp(), 0.0,
        intensity_fn=lambda a, b: 0.5)
    assert r.static == (False, 0.0)


def test_screen_off_signature_is_off():
    r = FakeRenderer()
    ramp = ViewscreenBrightnessRamp()
    vs = FakeVS(on=0)
    drive_viewscreen_static_and_brightness(
        r, _controller(vs), ramp, 0.0, intensity_fn=lambda a, b: 0.5)
    # off signature established; advancing keeps the same signature ramping up
    drive_viewscreen_static_and_brightness(
        r, _controller(vs), ramp, ViewscreenBrightnessRamp.DURATION_S,
        intensity_fn=lambda a, b: 0.5)
    assert r.brightness == 1.0
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_host_loop_viewscreen_drive.py -q`
Expected: FAIL — `drive_viewscreen_static_and_brightness` not defined.

- [ ] **Step 3: Implement the function**

In `engine/host_loop.py`, add near the other viewscreen helpers (after `_comm_feed_view`, ~line 2616). Import the helper at the top of the module if not present (`from engine.appc import viewscreen_static as _vss`):

```python
def drive_viewscreen_static_and_brightness(r, controller, ramp, dt,
                                           *, intensity_fn=_vss.static_intensity):
    """Per-frame: push the static overlay + ViewOn/ViewOff brightness fade to
    the renderer from the SDK-driven ViewScreenObject state. Pure w.r.t. the
    renderer/controller it's given, so it's unit-tested with fakes."""
    vs = getattr(controller, "viewscreen_obj", None)

    # Feed signature for the brightness ramp.
    if vs is None or not vs.IsOn():
        signature = ("off",)
    else:
        feed = _active_comm_feed(controller)
        signature = ("comm", feed[0]) if feed is not None else ("forward",)
    r.set_viewscreen_brightness(ramp.update(signature, dt))

    # Static overlay (only when the SDK turned it on with a positive range).
    if (vs is not None and vs.IsStaticOn()
            and getattr(vs, "_static_max", 0.0) > 0.0):
        paths = _vss.static_texture_paths(getattr(vs, "_static_icon_group", None))
        if paths and paths != getattr(controller, "_vs_static_paths_sent", None):
            r.set_viewscreen_static_source(paths)
            controller._vs_static_paths_sent = paths
        intensity = intensity_fn(getattr(vs, "_static_min", 0.0),
                                 getattr(vs, "_static_max", 0.0))
        r.set_viewscreen_static(True, intensity)
    else:
        r.set_viewscreen_static(False, 0.0)
```

- [ ] **Step 4: Wire it into Step 5c**

In `engine/host_loop.py` Step 5c (~line 3646, right after the `else: r.clear_viewscreen_comm_source()`), add the call. The ramp lives on the controller (lazily created):

```python
            else:
                r.clear_viewscreen_comm_source()
            # Static overlay + ViewOn/ViewOff brightness fade (SDK-driven).
            _vs_ramp = getattr(controller, "_viewscreen_brightness_ramp", None)
            if _vs_ramp is None:
                _vs_ramp = ViewscreenBrightnessRamp()
                controller._viewscreen_brightness_ramp = _vs_ramp
            drive_viewscreen_static_and_brightness(
                r, controller, _vs_ramp, frame_dt)
```

NOTE: confirm the in-scope per-frame delta variable name at this point in the loop is `frame_dt`; if the loop uses a different name (e.g. `dt`), use that. Grep nearby: `grep -n "frame_dt\b" engine/host_loop.py` around the gameloop.

- [ ] **Step 5: Run the focused + related suites**

Run: `uv run pytest tests/unit/test_host_loop_viewscreen_drive.py -q`
Expected: PASS.
Run: `uv run pytest tests/unit/test_bridge_set_stubs.py tests/unit/test_viewscreen_static.py tests/unit/test_viewscreen_brightness_ramp.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py tests/unit/test_host_loop_viewscreen_drive.py
git commit -m "feat(viewscreen): drive static overlay + brightness from SDK state in Step 5c"
```

---

### Task 6: Native — viewscreen brightness uniform in bridge.frag

**Files:**
- Modify: `native/src/renderer/shaders/bridge.frag` (add `u_viewscreen_brightness`)
- Modify: `native/src/renderer/include/renderer/bridge_pass.h` (add setter + member)
- Modify: `native/src/renderer/bridge_pass.cc:135-145` (set the uniform on the override path; default 1.0 elsewhere)
- Modify: `native/src/host/host_bindings.cc` (add `set_viewscreen_brightness` binding)
- Test: `native/tests/renderer/viewscreen_brightness_test.cc` (new) + add to `native/tests/renderer/CMakeLists.txt`

**Interfaces:**
- Produces: `BridgePass::set_viewscreen_brightness(float b)`; GLSL uniform `u_viewscreen_brightness` (default 1.0). Host binding `set_viewscreen_brightness(float)`.

- [ ] **Step 1: Write the failing GL test**

Create `native/tests/renderer/viewscreen_brightness_test.cc`. Mirror `comm_pass_test.cc`'s context/skip + readback pattern. Render the bridge viewscreen mesh with a known solid RTT feed colour, once at brightness 1.0 and once at 0.5, and assert the sampled pixel scales:

```cpp
#include <gtest/gtest.h>
#include <filesystem>
#include <memory>
#include <vector>
#include <glad/glad.h>
#include <renderer/window.h>
#include <renderer/pipeline.h>
#include <renderer/bridge_pass.h>
#include <renderer/hdr_target.h>
#include <scenegraph/world.h>
#include <assets/asset_cache.h>

// Use the same viewscreen NIF the bridge uses; if BC assets are absent, skip.
static const std::filesystem::path kRoot =
    std::filesystem::path(__FILE__).parent_path().parent_path()
        .parent_path().parent_path();

TEST(ViewscreenBrightness, ScalesSampledFeed) {
    std::unique_ptr<renderer::Window> win;
    try {
        win = std::make_unique<renderer::Window>(64, 64, "vs-brightness", false);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context: " << e.what();
    }
    // A 1x1 white RTT feed texture stands in for the comm/forward feed.
    GLuint feed = 0; glGenTextures(1, &feed);
    glBindTexture(GL_TEXTURE_2D, feed);
    const unsigned char white[4] = {255, 255, 255, 255};
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 1, 1, 0, GL_RGBA,
                 GL_UNSIGNED_BYTE, white);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);

    // Minimal: build a quad-only world whose single mesh is registered as the
    // viewscreen model so draw_mesh takes the base_override path. Reuse the
    // bridge_pass_test helper if one exists; otherwise GTEST_SKIP if the
    // viewscreen NIF asset is missing.
    // ... assemble world + camera framing the viewscreen quad ...
    // Render at brightness 1.0 -> read center pixel R; render at 0.5 -> read R2.
    // EXPECT_NEAR(R2, R * 0.5, tolerance).
    GTEST_SKIP() << "TODO: assemble viewscreen quad world (see Step 3 note)";
}
```

NOTE for the implementer: if standing up a viewscreen-mesh world in the test is disproportionate, the brightness uniform is small and low-risk — assert it via the simpler route used by `bridge_pass_test.cc` (whatever mesh/world helper it already builds), set `set_viewscreen_model` + `set_viewscreen_texture(feed)` + `set_viewscreen_brightness`, render twice, and compare the override-path pixel. Keep the test; do not delete it. Prefer reusing existing helpers in `bridge_pass_test.cc`.

- [ ] **Step 2: Add the test to CMake and run to verify it fails/skips**

Add `viewscreen_brightness_test.cc` to the `add_executable(renderer_tests ...)` list in `native/tests/renderer/CMakeLists.txt`.

Run: `cmake -B build -S . && cmake --build build -j --target renderer_tests && ./build/native/tests/renderer/renderer_tests --gtest_filter='ViewscreenBrightness.*'`
Expected: builds; test SKIPs (TODO) or FAILs (once asserting) — confirms it's wired.

- [ ] **Step 3: Implement the shader + pass + binding**

`native/src/renderer/shaders/bridge.frag` — add the uniform and apply it ONLY to the viewscreen feed. Since the override path sets `u_emissive=(1,1,1)`, the cleanest faithful spot is to scale the final colour by brightness, defaulting to 1.0:

```glsl
uniform int u_flip_v;
uniform float u_viewscreen_brightness;   // 1.0 except the viewscreen feed fade
```

and at the end of `main()`:

```glsl
    vec3 light = max(u_ambient, u_emissive);
    FragColor = vec4(base.rgb * lm * light * u_viewscreen_brightness, 1.0);
```

`native/src/renderer/include/renderer/bridge_pass.h` — add near `set_viewscreen_texture`:

```cpp
    void set_viewscreen_brightness(float b) { viewscreen_brightness_ = b; }
```

and a member (default 1.0):

```cpp
    float viewscreen_brightness_ = 1.0f;
```

`native/src/renderer/bridge_pass.cc` `draw_mesh` — set the uniform every draw (1.0 for non-viewscreen geometry so it's byte-identical, the pass's value for the override). Add right where `u_flip_v` is set (line 133):

```cpp
    shader.set_int("u_flip_v", base_override != 0 ? 1 : 0);
    shader.set_float("u_viewscreen_brightness",
                     base_override != 0 ? viewscreen_brightness_ : 1.0f);
```

(`draw_mesh` is a file-scope free function — pass `viewscreen_brightness_` in. Simplest: add a `float vs_brightness` parameter to `draw_mesh` and thread `viewscreen_brightness_` from the two `walk_bridge_meshes` lambdas, mirroring how `ov`/`base_override` is threaded. Default the new param to `1.0f`.)

`native/src/host/host_bindings.cc` — add a binding near `set_viewscreen_enabled` (line 962):

```cpp
    m.def("set_viewscreen_brightness",
          [](float b) { if (g_bridge_pass) g_bridge_pass->set_viewscreen_brightness(b); },
          py::arg("b"));
```

- [ ] **Step 4: Reconfigure + build (shader changed) + run the test**

Run: `cmake -B build -S . && cmake --build build -j --target renderer_tests`
Then finish the test assertion (Step 1) and run:
`./build/native/tests/renderer/renderer_tests --gtest_filter='ViewscreenBrightness.*'`
Expected: PASS (or documented SKIP if BC viewscreen asset absent in the env).

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/shaders/bridge.frag \
        native/src/renderer/include/renderer/bridge_pass.h \
        native/src/renderer/bridge_pass.cc \
        native/src/host/host_bindings.cc \
        native/tests/renderer/viewscreen_brightness_test.cc \
        native/tests/renderer/CMakeLists.txt
git commit -m "feat(viewscreen): native u_viewscreen_brightness for ViewOn/Off fade"
```

---

### Task 7: Native — ViewscreenStaticPass (noise composite) + shaders + Pipeline

**Files:**
- Create: `native/src/renderer/shaders/viewscreen_static.vert`
- Create: `native/src/renderer/shaders/viewscreen_static.frag`
- Create: `native/src/renderer/include/renderer/viewscreen_static_pass.h`
- Create: `native/src/renderer/viewscreen_static_pass.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (embed the two shaders; add the .cc to the renderer lib sources)
- Modify: `native/src/renderer/include/renderer/pipeline.h` + `native/src/renderer/pipeline.cc` (add `viewscreen_static_shader()`)
- Test: `native/tests/renderer/viewscreen_static_pass_test.cc` (new) + add to `native/tests/renderer/CMakeLists.txt`

**Interfaces:**
- Produces:
  - `class ViewscreenStaticPass` with:
    - `void set_textures(const std::vector<std::string>& paths)` — load/cache the noise frames (idempotent by the joined path key).
    - `void render(renderer::Shader& shader, float intensity, double wall_time)` — draws a fullscreen quad over the currently-bound framebuffer, sampling the wall-time-cycled noise frame, alpha-blended at `intensity`.
    - `bool has_textures() const`.
  - `Pipeline::viewscreen_static_shader()`.

- [ ] **Step 1: Write the shaders**

`native/src/renderer/shaders/viewscreen_static.vert` (fullscreen triangle, UV from clip pos):

```glsl
#version 330 core
layout(location = 0) in vec2 a_pos;   // [-1,3] fullscreen triangle
out vec2 v_uv;
void main() {
    v_uv = a_pos * 0.5 + 0.5;         // orientation irrelevant (noise is isotropic)
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
```

`native/src/renderer/shaders/viewscreen_static.frag` (noise.rgb at alpha=intensity; framebuffer alpha-blend does `mix(feed, noise, intensity)`):

```glsl
#version 330 core
in vec2 v_uv;
uniform sampler2D u_noise;
uniform float u_intensity;   // 0..1
out vec4 FragColor;
void main() {
    vec3 n = texture(u_noise, v_uv).rgb;
    FragColor = vec4(n, u_intensity);
}
```

- [ ] **Step 2: Write the failing GL test**

Create `native/tests/renderer/viewscreen_static_pass_test.cc`. Render into an `HdrTarget`: clear to a known feed colour (e.g. (0.2,0.4,0.6)), then run the static pass at a fixed intensity over a 1×1 (or solid) noise texture of known colour, and read back the center pixel; assert `out ≈ mix(feed, noise, intensity)`. Also assert intensity 0 leaves the feed unchanged.

```cpp
#include <gtest/gtest.h>
#include <memory>
#include <vector>
#include <glad/glad.h>
#include <renderer/window.h>
#include <renderer/pipeline.h>
#include <renderer/hdr_target.h>
#include <renderer/viewscreen_static_pass.h>

static std::vector<float> read_center(int w, int h) {
    std::vector<float> buf(static_cast<size_t>(w) * h * 4);
    glReadPixels(0, 0, w, h, GL_RGBA, GL_FLOAT, buf.data());
    return buf;  // pixel 0 is enough for a solid fill
}

TEST(ViewscreenStaticPass, BlendsNoiseOverFeed) {
    std::unique_ptr<renderer::Window> win;
    try { win = std::make_unique<renderer::Window>(16, 16, "vs-static", false); }
    catch (const std::runtime_error& e) { GTEST_SKIP() << e.what(); }

    renderer::Pipeline pipe;
    renderer::HdrTarget target;
    target.resize(16, 16);
    target.bind();
    glClearColor(0.2f, 0.4f, 0.6f, 1.0f);          // "feed"
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    // Inject a 1x1 mid-grey noise texture directly (bypass file load).
    renderer::ViewscreenStaticPass pass;
    pass.set_solid_noise_for_test(0.8f);            // helper: 1x1 (0.8,0.8,0.8)
    pass.render(pipe.viewscreen_static_shader(), /*intensity=*/0.5f, /*t=*/0.0);

    auto px = read_center(16, 16);
    // mix(0.2, 0.8, 0.5) = 0.5 ; mix(0.4,0.8,0.5)=0.6 ; mix(0.6,0.8,0.5)=0.7
    EXPECT_NEAR(px[0], 0.5f, 0.02f);
    EXPECT_NEAR(px[1], 0.6f, 0.02f);
    EXPECT_NEAR(px[2], 0.7f, 0.02f);
}

TEST(ViewscreenStaticPass, IntensityZeroLeavesFeed) {
    std::unique_ptr<renderer::Window> win;
    try { win = std::make_unique<renderer::Window>(16, 16, "vs-static0", false); }
    catch (const std::runtime_error& e) { GTEST_SKIP() << e.what(); }
    renderer::Pipeline pipe;
    renderer::HdrTarget target; target.resize(16, 16); target.bind();
    glClearColor(0.2f, 0.4f, 0.6f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    renderer::ViewscreenStaticPass pass;
    pass.set_solid_noise_for_test(0.8f);
    pass.render(pipe.viewscreen_static_shader(), 0.0f, 0.0);
    auto px = read_center(16, 16);
    EXPECT_NEAR(px[0], 0.2f, 0.001f);
    EXPECT_NEAR(px[1], 0.4f, 0.001f);
    EXPECT_NEAR(px[2], 0.6f, 0.001f);
}
```

NOTE: add a small test-only helper `set_solid_noise_for_test(float v)` to `ViewscreenStaticPass` that uploads a 1×1 RGBA texture `(v,v,v,1)` and registers it as the single frame, so the test needs no on-disk tga. Keep it compiled in (it's tiny and harmless).

- [ ] **Step 3: Implement the pass**

`native/src/renderer/include/renderer/viewscreen_static_pass.h`:

```cpp
#pragma once
#include <string>
#include <vector>
#include <cstdint>
#include <assets/texture.h>
namespace renderer { class Shader; }

namespace renderer {

/// Composites the BC "View Screen Static" noise over the viewscreen RTT.
/// Owns the (up to 3) noise frames; cycles them by wall time and alpha-blends
/// the current frame at `intensity` so the framebuffer computes
/// out = mix(feed, noise, intensity). Orientation-agnostic (noise is isotropic).
class ViewscreenStaticPass {
public:
    ViewscreenStaticPass() = default;
    ~ViewscreenStaticPass();
    ViewscreenStaticPass(const ViewscreenStaticPass&) = delete;
    ViewscreenStaticPass& operator=(const ViewscreenStaticPass&) = delete;

    /// Load/cache noise frames from absolute paths. No-op if the path set is
    /// unchanged. Skips frames that fail to load.
    void set_textures(const std::vector<std::string>& paths);
    bool has_textures() const { return !frames_.empty(); }

    /// Draw the current noise frame over the bound framebuffer, alpha-blended
    /// at `intensity`. Saves/restores blend + depth + cull state.
    void render(Shader& shader, float intensity, double wall_time);

    /// Test-only: register a single 1x1 (v,v,v,1) frame without file I/O.
    void set_solid_noise_for_test(float v);

private:
    void ensure_quad();
    std::vector<assets::Texture> frames_;
    std::vector<std::string> loaded_paths_;
    std::uint32_t vao_ = 0;
    std::uint32_t vbo_ = 0;
};

}  // namespace renderer
```

`native/src/renderer/viewscreen_static_pass.cc` — implement using the canonical fullscreen-triangle pattern (from `cef_composite_pass.cc`), `assets::decode_tga`/`upload_image` for loading, and `assets::compute_flip_frame_index` (delta = 1/15s, frequency 1, phase 0) to pick the frame:

```cpp
#include <renderer/viewscreen_static_pass.h>
#include <renderer/shader.h>
#include <assets/flip_frame.h>
#include <glad/glad.h>
#include <fstream>
#include <iterator>
#include <cstdio>

namespace renderer {

namespace {
assets::Texture load_tga(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) { std::fprintf(stderr, "[vs-static] open '%s' failed\n", path.c_str()); return {}; }
    std::vector<std::uint8_t> bytes((std::istreambuf_iterator<char>(in)),
                                     std::istreambuf_iterator<char>());
    try { return assets::upload_image(assets::decode_tga(bytes), /*mips=*/false); }
    catch (const std::exception& e) {
        std::fprintf(stderr, "[vs-static] decode '%s': %s\n", path.c_str(), e.what());
        return {};
    }
}
}  // namespace

ViewscreenStaticPass::~ViewscreenStaticPass() {
    if (vbo_) glDeleteBuffers(1, &vbo_);
    if (vao_) glDeleteVertexArrays(1, &vao_);
}

void ViewscreenStaticPass::ensure_quad() {
    if (vao_) return;
    const float verts[] = { -1.f, -1.f,  3.f, -1.f,  -1.f, 3.f };
    glGenVertexArrays(1, &vao_);
    glGenBuffers(1, &vbo_);
    glBindVertexArray(vao_);
    glBindBuffer(GL_ARRAY_BUFFER, vbo_);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 2 * sizeof(float), nullptr);
    glBindVertexArray(0);
}

void ViewscreenStaticPass::set_textures(const std::vector<std::string>& paths) {
    if (paths == loaded_paths_) return;
    frames_.clear();
    for (const auto& p : paths) {
        assets::Texture t = load_tga(p);
        if (t.id() != 0) frames_.push_back(std::move(t));
    }
    loaded_paths_ = paths;
}

void ViewscreenStaticPass::set_solid_noise_for_test(float v) {
    GLuint id = 0; glGenTextures(1, &id);
    glBindTexture(GL_TEXTURE_2D, id);
    const unsigned char px[4] = {
        (unsigned char)(v * 255), (unsigned char)(v * 255),
        (unsigned char)(v * 255), 255 };
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, px);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    frames_.clear();
    frames_.emplace_back(id, 1, 1, false);
    loaded_paths_ = {"__test_solid__"};
}

void ViewscreenStaticPass::render(Shader& shader, float intensity, double wall_time) {
    if (frames_.empty() || intensity <= 0.0f) return;
    ensure_quad();
    const int n = static_cast<int>(frames_.size());
    const int frame = assets::compute_flip_frame_index(
        wall_time, /*start*/0.0, /*freq*/1.0, /*phase*/0.0, /*delta*/1.0 / 15.0, n);

    const GLboolean prev_blend = glIsEnabled(GL_BLEND);
    const GLboolean prev_depth = glIsEnabled(GL_DEPTH_TEST);
    const GLboolean prev_cull  = glIsEnabled(GL_CULL_FACE);
    glDisable(GL_DEPTH_TEST);
    glDisable(GL_CULL_FACE);
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);

    shader.use();
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, frames_[frame].id());
    shader.set_int("u_noise", 0);
    shader.set_float("u_intensity", intensity);

    glBindVertexArray(vao_);
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glBindVertexArray(0);

    if (!prev_blend) glDisable(GL_BLEND);
    if (prev_depth)  glEnable(GL_DEPTH_TEST);
    if (prev_cull)   glEnable(GL_CULL_FACE);
}

}  // namespace renderer
```

(Confirm the `assets::Texture(GLuint,w,h,bool)` constructor is accessible — it is per `texture.h:24`. Confirm `Shader::set_float`/`set_int` exist — they do per `shader.h`.)

- [ ] **Step 4: Wire CMake + Pipeline**

`native/src/renderer/CMakeLists.txt`:
- Add the two `embed_shader(...)` lines next to the bridge ones:
```cmake
embed_shader(SHADER_VS_STATIC_VS shaders/viewscreen_static.vert viewscreen_static_vs)
embed_shader(SHADER_VS_STATIC_FS shaders/viewscreen_static.frag viewscreen_static_fs)
```
  and ensure the generated headers are added wherever the other `embed_shader` outputs are collected (follow the bridge entry exactly).
- Add `viewscreen_static_pass.cc` to the renderer library's source list (next to `bridge_pass.cc`).

`native/src/renderer/pipeline.cc`:
- Add includes near the other embedded-shader includes:
```cpp
#include "embedded_viewscreen_static_vs.h"
#include "embedded_viewscreen_static_fs.h"
```
- In `Pipeline::Pipeline()` add:
```cpp
    viewscreen_static_ = std::make_unique<Shader>(
        shader_src::viewscreen_static_vs, shader_src::viewscreen_static_fs);
```

`native/src/renderer/include/renderer/pipeline.h`:
- Add getter `Shader& viewscreen_static_shader() noexcept { return *viewscreen_static_; }`
- Add member `std::unique_ptr<Shader> viewscreen_static_;`

- [ ] **Step 5: Add the test to CMake, reconfigure, build, run**

Add `viewscreen_static_pass_test.cc` to `add_executable(renderer_tests ...)` in `native/tests/renderer/CMakeLists.txt`.

Run (shader files are new → reconfigure):
```bash
cmake -B build -S . && cmake --build build -j --target renderer_tests
./build/native/tests/renderer/renderer_tests --gtest_filter='ViewscreenStaticPass.*'
```
Expected: PASS (both tests).

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/shaders/viewscreen_static.vert \
        native/src/renderer/shaders/viewscreen_static.frag \
        native/src/renderer/include/renderer/viewscreen_static_pass.h \
        native/src/renderer/viewscreen_static_pass.cc \
        native/src/renderer/CMakeLists.txt \
        native/src/renderer/pipeline.cc \
        native/src/renderer/include/renderer/pipeline.h \
        native/tests/renderer/viewscreen_static_pass_test.cc \
        native/tests/renderer/CMakeLists.txt
git commit -m "feat(viewscreen): ViewscreenStaticPass noise composite + shaders"
```

---

### Task 8: Native — host_bindings wiring (static globals + frame composite)

**Files:**
- Modify: `native/src/host/host_bindings.cc` (static globals near line 171; bindings near line 982; frame() composite after the feed render, ~line 457)
- (No new test — verified by the Task 7 GL test + the end-to-end run in Task 9.)

**Interfaces:**
- Consumes: `ViewscreenStaticPass` (Task 7), `Pipeline::viewscreen_static_shader()`.
- Produces host bindings: `set_viewscreen_static_source(list[str])`, `set_viewscreen_static(bool on, float intensity)`. (`set_viewscreen_brightness` was added in Task 6.)

- [ ] **Step 1: Add globals + the pass instance**

In `native/src/host/host_bindings.cc` near `g_comm_source` (line 171), add:

```cpp
// Viewscreen static/"snow" overlay: composited over the viewscreen RTT after
// the feed (comm or forward) is rendered. on/intensity are pushed per frame by
// host_loop (intensity = SDK fMin/fMax flicker); textures come from the
// "View Screen Static" icon group paths resolved in Python.
struct ViewscreenStatic { bool on = false; float intensity = 0.0f; };
ViewscreenStatic g_viewscreen_static;
std::unique_ptr<renderer::ViewscreenStaticPass> g_viewscreen_static_pass;
```

Add the include at the top with the other renderer includes:
```cpp
#include <renderer/viewscreen_static_pass.h>
```

Initialize the pass where the other passes are constructed (search for `g_bridge_pass = std::make_unique` in the init binding) and add:
```cpp
    g_viewscreen_static_pass = std::make_unique<renderer::ViewscreenStaticPass>();
```

- [ ] **Step 2: Composite in frame()**

In `frame()`, inside the `if (viewscreen_on)` block, AFTER the feed renders (comm or forward) and BEFORE `g_bridge_pass->set_viewscreen_texture(...)` (line 457) — the HDR target `g_viewscreen_hdr` is still bound here:

```cpp
        // Static/"snow" overlay over the feed (degraded-signal hail look).
        if (g_viewscreen_static.on && g_viewscreen_static_pass
                && g_viewscreen_static_pass->has_textures()) {
            g_viewscreen_static_pass->render(
                g_pipeline->viewscreen_static_shader(),
                g_viewscreen_static.intensity, now);
        }
        g_bridge_pass->set_viewscreen_texture(g_viewscreen_hdr->color_texture());
```

(`now` is the `glfwGetTime()` value computed earlier in `frame()`. Confirm it is in scope at this point; if not, use the same time source the feed/animation uses.)

- [ ] **Step 3: Add the bindings**

Near `clear_viewscreen_comm_source` (line 982):

```cpp
    m.def("set_viewscreen_static_source",
          [](std::vector<std::string> paths) {
              if (g_viewscreen_static_pass)
                  g_viewscreen_static_pass->set_textures(paths);
          }, py::arg("paths"));
    m.def("set_viewscreen_static",
          [](bool on, float intensity) {
              g_viewscreen_static.on = on;
              g_viewscreen_static.intensity = intensity;
          }, py::arg("on"), py::arg("intensity"));
```

(Ensure `#include <vector>` and `#include <string>` are present — they are, but verify.)

- [ ] **Step 4: Full rebuild (host_bindings.cc) + run renderer_tests**

Run:
```bash
cmake -B build -S . && cmake --build build -j
./build/native/tests/renderer/renderer_tests --gtest_filter='Viewscreen*'
```
Expected: builds clean; viewscreen tests PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/host/host_bindings.cc
git commit -m "feat(viewscreen): host wiring for static composite (frame + bindings)"
```

---

### Task 9: Full verification — suites, build, and manual GUI steps

**Files:**
- Create: `docs/superpowers/verification/2026-06-19-comm-viewscreen-fidelity.md` (the manual test recipe for Mark)

- [ ] **Step 1: Full Python suite**

Run: `scripts/run_tests.sh`
Expected: PASS (watchdog-capped per memory `feedback_pytest_memory`). Confirm the new tests are collected.

- [ ] **Step 2: Full native build + renderer_tests**

Run:
```bash
cmake -B build -S . && cmake --build build -j
./build/native/tests/renderer/renderer_tests
```
Expected: build clean; tests pass (pre-existing batch GL-readback flakiness noted in the prior spec §7 is unrelated — confirm the `Viewscreen*` tests pass individually).

- [ ] **Step 3: Write the manual verification recipe**

Create `docs/superpowers/verification/2026-06-19-comm-viewscreen-fidelity.md` documenting, for Mark to drive (no synthetic desktop interaction):
- Launch `./build/dauntless` with `--developer`.
- **E1M2** (static test bed): trigger the Soams hail that calls `ViewscreenOn("MiscEng","Soams",0.8,1,1)` → expect heavy animated snow over the comm scene; and the clean `(0,0)` Soams hails → expect no snow. Provide dev-gated logging lines to add (gated by `dev_mode.is_enabled()`) at `drive_viewscreen_static_and_brightness` reporting `(signature, static_on, intensity)` each time they change, so the log corroborates the visual.
- **E1M1** (clean baseline + transitions): the Liu hail `(0,0)` → no snow; on hail open and on hang-up, expect the ~0.3s brightness fade-in. Log the brightness ramp start.
- Compare against BC reference footage (degraded-signal snow; screen tune-in).
- Note: character heads still render untextured ("lego head") — a separate known bug, not part of this work.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/verification/2026-06-19-comm-viewscreen-fidelity.md
git commit -m "docs(viewscreen): manual verification recipe for static + fade"
```

- [ ] **Step 5: Hand off for visual verification**

Report to Mark: the build command, the two missions to test, the dev log lines to watch, and request screenshots. Do not run the GUI or synthetic input on Mark's workstation.

---

## Self-Review notes

- **Spec coverage:** §4.1 → Task 1; §4.2 → Task 2; §4.3 (static plumbing) → Tasks 4+5; §4.3 (brightness ramp) → Task 3; §4.4 (static composite) → Task 7; §4.5 (brightness uniform) → Task 6; §4.5 host wiring → Task 8; §6 testing → tests in each task + Task 9. Cut/defer items (hail-face/menus) intentionally have no task.
- **Type consistency:** `set_viewscreen_static(on, intensity)`, `set_viewscreen_static_source(paths)`, `set_viewscreen_brightness(b)` names match across renderer.py (Task 4), host bindings (Tasks 6/8), and host_loop calls (Task 5). `static_intensity`/`static_texture_paths` names match between Task 2 and Task 5. `ViewscreenBrightnessRamp.update/DURATION_S` match between Task 3 and Task 5.
- **Open confirmations flagged inline:** the per-frame delta var name in Step 5c (`frame_dt`); `now` scope in frame(); reuse of `bridge_pass_test.cc` helpers for the brightness GL test; exact `embed_shader` output-collection mechanism in the renderer CMakeLists.
```
