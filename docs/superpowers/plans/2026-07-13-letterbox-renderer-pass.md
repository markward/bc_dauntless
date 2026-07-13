# Cutscene Letterbox → Renderer Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Draw the cutscene letterbox bars in the renderer (below the whole CEF overlay) instead of as CEF DOM, so every UI element draws over them by construction and no future panel can be swallowed by a black bar.

**Architecture:** A `glScissor` + `glClear` pass writes two black bars into the default framebuffer (FBO 0) after the post-process chain and before `ui_cef::composite()`. A pure-Python `LetterboxAnimator` takes over the slide-in/out that CSS `transition` used to do, driven from `TopWindow.letterbox_snapshot()` and the host loop's `_player_dt` (so the bars freeze under pause instead of sliding on wall-clock). The CEF divs, CSS, JS renderer, and `SDKMirrorPanel` entry are deleted.

**Tech Stack:** C++17 / OpenGL (glad) / pybind11 for the pass and binding; Python 3 for the animator and host wiring; gtest (`renderer_tests`, run via ctest) and pytest for tests.

**Spec:** `docs/superpowers/specs/2026-07-13-letterbox-renderer-pass-design.md`

## Global Constraints

- **Do NOT commit and do NOT create a branch.** Another session is working in this shared checkout. Leave every change in the working tree and ask Mark before committing. The per-task "Commit" steps below give the exact command and message to use *if and only if* Mark has cleared the tree — otherwise stop at the passing-test step of each task.
- **Never `git add -A`.** If Mark clears the tree for a commit, stage the explicit pathspec listed in that task only. Unrelated modified files (`engine/host_loop.py` DevTools-freeze work, `native/src/ui_cef/*`, `tests/host/test_pause_menu.py`) belong to another session.
- **`engine/host_loop.py` is currently modified by that other session.** Task 3 edits it. Make only the additions described; do not revert, reformat, or "tidy" any surrounding line.
- Adding a new `.cc` to `native/src/renderer/CMakeLists.txt` requires a **cmake reconfigure**, not just a rebuild: `cmake -B build -S .` then `cmake --build build -j`.
- Edits to `native/src/host/host_bindings.cc` require a full **`dauntless` binary** rebuild — rebuilding only the Python module leaves `./build/dauntless` stale.
- Single build tree: `build/`. Binary `build/dauntless`, module `build/python/_dauntless_host.cpython-*.so`. Never run cmake from inside `native/`.
- Test gate is `scripts/check_tests.sh` (pytest + ctest, diffed against `tests/known_failures.txt`). `scripts/run_tests.sh` is pytest-only and cannot see C++ regressions.
- Game units: the letterbox fraction is dimensionless (`fCoveredArea`, BC default `0.125` = total, i.e. 6.25% per bar). No GU conversion anywhere in this change.

---

## File Structure

| File | Responsibility |
|---|---|
| `native/src/renderer/include/renderer/letterbox_pass.h` (create) | Pass interface: `set_covered` / `covered` / `draw`. |
| `native/src/renderer/letterbox_pass.cc` (create) | The scissor-clear pass + clamped state. No shader, no FBO. |
| `native/src/renderer/CMakeLists.txt` (modify) | Add `letterbox_pass.cc` to the `renderer` sources. |
| `native/tests/renderer/letterbox_pass_test.cc` (create) | gtest: clamping + bars-are-black-and-centre-is-not. |
| `native/tests/renderer/CMakeLists.txt` (modify) | Add the test source to `renderer_tests`. |
| `native/src/host/host_bindings.cc` (modify) | `letterbox_set` binding; call `letterbox::draw()` in `frame()`. |
| `engine/renderer.py` (modify) | `letterbox_set()` wrapper + `_REQUIRED_BINDINGS` entry. |
| `engine/ui/letterbox.py` (create) | `LetterboxAnimator` — pure Python easing, no engine imports. |
| `tests/unit/test_letterbox.py` (create) | Animator unit tests. |
| `engine/host_loop.py` (modify) | `_pump_letterbox()` helper + one call site before `r.frame()`. |
| `tests/host/test_letterbox_pump.py` (create) | Host-wiring test against a fake renderer. |
| `native/assets/ui-cef/index.html` (modify) | Delete the two letterbox divs. |
| `native/assets/ui-cef/css/sdk_mirror.css` (modify) | Delete the `.sdk-letterbox` rules. |
| `native/assets/ui-cef/js/sdk_mirror.js` (modify) | Delete `renderLetterbox()` and its call. |
| `engine/appc/sdk_mirror_panel.py` (modify) | Delete the letterbox entry + `_letterbox_emitted`. |
| `tests/unit/test_sdk_mirror_panel.py` (modify) | Delete the three letterbox tests; add a never-emits test. |

