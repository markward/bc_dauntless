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

    GLFWwindow* native_handle() noexcept { return handle_; }

private:
    GLFWwindow* handle_ = nullptr;
};

}  // namespace renderer
