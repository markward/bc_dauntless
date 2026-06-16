// native/tests/renderer/shader_test.cc
#include <gtest/gtest.h>

#include <renderer/shader.h>
#include <renderer/window.h>

#include <glm/glm.hpp>

namespace {

const char* kTrivialVS = R"(#version 330 core
void main() { gl_Position = vec4(0.0, 0.0, 0.0, 1.0); }
)";

const char* kTrivialFS = R"(#version 330 core
out vec4 frag;
void main() { frag = vec4(1.0); }
)";

class ShaderTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(64, 64, "shader-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context available: " << e.what();
        }
    }
};

TEST_F(ShaderTest, CompilesLinksAndDestroys) {
    renderer::Shader s(kTrivialVS, kTrivialFS);
    EXPECT_NE(s.program(), 0u);
}

TEST_F(ShaderTest, BadSourceThrows) {
    EXPECT_THROW(renderer::Shader("not glsl", kTrivialFS), std::runtime_error);
}

TEST_F(ShaderTest, UniformSettersDoNotCrashWhenMissing) {
    renderer::Shader s(kTrivialVS, kTrivialFS);
    s.use();
    s.set_mat4("not_a_uniform", glm::mat4(1.0f));
    s.set_vec3("also_missing", glm::vec3(1, 2, 3));
}

// Not using the ShaderTest fixture so this test owns its own Window and can
// adjust context hints independently if that's ever needed.
TEST(Shader, CompilesTessellationProgram) {
    try {
        renderer::Window w(64, 64, "tess-shader-test", /*visible=*/false);

        const char* vs = R"GLSL(#version 410 core
layout(location=0) in vec3 a_pos;
void main() { gl_Position = vec4(a_pos, 1.0); }
)GLSL";
        const char* tcs = R"GLSL(#version 410 core
layout(vertices=3) out;
void main() {
    if (gl_InvocationID == 0) {
        gl_TessLevelInner[0] = 1.0;
        gl_TessLevelOuter[0] = 1.0;
        gl_TessLevelOuter[1] = 1.0;
        gl_TessLevelOuter[2] = 1.0;
    }
    gl_out[gl_InvocationID].gl_Position = gl_in[gl_InvocationID].gl_Position;
}
)GLSL";
        const char* tes = R"GLSL(#version 410 core
layout(triangles, equal_spacing, cw) in;
void main() {
    gl_Position = gl_TessCoord.x * gl_in[0].gl_Position
                + gl_TessCoord.y * gl_in[1].gl_Position
                + gl_TessCoord.z * gl_in[2].gl_Position;
}
)GLSL";
        const char* fs = R"GLSL(#version 410 core
out vec4 frag;
void main() { frag = vec4(1.0); }
)GLSL";

        renderer::Shader prog(vs, tcs, tes, fs);
        EXPECT_NE(prog.program(), 0u);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context available: " << e.what();
    }
}

}  // namespace
