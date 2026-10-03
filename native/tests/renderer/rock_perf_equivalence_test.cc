// native/tests/renderer/rock_perf_equivalence_test.cc
// Rock-fields CPU work (2026-10-03, .superpowers/sdd/rock-perf/brief.md):
// NearField::stream / step / build and MidField::build were made cheaper
// WITHOUT changing a byte of what they produce. These digests were recorded
// from the implementation BEFORE that work (feat/rock-fields ee82c35c) over
// representative runs -- the Beol 4 inside load, cap-binding dials, dial and
// source changes mid-run, origin/anchor shifts -- and every later
// implementation must reproduce them exactly: the drawn bins (bytes and
// order), the contacts (fields and order), the streamed rock set and the
// stats.
//
// A digest is FNV-1a 64 over raw float bytes, so it is tied to this
// toolchain's floating point. If a compiler/flag change (never an algorithm
// change) moves one, re-record it by checking out ee82c35c's rock_near.cc /
// rock_mid.cc, running this test, and pasting the printed values.
//
// Rock fade (2026-10-03): the builds now split their impostors into a
// solid/dithered list and a translucent list without changing any item. The
// digests below hash the two lists MERGED back into the one list the builds
// emitted before (rock_fade_merge.h), so these recorded values still pin
// every byte and the order; the split itself is pinned by
// NearBuild.OuterFadeBillboardsAreTranslucent and
// MidFade.EveryFadeIsTranslucentAndDrawsFarToNear.
#include <gtest/gtest.h>
#include <algorithm>
#include <cinttypes>
#include <cstdio>
#include <tuple>
#include <vector>
#include <renderer/glm_exact.h>
#include "rock_fade_merge.h"
#include "rock_scenario.h"

using namespace renderer;
using rock_scenario::Digest;