`engine/appc/top_window.py` is **not** touched — its cutscene surface and `letterbox_snapshot()` are already exactly what we need, and its tests stay green untouched.

---

### Task 1: `LetterboxAnimator` — the slide, in pure Python

The CSS `transition: height Ns ease` disappears in Task 5, so the easing has to live somewhere. It goes here: a class with no engine imports and no GL, so it is fully unit-testable headless.

**Files:**
- Create: `engine/ui/letterbox.py`
- Test: `tests/unit/test_letterbox.py`

**Interfaces:**
- Consumes: `TopWindow.letterbox_snapshot()` dicts — shape `{"type": "letterbox", "visible": bool, "covered": float, "transition_s": float}` (already exists, unchanged).
- Produces: `LetterboxAnimator().update(dt: float, snapshot: dict) -> float` returning the current total covered fraction in `[0, 1]`. Task 3 calls this.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_letterbox.py`:

```python
"""LetterboxAnimator — eases the cutscene bars in/out on the sim clock.

Replaces the CSS `transition: height Ns ease` that animated the bars while
they were CEF DOM. Driven from TopWindow.letterbox_snapshot() by the host
loop; see docs/superpowers/specs/2026-07-13-letterbox-renderer-pass-design.md
"""
from engine.ui.letterbox import LetterboxAnimator


def _snap(visible, covered=0.125, transition_s=1.0):
    return {"type": "letterbox", "visible": visible,
            "covered": covered, "transition_s": transition_s}


def test_starts_closed():
    assert LetterboxAnimator().current == 0.0


def test_slide_in_is_monotonic_and_reaches_the_target():
    a = LetterboxAnimator()
    prev = 0.0
    for _ in range(10):                      # 10 x 0.1 s = the full 1.0 s
        cur = a.update(0.1, _snap(True))
        assert cur >= prev                   # never retreats
        prev = cur
    assert a.update(0.0, _snap(True)) == 0.125


def test_does_not_overshoot_past_the_target():
    a = LetterboxAnimator()
    assert a.update(99.0, _snap(True)) == 0.125


def test_slide_out_eases_back_to_zero():
    a = LetterboxAnimator()
    a.update(99.0, _snap(True))               # fully in
    a.update(0.5, _snap(False, transition_s=1.0))
    assert 0.0 < a.current < 0.125            # mid-slide, not snapped
    a.update(1.0, _snap(False, transition_s=1.0))
    assert a.current == 0.0


def test_zero_duration_snaps():
    """AbortCutscene sets transition_s = 0.0 — the bars must vanish in one
    frame, not ease."""
    a = LetterboxAnimator()
    a.update(99.0, _snap(True))
    assert a.update(0.016, _snap(False, transition_s=0.0)) == 0.0


def test_frozen_dt_holds_the_bars_still():
    """dt == 0 is how the host loop reports pause / DevTools freeze. The bars
    must hold, not keep sliding on wall-clock time (which is what the old CSS
    transition did)."""
    a = LetterboxAnimator()
    a.update(0.3, _snap(True))
    held = a.current
    assert 0.0 < held < 0.125                 # genuinely mid-slide
    for _ in range(5):
        assert a.update(0.0, _snap(True)) == held


def test_retarget_mid_slide_eases_from_the_current_value():
    """EndCutscene while the bars are still sliding IN must reverse from where
    they are, not jump to full coverage first."""
    a = LetterboxAnimator()
    a.update(0.3, _snap(True))
    mid = a.current
    after = a.update(0.0, _snap(False, transition_s=1.0))
    assert after == mid                       # no jump on the retarget frame
    assert a.update(0.1, _snap(False, transition_s=1.0)) < mid


def test_clamps_a_hostile_covered_value():
    """fCoveredArea comes from mission script; a bogus value must not produce a
    negative or >1 fraction for the scissor rect downstream."""
    a = LetterboxAnimator()
    assert a.update(99.0, _snap(True, covered=5.0)) == 1.0
    a2 = LetterboxAnimator()
    assert a2.update(99.0, _snap(True, covered=-1.0)) == 0.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_letterbox.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.ui.letterbox'`

