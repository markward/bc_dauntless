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
#include <scenegraph/hull_damage.h>
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
        scenegraph::HullDamageStore ring;
        bool rock = false;
        // With a viewscreen `policy`, this instance is the viewscreen's target.
        bool viewscreen_target = false;
    };
    struct Shot {
        std::vector<std::uint8_t> px;
        int marks = -1;
        int interiors = -1;
        int far_draws = -1;
    };

    // What render() draws with: every hull near by default (these tests pin
    // the near look; quad_cam is ~85 GU from the box surface), quad_cam, and a
    // fresh FrameSubmitter per render unless `shared` is set.
    renderer::InteriorPolicy policy = all_near_policy();
    scenegraph::Camera cam = quad_cam();
    renderer::FrameSubmitter* shared = nullptr;
    // FrameSubmitter::set_plating_record_culling for every render.
    bool record_culling = true;

    // Every `placed` box drawn through submit_opaque_in_pass then
    // submit_plating_interior (or submit_opaque alone when `stock`), the
    // interior's fill coming from `fills`, under `policy` seen from `cam`.
    Shot render(const std::vector<Placed>& placed, renderer::CarveFieldCache* fills,
                bool stock = false, const assets::Model* use_model = nullptr) {
        const assets::Model* drawn = use_model != nullptr ? use_model : box.get();
        scenegraph::World world;
        renderer::InteriorPolicy drawn_policy = policy;
        for (const Placed& pl : placed) {
            auto iid = world.create_instance(
                reinterpret_cast<scenegraph::ModelHandle>(drawn));
            world.set_world_transform(iid, pl.world);
            world.get(iid)->hull_damage = pl.ring;
            world.get(iid)->surface_is_rock = pl.rock;
            if (pl.viewscreen_target) drawn_policy.viewscreen_target = iid;
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
        renderer::FrameSubmitter own;
        renderer::FrameSubmitter& submitter = shared != nullptr ? *shared : own;
        submitter.set_interior_policy(drawn_policy);
        submitter.set_plating_record_culling(record_culling);
        const auto lookup = [](scenegraph::ModelHandle h) -> const assets::Model* {
            return reinterpret_cast<const assets::Model*>(h);
        };
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
            out.far_draws = submitter.plating_far_draws_last_frame();
        }
        out.px.assign(static_cast<std::size_t>(kSize) * kSize * 4, 0);
        glReadPixels(0, 0, kSize, kSize, GL_RGBA, GL_UNSIGNED_BYTE, out.px.data());
        return out;
    }

    Shot render_one(const scenegraph::HullDamageStore& ring, renderer::CarveFieldCache* fills,
                    bool stock = false, const assets::Model* use_model = nullptr) {
        return render({Placed{glm::mat4(1.0f), ring}}, fills, stock, use_model);
    }

    // The near face's centre, where the camera axis meets the box.
    glm::ivec2 centre() const { return to_pixel(cam, glm::vec3(0.0f, 0.0f, kBoxHalf)); }

    static void report(const char* what, const Shot& s, glm::ivec2 c) {
        const std::uint8_t* q = pixel(s.px, c.x, c.y);
        std::fprintf(stderr,
                     "[HullInterior] %s centre=(%d,%d,%d) marks=%d interiors=%d far=%d\n",
                     what, q[0], q[1], q[2], s.marks, s.interiors, s.far_draws);
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
    scenegraph::HullDamageStore ring;
    ring.add(rec_a, glm::vec3(0.0f), reach_a, wear_a, scenegraph::HullDamageKind::Internal);
    ring.add(rec_b, glm::vec3(0.0f), reach_b, wear_b, scenegraph::HullDamageKind::Internal);

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
                              Placed{behind, scenegraph::HullDamageStore{}}},
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

// I2 of the final review: rocks are not ships. A damaged rock takes no
// marking and no interior; its hole stays see-through as before step 2c.
TEST_F(HullInteriorTest, RockGetsNeitherMarkNorInterior) {
    const auto ring = internal_ring({0.0f, 0.0f, kBoxHalf}, 30.0f, 10.0f);
    const auto rock = render({Placed{glm::mat4(1.0f), ring, /*rock=*/true}}, filled.get());
    report("rock", rock, centre());
    EXPECT_EQ(rock.marks, 0);
    EXPECT_EQ(rock.interiors, 0);
    EXPECT_TRUE(is_clear(pixel(rock.px, centre().x, centre().y)))
        << "a rock's hole must stay see-through";
}

