// first_blocker (beam_block.h) with FAKE trace hooks: the C++ port of
// tests/unit/test_beam_blockers.py, case for case and number for number.
// Shooter at the origin, target 100 GU up +Y, aim +Y, contact 95. The fake
// trace hits a chosen instance at a chosen t, as the Python test's
// monkeypatched host_io.ray_trace_mesh does.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>
#include <optional>
#include <unordered_map>
#include <vector>

#include "dauntless/combat/beam_block.h"
#include "dauntless/combat/beam_geometry.h"
#include "dauntless/combat/mirror.h"
#include "dauntless/transform_store.h"

using namespace dauntless::combat;
using dauntless::TransformStore;

namespace {

const Vec3 kEmitter{0.0, 0.0, 0.0};
const Vec3 kAim{0.0, 1.0, 0.0};
constexpr double kContact = 95.0;

struct World {
    TransformStore store;
    Mirror m{store};
    int64_t next_id = 1;
    uint32_t next_iid = 1;
    int64_t set = -1;
    std::unordered_map<int64_t, InstanceRef> iids;
    std::unordered_map<int64_t, std::optional<Vec3>> view_offsets;
    std::vector<int64_t> ships;
    std::vector<BeamPlanet> planets;
    std::unordered_map<uint32_t, double> hits;  // instance index -> t
    std::vector<uint32_t> traced;               // instance indices traced
    TraceHooks hooks;
    bool npc_shields_off = false;
    int64_t player = -1;
    int64_t shooter = -1, target = -1;

    World() {
        m.set_global_f(Global::SHIELD_ELLIPSOID_AXIS_SCALE, std::sqrt(3.0));
        set = m.register_row(Kind::Set);
        view_offsets[set] = std::nullopt;
        hooks.translation = [](InstanceId id) -> std::optional<Vec3> {
            if (id.generation != 1) return std::nullopt;
            return Vec3{0.0, 0.0, 0.0};
        };
        hooks.trace = [this](InstanceId id, const float o[3], const float d[3],
                             float max_dist) -> std::optional<TraceHit> {
            traced.push_back(id.index);
            const auto it = hits.find(id.index);
            if (it == hits.end() || it->second > max_dist) return std::nullopt;
            const float t = static_cast<float>(it->second);
            return TraceHit{{o[0] + d[0] * t, o[1] + d[1] * t, o[2] + d[2] * t},
                            {0.0f, -1.0f, 0.0f},
                            t};
        };
        shooter = add({0.0, 0.0, 0.0}, 5.0, false);
        target = add({0.0, 100.0, 0.0}, 5.0, false);
    }

    // A ShipClass in `set`, as ShipClass_Create + SetRadius + AddObjectToSet.
    int64_t add(const Vec3& at, double radius = 5.0, bool instance = true) {
        auto [i, g] = store.alloc();
        store.set_position(i, g, at[0], at[1], at[2]);
        const int64_t h = m.register_row(Kind::Object, i, g, next_id++);
        m.set_i(h, Field::is_ship_class, 1);
        m.set_i(h, Field::has_real_is_dead, 1);
        m.set_i(h, Field::has_real_get_shields, 1);
        m.set_i(h, Field::has_cloak_getter, 1);
        m.set_f(h, Field::o_radius, radius);
        m.set_f(h, Field::_scale, 1.0);
        m.set_ref(h, Field::_containing_set, set);
        ships.push_back(h);
        if (instance) iids[h] = InstanceRef{false, {next_iid++, 1}};
        return h;
    }

    void hit(int64_t h, double t) { hits[iids.at(h).id.index] = t; }

    // test_beam_blockers._shield: a generator with every face up, and a hull
    // box ((0, 0, 0), (4, 4, 4)).
    void shield(int64_t h) {
        const int64_t sh = m.register_row(Kind::Subsystem);
        m.set_i(sh, Field::has_shields, 1);
        m.set_i(sh, Field::_is_on, 1);
        m.set_ref(h, Field::_shield_subsystem, sh);
        m.set_fv(h, Field::_shield_hull_box_center, {0.0, 0.0, 0.0});
        m.set_fv(h, Field::_shield_hull_box_half, {4.0, 4.0, 4.0});
        m.set_i(h, Field::hull_box_set, 1);
    }

    BeamPlanet& planet(const Vec3& at, double radius = 5.0) {
        BeamPlanet p;
        p.set = set;
        p.centre = at;
        p.radius = radius;
        planets.push_back(p);
        return planets.back();
    }

