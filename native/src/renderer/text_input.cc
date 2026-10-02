// native/src/renderer/text_input.cc
#include "renderer/text_input.h"

#include <GLFW/glfw3.h>

namespace renderer {

void TextEventQueue::push(const TextEvent& e) {
    // Bounded: the host drains every frame (engine/ui/text_capture.py); the
    // cap only matters if a frame stalls, so the oldest events fall off
    // rather than growing.
    if (q_.size() >= kCapacity) q_.pop_front();
    q_.push_back(e);
}

std::vector<TextEvent> TextEventQueue::drain() {
    std::vector<TextEvent> out(q_.begin(), q_.end());
    q_.clear();
    return out;
}

int glfw_key_to_windows_vk(int glfw_key) noexcept {
    switch (glfw_key) {
        case GLFW_KEY_BACKSPACE: return 0x08;  // VK_BACK
        case GLFW_KEY_TAB:       return 0x09;  // VK_TAB
        case GLFW_KEY_ENTER:     return 0x0D;  // VK_RETURN
        case GLFW_KEY_ESCAPE:    return 0x1B;  // VK_ESCAPE
        case GLFW_KEY_END:       return 0x23;  // VK_END
        case GLFW_KEY_HOME:      return 0x24;  // VK_HOME
        case GLFW_KEY_LEFT:      return 0x25;  // VK_LEFT
        case GLFW_KEY_UP:        return 0x26;  // VK_UP
        case GLFW_KEY_RIGHT:     return 0x27;  // VK_RIGHT
        case GLFW_KEY_DOWN:      return 0x28;  // VK_DOWN
        case GLFW_KEY_DELETE:    return 0x2E;  // VK_DELETE
        default:                 return 0;
    }
}

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

}  // namespace renderer