// I3 of the final review: Review Focus 1 with a DAMAGED rear hull. Its cut
// (the same ring, so its hole sits right behind the front hole) is marked and
// shaded too, but must never show through the front hull's hole, whichever
// hull the world lists first.
TEST_F(HullInteriorTest, DamagedRearHullInteriorNeverPaintsThroughFrontHole) {
    const auto ring = internal_ring({0.0f, 0.0f, kBoxHalf}, 30.0f, 10.0f);
    const auto single = render_one(ring, filled.get());
    ASSERT_FALSE(is_clear(pixel(single.px, centre().x, centre().y)));
    const glm::mat4 behind = glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 0.0f, -100.0f));
    const Placed front{glm::mat4(1.0f), ring};
    const Placed rear{behind, ring};
    for (const bool front_first : {true, false}) {
        const auto pair = front_first ? render({front, rear}, filled.get())
                                      : render({rear, front}, filled.get());
        report(front_first ? "damaged pair, front first" : "damaged pair, rear first",
               pair, centre());
        EXPECT_EQ(pair.marks, 2);
        EXPECT_EQ(pair.interiors, 2);
        EXPECT_EQ(rgb_diff(pixel(pair.px, centre().x, centre().y),
                           pixel(single.px, centre().x, centre().y)), 0)
            << "the damaged rear hull shows through the front hole (front_first="
            << front_first << ")";
    }
}

TEST_F(HullInteriorTest, UndamagedSceneDrawsNoInterior) {
    const scenegraph::HullDamageStore none;
    const auto stock = render_one(none, filled.get(), /*stock=*/true);
    const auto s = render_one(none, filled.get());
    ASSERT_GT(count_not_clear(stock.px), 1000) << "the box does not render";
    EXPECT_EQ(s.marks, 0);
    EXPECT_EQ(s.interiors, 0);
    EXPECT_EQ(s.px, stock.px);
}

// ---- Phase 2 (near/far): the interior policy (renderer/hull_interior_policy.h).
// quad_cam's eye is 120 GU from the box centre; the box's bounding sphere
// (radius 20 x sqrt(3) = 34.6) starts 85.4 GU out.
namespace {
int rgb_sum(const std::uint8_t* q) { return q[0] + q[1] + q[2]; }
}  // namespace

// A far hull takes no marking and no interior: its hole is painted in place
// as wreckage by the plating draw, never left see-through.
TEST_F(HullInteriorTest, FarHullPaintsHoleAsWreck) {
    const auto ring = internal_ring({0.0f, 0.0f, kBoxHalf}, 30.0f, 10.0f);
    dauntless_plating::g_params[24] = 1000.0f;   // the plates hold: not blown through
    const auto hull = render_one(scenegraph::HullDamageStore{}, filled.get());
    policy.near_gu = 1.0f;
    const auto far = render_one(ring, filled.get());
    report("far", far, centre());
    EXPECT_EQ(far.marks, 0);
    EXPECT_EQ(far.interiors, 0);
    EXPECT_EQ(far.far_draws, 1);
    const std::uint8_t* q = pixel(far.px, centre().x, centre().y);
    EXPECT_FALSE(is_clear(q)) << "a far hole must be painted as wreckage, not see-through";
    EXPECT_LT(rgb_sum(q) * 2, rgb_sum(pixel(hull.px, centre().x, centre().y)))
        << "the far hole is not painted as dark wreckage";
}

// Blown clear through (wear past deck break), the hole is cut at any distance.
TEST_F(HullInteriorTest, FarBlownThroughStillCuts) {
    const auto ring = internal_ring(glm::vec3(0.0f), 60.0f, 10.0f);
    dauntless_plating::g_params[24] = 0.01f;
    policy.near_gu = 1.0f;
    const auto s = render_one(ring, filled.get());
    report("far, deck break 0.01", s, centre());
    EXPECT_EQ(s.marks, 0);
    EXPECT_EQ(s.interiors, 0);
    EXPECT_TRUE(is_clear(pixel(s.px, centre().x, centre().y)))
        << "a far hull blown through must still show what is behind it";
}

