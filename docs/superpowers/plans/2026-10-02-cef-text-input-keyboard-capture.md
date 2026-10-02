# In-Game Keyboard Capture for CEF Text Inputs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** While an editable element in the in-game CEF page has focus, the
game reads no keys at all. Typed text and editing keys go to CEF. The SPV's
Move, Rotate and Scale value rows become click-to-edit as the first consumer.

**Architecture:**

- **Native gate.** A pure C++ `KeyGate` sits inside `Window::key_state`, which
  every key read in the engine already goes through. A structural test keeps
  it the only raw read.
- **Page reports focus.** A small `text_capture.js` reports focus and blur.
- **Python arbitrates.** `TextCaptureController` turns the gate on and off,
  forwards the text queue to CEF while captured, and enforces the release
  triggers. Native clears the gate itself on page load and on renderer crash.

**Tech Stack:** C++20 (GLFW, CEF OSR, pybind11, gtest), Python 3.11 (pytest),
vanilla JS/CSS in the CEF page.

**Spec:** `docs/superpowers/specs/2026-10-02-cef-text-input-keyboard-capture-design.md`.
Read it before starting any task.

## Global Constraints

- **Branch** `feat/cef-text-capture`.
  - Never commit to `main`; check `git branch --show-current` before every
    commit.
  - Stage with explicit pathspecs only, never `git add -A` or `git add .`.
- **Banned git commands** (shared checkout): `git checkout -- <path>`,
  `git checkout .`, `git restore`, `git stash`, `git clean`,
  `git reset --hard`.
  - To mutate a file temporarily, use `cp file /tmp/bak` … `cp /tmp/bak file`,
    then `diff` to prove the restore.
- **Build** only with `cmake --build build -j` from the project root.
  - Never run cmake from inside `native/`.
  - Never change `CMAKE_BUILD_TYPE`.
  - Outputs: `build/dauntless`, `build/python/_dauntless_host.cpython-*.so`,
    `build/native/tests/renderer/renderer_tests`.
- **Never launch the game.** Live checks are Mark's (spec §8).
- **Nothing passes the gate while captured.** No F12, no Cmd+R, no dev keys.
  Mouse buttons and scroll are never gated.
- **Edit-command modifier:** `GLFW_MOD_SUPER` on `__APPLE__`, else
  `GLFW_MOD_CONTROL`.
- **Event names** are exact:
  - `kbd/focus:<panel-name>` (empty name allowed) and `kbd/blur`;
  - `ship-property-viewer/coord_set:{"axis":i,"value":v}`,
    `scale_set:{"index":i,"value":v}` and `rotate_set:{"axis":i,"value":v}`.
- **JS globals:** `window.__dauntlessBlurText()`,
  `window.__dauntlessTextCancel(el)`, `window.__dauntlessTextCommit(el)`.
- **Gate before merge:** `scripts/check_tests.sh` exits 0.

## Review Focus

1. **A cleared SPV field + Enter** must revert, not move the target to 0.
   (`Number('')` is `0`.) Pinned in Task 9.
2. **A decimal comma** (`1,5`) commits 1.5 rather than reverting. Pinned in
   Task 9.
3. **A fire key held when a field gains focus.** The game sees a clean release
   (firing stops) and no further press while focused. Pinned in Task 7.
4. **Tabbing between two fields** delivers only `focus:` again, with no blur
   between. Capture must stay on, and no blur payload may be emitted. Moving to
   an *untagged* field must release. Pinned in Task 5.
5. **The Esc that blurred a field is still held** on the next frames. It must
   not open the pause menu until it is released and pressed again. Pinned in
   Task 7.

---

### Task 1: `KeyGate`, the pure gate

**Files:**
- Create: `native/src/renderer/include/renderer/key_gate.h`
- Create: `native/src/renderer/key_gate.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (add `key_gate.cc` after `text_input.cc` in `add_library(renderer STATIC ...)`, about line 133)
- Create: `native/tests/renderer/key_gate_test.cc`
- Modify: `native/tests/renderer/CMakeLists.txt` (add `key_gate_test.cc` after `text_input_test.cc`, about line 83)

**Interfaces:**
- Produces: `renderer::KeyGate`, with `void capture() noexcept`,
  `void release(const std::vector<int>& raw_down)`,
  `bool captured() const noexcept` and `bool report(int key, bool raw) noexcept`.

- [ ] **Step 1: Write the failing gtest**

`native/tests/renderer/key_gate_test.cc`:

```cpp
#include <gtest/gtest.h>
#include <renderer/key_gate.h>

using renderer::KeyGate;

TEST(KeyGate, PassesRawThroughWhenNotCaptured) {
    KeyGate g;
    EXPECT_FALSE(g.captured());
    EXPECT_TRUE(g.report(87, true));
    EXPECT_FALSE(g.report(87, false));
}

TEST(KeyGate, CapturedReportsEveryKeyUp) {
    KeyGate g;
    g.capture();
    EXPECT_TRUE(g.captured());
    EXPECT_FALSE(g.report(87, true));
    EXPECT_FALSE(g.report(32, true));
    EXPECT_FALSE(g.report(256, false));
}

TEST(KeyGate, KeyHeldThroughReleaseStaysUpUntilPhysicallyReleased) {
    KeyGate g;
    g.capture();
    g.release({256});                    // Esc still down when capture ends
    EXPECT_FALSE(g.captured());
    EXPECT_FALSE(g.report(256, true));   // still held: masked
    EXPECT_FALSE(g.report(256, true));
    EXPECT_FALSE(g.report(256, false));  // released: unmasks
    EXPECT_TRUE(g.report(256, true));    // a NEW press is reported
}

TEST(KeyGate, KeyPressedAfterReleaseIsNotMasked) {
    KeyGate g;
    g.capture();
    g.release({256});
    EXPECT_TRUE(g.report(87, true));     // W was not down at release
}

TEST(KeyGate, ReleaseWithNothingDownMasksNothing) {
    KeyGate g;
    g.capture();
    g.release({});
    EXPECT_TRUE(g.report(256, true));
}

TEST(KeyGate, StrayReleaseWhileNotCapturedDoesNotMask) {
    KeyGate g;
    g.release({256});
    EXPECT_TRUE(g.report(256, true));
}

TEST(KeyGate, SecondCaptureIsHarmlessAndClearsAStaleMask) {
    KeyGate g;
    g.capture();
    g.release({256});
    g.capture();
    g.capture();
    EXPECT_FALSE(g.report(256, true));
    g.release({});
    EXPECT_TRUE(g.report(256, true));    // the old mask did not survive
}
```

Add `key_gate_test.cc` to `native/tests/renderer/CMakeLists.txt` right after
`text_input_test.cc`.

- [ ] **Step 2: Run it and watch it fail to build**

Run: `cmake --build build -j --target renderer_tests`
Expected: a compile error, `renderer/key_gate.h: No such file`.

- [ ] **Step 3: Implement**

`native/src/renderer/include/renderer/key_gate.h`:

```cpp
// native/src/renderer/include/renderer/key_gate.h
//
// The one filter between GLFW key state and everything that reads keys.
// While a CEF text field has focus the gate is CAPTURED and every key reads
// up. On release, keys still physically down stay masked until they are
// released, so the key that ended the edit (Enter, Esc) is never a fresh
// game press on the next frame.
// Spec: docs/superpowers/specs/2026-10-02-cef-text-input-keyboard-capture-design.md S2.1
#pragma once

#include <unordered_set>
#include <vector>

namespace renderer {

class KeyGate {
public:
    void capture() noexcept;
    void release(const std::vector<int>& raw_down);
    bool captured() const noexcept { return captured_; }
    bool report(int key, bool raw) noexcept;

private:
    bool captured_ = false;
    std::unordered_set<int> masked_;
};

}  // namespace renderer
```

`native/src/renderer/key_gate.cc`:

```cpp
// native/src/renderer/key_gate.cc
#include "renderer/key_gate.h"

namespace renderer {

void KeyGate::capture() noexcept {
    captured_ = true;
    masked_.clear();
}

void KeyGate::release(const std::vector<int>& raw_down) {
    if (!captured_) return;
    captured_ = false;
    masked_.insert(raw_down.begin(), raw_down.end());
}

bool KeyGate::report(int key, bool raw) noexcept {
    if (captured_) return false;
    auto it = masked_.find(key);
    if (it != masked_.end()) {
        if (raw) return false;
        masked_.erase(it);
    }
    return raw;
}

}  // namespace renderer
```

Add `key_gate.cc` to `native/src/renderer/CMakeLists.txt` after `text_input.cc`.

- [ ] **Step 4: Run it and watch it pass**

Run: `cmake --build build -j --target renderer_tests && ./build/native/tests/renderer/renderer_tests --gtest_filter='KeyGate.*'`
Expected: 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add native/src/renderer/include/renderer/key_gate.h native/src/renderer/key_gate.cc native/src/renderer/CMakeLists.txt native/tests/renderer/key_gate_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "feat(input): KeyGate -- pure key-capture filter with release mask"
```

---

### Task 2: Gate the window's key reads; bindings; structural guard

**Files:**
- Modify: `native/src/renderer/include/renderer/window.h` (`key_state` at about line 42; private members at about 106-117)
- Modify: `native/src/renderer/window.cc` (`key_state` at about 195-198; move constructor and assignment at about 123-170)
- Modify: `native/src/host/host_bindings.cc` (the snapshot loop at about 1850-1852; new bindings beside `key_state` at about 6106)
- Modify: `engine/host_io.py` (`_REQUIRED_BINDINGS` at about line 42; new wrappers after `key_pressed` at about 163)
- Create: `tests/tools/test_raw_key_reads.py`
- Modify: `tests/host/test_text_input_bindings.py`

**Interfaces:**
- Consumes: `renderer::KeyGate` (Task 1).
- Produces:
  - `Window::key_state(int) noexcept` (no longer `const`);
  - `void Window::set_key_capture(bool on)` and
    `bool Window::key_capture_active() const noexcept`;
  - Python bindings `set_key_capture(on: bool) -> None` and
    `key_capture_active() -> bool`;
  - `host_io.set_key_capture(on: bool) -> None` and
    `host_io.key_capture_active() -> bool`.

- [ ] **Step 1: Write the failing structural guard**

`tests/tools/test_raw_key_reads.py`:

```python
"""The keyboard-capture guarantee is structural: every key the engine reads
goes through Window::key_state, which filters through the KeyGate. A raw
glfwGetKey anywhere else in native/src would let keys leak into the game
while a CEF text field has focus.

Spec: docs/superpowers/specs/2026-10-02-cef-text-input-keyboard-capture-design.md S2.2, S7.3
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "native" / "src"
WINDOW_CC = NATIVE / "renderer" / "window.cc"
ALLOWED = {"Window::key_state", "Window::set_key_capture"}

# glfwGetKeyName( does NOT match: the name continues past "Key".
_CALL = re.compile(r"\bglfwGetKey\s*\(")


def _blank(text):
    return re.sub(r"[^\n]", " ", text)


def _strip(src):
    """Blank out comments and string/char literals, keeping offsets and
    newlines. Only applied to window.cc, which has no raw string literals."""
    out = []
    i, n = 0, len(src)
    while i < n:
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(_blank(src[i:j])); i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(_blank(src[i:j])); i = j
        elif src[i] in "\"'":
            q, j = src[i], i + 1
            while j < n and src[j] != q:
                j += 2 if src[j] == "\\" else 1
            j = min(j + 1, n)
            out.append(q + _blank(src[i + 1:j - 1]) + (q if j - i >= 2 else ""))
            i = j
        else:
            out.append(src[i]); i += 1
    return "".join(out)


def enclosing_functions(src):
    """For each glfwGetKey( call in `src`, the qualified name of the
    outermost function body containing it (namespace / extern "C" blocks are
    transparent), or None when the call is not inside a function."""
    s = _strip(src)
    stack = []          # ("ns" | "fn" | "block", name)
    boundary = 0
    hits = []
    for m in re.finditer(r"[{};]|\bglfwGetKey\s*\(", s):
        tok = m.group(0)
        if tok == "{":
            header = s[boundary:m.start()]
            in_fn = any(k == "fn" for k, _ in stack)
            if in_fn:
                stack.append(("block", None))
            elif re.search(r'\bnamespace\b|\bextern\s*"', header):
                stack.append(("ns", None))
            else:
                nm = re.search(r"([A-Za-z_]\w*(?:::~?[A-Za-z_]\w*)+)\s*\(", header)
                stack.append(("fn", nm.group(1) if nm else None))
            boundary = m.end()
        elif tok == "}":
            if stack:
                stack.pop()
            boundary = m.end()
        elif tok == ";":
            boundary = m.end()
        else:
            hits.append(next((nm for k, nm in stack if k == "fn"), None))
    return hits


def test_the_guard_sees_a_planted_offender():
    planted = (
        "namespace renderer {\n"
        "bool Window::key_state(int k) noexcept { return glfwGetKey(h, k); }\n"
        "void Window::poll() { auto f = [&]{ glfwGetKey(h, 1); }; }\n"
        "}\n"
    )
    assert enclosing_functions(planted) == ["Window::key_state", "Window::poll"]


def test_the_guard_ignores_comments_strings_and_key_name():
    src = ('// glfwGetKey(h, 1)\n/* glfwGetKey( */\n'
           'void Window::x() { const char* s = "glfwGetKey("; glfwGetKeyName(1, 2); }\n')
    assert enclosing_functions(src) == []


def test_window_cc_reads_raw_keys_only_inside_the_gate():
    found = enclosing_functions(WINDOW_CC.read_text())
    assert found, "window.cc has no glfwGetKey at all -- the guard is vacuous"
    assert set(found) == ALLOWED, found


def test_no_other_native_file_reads_raw_keys():
    offenders = []
    for path in sorted(NATIVE.rglob("*")):
        if path.suffix not in (".cc", ".cpp", ".h", ".mm") or path == WINDOW_CC:
            continue
        src = path.read_text(errors="replace")
        if "glfwGetKey" not in src:
            continue
        if _CALL.search(re.sub(r"//[^\n]*", "", src)):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, (
        "raw glfwGetKey outside Window::key_state -- read keys through "
        "g_window->key_state so the KeyGate filters them: %s" % offenders)
```

Add to `tests/host/test_text_input_bindings.py`:

```python
import pytest


def test_capture_bindings_exist_and_are_required():
    for name in ("set_key_capture", "key_capture_active"):
        assert hasattr(h, name), name
    assert {"set_key_capture", "key_capture_active"} <= host_io._REQUIRED_BINDINGS


def test_key_capture_is_inactive_without_a_window():
    assert h.key_capture_active() is False


def test_set_key_capture_without_a_window_raises():
    with pytest.raises(RuntimeError):
        h.set_key_capture(True)
```

- [ ] **Step 2: Run both and watch them fail**

Run: `uv run pytest tests/tools/test_raw_key_reads.py tests/host/test_text_input_bindings.py -v`
Expected:
- `test_window_cc_reads_raw_keys_only_inside_the_gate` FAILS, because
  `found == {"Window::key_state"}` and `set_key_capture` doesn't exist yet;
- `test_no_other_native_file_reads_raw_keys` FAILS, naming
  `native/src/host/host_bindings.cc`;
- the three new binding tests FAIL;
- both guard self-tests PASS.

- [ ] **Step 3: Implement `Window`**

In `window.h`:

- add `#include "renderer/key_gate.h"` beside `#include "renderer/text_input.h"`
  (also add `#include <unordered_set>`);
- replace the `key_state` declaration:

```cpp
    /// State of a GLFW keyboard key AS THE GAME SEES IT: the raw GLFW level
    /// filtered through the KeyGate (all keys up while a CEF text field holds
    /// the keyboard; a key held across release stays up until released).
    /// The ONLY raw key read in native/src -- tests/tools/test_raw_key_reads.py.
    /// Not const: the gate's release mask updates as it observes releases.
    bool key_state(int glfw_key) noexcept;

    /// Hand the keyboard to (on) or take it back from (off) a CEF text field.
    /// Off masks every polled key still physically down (KeyGate::release).
    void set_key_capture(bool on);
    bool key_capture_active() const noexcept { return key_gate_.captured(); }
```

- add private members after `TextEventQueue text_events_;`:

```cpp
    KeyGate key_gate_;
    std::unordered_set<int> polled_keys_;   // every key key_state was asked about
```

In `window.cc`, replace `key_state`:

```cpp
bool Window::key_state(int glfw_key) noexcept {
    if (!handle_) return false;
    polled_keys_.insert(glfw_key);
    return key_gate_.report(glfw_key, glfwGetKey(handle_, glfw_key) == GLFW_PRESS);
}

void Window::set_key_capture(bool on) {
    if (on) {
        key_gate_.capture();
        return;
    }
    // Only keys the game has polled can matter: it reads keys only through
    // key_state, and a key first polled after release never produces an edge
    // (key_pressed's first query records prev = now). Scanning the full
    // GLFW range instead would hit its code gaps, which raise
    // GLFW_INVALID_ENUM.
    std::vector<int> down;
    if (handle_) {
        for (int k : polled_keys_) {
            if (glfwGetKey(handle_, k) == GLFW_PRESS) down.push_back(k);
        }
    }
    key_gate_.release(down);
}
```

In the move constructor's initialiser list, after
`text_events_(std::move(other.text_events_))`, add
`, key_gate_(std::move(other.key_gate_)), polled_keys_(std::move(other.polled_keys_))`.
In the move-assignment body, beside the other member copies, add
`key_gate_ = std::move(other.key_gate_); polled_keys_ = std::move(other.polled_keys_);`.
Read both functions first and keep their existing member order.

- [ ] **Step 4: Implement the snapshot fix and bindings**

In `host_bindings.cc` at about line 1850, replace:

```cpp
    for (auto& [k, prev] : g_prev_key_state) {
        prev = (glfwGetKey(g_window->native_handle(), k) == GLFW_PRESS);
    }
```

with:

```cpp
    for (auto& [k, prev] : g_prev_key_state) {
        // Through the gate, like every other key read: a raw glfwGetKey here
        // would make prev disagree with key_pressed's gated `now`.
        prev = g_window->key_state(k);
    }
```

Directly after the `key_state` binding (about line 6106-6115), add these. They
sit outside any `DAUNTLESS_ENABLE_CEF` block, so they exist in every build:

```cpp
    m.def("set_key_capture",
          [](bool on) {
              if (!g_window) {
                  throw std::runtime_error("set_key_capture: init must be called first");
              }
              g_window->set_key_capture(on);
          },
          py::arg("on"),
          "Hand the keyboard to a focused CEF text field (True) or give it back "
          "(False). While captured every key_state/key_pressed reads False.");

    m.def("key_capture_active",
          []() { return g_window ? g_window->key_capture_active() : false; },
          "True while a CEF text field holds the keyboard. Native resets it on "
          "page load and on renderer crash.");
```

- [ ] **Step 5: Implement the `host_io` wrappers**

In `_REQUIRED_BINDINGS`, directly after the line
`"drain_text_events", "cef_send_key_event", "request_relaunch",`, add:

```python
    "set_key_capture", "key_capture_active",
```

After `key_pressed`, add:

```python
def set_key_capture(on: bool) -> None:
    """Hand the keyboard to a focused CEF text field (True) or give it back
    (False). Only engine.ui.text_capture calls this."""
    if _h is None:
        return
    _h.set_key_capture(bool(on))


def key_capture_active() -> bool:
    """True while a CEF text field holds the keyboard (native clears it on
    page load and renderer crash). False headless."""
    if _h is None:
        return False
    return bool(_h.key_capture_active())
```

- [ ] **Step 6: Build and run**

Run: `cmake --build build -j && uv run pytest tests/tools/test_raw_key_reads.py tests/host/test_text_input_bindings.py -v && ./build/native/tests/renderer/renderer_tests --gtest_filter='KeyGate.*:Window*'`
Expected: all PASS. `window_test.cc` still compiles; it calls `key_state` on a
non-const `Window`.

- [ ] **Step 7: Commit**

```bash
git branch --show-current
git add native/src/renderer/include/renderer/window.h native/src/renderer/window.cc native/src/host/host_bindings.cc engine/host_io.py tests/tools/test_raw_key_reads.py tests/host/test_text_input_bindings.py
git commit -m "feat(input): gate every key read through KeyGate; set_key_capture binding"
```

---

### Task 3: Edit commands (clipboard and undo)

**Files:**
- Modify: `native/src/renderer/include/renderer/text_input.h`
- Modify: `native/src/renderer/text_input.cc`
- Modify: `native/src/renderer/window.cc` (the `glfwSetKeyCallback` at about 84-89)
- Modify: `native/src/ui_cef/cef_lifecycle.h` (beside `send_key_event`, about line 84)
- Modify: `native/src/ui_cef/cef_lifecycle.cc` (after `send_key_event`)
- Modify: `native/src/host/host_bindings.cc` (`cef_send_key_event` at about 6399)
- Modify: `engine/host_io.py` (the `drain_text_events` docstring)
- Modify: `native/tests/renderer/text_input_test.cc`

**Interfaces:**
- Produces:
  - `renderer::kTextEventEdit == 2`;
  - `enum class renderer::EditCommand : int { None=0, SelectAll=1, Copy=2, Paste=3, Cut=4, Undo=5, Redo=6 }`;
  - `renderer::EditCommand renderer::edit_command_for(char letter, int mods) noexcept`;
  - `void dauntless::ui_cef::edit_command(int cmd)`;
  - queue tuples `(2, cmd, scancode, action, mods)`, which `cef_send_key_event`
    accepts.

- [ ] **Step 1: Write the failing gtest**

Append to `native/tests/renderer/text_input_test.cc`:

```cpp
using renderer::EditCommand;
using renderer::edit_command_for;

#if defined(__APPLE__)
constexpr int kPrimary = GLFW_MOD_SUPER;
constexpr int kWrong = GLFW_MOD_CONTROL;
#else
constexpr int kPrimary = GLFW_MOD_CONTROL;
constexpr int kWrong = GLFW_MOD_SUPER;
#endif

TEST(EditCommand, PrimaryModifierLetters) {
    EXPECT_EQ(edit_command_for('a', kPrimary), EditCommand::SelectAll);
    EXPECT_EQ(edit_command_for('c', kPrimary), EditCommand::Copy);
    EXPECT_EQ(edit_command_for('v', kPrimary), EditCommand::Paste);
    EXPECT_EQ(edit_command_for('x', kPrimary), EditCommand::Cut);
    EXPECT_EQ(edit_command_for('z', kPrimary), EditCommand::Undo);
    EXPECT_EQ(edit_command_for('y', kPrimary), EditCommand::Redo);
    EXPECT_EQ(edit_command_for('V', kPrimary), EditCommand::Paste);  // case-insensitive
}

TEST(EditCommand, ShiftZIsRedoAndOtherShiftLettersAreNothing) {
    EXPECT_EQ(edit_command_for('z', kPrimary | GLFW_MOD_SHIFT), EditCommand::Redo);
    EXPECT_EQ(edit_command_for('v', kPrimary | GLFW_MOD_SHIFT), EditCommand::None);
}

TEST(EditCommand, NoOrWrongOrExtraModifierIsNothing) {
    EXPECT_EQ(edit_command_for('v', 0), EditCommand::None);
    EXPECT_EQ(edit_command_for('v', GLFW_MOD_SHIFT), EditCommand::None);
    EXPECT_EQ(edit_command_for('v', kWrong), EditCommand::None);
    EXPECT_EQ(edit_command_for('v', kPrimary | GLFW_MOD_ALT), EditCommand::None);
    EXPECT_EQ(edit_command_for('v', kPrimary | kWrong), EditCommand::None);
    EXPECT_EQ(edit_command_for('q', kPrimary), EditCommand::None);
}

TEST(EditCommand, KindIsDistinctFromCharAndKey) {
    EXPECT_EQ(renderer::kTextEventEdit, 2);
    EXPECT_NE(renderer::kTextEventEdit, renderer::kTextEventChar);
    EXPECT_NE(renderer::kTextEventEdit, renderer::kTextEventKey);
}
```