namespace {

// `view`: the build's camera -- the merge orders by the distance the build
// sorted on (NearField::build's scalar length from inverse(view)'s eye).
void digest_near_out(Digest& d, const rockfield::NearOutput& o, const glm::mat4& view) {
    d.pod(o.mesh_count); d.pod(o.billboard_count);
    d.pod(o.meshes.size());
    for (const auto& b : o.meshes) {
        d.pod(b.family); d.pod(b.slot); d.pod(b.lod); d.pod(b.items.size());
        d.bytes(b.items.data(), b.items.size() * sizeof(minors::InstanceGpu));
    }
    const glm::vec3 eye = glm::vec3(glm::inverse(view)[3]);
    const auto boards = rock_fade_merge::merge(o.billboards, o.billboards_fading, [eye](const glm::vec3& c) {
        const float ex = c.x - eye.x, ey = c.y - eye.y, ez = c.z - eye.z;
        return std::sqrt(glm_exact::dot3(ex, ey, ez, ex, ey, ez));
    });
    d.pod(boards.size());
    for (const auto& b : boards) {
        d.pod(b.rock); d.pod(b.items.size());
        d.bytes(b.items.data(), b.items.size() * sizeof(far::ImpostorGpu));
    }
}

// The streamed set, order-independent (the cell map's order is not output).
void digest_stream(Digest& d, const rockfield::NearField& f) {
    const auto st = f.stats();
    d.pod(st.cells); d.pod(st.small); d.pod(st.large); d.pod(st.ghosted);
    for (auto cls : {rockfield::NearClass::Small, rockfield::NearClass::Large}) {
        std::vector<std::tuple<std::uint64_t, double, double, double, float, int>> v;
        f.for_each(cls, [&](std::uint64_t key, const rockfield::NearRock& r) {
            v.emplace_back(key, r.pos_sys.x, r.pos_sys.y, r.pos_sys.z, r.radius, r.rock);
        });
        std::sort(v.begin(), v.end());
        d.pod(v.size());
        for (const auto& t : v) {
            d.pod(std::get<0>(t)); d.pod(std::get<1>(t)); d.pod(std::get<2>(t));
            d.pod(std::get<3>(t)); d.pod(std::get<4>(t)); d.pod(std::get<5>(t));
        }
    }
}

struct NearRun {
    std::uint64_t build = 0, contacts = 0, stream = 0;
    int contacts_large = 0, contacts_small = 0, builds = 0;
    int capped_steps = 0;   // steps whose large contacts hit max_shoves_per_frame
    std::uint64_t full_passes = 0;   // NearField::full_stream_passes() at the end
    int fading = 0;                  // translucent billboards built (the merge is exercised)
};

// One scripted flight. `fast` raises the speed (contacts, cell churn);
// `caps` makes the per-class instance caps and the per-step touch cap bind.
// `resend` re-pushes the SAME sources before every stream, as the host
// does live (far_set_frame every frame calls NearField::set_sources).
NearRun run_near(bool fast, bool caps, bool resend = false) {
    rockfield::NearField f;
    rockfield::NearDials dials;
    // Pinned to the near_* defaults in effect when these digests were
    // recorded (before the 2026-10-03 look retune), so the digests below do
    // not need re-recording when far_dials.py / rock_near.h's defaults move.
    dials.small.density = 0.008f; dials.small.mesh_gu = 20.0f;
    dials.large.density = 1.0f / 8000.0f; dials.large.mesh_gu = 50.0f;
    dials.large.billboard_gu = 60.0f;
    if (caps) {
        dials.small.max_instances = 60;
        dials.large.max_instances = 12;
        dials.small.density = 0.03f;    // dense enough that the touch cap binds
        dials.large.density = 2.0e-3f;
    }
    f.set_dials(dials);
    f.set_catalogue(rock_scenario::near_catalogue());
    f.set_sources({rock_scenario::beol4_field()});
    rockfield::NearStepInput sin;
    if (caps) sin.minor_dials.max_shoves_per_frame = 3;
    rockfield::NearBuildInput bin;
    bin.viewport_h = 1080.0f;
    rockfield::NearOutput out;
    Digest db, dc, ds;
    NearRun run;
    const glm::dvec3 anchor(1.0e5, -3.0e4, 250.0);   // system = view + anchor
    double distance = 0.0;
    glm::dvec3 offset(0.0);                           // a teleport adds to this
    for (int i = 0; i < 720; ++i) {
        const double gups = fast ? (i < 360 ? 60.0 : 140.0) : (i < 360 ? 6.0 : 25.0);
        distance += gups / 60.0;
        if (i == 600) offset += glm::dvec3(0.0, 35.0, 0.0);   // a hop past the hysteresis margin
        rock_scenario::Pose pose;
        pose.pos = glm::dvec3(40.0 * std::sin(0.3 * i / 60.0), -700.0 + distance,
                              15.0 * std::sin(0.5 * i / 60.0)) + offset;
        pose.fwd = rock_scenario::player_pose(i, gups).fwd;
        // pose.pos is SYSTEM space; view = system - anchor; the render origin
        // follows the player in 50 GU steps (as the host's floating origin
        // does); render = view - origin.
        const glm::dvec3 view_pos = pose.pos - anchor;
        const glm::dvec3 origin = glm::floor(view_pos / 50.0) * 50.0;
        const glm::dvec3 render = view_pos - origin;
        if (i == 100) f.set_sources({rock_scenario::beol4_field()});   // same: keeps cells
        if (i == 250) {                                                  // non-generator dial change
            rockfield::NearDials d2 = f.dials();
            d2.small.billboard_gu = 26.0f; d2.large.mesh_gu = 44.0f; d2.stream_margin_gu = 6.0f;
            f.set_dials(d2);
        }
        if (i == 480) {
            rockfield::NearDials d2 = f.dials();
            d2.small.billboard_gu = 30.0f; d2.stream_margin_gu = 10.0f; d2.fade_gu = 6.0f;
            f.set_dials(d2);
        }
        if (resend) f.set_sources({rock_scenario::beol4_field()});
        f.stream(pose.pos);
        sin.game_time = 50.0 + i / 60.0;
        sin.render_origin = origin;
        sin.anchor_sys = anchor;
        sin.shield_inflate = (i >= 200 && i < 420) ? 1.8f : 0.0f;
        if (i >= 450 && i < 455) sin.player.reset();
        else {
            sin.player = rock_scenario::galaxy_box(glm::vec3(render), pose.fwd);
            if (caps) sin.player->half_mu *= 3.0f;   // a wide box: many touches per step
        }
        f.step(sin);
        {
            const auto lc = f.drain_large_contacts();
            const auto sc = f.drain_small_contacts();
            run.contacts_large += static_cast<int>(lc.size());
            run.contacts_small += static_cast<int>(sc.size());
            if (static_cast<int>(lc.size()) == sin.minor_dials.max_shoves_per_frame) ++run.capped_steps;
            dc.pod(lc.size());
            for (const auto& c : lc) {
                dc.pod(c.point_view); dc.pod(c.normal); dc.pod(c.rock_centre_view);
                dc.pod(c.rock_radius); dc.pod(c.rel_speed); dc.pod(c.pen); dc.pod(c.key);
            }
            dc.pod(sc.size());
            for (const auto& c : sc) { dc.pod(c.point_view); dc.pod(c.radius); dc.pod(c.rel_speed); }
        }
        if (i % 120 == 7) {   // clear one cooldown now and then (Python's rearm)
            f.for_each(rockfield::NearClass::Large, [&](std::uint64_t key, const rockfield::NearRock&) {
                f.rearm(key);
            });
        }
        // The chase camera, in render space.
        rock_scenario::Pose rp{render, pose.fwd};
        rock_scenario::chase_camera(rp, bin.view, bin.proj);
        bin.render_origin = origin;
        bin.anchor_sys = anchor;
        bin.game_time = sin.game_time;
        f.build(bin, out);
        digest_near_out(db, out, bin.view);
        run.fading += out.billboard_fading_count;
        ++run.builds;
        if (i % 9 == 0) {   // a second camera: looking back, telephoto
            const glm::vec3 eye = glm::vec3(render) + glm::vec3(0, 0, 2.0f);
            bin.view = glm::lookAt(eye, eye - pose.fwd * 10.0f + glm::vec3(0.3f, 0, 0), glm::vec3(0, 0, 1));
            bin.proj = glm::perspective(glm::radians(20.0f), 1.0f, 0.1f, 1.0e5f);
            f.build(bin, out);
            digest_near_out(db, out, bin.view);
            ++run.builds;
        }
        if (i % 60 == 0) digest_stream(ds, f);
    }
    digest_stream(ds, f);
    run.build = db.h; run.contacts = dc.h; run.stream = ds.h;
    run.full_passes = f.full_stream_passes();
    return run;
}

void expect_near(const char* name, const NearRun& r, std::uint64_t build, std::uint64_t contacts,
                 std::uint64_t stream) {
    std::printf("[near equivalence] %s: build=0x%016" PRIx64 " contacts=0x%016" PRIx64
                " stream=0x%016" PRIx64 " (contacts large=%d small=%d, builds=%d)\n",
                name, r.build, r.contacts, r.stream, r.contacts_large, r.contacts_small, r.builds);
    EXPECT_EQ(r.build, build) << name << ": drawn near bins changed";
    EXPECT_EQ(r.contacts, contacts) << name << ": near contacts changed";
    EXPECT_EQ(r.stream, stream) << name << ": the streamed rock set changed";
}

}  // namespace