- [ ] **Step 3: Write the implementation**

Create `engine/ui/letterbox.py`:

```python
"""Cutscene letterbox easing.

The bars are drawn by the renderer (native/src/renderer/letterbox_pass.cc),
not by CEF, so nothing animates them for free any more — this does it.

TopWindow records the target coverage and the slide duration when a mission
calls StartCutscene / EndCutscene / AbortCutscene; the host loop feeds the
resulting snapshot in here once per frame along with the frame dt, and pushes
the returned fraction at renderer.letterbox_set().

The dt is the host loop's _player_dt, which is 0 while the sim is frozen, so
the bars hold still under the pause menu instead of sliding on wall-clock time.

Spec: docs/superpowers/specs/2026-07-13-letterbox-renderer-pass-design.md
"""
from __future__ import annotations


def _clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


class LetterboxAnimator:
    """Eases the total covered fraction toward the snapshot's target.

    Smoothstep approximates the CSS `ease` curve the DOM bars used, so the
    motion is recognisably the same as before the move to GL.
    """

    def __init__(self) -> None:
        self._current = 0.0
        self._start = 0.0      # value at the last re-target, for the ease
        self._target = 0.0
        self._elapsed = 0.0
        self._duration = 0.0

    @property
    def current(self) -> float:
        return self._current

    def update(self, dt: float, snapshot: dict) -> float:
        target = _clamp01(float(snapshot.get("covered", 0.0))) \
            if snapshot.get("visible") else 0.0

        if target != self._target:
            # Re-base the ease from wherever the bars are right now. A mission
            # that ends a cutscene while the bars are still sliding IN must
            # reverse from the current height, not jump to full coverage.
            self._target = target
            self._start = self._current
            self._elapsed = 0.0
            self._duration = max(0.0, float(snapshot.get("transition_s", 0.0)))

        if self._duration <= 0.0:
            # AbortCutscene's snap (transition_s = 0.0) lands here.
            self._current = self._target
            return self._current

        self._elapsed += max(0.0, dt)
        t = min(1.0, self._elapsed / self._duration)
        s = t * t * (3.0 - 2.0 * t)              # smoothstep ~= CSS `ease`
        self._current = self._start + (self._target - self._start) * s
        return self._current
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_letterbox.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 5: Commit — ONLY if Mark has cleared the shared tree (see Global Constraints)**

```bash
git add engine/ui/letterbox.py tests/unit/test_letterbox.py
git commit -m "feat(cutscene): LetterboxAnimator — sim-clock easing for the bars"
```

---

### Task 2: The renderer pass, its binding, and the Python wrapper

**Files:**
- Create: `native/src/renderer/include/renderer/letterbox_pass.h`
- Create: `native/src/renderer/letterbox_pass.cc`
- Create: `native/tests/renderer/letterbox_pass_test.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (source list, ~line 137 — alongside `target_reticle_pass.cc`)
- Modify: `native/tests/renderer/CMakeLists.txt` (`renderer_tests` source list)
- Modify: `native/src/host/host_bindings.cc` (the `frame()` function ~line 997, and the `PYBIND11_MODULE` block)
- Modify: `engine/renderer.py` (`_REQUIRED_BINDINGS` ~line 34, wrapper near `set_dust_enabled` ~line 368)

**Interfaces:**
- Produces: `renderer::letterbox::set_covered(float)`, `renderer::letterbox::covered()`, `renderer::letterbox::draw(int fb_width, int fb_height)`; Python `_dauntless_host.letterbox_set(covered: float)` and `engine.renderer.letterbox_set(covered: float) -> None`. Task 3 calls the Python wrapper.

- [ ] **Step 1: Write the failing C++ test**

Create `native/tests/renderer/letterbox_pass_test.cc`:

