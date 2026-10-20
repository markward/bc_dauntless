// native/tests/renderer/hull_interior_test.cc
//
// SPIKE (damage redesign), plan 2026-10-20-layered-damage-hull-interior,
// Task 3: the interior draw. Behind every plating cut,
// FrameSubmitter::submit_plating_interior draws decks and rooms (the
// interior-mapping walk ported from spike/breach-interior-mapping) under the
// cut's own stencil value, so a hole shows the inside of the ship instead of
// whatever is behind it. Rendered through the real FrameSubmitter on a
// synthetic closed box hull with a synthetic fill, so no BC assets are needed.
#include <gtest/gtest.h>

#include <renderer/carve_field_cache.h>
#include <renderer/frame.h>
#include <renderer/pipeline.h>
#include <renderer/plating_damage.h>

#include <scenegraph/camera.h>
#include <scenegraph/damage_decals.h>
#include <scenegraph/world.h>

#include <assets/model.h>

#include <voxel/volume.h>

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <memory>
#include <vector>

#include "plating_gl_fixture.h"

using namespace plating_gl;

namespace {

constexpr float kBoxHalf = 20.0f;
// Never on disk: the fill reaches the cache through put_for_source only.
constexpr const char* kBoxSource = "hull_interior_test/box.nif";

// Solid over the whole box (BC occupancy runs 0..127).
voxel::VoxelVolume solid_box_fill() {
    voxel::VoxelVolume v;
    v.dims = glm::ivec3(20);
    v.cell = glm::vec3(2.0f * kBoxHalf / 20.0f);
    v.origin = glm::vec3(-kBoxHalf);
    v.occ.assign(static_cast<std::size_t>(20 * 20 * 20), 127);
    return v;
}

bool is_clear(const std::uint8_t* q) { return q[0] + q[1] + q[2] <= 6; }

class HullInteriorTest : public PlatingGLFixture {
protected:
    std::unique_ptr<assets::Model> box;
    std::unique_ptr<renderer::CarveFieldCache> filled;   // holds the box's fill
    std::unique_ptr<renderer::CarveFieldCache> empty;    // has no fill for it

    void SetUp() override {
        PlatingGLFixture::SetUp();
        if (!w) return;
        dauntless_plating::g_params[0] = 1.0f;
        box = build_box(kBoxHalf);
        box->source = kBoxSource;
        filled = std::make_unique<renderer::CarveFieldCache>();
        ASSERT_NE(filled->put_for_source(kBoxSource, solid_box_fill()), nullptr);
        empty = std::make_unique<renderer::CarveFieldCache>();
    }

    void TearDown() override {
        filled.reset();
        empty.reset();
        box.reset();
        PlatingGLFixture::TearDown();
    }

    struct Placed {
        glm::mat4 world;
        scenegraph::DamageDecalRing ring;
    };
    struct Shot {
        std::vector<std::uint8_t> px;
        int marks = -1;
        int interiors = -1;
    };

    // Every `placed` box drawn through submit_opaque_in_pass then
    // submit_plating_interior (or submit_opaque alone when `stock`), the
    // interior's fill coming from `fills`.
    Shot render(const std::vector<Placed>& placed, renderer::CarveFieldCache* fills,
                bool stock = false) {
        scenegraph::World world;
        for (const Placed& pl : placed) {
            auto iid = world.create_instance(
                reinterpret_cast<scenegraph::ModelHandle>(box.get()));
            world.set_world_transform(iid, pl.world);
            world.get(iid)->decals = pl.ring;
        }
        glViewport(0, 0, kSize, kSize);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glStencilMask(0xFF);
        glClearStencil(0);
        glEnable(GL_CULL_FACE);
        glCullFace(GL_BACK);
        glDepthFunc(GL_LESS);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
        renderer::reset_model_radius_cache();
        renderer::FrameSubmitter submitter;
        const auto lookup = [](scenegraph::ModelHandle h) -> const assets::Model* {
            return reinterpret_cast<const assets::Model*>(h);
        };
        const auto cam = quad_cam();
        Shot out;
        if (stock) {
            submitter.submit_opaque(world, cam, *p, lookup, test_lighting(), kDecalTime);
        } else {
            submitter.submit_opaque_in_pass(world, cam, *p, lookup, test_lighting(),
                                            scenegraph::Pass::Space, kDecalTime);
            submitter.submit_plating_interior(world, cam, *p, lookup, fills,
                                              test_lighting(), 1.0f, kDecalTime);
            out.marks = submitter.plating_marks_last_frame();
            out.interiors = submitter.plating_interiors_last_frame();
        }
        out.px.assign(static_cast<std::size_t>(kSize) * kSize * 4, 0);
        glReadPixels(0, 0, kSize, kSize, GL_RGBA, GL_UNSIGNED_BYTE, out.px.data());
        return out;
    }

    Shot render_one(const scenegraph::DamageDecalRing& ring, renderer::CarveFieldCache* fills,
                    bool stock = false) {
        return render({Placed{glm::mat4(1.0f), ring}}, fills, stock);
    }

    // The near face's centre, where the camera axis meets the box.
    glm::ivec2 centre() const { return to_pixel(quad_cam(), glm::vec3(0.0f, 0.0f, kBoxHalf)); }

