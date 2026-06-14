// native/tests/renderer/skinned_render_test.cc
//
// Offscreen GL verification for the skinned draw branch added to
// renderer::draw_model (Task 5). Two tests:
//
//   A (plumbing): a skinned model at BIND POSE renders identically whether
//       drawn through the static program (empty palette) or the skinned program
//       (identity-per-bone palette). Proves the skinning plumbing reproduces the
//       undeformed mesh.
//
//   B (palette math): translating every bone palette entry +X shifts the
//       rendered silhouette's non-background centroid toward +screen-X. Proves
//       the palette actually deforms geometry.
//
// Both SKIP (not fail) when the BC asset or a GL context is unavailable.

#include <gtest/gtest.h>

#include <renderer/frame.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>
#include <renderer/shader.h>
#include <renderer/bone_palette.h>

#include <scenegraph/instance.h>
#include <scenegraph/camera.h>
#include <scenegraph/damage_decals.h>

#include <assets/cache.h>
#include <assets/model.h>

#include <glad/glad.h>
#include <glm/gtc/matrix_transform.hpp>

#include <array>
#include <filesystem>
#include <vector>

namespace {

const std::filesystem::path kProjectRoot =
    std::filesystem::path(__FILE__).parent_path().parent_path().parent_path().parent_path();
const std::filesystem::path kBodyNif =
    kProjectRoot / "game" / "data" / "Models" / "Characters" / "Bodies"
                 / "BodyMaleL" / "BodyMaleL.NIF";
// BodyMaleL's textures (head.tga / body.tga) live alongside the NIF.
const std::filesystem::path kBodyTex =
    kProjectRoot / "game" / "data" / "Models" / "Characters" / "Bodies"
                 / "BodyMaleL";

constexpr int kW = 256;
constexpr int kH = 256;

class SkinnedRenderTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;
    std::unique_ptr<renderer::Pipeline> p;
    std::unique_ptr<assets::AssetCache> cache;
    assets::ModelHandle model_h;

    void SetUp() override {
        if (!std::filesystem::is_regular_file(kBodyNif)) {
            GTEST_SKIP() << "BC skinned asset not available at " << kBodyNif;
        }
        try {
            w = std::make_unique<renderer::Window>(kW, kH, "skinned-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        p = std::make_unique<renderer::Pipeline>();
        cache = std::make_unique<assets::AssetCache>();
        model_h = cache->load(kBodyNif, kBodyTex);
        if (!model_h || model_h->skeleton.bones.empty()) {
            GTEST_SKIP() << "loaded model has no skeleton — not a skinned NIF";
        }
    }

    // Frame a camera so the whole model fits and is roughly centred. The model
    // is loaded at origin in its model units; pull the camera back along +Z.
    static scenegraph::Camera frame_camera() {
        scenegraph::Camera cam;
        cam.eye    = glm::vec3(0.0f, 0.0f, 30.0f);
        cam.target = glm::vec3(0.0f, 0.0f, 0.0f);
        cam.aspect = 1.0f;
        return cam;
    }

    // Render the model once with the given palette into the default framebuffer
    // and read back the full RGBA buffer. An empty palette forces draw_model's
    // static branch; a non-empty palette drives the skinned program.
    std::vector<unsigned char> render_with_palette(
            const std::vector<glm::mat4>& palette) {
        scenegraph::Camera cam = frame_camera();

        renderer::Lighting lighting;  // default lit so the model is visible.

        glViewport(0, 0, kW, kH);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        glEnable(GL_DEPTH_TEST);

        renderer::FrameSubmitter submitter;
        // ensure_*_texture is private to FrameSubmitter; drive the fallbacks
        // by going through the public submit path for per-frame uniforms, then
        // call draw_model directly with our controlled palette. Simplest: set
        // per-frame uniforms on both programs ourselves and call draw_model.
        renderer::Shader& opaque  = p->opaque_shader();
        renderer::Shader& skinned = p->skinned_shader();
        auto configure = [&](renderer::Shader& s) {
            s.use();
            s.set_mat4("u_view", cam.view_matrix());
            s.set_mat4("u_proj", cam.proj_matrix());
            const glm::vec3 cam_pos_ws =
                glm::vec3(glm::inverse(cam.view_matrix())[3]);
            s.set_vec3("u_camera_pos_ws", cam_pos_ws);
            s.set_vec3("u_ambient_light", lighting.ambient);
            s.set_int("u_dir_light_count", lighting.directional_count);
            if (lighting.directional_count > 0) {
                s.set_vec3_array("u_dir_light_dir_ws",
                                 lighting.directional_dir_ws,
                                 lighting.directional_count);
                s.set_vec3_array("u_dir_light_color",
                                 lighting.directional_color,
                                 lighting.directional_count);
            }
        };
        configure(opaque);
        configure(skinned);

        // 1×1 white/black fallbacks so the draw doesn't depend on textures.
        GLuint white = make_pixel_texture(255, 255, 255);
        GLuint black = make_pixel_texture(0, 0, 0);

        const std::array<scenegraph::Instance::GlowRegion,
                         scenegraph::Instance::kMaxGlowRegions> no_glow{};
        scenegraph::DamageDecalRing no_decals;

        renderer::draw_model(*model_h, glm::mat4(1.0f), opaque, skinned,
                             white, black, /*rim_active=*/false,
                             no_decals, no_glow, /*decal_time=*/0.0f,
                             /*emissive_scale=*/1.0f, palette);

        glDeleteTextures(1, &white);
        glDeleteTextures(1, &black);

        std::vector<unsigned char> buf(static_cast<size_t>(kW) * kH * 4);
        glReadPixels(0, 0, kW, kH, GL_RGBA, GL_UNSIGNED_BYTE, buf.data());
        return buf;
    }

    static GLuint make_pixel_texture(unsigned char r, unsigned char g,
                                     unsigned char b) {
        GLuint t = 0;
        glGenTextures(1, &t);
        glBindTexture(GL_TEXTURE_2D, t);
        const unsigned char px[4] = {r, g, b, 255};
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 1, 1, 0, GL_RGBA,
                     GL_UNSIGNED_BYTE, px);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
        return t;
    }

    // Mean column index of non-background pixels (background = clear black).
    // Returns -1 when no foreground pixel is found.
    static double centroid_x(const std::vector<unsigned char>& buf) {
        double sum_x = 0.0;
        long count = 0;
        for (int y = 0; y < kH; ++y) {
            for (int x = 0; x < kW; ++x) {
                const size_t i = (static_cast<size_t>(y) * kW + x) * 4;
                const int total = buf[i] + buf[i + 1] + buf[i + 2];
                if (total > 6) {  // a few LSBs above the black clear colour
                    sum_x += x;
                    ++count;
                }
            }
        }
        return count > 0 ? sum_x / static_cast<double>(count) : -1.0;
    }

    static long foreground_count(const std::vector<unsigned char>& buf) {
        long count = 0;
        for (size_t i = 0; i < buf.size(); i += 4) {
            if (buf[i] + buf[i + 1] + buf[i + 2] > 6) ++count;
        }
        return count;
    }
};

// Test A — PLUMBING: skinned model at bind pose renders identically whether
// drawn through the static program (empty palette) or the skinned program
// (identity-per-bone palette).
TEST_F(SkinnedRenderTest, BindPoseMatchesStaticDraw) {
    // Static branch: empty palette → draw_model uses the static shader.
    const std::vector<unsigned char> bufA = render_with_palette({});
    ASSERT_EQ(glGetError(), GL_NO_ERROR);

    // Skinned branch: identity-per-bone palette (local_pose = nullptr).
    const std::vector<glm::mat4> ident =
        renderer::build_bone_palette(model_h->skeleton, /*local_pose=*/nullptr);
    ASSERT_FALSE(ident.empty());
    const std::vector<unsigned char> bufB = render_with_palette(ident);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);

