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

Window::Window(Window&& other) noexcept : handle_(other.handle_) {
    other.handle_ = nullptr;
}

Window& Window::operator=(Window&& other) noexcept {
    if (this != &other) {
        if (handle_) {
            glfwDestroyWindow(handle_);
            release_glfw();
        }
        handle_ = other.handle_;
        other.handle_ = nullptr;
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

}  // namespace renderer