    static void report(const char* what, const Shot& s, glm::ivec2 c) {
        const std::uint8_t* q = pixel(s.px, c.x, c.y);
        std::fprintf(stderr, "[HullInterior] %s centre=(%d,%d,%d) marks=%d interiors=%d\n",
                     what, q[0], q[1], q[2], s.marks, s.interiors);
    }
};

}  // namespace

TEST_F(HullInteriorTest, HoleShowsInteriorNotClearColour) {
    const auto ring = internal_ring({0.0f, 0.0f, kBoxHalf}, 30.0f, 10.0f);
    const auto on = render_one(ring, filled.get());
    report("interior on", on, centre());
    EXPECT_EQ(on.marks, 1);
    EXPECT_EQ(on.interiors, 1);
    EXPECT_FALSE(is_clear(pixel(on.px, centre().x, centre().y)))
        << "the hole shows what is behind the ship, not its interior";

    dauntless_plating::g_params[25] = 0.0f;
    const auto off = render_one(ring, filled.get());
    report("interior off", off, centre());
    EXPECT_EQ(off.marks, 1) << "the marking still runs with the interior off";
    EXPECT_EQ(off.interiors, 0);
    EXPECT_TRUE(is_clear(pixel(off.px, centre().x, centre().y)))
        << "with the interior off the hole must stay see-through";
}

TEST_F(HullInteriorTest, BlownThroughOnlyPastDeckBreak) {
    const auto ring = internal_ring(glm::vec3(0.0f), 60.0f, 10.0f);
    dauntless_plating::g_params[24] = 1000.0f;
    const auto hold = render_one(ring, filled.get());
    report("deck break 1000", hold, centre());
    EXPECT_EQ(hold.interiors, 1);
    EXPECT_FALSE(is_clear(pixel(hold.px, centre().x, centre().y))) << "the plates should hold";

    dauntless_plating::g_params[24] = 0.01f;
    const auto blown = render_one(ring, filled.get());
    report("deck break 0.01", blown, centre());
    EXPECT_EQ(blown.interiors, 1);
    EXPECT_TRUE(is_clear(pixel(blown.px, centre().x, centre().y)))
        << "decks and far wall should be blown through";
}

TEST_F(HullInteriorTest, NoFillStillDrawsRooms) {
    const auto ring = internal_ring({0.0f, 0.0f, kBoxHalf}, 30.0f, 10.0f);
    const auto s = render_one(ring, empty.get());
    report("no fill", s, centre());
    EXPECT_EQ(s.interiors, 1);
    EXPECT_FALSE(is_clear(pixel(s.px, centre().x, centre().y)))
        << "a hull with no fill volume shows a see-through hole";
}

// A fill that holds no material: the first crossing has already left the
// ship. Below deck break that shows the far wall; past it, the hole is clear.
TEST_F(HullInteriorTest, LeftTheShipShowsFarWallUnlessBlownThrough) {
    voxel::VoxelVolume hollow = solid_box_fill();
    std::fill(hollow.occ.begin(), hollow.occ.end(), std::uint8_t{0});
    renderer::CarveFieldCache hollow_cache;
    ASSERT_NE(hollow_cache.put_for_source(kBoxSource, hollow), nullptr);
    const auto ring = internal_ring({0.0f, 0.0f, kBoxHalf}, 30.0f, 10.0f);

    dauntless_plating::g_params[24] = 1000.0f;
    const auto wall = render_one(ring, &hollow_cache);
    report("far wall", wall, centre());
    EXPECT_EQ(wall.interiors, 1);
    EXPECT_FALSE(is_clear(pixel(wall.px, centre().x, centre().y))) << "no far wall";

    dauntless_plating::g_params[24] = 6.0f;
    const auto through = render_one(ring, &hollow_cache);
    report("blown through", through, centre());
    EXPECT_TRUE(is_clear(pixel(through.px, centre().x, centre().y)))
        << "blown through, yet something painted the hole";
}

TEST_F(HullInteriorTest, RearHullInteriorNeverPaintsThroughFrontHole) {
    const auto ring = internal_ring({0.0f, 0.0f, kBoxHalf}, 30.0f, 10.0f);
    const auto single = render_one(ring, filled.get());
    const glm::mat4 behind = glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 0.0f, -100.0f));
    const auto pair = render({Placed{glm::mat4(1.0f), ring},
                              Placed{behind, scenegraph::DamageDecalRing{}}},
                             filled.get());
    report("single", single, centre());
    report("pair", pair, centre());
    EXPECT_EQ(pair.marks, 1) << "the undamaged rear hull must take no marking";
    EXPECT_EQ(pair.interiors, 1);
    EXPECT_FALSE(is_clear(pixel(single.px, centre().x, centre().y)));
    EXPECT_EQ(rgb_diff(pixel(pair.px, centre().x, centre().y),
                       pixel(single.px, centre().x, centre().y)), 0)
        << "the rear hull shows through the front hole";
}

TEST_F(HullInteriorTest, UndamagedSceneDrawsNoInterior) {
    const scenegraph::DamageDecalRing none;
    const auto stock = render_one(none, filled.get(), /*stock=*/true);
    const auto s = render_one(none, filled.get());
    ASSERT_GT(count_non_black(stock.px), 1000) << "the box does not render";
    EXPECT_EQ(s.marks, 0);
    EXPECT_EQ(s.interiors, 0);
    EXPECT_EQ(s.px, stock.px);
}
