# Scrollable Target List — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route mouse-wheel events to RmlUi when the cursor is over a scrollable panel element; fall through to camera zoom otherwise. The `.bc-panel-body` rule picks up `overflow-y: auto` so long target lists scroll; short lists render unchanged.

**Architecture:** Three native edits + one CSS edit. `Window` gets a public `add_scroll_y(dy)` helper. `UiSystem` installs a GLFW scroll callback that consults `RmlGLFW::ProcessScrollCallback` first and re-emits to the window's accumulator only when RmlUi didn't consume the event. `Window`'s own scroll-callback lambda goes away. The panel stylesheet adds overflow + scrollbar styling.

**Tech Stack:** C++17, GLFW, RmlUi (already linked), GTest for native unit tests. Python harness for end-to-end behaviour checks via the existing `_h.consume_scroll_y` path.

**Spec:** [docs/project/superpowers/specs/2026-05-12-scrollable-target-list-design.md](../specs/2026-05-12-scrollable-target-list-design.md).

---

## Task 1: `Window::add_scroll_y` helper

**Files:**
- Modify: [native/src/renderer/include/renderer/window.h](../../../native/src/renderer/include/renderer/window.h) — declare `add_scroll_y`
- Modify: [native/src/renderer/window.cc](../../../native/src/renderer/window.cc) — define `add_scroll_y`
- Modify: [native/tests/renderer/window_test.cc](../../../native/tests/renderer/window_test.cc) — add test

- [ ] **Step 1: Write the failing test**

Append to [native/tests/renderer/window_test.cc](../../../native/tests/renderer/window_test.cc) (inside the existing anonymous namespace, after the last `TEST(Window, ...)`):

```cpp
TEST(Window, AddScrollYAccumulatesIntoConsumeScrollY) {
    try {
        renderer::Window w(640, 480, "add-scroll-test", /*visible=*/false);

        // No scroll yet — accumulator starts at 0.
        EXPECT_DOUBLE_EQ(w.consume_scroll_y(), 0.0);

        w.add_scroll_y(1.5);
        w.add_scroll_y(-0.5);
        // Cumulative read drains.
        EXPECT_DOUBLE_EQ(w.consume_scroll_y(), 1.0);
        // Second read is zero (consume drained the accumulator).
        EXPECT_DOUBLE_EQ(w.consume_scroll_y(), 0.0);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}
```

- [ ] **Step 2: Build and run; verify it fails**

```bash
cmake --build build -j --target renderer_tests
./build/native/tests/renderer/renderer_tests --gtest_filter='Window.AddScrollYAccumulatesIntoConsumeScrollY'
```

Expected: FAIL or COMPILE ERROR — `add_scroll_y` doesn't exist on `renderer::Window`.

- [ ] **Step 3: Declare in the header**

Edit [native/src/renderer/include/renderer/window.h](../../../native/src/renderer/include/renderer/window.h). After the existing `consume_scroll_y()` declaration (around line 35), add:

```cpp
    /// Add `dy` to the internal scroll accumulator.  Used by UiSystem
    /// to re-emit scroll deltas that RmlUi declined to consume — keeps
    /// the camera-zoom path unchanged.
    void add_scroll_y(double dy) noexcept;
```

- [ ] **Step 4: Define in the .cc**

In [native/src/renderer/window.cc](../../../native/src/renderer/window.cc), after `Window::consume_scroll_y()` (around line 155–158), add:

```cpp
void Window::add_scroll_y(double dy) noexcept {
    scroll_y_accum_ += dy;
}
```

- [ ] **Step 5: Build and run; verify the test passes**

```bash
cmake --build build -j --target renderer_tests
./build/native/tests/renderer/renderer_tests --gtest_filter='Window.AddScrollYAccumulatesIntoConsumeScrollY'
```

Expected: PASS.

- [ ] **Step 6: Run all renderer tests to catch regressions**

```bash
./build/native/tests/renderer/renderer_tests
```

Expected: PASS (or skip on no-GL machines, like the existing tests).

- [ ] **Step 7: Commit**

