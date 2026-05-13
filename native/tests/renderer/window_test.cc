// native/tests/renderer/window_test.cc
#include <gtest/gtest.h>

#include <renderer/window.h>

#include <GLFW/glfw3.h>

namespace {

TEST(Window, ConstructHiddenAndDestroy) {
    try {
        renderer::Window w(640, 480, "test", /*visible=*/false);
        int fw = 0, fh = 0;
        w.framebuffer_size(&fw, &fh);
        EXPECT_GT(fw, 0);
        EXPECT_GT(fh, 0);
        EXPECT_FALSE(w.should_close());
        w.poll_events();
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}

TEST(Window, FramebufferSizeReflectsResize) {
    try {
        renderer::Window w(640, 480, "resize-test", /*visible=*/false);
        int fw0 = 0, fh0 = 0;
        w.framebuffer_size(&fw0, &fh0);
        ASSERT_GT(fw0, 0);
        ASSERT_GT(fh0, 0);

        // Resize via GLFW directly (Window doesn't expose a resize method;
        // tests reach through the native handle).
        glfwSetWindowSize(w.native_handle(), 320, 240);
        // Pump events so the resize takes effect.
        for (int i = 0; i < 4; ++i) w.poll_events();

        int fw1 = 0, fh1 = 0;
        w.framebuffer_size(&fw1, &fh1);
        EXPECT_GT(fw1, 0);
        EXPECT_GT(fh1, 0);
        // We can't insist on exact 320x240 — HiDPI scaling may produce a
        // different framebuffer size — but it must have shrunk relative
        // to the original 640x480.
        EXPECT_LT(fw1, fw0);
        EXPECT_LT(fh1, fh0);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}

TEST(Window, KeyStateReturnsFalseForUnpressedKeys) {
    try {
        renderer::Window w(64, 64, "key-state-test", /*visible=*/false);
        // Hidden offscreen windows never gain focus, so glfwGetKey reports
        // RELEASE for everything. The test verifies the wiring compiles +
        // links and returns the documented sentinel; real hardware events
        // can't be simulated in a test without a window manager.
        EXPECT_FALSE(w.key_state(GLFW_KEY_W));
        EXPECT_FALSE(w.key_state(GLFW_KEY_SPACE));
        EXPECT_FALSE(w.key_state(GLFW_KEY_0));
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}

TEST(Window, MoveAssignDoesNotLeak) {
    try {
        renderer::Window a(320, 240, "a", /*visible=*/false);
        renderer::Window b(320, 240, "b", /*visible=*/false);
        a = std::move(b);  // a's old handle destroyed; a now owns b's
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}

TEST(Window, AddScrollYAccumulatesIntoConsumeScrollY) {
    try {
        renderer::Window w(640, 480, "add-scroll-test", /*visible=*/false);

        // No scroll yet — accumulator starts at 0.
        EXPECT_DOUBLE_EQ(w.consume_scroll_y(), 0.0);

        w.add_scroll_y(1.5);
        w.add_scroll_y(-0.5);
        // Cumulative read drains.
        EXPECT_DOUBLE_EQ(w.consume_scroll_y(), 1.0);
        // Second read is zero (consume drained the accumulator).
        EXPECT_DOUBLE_EQ(w.consume_scroll_y(), 0.0);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}

}  // namespace
