// native/tests/renderer/gl_caps_test.cc
#include <gtest/gtest.h>

#include <renderer/gl_caps.h>
#include <renderer/window.h>

namespace {

TEST(GlCaps, ReportsTessellationAvailableUnderTestContext) {
    try {
        renderer::Window w(64, 64, "gl-caps-test", /*visible=*/false);
        const renderer::GlCaps caps = renderer::query_gl_caps();
        // The context was requested at 4.1; llvmpipe gives 4.5. Either way
        // tessellation (GL 4.0+) must be reported available.
        EXPECT_GE(caps.version_major, 4);
        EXPECT_TRUE(caps.tessellation_available);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}

}  // namespace