    std::optional<BeamBlocker> run() {
        const BeamBlockInputs in{m,      hooks,  iids,  view_offsets,
                                 npc_shields_off, player, ships, planets};
        return first_blocker(in, shooter, target, kEmitter, kAim, kContact);
    }
};

double norm(const Vec3& p) {
    return std::sqrt(p[0] * p[0] + p[1] * p[1] + p[2] * p[2]);
}

}  // namespace

// ── Task 1's cases, one for one ─────────────────────────────────────────────

TEST(BeamBlock, ShipInLineBlocks) {
    World w;
    const int64_t b = w.add({0.0, 50.0, 0.0});
    w.hit(b, 48.0);
    const auto r = w.run();
    ASSERT_TRUE(r.has_value());
    EXPECT_EQ(r->kind, BeamBlocker::Kind::Ship);
    EXPECT_EQ(r->handle, b);
    EXPECT_EQ(r->planet, -1);
    EXPECT_EQ(r->dist, 48.0);
    EXPECT_EQ(r->point, (Vec3{0.0, 48.0, 0.0}));
    ASSERT_TRUE(r->normal.has_value());
    EXPECT_EQ(*r->normal, (Vec3{0.0, -1.0, 0.0}));
    EXPECT_FALSE(r->bubble.has_value());
    EXPECT_EQ(r->tier, BeamBlocker::Tier::Mesh);
}

TEST(BeamBlock, GrazeDoesNotBlock) {
    World w;
    w.add({3.0, 50.0, 0.0}, 5.0);
    EXPECT_FALSE(w.run().has_value());
    // The mesh WAS asked (the sphere is crossed), and missed; the sphere
    // tier never counts.
    EXPECT_EQ(w.traced.size(), 1u);
}

TEST(BeamBlock, NoInstanceNeverBlocks) {
    World w;
    w.add({0.0, 50.0, 0.0}, 5.0, false);
    EXPECT_FALSE(w.run().has_value());
    EXPECT_TRUE(w.traced.empty());
}

TEST(BeamBlock, ShieldedBlocksAtBubble) {
    World w;
    const int64_t b = w.add({0.0, 50.0, 0.0});
    w.shield(b);
    ASSERT_TRUE(shields_block(w.m, b, false, -1));
    const auto expect = shield_bubble_entry(w.m, b, kEmitter, kAim, kContact);
    ASSERT_TRUE(expect.has_value());
    const auto r = w.run();
    ASSERT_TRUE(r.has_value());
    EXPECT_EQ(r->handle, b);
    EXPECT_EQ(r->tier, BeamBlocker::Tier::Bubble);
    ASSERT_TRUE(r->bubble.has_value());
    EXPECT_EQ(*r->bubble, *expect);
    EXPECT_EQ(r->dist, norm(*expect));
    // The mesh missed (no hit for its instance): the point is the bubble.
    EXPECT_EQ(r->point, *expect);
    EXPECT_FALSE(r->normal.has_value());
}

TEST(BeamBlock, EmitterInsideBubbleMeshOnly) {
    World w;
    const int64_t b = w.add({0.0, 2.0, 0.0});
    w.shield(b);
    ASSERT_FALSE(shield_bubble_entry(w.m, b, kEmitter, kAim, kContact));
    EXPECT_FALSE(w.run().has_value());
    // ...but the mesh was traced, and a hit there blocks as a mesh hit.
    EXPECT_EQ(w.traced.size(), 1u);
    w.hit(b, 1.5);
    const auto r = w.run();
    ASSERT_TRUE(r.has_value());
    EXPECT_EQ(r->tier, BeamBlocker::Tier::Mesh);
    EXPECT_EQ(r->dist, 1.5);
}

TEST(BeamBlock, BehindTargetNever) {
    World w;
    const int64_t b = w.add({0.0, 150.0, 0.0});
    w.hit(b, 148.0);
    EXPECT_FALSE(w.run().has_value());
    EXPECT_TRUE(w.traced.empty());  // the broadphase rejected it
}

TEST(BeamBlock, ShooterAndTargetExcluded) {
    World w;
    w.iids[w.shooter] = InstanceRef{false, {90, 1}};
    w.iids[w.target] = InstanceRef{false, {91, 1}};
    w.hits[90] = 1.0;
    w.hits[91] = 1.0;
    EXPECT_FALSE(w.run().has_value());
    EXPECT_TRUE(w.traced.empty());
}

