// native/tests/renderer/skinned_program_test.cc
#include <gtest/gtest.h>

#include <renderer/pipeline.h>
#include <renderer/window.h>

#include <memory>
#include <stdexcept>

// Constructing the Pipeline compiles + links every shader program, including
// the skinned program (skinned.vert + opaque.frag). The Shader ctor throws a
// std::runtime_error on any compile or link failure, so a successful Pipeline
// construction proves skinned.vert compiles and links against opaque.frag.
TEST(SkinnedProgram, LinksSuccessfully) {
    std::unique_ptr<renderer::Window> w;
    try {
        // Hidden/offscreen window: same signature frame_test.cc uses
        // (width, height, title, visible=false).
        w = std::make_unique<renderer::Window>(64, 64, "skinned-program-test", false);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context: " << e.what();
    }

    renderer::Pipeline p;  // throws on shader compile/link failure
    SUCCEED();
}
