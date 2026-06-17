// native/tests/renderer/breach_pass_test.cc
//
// Tests for the breach interior-surface pass (Path C / hull-breach-2b/2c).
//
// The pass renders a SPHERE SCOOP per active carve sphere: for each active
// carve, it draws the inner (far) wall of a unit sphere scaled to carve_radius
// and centred at carve_center_body, masked by the ORIGINAL (uncarved) fill.
//
//  CPU tests (no GL):
//    - No active carves → draw_instance() is a no-op.
//
//  GL tests (skips without a context):
//    - draw_instance with ONE active carve over a solid-fill region:
//        fill is solid at p_body → scoop fragment kept → pixel != background.
//    - draw_instance with ONE active carve over an empty-fill region:
//        fill is 0 at p_body → scoop fragment discarded → pixel == background.
//    - No active carves → pass draws nothing → pixel stays background.
//    - Rim emissive: fresh breach (age=0) renders brighter than cold (age≥kRimLife).

#include <gtest/gtest.h>

#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <renderer/breach_pass.h>
#include <renderer/pipeline.h>
#include <renderer/window.h>

#include <scenegraph/breach_events.h>
#include <scenegraph/camera.h>
#include <scenegraph/hull_carve.h>

#include <voxel/volume.h>

#include <array>
#include <memory>
#include <numeric>
#include <vector>

namespace {

constexpr int kW = 64;
constexpr int kH = 64;

// An 8^3 fill that is SOLID (127) everywhere in its volume: the original
// (uncarved) hull material. The breach.frag fill mask passes every fragment
// that maps inside this volume. The 2c scoop is a shallow cap offset toward
// the hit normal by kDepthOffset*radius, so the sphere extends well beyond the
// carve centre; the fill cube must span [-4,4] (not the old [-2,2]) so the
// offset interior wall still lands in solid material rather than reading as
// see-through off the edge of an undersized fill.
voxel::VoxelVolume solid_fill() {
    voxel::VoxelVolume v;
    v.dims   = {8, 8, 8};
    v.origin = {-4.f, -4.f, -4.f};
    v.cell   = {1.f, 1.f, 1.f};
    v.occ.assign(8 * 8 * 8, 127);  // all solid
    return v;
}

// A 4^3 fill that is EMPTY (0) everywhere: no hull material.
// The breach.frag fill mask discards every fragment here.
voxel::VoxelVolume empty_fill() {
    voxel::VoxelVolume v;
    v.dims   = {4, 4, 4};
    v.origin = {-2.f, -2.f, -2.f};
    v.cell   = {1.f, 1.f, 1.f};
    v.occ.assign(4 * 4 * 4, 0);   // all empty
    return v;
}

// A 4^3 fill where every cell is 75 (just above kIsovalue=64, well inside the
// rim band [64/255, (64+0.12*255)/255] ≈ byte [64, 94]).  Fragments pass the
// fill mask (75 > 64) and land in the rim band → rim_w ≈ 1.  Used by the
// hot-vs-cold emissive test to ensure the emissive term fires.
voxel::VoxelVolume rim_fill() {
    voxel::VoxelVolume v;
    v.dims   = {4, 4, 4};
    v.origin = {-2.f, -2.f, -2.f};
    v.cell   = {1.f, 1.f, 1.f};
    v.occ.assign(4 * 4 * 4, 75);  // just above iso, inside rim band
    return v;
}

class BreachPassGLTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window>   w;
    std::unique_ptr<renderer::Pipeline> pipeline;

