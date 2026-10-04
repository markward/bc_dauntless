// native/src/renderer/include/renderer/text_input.h
//
// Typed text for CEF fields (Mods screen titles, class names). GLFW char and
// key callbacks push here; the host drains once per frame, runs the queue
// through TextEventTranslator, and forwards the result to
// CefBrowserHost::SendKeyEvent. Game key bindings never read this -- they
// poll glfwGetKey via Window::key_state. kind 2 carries edit commands.
#pragma once

#include <cstddef>
#include <deque>
#include <unordered_map>
#include <vector>

namespace renderer {

constexpr int kTextEventChar = 0;   // code = Unicode codepoint
constexpr int kTextEventKey = 1;    // code = GLFW key; every key, not just editing keys --
                                     // TextEventTranslator needs every PRESS/RELEASE to pair
                                     // keys with their char and to know when to emit a KEYUP
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

// ── TextEventTranslator ─────────────────────────────────────────────────
//
// Turns the raw per-frame TextEvent queue into the KEYDOWN+CHAR / KEYUP
// sequence a real keyboard produces, with a non-zero character on every
// event. That is load-bearing on macOS: CEF's native key translator
// (CefBrowserPlatformDelegateNativeMac::TranslateWebKeyEvent) treats
// character == 0 && unmodified_character == 0 as NSEventTypeFlagsChanged
// and ignores the KEYEVENT type entirely -- so sending editing keys with
// character 0 on both press AND release made both arrive in Blink as a
// key-down (the live bug: one Right-arrow tap moved the caret twice).
//
// cef_key_event_type_t values, named here so text_input.{h,cc} does not
// depend on the CEF SDK headers (only ui_cef does).
enum class CefKeyType : int { RawKeyDown = 0, KeyDown = 1, KeyUp = 2, Char = 3 };

struct CefKeyIntent {
    CefKeyType type;
    int windows_key_code;       // CEF's windows_key_code; ignored by CEF on macOS
    int native_key_code;        // the queued scancode, or 0 for an unpaired char
    char16_t character;
    char16_t unmodified_character;
    int glfw_mods;
};

/// Pure, stateful translator: one per CEF browser (host_bindings.cc keeps a
/// single file-static instance). `translate` turns one frame's drained
/// TextEvents, in order, into the CefKeyIntent sequence to send; `reset`
/// forgets every key the translator currently believes is held, so a key
/// still down across a capture boundary cannot emit an orphaned KEYUP into
/// a page that never saw its KEYDOWN.
///
/// Rules (see docs/superpowers/specs/2026-10-02-cef-text-input-keyboard-
/// capture-design.md §2.7 for the full writeup):
///   - a PRESS/REPEAT immediately followed by its char event pairs into
///     KeyDown+Char and remembers the character for the matching KEYUP;
///   - a PRESS/REPEAT of a key with no following char but a platform
///     control character (arrows, Home/End/Delete, Backspace, Enter/KP
///     Enter, Tab, Escape) emits that KeyDown(+Char on Apple; Apple's fn()
///     table is never 0), and remembers it too;
///   - a PRESS/REPEAT with neither (Shift alone, F-keys, a letter whose
///     char Cocoa ate) emits nothing and is not remembered;
///   - a RELEASE emits a KEYUP with the remembered character only if one
///     is remembered -- never a KEYUP with character 0, which macOS would
///     itself misread as a key-down;
///   - a bare char with no preceding key (IME/compose) emits KeyDown+Char
///     with native_key_code 0 and is never remembered (so it has no KEYUP);
///   - a char event (paired or bare) whose codepoint is above 0xFFFF (not
///     representable in CEF's char16_t fields) emits nothing -- a key
///     paired with one is dropped entirely, not remembered, same as a key
///     with neither a char nor a platform character;
///   - kind-2 (edit command) events are not translated -- the caller routes
///     those to ui_cef::edit_command directly (see build_text_event_steps
///     below for preserving relative order against a mixed batch).
///
/// Off-Apple (unverified -- no reference client to check against): the
/// key-down type is RawKeyDown rather than KeyDown (CEF's own Windows path
/// sends RAWKEYDOWN), and the CHAR half is skipped whenever the platform
/// character is 0 (arrows/Home/End/Delete carry no character off-Apple;
/// windows_key_code carries the key instead, and CEF's char==0 flags-
/// changed rule is macOS-only so a 0-character KEYUP is harmless there).
class TextEventTranslator {
public:
    std::vector<CefKeyIntent> translate(const std::vector<TextEvent>& events);
    void reset() noexcept;

private:
    std::unordered_map<int, char16_t> held_;  // GLFW key -> character to replay on KEYUP
};

/// One step in a drained batch's send order: either a run of translated
/// key intents, or one edit command. `build_text_event_steps` (below)
/// returns these in the SAME relative order the events were queued in --
/// that is the whole point of the type. A caller that instead ran every
/// edit command first and every key intent after (as a naive two-pass
/// split would) reorders a frame that holds, say, a typed character
/// immediately followed by Cmd+Z: the undo would run before the type it
/// was supposed to undo.
struct TextEventStep {
    bool is_edit_command;
    EditCommand command;              // valid when is_edit_command
    std::vector<CefKeyIntent> intents;  // valid when !is_edit_command
};

/// Splits one frame's drained `events` into ordered steps, feeding every
/// contiguous run of kind 0/1 events through `translator` (so a key and
/// its immediately-following char event still pair correctly -- pairing
/// never needs to span a kind-2 event: window.cc's key callback returns
/// early for a clipboard/undo chord, so a chord key is never also queued
/// as kind 1) and emitting one step per kind-2 event in between, in the
/// batch's original order. The caller (host_bindings.cc's
/// cef_send_text_events) just walks the result and executes each step
/// as it appears.
std::vector<TextEventStep> build_text_event_steps(const std::vector<TextEvent>& events,
                                                    TextEventTranslator& translator);

}  // namespace renderer