TEST(RockPerfEquivalence, NearSlowFlightMatchesTheRecordedDigests) {
    const NearRun r = run_near(/*fast=*/false, /*caps=*/false);
    EXPECT_GT(r.contacts_large + r.contacts_small, 0) << "the run must exercise contacts";
    EXPECT_GT(r.fading, 0) << "the run must build translucent billboards (the merge)";
    expect_near("slow", r, 0x32b35fece022b324ull, 0xdf39b4a12bf4af85ull, 0x8d90bab75baf5c86ull);
}

TEST(RockPerfEquivalence, NearFastFlightMatchesTheRecordedDigests) {
    const NearRun r = run_near(/*fast=*/true, /*caps=*/false);
    EXPECT_GT(r.contacts_large, 0);
    EXPECT_GT(r.contacts_small, 0);
    EXPECT_GT(r.fading, 0) << "the run must build translucent billboards (the merge)";
    expect_near("fast", r, 0x3c17112b6b47cbdaull, 0x9368168741730520ull, 0x9d8b4ece39601a8bull);
}

TEST(RockPerfEquivalence, NearCapsBindingMatchesTheRecordedDigests) {
    const NearRun r = run_near(/*fast=*/true, /*caps=*/true);
    EXPECT_GT(r.capped_steps, 0) << "the per-step touch cap must bind";
    expect_near("caps", r, 0x6a7ff5fc17713837ull, 0xefbcbac817d4349cull, 0x9e23d1b0ea412383ull);
}

