// native/src/renderer/include/renderer/window.h
#pragma once

#include <string>

struct GLFWwindow;

namespace renderer {

class Window {
public:
    /// Construct a windowed GL 3.3 core context. `visible=false` creates a
    /// hidden window for offscreen tests. Throws std::runtime_error on
    /// GLFW or context-creation failure.
    Window(int width, int height, const std::string& title, bool visible = true);
    ~Window();

    Window(const Window&) = delete;
    Window& operator=(const Window&) = delete;
    Window(Window&&) noexcept;
    Window& operator=(Window&&) noexcept;

    bool should_close() const noexcept;
    void swap_buffers() noexcept;
    void poll_events() noexcept;

    /// Current framebuffer size in pixels (may differ from window size on
    /// HiDPI displays).
    void framebuffer_size(int* w, int* h) const noexcept;

    /// Cached state of a GLFW keyboard key. Returns true while the key is
    /// held. State is updated by glfwPollEvents() (called by poll_events()).
    bool key_state(int glfw_key) const noexcept;

    /// Cached state of a GLFW mouse button (GLFW_MOUSE_BUTTON_*). Returns
    /// true while the button is held. State is updated by poll_events().
    bool mouse_button_state(int glfw_button) const noexcept;

    /// Return the accumulated mouse-wheel Y delta since the last call and
    /// reset the accumulator. Positive = scroll up. Updated from the GLFW
    /// scroll callback during poll_events().
    double consume_scroll_y() noexcept;

    /// Add `dy` to the internal scroll accumulator.  Used by UiSystem
    /// to re-emit scroll deltas that RmlUi declined to consume — keeps
    /// the camera-zoom path unchanged.
    void add_scroll_y(double dy) noexcept;

    /// Write the most recently observed cursor position (in screen pixels)
    /// to *out_x, *out_y.  Updated by GLFW's cursor-position callback.
    /// Before the first cursor event, returns the initial cursor pos
    /// queried from GLFW.
    void cursor_pos(double* out_x, double* out_y) const noexcept;

    /// Return the accumulated mouse cursor delta since the last call (in
    /// pixels) and reset the accumulator. Updated from the GLFW cursor
    /// callback during poll_events(). Deltas accumulate even when the
    /// cursor is unlocked; consumers gate use by other means.
    void consume_mouse_delta(double* dx, double* dy) noexcept;

    /// Lock or release the cursor. Locked = hidden + warped to centre
    /// each frame so motion produces unbounded raw deltas. Unlocked =
    /// normal cursor visible inside the window.
    void set_cursor_locked(bool locked) noexcept;

    GLFWwindow* native_handle() noexcept { return handle_; }

private:
    GLFWwindow* handle_ = nullptr;
    double      scroll_y_accum_ = 0.0;
    double      mouse_dx_accum_ = 0.0;
    double      mouse_dy_accum_ = 0.0;
    double      last_cursor_x_  = 0.0;
    double      last_cursor_y_  = 0.0;
    bool        cursor_seeded_  = false;  // false until first cursor-pos event
};

}  // namespace renderer
