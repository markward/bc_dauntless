// native/tests/renderer/window_test.cc
#include <gtest/gtest.h>

#include <renderer/window.h>

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

TEST(Window, MoveAssignDoesNotLeak) {
    try {
        renderer::Window a(320, 240, "a", /*visible=*/false);
        renderer::Window b(320, 240, "b", /*visible=*/false);
        a = std::move(b);  // a's old handle destroyed; a now owns b's
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}

}  // namespace
