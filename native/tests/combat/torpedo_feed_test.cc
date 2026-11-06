// The native torpedo descriptor + torpedo light feed (torpedo_feed.h) on
// hand-built torpedo rows: the Python builders' dimming, forward, frame
// shifts, camera fade and counted skips, and _budgeted_dynamic_lights'
// slicing. The native-vs-Python differential over a real host runs from
// tests/host/test_native_torpedo_feed.py (phase 6 follow-up 1b, Task 3).
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>
#include <limits>
#include <optional>
#include <stdexcept>
#include <vector>

#include "dauntless/combat/mirror.h"
#include "dauntless/combat/py_math.h"
#include "dauntless/combat/torpedo_feed.h"
#include "dauntless/combat/torpedo_table.h"
#include "dauntless/transform_store.h"

using namespace dauntless::combat;
using dauntless::TransformStore;

namespace {

constexpr double kBright = 0.25, kRadScale = 50.0, kIntensity = 1.5,
                 kFadeStart = 13.0 / 0.175, kCull = 15.0 / 0.175;

TorpedoVisual photon_visual() {
    TorpedoVisual v;
    v.core_texture = "/g/data/Textures/Tactical/PhotonCore.tga";
    v.glow_texture = "/g/data/Textures/Tactical/PhotonGlow.tga";
    v.flares_texture = "/g/data/Textures/Tactical/PhotonFlares.tga";
    v.core_color = {1.0, 0.5, 0.1, 0.9};
    v.glow_color = {0.7, 0.3, 0.1, 0.8};
    v.flares_color = {0.3, 0.6, 0.9, 1.0};
    v.core_size_a = 0.2;
    v.core_size_b = 1.2;
    v.glow_size_a = 3.0;
    v.glow_size_b = 0.3;
    v.glow_size_c = 0.6;
    v.flares_size_a = 0.7;
    v.flares_size_b = 0.4;
    v.num_flares = 8;
    v.id = 41;
    v.light_base = py_max(3.0, 0.3);
    return v;
}

TorpedoVisual bolt_visual() {
    TorpedoVisual v;  // quad fields at Torpedo.__init__'s defaults
    v.is_disruptor = true;
    v.shell_color = {0.2, 0.9, 0.1, 1.0};
    v.bolt_core_color = {1.0, 1.0, 0.5, 1.0};
    v.bolt_length = 3.5;
    v.bolt_width = 0.3;
    v.id = 42;
    return v;
}

struct World {
    TransformStore store;
    Mirror m{store};
    int64_t set = -1;  // the viewed set, frame 1 at the origin
    TorpedoFeedCtx ctx;
    std::vector<TorpedoOut> torps;
    std::vector<TorpedoLightOut> lights;

    World() {
        set = add_set(1, {0.0, 0.0, 0.0});
        ctx.view = set;
        ctx.brightness = kBright;
        ctx.light_radius_scale = kRadScale;
        ctx.light_intensity = kIntensity;
        ctx.fade_start = kFadeStart;
        ctx.cull = kCull;
    }
    int64_t add_set(int64_t frame_id, Vec3 anchor) {
        const int64_t s = m.register_row(Kind::Set);
        ctx.frames[s] = BeamFrame{frame_id, anchor};
        return s;
    }
    int64_t torp(const Vec3& pos, const Vec3& v, int64_t in_set = -3,
                 const TorpedoVisual* vis = nullptr, double age = 1.25) {
        auto [i, g] = store.alloc();
        store.set_position(i, g, pos[0], pos[1], pos[2]);
        auto& t = m.torpedoes();
        const int64_t h = t.add(i, g);
        t.set_f(h, TorpField::_age, age);
        t.set_v(h, TorpField::_velocity, true, v);
        m.set_torpedo_ref(h, TorpField::_containing_set,
                          in_set == -3 ? set : in_set);
        const TorpedoVisual pv = photon_visual();
        t.set_visual(h, vis ? *vis : pv);
        return h;
    }
    TorpedoSkips skips{};
    void run() { build_torpedo_feed(m, ctx, torps, lights, skips); }
    int64_t skipped(TorpedoSkip w) const {
        return skips[static_cast<size_t>(w)];
    }
    int64_t total_skipped() const {
        int64_t n = 0;
        for (const int64_t k : skips) n += k;
        return n;
    }
};

bool same(const TorpedoLightOut& a, const TorpedoLightOut& b) {
    return a.position == b.position && a.color == b.color &&
           a.radius == b.radius && a.intensity == b.intensity;
}

std::array<double, 4> dim(const std::array<double, 4>& c, double s) {
    return {c[0] * s, c[1] * s, c[2] * s, c[3]};
}

// _camera_distance_fade's band, for a point `d` GU from the eye on +x.
double fade_at(double d) {
    const double d2 = d * d + 0.0 * 0.0 + 0.0 * 0.0;
    const double t = (std::sqrt(d2) - kFadeStart) / (kCull - kFadeStart);
    return 1.0 - t * t * (3.0 - 2.0 * t);
}

}  // namespace

