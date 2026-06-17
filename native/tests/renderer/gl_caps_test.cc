// native/tests/renderer/gl_caps_test.cc
#include <gtest/gtest.h>
#include <renderer/gl_caps.h>
#include <renderer/window.h>

TEST(GlCaps, ReportsTessellationUnderTestContext) {
    try {
        renderer::Window w(64, 64, "gl-caps-test", /*visible=*/false);
        const renderer::GlCaps caps = renderer::query_gl_caps();
        EXPECT_GE(caps.version_major, 4);              // requested 4.1
        EXPECT_TRUE(caps.tessellation_available);      // GL 4.0+
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}