- [ ] **Step 2: Run it and watch it fail to build**

Run: `cmake --build build -j --target renderer_tests`
Expected: compile errors, because `EditCommand` and `edit_command_for` are
undeclared.

- [ ] **Step 3: Implement the pure part**

In `text_input.h`:

- after `constexpr int kTextEventKey = 1;`, add:

```cpp
constexpr int kTextEventEdit = 2;   // code = EditCommand (Cmd/Ctrl + A/C/V/X/Z/Y)

/// A clipboard/undo shortcut, run as a CefFrame command rather than a key
/// event: in macOS OSR, Cmd shortcuts arrive via the app's Edit menu, so CEF
/// never acts on them as keys. Values are the wire format (queue `code` and
/// ui_cef::edit_command's argument).
enum class EditCommand : int {
    None = 0, SelectAll = 1, Copy = 2, Paste = 3, Cut = 4, Undo = 5, Redo = 6,
};
```

- after the `glfw_key_to_windows_vk` declaration, add:

```cpp
/// The edit command for `letter` (the layout's character, from
/// glfwGetKeyName) with GLFW `mods`, or None. Primary modifier: SUPER on
/// macOS, CONTROL elsewhere; any other of SUPER/CONTROL/ALT also held => None.
EditCommand edit_command_for(char letter, int mods) noexcept;
```

- change the comment on `kTextEventKey` from "only editing keys" to
  "only editing keys (glfw_key_to_windows_vk != 0)". The header comment says
  the game never reads this queue; add "kind 2 carries edit commands".

In `text_input.cc`, before the closing namespace, add:

```cpp
EditCommand edit_command_for(char letter, int mods) noexcept {
#if defined(__APPLE__)
    constexpr int kPrimary = GLFW_MOD_SUPER;
#else
    constexpr int kPrimary = GLFW_MOD_CONTROL;
#endif
    constexpr int kOthers = (GLFW_MOD_SUPER | GLFW_MOD_CONTROL | GLFW_MOD_ALT) & ~kPrimary;
    if (!(mods & kPrimary) || (mods & kOthers)) return EditCommand::None;
    const char c = (letter >= 'A' && letter <= 'Z') ? static_cast<char>(letter - 'A' + 'a') : letter;
    if (mods & GLFW_MOD_SHIFT) return c == 'z' ? EditCommand::Redo : EditCommand::None;
    switch (c) {
        case 'a': return EditCommand::SelectAll;
        case 'c': return EditCommand::Copy;
        case 'v': return EditCommand::Paste;
        case 'x': return EditCommand::Cut;
        case 'z': return EditCommand::Undo;
        case 'y': return EditCommand::Redo;
        default:  return EditCommand::None;
    }
}
```

Also update the stale `TextEventQueue::push` comment. "nothing drains in-game
yet (sub-project 2 adds focus arbitration)" becomes "the host drains every
frame (engine/ui/text_capture.py); the cap only matters if a frame stalls".

- [ ] **Step 4: Run the gtest**

Run: `cmake --build build -j --target renderer_tests && ./build/native/tests/renderer/renderer_tests --gtest_filter='EditCommand.*:TextInput.*'`
Expected: PASS.

- [ ] **Step 5: Wire the callback, CEF command and binding**

In `window.cc`, replace the key callback:

```cpp
    glfwSetKeyCallback(handle_, [](GLFWwindow* w, int key, int scancode, int action, int mods) {
        auto* self = static_cast<Window*>(glfwGetWindowUserPointer(w));
        if (!self) return;
        // Clipboard/undo chords first: resolve the LAYOUT's letter (an AZERTY
        // Cmd+A is GLFW_KEY_Q) and queue a CefFrame command.
        if (action != GLFW_RELEASE) {
            const char* name = glfwGetKeyName(key, scancode);
            if (name && name[0] && !name[1]) {
                const EditCommand cmd = edit_command_for(name[0], mods);
                if (cmd != EditCommand::None) {
                    self->text_events_.push({kTextEventEdit, static_cast<int>(cmd), scancode, action, mods});
                    return;
                }
            }
        }
        if (glfw_key_to_windows_vk(key) == 0) return;   // editing keys only
        self->text_events_.push({kTextEventKey, key, scancode, action, mods});
    });
```

In `cef_lifecycle.h`, after `send_key_event`:

```cpp
// Run an edit command on the focused frame: 1 SelectAll, 2 Copy, 3 Paste,
// 4 Cut, 5 Undo, 6 Redo (renderer::EditCommand's values). No-op with no
// browser or an unknown value.
void edit_command(int cmd);
```

In `cef_lifecycle.cc`, after `send_key_event`:

```cpp
void edit_command(int cmd) {
    if (!g_client || !g_client->browser()) return;
    auto frame = g_client->browser()->GetFocusedFrame();
    if (!frame) frame = g_client->browser()->GetMainFrame();
    if (!frame) return;
    switch (cmd) {
        case 1: frame->SelectAll(); break;
        case 2: frame->Copy(); break;
        case 3: frame->Paste(); break;
        case 4: frame->Cut(); break;
        case 5: frame->Undo(); break;
        case 6: frame->Redo(); break;
        default: break;
    }
}
```

In `host_bindings.cc`'s CEF `cef_send_key_event` lambda, insert at the top:

```cpp
              if (kind == renderer::kTextEventEdit) {
                  static_assert(static_cast<int>(renderer::EditCommand::Redo) == 6,
                                "ui_cef::edit_command's numbering");
                  dauntless::ui_cef::edit_command(code);
                  return;
              }
```

The non-CEF stub `cef_send_key_event` stays `[](int,int,int,int,int){}`.

In `host_io.py`, the `drain_text_events` docstring becomes "kind 0 = char
(code = codepoint), 1 = key (code = GLFW key), 2 = edit command (code =
renderer::EditCommand)".

Add to `tests/host/test_text_input_bindings.py`:

```python
def test_edit_command_without_a_browser_is_a_noop():
    h.cef_send_key_event(2, 3, 9, 1, 8)               # Paste, no browser alive
```

- [ ] **Step 6: Build and run**

Run: `cmake --build build -j && uv run pytest tests/host/test_text_input_bindings.py tests/host/test_preboot_panel_loop.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git branch --show-current
git add native/src/renderer/include/renderer/text_input.h native/src/renderer/text_input.cc native/src/renderer/window.cc native/src/ui_cef/cef_lifecycle.h native/src/ui_cef/cef_lifecycle.cc native/src/host/host_bindings.cc engine/host_io.py native/tests/renderer/text_input_test.cc tests/host/test_text_input_bindings.py
git commit -m "feat(input): Cmd/Ctrl+A/C/V/X/Z/Y as CefFrame edit commands"
```

---

### Task 4: Native capture reset on page load and renderer crash

**Files:**
- Modify: `native/src/ui_cef/cef_lifecycle.h` and `cef_lifecycle.cc`
- Modify: `native/src/ui_cef/cef_client.h` (class bases; `Get*Handler` overrides, about lines 38-50)
- Modify: `native/src/ui_cef/cef_client.cc` (`OnLoadStart`, about line 123)
- Modify: `native/src/host/host_bindings.cc` (module init, inside `#ifdef DAUNTLESS_ENABLE_CEF`)
- Create: `tests/tools/test_cef_capture_reset_wiring.py`

**Interfaces:**
- Consumes: `Window::set_key_capture(bool)` (Task 2).
- Produces:
  - `void dauntless::ui_cef::set_capture_reset_handler(std::function<void()>)`;
  - `void dauntless::ui_cef::fire_capture_reset()`.

There is no automated way to run a CEF reload or crash in the suite. This task
is guarded by a source-shape test, and the live check covers its behaviour.

- [ ] **Step 1: Write the failing source-shape test**

`tests/tools/test_cef_capture_reset_wiring.py`:

```python
"""Native clears keyboard capture when the page reloads/navigates or the
renderer dies, with no Python round trip -- so a field that vanished with its
page can never leave the game deaf. CEF reloads/crashes can't run in the
suite, so this pins the wiring at source level.

Spec: docs/superpowers/specs/2026-10-02-cef-text-input-keyboard-capture-design.md S2.4
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLIENT_CC = ROOT / "native/src/ui_cef/cef_client.cc"
CLIENT_H = ROOT / "native/src/ui_cef/cef_client.h"
BINDINGS = ROOT / "native/src/host/host_bindings.cc"


def _body(src, signature_regex):
    m = re.search(signature_regex, src)
    assert m, signature_regex
    i = src.index("{", m.end())
    depth = 0
    for j in range(i, len(src)):
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        if depth == 0:
            return src[i:j + 1]
    raise AssertionError("unbalanced body")


def test_load_start_fires_the_reset_for_the_main_frame():
    body = _body(CLIENT_CC.read_text(), r"DauntlessCefClient::OnLoadStart\s*\(")
    main = body[body.index("IsMain()"):]
    assert "fire_capture_reset()" in main


def test_renderer_crash_fires_the_reset():
    assert "CefRequestHandler" in CLIENT_H.read_text()
    body = _body(CLIENT_CC.read_text(),
                 r"DauntlessCefClient::OnRenderProcessTerminated\s*\(")
    assert "fire_capture_reset()" in body


def test_bindings_wire_the_reset_to_the_window_gate():
    src = BINDINGS.read_text()
    m = re.search(r"set_capture_reset_handler\s*\(", src)
    assert m, "host_bindings never installs the capture-reset handler"
    tail = src[m.end():m.end() + 400]
    assert "set_key_capture(false)" in tail
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/tools/test_cef_capture_reset_wiring.py -v`
Expected: all three FAIL.

- [ ] **Step 3: Implement**

In `cef_lifecycle.h`, after `set_load_end_handler`:

```cpp
// Called (main thread) whenever the page that might hold a focused text field
// goes away: main-frame load start (reload / navigation) and renderer-process
// termination. The host wires it to Window::set_key_capture(false). Stored in
// the lifecycle, not on the client, so it can be installed before
// initialize().
void set_capture_reset_handler(std::function<void()> handler);
// Invoke the handler if one is installed. Used by DauntlessCefClient.
void fire_capture_reset();
```

In `cef_lifecycle.cc`, at namespace scope near the other globals:

```cpp
namespace {
std::function<void()> g_capture_reset;
}  // namespace

void set_capture_reset_handler(std::function<void()> handler) {
    g_capture_reset = std::move(handler);
}

void fire_capture_reset() {
    if (g_capture_reset) g_capture_reset();
}
```

If the file already has an anonymous namespace holding `g_client`, put
`g_capture_reset` in it instead of opening a second one.

In `cef_client.h`:

- add `#include "include/cef_request_handler.h"` beside the other CEF includes;
- add `public CefRequestHandler` to the base list after `public CefLoadHandler`;
- add `CefRefPtr<CefRequestHandler> GetRequestHandler() override { return this; }`
  beside the other getters;
- declare:

```cpp
    // CefRequestHandler
    void OnRenderProcessTerminated(CefRefPtr<CefBrowser> browser,
                                   TerminationStatus status,
                                   int error_code,
                                   const CefString& error_string) override;
```

In `cef_client.cc`, change `OnLoadStart`'s last line:

```cpp
    if (frame && frame->IsMain()) {
        page_loaded_ = false;
        // The document (and any focused text field) is going away: give the
        // keyboard back to the game natively, before any Python runs.
        fire_capture_reset();
    }
```

and add:

```cpp
void DauntlessCefClient::OnRenderProcessTerminated(CefRefPtr<CefBrowser> browser,
                                                   TerminationStatus /*status*/,
                                                   int /*error_code*/,
                                                   const CefString& /*error_string*/) {
    if (browser_ && !browser->IsSame(browser_)) return;   // DevTools, not us
    fire_capture_reset();
}
```

`cef_client.cc` must see `fire_capture_reset`. Include `"cef_lifecycle.h"` if
it doesn't already.

In `host_bindings.cc`, inside `PYBIND11_MODULE`, within the
`#ifdef DAUNTLESS_ENABLE_CEF` region that defines the `cef_*` bindings, before
`m.def("cef_initialize", ...)`:

```cpp
    // A focused CEF text field holds the keyboard (Window::set_key_capture).
    // If its page reloads or its renderer dies, take the keyboard back
    // natively -- Python learns of it via key_capture_active().
    dauntless::ui_cef::set_capture_reset_handler([]() {
        if (g_window) g_window->set_key_capture(false);
    });
```

- [ ] **Step 4: Build and run**

Run: `cmake --build build -j && uv run pytest tests/tools/test_cef_capture_reset_wiring.py tests/host/test_text_input_bindings.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add native/src/ui_cef/cef_lifecycle.h native/src/ui_cef/cef_lifecycle.cc native/src/ui_cef/cef_client.h native/src/ui_cef/cef_client.cc native/src/host/host_bindings.cc tests/tools/test_cef_capture_reset_wiring.py
git commit -m "feat(input): native capture reset on page load and renderer crash"
```

---

### Task 5: `TextCaptureController` and `PanelRegistry.find`

**Files:**
- Modify: `engine/ui/panel_registry.py`
- Create: `engine/ui/text_capture.py`
- Create: `tests/ui/test_text_capture.py`

**Interfaces:**
- Consumes: `host_io.set_key_capture`, `host_io.key_capture_active`,
  `host_io.drain_text_events` and `host_io.cef_send_key_event` (Task 2 and
  existing).
- Produces:
  - `PanelRegistry.find(name: str) -> Optional[Panel]`;
  - `TextCaptureController(registry)`, a `Panel` named `"kbd"`, with
    attribute `owner: Optional[str]` and methods `dispatch_event(action) -> bool`,
    `render_payload() -> Optional[str]`, `tick() -> None` and `release() -> None`;
  - module constant `BLUR_SCRIPT`.

- [ ] **Step 1: Write the failing tests**

`tests/ui/test_text_capture.py`:

```python
"""TextCaptureController: page focus reports -> native key gate, the queue
forwarded only while a field holds the keyboard, and every release trigger.

Spec: docs/superpowers/specs/2026-10-02-cef-text-input-keyboard-capture-design.md S4
"""
import pytest

from engine import host_io
from engine.ui.panel import Panel
from engine.ui.panel_registry import PanelRegistry
from engine.ui.text_capture import BLUR_SCRIPT, TextCaptureController


class _Host:
    """Stand-in for _dauntless_host's capture + text-queue bindings."""

    def __init__(self):
        self.captured = False
        self.capture_calls = []
        self.queue = []
        self.sent = []

    def set_key_capture(self, on):
        self.capture_calls.append(on)
        self.captured = on

    def key_capture_active(self):
        return self.captured

    def drain_text_events(self):
        out, self.queue = self.queue, []
        return out

    def cef_send_key_event(self, *ev):
        self.sent.append(ev)


class _Owner(Panel):
    def __init__(self, name="probe", is_open=True):
        super().__init__()
        self._name = name
        self.open_ = is_open

    @property
    def name(self):
        return self._name

    def is_open(self):
        return self.open_

    def render_payload(self):
        return None

    def dispatch_event(self, action):
        return False


@pytest.fixture
def env(monkeypatch):
    host = _Host()
    monkeypatch.setattr(host_io, "_h", host)
    reg = PanelRegistry()
    owner = _Owner()
    reg.register(owner)
    cap = TextCaptureController(reg)
    reg.register(cap)
    return host, reg, owner, cap


def test_registry_find():
    reg = PanelRegistry()
    p = _Owner("x")
    reg.register(p)
    assert reg.find("x") is p
    assert reg.find("nope") is None


def test_focus_on_an_open_owner_captures(env):
    host, reg, owner, cap = env
    assert reg.dispatch("kbd/focus:probe") is True
    assert cap.owner == "probe"
    assert host.captured is True
    assert cap.render_payload() is None


@pytest.mark.parametrize("name", ["", "nope"])
def test_focus_on_an_unknown_or_untagged_owner_is_refused(env, name, caplog):
    host, _reg, _owner, cap = env
    cap.dispatch_event("focus:" + name)
    assert cap.owner is None
    assert host.captured is False
    assert cap.render_payload() == BLUR_SCRIPT
    assert cap.render_payload() is None          # exactly once
    assert "data-panel" in caplog.text


def test_focus_on_a_closed_owner_is_refused(env):
    host, _reg, owner, cap = env
    owner.open_ = False
    cap.dispatch_event("focus:probe")
    assert host.captured is False
    assert cap.render_payload() == BLUR_SCRIPT


def test_blur_releases_without_a_payload(env):
    host, _reg, _owner, cap = env
    cap.dispatch_event("focus:probe")
    cap.dispatch_event("blur")
    assert cap.owner is None
    assert host.captured is False
    assert cap.render_payload() is None


def test_blur_is_idempotent(env):
    _host, _reg, _owner, cap = env
    assert cap.dispatch_event("blur") is True
    assert cap.dispatch_event("blur") is True
    assert cap.owner is None


def test_tab_between_two_fields_keeps_capture(env):
    """Review Focus 4: focusout to another editable sends nothing, then the
    new field's focusin re-sends focus: -- capture stays on, no blur."""
    host, _reg, _owner, cap = env
    cap.dispatch_event("focus:probe")
    cap.dispatch_event("focus:probe")
    cap.tick()
    assert host.captured is True
    assert cap.owner == "probe"
    assert cap.render_payload() is None


def test_moving_to_an_untagged_field_releases(env):
    """Review Focus 4: tabbing from a tagged field to an untagged one sends no
    blur (relatedTarget is editable) -- the refusal itself must release."""
    host, _reg, _owner, cap = env
    cap.dispatch_event("focus:probe")
    cap.dispatch_event("focus:")
    assert cap.owner is None
    assert host.captured is False
    assert cap.render_payload() == BLUR_SCRIPT


def test_owner_closing_releases_with_one_blur(env):
    host, _reg, owner, cap = env
    cap.dispatch_event("focus:probe")
    owner.open_ = False
    cap.tick()
    assert cap.owner is None
    assert host.captured is False
    assert cap.render_payload() == BLUR_SCRIPT
    assert cap.render_payload() is None


def test_owner_without_is_open_uses_visible(env):
    host, reg, _owner, cap = env

    class _Plain(Panel):
        name = "plain"
        def render_payload(self): return None
        def dispatch_event(self, a): return False

    plain = _Plain()
    reg.register(plain)
    cap.dispatch_event("focus:plain")
    assert host.captured is True
    plain.visible = False
    cap.tick()
    assert host.captured is False


def test_native_reset_drops_the_owner_silently(env):
    host, _reg, _owner, cap = env
    cap.dispatch_event("focus:probe")
    host.captured = False                        # page reloaded: native cleared it
    cap.tick()
    assert cap.owner is None
    assert cap.render_payload() is None          # no page left to blur


def test_release_with_an_owner(env):
    host, _reg, _owner, cap = env
    cap.dispatch_event("focus:probe")
    cap.release()
    assert cap.owner is None
    assert host.capture_calls[-1] is False
    assert cap.render_payload() == BLUR_SCRIPT


def test_release_without_an_owner_does_nothing(env):
    host, _reg, _owner, cap = env
    cap.release()
    assert host.capture_calls == []
    assert cap.render_payload() is None


def test_queue_forwarded_only_while_captured(env):
    host, _reg, _owner, cap = env
    host.queue = [(0, ord("w"), 0, 1, 0)]        # typed in flight
    cap.tick()
    assert host.sent == []                        # discarded, not saved for later
    cap.dispatch_event("focus:probe")
    host.queue = [(0, ord("-"), 0, 1, 0), (1, 259, 51, 1, 0)]
    cap.tick()
    assert host.sent == [(0, ord("-"), 0, 1, 0), (1, 259, 51, 1, 0)]
    cap.dispatch_event("blur")
    host.queue = [(0, ord("x"), 0, 1, 0)]
    cap.tick()
    assert len(host.sent) == 2


def test_headless_tick_is_a_noop(monkeypatch):
    monkeypatch.setattr(host_io, "_h", None)
    reg = PanelRegistry()
    cap = TextCaptureController(reg)
    cap.tick()
    cap.release()
    assert cap.owner is None
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/ui/test_text_capture.py -v`
Expected: an import error, `No module named 'engine.ui.text_capture'`.

- [ ] **Step 3: Implement**

In `engine/ui/panel_registry.py`, after `register`:

```python
    def find(self, name: str) -> Optional[Panel]:
        """The registered panel called `name`, or None."""
        for p in self._panels:
            if p.name == name:
                return p
        return None
```

`engine/ui/text_capture.py`:

```python
"""Keyboard capture for in-game CEF text fields.

While an editable element in the page has focus, it owns the keyboard: the
native KeyGate (renderer/key_gate.h) makes every key read False, so no polled
read, ET_KEYBOARD event or dev binding fires. Typed text goes to CEF instead.

The page (native/assets/ui-cef/js/text_capture.js) reports focus as
``kbd/focus:<panel>`` and ``kbd/blur``. This controller turns the gate on and
off, forwards the text queue to CEF only while a field holds the keyboard, and
enforces the release triggers so the game can never be left deaf:

  1. the page blurs the field (``kbd/blur``);
  2. native reset on page load / renderer crash (observed via
     ``host_io.key_capture_active()``);
  3. the owning panel is no longer open (checked every ``tick``);
  4. mission swap (``release`` is a pre-swap hook);
  5. a left click the host did not route to CEF (``release``).

A forced release (3-5) abandons the edit: the page reverts, then blurs.

Spec: docs/superpowers/specs/2026-10-02-cef-text-input-keyboard-capture-design.md
"""
from __future__ import annotations

import logging
from typing import Optional

from engine import host_io
from engine.ui.panel import Panel

_log = logging.getLogger(__name__)

BLUR_SCRIPT = "window.__dauntlessBlurText&&window.__dauntlessBlurText()"


def _is_open(panel: Panel) -> bool:
    fn = getattr(panel, "is_open", None)
    if callable(fn):
        return bool(fn())
    return bool(panel.visible)


class TextCaptureController(Panel):
    def __init__(self, registry):
        super().__init__()
        self._registry = registry
        self.owner: Optional[str] = None
        self._blur_pending = False

    @property
    def name(self) -> str:
        return "kbd"

    def dispatch_event(self, action: str) -> bool:
        if action.startswith("focus:"):
            name = action[len("focus:"):]
            panel = self._registry.find(name) if name else None
            if panel is not None and panel is not self and _is_open(panel):
                self.owner = name
                host_io.set_key_capture(True)
            else:
                if panel is None:
                    _log.warning(
                        "text capture refused: no panel named %r -- is the "
                        "field's panel root missing its data-panel tag?", name)
                # Also releases a field that was holding the keyboard: tabbing
                # to an untagged field sends no blur first.
                self.owner = None
                host_io.set_key_capture(False)
                self._blur_pending = True
            return True
        if action == "blur":
            self.owner = None
            host_io.set_key_capture(False)
            return True
        return False

    def render_payload(self) -> Optional[str]:
        if not self._blur_pending:
            return None
        self._blur_pending = False
        return BLUR_SCRIPT

    def release(self) -> None:
        """Forced release (panel gone, mission swap, click on the game world).
        Abandons the edit: the page reverts, then blurs."""
        if self.owner is None:
            return
        self.owner = None
        host_io.set_key_capture(False)
        self._blur_pending = True

    def tick(self) -> None:
        """Once per frame, at the top of the input block."""
        if self.owner is not None and not host_io.key_capture_active():
            # Native reset: the page that held the field reloaded or died.
            self.owner = None
        if self.owner is not None:
            panel = self._registry.find(self.owner)
            if panel is None or not _is_open(panel):
                self.release()
        # Drain EVERY frame, so keys typed in flight never arrive in a field
        # that gains focus later.
        events = host_io.drain_text_events()
        if self.owner is not None:
            for ev in events:
                host_io.cef_send_key_event(*ev)
```

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest tests/ui/test_text_capture.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add engine/ui/panel_registry.py engine/ui/text_capture.py tests/ui/test_text_capture.py
git commit -m "feat(input): TextCaptureController -- focus arbitration and release triggers"
```

---

### Task 6: `text_capture.js`, the page half

**Files:**
- Create: `native/assets/ui-cef/js/text_capture.js`
- Modify: `native/assets/ui-cef/index.html` (script tag after `js/pause_menu.js`, about line 1045)
- Create: `tests/ui/test_text_capture_js.py`

**Interfaces:**
- Consumes: `dauntlessEvent(name)` (global, `js/pause_menu.js:9`).
- Produces: `kbd/focus:<owner>` and `kbd/blur` events;
  `window.__dauntlessBlurText()`, `window.__dauntlessTextCancel(el)` and
  `window.__dauntlessTextCommit(el)`.

The repo has no JS runtime harness (see `tests/ui/test_target_list_caret.py`),
so these are source-shape tests. That was agreed in the brainstorm (D6).

- [ ] **Step 1: Write the failing tests**

`tests/ui/test_text_capture_js.py`:

```python
"""Source-shape guards for text_capture.js (no JS runtime harness in this
repo -- brainstorm D6). Behaviour is covered by Mark's live check (spec S8).

Spec: docs/superpowers/specs/2026-10-02-cef-text-input-keyboard-capture-design.md S3
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "native/assets/ui-cef/js/text_capture.js")
HTML = (ROOT / "native/assets/ui-cef/index.html")


def _src():
    return JS.read_text()


def _fn(src, name):
    """Body of `function name(...) {...}` or `window.name = function (...) {...}`."""
    m = re.search(r"(function\s+%s\s*\(|window\.%s\s*=\s*function\s*\()" % (name, name), src)
    assert m, name
    i = src.index("{", m.end())
    depth = 0
    for j in range(i, len(src)):
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        if depth == 0:
            return src[i:j + 1]
    raise AssertionError(name)


def test_loaded_after_pause_menu_and_before_the_panels():
    html = HTML.read_text()
    pm = html.index('src="js/pause_menu.js"')
    tc = html.index('src="js/text_capture.js"')
    spv = html.index('src="js/ship_property_viewer.js"')
    assert pm < tc < spv


def test_editable_excludes_checkbox_range_and_buttons():
    body = _fn(_src(), "isEditable")
    types = re.search(r"TEXT_TYPES\s*=\s*\[([^\]]*)\]", _src()).group(1)
    for t in ("text", "search", "number", "email", "url", "password", "tel"):
        assert "'%s'" % t in types
    for t in ("checkbox", "range", "button", "submit", "radio"):
        assert t not in types
    assert "TEXTAREA" in body and "isContentEditable" in body


def test_listeners_are_capture_phase():
    src = _src()
    for ev in ("focusin", "focusout", "keydown"):
        m = re.search(r"addEventListener\('%s',.*?\},\s*true\)" % ev, src, re.S)
        assert m, ev


def test_focus_reports_owner_and_saves_value():
    src = _src()
    block = src[src.index("'focusin'"):src.index("'focusout'")]
    assert "saved.set(" in block
    assert "dauntlessEvent('kbd/focus:' + ownerOf(" in block
    assert "closest('[data-panel]')" in _fn(src, "ownerOf")


def test_focusout_to_another_editable_sends_nothing():
    src = _src()
    block = src[src.index("'focusout'"):src.index("'keydown'")]
    assert block.index("isEditable(e.relatedTarget)") < block.index("dauntlessEvent('kbd/blur')")


def test_escape_restores_before_blurring_and_stops_propagation():
    src = _src()
    assert _fn(src, "revertAndBlur").index("setValue(") < _fn(src, "revertAndBlur").index(".blur()")
    block = src[src.index("'keydown'"):]
    esc = block[block.index("'Escape'"):block.index("'Enter'")]
    assert "stopPropagation()" in esc and "revertAndBlur(" in esc


def test_enter_blurs_except_in_textarea():
    block = _src()[_src().index("'Enter'"):]
    assert "TEXTAREA" in block[:200] and ".blur()" in block[:200]


def test_forced_blur_reverts():
    body = _fn(_src(), "__dauntlessBlurText")
    assert "revertAndBlur(" in body
    assert "revertAndBlur(" in _fn(_src(), "__dauntlessTextCancel")
    assert ".blur()" in _fn(_src(), "__dauntlessTextCommit")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/ui/test_text_capture_js.py -v`
Expected: FAIL with `FileNotFoundError` for `text_capture.js`.

- [ ] **Step 3: Implement**

`native/assets/ui-cef/js/text_capture.js`:

```js
// text_capture.js -- keyboard capture for in-game CEF text fields.
//
// Reports focus/blur of editable elements so the host can hand the keyboard
// to the page (engine/ui/text_capture.py -> native KeyGate), and gives every
// field the same three keys: Esc reverts then blurs, Enter blurs (the DOM
// `change` event is the commit), Tab stays in the page. Kept thin on purpose:
// all other logic lives in Python where it is tested.
//
// A panel hosting a field puts data-panel="<registry name>" on its root.
// Spec: docs/superpowers/specs/2026-10-02-cef-text-input-keyboard-capture-design.md S3
(function () {
    var TEXT_TYPES = ['text', 'search', 'number', 'email', 'url', 'password', 'tel'];
    var saved = new WeakMap();   // element -> value at focus

    function isEditable(el) {
        if (!el || el.nodeType !== 1) return false;
        if (el.tagName === 'TEXTAREA') return true;
        if (el.tagName === 'INPUT') {
            return TEXT_TYPES.indexOf((el.getAttribute('type') || 'text').toLowerCase()) >= 0;
        }
        return el.isContentEditable === true;
    }

    function isField(el) { return el.tagName === 'INPUT' || el.tagName === 'TEXTAREA'; }
    function valueOf(el) { return isField(el) ? el.value : el.textContent; }
    function setValue(el, v) { if (isField(el)) el.value = v; else el.textContent = v; }

    function ownerOf(el) {
        var root = el.closest('[data-panel]');
        return root ? root.getAttribute('data-panel') : '';
    }

    // Restore BEFORE blurring, so no `change` fires and nothing commits.
    function revertAndBlur(el) {
        if (saved.has(el)) setValue(el, saved.get(el));
        el.blur();
    }

    document.addEventListener('focusin', function (e) {
        var el = e.target;
        if (!isEditable(el)) return;
        saved.set(el, valueOf(el));
        dauntlessEvent('kbd/focus:' + ownerOf(el));
    }, true);

    document.addEventListener('focusout', function (e) {
        if (!isEditable(e.target)) return;
        // Field -> field (Tab): the next focusin re-reports; keep capture.
        if (isEditable(e.relatedTarget)) return;
        dauntlessEvent('kbd/blur');
    }, true);

    document.addEventListener('keydown', function (e) {
        var el = e.target;
        if (!isEditable(el)) return;
        if (e.key === 'Escape') {
            e.preventDefault();
            e.stopPropagation();
            revertAndBlur(el);
        } else if (e.key === 'Enter' && el.tagName !== 'TEXTAREA') {
            e.preventDefault();
            el.blur();
        }
    }, true);

    // Host-forced release (panel closed, mission swap, click on the game
    // world): abandon the edit.
    window.__dauntlessBlurText = function () {
        var el = document.activeElement;
        if (isEditable(el)) revertAndBlur(el);
    };
    // For in-panel cancel/commit buttons.
    window.__dauntlessTextCancel = function (el) {
        if (isEditable(el)) revertAndBlur(el);
    };
    window.__dauntlessTextCommit = function (el) {
        if (el) el.blur();
    };
})();
```

The test's `_fn` looks for `function name(` or `window.name = function (`.
`isEditable`, `ownerOf` and `revertAndBlur` are declared with
`function name(`, so they match.

In `index.html`, directly after `<script src="js/pause_menu.js"></script>`, add:

```html
    <script src="js/text_capture.js"></script>
```

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest tests/ui/test_text_capture_js.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add native/assets/ui-cef/js/text_capture.js native/assets/ui-cef/index.html tests/ui/test_text_capture_js.py
git commit -m "feat(ui): text_capture.js -- report field focus; Esc reverts, Enter commits"
```

---

### Task 7: Host-loop wiring and the no-leak test

**Files:**
- Modify: `engine/host_loop.py`:
  - after `registry = PanelRegistry()` (about line 9918);
  - the input block's `if _h is not None:` (about 10316);
  - the unpaused click router (about 10667).
- Create: `tests/host/test_text_capture_wiring.py`

**Interfaces:**
- Consumes: `TextCaptureController` (Task 5); `host_io.set_key_capture` and
  `host_io.key_capture_active` (Task 2); `controller.pre_swap_hooks`.
- Produces: nothing new for later tasks.

The no-leak test drives the **real** pollers and controllers through a fake
host whose `key_state` / `key_pressed` reproduce the native contract: the
`KeyGate` from Task 1 plus `key_pressed`'s prev snapshot. It proves the Python
side holds up its end:

- the controller drives the gate;
- a held key gets a clean release when capture starts;
- the key that ended an edit stays silent.

That native reads can't bypass the gate is proven by Task 2's structural guard.

- [ ] **Step 1: Write the failing test**

`tests/host/test_text_capture_wiring.py`:

```python
"""While a CEF text field holds the keyboard, the game's own key consumers
hear nothing -- and they get clean releases at the boundaries.

The fake host below reproduces the native contract exactly: KeyGate
(native/src/renderer/key_gate.cc) filtering every level read, plus
key_pressed's prev snapshot taken at end of frame (host_bindings.cc frame()).
The pollers, pause controller and modal-ESC router are the REAL ones.