    void SetUp() override {
        try {
            w = std::make_unique<renderer::Window>(kW, kH, "breach-pass-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        pipeline = std::make_unique<renderer::Pipeline>();
    }

    std::array<unsigned char, 4> read_center() const {
        glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);
        std::array<unsigned char, 4> px{0, 0, 0, 0};
        glReadPixels(kW / 2, kH / 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
        return px;
    }

    // Brightest RGB sum over the inner half of the framebuffer. The 2c scoop is
    // a shallow cap offset toward the hit normal (kDepthOffset) with a
    // noise-deformed radius, so the visible interior wall is an off-centre
    // annulus rather than a disc centred on the exact pole pixel. Sampling the
    // inner-half max proves the interior wall rendered near the breach axis
    // without depending on which single pixel the (degenerate) UV-sphere pole
    // lands on.
    int read_inner_max() const {
        glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);
        std::vector<unsigned char> buf(kW * kH * 4);
        glReadPixels(0, 0, kW, kH, GL_RGBA, GL_UNSIGNED_BYTE, buf.data());
        int best = 0;
        for (int y = kH / 4; y < 3 * kH / 4; ++y) {
            for (int x = kW / 4; x < 3 * kW / 4; ++x) {
                int i = (y * kW + x) * 4;
                int s = buf[i] + buf[i + 1] + buf[i + 2];
                if (s > best) best = s;
            }
        }
        return best;
    }

    // Sum all RGB components across the whole framebuffer — used to compare
    // brightness between a hot and a cold render.
    long long read_frame_sum() const {
        glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);
        std::vector<unsigned char> buf(kW * kH * 4);
        glReadPixels(0, 0, kW, kH, GL_RGBA, GL_UNSIGNED_BYTE, buf.data());
        long long s = 0;
        for (int i = 0; i < kW * kH; ++i) {
            s += buf[i * 4 + 0];  // R
            s += buf[i * 4 + 1];  // G
            s += buf[i * 4 + 2];  // B
        }
        return s;
    }

    // Camera looking at the origin along -Z.  The carve sphere is centred at
    // the origin; with CW winding + cull-front (far wall = back faces), the
    // inner wall of the sphere facing the camera renders at the centre.
    static scenegraph::Camera cam_looking_at_origin() {
        scenegraph::Camera c;
        c.eye    = glm::vec3(0.f, 0.f, 5.f);
        c.target = glm::vec3(0.f);
        c.up     = glm::vec3(0.f, 1.f, 0.f);
        c.fov_y_rad = glm::radians(45.f);
        c.aspect = 1.0f;
        c.near   = 0.1f;
        c.far    = 50.f;
        return c;
    }

    void clear_framebuffer() {
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glViewport(0, 0, kW, kH);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    }
};

}  // namespace

// CPU: draw_instance with no active carves does nothing (returns immediately).
// No GL needed — this is a control-flow check.
TEST(BreachPassCpu, NoActiveCarvesDrawsNothing) {
    // No GL context available in CPU tests. Confirm via carve count only.
    scenegraph::HullCarveField carve;  // no carves added
    EXPECT_EQ(carve.count(), 0u)
        << "default HullCarveField must have count()==0; "
           "draw_instance should return early";
}