TEST(TorpedoFeed, OneTorpedoMatchesPython) {
    World w;
    w.ctx.origin = {12.5, -30.25, 4.0};
    const Vec3 v{3.0, 4.0, 0.5};
    w.torp({60.1, 40.2, 10.3}, v);
    w.run();
    ASSERT_EQ(w.torps.size(), 1u);
    const TorpedoOut& o = w.torps[0];
    const TorpedoVisual pv = photon_visual();
    EXPECT_EQ(o.position, (Vec3{60.1 - 12.5, 40.2 - -30.25, 10.3 - 4.0}));
    EXPECT_EQ(o.core_color, dim(pv.core_color, kBright));
    EXPECT_EQ(o.glow_color, dim(pv.glow_color, kBright));
    EXPECT_EQ(o.flares_color, dim(pv.flares_color, kBright));
    EXPECT_EQ(o.age, 1.25);
    const double mag = py_pow(v[0] * v[0] + v[1] * v[1] + v[2] * v[2], 0.5);
    EXPECT_EQ(o.forward, (Vec3{v[0] / mag, v[1] / mag, v[2] / mag}));
    ASSERT_NE(o.visual, nullptr);
    EXPECT_EQ(o.visual->core_texture, pv.core_texture);
    EXPECT_EQ(o.visual->id, 41);
    EXPECT_EQ(o.visual->num_flares, 8);
    // The light: undimmed glow RGB, radius scale x max(glow a, glow b),
    // intensity knob x 1.0 (no eye), at the render position.
    ASSERT_EQ(w.lights.size(), 1u);
    const TorpedoLightOut& l = w.lights[0];
    EXPECT_EQ(l.position, o.position);
    EXPECT_EQ(l.color, (std::array<double, 3>{0.7, 0.3, 0.1}));
    EXPECT_EQ(l.radius, kRadScale * 3.0);
    EXPECT_EQ(l.intensity, kIntensity * 1.0);
}

TEST(TorpedoFeed, NearZeroVelocityFacesZ) {
    World w;
    w.torp({0.0, 0.0, 0.0}, {9e-7, 0.0, 0.0});
    w.torp({1.0, 0.0, 0.0}, {0.0, 0.0, 0.0});
    w.torp({2.0, 0.0, 0.0}, {-2e-6, 0.0, 0.0});
    w.run();
    ASSERT_EQ(w.torps.size(), 3u);
    EXPECT_EQ(w.torps[0].forward, (Vec3{0.0, 0.0, 1.0}));
    EXPECT_EQ(w.torps[1].forward, (Vec3{0.0, 0.0, 1.0}));
    // Past the 1e-6 threshold the velocity is normalised (-1, 0, 0).
    EXPECT_EQ(w.torps[2].forward[0], -2e-6 / py_pow(-2e-6 * -2e-6, 0.5));
}

