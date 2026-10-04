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

namespace {

// The fixed editing-key set: the only GLFW keys that ever get a KEYDOWN
// from TextEventTranslator without a following char event. Deliberately
// its own table (not glfw_key_to_windows_vk) because GLFW_KEY_KP_ENTER
// belongs here too but has no distinct VK -- it is CEF's windows_key_code
// for VK_RETURN just the same as GLFW_KEY_ENTER, and CEF's reference NSEvent
// behaviour treats them identically.
bool is_editing_key(int glfw_key) noexcept {
    switch (glfw_key) {
        case GLFW_KEY_BACKSPACE:
        case GLFW_KEY_TAB:
        case GLFW_KEY_ENTER:
        case GLFW_KEY_KP_ENTER:
        case GLFW_KEY_ESCAPE:
        case GLFW_KEY_END:
        case GLFW_KEY_HOME:
        case GLFW_KEY_LEFT:
        case GLFW_KEY_UP:
        case GLFW_KEY_RIGHT:
        case GLFW_KEY_DOWN:
        case GLFW_KEY_DELETE:
            return true;
        default:
            return false;
    }
}

// The character a real macOS keyboard's NSEvent carries for an editing key
// with no text to insert (an arrow, Home/End/Delete, or a control key).
// Values are NSEvent's own function-key / control-character constants.
// Off-Apple, the function keys (arrows/Home/End/Delete) carry
// no character at all -- CEF uses windows_key_code for those on that
// platform, and the macOS character==0 flags-changed trap this translator
// exists to dodge does not apply there.
char16_t platform_editing_char(int glfw_key) noexcept {
#if defined(__APPLE__)
    switch (glfw_key) {
        case GLFW_KEY_UP:        return 0xF700;
        case GLFW_KEY_DOWN:      return 0xF701;
        case GLFW_KEY_LEFT:      return 0xF702;
        case GLFW_KEY_RIGHT:     return 0xF703;
        case GLFW_KEY_DELETE:    return 0xF728;
        case GLFW_KEY_HOME:      return 0xF729;
        case GLFW_KEY_END:       return 0xF72B;
        case GLFW_KEY_BACKSPACE: return 0x7F;
        case GLFW_KEY_ENTER:
        case GLFW_KEY_KP_ENTER:  return 0x0D;
        case GLFW_KEY_TAB:       return 0x09;
        case GLFW_KEY_ESCAPE:    return 0x1B;
        default:                 return 0;
    }
#else
    switch (glfw_key) {
        case GLFW_KEY_BACKSPACE: return 0x08;
        case GLFW_KEY_ENTER:
        case GLFW_KEY_KP_ENTER:  return 0x0D;
        case GLFW_KEY_TAB:       return 0x09;
        case GLFW_KEY_ESCAPE:    return 0x1B;
        default:                 return 0;  // arrows / Home / End / Delete
    }
#endif
}

// windows_key_code for any key, editing or printable. Ignored by CEF on
// macOS (derived from the synthetic NSEvent there instead); used verbatim
// on Windows/Linux. GLFW's A..Z and 0..9 codes are already the matching VK
// codes (ASCII 'A'-'Z' / '0'-'9' == VK_A-VK_Z / VK_0-VK_9), so no table is
// needed for those.
int windows_vk_for(int glfw_key) noexcept {
    // GLFW_KEY_KP_ENTER has no case in glfw_key_to_windows_vk (that table
    // is also the is_editing_key/non-editing-key boundary elsewhere), but
    // it is still VK_RETURN -- same as GLFW_KEY_ENTER -- per is_editing_key's
    // doc comment above.
    if (glfw_key == GLFW_KEY_KP_ENTER) return glfw_key_to_windows_vk(GLFW_KEY_ENTER);
    const int editing_vk = glfw_key_to_windows_vk(glfw_key);
    if (editing_vk != 0) return editing_vk;
    if (glfw_key >= GLFW_KEY_A && glfw_key <= GLFW_KEY_Z) return glfw_key;
    if (glfw_key >= GLFW_KEY_0 && glfw_key <= GLFW_KEY_9) return glfw_key;
    return 0;
}

// CEF's own reference Windows path sends RAWKEYDOWN (what WM_KEYDOWN is);
// the synthetic-NSEvent macOS path sends KEYDOWN (see
// CefBrowserPlatformDelegateNativeMac::TranslateWebKeyEvent). Unverified
// off-Apple -- no reference client to check against there.
constexpr CefKeyType kKeyDownType =
#if defined(__APPLE__)
    CefKeyType::KeyDown;
#else
    CefKeyType::RawKeyDown;
#endif

}  // namespace