// The production default (20 GU) with the camera close: rooms, as before.
TEST_F(HullInteriorTest, NearHullStillDrawsInterior) {
    policy = renderer::InteriorPolicy{};
    cam.eye = glm::vec3(0.0f, 0.0f, 50.0f);   // sphere surface 15.4 GU out
    const auto ring = internal_ring({0.0f, 0.0f, kBoxHalf}, 30.0f, 10.0f);
    const auto s = render_one(ring, filled.get());
    report("near (default policy)", s, centre());
    EXPECT_EQ(s.marks, 1);
    EXPECT_EQ(s.interiors, 1);
    EXPECT_EQ(s.far_draws, 0);
    EXPECT_FALSE(is_clear(pixel(s.px, centre().x, centre().y)))
        << "the hole shows what is behind the ship, not its interior";
}

// One near/far decision per instance per render: a hull whose sphere spans
// near_gu (surface 85.4 GU in, centre 120 GU out) is either marked or painted
// far, never both.
TEST_F(HullInteriorTest, OneDecisionPerInstancePerRender) {
    const auto ring = internal_ring({0.0f, 0.0f, kBoxHalf}, 30.0f, 10.0f);
    policy.near_gu = 100.0f;
    const auto s = render_one(ring, filled.get());
    report("straddling near_gu", s, centre());
    EXPECT_EQ(s.marks + s.far_draws, 1);
}

// On the viewscreen only its target gets rooms, whatever the distance.
TEST_F(HullInteriorTest, ViewscreenOnlyTargetGetsInterior) {
    const auto ring = internal_ring({0.0f, 0.0f, kBoxHalf}, 30.0f, 10.0f);
    dauntless_plating::g_params[24] = 1000.0f;   // the plates hold everywhere
    policy = renderer::InteriorPolicy{};
    policy.near_gu = 1.0e9f;                     // distance plays no part
    policy.viewscreen = true;
    const glm::vec3 at_l(-30.0f, 0.0f, 0.0f), at_r(30.0f, 0.0f, 0.0f);
    const auto s = render({Placed{glm::translate(glm::mat4(1.0f), at_l), ring, false, true},
                           Placed{glm::translate(glm::mat4(1.0f), at_r), ring}},
                          filled.get());
    report("viewscreen, left targeted", s, centre());
    EXPECT_EQ(s.marks, 1);
    EXPECT_EQ(s.interiors, 1);
    EXPECT_EQ(s.far_draws, 1);
    const glm::ivec2 l = to_pixel(cam, at_l + glm::vec3(0.0f, 0.0f, kBoxHalf));
    const glm::ivec2 r = to_pixel(cam, at_r + glm::vec3(0.0f, 0.0f, kBoxHalf));
    EXPECT_FALSE(is_clear(pixel(s.px, l.x, l.y))) << "target hole: no rooms";
    EXPECT_FALSE(is_clear(pixel(s.px, r.x, r.y))) << "other hole: not painted";
}

TEST_F(HullInteriorTest, ViewscreenWithoutTargetDrawsNoInterior) {
    const auto ring = internal_ring({0.0f, 0.0f, kBoxHalf}, 30.0f, 10.0f);
    policy = renderer::InteriorPolicy{};
    policy.near_gu = 1.0e9f;
    policy.viewscreen = true;
    const auto s = render_one(ring, filled.get());
    report("viewscreen, no target", s, centre());
    EXPECT_EQ(s.marks, 0);
    EXPECT_EQ(s.interiors, 0);
}

// The viewscreen's policy must not stick: the next (main view) render on the
// same submitter, under the default policy with the camera close, has rooms.
TEST_F(HullInteriorTest, MainViewPolicyRestoredAfterViewscreen) {
    renderer::FrameSubmitter submitter;
    shared = &submitter;
    cam.eye = glm::vec3(0.0f, 0.0f, 50.0f);
    const auto ring = internal_ring({0.0f, 0.0f, kBoxHalf}, 30.0f, 10.0f);
    policy = renderer::InteriorPolicy{};
    policy.viewscreen = true;
    const auto vs = render_one(ring, filled.get());
    EXPECT_EQ(vs.interiors, 0);
    policy = renderer::InteriorPolicy{};
    const auto main_view = render_one(ring, filled.get());
    report("main after viewscreen", main_view, centre());
    EXPECT_EQ(main_view.marks, 1);
    EXPECT_EQ(main_view.interiors, 1);
    shared = nullptr;
}