TEST(BeamBlock, DeadAndHiddenExcluded) {
    World w;
    const int64_t d = w.add({0.0, 40.0, 0.0});
    const int64_t h = w.add({0.0, 50.0, 0.0});
    w.hit(d, 38.0);
    w.hit(h, 48.0);
    w.m.set_i(d, Field::_dead, 1);
    w.m.set_i(h, Field::_hidden, 1);
    EXPECT_FALSE(w.run().has_value());
    EXPECT_TRUE(w.traced.empty());
}

TEST(BeamBlock, OtherSetNever) {
    World w;
    const int64_t other = w.m.register_row(Kind::Set);
    const int64_t b = w.add({0.0, 50.0, 0.0});
    w.hit(b, 48.0);
    w.m.set_ref(b, Field::_containing_set, other);
    EXPECT_FALSE(w.run().has_value());
    EXPECT_TRUE(w.traced.empty());
}

TEST(BeamBlock, NearestWinsTieEarlier) {
    World w;
    const int64_t far = w.add({0.0, 40.0, 0.0});
    const int64_t near = w.add({0.0, 30.0, 0.0});
    w.hit(far, 40.0);
    w.hit(near, 30.0);
    auto r = w.run();
    ASSERT_TRUE(r.has_value());
    EXPECT_EQ(r->handle, near);
    const int64_t a = w.add({0.0, 60.0, 0.0});
    const int64_t c = w.add({0.0, 60.0, 0.0});
    w.hits.clear();
    w.hit(a, 60.0);
    w.hit(c, 60.0);
    r = w.run();
    ASSERT_TRUE(r.has_value());
    EXPECT_EQ(r->handle, a);
}

TEST(BeamBlock, PlanetSphereNoInstance) {
    World w;
    w.planet({0.0, 60.0, 0.0});
    const auto r = w.run();
    ASSERT_TRUE(r.has_value());
    EXPECT_EQ(r->kind, BeamBlocker::Kind::Planet);
    EXPECT_EQ(r->handle, -1);
    EXPECT_EQ(r->planet, 0);
    EXPECT_EQ(r->dist, 55.0);
    EXPECT_EQ(r->point, (Vec3{0.0, 55.0, 0.0}));
    EXPECT_FALSE(r->normal.has_value());
    EXPECT_FALSE(r->bubble.has_value());
    EXPECT_EQ(r->tier, BeamBlocker::Tier::Sphere);
}

TEST(BeamBlock, PlanetMesh) {
    World w;
    w.planet({0.0, 60.0, 0.0}).iid = InstanceId{77, 1};
    w.hits[77] = 54.0;
    const auto r = w.run();
    ASSERT_TRUE(r.has_value());
    EXPECT_EQ(r->kind, BeamBlocker::Kind::Planet);
    EXPECT_EQ(r->dist, 54.0);
    EXPECT_EQ(r->point, (Vec3{0.0, 54.0, 0.0}));
    ASSERT_TRUE(r->normal.has_value());
    EXPECT_EQ(r->tier, BeamBlocker::Tier::Mesh);
}

// test_beam_blockers.test_hidden_planet_never_blocks: spec section 4.1,
// hidden objects never block -- sphere tier and mesh tier, never traced.
TEST(BeamBlock, HiddenPlanetNeverBlocks) {
    World w;
    w.planet({0.0, 60.0, 0.0}).hidden = true;
    EXPECT_FALSE(w.run().has_value());
    w.planets.back().iid = InstanceId{77, 1};
    w.hits[77] = 54.0;
    EXPECT_FALSE(w.run().has_value());
    EXPECT_TRUE(w.traced.empty());
}

TEST(BeamBlock, RockBlocks) {
    World w;
    const int64_t rk = w.add({0.0, 50.0, 0.0});
    w.m.set_i(rk, Field::is_rock, 1);
    w.hit(rk, 47.0);
    const auto r = w.run();
    ASSERT_TRUE(r.has_value());
    EXPECT_EQ(r->kind, BeamBlocker::Kind::Ship);
    EXPECT_EQ(r->handle, rk);
}

// ── The planet branches the Task 1 review deferred ──────────────────────────

TEST(BeamBlock, PlanetBroadphaseReject) {
    World w;
    w.planet({50.0, 60.0, 0.0}).iid = InstanceId{78, 1};
    w.hits[78] = 54.0;  // would hit, were it ever traced
    EXPECT_FALSE(w.run().has_value());
    EXPECT_TRUE(w.traced.empty());
}

