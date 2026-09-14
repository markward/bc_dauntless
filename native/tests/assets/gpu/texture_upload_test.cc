#include <gtest/gtest.h>
#include <assets/texture.h>
#include <glad/glad.h>

#include <array>

#include "gl_fixture.h"

class TextureUploadTest : public assets_test::GLContext {};

TEST_F(TextureUploadTest, UploadsRgba8WithMipmaps) {
    assets::Image img;
    img.width = 8;
    img.height = 8;
    img.format = assets::Image::Format::RGBA8;
    img.pixels.assign(8 * 8 * 4, 0xCC);

    auto tex = assets::upload_image(img, /*generate_mipmaps=*/true);
    EXPECT_NE(tex.id(), 0u);
    EXPECT_TRUE(glIsTexture(tex.id()));
    EXPECT_EQ(tex.width(), 8u);
    EXPECT_EQ(tex.height(), 8u);
    EXPECT_TRUE(tex.has_mipmaps());

    GLint w = 0;
    glBindTexture(GL_TEXTURE_2D, tex.id());
    glGetTexLevelParameteriv(GL_TEXTURE_2D, 0, GL_TEXTURE_WIDTH, &w);
    EXPECT_EQ(w, 8);
    glBindTexture(GL_TEXTURE_2D, 0);
}

TEST_F(TextureUploadTest, MovedFromTextureIsZero) {
    assets::Image img;
    img.width = 4;
    img.height = 4;
    img.format = assets::Image::Format::RGBA8;
    img.pixels.assign(64, 0);

    auto a = assets::upload_image(img, false);
    auto b = std::move(a);
    EXPECT_EQ(a.id(), 0u);
    EXPECT_NE(b.id(), 0u);
    EXPECT_TRUE(glIsTexture(b.id()));
}

TEST_F(TextureUploadTest, Rgb8Uploads) {
    assets::Image img;
    img.width = 2;
    img.height = 2;
    img.format = assets::Image::Format::RGB8;
    img.pixels.assign(2 * 2 * 3, 0x80);

    auto tex = assets::upload_image(img, false);
    EXPECT_TRUE(glIsTexture(tex.id()));
    EXPECT_FALSE(tex.has_mipmaps());  // dimensions <= 4
}

// The atlas mip clamp is applied per-emitter at BIND time, not at upload time:
// the grid is a property of the emitter, not of the texture file, and
// upload_image's signature is load-bearing (model_build.cc binds its address
// through a TextureUploaderFn typedef). So the clamp has to be settable, and
// resettable, on an already-uploaded texture.
TEST_F(TextureUploadTest, MaxLevelIsSettableAndRestorableAfterUpload) {
    assets::Image img;
    img.width = 256;
    img.height = 256;
    img.format = assets::Image::Format::RGBA8;
    img.pixels.assign(256 * 256 * 4, 0x80);
    auto tex = assets::upload_image(img, /*generate_mipmaps=*/true);
    ASSERT_NE(tex.id(), 0u);

    assets::set_texture_max_level(tex, 3);
    GLint level = 0;
    glBindTexture(GL_TEXTURE_2D, tex.id());
    glGetTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_MAX_LEVEL, &level);
    EXPECT_EQ(level, 3);

    // 1000 is the GL default: a later 1x1 emitter on the same texture must be
    // able to undo an earlier atlas emitter's clamp.
    assets::set_texture_max_level(tex, 1000);
    glGetTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_MAX_LEVEL, &level);
    EXPECT_EQ(level, 1000);
    glBindTexture(GL_TEXTURE_2D, 0);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}