TEST(TorpedoFeed, DisruptorHasNoLight) {
    World w;
    const TorpedoVisual bv = bolt_visual();
    w.torp({5.0, 6.0, 7.0}, {0.0, 6.0, 0.8}, -3, &bv);
    w.torp({1.0, 2.0, 3.0}, {1.0, 0.0, 0.0});
    w.run();
    ASSERT_EQ(w.torps.size(), 2u);
    const TorpedoOut& b = w.torps[0];
    EXPECT_TRUE(b.visual->is_disruptor);
    EXPECT_EQ(b.visual->core_texture, "");
    EXPECT_EQ(b.visual->shell_color, bv.shell_color);
    EXPECT_EQ(b.visual->bolt_length, 3.5);
    // The quad colours (white defaults) are still dimmed; the bolt's are not.
    EXPECT_EQ(b.core_color, (std::array<double, 4>{kBright, kBright, kBright,
                                                    1.0}));
    // One light, the photon's.
    ASSERT_EQ(w.lights.size(), 1u);
    EXPECT_EQ(w.lights[0].position, (Vec3{1.0, 2.0, 3.0}));
}

TEST(TorpedoFeed, ZeroGlowCastsNoLight) {
    World w;
    TorpedoVisual pv = photon_visual();
    pv.light_base = 0.0;
    w.torp({1.0, 2.0, 3.0}, {1.0, 0.0, 0.0}, -3, &pv);
    pv.light_base = -1.0;
    w.torp({1.0, 2.0, 3.0}, {1.0, 0.0, 0.0}, -3, &pv);
    w.run();
    EXPECT_EQ(w.torps.size(), 2u);
    EXPECT_TRUE(w.lights.empty());
}

TEST(TorpedoFeed, ZeroShiftKeepsNegativeZero) {
    World w;
    // A sibling set of the same frame at the same anchor: offset (0, 0, 0),
    // so the point is handed back untouched; the origin is -0.0 == zero.
    const int64_t sib = w.add_set(1, {0.0, 0.0, 0.0});
    w.ctx.origin = {-0.0, 0.0, 0.0};
    w.torp({-0.0, 1.0, -0.0}, {1.0, 0.0, 0.0}, sib);
    w.run();
    ASSERT_EQ(w.torps.size(), 1u);
    EXPECT_TRUE(std::signbit(w.torps[0].position[0]));
    EXPECT_TRUE(std::signbit(w.torps[0].position[2]));
    ASSERT_EQ(w.lights.size(), 1u);
    EXPECT_TRUE(std::signbit(w.lights[0].position[0]));
}

TEST(TorpedoFeed, OtherFrameDrawsNothing) {
    World w;
    w.ctx.origin = {1.0, 2.0, 3.0};
    const int64_t other = w.add_set(2, {0.0, 0.0, 0.0});
    const int64_t shifted = w.add_set(1, {100.0, 0.0, -50.0});
    w.torp({1.0, 1.0, 1.0}, {1.0, 0.0, 0.0}, other);
    w.torp({1.0, 1.0, 1.0}, {1.0, 0.0, 0.0}, -1);  // in no set
    w.torp({1.0, 1.0, 1.0}, {1.0, 0.0, 0.0}, shifted);
    w.run();
    // Only the shifted sibling draws: view-local = p + (anchor_b - anchor_a),
    // then minus the origin.
    ASSERT_EQ(w.torps.size(), 1u);
    EXPECT_EQ(w.torps[0].position,
              (Vec3{(1.0 + 100.0) - 1.0, (1.0 + 0.0) - 2.0,
                    (1.0 + -50.0) - 3.0}));
    ASSERT_EQ(w.lights.size(), 1u);
    EXPECT_EQ(w.lights[0].position, w.torps[0].position);
}