```bash
git add native/src/renderer/include/renderer/window.h native/src/renderer/window.cc native/tests/renderer/window_test.cc
git commit -m "$(cat <<'EOF'
feat(window): Window::add_scroll_y for re-emitting filtered scroll deltas

UiSystem (next task) installs the scroll callback first and consults
RmlUi before the camera.  When the UI declines, UiSystem calls
add_scroll_y(dy) so the existing consume_scroll_y -> camera-zoom path
keeps working unchanged.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: UiSystem scroll callback routes via RmlUi

**Files:**
- Modify: [native/src/ui/UiSystem.cc](../../../native/src/ui/UiSystem.cc) — add `scroll_cb`, wire `glfwSetScrollCallback`
- New manual-verification doc step (no automated C++ test for the callback itself — see notes)

The RmlUi path is hard to unit-test in isolation because `RmlGLFW::ProcessScrollCallback`'s return value depends on the live cursor position + the live DOM. The C++ unit test infrastructure here has no offscreen RmlUi document fixture, and adding one is disproportionate cost. We rely on:
- **Static review**: the callback is a 6-line if/else.
- **Manual verification step** at the end of this task.
- **Python integration**: Task 4 covers end-to-end via a probe.

- [ ] **Step 1: Add include**

In [native/src/ui/UiSystem.cc](../../../native/src/ui/UiSystem.cc), after the existing `#include "ui/PanelDocument.h"` (line 4), add:

```cpp
#include <renderer/window.h>
```