TEST(BeamBlock, PlanetInstanceMeshMissDoesNotBlock) {
    World w;
    w.planet({0.0, 60.0, 0.0}).iid = InstanceId{77, 1};
    // No hit: the sphere entry (55) would block, but with an instance only
    // a mesh hit counts.
    EXPECT_FALSE(w.run().has_value());
    ASSERT_EQ(w.traced.size(), 1u);
    EXPECT_EQ(w.traced[0], 77u);
    // A bad instance value: the trace raises inside the try, same answer.
    w.planets[0].iid.reset();
    w.planets[0].iid_bad = true;
    EXPECT_FALSE(w.run().has_value());
}

TEST(BeamBlock, EmitterInsidePlanetSphereDoesNotBlock) {
    World w;
    w.planet({0.0, 2.0, 0.0});
    EXPECT_FALSE(w.run().has_value());
}

// ── Further rules of the port ───────────────────────────────────────────────

TEST(BeamBlock, ATieWithTheTargetGoesToTheTarget) {
    World w;
    const int64_t b = w.add({0.0, 95.0, 0.0});
    w.hit(b, 95.0);
    EXPECT_FALSE(w.run().has_value());
}

TEST(BeamBlock, ShieldedMeshHitKeepsTheBubbleDistance) {
    World w;
    const int64_t b = w.add({0.0, 50.0, 0.0});
    w.shield(b);
    w.hit(b, 47.0);
    const auto expect = shield_bubble_entry(w.m, b, kEmitter, kAim, kContact);
    ASSERT_TRUE(expect.has_value());
    const auto r = w.run();
    ASSERT_TRUE(r.has_value());
    EXPECT_EQ(r->tier, BeamBlocker::Tier::Bubble);
    EXPECT_EQ(r->dist, norm(*expect));   // the bubble's distance
    EXPECT_EQ(r->point, (Vec3{0.0, 47.0, 0.0}));  // the hull point
    ASSERT_TRUE(r->normal.has_value());
    EXPECT_EQ(*r->bubble, *expect);
}

TEST(BeamBlock, ShieldedBubbleNotNearerIsSkippedWhole) {
    World w;
    const int64_t first = w.add({0.0, 30.0, 0.0});
    w.hit(first, 30.0);
    const int64_t s = w.add({0.0, 50.0, 0.0});
    w.shield(s);
    w.hit(s, 10.0);  // nearer than 30, but the bubble (~43) is not: no mesh
    const auto r = w.run();
    ASSERT_TRUE(r.has_value());
    EXPECT_EQ(r->handle, first);
    EXPECT_EQ(r->dist, 30.0);
}

TEST(BeamBlock, BadShipInstanceDoesNotBlock) {
    World w;
    const int64_t b = w.add({0.0, 50.0, 0.0});
    w.hit(b, 48.0);
    w.iids[b].bad = true;
    EXPECT_FALSE(w.run().has_value());
    EXPECT_TRUE(w.traced.empty());
}

TEST(BeamBlock, TheViewOffsetShiftsTheTraceAndBack) {
    World w;
    const int64_t b = w.add({0.0, 50.0, 0.0});
    w.hit(b, 48.0);
    w.view_offsets[w.set] = Vec3{0.0, 1000.0, 0.0};
    const auto r = w.run();
    ASSERT_TRUE(r.has_value());
    // In at (0, 1000, 0), hit at (0, 1048, 0), back out by -1000.
    EXPECT_EQ(r->point, (Vec3{0.0, 48.0, 0.0}));
}

TEST(BeamBlock, PlanetsOnlyInTheShooterSetAndNeverTheTarget) {
    World w;
    const int64_t other = w.m.register_row(Kind::Set);
    w.planet({0.0, 60.0, 0.0}).set = other;
    EXPECT_FALSE(w.run().has_value());
    w.planets[0].set = w.set;
    w.planets[0].handle = w.target;
    EXPECT_FALSE(w.run().has_value());
    w.planets[0].handle = w.shooter;
    EXPECT_FALSE(w.run().has_value());
    // No shooter set: planet_rows(None) is empty.
    w.planets[0].handle = -1;
    w.planets[0].set = -1;
    w.m.set_ref(w.shooter, Field::_containing_set, -1);
    EXPECT_FALSE(w.run().has_value());
}

TEST(BeamBlock, ShipPlanetNearestWins) {
    World w;
    w.planet({0.0, 60.0, 0.0});  // sphere at 55
    const int64_t b = w.add({0.0, 70.0, 0.0});
    w.hit(b, 68.0);
    auto r = w.run();
    ASSERT_TRUE(r.has_value());
    EXPECT_EQ(r->kind, BeamBlocker::Kind::Planet);
    w.hit(b, 55.0);  // a tie: the ship came first
    r = w.run();
    ASSERT_TRUE(r.has_value());
    EXPECT_EQ(r->kind, BeamBlocker::Kind::Ship);
}

