// native/src/renderer/include/renderer/text_input.h
//
// Typed text for CEF fields (Mods screen titles, class names). GLFW char and
// key callbacks push here; the host drains once per frame and forwards to
// CefBrowserHost::SendKeyEvent. Game key bindings never read this -- they
// poll glfwGetKey via Window::key_state.
#pragma once

#include <cstddef>
#include <deque>
#include <vector>

namespace renderer {

constexpr int kTextEventChar = 0;   // code = Unicode codepoint
constexpr int kTextEventKey = 1;    // code = GLFW key; only editing keys

struct TextEvent {
    int kind;
    int code;
    int scancode;   // native key code (macOS kVK_*), for CEF native_key_code
    int action;     // GLFW_PRESS / GLFW_REPEAT / GLFW_RELEASE
    int mods;       // GLFW_MOD_* bits
};

class TextEventQueue {
public:
    static constexpr std::size_t kCapacity = 256;
    void push(const TextEvent& e);
    std::vector<TextEvent> drain();
    std::size_t size() const noexcept { return q_.size(); }
private:
    std::deque<TextEvent> q_;
};

/// Windows virtual-key code for an editing key (what CEF's windows_key_code
/// expects on every platform), or 0 if `glfw_key` is not one we forward.
int glfw_key_to_windows_vk(int glfw_key) noexcept;

}  // namespace renderer