namespace {

// Samples texel (0,0) of `tex` through a real shader and returns the RGBA the
// shader saw. glGetTexImage can NOT stand in for this: texture swizzle is a
// sampling-time operation and glGetTexImage bypasses it, so only a fetch
// through a sampler2D proves what opaque.frag's `texture(...).rgb` receives.
std::array<GLubyte, 4> sample_texel_through_shader(GLuint tex) {
    static const char* kVert =
        "#version 330 core\n"
        "void main() {\n"
        "  vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);\n"
        "  gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);\n"
        "}\n";
    static const char* kFrag =
        "#version 330 core\n"
        "uniform sampler2D u_tex;\n"
        "out vec4 o;\n"
        "void main() { o = texelFetch(u_tex, ivec2(0, 0), 0); }\n";

    auto compile = [](GLenum type, const char* src) {
        GLuint s = glCreateShader(type);
        glShaderSource(s, 1, &src, nullptr);
        glCompileShader(s);
        GLint ok = 0;
        glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
        EXPECT_TRUE(ok) << "shader compile failed";
        return s;
    };
    GLuint vs = compile(GL_VERTEX_SHADER, kVert);
    GLuint fs = compile(GL_FRAGMENT_SHADER, kFrag);
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs);
    glAttachShader(prog, fs);
    glLinkProgram(prog);
    GLint linked = 0;
    glGetProgramiv(prog, GL_LINK_STATUS, &linked);
    EXPECT_TRUE(linked) << "program link failed";

    GLuint fbo = 0, target = 0, vao = 0;
    glGenTextures(1, &target);
    glBindTexture(GL_TEXTURE_2D, target);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
    glGenFramebuffers(1, &fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, target, 0);
    EXPECT_EQ(glCheckFramebufferStatus(GL_FRAMEBUFFER),
              static_cast<GLenum>(GL_FRAMEBUFFER_COMPLETE));

    glViewport(0, 0, 1, 1);
    glDisable(GL_DEPTH_TEST);
    glUseProgram(prog);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, tex);
    glUniform1i(glGetUniformLocation(prog, "u_tex"), 0);
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
    glDrawArrays(GL_TRIANGLES, 0, 3);

    std::array<GLubyte, 4> px{};
    glReadPixels(0, 0, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px.data());

    glBindVertexArray(0);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glBindTexture(GL_TEXTURE_2D, 0);
    glUseProgram(0);
    glDeleteVertexArrays(1, &vao);
    glDeleteFramebuffers(1, &fbo);
    glDeleteTextures(1, &target);
    glDeleteProgram(prog);
    glDeleteShader(vs);
    glDeleteShader(fs);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
    return px;
}

}  // namespace

// An 8-bit grayscale TGA (image type 3 -- how the CGSovereign mod authors
// every one of its _specular masks) decodes to one channel and uploads as
// GL_R8. A bare GL_R8 texture samples as (v, 0, 0, 1), so opaque.frag's
// `spec_acc * texture(u_specular_map).rgb` kept only the red component of the
// sun-coloured highlight: every modded ship wore red specular in every system.
// A single-channel image is a MASK; the shader must see it as neutral grey.
TEST_F(TextureUploadTest, R8SamplesAsNeutralGrey) {
    assets::Image img;
    img.width = 1;
    img.height = 1;
    img.format = assets::Image::Format::R8;
    img.pixels.assign(1, 0xC0);

    auto tex = assets::upload_image(img, false);
    ASSERT_NE(tex.id(), 0u);

    const auto px = sample_texel_through_shader(tex.id());
    EXPECT_EQ(px[0], 0xC0);
    EXPECT_EQ(px[1], 0xC0) << "green must replicate the single channel";
    EXPECT_EQ(px[2], 0xC0) << "blue must replicate the single channel";
    EXPECT_EQ(px[3], 0xFF);
}

// The swizzle is for one-channel images only: an RGB8 upload must still
// sample its authored, distinct channels.
TEST_F(TextureUploadTest, Rgb8SamplesAuthoredChannels) {
    assets::Image img;
    img.width = 1;
    img.height = 1;
    img.format = assets::Image::Format::RGB8;
    img.pixels = {0x10, 0x80, 0xF0};

    auto tex = assets::upload_image(img, false);
    ASSERT_NE(tex.id(), 0u);

    const auto px = sample_texel_through_shader(tex.id());
    EXPECT_EQ(px[0], 0x10);
    EXPECT_EQ(px[1], 0x80);
    EXPECT_EQ(px[2], 0xF0);
    EXPECT_EQ(px[3], 0xFF);
}

TEST_F(TextureUploadTest, MaxLevelOnEmptyTextureIsANoOp) {
    assets::Texture empty;
    ASSERT_EQ(empty.id(), 0u);
    assets::set_texture_max_level(empty, 3);
    EXPECT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));
}