// ---- Mid band ---------------------------------------------------------------
namespace {

void digest_mid_out(Digest& d, const rockfield::MidOutput& o, const glm::mat4& view) {
    const glm::vec3 eye = glm::vec3(glm::inverse(view)[3]);
    const auto sprites = rock_fade_merge::merge(o.sprites, o.sprites_fading,
                                                [eye](const glm::vec3& c) { return glm::length(c - eye); });
    d.pod(o.count); d.pod(o.tiles); d.pod(sprites.size());
    for (const auto& b : sprites) {
        d.pod(b.rock); d.pod(b.items.size());
        d.bytes(b.items.data(), b.items.size() * sizeof(far::ImpostorGpu));
    }
}

far::DiscSource small_cluster() {   // 2R < every tile: snaps at every level
    far::DiscSource s;
    s.id = 11; s.seed = 77u; s.shape = far::DiscSource::Shape::Sphere; s.view_space = true;
    s.centre = {1300.0, 450.0, -80.0};
    s.sphere_radius_gu = 60.0f; s.sphere_edge_frac = 0.3f;
    return s;
}

far::DiscSource noisy_belt() {
    far::DiscSource b;
    b.id = 12; b.seed = 5u;
    b.table = {{0.0f, 0.0f}, {3000.0f, 0.6f}, {9000.0f, 1.0f}, {20000.0f, 0.2f}};
    b.scale_height_min_gu = 1500.0f;
    b.noise_scale_gu = 4000.0f; b.noise_contrast = 0.8f; b.noise_octaves = 3;
    return b;
}

}  // namespace