// ── NeedPython: what only Python can answer ─────────────────────────────────

TEST(BeamBlock, NeedPythonForAStubIsDead) {
    World w;
    const int64_t b = w.add({0.0, 50.0, 0.0});
    w.m.set_i(b, Field::has_real_is_dead, 0);
    EXPECT_THROW(w.run(), NeedPython);
}

TEST(BeamBlock, NeedPythonForAnUnnameableSet) {
    World w;
    const int64_t b = w.add({0.0, 50.0, 0.0});
    w.m.set_ref(b, Field::_containing_set, kRefUnrepresentable);
    EXPECT_THROW(w.run(), NeedPython);
}

TEST(BeamBlock, NeedPythonForTheShooterWithNoRow) {
    World w;
    w.m.unregister_row(w.shooter);
    EXPECT_THROW(w.run(), NeedPython);
}

TEST(BeamBlock, NeedPythonForACandidateWithNoRow) {
    World w;
    w.ships.push_back(-1);
    EXPECT_THROW(w.run(), NeedPython);
}

TEST(BeamBlock, NeedPythonForANonShipClass) {
    World w;
    const int64_t b = w.add({0.0, 50.0, 0.0});
    w.m.set_i(b, Field::is_ship_class, 0);
    EXPECT_THROW(w.run(), NeedPython);
}

TEST(BeamBlock, NeedPythonForAnUnnameableShieldRef) {
    World w;
    const int64_t b = w.add({0.0, 50.0, 0.0});
    w.m.set_ref(b, Field::_shield_subsystem, kRefUnrepresentable);
    EXPECT_THROW(w.run(), NeedPython);
}

TEST(BeamBlock, NeedPythonForAnUnnameableCloakRef) {
    World w;
    const int64_t b = w.add({0.0, 50.0, 0.0});
    w.shield(b);
    w.m.set_ref(b, Field::_cloaking_subsystem, kRefUnrepresentable);
    EXPECT_THROW(w.run(), NeedPython);
}

TEST(BeamBlock, NeedPythonForAZeroBubbleSemiAxis) {
    World w;
    const int64_t b = w.add({0.0, 50.0, 0.0});
    w.shield(b);
    w.m.set_fv(b, Field::_shield_hull_box_half, {4.0, 1e-300, 4.0});
    w.m.set_f(b, Field::_scale, 1e-30);
    EXPECT_THROW(w.run(), NeedPython);
}

TEST(BeamBlock, NeedPythonForAnInstanceWithNoViewOffset) {
    World w;
    const int64_t b = w.add({0.0, 50.0, 0.0});
    w.view_offsets.erase(w.set);
    EXPECT_THROW(w.run(), NeedPython);
    // Without an instance the offset is never read.
    w.iids.erase(b);
    EXPECT_FALSE(w.run().has_value());
    // A planet with an instance reads it too; one without does not.
    w.planet({0.0, 60.0, 0.0});
    EXPECT_TRUE(w.run().has_value());
    w.planets[0].iid = InstanceId{77, 1};
    EXPECT_THROW(w.run(), NeedPython);
}

TEST(BeamBlock, EarlySkipsAreNeverAskedAbout) {
    World w;
    // Dead, hidden, in another set, out of reach: each has a field the
    // mirror could not answer past the skip, and none is asked.
    const int64_t dead = w.add({0.0, 50.0, 0.0});
    w.m.set_i(dead, Field::_dead, 1);
    w.m.set_ref(dead, Field::_shield_subsystem, kRefUnrepresentable);
    const int64_t hid = w.add({0.0, 50.0, 0.0});
    w.m.set_i(hid, Field::_hidden, 1);
    w.m.set_i(hid, Field::is_ship_class, 0);
    const int64_t other = w.m.register_row(Kind::Set);
    const int64_t away = w.add({0.0, 50.0, 0.0});
    w.m.set_ref(away, Field::_containing_set, other);
    w.m.set_i(away, Field::is_ship_class, 0);
    const int64_t behind = w.add({0.0, 150.0, 0.0});
    w.m.set_ref(behind, Field::_shield_subsystem, kRefUnrepresentable);
    w.view_offsets.erase(w.set);
    EXPECT_FALSE(w.run().has_value());
}