TEST(TorpedoFeed, FadeBandScalesIntensity) {
    World w;
    // The fade is judged on the VIEW position: a non-zero origin must not
    // move it.
    w.ctx.origin = {500.0, 500.0, 500.0};
    w.ctx.eye = Vec3{10.0, 0.0, 0.0};
    const double d = 80.0;
    ASSERT_GT(d, kFadeStart);
    ASSERT_LT(d, kCull);
    w.torp({10.0 + d, 0.0, 0.0}, {1.0, 0.0, 0.0});
    w.torp({10.0 + 5.0, 0.0, 0.0}, {1.0, 0.0, 0.0});  // inside: full
    w.run();
    ASSERT_EQ(w.lights.size(), 2u);
    const double dx = (10.0 + d) - 10.0;
    const double d2 = dx * dx + 0.0 * 0.0 + 0.0 * 0.0;
    const double t = (std::sqrt(d2) - kFadeStart) / (kCull - kFadeStart);
    EXPECT_EQ(w.lights[0].intensity, kIntensity * (1.0 - t * t * (3.0 - 2.0 * t)));
    EXPECT_EQ(w.lights[0].intensity, kIntensity * fade_at(d));
    EXPECT_GT(w.lights[0].intensity, 0.0);
    EXPECT_LT(w.lights[0].intensity, kIntensity);
    EXPECT_EQ(w.lights[1].intensity, kIntensity * 1.0);
    EXPECT_EQ(w.lights[0].position, (Vec3{10.0 + d - 500.0, -500.0, -500.0}));
}

TEST(TorpedoFeed, BeyondCullBuildsNoLight) {
    World w;
    w.ctx.eye = Vec3{0.0, 0.0, 0.0};
    w.torp({kCull, 0.0, 0.0}, {1.0, 0.0, 0.0});        // at: culled
    w.torp({0.0, 200.0, 0.0}, {1.0, 0.0, 0.0});        // beyond: culled
    w.run();
    // The descriptors are not culled; the lights are.
    EXPECT_EQ(w.torps.size(), 2u);
    EXPECT_TRUE(w.lights.empty());
}

TEST(TorpedoFeed, NoEyeMeansFullIntensity) {
    World w;
    w.torp({0.0, 5000.0, 0.0}, {1.0, 0.0, 0.0});
    w.run();
    ASSERT_EQ(w.lights.size(), 1u);
    EXPECT_EQ(w.lights[0].intensity, kIntensity * 1.0);
}

TEST(TorpedoFeed, NoViewDrawsNothing) {
    World w;
    w.ctx.view = -1;
    w.torp({0.0, 0.0, 0.0}, {1.0, 0.0, 0.0});
    w.m.torpedoes().add(-1, -1);  // no visual, no slot: never read
    w.run();
    EXPECT_TRUE(w.torps.empty());
    EXPECT_TRUE(w.lights.empty());
}

TEST(TorpedoFeed, SkipReasonsHaveNames) {
    const char* want[] = {"rows",           "unrepresentable", "no_visual",
                          "transform",      "containing_set",  "frames",
                          "c_int",          "error"};
    ASSERT_EQ(std::size(want), static_cast<size_t>(TorpedoSkip::kCount));
    for (size_t i = 0; i < std::size(want); ++i)
        EXPECT_STREQ(torpedo_skip_name(static_cast<TorpedoSkip>(i)), want[i]);
}

TEST(TorpedoFeed, RowCountMismatchCountsTheEntriesWithNoRow) {
    World w;
    w.torp({0.0, 0.0, 0.0}, {1.0, 0.0, 0.0});
    w.ctx.expected_rows = 3;
    w.run();
    EXPECT_EQ(w.torps.size(), 1u);  // every row still drawn
    EXPECT_EQ(w.skipped(TorpedoSkip::Rows), 2);
    EXPECT_EQ(w.total_skipped(), 2);
    w.ctx.expected_rows = 1;
    w.run();
    EXPECT_EQ(w.torps.size(), 1u);
    EXPECT_EQ(w.total_skipped(), 0);  // reset per build
}