```cpp
// native/tests/renderer/letterbox_pass_test.cc
//
// The cutscene letterbox is a renderer pass, not CEF DOM, so that every UI
// element draws over it by construction. See
// docs/superpowers/specs/2026-07-13-letterbox-renderer-pass-design.md
#include <gtest/gtest.h>

#include <renderer/letterbox_pass.h>
#include <renderer/window.h>

#include <glad/glad.h>

#include <memory>
#include <vector>

TEST(LetterboxState, ClampsAndRoundTrips) {
    renderer::letterbox::set_covered(0.125f);
    EXPECT_FLOAT_EQ(renderer::letterbox::covered(), 0.125f);
    renderer::letterbox::set_covered(5.0f);
    EXPECT_FLOAT_EQ(renderer::letterbox::covered(), 1.0f);
    renderer::letterbox::set_covered(-1.0f);
    EXPECT_FLOAT_EQ(renderer::letterbox::covered(), 0.0f);
    renderer::letterbox::set_covered(0.0f);      // restore for other tests
}

namespace {

// GL-only fixture: the pass needs no BC assets, no model, no camera.
class LetterboxPassTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    int fw = 0, fh = 0;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(256, 256, "letterbox-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        w->framebuffer_size(&fw, &fh);   // may be 512x512 on a HiDPI display
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glViewport(0, 0, fw, fh);
    }

    void TearDown() override { renderer::letterbox::set_covered(0.0f); }

    // Fill FBO 0 with pure red so any black we read back came from the pass.
    void fill_red() {
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glDisable(GL_SCISSOR_TEST);
        glClearColor(1.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);
    }

    bool is_black_at(int y) {
        unsigned char px[4] = {0};
        glReadPixels(fw / 2, y, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
        return px[0] == 0 && px[1] == 0 && px[2] == 0;
    }
};

}  // namespace

TEST_F(LetterboxPassTest, ZeroCoverageDrawsNothing) {
    fill_red();
    renderer::letterbox::set_covered(0.0f);
    renderer::letterbox::draw(fw, fh);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    EXPECT_FALSE(is_black_at(fh - 2));      // top row still red
    EXPECT_FALSE(is_black_at(1));           // bottom row still red
}

TEST_F(LetterboxPassTest, BarsAreBlackAndTheCentreBandIsNot) {
    fill_red();
    // 0.5 total => a quarter of the height per bar: rows [0, fh/4) and
    // [fh - fh/4, fh). Sample well inside each bar and at mid-screen.
    renderer::letterbox::set_covered(0.5f);
    renderer::letterbox::draw(fw, fh);
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
    EXPECT_TRUE(is_black_at(fh - 2));               // inside the top bar
    EXPECT_TRUE(is_black_at(1));                    // inside the bottom bar
    EXPECT_FALSE(is_black_at(fh / 2));              // scene survives in the middle
    EXPECT_FALSE(is_black_at(fh / 2 + fh / 8));     // just inside the top bar's edge
}

TEST_F(LetterboxPassTest, LeavesScissorTestDisabledForTheCefComposite) {
    // The pass runs immediately before ui_cef::composite(). If it leaked an
    // enabled GL_SCISSOR_TEST, the overlay would be clipped to the last bar.
    fill_red();
    renderer::letterbox::set_covered(0.5f);
    renderer::letterbox::draw(fw, fh);
    EXPECT_FALSE(glIsEnabled(GL_SCISSOR_TEST));
}
```

Add the source to `native/tests/renderer/CMakeLists.txt`, in the `renderer_tests` list immediately after `dust_pass_test.cc`:

```cmake
    dust_pass_test.cc
    letterbox_pass_test.cc
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cmake -B build -S . && cmake --build build -j --target renderer_tests
```
Expected: FAIL to compile — `fatal error: 'renderer/letterbox_pass.h' file not found`.

- [ ] **Step 3: Write the pass**

Create `native/src/renderer/include/renderer/letterbox_pass.h`:

```cpp
// native/src/renderer/include/renderer/letterbox_pass.h
#pragma once

/// Cutscene letterbox bars.
///
/// Drawn by the renderer rather than by CEF so that the entire UI overlay
/// composites ON TOP of the bars by construction — no z-index to forget. The
/// bars used to be DOM (`.sdk-letterbox`, z-index 5) and swallowed any HUD
/// root that had no z-index of its own, which is how E1M1's XO menu once went
/// invisible mid-tutorial.
///
/// Called from host_bindings::frame() after the post-process chain has
/// resolved into FBO 0 and before ui_cef::composite().
///
/// Spec: docs/superpowers/specs/2026-07-13-letterbox-renderer-pass-design.md
namespace renderer::letterbox {

/// Set the TOTAL covered fraction (BC's fCoveredArea: 0.125 => 6.25% per
/// bar). Clamped to [0, 1] — the value originates in mission script.
void set_covered(float covered);

/// Current total covered fraction, in [0, 1].
float covered();

/// Draw the two bars into FBO 0. No-op when the coverage is zero, so an
/// out-of-cutscene frame costs one float compare.
void draw(int fb_width, int fb_height);

}  // namespace renderer::letterbox
```