namespace {
struct MidRun { std::uint64_t digest = 0; int sprites = 0, builds = 0; rockfield::MidCacheStats cache; int fading = 0; };
// `resend` re-pushes the SAME sources before every build, as the host does
// live (far_set_frame every frame calls MidField::set_sources).
MidRun run_mid(bool resend) {
    rockfield::MidField f;
    f.set_collections(rock_scenario::mid_collections());
    f.set_view_dirs(rock_scenario::view_dirs16());
    std::vector<far::DiscSource> sources{rock_scenario::beol4_field(), small_cluster()};
    f.set_sources(sources);
    // Pinned to the mid_in_lo_gu/mid_in_hi_gu defaults in effect when these
    // digests were recorded (before the 2026-10-03 look retune), so the
    // digests below do not need re-recording when far_dials.py / rock_mid.h's
    // defaults move.
    rockfield::MidDials pinned0;
    pinned0.in_lo_gu = 80.0f; pinned0.in_hi_gu = 150.0f;
    f.set_dials(pinned0);
    rockfield::MidBuildInput in;
    in.viewport_h = 1080.0f;
    rockfield::MidOutput out;
    Digest d;
    int sprites = 0, builds = 0, fading = 0;
    const glm::dvec3 anchor(-2.5e4, 1.2e4, -300.0);
    auto build_at = [&](const glm::dvec3& eye_sys, const glm::vec3& look_dir, float fov_deg,
                        const glm::dvec3& origin) {
        // view = system - anchor; render = view - origin
        const glm::vec3 eye(eye_sys - anchor - origin);
        in.view = glm::lookAt(eye, eye + look_dir, glm::vec3(0, 0, 1));
        in.proj = glm::perspective(glm::radians(fov_deg), 16.0f / 9.0f, 0.1f, 1.0e6f);
        in.render_origin = origin;
        in.anchor_sys = anchor;
        if (resend) f.set_sources(sources);
        f.build(in, out);
        digest_mid_out(d, out, in.view);
        sprites += out.count;
        fading += out.fading;
        ++builds;
    };
    // MidField's sources are in system coordinates (the fields sit around
    // the system origin); view = system - anchor, render = view - origin.
    for (int phase = 0; phase < 5; ++phase) {
        if (phase == 1) f.set_sources(sources);   // same
        if (phase == 2) {                                   // quarter tiles; the cap binds
            rockfield::MidDials m;
            m.in_lo_gu = 80.0f; m.in_hi_gu = 150.0f;        // pinned, see above
            m.l0_tile_gu /= 4.0f; m.l1_tile_gu /= 4.0f; m.l2_tile_gu /= 4.0f;
            m.max_sprites = 300; m.fill = 0.7f; m.sprite_scale = 1.3f;
            f.set_dials(m);
        }
        if (phase == 3) {                                   // sources and collections change
            f.set_dials(pinned0);
            sources = {noisy_belt(), small_cluster(), rock_scenario::beol4_field()};
            f.set_sources(sources);
            auto cols = rock_scenario::mid_collections();
            cols.resize(30);
            f.set_collections(cols);
        }
        if (phase == 4) {
            far::DiscSource moved = rock_scenario::beol4_field();
            moved.centre = {400.0, -200.0, 50.0};
            sources = {moved, noisy_belt()};
            f.set_sources(sources);
            f.set_collections(rock_scenario::mid_collections());
        }
        for (int i = 0; i < 24; ++i) {
            const double t = i / 24.0;
            // Inside the field, sweeping the view around.
            const glm::dvec3 eye_in(40.0 * std::sin(6.0 * t), -700.0 + 30.0 * t, 10.0 * t);
            const glm::vec3 dir_in(std::sin(6.283f * t), std::cos(6.283f * t), 0.2f * std::sin(3.0f * t));
            build_at(eye_in, dir_in, 60.0f, glm::floor(eye_in / 50.0) * 50.0);
            // Outside, looking at the field.
            const glm::dvec3 eye_out(500.0 * t, -6000.0 + 900.0 * t, 300.0);
            build_at(eye_out, glm::normalize(glm::vec3(-eye_out)), 35.0f, glm::dvec3(0.0));
            if (i % 6 == 0)   // telephoto down the cluster
                build_at(glm::dvec3(1300.0, -1500.0, 0.0), {0, 1, -0.04f}, 8.0f, glm::dvec3(1250.0, -1500.0, 0.0));
        }
    }
    return {d.h, sprites, builds, f.cache_stats(), fading};
}
}  // namespace

TEST(RockPerfEquivalence, MidBuildsMatchTheRecordedDigests) {
    const MidRun r = run_mid(/*resend=*/false);
    std::printf("[mid equivalence] builds=0x%016" PRIx64 " (builds=%d sprites=%d)\n", r.digest,
                r.builds, r.sprites);
    EXPECT_GT(r.sprites, 0);
    EXPECT_GT(r.fading, 0) << "the run must build translucent sprites";
    EXPECT_EQ(r.digest, 0x433d292793849a18ull) << "drawn mid sprites changed";
}