// Every skip reason on hand-built rows: three torpedoes (A, B, C) in view,
// each with its light; only B is broken, so the frame is A's and C's
// descriptors and lights exactly as built without the break, and the one
// reason is counted. ("error" has no row state that raises it.)
TEST(TorpedoFeed, SkippedItemDropsOnlyItself) {
    struct Case {
        const char* name;
        TorpedoSkip why;
        std::optional<TorpField> field;
    };
    const Case cases[] = {
        {"unrepresentable _age", TorpedoSkip::Unrepresentable, TorpField::_age},
        {"unrepresentable _velocity", TorpedoSkip::Unrepresentable,
         TorpField::_velocity},
        {"unrepresentable _containing_set", TorpedoSkip::Unrepresentable,
         TorpField::_containing_set},
        {"no_visual", TorpedoSkip::NoVisual, std::nullopt},
        {"transform", TorpedoSkip::Transform, std::nullopt},
        {"containing_set", TorpedoSkip::ContainingSet, std::nullopt},
        {"frames", TorpedoSkip::Frames, std::nullopt},
        {"c_int", TorpedoSkip::CInt, std::nullopt},
    };
    for (const Case& c : cases) {
        SCOPED_TRACE(c.name);
        World w;
        w.ctx.expected_rows = 3;
        TorpedoVisual pv = photon_visual();
        if (c.why == TorpedoSkip::CInt) pv.id = int64_t{1} << 31;
        int64_t gone_set = -3;
        if (c.why == TorpedoSkip::ContainingSet)
            gone_set = w.add_set(1, {0.0, 0.0, 0.0});
        if (c.why == TorpedoSkip::Frames)
            gone_set = w.m.register_row(Kind::Set);  // not in ctx.frames
        w.torp({1.0, 0.0, 0.0}, {1.0, 0.0, 0.0});
        int64_t b = -1;
        if (c.why == TorpedoSkip::NoVisual) {
            auto [i, g] = w.store.alloc();
            b = w.m.torpedoes().add(i, g);
            w.m.torpedoes().set_v(b, TorpField::_velocity, true,
                                  {1.0, 0.0, 0.0});
            w.m.set_torpedo_ref(b, TorpField::_containing_set, w.set);
        } else {
            b = w.torp({2.0, 0.0, 0.0}, {1.0, 0.0, 0.0}, gone_set, &pv);
        }
        w.torp({3.0, 0.0, 0.0}, {1.0, 0.0, 0.0});
        // The frame without B: A and C built alone.
        World clean;
        clean.torp({1.0, 0.0, 0.0}, {1.0, 0.0, 0.0});
        clean.torp({3.0, 0.0, 0.0}, {1.0, 0.0, 0.0});
        clean.run();
        ASSERT_EQ(clean.torps.size(), 2u);
        ASSERT_EQ(clean.lights.size(), 2u);
        if (c.field) w.m.torpedoes().set_unrepresentable(b, *c.field);
        if (c.why == TorpedoSkip::Transform) {
            // B's store slot freed under it.
            const auto& rows = w.m.torpedoes().rows();
            const TorpedoRow& rb = rows[1];
            w.store.free(static_cast<uint32_t>(rb.xform_index),
                         static_cast<uint32_t>(rb.xform_gen));
        }
        if (c.why == TorpedoSkip::ContainingSet) w.m.unregister_row(gone_set);
        w.run();
        ASSERT_EQ(w.torps.size(), 2u);
        ASSERT_EQ(w.lights.size(), 2u);
        for (size_t k = 0; k < 2; ++k) {
            EXPECT_EQ(w.torps[k].position, clean.torps[k].position);
            EXPECT_EQ(w.torps[k].core_color, clean.torps[k].core_color);
            EXPECT_EQ(w.torps[k].glow_color, clean.torps[k].glow_color);
            EXPECT_EQ(w.torps[k].flares_color, clean.torps[k].flares_color);
            EXPECT_EQ(w.torps[k].forward, clean.torps[k].forward);
            EXPECT_EQ(w.torps[k].age, clean.torps[k].age);
            EXPECT_EQ(w.torps[k].visual->id, clean.torps[k].visual->id);
            EXPECT_TRUE(same(w.lights[k], clean.lights[k]));
        }
        EXPECT_EQ(w.skipped(c.why), 1);
        EXPECT_EQ(w.total_skipped(), 1);
    }
}

