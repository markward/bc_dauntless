// native/src/renderer/window.cc
#include "renderer/window.h"

#include <glad/glad.h>
#include <GLFW/glfw3.h>

#include <atomic>
#include <stdexcept>
#include <string>

namespace renderer {

namespace {

std::atomic<int> g_glfw_users{0};

void ensure_glfw() {
    if (g_glfw_users.fetch_add(1) == 0) {
        if (!glfwInit()) {
            g_glfw_users.fetch_sub(1);
            throw std::runtime_error("renderer::Window: glfwInit failed");
        }
    }
}

void release_glfw() {
    // glfwTerminate() intentionally omitted: re-initialising GLFW on macOS
    // deadlocks in [NSApp run] because applicationDidFinishLaunching: only
    // fires once per process, so the second glfwInit has no event to stop
    // its run-loop on (see third_party/glfw/src/cocoa_init.m:634). The OS
    // reclaims GLFW state at process exit.
    g_glfw_users.fetch_sub(1);
}

}  // namespace

Window::Window(int width, int height, const std::string& title, bool visible) {
    ensure_glfw();

    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 3);
    glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
    glfwWindowHint(GLFW_OPENGL_FORWARD_COMPAT, GL_TRUE);
    glfwWindowHint(GLFW_VISIBLE, visible ? GLFW_TRUE : GLFW_FALSE);

    handle_ = glfwCreateWindow(width, height, title.c_str(), nullptr, nullptr);
    if (!handle_) {
        release_glfw();
        throw std::runtime_error("renderer::Window: glfwCreateWindow failed");
    }

    glfwMakeContextCurrent(handle_);

    // UiSystem installs the scroll callback so it can filter through RmlUi
    // before the camera sees the event; the user pointer lets per-window
    // callbacks (cursor, etc.) dispatch back to this Window instance.
    glfwSetWindowUserPointer(handle_, this);

    glfwSetCursorPosCallback(handle_, [](GLFWwindow* w, double x, double y) {
        if (auto* self = static_cast<Window*>(glfwGetWindowUserPointer(w))) {
            self->on_cursor_pos(x, y);
        }
    });

    if (!gladLoadGLLoader(reinterpret_cast<GLADloadproc>(glfwGetProcAddress))) {
        glfwDestroyWindow(handle_);
        handle_ = nullptr;
        release_glfw();
        throw std::runtime_error("renderer::Window: gladLoadGLLoader failed");
    }

    if (visible) {
        glfwSwapInterval(1);  // vsync gates the loop to monitor refresh.
    } else {
        glfwSwapInterval(0);
    }
}

Window::~Window() {
    if (handle_) {
        glfwDestroyWindow(handle_);
        handle_ = nullptr;
        release_glfw();
    }
}

Window::Window(Window&& other) noexcept
    : handle_(other.handle_),
      scroll_y_accum_(other.scroll_y_accum_),
      mouse_dx_accum_(other.mouse_dx_accum_),
      mouse_dy_accum_(other.mouse_dy_accum_),
      last_cursor_x_(other.last_cursor_x_),
      last_cursor_y_(other.last_cursor_y_),
      cursor_seeded_(other.cursor_seeded_) {
    other.handle_ = nullptr;
    other.scroll_y_accum_ = 0.0;
    other.mouse_dx_accum_ = 0.0;
    other.mouse_dy_accum_ = 0.0;
    other.cursor_seeded_  = false;
    if (handle_) glfwSetWindowUserPointer(handle_, this);
}

Window& Window::operator=(Window&& other) noexcept {
    if (this != &other) {
        if (handle_) {
            glfwDestroyWindow(handle_);
            release_glfw();
        }
        handle_ = other.handle_;
        scroll_y_accum_ = other.scroll_y_accum_;
        mouse_dx_accum_ = other.mouse_dx_accum_;
        mouse_dy_accum_ = other.mouse_dy_accum_;
        last_cursor_x_  = other.last_cursor_x_;
        last_cursor_y_  = other.last_cursor_y_;
        cursor_seeded_  = other.cursor_seeded_;
        other.handle_ = nullptr;
        other.scroll_y_accum_ = 0.0;
        other.mouse_dx_accum_ = 0.0;
        other.mouse_dy_accum_ = 0.0;
        other.cursor_seeded_  = false;
        if (handle_) glfwSetWindowUserPointer(handle_, this);
    }
    return *this;
}

