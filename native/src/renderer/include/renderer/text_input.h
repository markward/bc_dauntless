// native/src/renderer/include/renderer/text_input.h
//
// Typed text for CEF fields (Mods screen titles, class names). GLFW char and
// key callbacks push here; the host drains once per frame and forwards to
// CefBrowserHost::SendKeyEvent. Game key bindings never read this -- they
// poll glfwGetKey via Window::key_state. kind 2 carries edit commands.
#pragma once

#include <cstddef>
#include <deque>
#include <vector>

namespace renderer {

constexpr int kTextEventChar = 0;   // code = Unicode codepoint
constexpr int kTextEventKey = 1;    // code = GLFW key; only editing keys (glfw_key_to_windows_vk != 0)
constexpr int kTextEventEdit = 2;   // code = EditCommand (Cmd/Ctrl + A/C/V/X/Z/Y)

/// A clipboard/undo shortcut, run as a CefFrame command rather than a key
/// event: in macOS OSR, Cmd shortcuts arrive via the app's Edit menu, so CEF
/// never acts on them as keys. Values are the wire format (queue `code` and
/// ui_cef::edit_command's argument).
enum class EditCommand : int {
    None = 0, SelectAll = 1, Copy = 2, Paste = 3, Cut = 4, Undo = 5, Redo = 6,
};

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

/// The edit command for `letter` (the layout's character, from
/// glfwGetKeyName) with GLFW `mods`, or None. Primary modifier: SUPER on
/// macOS, CONTROL elsewhere; any other of SUPER/CONTROL/ALT also held => None.
EditCommand edit_command_for(char letter, int mods) noexcept;

}  // namespace renderer
