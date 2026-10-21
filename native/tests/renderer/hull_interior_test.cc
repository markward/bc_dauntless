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

#include <renderer/hull_fill_cache.h>
#include <renderer/frame.h>
#include <renderer/pipeline.h>
#include <renderer/plating_damage.h>

#include <scenegraph/camera.h>
#include <scenegraph/damage_decals.h>
#include <scenegraph/hull_damage.h>
#include <scenegraph/world.h>

#include <assets/material.h>
#include <assets/model.h>
#include <assets/texture.h>

#include <voxel/volume.h>

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <chrono>
#include <memory>
#include <thread>
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
    std::unique_ptr<renderer::HullFillCache> filled;   // holds the box's fill
    std::unique_ptr<renderer::HullFillCache> empty;    // has no fill for it

    void SetUp() override {
        PlatingGLFixture::SetUp();
        if (!w) return;
        dauntless_plating::g_params[0] = 1.0f;
        box = build_box(kBoxHalf);
        box->source = kBoxSource;
        filled = std::make_unique<renderer::HullFillCache>();
        ASSERT_NE(filled->put_for_source(kBoxSource, solid_box_fill()), nullptr);
        empty = std::make_unique<renderer::HullFillCache>();
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
        scenegraph::BreachEventRing breach{};   // Instance::breach_events
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
    Shot render(const std::vector<Placed>& placed, renderer::HullFillCache* fills,
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
            world.get(iid)->breach_events = pl.breach;
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

    Shot render_one(const scenegraph::HullDamageStore& ring, renderer::HullFillCache* fills,
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
    renderer::HullFillCache hollow_cache;
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
    renderer::HullFillCache cache;
    EXPECT_EQ(cache.put_for_source(nif, voxel::VoxelVolume{}), nullptr);
    const renderer::HullFillCache::Entry* e = nullptr;
    for (int i = 0; i < 1000 && e == nullptr; ++i) {
        e = cache.get_for_source(nif);
        if (e == nullptr) std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    EXPECT_NE(e, nullptr);
}

// A fill installed with put_for_source after the source's prefetch decoded
// drops the decoded volume: get_for_source returns the installed entry and
// never reads it, so it would sit in memory for the cache's lifetime.
TEST_F(HullInteriorTest, PutAfterPrefetchDropsTheDecodedVolume) {
    const auto nif = test_support::game_root() / "data/Models/Ships/Ambassador/Ambassador.nif";
    if (!std::filesystem::is_regular_file(nif))
        GTEST_SKIP() << "BC asset not available at " << nif << " -- set DAUNTLESS_GAME_DIR";
    renderer::HullFillCache cache;
    cache.prefetch(nif);
    for (int i = 0; i < 1000 && cache.decoded_pending() == 0; ++i)
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    ASSERT_EQ(cache.decoded_pending(), 1u) << "decode not done within 10 s";
    ASSERT_NE(cache.put_for_source(nif, solid_box_fill()), nullptr);
    EXPECT_EQ(cache.decoded_pending(), 0u) << "the superseded decode is still held";
}

// get_for_source never blocks on the CPU decode: a fresh cache answers nullptr
// at once, and the entry shows up once the background worker is done.
TEST_F(HullInteriorTest, FillPrefetchDoesNotBlockAndBecomesReady) {
    const auto nif = test_support::game_root() / "data/Models/Ships/Ambassador/Ambassador.nif";
    if (!std::filesystem::is_regular_file(nif))
        GTEST_SKIP() << "BC asset not available at " << nif << " -- set DAUNTLESS_GAME_DIR";
    renderer::HullFillCache cache;
    const auto t0 = std::chrono::steady_clock::now();
    EXPECT_EQ(cache.get_for_source(nif), nullptr);
    const auto first_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - t0).count();
    EXPECT_LT(first_ms, 50) << "get_for_source blocked on the decode";

    const renderer::HullFillCache::Entry* e = nullptr;
    for (int i = 0; i < 1000 && e == nullptr; ++i) {
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
        e = cache.get_for_source(nif);
    }
    ASSERT_NE(e, nullptr) << "fill not ready within 10 s";
    EXPECT_NE(e->tex3d, 0u);
}

// While the fill is still loading the cache hands back nullptr, which the
// interior draw treats as "no fill": rooms with no left-the-ship test.
TEST_F(HullInteriorTest, InteriorDrawsWhileFillIsLoading) {
    const auto nif = test_support::game_root() / "data/Models/Ships/Ambassador/Ambassador.nif";
    if (!std::filesystem::is_regular_file(nif))
        GTEST_SKIP() << "BC asset not available at " << nif << " -- set DAUNTLESS_GAME_DIR";
    renderer::HullFillCache loading;
    EXPECT_EQ(loading.get_for_source(nif), nullptr);     // starts the decode
    EXPECT_EQ(loading.get_for_source(kBoxSource), nullptr);  // box hull: still loading
    const auto ring = internal_ring({0.0f, 0.0f, kBoxHalf}, 30.0f, 10.0f);
    const auto s = render_one(ring, &loading);
    report("fill loading", s, centre());
    EXPECT_EQ(s.interiors, 1);
    EXPECT_FALSE(is_clear(pixel(s.px, centre().x, centre().y)))
        << "a hole drawn while the fill loads shows the clear colour";
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

// ---- Phase 3 Task 2: rock craters. Rocks are not ships: no panels, ribs or
// rooms. A rock's cut is marked and filled by the interior pass in its rock
// mode, which marches the damage field from the cut to the crater wall and
// shades it with the rock's own base texture. (Supersedes phase 2's
// RockGetsNeitherMarkNorInterior: a rock's hole is no longer see-through.)
namespace {
// The box with a 1x1 base texture of `rgb` on every face (Material Base
// stage), as a rock model carries its own rock texture.
std::unique_ptr<assets::Model> textured_box(const std::uint8_t (&rgb)[3]) {
    auto m = build_box(kBoxHalf);
    m->source = kBoxSource;
    assets::Image img;
    img.width = 1;
    img.height = 1;
    img.format = assets::Image::Format::RGBA8;
    img.pixels = {rgb[0], rgb[1], rgb[2], 255};
    m->textures.push_back(assets::upload_image(img, /*generate_mipmaps=*/false));
    m->materials[0].stages[static_cast<std::size_t>(assets::Material::StageSlot::Base)]
        .texture_index = 0;
    return m;
}
}  // namespace

TEST_F(HullInteriorTest, RockCraterShowsRockNotRoomsNotSpace) {
    const std::uint8_t red[3] = {255, 0, 0};
    const auto red_box = textured_box(red);
    const auto ring = internal_ring({0.0f, 0.0f, kBoxHalf}, 30.0f, 10.0f);
    const auto rock = render({Placed{glm::mat4(1.0f), ring, /*rock=*/true}}, filled.get(),
                             false, red_box.get());
    const auto ship = render({Placed{glm::mat4(1.0f), ring}}, filled.get(), false,
                             red_box.get());
    report("rock crater (red texture)", rock, centre());
    report("same hole, ship", ship, centre());
    EXPECT_EQ(rock.marks, 1);
    EXPECT_EQ(rock.interiors, 1);
    const std::uint8_t* q = pixel(rock.px, centre().x, centre().y);
    ASSERT_FALSE(is_clear(q)) << "the crater shows space, not rock";
    EXPECT_GT(rgb_diff(q, pixel(ship.px, centre().x, centre().y)), 10)
        << "the crater shows the ship's rooms";
    EXPECT_GT(q[0], 10) << "the crater wall is black";
    EXPECT_GT(q[0], 2 * q[1]) << "the crater is not shaded with the rock's texture";
    EXPECT_GT(q[0], 2 * q[2]) << "the crater is not shaded with the rock's texture";

    // No base texture: the flat rock colour, never space.
    const auto plain = render({Placed{glm::mat4(1.0f), ring, /*rock=*/true}}, filled.get());
    report("rock crater (no texture)", plain, centre());
    const std::uint8_t* f = pixel(plain.px, centre().x, centre().y);
    EXPECT_FALSE(is_clear(f)) << "an untextured rock's crater shows space";
    EXPECT_GE(f[0], f[2]) << "the flat rock colour is warm grey";
}

// Just outside the hole a rock looks exactly as it does with the plating
// layer off: no stripped panels, ribs or members. Ring reach 16, wear 10:
// 13 mu from its centre the wear is 1.16, past strip wear (0.5, a ship shows
// ribs there) but short of every breach (floor 2.42 less the 0.675 tear lift).
TEST_F(HullInteriorTest, RockHasNoPanelsOrRibs) {
    const auto ring = internal_ring({0.0f, 0.0f, kBoxHalf}, 16.0f, 10.0f);
    const Placed rock{glm::mat4(1.0f), ring, /*rock=*/true};
    const auto on = render({rock}, filled.get());
    dauntless_plating::g_params[0] = 0.0f;
    const auto off = render({rock}, filled.get());
    ASSERT_GT(count_not_clear(off.px), 1000) << "the box does not render";
    for (const glm::vec3 at : {glm::vec3(13.0f, 0.0f, kBoxHalf), glm::vec3(-13.0f, 0.0f, kBoxHalf),
                               glm::vec3(0.0f, 13.0f, kBoxHalf), glm::vec3(9.0f, 9.5f, kBoxHalf)}) {
        const glm::ivec2 px = to_pixel(cam, at);
        const std::uint8_t* a = pixel(on.px, px.x, px.y);
        const std::uint8_t* b = pixel(off.px, px.x, px.y);
        std::fprintf(stderr, "[HullInterior] rock near damage (%.0f,%.0f) on=(%d,%d,%d) "
                     "off=(%d,%d,%d)\n", at.x, at.y, a[0], a[1], a[2], b[0], b[1], b[2]);
        for (int k = 0; k < 3; ++k)
            EXPECT_LE(std::abs(a[k] - b[k]), 3)
                << "a rock shows plating near damage at (" << at.x << "," << at.y << ")";
    }
}

// Blown clear through: the march leaves the fill before it finds a wall.
TEST_F(HullInteriorTest, RockBlownThroughDiscards) {
    const auto ring = internal_ring(glm::vec3(0.0f), 60.0f, 10.0f);
    const auto s = render({Placed{glm::mat4(1.0f), ring, /*rock=*/true}}, filled.get());
    report("rock blown through", s, centre());
    EXPECT_EQ(s.marks, 1);
    EXPECT_EQ(s.interiors, 1);
    EXPECT_TRUE(is_clear(pixel(s.px, centre().x, centre().y)))
        << "a rock blown through must show what is behind it";
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

// The near test's sphere is centred on the model's box centre carried
// through the instance world, not the model origin. A quad 300 mu off its
// origin (box half-diagonal 14.1): with the camera 15 GU above the quad it is
// near (0.9 GU to the sphere) though the origin is 300 GU away; under a world
// scale of 2 and a shift putting the origin at the camera it is far (the quad
// sits 600 GU out) though the origin is right there.
TEST_F(HullInteriorTest, NearSphereIsCentredOnTheModelBoxNotItsOrigin) {
    auto off = std::make_unique<assets::Model>();
    add_face(*off, glm::vec3(300.0f, 0.0f, 0.0f), glm::vec3(1, 0, 0), glm::vec3(0, 1, 0), 10.0f);
    policy = renderer::InteriorPolicy{};
    cam.eye = glm::vec3(300.0f, 0.0f, 15.0f);
    cam.target = glm::vec3(300.0f, 0.0f, 0.0f);
    const auto ring = internal_ring({300.0f, 0.0f, 0.0f}, 8.0f, 10.0f);
    const auto near = render({Placed{glm::mat4(1.0f), ring}}, empty.get(), false, off.get());
    EXPECT_EQ(near.marks, 1) << "a hull 0.9 GU from the camera was judged far";
    EXPECT_EQ(near.far_draws, 0);

    cam.eye = glm::vec3(0.0f, 0.0f, 15.0f);
    cam.target = glm::vec3(0.0f);
    const glm::mat4 world = glm::scale(glm::mat4(1.0f), glm::vec3(2.0f));
    const auto far = render({Placed{world, ring}}, empty.get(), false, off.get());
    EXPECT_EQ(far.marks, 0) << "a hull 570 GU from the camera was judged near";
    EXPECT_EQ(far.far_draws, 1);
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

// Phase 3 Task 2 (supersedes phase 2's FarRockHoleStaysSeeThrough): rocks
// join the near/far policy. A far rock's crater is painted (darkened,
// scorched rock), never cut, marked or filled.
TEST_F(HullInteriorTest, FarRockCraterIsPaintedNotCut) {
    const auto ring = internal_ring({0.0f, 0.0f, kBoxHalf}, 30.0f, 10.0f);
    dauntless_plating::g_params[24] = 1000.0f;   // not blown through
    const auto whole = render({Placed{glm::mat4(1.0f), scenegraph::HullDamageStore{}, true}},
                              filled.get());
    policy.near_gu = 1.0f;
    const auto s = render({Placed{glm::mat4(1.0f), ring, /*rock=*/true}}, filled.get());
    report("far rock", s, centre());
    EXPECT_EQ(s.far_draws, 1);
    EXPECT_EQ(s.marks, 0);
    EXPECT_EQ(s.interiors, 0);
    const std::uint8_t* q = pixel(s.px, centre().x, centre().y);
    EXPECT_FALSE(is_clear(q)) << "a far rock's crater must be painted, not cut";
    EXPECT_LT(rgb_sum(q) * 2, rgb_sum(pixel(whole.px, centre().x, centre().y)))
        << "the far rock crater is not painted dark";
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

// ── Molten rims on fresh tears (layered damage phase 4 §2.3) ───────────────
namespace {
// A breach event at body point `c`, radius `r`, born `age` s before kDecalTime.
scenegraph::BreachEventRing rim_event(const glm::vec3& c, float r, float age) {
    scenegraph::BreachEventRing ring;
    ring.push(c, r, glm::vec3(0.0f, 0.0f, 1.0f), kDecalTime - age, 1u);
    return ring;
}
int redness(const std::uint8_t* q) { return int(q[0]) - int(q[2]); }
}  // namespace

// The plate char edge at a fresh tear takes the rim's heat: the deck at the
// tear (CharBandFollowsTheTearNotTheWholeInterior's deck B) is redder with
// the event just born than kRimLife + 1 s later.
TEST_F(HullInteriorTest, FreshTearHeatsTheCharEdge) {
    dauntless_plating::g_params[19] = 0.0f;   // tear noise: exact wear
    const glm::vec3 rec_b(11.0f, 4.0f, kBoxHalf + 1.0f);
    const float reach_b = 3.5f, wear_b = 40.0f;
    scenegraph::HullDamageStore ring;
    ring.add(rec_b, glm::vec3(0.0f), reach_b, wear_b, scenegraph::HullDamageKind::Internal);
    // Deck break just past the wear on the deck under B (the char band).
    const glm::ivec2 pb = to_pixel(cam, glm::vec3(11.0f, 4.0f, kBoxHalf));
    const float deck_z = 7.0f * 2.67f;
    const glm::mat4 inv = glm::inverse(cam.proj_matrix() * cam.view_matrix());
    const glm::vec2 ndc((pb.x + 0.5f) / kSize * 2.0f - 1.0f, (pb.y + 0.5f) / kSize * 2.0f - 1.0f);
    const glm::vec4 a4 = inv * glm::vec4(ndc, -1.0f, 1.0f), b4 = inv * glm::vec4(ndc, 1.0f, 1.0f);
    const glm::vec3 o = glm::vec3(a4) / a4.w, d = glm::vec3(b4) / b4.w - o;
    const glm::vec3 db = o + d * ((deck_z - o.z) / d.z);
    const float rr = glm::length(db - rec_b) / reach_b;
    ASSERT_LT(rr, 1.0f);
    const float wear_db = wear_b * (1.0f - rr * rr) * (1.0f - rr * rr);
    dauntless_plating::g_params[24] = wear_db + 0.3f;

    Placed pl{glm::mat4(1.0f), ring};
    pl.breach = rim_event(rec_b, 0.5f * reach_b, 0.0f);
    const auto fresh = render({pl}, filled.get());
    pl.breach = rim_event(rec_b, 0.5f * reach_b, scenegraph::kRimLife + 1.0f);
    const auto old = render({pl}, filled.get());
    const std::uint8_t* f = pixel(fresh.px, pb.x, pb.y);
    const std::uint8_t* c = pixel(old.px, pb.x, pb.y);
    std::fprintf(stderr, "[HullInterior] char edge fresh=(%d,%d,%d) old=(%d,%d,%d)\n",
                 f[0], f[1], f[2], c[0], c[1], c[2]);
    ASSERT_EQ(fresh.interiors, 1);
    ASSERT_FALSE(is_clear(f));
    EXPECT_GE(redness(f), redness(c) + 30) << "the char edge at a fresh tear is not molten";
}

// A far hull's wreck-painted hole is molten while its tear is fresh, and
// exactly the cold wreck once the event is older than kRimLife. Probed at
// twice the rim radius (heat 0.5: orange, not white-hot saturated).
TEST_F(HullInteriorTest, FarWreckRimGlowsWhenFresh) {
    const glm::vec3 hit(0.0f, 0.0f, kBoxHalf);
    const auto ring = internal_ring(hit, 30.0f, 10.0f);
    dauntless_plating::g_params[24] = 1000.0f;   // the plates hold: not blown through
    policy.near_gu = 1.0f;
    const float r = 5.0f;
    Placed pl{glm::mat4(1.0f), ring};
    const auto none = render({pl}, filled.get());
    pl.breach = rim_event(hit, r, 0.0f);
    const auto fresh = render({pl}, filled.get());
    pl.breach = rim_event(hit, r, scenegraph::kRimLife + 1.0f);
    const auto old = render({pl}, filled.get());
    ASSERT_EQ(fresh.far_draws, 1);
    const glm::ivec2 q = to_pixel(cam, hit + glm::vec3(2.0f * r, 0.0f, 0.0f));
    const std::uint8_t* f = pixel(fresh.px, q.x, q.y);
    const std::uint8_t* c = pixel(old.px, q.x, q.y);
    ASSERT_FALSE(is_clear(c)) << "the probe is not on the wreck";
    std::fprintf(stderr, "[HullInterior] far wreck fresh=(%d,%d,%d) old=(%d,%d,%d)\n",
                 f[0], f[1], f[2], c[0], c[1], c[2]);
    EXPECT_GE(redness(f), redness(c) + 40) << "a far wreck's fresh tear is not molten";
    int worst = 0;
    for (std::size_t i = 0; i < none.px.size(); ++i)
        worst = std::max(worst, std::abs(int(none.px[i]) - int(old.px[i])));
    EXPECT_LE(worst, 1) << "a cold tear still changes the far wreck";
}