// Rocks have no rooms: a far rock's hole stays see-through, never wreckage.
TEST_F(HullInteriorTest, FarRockHoleStaysSeeThrough) {
    const auto ring = internal_ring({0.0f, 0.0f, kBoxHalf}, 30.0f, 10.0f);
    dauntless_plating::g_params[24] = 1000.0f;
    policy.near_gu = 1.0f;
    const auto s = render({Placed{glm::mat4(1.0f), ring, /*rock=*/true}}, filled.get());
    report("far rock", s, centre());
    EXPECT_EQ(s.far_draws, 0);
    EXPECT_TRUE(is_clear(pixel(s.px, centre().x, centre().y)));
}

// ---- Phase 2 Task 3: the deck-break subset. ---------------------------------
// The walk's blown tests read only the records that can blow a plate
// (plating::deck_break_subset); shading keeps the whole list. Setup: one
// heavy record above the near face blows it and the deck at z = 18.69 open;
// four light records (wear 4.5, below deck break 6 less the 1.125 tear-noise
// lift, and clear of every other sphere) sit on the next deck down, z = 16.02,
// which holds. The light records are outside the subset, yet they soot that
// deck: the walk must shade it from the whole list, so the picture is the
// same with the subset as without.
TEST_F(HullInteriorTest, InteriorSubsetMatchesFullWalk) {
    dauntless_plating::g_params[24] = 6.0f;
    dauntless_plating::g_params[19] = 0.9f;
    const float deck = 6.0f * 2.67f;
    scenegraph::HullDamageStore heavy;
    heavy.add({0.0f, 0.0f, 26.0f}, glm::vec3(0.0f), 10.0f, 1000.0f,
              scenegraph::HullDamageKind::Internal);
    scenegraph::HullDamageStore ring = heavy;
    const glm::vec2 lights[4] = {{4, 4}, {-4, 4}, {4, -4}, {-4, -4}};
    for (const auto& xy : lights)
        ring.add({xy.x, xy.y, deck}, glm::vec3(0.0f), 1.4f, 4.5f,
                 scenegraph::HullDamageKind::Internal);
    const auto list = renderer::plating::build_damage_list(ring, dauntless_plating::g_params);
    ASSERT_EQ(list.count, 5);
    const auto db = renderer::plating::deck_break_subset(list, dauntless_plating::g_params);
    ASSERT_EQ(db.count, 1) << "only the heavy record can blow a plate";
    EXPECT_EQ(db.idx[0], 0);

    record_culling = true;
    const auto on = render_one(ring, filled.get());
    record_culling = false;
    const auto off = render_one(ring, filled.get());
    record_culling = true;
    const auto heavy_only = render_one(heavy, filled.get());
    const glm::ivec2 lp = to_pixel(cam, glm::vec3(4.0f, 4.0f, deck));
    const std::uint8_t* a = pixel(on.px, lp.x, lp.y);
    const std::uint8_t* h = pixel(heavy_only.px, lp.x, lp.y);
    std::fprintf(stderr, "[HullInterior] subset light deck=(%d,%d,%d) heavy only=(%d,%d,%d)\n",
                 a[0], a[1], a[2], h[0], h[1], h[2]);
    ASSERT_EQ(on.interiors, 1);
    ASSERT_FALSE(is_clear(pixel(on.px, centre().x, centre().y)));
    ASSERT_FALSE(is_clear(a)) << "the light records' deck is not drawn";
    EXPECT_GT(rgb_diff(a, h), 0) << "the light records do not shade their deck";
    int diff = 0;
    for (std::size_t i = 0; i < on.px.size(); ++i) diff += on.px[i] != off.px[i] ? 1 : 0;
    EXPECT_EQ(diff, 0) << "the deck-break subset changed the interior";
}
