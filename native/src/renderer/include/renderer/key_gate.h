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