TEST(TorpedoFeed, DroppedRowsAreSkipped) {
    World w;
    const int64_t a = w.torp({1.0, 0.0, 0.0}, {1.0, 0.0, 0.0});
    w.torp({2.0, 0.0, 0.0}, {1.0, 0.0, 0.0});
    w.m.torpedoes().drop(a);
    w.ctx.expected_rows = 1;
    w.run();
    ASSERT_EQ(w.torps.size(), 1u);
    EXPECT_EQ(w.torps[0].position, (Vec3{2.0, 0.0, 0.0}));
}

// _budgeted_dynamic_lights, transcribed: the reference the native slicing
// is pinned against (group, index) for (group, index).
static std::vector<LightPick> python_budget(std::size_t ne, std::size_t nt,
                                            std::size_t nm,
                                            const LightBudget& b) {
    auto slice = [](int64_t n, int64_t a, int64_t z) {
        auto norm = [n](int64_t x) {
            if (x < 0) x += n;
            if (x < 0) x = 0;
            if (x > n) x = n;
            return x;
        };
        return std::pair<int64_t, int64_t>{norm(a), norm(z)};
    };
    const int64_t n[3] = {static_cast<int64_t>(ne), static_cast<int64_t>(nt),
                          static_cast<int64_t>(nm)};
    const int64_t bud[3] = {b.explosions, b.torpedoes, b.emitters};
    std::vector<LightPick> out;
    for (int g = 0; g < 3; ++g) {
        auto [a, z] = slice(n[g], 0, bud[g]);
        for (int64_t i = a; i < z; ++i)
            out.push_back({g, static_cast<std::size_t>(i)});
    }
    for (int g = 0; g < 3; ++g) {
        const int64_t room = b.cap - static_cast<int64_t>(out.size());
        if (room <= 0) break;
        auto [a, z] = slice(n[g], bud[g], bud[g] + room);
        for (int64_t i = a; i < z; ++i)
            out.push_back({g, static_cast<std::size_t>(i)});
    }
    return out;
}

TEST(Budget, SlicingMatchesPython) {
    const LightBudget stock;
    // Torpedoes overflow their 10 and emitters leave room: the spill hands
    // the room to torpedoes, AFTER every emitter.
    {
        const auto got = budget_lights(3, 25, 30, stock);
        ASSERT_EQ(got.size(), 3u + 25u + 30u);
        EXPECT_EQ(got[3], (LightPick{1, 0}));
        EXPECT_EQ(got[13], (LightPick{2, 0}));
        EXPECT_EQ(got[43], (LightPick{1, 10}));
        EXPECT_EQ(got.back(), (LightPick{1, 24}));
        EXPECT_EQ(got, python_budget(3, 25, 30, stock));
    }
    // Everything overflows: capped at 64, emitters' spill gets nothing.
    {
        const auto got = budget_lights(15, 70, 50, stock);
        ASSERT_EQ(got.size(), 64u);
        EXPECT_EQ(got, python_budget(15, 70, 50, stock));
        EXPECT_EQ(got[59], (LightPick{2, 39}));
        EXPECT_EQ(got[60], (LightPick{0, 10}));   // explosions spill first
        EXPECT_EQ(got[63], (LightPick{0, 13}));
    }
    // A sweep, including budgets past the cap and negative (Python slice)
    // budgets.
    for (const LightBudget b : {stock, LightBudget{5, 2, 2, 2},
                                LightBudget{64, 0, 0, 0},
                                LightBudget{64, -2, 3, 70},
                                LightBudget{0, 10, 10, 40},
                                LightBudget{-1, 10, 10, 40}})
        for (std::size_t ne : {0u, 1u, 12u})
            for (std::size_t nt : {0u, 9u, 40u})
                for (std::size_t nm : {0u, 39u, 80u})
                    EXPECT_EQ(budget_lights(ne, nt, nm, b),
                              python_budget(ne, nt, nm, b))
                        << b.cap << " " << b.explosions << " " << b.torpedoes
                        << " " << b.emitters << " / " << ne << " " << nt
                        << " " << nm;
}