(The CMake target for `ui` may already link `renderer`; if compile fails on link, add `renderer` to UiSystem's `target_link_libraries` in `native/src/ui/CMakeLists.txt`.)

- [ ] **Step 2: Add `scroll_cb` in the anonymous namespace**

In the anonymous namespace inside `UiSystem.cc` (after the `char_cb` definition at line 49), add:

```cpp
void scroll_cb(GLFWwindow* w, double /*xoffset*/, double yoffset) {
    bool consumed = false;
    if (g_input_ctx) {
        consumed = RmlGLFW::ProcessScrollCallback(
            g_input_ctx, yoffset, /*key_modifier_state=*/0);
    }
    if (!consumed) {
        if (auto* win = static_cast<renderer::Window*>(
                glfwGetWindowUserPointer(w))) {
            win->add_scroll_y(yoffset);
        }
    }
}
```

- [ ] **Step 3: Wire `glfwSetScrollCallback`**

In `UiSystem` constructor, after the existing GLFW callback registrations (around line 117), add:

```cpp
    glfwSetScrollCallback(window, scroll_cb);
```

And update the explanatory comment block at line 109–112 (which currently says "Mouse-wheel forwarding into RmlUi can be added later") to reflect the new wiring:

```cpp
    // Wire GLFW input → RmlUi context.  Scroll is filtered: RmlUi
    // attempts to consume the event first (cursor over a scrollable
    // element), and if it declines the delta is forwarded to
    // renderer::Window's accumulator for camera-zoom.
    g_input_ctx = context_;
    glfwSetCursorPosCallback(window, cursor_pos_cb);
    glfwSetMouseButtonCallback(window, mouse_button_cb);
    glfwSetKeyCallback(window, key_cb);
    glfwSetCharCallback(window, char_cb);
    glfwSetScrollCallback(window, scroll_cb);
```

- [ ] **Step 4: Build the host binary**

```bash
cmake --build build -j
```

Expected: clean build. If linker complains about missing `renderer::Window` symbols inside `ui`, add `renderer` to `ui` target's link list in `native/src/ui/CMakeLists.txt`:

```cmake
target_link_libraries(ui PRIVATE renderer)
```

- [ ] **Step 5: Run all native tests**

```bash
ctest --test-dir build --output-on-failure
```

Expected: PASS. The new callback isn't wired by any test, so this is a smoke check.

- [ ] **Step 6: Manual verification (camera zoom still works)**

Launch the host:

```bash
./build/open_stbc
```

With the cursor over open scene (not over a panel), scroll the mouse wheel. Expected: camera zooms in/out as before. This proves the RmlUi-not-consumed → camera-fallthrough path works.

- [ ] **Step 7: Commit**

```bash
git add native/src/ui/UiSystem.cc
# also native/src/ui/CMakeLists.txt if you needed to edit it
git commit -m "$(cat <<'EOF'
feat(ui): route mouse-wheel through RmlUi before camera zoom

Installs a GLFW scroll callback in UiSystem that consults
RmlGLFW::ProcessScrollCallback first.  When RmlUi consumes the event
(cursor over a scrollable panel element), nothing else happens.  When
it declines, the delta is re-emitted via renderer::Window::add_scroll_y
so the existing camera-zoom path runs unchanged.

Removes the long-standing 'wheel-forwarding will be added later'
comment.  Window's own glfwSetScrollCallback is removed in the next
task — UiSystem now owns the callback because it must filter first.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Remove `Window`'s own scroll callback

**Files:**
- Modify: [native/src/renderer/window.cc](../../../native/src/renderer/window.cc) — delete the `glfwSetScrollCallback` lambda at lines 51–58

UiSystem now installs the scroll callback. Window's own scroll callback would be overwritten anyway, but it's dead code and should be removed for clarity.

- [ ] **Step 1: Delete the lambda**

In [native/src/renderer/window.cc](../../../native/src/renderer/window.cc), remove the block at approximately lines 51–58:

```cpp
    // Wire mouse-wheel events into scroll_y_accum_. The user pointer lets
    // ...
    glfwSetScrollCallback(handle_, [](GLFWwindow* w, double, double yoffset) {
        if (auto* self = static_cast<Window*>(glfwGetWindowUserPointer(w))) {
            self->scroll_y_accum_ += yoffset;
        }
    });
```

Leave the `glfwSetWindowUserPointer(handle_, this);` call (line 53) — `UiSystem` reads that user pointer.

- [ ] **Step 2: Run the existing window test**

```bash
cmake --build build -j --target renderer_tests
./build/native/tests/renderer/renderer_tests --gtest_filter='Window.*'
```

Expected: PASS. The `add_scroll_y` test from Task 1 still works (it doesn't rely on a GLFW callback — it calls `add_scroll_y` directly).

- [ ] **Step 3: Manual verification (camera zoom)**

```bash
cmake --build build -j
./build/open_stbc
```

With the cursor in open scene, scroll. Expected: camera zooms (proves UiSystem's scroll callback is the one wired and that its fallthrough path works).

- [ ] **Step 4: Commit**

```bash
git add native/src/renderer/window.cc
git commit -m "$(cat <<'EOF'
refactor(window): drop Window's scroll callback — UiSystem owns it now

UiSystem installs the scroll callback (one task back) so it can filter
through RmlUi before the camera sees the event.  Window's own lambda
would be overwritten by UiSystem's anyway, and removing it makes the
event ownership unambiguous.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `.bc-panel-body` overflow + scrollbar styling

**Files:**
- Modify: [native/assets/ui/components.rcss](../../../native/assets/ui/components.rcss) — extend `.bc-panel-body`, add scrollbar rules
- Test: [tests/host/test_panel_overflow.py](../../../tests/host/test_panel_overflow.py) — new file (asserts the .rcss contains the rule)

- [ ] **Step 1: Write the failing test**

```python
"""The .bc-panel-body rule in components.rcss declares overflow-y: auto
and a tunable max-height so long target lists scroll.  Scrollbar rules
match the panel palette.

This test asserts the file's textual content; it doesn't execute RmlUi.
A runtime check would require parsing the compiled DOM, which our test
harness doesn't expose."""
from pathlib import Path


_RCSS = Path(__file__).resolve().parents[2] / "native" / "assets" / "ui" / "components.rcss"


def _rcss_text():
    return _RCSS.read_text(encoding="utf-8")


def test_bc_panel_body_has_overflow_y_auto():
    text = _rcss_text()
    # The .bc-panel-body block must include overflow-y: auto somewhere.
    # Use a substring check rather than parsing CSS — RmlUi's RCSS dialect
    # isn't a perfect CSS subset.
    body_block_start = text.index(".bc-panel-body")
    body_block_end   = text.index("}", body_block_start)
    body_block = text[body_block_start:body_block_end]
    assert "overflow-y" in body_block
    assert "auto" in body_block


def test_bc_panel_body_has_max_height():
    text = _rcss_text()
    body_block_start = text.index(".bc-panel-body")
    body_block_end   = text.index("}", body_block_start)
    body_block = text[body_block_start:body_block_end]
    assert "max-height" in body_block


def test_components_rcss_styles_vertical_scrollbar():
    text = _rcss_text()
    assert "scrollbar-vertical" in text
    assert "sliderbar"          in text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/host/test_panel_overflow.py -v
```

Expected: FAIL — `.bc-panel-body` doesn't have overflow-y; no scrollbar rules in the file.

- [ ] **Step 3: Extend `.bc-panel-body` and add scrollbar rules**

Open [native/assets/ui/components.rcss](../../../native/assets/ui/components.rcss). Find the `.bc-panel-body` rule near line 82. Inside the existing rule body (don't add a duplicate block), add:

```css
.bc-panel-body {
    /* existing rules — keep them */
    overflow-y: auto;
    max-height: 70vh;
}
```

Append a new section to the end of the file:

```css
/* ── Scrollbar styling ─────────────────────────────────────────────────
   Used by .bc-panel-body when its content overflows max-height.  Colours
   read from --panel-accent so each panel's affiliation palette flows
   through automatically. */

scrollbar-vertical {
    width: 12dp;
}

slidertrack {
    background-color: rgba(20, 20, 30, 160);
}

sliderbar {
    background-color: var(--panel-accent, #66c2ff);
    min-height: 24dp;
    border-radius: 4dp;
}

sliderbar:hover {
    background-color: var(--panel-accent-hover, #99e0ff);
}
```

(RCSS uses 8-bit-channel rgba in some implementations rather than 0–1 alpha — adjust the `160` if RmlUi's parser rejects it. If unsure, use a flat hex `#14141eaa`.)

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/host/test_panel_overflow.py -v
```

Expected: PASS, 3 tests.

- [ ] **Step 5: Rebuild and visually verify**

```bash
cmake --build build -j
./build/open_stbc
```

Load any mission. The targets panel renders as before (no scrollbar visible because content fits). Resize the window vertically to compress the panel below the content height — a vertical scrollbar should appear, styled in the panel's accent colour.

Hover the cursor over the panel body and scroll: panel scrolls. Hover over the title bar and scroll: camera zooms (the title bar has no `overflow-y: auto`, so RmlUi doesn't consume). Hover over open scene and scroll: camera zooms.

- [ ] **Step 6: Commit**

```bash
git add native/assets/ui/components.rcss tests/host/test_panel_overflow.py
git commit -m "$(cat <<'EOF'
feat(ui): scrollable .bc-panel-body with palette-aware scrollbar

Adds overflow-y: auto and max-height: 70vh to .bc-panel-body so long
target lists scroll inside the panel.  Scrollbar styling reads from
--panel-accent / --panel-accent-hover so each panel's affiliation
palette flows through.  RmlUi's hit testing then routes wheel events
to the scrollable body when the cursor is over content, falling
through to camera zoom otherwise.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: End-to-end manual smoke

This task is checklist-only — no new test files.  Use it to convince yourself the routing matrix is right.  Run the host (`./build/open_stbc`), then exercise the matrix:

| Cursor location | Action | Expected |
|---|---|---|
| Open scene | Scroll wheel | Camera zooms |
| Over panel title bar | Scroll wheel | Camera zooms (title bar isn't scrollable) |
| Over panel body, list fits | Scroll wheel | Camera zooms (no overflow, RmlUi doesn't consume) |
| Over panel body, list overflows | Scroll wheel | Panel scrolls (camera unchanged) |
| Over panel body, scrolled to bottom, scroll down further | Scroll wheel | Stays at bottom — RmlUi consumes but doesn't actually advance content. *Verify camera does not zoom.* If RmlUi releases the event at extents, that's a Phase-2 follow-up; document the behaviour. |
| Click and drag the scrollbar thumb | Drag | Panel scrolls smoothly |

- [ ] **Step 1: Walk the matrix**

Load a mission with enough ships to overflow the panel (the drydock mission shown in the spec's reference screenshot is the canonical test case once Plan A lands). For now, the SHIP_GATE_MISSION with two Galaxies is enough to verify the four primary rows.

- [ ] **Step 2: If anything misbehaves, capture the symptom**

Open an issue describing the matrix cell that failed. Don't try to fix end-to-end issues by guessing at the C++ — re-derive from the spec.

- [ ] **Step 3: No commit** (manual smoke step)

If everything checks out, the plan is complete. Move to Plan A's integration with this work — once child emitters land, the drydock targets row will scroll naturally.

---

## Self-review checklist

- [ ] Each spec section is covered by at least one task:
  - B.1 Native scroll routing → Task 2
  - B.2 Window API addition → Task 1
  - B.3 Init ordering / Window scroll callback removal → Task 3
  - B.4 Panel CSS — overflow + max-height → Task 4
  - B.5 Scrollbar styling → Task 4
  - B.6 Testing (native + Python) → Tasks 1 and 4 (unit), Task 5 (manual matrix)
- [ ] No "TBD" / "TODO" / "fill in details" markers.
- [ ] Method names match across tasks (`add_scroll_y`, not `accumulate_scroll_y`).
- [ ] CSS class name matches the existing codebase (`bc-panel-body`, not `panel-body`).
- [ ] Manual verification steps named explicitly — automated C++ test for the RmlUi-routing callback would require offscreen RmlUi document infrastructure that doesn't exist in `native/tests/`; flagged in Task 2.
- [ ] Camera-zoom regression covered by the manual matrix in Task 5.
