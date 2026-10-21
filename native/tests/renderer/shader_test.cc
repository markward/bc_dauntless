// native/tests/renderer/shader_test.cc
#include <gtest/gtest.h>

#include <glad/glad.h>

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

// Every set_* serves its location from the per-program cache: a name is
// looked up once for the life of the program, then reused.
TEST_F(ShaderTest, SetUniformLooksUpOncePerName) {
    const char* fs = R"(#version 410 core
uniform float u_probe;
out vec4 frag;
void main() { frag = vec4(u_probe); }
)";
    renderer::Shader s(kTrivialVS, fs);
    s.use();
    const std::size_t before = s.cached_location_count();
    s.set_float("u_probe", 0.25f);
    s.set_float("u_probe", 0.5f);
    EXPECT_EQ(s.cached_location_count(), before + 1);
    // The value still lands: the cached location is the real one.
    GLfloat v = 0.0f;
    glGetUniformfv(s.program(), glGetUniformLocation(s.program(), "u_probe"), &v);
    EXPECT_EQ(v, 0.5f);
    // A missing name is cached too (as -1) and stays silent.
    s.set_float("u_not_there", 1.0f);
    s.set_float("u_not_there", 2.0f);
    EXPECT_EQ(s.cached_location_count(), before + 2);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

}  // namespace
