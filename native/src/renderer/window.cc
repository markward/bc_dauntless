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
    if (g_glfw_users.fetch_sub(1) == 1) {
        glfwTerminate();
    }
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

    // Wire mouse-wheel events into scroll_y_accum_. The user pointer lets
    // the static callback dispatch back to this Window instance.
    glfwSetWindowUserPointer(handle_, this);
    glfwSetScrollCallback(handle_, [](GLFWwindow* w, double, double yoffset) {
        if (auto* self = static_cast<Window*>(glfwGetWindowUserPointer(w))) {
            self->scroll_y_accum_ += yoffset;
        }
    });

    glfwSetCursorPosCallback(handle_, [](GLFWwindow* w, double x, double y) {
        if (auto* self = static_cast<Window*>(glfwGetWindowUserPointer(w))) {
            if (self->cursor_seeded_) {
                self->mouse_dx_accum_ += x - self->last_cursor_x_;
                self->mouse_dy_accum_ += y - self->last_cursor_y_;
            }
            self->last_cursor_x_ = x;
            self->last_cursor_y_ = y;
            self->cursor_seeded_ = true;
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

double Window::consume_scroll_y() noexcept {
    double v = scroll_y_accum_;
    scroll_y_accum_ = 0.0;
    return v;
}

void Window::add_scroll_y(double dy) noexcept {
    scroll_y_accum_ += dy;
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
    // Drop the seed so the next cursor-pos event re-anchors and we don't
    // see a giant warp delta on lock-state change.
    cursor_seeded_ = false;
}

}  // namespace renderer