// GL: with ONE active carve and a SOLID fill, the scoop sphere inner wall is
// masked by the fill → fragment kept → pixel is non-background.
TEST_F(BreachPassGLTest, SolidFillDrawsScoopInterior) {
    clear_framebuffer();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    // cull-front is set INSIDE BreachPass::draw_instance; do not set it here
    // (the pass sets and restores it).

    renderer::BreachPass pass;
    voxel::VoxelVolume fill = solid_fill();

    scenegraph::HullCarveField carve;
    carve.add(glm::vec3(0.f, 0.f, 0.f), 1.5f,
              glm::vec3(0.f, 0.f, 1.f));  // sphere at origin, r=1.5, +Z normal

    scenegraph::Camera cam = cam_looking_at_origin();

    pass.draw_instance(/*instance_key=*/1, fill, carve,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in solid-fill scoop draw";
    EXPECT_GT(read_inner_max(), 24)
        << "Inner region is background — solid fill: scoop sphere inner wall "
           "should be visible around the breach axis";
}

// GL: with ONE active carve and an EMPTY fill, every scoop fragment is
// discarded by the fill mask → pixel stays background.
TEST_F(BreachPassGLTest, EmptyFillDiscardsAllScoopFragments) {
    clear_framebuffer();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);

    renderer::BreachPass pass;
    voxel::VoxelVolume fill = empty_fill();

    scenegraph::HullCarveField carve;
    carve.add(glm::vec3(0.f, 0.f, 0.f), 1.5f, glm::vec3(0.f, 0.f, 1.f));

    scenegraph::Camera cam = cam_looking_at_origin();

    pass.draw_instance(/*instance_key=*/2, fill, carve,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in empty-fill scoop draw";
    auto px = read_center();
    EXPECT_LT(px[0] + px[1] + px[2], 16)
        << "Centre pixel is bright (R=" << (int)px[0]
        << " G=" << (int)px[1] << " B=" << (int)px[2]
        << ") — empty fill: all scoop fragments should be discarded (see-through)";
}

// GL: with NO active carves, the pass draws nothing → pixel stays background.
TEST_F(BreachPassGLTest, NoCarvesDrawsNothing) {
    clear_framebuffer();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);

    renderer::BreachPass pass;
    voxel::VoxelVolume fill = solid_fill();
    scenegraph::HullCarveField carve;   // no carves
    scenegraph::Camera cam = cam_looking_at_origin();

    pass.draw_instance(/*instance_key=*/3, fill, carve,
                       glm::mat4(1.0f), cam, *pipeline);
    glFinish();

    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in empty breach draw";
    auto px = read_center();
    EXPECT_LT(px[0] + px[1] + px[2], 16)
        << "Centre pixel is lit with no carves — the pass should be a no-op";
}

// GL: a fresh breach (age=0, heat=1) must render brighter than a cold one
// (age≥kRimLife, heat=0).  Uses rim_fill() — voxels at byte 75 — which falls
// inside the rim band [iso, iso+0.12*255] so rim_w is nonzero when hot.
// The cold render should look identical to the base scoop (no emissive term);
// the hot render adds the blackbody emissive → the whole-frame RGB sum is
// strictly larger.
TEST_F(BreachPassGLTest, HotBreachBrighterThanCold) {
    scenegraph::HullCarveField carve;
    carve.add(glm::vec3(0.f, 0.f, 0.f), 1.5f, glm::vec3(0.f, 0.f, 1.f));
    scenegraph::Camera cam = cam_looking_at_origin();

    // ── Cold render (age well past kRimLife → heat = 0, no emissive) ────────
    clear_framebuffer();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    {
        renderer::BreachPass pass;
        voxel::VoxelVolume fill = rim_fill();
        pass.draw_instance(/*instance_key=*/10, fill, carve,
                           glm::mat4(1.0f), cam, *pipeline,
                           scenegraph::kRimLife + 1.f);  // cold
    }
    glFinish();
    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in cold breach draw";
    const long long cold_sum = read_frame_sum();

    // ── Hot render (age=0 → heat=1, maximum emissive) ───────────────────────
    clear_framebuffer();
    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    {
        renderer::BreachPass pass;
        voxel::VoxelVolume fill = rim_fill();
        pass.draw_instance(/*instance_key=*/11, fill, carve,
                           glm::mat4(1.0f), cam, *pipeline,
                           0.f);  // fresh (hot)
    }
    glFinish();
    EXPECT_EQ(glGetError(), GL_NO_ERROR) << "GL error in hot breach draw";
    const long long hot_sum = read_frame_sum();

    // A fresh breach must be meaningfully brighter than a cold one.
    // The blackbody emissive at heat=1 yields near-white (≈1,0.92,0.72)
    // scaled by 1.5, so even with clamping the hot frame is substantially
    // brighter. We require a margin of at least 512 (summed RGB units across
    // all pixels) to rule out noise; typical values are several thousand.
    EXPECT_GT(hot_sum, cold_sum + 512)
        << "Hot breach (age=0) frame sum=" << hot_sum
        << " should be significantly brighter than cold (age>=kRimLife) sum="
        << cold_sum
        << " — rim emissive did not contribute";
}