Spec: docs/superpowers/specs/2026-10-02-cef-text-input-keyboard-capture-design.md S7.5
"""
import App
import pytest

from engine import host_io, host_loop
from engine.host_loop import (_PauseMenuController, _dispatch_modal_esc,
                              _poll_fire_keys, _poll_raw_keyboard)
from engine.input_map import GLFW_KEYS, InputMap
from engine.ui.panel import Panel
from engine.ui.panel_registry import PanelRegistry
from engine.ui.text_capture import TextCaptureController


class _Keys:
    KEY_SPACE = 32
    KEY_1 = 49
    KEY_S = ord("S")
    KEY_W = ord("W")
    KEY_F = ord("F")
    KEY_X = ord("X")
    KEY_G = ord("G")
    KEY_ESCAPE = 256
    KEY_F1 = 290
    KEY_F6 = 295
    KEY_F9 = 298
    KEY_LEFT_SHIFT = 340
    KEY_LEFT_CONTROL = 341
    KEY_LEFT_ALT = 342
    KEY_RIGHT_SHIFT = 344
    KEY_RIGHT_CONTROL = 345
    KEY_RIGHT_ALT = 346


class _GatedHost:
    """Native contract: KeyGate + polled-key mask + end-of-frame prev snapshot."""
    keys = _Keys()

    def __init__(self):
        self.raw = set()           # physically held
        self._captured = False
        self._mask = set()
        self._polled = set()
        self._prev = {}
        self.queue = []
        self.sent = []

    # KeyGate::report
    def key_state(self, k):
        self._polled.add(k)
        raw = k in self.raw
        if self._captured:
            return False
        if k in self._mask:
            if raw:
                return False
            self._mask.discard(k)
        return raw

    def key_pressed(self, k):
        now = self.key_state(k)
        if k not in self._prev:
            self._prev[k] = now
            return False
        return now and not self._prev[k]

    def end_frame(self):
        for k in self._prev:
            self._prev[k] = self.key_state(k)

    # Window::set_key_capture
    def set_key_capture(self, on):
        if on:
            self._captured = True
            self._mask.clear()
        elif self._captured:
            self._captured = False
            self._mask |= {k for k in self._polled if k in self.raw}

    def key_capture_active(self):
        return self._captured

    def drain_text_events(self):
        out, self.queue = self.queue, []
        return out

    def cef_send_key_event(self, *ev):
        self.sent.append(ev)


class _Owner(Panel):
    name = "probe"

    def __init__(self):
        super().__init__()
        self.esc_calls = 0

    def is_open(self):
        return True

    def handle_key_esc(self):
        self.esc_calls += 1

    def render_payload(self):
        return None

    def dispatch_event(self, action):
        return False


class _NoCrewMenu:
    def has_open_menu(self):
        return False


_RAW_SEEN = []
_HANDLER = __name__ + "._on_raw_keyboard"


def _on_raw_keyboard(obj, event):
    _RAW_SEEN.append(event.GetUnicode())


@pytest.fixture
def rig(monkeypatch):
    import KeyConfig
    KeyConfig.MapScancodes()
    host_loop._fn_key_prev.clear()
    host_loop._raw_key_pairs_host = None
    _RAW_SEEN.clear()
    App.g_kRootWindow.AddPythonFuncHandlerForInstance(App.ET_KEYBOARD, _HANDLER)
    host = _GatedHost()
    monkeypatch.setattr(host_io, "_h", host)
    downs, ups = [], []
    monkeypatch.setattr(App.g_kInputManager, "OnKeyDown", lambda wc: downs.append(wc))
    monkeypatch.setattr(App.g_kInputManager, "OnKeyUp", lambda wc: ups.append(wc))
    reg = PanelRegistry()
    owner = _Owner()
    reg.register(owner)
    cap = TextCaptureController(reg)
    reg.register(cap)
    im = InputMap()
    pause = _PauseMenuController()

    def frame(blockers=()):
        """One host frame's worth of the real key consumers, then the
        native end-of-frame snapshot."""
        cap.tick()
        _dispatch_modal_esc(list(blockers), _NoCrewMenu(), pause, host)
        _poll_fire_keys(host, im)
        _poll_raw_keyboard(host, im)
        host.end_frame()

    yield host, cap, owner, pause, downs, ups, frame
    App.g_kRootWindow.RemoveHandlerForInstance(App.ET_KEYBOARD, _HANDLER)
    _RAW_SEEN.clear()
    host_loop._fn_key_prev.clear()
    host_loop._raw_key_pairs_host = None


def test_nothing_reaches_the_game_while_a_field_is_focused(rig):
    host, cap, owner, pause, downs, ups, frame = rig
    frame()                                       # register keys, idle
    cap.dispatch_event("focus:probe")
    host.raw |= {_Keys.KEY_W, _Keys.KEY_SPACE, GLFW_KEYS["F"], _Keys.KEY_1,
                 _Keys.KEY_ESCAPE}
    for _ in range(3):
        frame(blockers=[owner])
    assert downs == []                            # no fire, no input-manager press
    assert _RAW_SEEN == []                        # no raw ET_KEYBOARD
    assert owner.esc_calls == 0                   # Esc never reached the panel
    frame()                                       # no blockers: pause path
    assert pause.is_open is False


def test_a_fire_key_held_when_focus_arrives_gets_a_clean_release(rig):
    """Review Focus 3."""
    host, cap, _owner, _pause, downs, ups, frame = rig
    host.raw.add(GLFW_KEYS["F"])
    frame()
    assert downs == [App.WC_F]                    # firing
    cap.dispatch_event("focus:probe")
    frame()
    assert ups == [App.WC_F]                      # firing stops
    frame()
    assert downs == [App.WC_F] and ups == [App.WC_F]   # and stays stopped


def test_the_esc_that_blurred_the_field_does_not_open_pause(rig):
    """Review Focus 5: Esc reverts+blurs in the page, and the same physical
    press is still down on the following frames."""
    host, cap, _owner, pause, _downs, _ups, frame = rig
    frame()
    cap.dispatch_event("focus:probe")
    host.raw.add(_Keys.KEY_ESCAPE)
    frame()
    cap.dispatch_event("blur")                    # page handled Esc
    frame()
    frame()
    assert pause.is_open is False                 # still held: masked
    host.raw.discard(_Keys.KEY_ESCAPE)
    frame()
    assert pause.is_open is False
    host.raw.add(_Keys.KEY_ESCAPE)                # a NEW press
    frame()
    assert pause.is_open is True


def test_typed_text_reaches_cef_only_while_focused(rig):
    host, cap, _owner, _pause, _downs, _ups, frame = rig
    host.queue = [(0, ord("w"), 0, 1, 0)]
    frame()
    assert host.sent == []
    cap.dispatch_event("focus:probe")
    host.queue = [(0, ord("-"), 0, 1, 0)]
    frame()
    assert host.sent == [(0, ord("-"), 0, 1, 0)]
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/host/test_text_capture_wiring.py -v`

Expected: this test exercises Tasks 1-5 together through real consumers, so it
may already PASS. If it does, mutate to prove it can fail:

```bash
cp engine/ui/text_capture.py /tmp/tc.bak
```

Edit `text_capture.py`'s `dispatch_event` so the `focus:` branch calls
`host_io.set_key_capture(False)` instead of `True`. Run the test again;
`test_nothing_reaches_the_game_while_a_field_is_focused` and
`test_a_fire_key_held_when_focus_arrives_gets_a_clean_release` must FAIL. Then
restore and prove the restore is byte-identical:

```bash
cp /tmp/tc.bak engine/ui/text_capture.py
diff engine/ui/text_capture.py /tmp/tc.bak
```

If any test fails for a reason other than the mutation, it is a real
integration bug. Fix it in the owning module (`text_capture.py` or
`host_io.py`), not in the test.

- [ ] **Step 3: Wire the host loop**

Directly after `registry = PanelRegistry()` and
`ai_inspector = _register_ai_inspector(registry)`:

```python
        # Keyboard capture for CEF text fields: while one has focus the native
        # KeyGate makes every key read up. Registered as panel "kbd" so the
        # page's kbd/focus / kbd/blur events route here. Spec:
        # docs/superpowers/specs/2026-10-02-cef-text-input-keyboard-capture-design.md
        from engine.ui.text_capture import TextCaptureController
        text_capture = TextCaptureController(registry)
        registry.register(text_capture)
        # Trigger 4: a mission swap abandons any edit in progress.
        controller.pre_swap_hooks.append(text_capture.release)
```

In the input block, make `text_capture.tick()` the first statement inside
`if _h is not None:`, before the
`if configuration_panel.capturing_action is not None:` line:

```python
                # Text-field keyboard capture: release triggers 2-3, and the
                # typed-text queue to CEF (drained every frame, forwarded only
                # while a field holds the keyboard). First, so every key read
                # below sees this frame's gate.
                text_capture.tick()
```

In the unpaused click router (about line 10667), replace:

```python
                    if _cef_send_mouse_click is not None and _cursor_in_panel:
                        if host_io.mouse_button_pressed(_h.keys.MOUSE_BUTTON_LEFT):
                            _cef_send_mouse_click(_mx, _my, 0, True)
                        if host_io.mouse_button_released(_h.keys.MOUSE_BUTTON_LEFT):
                            _cef_send_mouse_click(_mx, _my, 0, False)
```

with:

```python
                    if _cef_send_mouse_click is not None and _cursor_in_panel:
                        if host_io.mouse_button_pressed(_h.keys.MOUSE_BUTTON_LEFT):
                            _cef_send_mouse_click(_mx, _my, 0, True)
                        if host_io.mouse_button_released(_h.keys.MOUSE_BUTTON_LEFT):
                            _cef_send_mouse_click(_mx, _my, 0, False)
                    elif host_io.mouse_button_pressed(_h.keys.MOUSE_BUTTON_LEFT):
                        # Trigger 5: a click on the game world never reaches
                        # CEF, so the page cannot blur on its own -- release
                        # the keyboard (abandoning the edit) here.
                        text_capture.release()
```

`mouse_button_pressed` is read-only; only `mouse_button_released` advances the
button's prev state. Calling it here therefore doesn't disturb
`_poll_mouse_buttons`.

- [ ] **Step 4: Run the wiring test plus the host suites that touch these lines**

Run: `uv run pytest tests/host/test_text_capture_wiring.py tests/host/ tests/unit/test_raw_keyboard_poll.py tests/unit/test_fire_key_remap.py -q`
Expected: PASS. Any failure in the existing suites is a regression from this
task.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add engine/host_loop.py tests/host/test_text_capture_wiring.py
git commit -m "feat(input): wire text capture into the host loop; no-leak test"
```

---

### Task 8: SPV `coord_set`, `scale_set` and `rotate_set`

**Files:**
- Modify: `engine/ui/ship_property_viewer_panel.py`:
  - `_MOUNT_GIZMO_PREFIXES` (about line 2407);
  - `_dispatch_event_inner`, beside the `*_nudge` handlers (about 2778-2876).
- Create: `tests/ui/test_spv_value_set.py`

**Interfaces:**
- Consumes: `EditTarget.position()/set_position()`, `scale_kind()`,
  `set_scale_field()`, `rotate_spec()` and `rotate_nudge()` (existing,
  `engine/ui/spv_edit_targets.py`).
- Produces the actions, which Task 9's JS sends:
  - `coord_set:{"axis":i,"value":v}`;
  - `scale_set:{"index":i,"value":v}`;
  - `rotate_set:{"axis":i,"value":v}`.

- [ ] **Step 1: Write the failing tests**

`tests/ui/test_spv_value_set.py`:

```python
"""Typed values in the SPV Move / Rotate / Scale rows.

A typed value must do EXACTLY what the steppers do when clicked until the row
reads that value -- so each *_set is pinned equal to the matching *_nudge on
every edit-target kind (returned, staged change, undo entries), using the
characterisation fixture.