// ---- The live call pattern (coordinator review 2026-10-03) -----------------
// The host re-pushes the same sources EVERY frame (far_set_frame). That must
// neither change a byte nor throw away the incremental state.

TEST(RockPerfEquivalence, NearSameSourcesEveryFrameKeepsTheIncrementalStream) {
    const NearRun base = run_near(/*fast=*/false, /*caps=*/false);
    const NearRun live = run_near(/*fast=*/false, /*caps=*/false, /*resend=*/true);
    expect_near("slow, sources every frame", live, 0x32b35fece022b324ull, 0xdf39b4a12bf4af85ull,
                0x8d90bab75baf5c86ull);
    // 720 streams x 2 classes at 6-25 GU/s: a full pass only every ~2 GU of
    // travel (plus the dial changes) -- 1,440 if every frame were full.
    EXPECT_EQ(live.full_passes, base.full_passes);
    EXPECT_LT(live.full_passes, 360u);
}

TEST(RockPerfEquivalence, MidSameSourcesEveryFrameKeepsTheTileCache) {
    const MidRun base = run_mid(/*resend=*/false);
    const MidRun live = run_mid(/*resend=*/true);
    EXPECT_EQ(live.digest, 0x433d292793849a18ull) << "drawn mid sprites changed";
    EXPECT_EQ(live.cache.fills, base.cache.fills) << "re-pushing the same sources refilled the cache";
}

TEST(RockPerfEquivalence, MidMovedSourceStillClearsTheCache) {
    // A real anchor move shifts a view-space source's system centre: the
    // output must match a fresh field's.
    rockfield::MidField a, b;
    for (auto* f : {&a, &b}) {
        f->set_collections(rock_scenario::mid_collections());
        f->set_view_dirs(rock_scenario::view_dirs16());
    }
    rockfield::MidBuildInput in;
    in.viewport_h = 1080.0f;
    in.view = glm::lookAt(glm::vec3(0, -700, 0), glm::vec3(0), glm::vec3(0, 0, 1));
    in.proj = glm::perspective(glm::radians(60.0f), 16.0f / 9.0f, 0.1f, 1.0e6f);
    rockfield::MidOutput oa, ob;
    a.set_sources({rock_scenario::beol4_field()});
    a.build(in, oa);
    far::DiscSource moved = rock_scenario::beol4_field();
    moved.centre = {37.5, -12.0, 4.0};
    a.set_sources({moved});
    a.build(in, oa);
    b.set_sources({moved});
    b.build(in, ob);
    Digest da, dbg;
    digest_mid_out(da, oa, in.view);
    digest_mid_out(dbg, ob, in.view);
    EXPECT_EQ(da.h, dbg.h);
    EXPECT_GT(oa.count, 0);
}

// Reviewer's repro: leaving a source's reach drops every cell; coming back
// within the watch width of the last full pass must re-stream them all.
TEST(RockPerfEquivalence, NearOutOfReachAndBackMatchesAFreshStream) {
    for (bool resend : {false, true}) {
        rockfield::NearField f, fresh;
        for (auto* g : {&f, &fresh}) {
            g->set_catalogue(rock_scenario::near_catalogue());
            g->set_sources({rock_scenario::beol4_field()});
        }
        const glm::dvec3 P(0, -700, 0), back = P + glm::dvec3(0.5, 0, 0);
        f.stream(P);
        if (resend) f.set_sources({rock_scenario::beol4_field()});
        f.stream(glm::dvec3(0, -5000, 0));   // out of reach: every cell dropped
        EXPECT_EQ(f.stats().cells, 0);
        if (resend) f.set_sources({rock_scenario::beol4_field()});
        f.stream(back);
        fresh.stream(back);
        Digest a, b;
        digest_stream(a, f);
        digest_stream(b, fresh);
        EXPECT_EQ(f.stats().cells, fresh.stats().cells) << "resend=" << resend;
        EXPECT_EQ(a.h, b.h) << "resend=" << resend;
    }
}
