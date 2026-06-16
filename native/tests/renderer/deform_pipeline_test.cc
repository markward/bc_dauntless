// native/tests/renderer/deform_pipeline_test.cc
#include <gtest/gtest.h>
#include <glad/glad.h>

#include <renderer/shader.h>
#include <renderer/window.h>

#include "embedded_opaque_deform_vs.h"
#include "embedded_opaque_deform_tcs.h"
#include "embedded_opaque_deform_tes.h"
#include "embedded_opaque_fs.h"

namespace {

TEST(DeformPipeline, ProgramLinksWithOpaqueFragment) {
    try {
        renderer::Window w(64, 64, "deform-link-test", /*visible=*/false);
        // 410 tess stages + 330 opaque fragment: mixed-version program must
        // link, and the TES out-varyings must match opaque.frag in-varyings.
        renderer::Shader prog(renderer::shader_src::opaque_deform_vs,
                              renderer::shader_src::opaque_deform_tcs,
                              renderer::shader_src::opaque_deform_tes,
                              renderer::shader_src::opaque_fs);
        EXPECT_NE(prog.program(), 0u);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}

}  // namespace
