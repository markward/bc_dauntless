// native/tests/ui_cef/cef_composite_pass_gpu_test.cc
//
// The CEF overlay's sub-image upload on a real GL context: upload a whole
// bitmap, then only some rects of a second one, read the texture back and
// compare every byte against the expected overlay. Pins what the CPU model in
// cef_dirty_rects_test.cc cannot: GL_UNPACK_ROW_LENGTH, the per-rect source
// offset and texel origin, and the row-length reset other passes rely on.
// Skips without a GL context (assets_test::GLContext).
#include "cef_composite_pass.h"
#include "cef_dirty_rects.h"

#include "gl_fixture.h"

#include <glad/glad.h>
#include <gtest/gtest.h>

#include <cstdint>
#include <vector>

using dauntless::ui_cef::CefCompositePass;
using dauntless::ui_cef::PixelRect;
using dauntless::ui_cef::clip_rect;

namespace {

class CefCompositePassGpu : public assets_test::GLContext {
protected:
    void SetUp() override {
        assets_test::GLContext::SetUp();
        if (IsSkipped()) return;
        GLint major = 0, minor = 0;
        glGetIntegerv(GL_MAJOR_VERSION, &major);
        glGetIntegerv(GL_MINOR_VERSION, &minor);
        // The pass's shaders are #version 410 and exit the process if they
        // fail to compile, so a 3.3-only context must skip, not construct it.
        if (major * 10 + minor < 41) {
            GTEST_SKIP() << "needs GL 4.1, have " << major << "." << minor;
        }
    }
};

std::vector<std::uint8_t> pattern(int w, int h, int seed) {
    std::vector<std::uint8_t> v(static_cast<size_t>(w) * h * 4);
    for (size_t i = 0; i < v.size(); ++i) {
        v[i] = static_cast<std::uint8_t>((i * 7 + seed * 31 + 1) & 0xFF);
    }
    return v;
}

std::vector<std::uint8_t> overlay(std::vector<std::uint8_t> base,
                                  const std::vector<std::uint8_t>& src, int w,
                                  PixelRect r) {
    for (int y = r.y; y < r.y + r.h; ++y) {
        for (int x = r.x; x < r.x + r.w; ++x) {
            for (int c = 0; c < 4; ++c) {
                const size_t i = (static_cast<size_t>(y) * w + x) * 4 + c;
                base[i] = src[i];
            }
        }
    }
    return base;
}

std::vector<std::uint8_t> read_back(GLuint tex, int w, int h) {
    std::vector<std::uint8_t> out(static_cast<size_t>(w) * h * 4, 0);
    glBindTexture(GL_TEXTURE_2D, tex);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    glGetTexImage(GL_TEXTURE_2D, 0, GL_BGRA, GL_UNSIGNED_BYTE, out.data());
    return out;
}

}  // namespace

TEST_F(CefCompositePassGpu, UploadRectsWritesOnlyTheRects) {
    // Odd, non-square size so a swapped x/y or a wrong row stride lands on
    // different texels.
    const int w = 13, h = 7;
    const auto a = pattern(w, h, 1);
    const auto b = pattern(w, h, 2);

    CefCompositePass pass;
    pass.upload(a.data(), w, h);
    GLint tex = 0;
    glGetIntegerv(GL_TEXTURE_BINDING_2D, &tex);
    ASSERT_NE(tex, 0);
    ASSERT_EQ(read_back(static_cast<GLuint>(tex), w, h), a);

    const std::vector<PixelRect> rects = {
        {9, 4, 4, 3},     // touches the right AND bottom edges
        {1, 1, 3, 2},     // odd width
        {5, 0, 1, 6},     // one column, from the top row
        {11, 0, 5, 2},    // overhangs the right edge: clipped to 2 wide
    };
    pass.upload_rects(b.data(), w, h, rects);
    ASSERT_EQ(glGetError(), static_cast<GLenum>(GL_NO_ERROR));

    std::vector<std::uint8_t> want = a;
    for (const PixelRect& r : rects) {
        want = overlay(want, b, w, clip_rect(r, w, h));
    }
    EXPECT_EQ(read_back(static_cast<GLuint>(tex), w, h), want);

    GLint row_length = -1;
    glGetIntegerv(GL_UNPACK_ROW_LENGTH, &row_length);
    EXPECT_EQ(row_length, 0);
}

TEST_F(CefCompositePassGpu, UploadRectsIgnoresAMismatchedSize) {
    // A size change must take the whole upload(); upload_rects into a texture
    // of another size changes nothing.
    const int w = 8, h = 4;
    const auto a = pattern(w, h, 1);
    const auto b = pattern(4, 8, 2);

    CefCompositePass pass;
    pass.upload(a.data(), w, h);
    GLint tex = 0;
    glGetIntegerv(GL_TEXTURE_BINDING_2D, &tex);
    pass.upload_rects(b.data(), 4, 8, {{0, 0, 2, 2}});
    EXPECT_EQ(read_back(static_cast<GLuint>(tex), w, h), a);
}