Create `native/src/renderer/letterbox_pass.cc`:

```cpp
// native/src/renderer/letterbox_pass.cc
#include "renderer/letterbox_pass.h"

#include <glad/glad.h>

#include <algorithm>
#include <cmath>

namespace renderer::letterbox {
namespace {
float g_covered = 0.0f;
}  // namespace

void set_covered(float covered) {
    g_covered = std::clamp(covered, 0.0f, 1.0f);
}

float covered() { return g_covered; }

void draw(int fb_width, int fb_height) {
    if (g_covered <= 0.0f || fb_width <= 0 || fb_height <= 0) return;

    // Per-bar height: covered is the TOTAL fraction, split across two bars.
    const int bar = static_cast<int>(
        std::lround(static_cast<double>(g_covered) * 0.5 * fb_height));
    if (bar <= 0) return;

    // Save the state we touch: this pass runs immediately before the CEF
    // composite, and a leaked scissor rect would clip the whole overlay.
    GLfloat prev_clear[4];
    glGetFloatv(GL_COLOR_CLEAR_VALUE, prev_clear);
    const GLboolean prev_scissor_enabled = glIsEnabled(GL_SCISSOR_TEST);
    GLint prev_box[4];
    glGetIntegerv(GL_SCISSOR_BOX, prev_box);

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, fb_width, fb_height);
    glEnable(GL_SCISSOR_TEST);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);

    // GL's origin is bottom-left, so y=0 is the BOTTOM bar.
    glScissor(0, 0, fb_width, bar);
    glClear(GL_COLOR_BUFFER_BIT);
    glScissor(0, fb_height - bar, fb_width, bar);
    glClear(GL_COLOR_BUFFER_BIT);

    if (!prev_scissor_enabled) glDisable(GL_SCISSOR_TEST);
    glScissor(prev_box[0], prev_box[1], prev_box[2], prev_box[3]);
    glClearColor(prev_clear[0], prev_clear[1], prev_clear[2], prev_clear[3]);
}

}  // namespace renderer::letterbox
```

Add the source to `native/src/renderer/CMakeLists.txt` in the `renderer` source list, immediately after `target_reticle_pass.cc`:

```cmake
    target_reticle_pass.cc
    letterbox_pass.cc
```

- [ ] **Step 4: Run the C++ test to verify it passes**

Run:
```bash
cmake -B build -S . && cmake --build build -j --target renderer_tests
./build/native/tests/renderer/renderer_tests --gtest_filter='Letterbox*'
```
Expected: PASS, 4 tests (or SKIPPED with "no GL context" on a headless box without a GL surface — if they skip, say so explicitly rather than reporting a pass).

- [ ] **Step 5: Call the pass from `frame()` and expose the binding**

In `native/src/host/host_bindings.cc`, add the include next to the other renderer pass includes at the top of the file:

```cpp
#include <renderer/letterbox_pass.h>
```

In `frame()`, immediately after the `if (any_post) { ... }` ping-pong block closes (currently ~line 997, just before the `// Cache this exterior frame's view-projection` comment), insert:

```cpp
    // Cutscene letterbox — the final image is now in FBO 0 whether or not the
    // post chain ran. Draw the bars over the scene but BEFORE the CEF
    // composite below, so every UI element (subtitles, crew menus, info boxes,
    // pause menu) lands on top of them. No-op outside a cutscene.
    renderer::letterbox::draw(fw, fh);
```

In the `PYBIND11_MODULE` block, next to the other renderer toggles (e.g. near `dust_set_enabled`), add:

```cpp
    m.def("letterbox_set",
          [](float covered) { renderer::letterbox::set_covered(covered); },
          "Set the cutscene letterbox TOTAL covered fraction (BC's "
          "fCoveredArea; 0.125 => 6.25% per bar). Clamped to [0, 1]. The bars "
          "draw over the 3D scene and under the whole CEF overlay.");
```

This binding is **not** CEF-gated, so it does **not** get an entry in the `#else` stub block near line 3362 — the renderer is always linked.

- [ ] **Step 6: Add the Python wrapper**