Spec: docs/superpowers/specs/2026-10-02-cef-text-input-keyboard-capture-design.md S5.2
"""
import json

import pytest

from tests.ui.spv_test_fixtures import (  # noqa: F401  (make_panel: fixture)
    CASES, _diff, _select, _staged, _use_tool, make_panel)


def _run(make_panel, case, tool, action):
    p = make_panel()
    _select(p, case)
    _use_tool(p, tool)
    before, n = _staged(p, case), len(p._undo_stack)
    ok = p.dispatch_event(action)
    return (ok, _diff(before, _staged(p, case)), len(p._undo_stack) - n)


def _shown(make_panel, case, tool):
    """The values the row displays, read the way the JS gets them."""
    p = make_panel()
    _select(p, case)
    _use_tool(p, tool)
    if tool == "transform":
        tc = p.transform_coords()
        return None if tc is None else [tc["x"], tc["y"], tc["z"]]
    vals = p.scale_values() if tool == "scale" else p.rotate_values()
    return None if vals is None else [f["value"] for f in vals["fields"]]


@pytest.mark.parametrize("case", CASES)
def test_coord_set_equals_the_nudge(make_panel, case):
    nudged = _run(make_panel, case, "transform", 'coord_nudge:{"axis": 0, "delta": 1.0}')
    shown = _shown(make_panel, case, "transform")
    value = (shown[0] + 1.0) if shown else 1.0
    got = _run(make_panel, case, "transform",
               "coord_set:" + json.dumps({"axis": 0, "value": value}))
    assert got == nudged


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("k", [0, 1, 2])
def test_scale_set_equals_the_nudge(make_panel, case, k):
    nudged = _run(make_panel, case, "scale", 'scale_nudge:{"index": %d, "delta": 0.1}' % k)
    shown = _shown(make_panel, case, "scale")
    value = (shown[k] + 0.1) if shown and k < len(shown) else 0.1
    got = _run(make_panel, case, "scale",
               "scale_set:" + json.dumps({"index": k, "value": value}))
    assert got == nudged


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("k", [0, 1, 2])
def test_rotate_set_equals_the_nudge(make_panel, case, k):
    nudged = _run(make_panel, case, "rotate", 'rotate_nudge:{"axis": %d, "delta": 10.0}' % k)
    shown = _shown(make_panel, case, "rotate")
    value = (shown[k] + 10.0) if shown and k < len(shown) else 10.0
    got = _run(make_panel, case, "rotate",
               "rotate_set:" + json.dumps({"axis": k, "value": value}))
    assert got == nudged


def test_rotate_set_is_relative_to_the_accumulator(make_panel):
    p = make_panel()
    _select(p, "light_cylinder")
    _use_tool(p, "rotate")
    p.dispatch_event('rotate_nudge:{"axis": 0, "delta": 20.0}')
    calls = []
    t = p._rotate_edit_target()
    orig = type(t).rotate_nudge
    type(t).rotate_nudge = lambda self, i, d: calls.append((i, d))
    try:
        p.dispatch_event('rotate_set:{"axis": 0, "value": 30.0}')
    finally:
        type(t).rotate_nudge = orig
    assert calls == [(0, pytest.approx(10.0))]


@pytest.mark.parametrize("action", [
    "coord_set:not json",
    'coord_set:{"axis": 3, "value": 1.0}',
    'coord_set:{"axis": 0}',
    'coord_set:{"axis": 0, "value": NaN}',
    'coord_set:{"axis": 0, "value": Infinity}',
    'coord_set:{"axis": 0, "value": "abc"}',
    'scale_set:{"index": 9, "value": 1.0}',
    'scale_set:{"index": 0, "value": NaN}',
    'rotate_set:{"axis": 7, "value": 1.0}',
    'rotate_set:{"axis": 0, "value": -Infinity}',
])
def test_malformed_sets_are_rejected_and_change_nothing(make_panel, action):
    p = make_panel()
    _select(p, "light_box")
    tool = {"coord": "transform", "scale": "scale", "rotate": "rotate"}[action.split("_")[0]]
    _use_tool(p, tool)
    before, n = _staged(p, "light_box"), len(p._undo_stack)
    assert p.dispatch_event(action) is False
    assert _diff(before, _staged(p, "light_box")) == _diff(before, before)
    assert len(p._undo_stack) == n


@pytest.mark.parametrize("case", CASES)
def test_a_locked_mount_refuses_typed_values(make_panel, case):
    """Typed values honour the same lock as the steppers and gizmo."""
    from engine.appc import articulation
    p = make_panel()
    _select(p, case)
    _use_tool(p, "transform")
    articulation.set_dev_override("red")
    try:
        locked = p._current_target_is_locked_mount()
        before = _staged(p, case)
        results = [p.dispatch_event(a) for a in (
            'coord_set:{"axis": 0, "value": 5.0}',
            'scale_set:{"index": 0, "value": 5.0}',
            'rotate_set:{"axis": 0, "value": 5.0}')]
        changed = _diff(before, _staged(p, case)) != _diff(before, before)
    finally:
        articulation.set_dev_override(None)
    if locked:
        assert not any(results) and not changed
```

Before running, check `_diff`'s "no change" value in `tests/ui/spv_test_fixtures.py`.
`_diff(before, before)` is used above as "no change" so the test doesn't assume
its shape. If `_diff` returns a falsy value for no change, these assertions still
hold.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/ui/test_spv_value_set.py -q`
Expected: the `*_set` tests FAIL, because `dispatch_event` returns `False` for
unknown actions while the nudges return `True`.

- [ ] **Step 3: Implement**

Change `_MOUNT_GIZMO_PREFIXES` to:

```python
    _MOUNT_GIZMO_PREFIXES = ("coord_nudge:", "scale_nudge:", "rotate_nudge:",
                             "coord_set:", "scale_set:", "rotate_set:")
```

Add a module-level helper near the top of the file, after the imports:

```python
def _parse_set(action: str, key: str):
    """(index, value) from a '<verb>_set:{"<key>": i, "value": v}' action, or
    None when malformed or the value is not finite (json accepts NaN/Infinity
    tokens -- typed values must never stage them)."""
    try:
        arg = json.loads(action.split(":", 1)[1])
        index = int(arg[key])
        value = float(arg["value"])
    except (ValueError, KeyError, TypeError, IndexError):
        return None
    if not math.isfinite(value):
        return None
    return index, value
```

In `_dispatch_event_inner`, directly after the `coord_nudge:` handler:

```python
        if action.startswith("coord_set:"):
            # A typed value (click-to-edit row): set one component absolutely.
            parsed = _parse_set(action, "axis")
            if parsed is None or parsed[0] not in (0, 1, 2):
                return False
            axis, value = parsed
            t = self._edit_target()
            pos = t.position() if t is not None else None
            if pos is None:
                return False
            p = list(pos); p[axis] = value
            t.set_position(tuple(p))
            self._last_pushed = None
            return True
```

Directly after the `scale_nudge:` handler:

```python
        if action.startswith("scale_set:"):
            parsed = _parse_set(action, "index")
            if parsed is None:
                return False
            index, value = parsed
            t = self._scale_edit_target()
            if t is None:
                return False
            _kind, fields = t.scale_kind()
            if not (0 <= index < len(fields)):
                return False
            t.set_scale_field(index, value)
            return True
```

Directly after the `rotate_nudge:` handler:

```python
        if action.startswith("rotate_set:"):
            # The Rotate rows show a per-target ACCUMULATOR of degrees nudged,
            # not an absolute angle: typing v rotates by (v - shown), exactly
            # what clicking the steppers until the row read v would do.
            parsed = _parse_set(action, "axis")
            if parsed is None:
                return False
            axis, value = parsed
            t = self._rotate_edit_target()
            spec = t.rotate_spec() if t is not None else None
            if spec is None or not (0 <= axis < len(spec["fields"])):
                return False
            t.rotate_nudge(axis, value - spec["fields"][axis]["value"])
            return True
```

- [ ] **Step 4: Run it, plus the existing SPV suites**

Run: `uv run pytest tests/ui/test_spv_value_set.py tests/ui/test_spv_edit_target_characterisation.py tests/ui/ -q -k "spv or ship_property"`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add engine/ui/ship_property_viewer_panel.py tests/ui/test_spv_value_set.py
git commit -m "feat(spv): coord_set / scale_set / rotate_set -- typed row values"
```

---

### Task 9: SPV click-to-edit rows

**Files:**
- Modify: `native/assets/ui-cef/js/ship_property_viewer.js`:
  - `spvStepperRow` (about 185), `spvShowPanel` (about 198) and
    `renderSPVToolPanels` (about 224);
  - the Esc comment at about 262-268;
  - the radius-stepper comment at about 398-400.
- Modify: `native/assets/ui-cef/index.html`:
  - `#spv-root` (about line 293) gets `data-panel`;
  - the coords comment at about 448-451.
- Modify: `native/assets/ui-cef/css/ship_property_viewer.css` (beside `.spv-coords__val`, about line 624)
- Create: `tests/ui/test_spv_value_edit_js.py`

**Interfaces:**
- Consumes:
  - Task 6: `__dauntlessTextCancel(el)`, `__dauntlessTextCommit(el)` and the
    `data-panel` contract;
  - Task 8: the `coord_set`, `scale_set` and `rotate_set` actions.
- Produces: `spvBeginValueEdit(span, kind, index, value)`,
  `spvFinishValueEdit(input)` and `spvParseValue(text) -> number|null` (JS
  globals).

- [ ] **Step 1: Write the failing tests**

`tests/ui/test_spv_value_edit_js.py`:

```python
"""Source-shape guards for the SPV click-to-edit value rows (no JS runtime
harness -- brainstorm D6; behaviour is Mark's live check, spec S8).

Spec: docs/superpowers/specs/2026-10-02-cef-text-input-keyboard-capture-design.md S5.1
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "native/assets/ui-cef/js/ship_property_viewer.js"
HTML = ROOT / "native/assets/ui-cef/index.html"
CSS = ROOT / "native/assets/ui-cef/css/ship_property_viewer.css"


def _fn(src, name):
    m = re.search(r"function\s+%s\s*\(" % name, src)
    assert m, name
    i = src.index("{", m.end())
    depth = 0
    for j in range(i, len(src)):
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        if depth == 0:
            return src[i:j + 1]
    raise AssertionError(name)


def test_spv_root_is_tagged_for_text_capture():
    assert re.search(r'<div id="spv-root"[^>]*data-panel="ship-property-viewer"',
                     HTML.read_text())


def test_value_span_is_still_between_the_steppers_and_starts_an_edit():
    body = _fn(JS.read_text(), "spvStepperRow")
    order = [body.index("b(-big)"), body.index("b(-small)"),
             body.index("spv-coords__val"), body.index("b(small)"),
             body.index("b(big)")]
    assert order == sorted(order)
    assert "spvBeginValueEdit(" in body


def test_all_three_panels_pass_their_kind():
    body = _fn(JS.read_text(), "renderSPVToolPanels")
    for kind in ("'coord'", "'scale'", "'rotate'"):
        assert kind in body


def test_edit_keeps_the_axis_label_and_adds_cancel_then_ok():
    body = _fn(JS.read_text(), "spvBeginValueEdit")
    assert "spv-coords__axis" in body
    assert body.index("\\u2715") < body.index("\\u2713")      # ✕ then ✓
    assert "__dauntlessTextCancel(" in body and "__dauntlessTextCommit(" in body
    assert ".select()" in body


def test_edit_buttons_do_not_steal_focus():
    body = _fn(JS.read_text(), "spvEditButton")
    assert "'mousedown'" in body and "preventDefault()" in body


def test_unchanged_text_sends_nothing_and_commit_routes_each_kind():
    body = _fn(JS.read_text(), "spvFinishValueEdit")
    assert body.index("=== ed.original") < body.index("dauntlessEvent(")
    for ev in ("coord_set", "scale_set", "rotate_set"):
        assert ev in body


def test_parse_rejects_empty_and_accepts_decimal_comma():
    """Review Focus 1 + 2: Number('') is 0, so empty must be refused
    explicitly; '1,5' must read as 1.5."""
    body = _fn(JS.read_text(), "spvParseValue")
    assert ".trim()" in body
    assert "=== ''" in body
    assert body.index("=== ''") < body.index("Number(")
    assert "replace(','" in body
    assert "isFinite(" in body


def test_show_panel_does_not_rebuild_under_an_open_edit():
    body = _fn(JS.read_text(), "spvShowPanel")
    guard = body.index("spvEdit")
    assert guard < body.index("innerHTML")


def test_stale_mouse_only_comments_are_gone():
    """Every 'no keyboard->CEF forwarding' claim is false once capture ships."""
    assert "keyboard->CEF" not in HTML.read_text()
    assert "keyboard->CEF" not in JS.read_text()


def test_value_reads_as_clickable_and_input_is_styled():
    css = CSS.read_text()
    assert re.search(r"\.spv-coords__val\s*\{[^}]*cursor:\s*text", css)
    assert ".spv-coords__input" in css
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/ui/test_spv_value_edit_js.py -v`
Expected: most FAIL.

- [ ] **Step 3: Implement the JS**

Replace `spvStepperRow` with:

```js
function spvStepperRow(label, value, digits, unit, small, big, handler, index, kind) {
    function b(delta) {
        return '<button class="spv-step" onclick="' + handler + '(' + index + ','
            + parseFloat(delta.toPrecision(6)) + ')">' + spvStepLabel(delta, unit) + '</button>';
    }
    // Click the value to type one (spvBeginValueEdit): the row is swapped for
    // an input + Cancel/OK while editing and restored after.
    return '<div class="spv-coords__row">'
        + '<span class="spv-coords__axis">' + escapeHtmlSPV(label) + '</span>'
        + b(-big) + b(-small)
        + '<span class="spv-coords__val" onclick="spvBeginValueEdit(this,\'' + kind + '\','
        + index + ',' + Number(value) + ')">' + value.toFixed(digits) + (unit || '') + '</span>'
        + b(small) + b(big)
        + '</div>';
}

// ── Click-to-edit values ────────────────────────────────────────────────────
// One row at a time. While it edits, spvShowPanel leaves that panel alone so
// a payload refresh or gizmo push can't destroy the input. The row commits on
// its input's BLUR (Enter, OK, click/tab elsewhere in the page) -- unless the
// text is unchanged, which is also how Esc, Cancel and a host-forced release
// land: text_capture.js restores the pre-filled text before blurring, so no
// cancel flag is needed (its capture-phase Esc handler stops propagation, so
// the row never sees the Esc keydown anyway).
var spvEdit = null;   // {row, html, kind, index, original, done}

function spvParseValue(text) {
    var s = String(text).trim().replace(',', '.');
    if (s === '') return null;          // Number('') is 0: never commit a blank
    var v = Number(s);
    return isFinite(v) ? v : null;
}

function spvEditButton(label, cls, onClick) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'spv-step spv-coords__edit-btn ' + cls;
    b.textContent = label;
    // Keep focus in the input: a blur here would commit before Cancel runs.
    b.addEventListener('mousedown', function (e) { e.preventDefault(); });
    b.addEventListener('click', onClick);
    return b;
}

