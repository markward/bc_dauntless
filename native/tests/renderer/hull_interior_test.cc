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
#include <filesystem>
#include <memory>
#include <vector>

#include "plating_gl_fixture.h"
#include "support/content_root.h"

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

// The framebuffer is cleared to this, deliberately NOT black: the interior's
// out-of-steps shade is near-black (~1,1,1) and must never pass for a discard.
constexpr float kClearR = 0.8f, kClearG = 0.2f, kClearB = 0.8f;

bool is_clear(const std::uint8_t* q) {
    return std::abs(q[0] - 204) <= 1 && std::abs(q[1] - 51) <= 1 &&
           std::abs(q[2] - 204) <= 1;
}

int count_not_clear(const std::vector<std::uint8_t>& px) {
    int n = 0;
    for (std::size_t i = 0; i + 3 < px.size(); i += 4)
        if (!is_clear(&px[i])) ++n;
    return n;
}

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
                bool stock = false, const assets::Model* use_model = nullptr) {
        const assets::Model* drawn = use_model != nullptr ? use_model : box.get();
        scenegraph::World world;
        for (const Placed& pl : placed) {
            auto iid = world.create_instance(
                reinterpret_cast<scenegraph::ModelHandle>(drawn));
            world.set_world_transform(iid, pl.world);
            world.get(iid)->decals = pl.ring;
        }
        glViewport(0, 0, kSize, kSize);
        glClearColor(kClearR, kClearG, kClearB, 1.0f);
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
                    bool stock = false, const assets::Model* use_model = nullptr) {
        return render({Placed{glm::mat4(1.0f), ring}}, fills, stock, use_model);
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

// The char band sits at the tear, not over the whole interior.
//
// Setup: two small holes in the near face, both over the SAME room cell
// (x in [6, 12), y in [0, 8.67), z cell 7, whose floor is the deck plane
// z = 7 x 2.67 = 18.69, 1.31 mu below the face). Same cell = same room light
// and floor albedo, so the two deck pixels differ only by their char. The
// cell is chosen for its room state: a white-lit or dark room, so an
// uncharred deck is grey (cell x 0 is an emergency-red room, which would
// tint deck A red without any char).
//   A at (7, 4): its record hovers 2.7 mu above the face (reach 4), so it
//     tears the face but the deck under it is out of every record's reach:
//     wear 0, an undamaged deck, never charred.
//   B at (11, 4): its record (reach 3.5) still reaches the deck under it.
//     Deck break is set 0.3 above that deck's wear (tear noise 0, so the
//     wear the shader sees is exact): the plate holds, inside the char band.
// Neither record reaches the other hole's deck.
TEST_F(HullInteriorTest, CharBandFollowsTheTearNotTheWholeInterior) {
    dauntless_plating::g_params[19] = 0.0f;   // tear noise: exact wear
    const glm::vec3 rec_a(7.0f, 4.0f, kBoxHalf + 2.7f);
    const glm::vec3 rec_b(11.0f, 4.0f, kBoxHalf + 1.0f);
    const float reach_a = 4.0f, wear_a = 30.0f;
    const float reach_b = 3.5f, wear_b = 40.0f;
    scenegraph::DamageDecalRing ring;
    ring.add(rec_a, glm::vec3(0, 0, 1), reach_a, 1.0f, scenegraph::WeaponClass::Internal,
             0.0f, glm::vec3(0.0f), wear_a);
    ring.add(rec_b, glm::vec3(0, 0, 1), reach_b, 1.0f, scenegraph::WeaponClass::Internal,
             0.0f, glm::vec3(0.0f), wear_b);

    const auto cam = quad_cam();
    const glm::ivec2 pa = to_pixel(cam, glm::vec3(7.0f, 4.0f, kBoxHalf));
    const glm::ivec2 pb = to_pixel(cam, glm::vec3(11.0f, 4.0f, kBoxHalf));
    // Where pixel `px`'s centre ray meets the deck plane.
    const float deck_z = 7.0f * 2.67f;
    auto deck_point = [&](glm::ivec2 px) {
        const glm::mat4 inv = glm::inverse(cam.proj_matrix() * cam.view_matrix());
        const glm::vec2 ndc((px.x + 0.5f) / kSize * 2.0f - 1.0f,
                            (px.y + 0.5f) / kSize * 2.0f - 1.0f);
        const glm::vec4 a = inv * glm::vec4(ndc, -1.0f, 1.0f);
        const glm::vec4 b = inv * glm::vec4(ndc, 1.0f, 1.0f);
        const glm::vec3 o = glm::vec3(a) / a.w;
        const glm::vec3 d = glm::vec3(b) / b.w - o;
        return o + d * ((deck_z - o.z) / d.z);
    };
    auto wear_at = [](const glm::vec3& p, const glm::vec3& c, float reach, float wear) {
        const float r = glm::length(p - c) / reach;
        if (r >= 1.0f) return 0.0f;
        const float f = 1.0f - r * r;
        return wear * f * f;
    };
    const glm::vec3 da = deck_point(pa), db = deck_point(pb);
    ASSERT_EQ(wear_at(da, rec_a, reach_a, wear_a) + wear_at(da, rec_b, reach_b, wear_b), 0.0f)
        << "deck A must be out of every record's reach";
    ASSERT_EQ(wear_at(db, rec_a, reach_a, wear_a), 0.0f);
    const float wear_db = wear_at(db, rec_b, reach_b, wear_b);
    ASSERT_GT(wear_db, 2.0f);
    dauntless_plating::g_params[24] = wear_db + 0.3f;

    const auto s = render_one(ring, filled.get());
    const std::uint8_t* a = pixel(s.px, pa.x, pa.y);
    const std::uint8_t* b = pixel(s.px, pb.x, pb.y);
    std::fprintf(stderr, "[HullInterior] deck A (wear 0)=(%d,%d,%d) deck B (wear %.2f, "
                 "break %.2f)=(%d,%d,%d)\n", a[0], a[1], a[2], wear_db,
                 dauntless_plating::g_params[24], b[0], b[1], b[2]);
    ASSERT_EQ(s.interiors, 1);
    ASSERT_FALSE(is_clear(a)) << "deck A not drawn";
    ASSERT_FALSE(is_clear(b)) << "deck B not drawn";
    EXPECT_LT(a[0] - a[2], 12) << "an undamaged deck is orange-tinted (charred)";
    EXPECT_LT(b[2] + 10, a[2]) << "the deck at the tear is not charred darker";
    EXPECT_GT(b[0] - b[2], a[0] - a[2] + 10) << "the deck at the tear has no glow";
}

// An empty volume is never uploaded, and must not leave an entry behind that
// hides the hull's real fill from get_for_source.
TEST_F(HullInteriorTest, PutEmptyFillDoesNotShadowTheRealOne) {
    const auto nif = test_support::game_root() / "data/Models/Ships/Ambassador/Ambassador.nif";
    if (!std::filesystem::is_regular_file(nif))
        GTEST_SKIP() << "BC asset not available at " << nif << " -- set DAUNTLESS_GAME_DIR";
    renderer::CarveFieldCache cache;
    EXPECT_EQ(cache.put_for_source(nif, voxel::VoxelVolume{}), nullptr);
    EXPECT_NE(cache.get_for_source(nif), nullptr);
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

// I1 of the final review: an INTACT part of the same hull, seen through a
// blown-through hole, must stay what the opaque pass drew. Here a
// front-facing quad sits inside the box, behind the cut face and inside the
// record's reach; with the hole blown through, the interior draw must not
// repaint the quad as rooms.
TEST_F(HullInteriorTest, IntactPartOfSameHullBehindBlownHoleIsNotRepainted) {
    for (const float quad_z : {-100.0f}) {
        auto two = build_box(kBoxHalf);
        two->source = kBoxSource;
        add_quad(*two, kBoxHalf, quad_z, /*facing_camera=*/true);
        const auto ring = internal_ring(glm::vec3(0.0f), 60.0f, 10.0f);
        dauntless_plating::g_params[24] = 0.01f;
        dauntless_plating::g_params[25] = 1.0f;

        const auto on = render_one(ring, filled.get(), false, two.get());
        dauntless_plating::g_params[25] = 0.0f;
        const auto off = render_one(ring, filled.get(), false, two.get());
        std::fprintf(stderr, "[HullInterior] quad z=%.0f:\n", quad_z);
        report("  interior on", on, centre());
        report("  interior off", off, centre());
        EXPECT_EQ(on.interiors, 1);
        EXPECT_FALSE(is_clear(pixel(off.px, centre().x, centre().y)))
            << "the probe's quad must be visible through the hole (z=" << quad_z << ")";
        EXPECT_EQ(rgb_diff(pixel(on.px, centre().x, centre().y),
                           pixel(off.px, centre().x, centre().y)), 0)
            << "the intact quad behind the hole was painted as interior (z=" << quad_z << ")";
    }
}

TEST_F(HullInteriorTest, UndamagedSceneDrawsNoInterior) {
    const scenegraph::DamageDecalRing none;
    const auto stock = render_one(none, filled.get(), /*stock=*/true);
    const auto s = render_one(none, filled.get());
    ASSERT_GT(count_not_clear(stock.px), 1000) << "the box does not render";
    EXPECT_EQ(s.marks, 0);
    EXPECT_EQ(s.interiors, 0);
    EXPECT_EQ(s.px, stock.px);
}