In `engine/renderer.py`, add `"letterbox_set"` to `_REQUIRED_BINDINGS` (keep the set's alphabetical grouping — it goes on the line with the `l`/`i` names), and add the wrapper near `set_dust_enabled`:

```python
def letterbox_set(covered: float) -> None:
    """Set the cutscene letterbox TOTAL covered fraction (BC's fCoveredArea;
    0.125 => 6.25% per bar). Clamped native-side to [0, 1]. The bars draw over
    the 3D scene and under the entire CEF overlay, so all UI sits on top."""
    _h.letterbox_set(float(covered))
```

- [ ] **Step 7: Rebuild the binary and verify the binding exists**

Run:
```bash
cmake -B build -S . && cmake --build build -j
uv run python -c "import sys; sys.path.insert(0, 'build/python'); import _dauntless_host as h; print(h.letterbox_set)"
```
Expected: prints a built-in function. An `AttributeError` here means a stale binary — rebuild, do not touch the Python side.

- [ ] **Step 8: Commit — ONLY if Mark has cleared the shared tree**

```bash
git add native/src/renderer/letterbox_pass.cc \
        native/src/renderer/include/renderer/letterbox_pass.h \
        native/src/renderer/CMakeLists.txt \
        native/tests/renderer/letterbox_pass_test.cc \
        native/tests/renderer/CMakeLists.txt \
        native/src/host/host_bindings.cc engine/renderer.py
git commit -m "feat(renderer): letterbox pass — bars in GL, under the whole UI layer"
```

---

### Task 3: Host-loop wiring

**Files:**
- Modify: `engine/host_loop.py` (new helper next to `_pump_bridge_doors` ~line 1803; one call site immediately before `r.frame()` ~line 6857)
- Test: `tests/host/test_letterbox_pump.py` (create)

**Interfaces:**
- Consumes: `LetterboxAnimator.update(dt, snapshot) -> float` (Task 1); `engine.renderer.letterbox_set(covered)` (Task 2); `TopWindow.letterbox_snapshot()` (already exists).
- Produces: `_pump_letterbox(renderer, animator, dt) -> float` in `engine.host_loop`.

- [ ] **Step 1: Write the failing test**

Create `tests/host/test_letterbox_pump.py`:

```python
"""_pump_letterbox — the one wire from TopWindow's cutscene state to the GL
letterbox pass. Runs every frame, unconditionally: the bars are not view-gated
(BC letterboxes bridge cutscenes as well as exterior ones)."""
import pytest

from engine.appc import top_window
from engine.host_loop import _pump_letterbox
from engine.ui.letterbox import LetterboxAnimator


@pytest.fixture(autouse=True)
def _reset_tw():
    top_window.reset_for_tests()


class _FakeRenderer:
    def __init__(self):
        self.pushed = []

    def letterbox_set(self, covered):
        self.pushed.append(covered)


def test_pushes_zero_when_no_cutscene():
    r, a = _FakeRenderer(), LetterboxAnimator()
    assert _pump_letterbox(r, a, 0.016) == 0.0
    assert r.pushed == [0.0]


def test_cutscene_bars_ease_in_and_reach_the_sdk_covered_fraction():
    r, a = _FakeRenderer(), LetterboxAnimator()
    top_window.TopWindow_GetTopWindow().StartCutscene(1.0, 0.125, 1)
    _pump_letterbox(r, a, 0.5)
    assert 0.0 < r.pushed[-1] < 0.125          # mid-slide
    _pump_letterbox(r, a, 1.0)
    assert r.pushed[-1] == 0.125               # fully in


def test_abort_snaps_the_bars_away():
    r, a = _FakeRenderer(), LetterboxAnimator()
    tw = top_window.TopWindow_GetTopWindow()
    tw.StartCutscene(1.0, 0.125, 1)
    _pump_letterbox(r, a, 99.0)
    tw.AbortCutscene()
    assert _pump_letterbox(r, a, 0.016) == 0.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/host/test_letterbox_pump.py -v`
Expected: FAIL — `ImportError: cannot import name '_pump_letterbox' from 'engine.host_loop'`

- [ ] **Step 3: Add the helper**

In `engine/host_loop.py`, immediately after `_pump_bridge_doors` (~line 1806), add:

```python
def _pump_letterbox(renderer, animator, dt: float) -> float:
    """Drive the GL cutscene letterbox from TopWindow's cutscene state.

    The bars are a renderer pass, not CEF DOM, so the whole UI overlay draws on
    top of them by construction (they used to be a z-index:5 div that swallowed
    every HUD root without a z-index of its own — that is how E1M1's XO menu
    went invisible). Nothing else animates them now, so the ease lives in
    LetterboxAnimator and is ticked here.

    Unconditional — NOT view-gated. BC letterboxes bridge cutscenes as well as
    exterior ones. `dt` is _player_dt, which is 0 while the sim is frozen, so
    the bars hold still under the pause menu instead of sliding on wall-clock.

    Spec: docs/superpowers/specs/2026-07-13-letterbox-renderer-pass-design.md
    """
    from engine.appc.top_window import TopWindow_GetTopWindow
    covered = animator.update(dt, TopWindow_GetTopWindow().letterbox_snapshot())
    renderer.letterbox_set(covered)
    return covered
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/host/test_letterbox_pump.py -v`
Expected: PASS, 3 tests.

- [ ] **Step 5: Wire it into the frame**

In `engine/host_loop.py`, add the import alongside the other `engine.ui` imports at the top of the module:

```python
from engine.ui.letterbox import LetterboxAnimator
```

Construct the animator once, next to where `SDKMirrorPanel` is registered (~line 5589, inside `run()` before the main loop):

```python
        _letterbox_anim = LetterboxAnimator()
```

Then, in the main loop immediately **before** `r.frame()` (~line 6857, after the `_push_cloak_refraction(r, session, player)` call and the `verbose` block), add:

```python
            _pump_letterbox(r, _letterbox_anim, _player_dt)
```

- [ ] **Step 6: Verify nothing regressed in the host suite**

Run: `uv run pytest tests/host -q`
Expected: PASS (the DevTools-freeze tests from the other session's work in `tests/host/test_pause_menu.py` should pass too — if they don't, that is that session's tree, not this change; check with `git stash list`/`git diff` before blaming this task).

- [ ] **Step 7: Commit — ONLY if Mark has cleared the shared tree**

```bash
git add engine/host_loop.py tests/host/test_letterbox_pump.py
git commit -m "feat(cutscene): drive the GL letterbox from TopWindow each frame"
```

---

### Task 4: Delete the CEF letterbox

Only now — with the GL bars live — do the DOM bars come out. Doing it in this order means there is never a commit where a cutscene has no letterbox at all.

**Files:**
- Modify: `native/assets/ui-cef/index.html` (lines 562-564)
- Modify: `native/assets/ui-cef/css/sdk_mirror.css` (lines 31-46)
- Modify: `native/assets/ui-cef/js/sdk_mirror.js` (line 9 and the `renderLetterbox` function, lines 12-29)
- Modify: `engine/appc/sdk_mirror_panel.py` (the `_letterbox_emitted` field ~line 29; the letterbox block ~lines 53-60; the reset ~line 80)
- Test: `tests/unit/test_sdk_mirror_panel.py` (delete three tests, add one)

**Interfaces:**
- Consumes: nothing new.
- Produces: `SDKMirrorPanel.render_payload()` no longer emits any entry with `type == "letterbox"`.

- [ ] **Step 1: Rewrite the mirror-panel tests (they fail first)**

In `tests/unit/test_sdk_mirror_panel.py`, delete `test_letterbox_absent_until_cutscene`, `test_letterbox_emitted_on_cutscene_start`, and `test_letterbox_hide_update_then_silent` entirely, and add in their place:

```python
def test_letterbox_is_never_emitted():
    """The cutscene letterbox is a RENDERER pass now (letterbox_pass.cc),
    driven by _pump_letterbox from TopWindow's snapshot. It must not also come
    through the CEF mirror: as DOM it was a z-index:5 element that painted over
    every HUD root without a z-index (E1M1's XO menu vanished under it). See
    docs/superpowers/specs/2026-07-13-letterbox-renderer-pass-design.md
    """
    _seed_subtitle()
    p = SDKMirrorPanel()
    top_window._the_top_window.StartCutscene(1.0, 0.125, 1)
    out = p.render_payload()
    entries = _entries(out) if out is not None else []
    assert not any(e["type"] == "letterbox" for e in entries)
```

Keep the `_entries` helper — the other tests use it.

- [ ] **Step 2: Run the tests to verify the new one fails**

Run: `uv run pytest tests/unit/test_sdk_mirror_panel.py -v`
Expected: FAIL on `test_letterbox_is_never_emitted` — the panel still emits the entry.

- [ ] **Step 3: Strip the letterbox out of `SDKMirrorPanel`**

In `engine/appc/sdk_mirror_panel.py`:
- Delete the line `self._letterbox_emitted: bool = False` from `__init__`.
- Delete the whole letterbox block from `render_payload()` — the comment plus:
  ```python
  lb = tw.letterbox_snapshot()
  if lb["visible"] or self._letterbox_emitted:
      entries.append(lb)
  self._letterbox_emitted = bool(lb["visible"])
  ```
- Delete the `self._letterbox_emitted = False` line from the invalidate/reset method (~line 80).

Leave `TopWindow.letterbox_snapshot()` alone — `_pump_letterbox` is its consumer now.

- [ ] **Step 4: Delete the DOM bars**

In `native/assets/ui-cef/index.html`, delete these three lines:

```html
    <!-- Cutscene letterbox bars (MissionLib.StartCutscene..EndCutscene). -->
    <div id="sdk-letterbox-top" class="sdk-letterbox"></div>
    <div id="sdk-letterbox-bottom" class="sdk-letterbox"></div>
```

In `native/assets/ui-cef/css/sdk_mirror.css`, delete the comment block and rules:

```css
/* Cutscene letterbox bars — black strips anchored to the top and bottom
   edges. ... */
.sdk-letterbox { ... }
#sdk-letterbox-top { top: 0; }
#sdk-letterbox-bottom { bottom: 0; }
```

In `native/assets/ui-cef/js/sdk_mirror.js`, delete the call in `setSdkMirror`:

```js
  renderLetterbox(entries.find(e => e.type === "letterbox"));
```

and the entire `renderLetterbox` function together with its leading comment block.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_sdk_mirror_panel.py tests/unit/test_top_window.py -v`
Expected: PASS. `test_top_window.py`'s cutscene tests must still pass **unchanged** — the SDK-facing surface did not move.

- [ ] **Step 6: Commit — ONLY if Mark has cleared the shared tree**

```bash
git add native/assets/ui-cef/index.html native/assets/ui-cef/css/sdk_mirror.css \
        native/assets/ui-cef/js/sdk_mirror.js engine/appc/sdk_mirror_panel.py \
        tests/unit/test_sdk_mirror_panel.py
git commit -m "refactor(ui): delete the CEF letterbox — the renderer owns it now"
```

---

### Task 5: Gate + live verification

**Files:** none — this task only runs things.

- [ ] **Step 1: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: exit 0. It builds C++, runs pytest + ctest, and diffs failures against `tests/known_failures.txt` (whose only legitimate entries are the 7 headless-GL scorch/heat-glow `FrameTest`s). Any other named failure is a regression from this change — fix it, do not baseline it. In particular, **do not** add `LetterboxPassTest` to `known_failures.txt`: if the pass cannot render headless, the pass is wrong.

- [ ] **Step 2: Live-verify in the real game**

The bars are now GL, so no test in either suite proves that a cutscene actually looks right. Launch and watch a cutscene that raises UI:

```bash
./build/dauntless --developer
```

Load E1M1 (Developer → Load Mission…). During the opening cutscene, confirm:
1. The bars slide in and out, at roughly the same speed as before.
2. Subtitles render **over** the bars, not clipped by them.
3. Any crew menu the mission raises mid-cutscene is fully visible — top-left, not sheared by the top bar. This is the bug that motivated the change.
4. Opening the pause menu (ESC) mid-slide **freezes** the bars where they are, and they resume on unpause.

Report what you actually saw. Do not claim this passed without running it — and do not drive the desktop to do it: hand it to Mark if the run needs a human at the keyboard.

- [ ] **Step 3: Report**

Summarise: gate result, the four live checks, and anything that looked off. Then stop — Mark decides whether to commit, given the shared tree.

---

## Self-Review

**Spec coverage:** pass (Task 2) ✓; binding + `_REQUIRED_BINDINGS` (Task 2) ✓; `LetterboxAnimator` incl. smoothstep / zero-duration snap / frozen-dt hold / re-target (Task 1) ✓; host wiring at `_player_dt` (Task 3) ✓; all five deletions (Task 4) ✓; `TopWindow` untouched ✓; every test row in the spec's table has a task ✓; the "don't baseline the FrameTest" rule (Task 5) ✓; clamping in both the animator and `set_covered` ✓.

**Out-of-scope guarded:** `_tactical_hud_visible` and `bHideReticle` are not touched by any task; the missing HUD `z-index` values are deliberately left alone.
