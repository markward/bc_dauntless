// native/tests/renderer/shader_test.cc
#include <gtest/gtest.h>

#include <renderer/shader.h>
#include <renderer/window.h>

#include <glm/glm.hpp>

namespace {

const char* kTrivialVS = R"(#version 410 core
void main() { gl_Position = vec4(0.0, 0.0, 0.0, 1.0); }
)";

const char* kTrivialFS = R"(#version 410 core
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

}  // namespace