function spvBeginValueEdit(span, kind, index, value) {
    if (spvEdit) return;
    var row = span.parentNode;
    var axis = row.querySelector('.spv-coords__axis');
    var original = String(parseFloat(Number(value).toPrecision(12)));
    spvEdit = {row: row, html: row.innerHTML, kind: kind, index: index,
               original: original, done: false};
    row.innerHTML = '';
    row.appendChild(axis);
    var input = document.createElement('input');
    input.type = 'text';
    input.className = 'spv-coords__input';
    input.setAttribute('inputmode', 'decimal');
    input.value = original;
    row.appendChild(input);
    row.appendChild(spvEditButton('✕', 'spv-coords__edit-btn--cancel',
        function () { __dauntlessTextCancel(input); }));
    row.appendChild(spvEditButton('✓', 'spv-coords__edit-btn--ok',
        function () { __dauntlessTextCommit(input); }));
    input.addEventListener('blur', function () { spvFinishValueEdit(input); });
    input.focus();
    input.select();
}

function spvFinishValueEdit(input) {
    var ed = spvEdit;
    if (!ed || ed.done) return;
    ed.done = true;
    spvEdit = null;
    var text = input.value;
    ed.row.innerHTML = ed.html;          // swap back; the next payload refreshes it
    if (text === ed.original) return;    // Esc / Cancel / forced release / no change
    var v = spvParseValue(text);
    if (v === null) return;              // blank or not a number: revert
    var verb = {coord: 'coord_set', scale: 'scale_set', rotate: 'rotate_set'}[ed.kind];
    var arg = {};
    arg[ed.kind === 'scale' ? 'index' : 'axis'] = ed.index;
    arg.value = v;
    dauntlessEvent('ship-property-viewer/' + verb + ':' + JSON.stringify(arg));
}
```

In `spvShowPanel`, insert as the first statements after `if (!el) return;`:

```js
    // A row in this panel is being typed into: leave it alone until it ends.
    if (spvEdit && el.contains(spvEdit.row)) return;
```

The test requires `spvEdit` to appear before the first `innerHTML` in
`spvShowPanel`.

In `renderSPVToolPanels`, append the kind argument to the three calls:

- `'shipPropertyViewerCoordNudge', i, 'coord'`
- `'shipPropertyViewerScaleNudge', i, 'scale'`
- `'shipPropertyViewerRotateNudge', i, 'rotate'`

Update the Esc comment block (about 262-268). After its last sentence, add:
"Exception: while a text field (e.g. a Move/Rotate/Scale value row) has
focus, Esc goes to the page instead. text_capture.js reverts and blurs the
field, and the host's ESC router reads nothing until that key is released
(native KeyGate)."

**Reword every stale "no keyboard->CEF forwarding" comment.** It is false once
this ships. There are 8 at plan time:

- `ship_property_viewer.js`: about lines 398, 428, 499 and 1283;
- `index.html`: about lines 450, 529, 580 and 616. Line 450 is handled in
  Step 4.

Find them with `grep -n "keyboard->CEF" native/assets/ui-cef/index.html native/assets/ui-cef/js/ship_property_viewer.js`.

Each describes a widget that stays mouse-only (the radius stepper, the light
modal, the part popups). Keep what the comment says about the widget, and
replace the forwarding claim with "mouse-only; typed input is available through
the text-capture contract (spec 2026-10-02) but not adopted here". The guard
test fails if any instance of the phrase survives.

- [ ] **Step 4: Implement the HTML and CSS**

In `index.html`:

- change `<div id="spv-root" class="spv-root dev-only">` to
  `<div id="spv-root" class="spv-root dev-only" data-panel="ship-property-viewer">`;
- in the comment above `#spv-coords` (about 448-451), replace "Mouse-only
  steppers (no keyboard->CEF forwarding)." with "Steppers, plus click-the-value
  to type one (spvBeginValueEdit)."

In `ship_property_viewer.css`, change
`.spv-coords__val { flex: 1; text-align: center; font-variant-numeric: tabular-nums; }`
to:

```css
.spv-coords__val { flex: 1; text-align: center; font-variant-numeric: tabular-nums; cursor: text; }
/* Click-to-edit: the input takes the steppers' + value's space; the axis
   label stays. Buttons reuse .spv-step so they match the steppers. */
.spv-coords__input {
    flex: 1;
    min-width: 0;
    font: inherit;
    font-variant-numeric: tabular-nums;
    text-align: center;
    color: inherit;
    background: rgba(0, 0, 0, 0.55);
    border: 1px solid rgba(255, 214, 90, 0.6);
    border-radius: 2px;
    padding: 1px 4px;
    outline: none;
}
.spv-coords__edit-btn { flex: 0 0 auto; }
```

- [ ] **Step 5: Run it and watch it pass, then run the SPV suites**

Run: `uv run pytest tests/ui/test_spv_value_edit_js.py tests/ui/ -q -k "spv or ship_property or text_capture"`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git branch --show-current
git add native/assets/ui-cef/js/ship_property_viewer.js native/assets/ui-cef/index.html native/assets/ui-cef/css/ship_property_viewer.css tests/ui/test_spv_value_edit_js.py
git commit -m "feat(spv): click-to-edit Move/Rotate/Scale values with cancel/ok"
```

---

### Task 10: Docs and the full gate

**Files:**
- Modify: `CLAUDE.md` (a new row in the "Key reference material" table, after the "Developer flag" row)
- Modify: `docs/superpowers/specs/2026-10-01-mod-ships-screen-design.md` (§6, the "In-game forwarding" bullet)
- Modify: `docs/superpowers/specs/2026-10-02-cef-text-input-keyboard-capture-design.md` (Status line)

- [ ] **Step 1: Add the `CLAUDE.md` row**

Insert after the `| Developer flag | ...` row:

```markdown
| **Keyboard capture for CEF text fields** | `native/src/renderer/key_gate.{h,cc}`, `engine/ui/text_capture.py`, `native/assets/ui-cef/js/text_capture.js`, `docs/superpowers/specs/2026-10-02-cef-text-input-keyboard-capture-design.md` | While an editable element in the in-game page has focus, the game reads **no keys at all**: `Window::key_state` filters every read through `KeyGate`, so the 60+ direct `h.key_*` call sites need no changes. ⚠️ **Never call `glfwGetKey` outside `Window::key_state` / `set_key_capture`** — `tests/tools/test_raw_key_reads.py` fails the gate. A key held when capture ends stays masked until released (the Esc/Enter that ended an edit is never a game press). Release triggers: page blur, native reset on load/crash, owner panel closed, mission swap, unrouted click. **Panel contract:** tag the root `data-panel="<registry name>"`, commit on `change`; capture is automatic. Cmd/Ctrl+A/C/V/X/Z/Y run `CefFrame` edit commands (macOS OSR never acts on Cmd as keys). First consumer: SPV Move/Rotate/Scale click-to-edit rows. |
```

- [ ] **Step 2: Point the Mods-screen spec at the new one**

In `2026-10-01-mod-ships-screen-design.md` §6, replace the last bullet, the
one that begins "**In-game forwarding** needs focus arbitration …", with:

```markdown
- **In-game forwarding** is built by
  `2026-10-02-cef-text-input-keyboard-capture-design.md`: a native key gate,
  page-reported focus and release triggers. The in-game host drains the queue
  every frame and forwards it only while a field holds the keyboard.
```

- [ ] **Step 3: Update the spec status**

In the new spec, change `**Status:** spec, awaiting review` to
`**Status:** implemented on feat/cef-text-capture, awaiting live check (§8)`.

- [ ] **Step 4: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: exit 0, with no failure outside `tests/known_failures.txt`. If it
names a failure, it is a regression from this branch: fix it in its owning
task's files and re-run. Never baseline it.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add CLAUDE.md docs/superpowers/specs/2026-10-01-mod-ships-screen-design.md docs/superpowers/specs/2026-10-02-cef-text-input-keyboard-capture-design.md
git commit -m "docs: keyboard capture for CEF text fields -- CLAUDE.md row, spec status"
```

- [ ] **Step 6: Hand Mark the live check**

Do not launch the game. Give Mark spec §8's steps and a plain launch command
(no `#` comments, no `DAUNTLESS_MISSION`):

```
./build/dauntless --developer
```