std::vector<CefKeyIntent> TextEventTranslator::translate(const std::vector<TextEvent>& events) {
    std::vector<CefKeyIntent> out;
    for (std::size_t i = 0; i < events.size(); ++i) {
        const TextEvent& e = events[i];

        if (e.kind == kTextEventEdit) {
            continue;  // caller routes these to ui_cef::edit_command directly
        }

        if (e.kind == kTextEventChar) {
            // A char that was not consumed as the pair for a preceding key
            // (below, via ++i) arrived with nothing to pair it to -- IME,
            // compose, or some other unusual input. One KeyDown+Char, no
            // KEYUP: there is no key to release.
            if (e.code > 0xFFFF) continue;  // not representable in char16_t; drop it
            const char16_t c = static_cast<char16_t>(e.code);
            out.push_back({kKeyDownType, 0, 0, c, c, e.mods});
            out.push_back({CefKeyType::Char, 0, 0, c, c, e.mods});
            continue;
        }

        // e.kind == kTextEventKey
        const int key = e.code;
        const int vk = windows_vk_for(key);

        if (e.action != /*GLFW_RELEASE*/ 0) {
            // PRESS or REPEAT. Rule 1: immediately followed by its char.
            if (i + 1 < events.size() && events[i + 1].kind == kTextEventChar) {
                const int raw = events[i + 1].code;
                ++i;  // consume the char either way -- it belongs to this key
                if (raw > 0xFFFF) continue;  // not representable; drop key+char, not remembered
                const char16_t c = static_cast<char16_t>(raw);
                out.push_back({kKeyDownType, vk, e.scancode, c, c, e.mods});
                out.push_back({CefKeyType::Char, vk, e.scancode, c, c, e.mods});
                held_[key] = c;
                continue;
            }
            // Rule 2: no char, but a platform editing character.
            if (is_editing_key(key)) {
                const char16_t c = platform_editing_char(key);
                out.push_back({kKeyDownType, vk, e.scancode, c, c, e.mods});
                if (c != 0) {
                    out.push_back({CefKeyType::Char, vk, e.scancode, c, c, e.mods});
                }
                held_[key] = c;
                continue;
            }
            // Rule 3: neither (Shift alone, F-keys, a letter whose char
            // Cocoa ate). Emit nothing; do not remember.
            continue;
        }

        // RELEASE. platform_editing_char/the paired-char branch above never
        // remember a 0 character on Apple (every Apple fn() value and every
        // typed char is non-zero), which is the property that matters: a
        // 0-character KEYUP is what macOS itself would misread as a
        // key-down. Off-Apple a 0 character (arrows/Home/End/Delete) is
        // harmless to send -- that flags-changed rule is macOS-only -- so
        // it still gets its KEYUP there.
        auto it = held_.find(key);
        if (it != held_.end()) {
            const char16_t c = it->second;
            held_.erase(it);
            out.push_back({CefKeyType::KeyUp, vk, e.scancode, c, c, e.mods});
        }
    }
    return out;
}

void TextEventTranslator::reset() noexcept {
    held_.clear();
}

std::vector<TextEventStep> build_text_event_steps(const std::vector<TextEvent>& events,
                                                     TextEventTranslator& translator) {
    std::vector<TextEventStep> steps;
    std::vector<TextEvent> run;  // the kind-0/1 events since the last kind-2 (or the start)

    // Translate and emit `run` as one step, in the SAME call to
    // `translator.translate` -- that is what lets a key and its
    // immediately-following char pair even though build_text_event_steps
    // itself only sees them inside this one accumulated run. Skipped when
    // empty so two adjacent edit commands get exactly one step apiece,
    // not an empty key-step wedged between them.
    const auto flush = [&]() {
        if (run.empty()) return;
        TextEventStep step;
        step.is_edit_command = false;
        step.intents = translator.translate(run);
        steps.push_back(std::move(step));
        run.clear();
    };

    for (const auto& e : events) {
        if (e.kind == kTextEventEdit) {
            flush();  // order: whatever key/char run came before this edit, first
            TextEventStep step;
            step.is_edit_command = true;
            step.command = static_cast<EditCommand>(e.code);
            steps.push_back(std::move(step));
            continue;
        }
        run.push_back(e);
    }
    flush();
    return steps;
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