    // The model must actually have rendered something in at least one path.
    ASSERT_GT(foreground_count(bufA), 0)
        << "static-program render of the skinned model was empty";
    ASSERT_GT(foreground_count(bufB), 0)
        << "skinned-program render at bind pose was empty";

    // Per-channel equality within a tiny tolerance (rasteriser / interpolation
    // LSB noise between two different programs computing the same vertex math).
    long differing = 0;
    int max_diff = 0;
    for (size_t i = 0; i < bufA.size(); ++i) {
        const int d = std::abs(static_cast<int>(bufA[i]) -
                               static_cast<int>(bufB[i]));
        if (d > max_diff) max_diff = d;
        if (d > 2) ++differing;
    }
    EXPECT_EQ(differing, 0)
        << "bind-pose skinned render diverged from the static render: "
        << differing << " channels differ by >2 (max diff " << max_diff
        << ") — the skinning plumbing does not reproduce the static mesh.";
}

// Test B — PALETTE MATH: a palette translating every bone +X shifts the
// rendered silhouette's non-background centroid in +screen-X.
TEST_F(SkinnedRenderTest, TranslatedPaletteShiftsSilhouette) {
    const std::vector<glm::mat4> ident =
        renderer::build_bone_palette(model_h->skeleton, /*local_pose=*/nullptr);
    ASSERT_FALSE(ident.empty());

    const std::vector<unsigned char> buf0 = render_with_palette(ident);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const double cx0 = centroid_x(buf0);
    ASSERT_GT(cx0, 0.0) << "identity-palette render produced no silhouette";

    // Shift every bone a large amount along world +X (which maps to screen
    // +X for this camera looking down -Z). Pre-multiplying the identity palette
    // by a world-space translation moves every skinned vertex by the same
    // offset, so the whole silhouette slides right.
    const float shift_x = 6.0f;  // large relative to the model's model-unit size
    std::vector<glm::mat4> shifted = ident;
    const glm::mat4 T = glm::translate(glm::mat4(1.0f),
                                       glm::vec3(shift_x, 0.0f, 0.0f));
    for (auto& m : shifted) m = T * m;

    const std::vector<unsigned char> buf1 = render_with_palette(shifted);
    ASSERT_EQ(glGetError(), GL_NO_ERROR);
    const double cx1 = centroid_x(buf1);
    ASSERT_GT(cx1, 0.0) << "shifted-palette render produced no silhouette";

    EXPECT_GT(cx1, cx0 + 1.0)
        << "translating the bone palette +X did not move the silhouette right "
           "(cx0=" << cx0 << " cx1=" << cx1 << ") — the palette is not "
           "deforming geometry.";
}

}  // namespace