bool Window::should_close() const noexcept {
    return handle_ ? glfwWindowShouldClose(handle_) != 0 : true;
}

void Window::swap_buffers() noexcept {
    if (handle_) glfwSwapBuffers(handle_);
}

void Window::poll_events() noexcept {
    glfwPollEvents();
}

void Window::framebuffer_size(int* w, int* h) const noexcept {
    if (handle_) glfwGetFramebufferSize(handle_, w, h);
    else { *w = 0; *h = 0; }
}

bool Window::key_state(int glfw_key) const noexcept {
    if (!handle_) return false;
    return glfwGetKey(handle_, glfw_key) == GLFW_PRESS;
}

bool Window::mouse_button_state(int glfw_button) const noexcept {
    if (!handle_) return false;
    return glfwGetMouseButton(handle_, glfw_button) == GLFW_PRESS;
}

double Window::consume_scroll_y() noexcept {
    double v = scroll_y_accum_;
    scroll_y_accum_ = 0.0;
    return v;
}

void Window::add_scroll_y(double dy) noexcept {
    scroll_y_accum_ += dy;
}

void Window::cursor_pos(double* out_x, double* out_y) const noexcept {
    if (!out_x || !out_y) return;
    double x = 0.0, y = 0.0;
    if (cursor_seeded_) {
        x = last_cursor_x_;
        y = last_cursor_y_;
    } else if (handle_) {
        // No callback has fired yet (window just created, cursor outside
        // viewport).  Query GLFW directly so callers don't see NaN/garbage.
        glfwGetCursorPos(handle_, &x, &y);
    }
    // Convert GLFW screen coords (logical pixels) to framebuffer coords
    // (physical pixels).  This matches PanelDocument::bounds() (which
    // returns RmlUi's framebuffer-space rect) so callers can do straight
    // inside-rect comparisons on Retina/high-DPI displays.
    if (handle_) {
        int win_w = 0, win_h = 0, fb_w = 0, fb_h = 0;
        glfwGetWindowSize(handle_, &win_w, &win_h);
        glfwGetFramebufferSize(handle_, &fb_w, &fb_h);
        if (win_w > 0) x *= static_cast<double>(fb_w) / static_cast<double>(win_w);
        if (win_h > 0) y *= static_cast<double>(fb_h) / static_cast<double>(win_h);
    }
    *out_x = x;
    *out_y = y;
}

void Window::on_cursor_pos(double x, double y) noexcept {
    if (cursor_seeded_) {
        mouse_dx_accum_ += x - last_cursor_x_;
        mouse_dy_accum_ += y - last_cursor_y_;
    }
    last_cursor_x_ = x;
    last_cursor_y_ = y;
    cursor_seeded_ = true;
}

void Window::consume_mouse_delta(double* dx, double* dy) noexcept {
    *dx = mouse_dx_accum_;
    *dy = mouse_dy_accum_;
    mouse_dx_accum_ = 0.0;
    mouse_dy_accum_ = 0.0;
}

void Window::set_cursor_locked(bool locked) noexcept {
    if (!handle_) return;
    glfwSetInputMode(handle_, GLFW_CURSOR,
                     locked ? GLFW_CURSOR_DISABLED : GLFW_CURSOR_NORMAL);
    // Enable raw, unaccelerated mouse motion when the platform supports
    // it. macOS in particular benefits — without raw motion, GLFW's
    // virtual cursor in disabled mode can produce zero deltas in some
    // window-focus states. glfwRawMouseMotionSupported() returns false
    // on platforms where the call would be a no-op, so this is safe to
    // call unconditionally.
    if (glfwRawMouseMotionSupported()) {
        glfwSetInputMode(handle_, GLFW_RAW_MOUSE_MOTION,
                         locked ? GLFW_TRUE : GLFW_FALSE);
    }
    // Drop the seed so the next cursor-pos event re-anchors and we don't
    // see a giant warp delta on lock-state change.
    cursor_seeded_ = false;
    // Flush any pre-existing accumulator content. While the cursor is
    // unlocked nothing consumes the deltas, so they accumulate across
    // every cursor movement in the space scene. Without this flush, the
    // first tick after entering bridge mode would apply the entire
    // pre-bridge cursor history as one giant delta and slam the camera
    // pitch into its clamp.
    mouse_dx_accum_ = 0.0;
    mouse_dy_accum_ = 0.0;
}

}  // namespace renderer
