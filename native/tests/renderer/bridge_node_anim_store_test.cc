#include <gtest/gtest.h>
#include <renderer/bridge_node_anim_store.h>
#include <assets/model.h>
#include <assets/animation.h>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtx/quaternion.hpp>

namespace {
// A bridge-shaped model: one door pair and one chair, as on the real DBridge.
assets::Model bridge_model() {
    assets::Model m;
    assets::Node root;  root.name = "root";  root.parent_index = -1;
    root.local_transform = glm::mat4(1.0f);
    assets::Node da;    da.name = "door 04a"; da.parent_index = 0;
    da.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(1, 0, 0));
    assets::Node db;    db.name = "door 04b"; db.parent_index = 0;
    db.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(2, 0, 0));
    assets::Node seat;  seat.name = "console seat 01"; seat.parent_index = 0;
    seat.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(0, 5, 0));
    m.nodes = {root, da, db, seat};       // indices 0,1,2,3
    m.root_node = 0;
    return m;
}

// The L1 door clip: slides BOTH leaves aside over 1s and back — it opens and
// closes itself (3 keys, returns to start), exactly like DB_door_L1.NIF.
assets::AnimationClip door_clip() {
    assets::AnimationClip c; c.duration_seconds = 1.0f;
    assets::AnimationClip::NodeTrack a; a.target_node_name = "door 04a";
    a.translation = {{0.0f, glm::vec3(1, 0, 0)},
                     {0.5f, glm::vec3(1, 0, 9)},
                     {1.0f, glm::vec3(1, 0, 0)}};
    assets::AnimationClip::NodeTrack b; b.target_node_name = "door 04b";
    b.translation = {{0.0f, glm::vec3(2, 0, 0)},
                     {0.5f, glm::vec3(2, 0, -9)},
                     {1.0f, glm::vec3(2, 0, 0)}};
    c.tracks = {a, b};
    return c;
}

// A chair turn: rotates the seat and HOLDS the turned pose (BC ships a separate
// reverse NIF to bring it back — the pose persists after the clip ends).
assets::AnimationClip chair_clip() {
    assets::AnimationClip c; c.duration_seconds = 1.0f;
    assets::AnimationClip::NodeTrack s; s.target_node_name = "console seat 01";
    glm::quat rest = glm::angleAxis(glm::radians(0.0f),  glm::vec3(0, 0, 1));
    glm::quat turn = glm::angleAxis(glm::radians(90.0f), glm::vec3(0, 0, 1));
    s.rotation = {{0.0f, rest}, {1.0f, turn}};
    c.tracks = {s};
    return c;
}

// The dedicated reverse NIF BC ships to bring a turned chair back: a DIFFERENT
// clip (different key/path) that animates the SAME node from turned to rest.
assets::AnimationClip unturn_chair_clip() {
    assets::AnimationClip c; c.duration_seconds = 1.0f;
    assets::AnimationClip::NodeTrack s; s.target_node_name = "console seat 01";
    glm::quat turn = glm::angleAxis(glm::radians(90.0f), glm::vec3(0, 0, 1));
    glm::quat rest = glm::angleAxis(glm::radians(0.0f),  glm::vec3(0, 0, 1));
    s.rotation = {{0.0f, turn}, {1.0f, rest}};
    c.tracks = {s};
    return c;
}

// A third, distinct clip on the same seat node, settling at a third angle, so
// overlap-ordering tests can tell all three apart unambiguously.
assets::AnimationClip half_turn_chair_clip() {
    assets::AnimationClip c; c.duration_seconds = 1.0f;
    assets::AnimationClip::NodeTrack s; s.target_node_name = "console seat 01";
    glm::quat rest = glm::angleAxis(glm::radians(0.0f),  glm::vec3(0, 0, 1));
    glm::quat half = glm::angleAxis(glm::radians(45.0f), glm::vec3(0, 0, 1));
    s.rotation = {{0.0f, rest}, {1.0f, half}};
    c.tracks = {s};
    return c;
}

// The rotation angle (degrees, about the shared Z axis) encoded in a sampled
// node override's upper-left 3x3, so overlap-ordering tests can tell which
// clip's pose actually won without hand-decomposing matrices inline.
float seat_angle_deg(const glm::mat4& m) {
    glm::mat3 m3(m);
    glm::quat q = glm::quat_cast(m3);
    return glm::degrees(glm::angle(q));
}

constexpr std::uint32_t kBridge = 7;   // arbitrary instance index
constexpr std::uint32_t kBridge2 = 8;  // a second, distinct instance
}  // namespace

// THE REGRESSION THIS TASK EXISTS TO FIX: today the second play overwrites the
// first, so a door opening during a turn-to-captain kills the chair clip.
TEST(BridgeNodeAnimStore, DoorAndChairCoexist) {
    renderer::BridgeNodeAnimStore s;
    auto m = bridge_model();
    s.play(kBridge, "data/animations/db_door_l1.nif", door_clip(), 0.0, false, false);
    s.play(kBridge, "data/animations/db_chair_h.nif", chair_clip(), 0.0, false, false);
    EXPECT_EQ(s.active_count(kBridge), 2u);

    auto ov = s.sample(kBridge, m, 0.5);      // mid-cycle: door open, chair turning
    ASSERT_EQ(ov.size(), 3u);                 // both door leaves AND the seat
    EXPECT_TRUE(ov.count(1));                 // door 04a
    EXPECT_TRUE(ov.count(2));                 // door 04b
    EXPECT_TRUE(ov.count(3));                 // console seat 01
    EXPECT_NEAR(ov[1][3].z,  9.0f, 1e-4f);    // leaf A slid open
    EXPECT_NEAR(ov[2][3].z, -9.0f, 1e-4f);    // leaf B slid open
}

// E1M1 fires the SAME door twice under two registered names. Re-playing must
// RESTART the clip, never stack a rival copy fighting over the same nodes.
TEST(BridgeNodeAnimStore, SamePathRestartsRatherThanStacks) {
    renderer::BridgeNodeAnimStore s;
    auto m = bridge_model();
    s.play(kBridge, "data/animations/db_door_l1.nif", door_clip(), 0.0, false, false);
    s.play(kBridge, "data/animations/db_door_l1.nif", door_clip(), 0.5, false, false);
    EXPECT_EQ(s.active_count(kBridge), 1u);

    // Restarted at t=0.5, so at now=0.5 the clip is at its OWN t=0 (closed).
    auto ov = s.sample(kBridge, m, 0.5);
    EXPECT_NEAR(ov[1][3].z, 0.0f, 1e-4f);
}

// "doorl1" -> db_door_l1.nif and "DB_Door_L1" -> DB_Door_L1.nif are the SAME
// file. Keying by name would let the aliases collide; keying by path collapses.
TEST(BridgeNodeAnimStore, CaseAliasesAreTheSameClip) {
    renderer::BridgeNodeAnimStore s;
    s.play(kBridge, "data/animations/DB_Door_L1.nif", door_clip(), 0.0, false, false);
    s.play(kBridge, "data/animations/db_door_l1.nif", door_clip(), 0.0, false, false);
    EXPECT_EQ(s.active_count(kBridge), 1u);
}

// One uniform rule, matching BC: a settled clip HOLDS its last frame. The chair
// stays turned; a door clip ends back at rest so holding it is invisible.
TEST(BridgeNodeAnimStore, SettledClipHoldsLastFrame) {
    renderer::BridgeNodeAnimStore s;
    auto m = bridge_model();
    s.play(kBridge, "data/animations/db_chair_h.nif", chair_clip(), 0.0, false, false);

    auto at_end  = s.sample(kBridge, m, 1.0);    // exactly the last frame
    auto way_past = s.sample(kBridge, m, 99.0);  // long after it settled
    ASSERT_TRUE(at_end.count(3) && way_past.count(3));
    for (int col = 0; col < 4; ++col)
        for (int row = 0; row < 4; ++row)
            EXPECT_NEAR(way_past[3][col][row], at_end[3][col][row], 1e-5f);
    EXPECT_EQ(s.active_count(kBridge), 1u);      // held, not evicted
}

TEST(BridgeNodeAnimStore, StopClearsTheInstanceAndSampleIsEmpty) {
    renderer::BridgeNodeAnimStore s;
    auto m = bridge_model();
    s.play(kBridge, "data/animations/db_door_l1.nif", door_clip(), 0.0, false, false);
    s.stop(kBridge);
    EXPECT_EQ(s.active_count(kBridge), 0u);
    EXPECT_TRUE(s.sample(kBridge, m, 0.5).empty());
    EXPECT_TRUE(s.empty());
}

TEST(BridgeNodeAnimStore, LoopingClipWraps) {
    renderer::BridgeNodeAnimStore s;
    auto m = bridge_model();
    s.play(kBridge, "data/animations/db_door_l1.nif", door_clip(), 0.0, true, false);
    auto a = s.sample(kBridge, m, 0.5);
    auto b = s.sample(kBridge, m, 2.5);     // 2 full cycles later == same phase
    EXPECT_NEAR(a[1][3].z, b[1][3].z, 1e-4f);
}

// Plain overlap ordering: two DIFFERENT keys animating the SAME node — the
// later-played clip wins, per the documented merge rule.
TEST(BridgeNodeAnimStore, LaterPlayedClipWinsOnNodeOverlap) {
    renderer::BridgeNodeAnimStore s;
    auto m = bridge_model();
    s.play(kBridge, "data/animations/db_chair_h.nif", chair_clip(), 0.0, false, false);
    s.play(kBridge, "data/animations/db_chair_half.nif", half_turn_chair_clip(), 0.0, false, false);
    EXPECT_EQ(s.active_count(kBridge), 2u);

    auto ov = s.sample(kBridge, m, 5.0);   // both long settled
    ASSERT_TRUE(ov.count(3));
    EXPECT_NEAR(seat_angle_deg(ov[3]), 45.0f, 1e-3f);   // half-turn, played LAST, wins
}

// CRITICAL REGRESSION: a re-played clip must restart at the BACK of the
// per-instance vector (most-recently-played wins), not mutate in place at its
// original position. Otherwise a stale settled clip that was played AFTER it
// keeps overwriting the shared node forever, and the chair (or door) never
// turns again on a second play.
TEST(BridgeNodeAnimStore, ReplayMovesClipToTheBackSoItWinsAgain) {
    renderer::BridgeNodeAnimStore s;
    auto m = bridge_model();

    // 1. turn_chair plays the forward clip -> settles TURNED (90 deg).
    s.play(kBridge, "data/animations/db_chair_h.nif", chair_clip(), 0.0, false, false);
    auto after_turn = s.sample(kBridge, m, 1.0);
    ASSERT_TRUE(after_turn.count(3));
    EXPECT_NEAR(seat_angle_deg(after_turn[3]), 90.0f, 1e-3f);

    // 2. unturn_chair plays a DIFFERENT clip -> settles REST (0 deg) and, being
    //    later, wins the seat node.
    s.play(kBridge, "data/animations/db_chair_h_reverse.nif", unturn_chair_clip(),
           1.0, false, false);
    auto after_unturn = s.sample(kBridge, m, 2.0);
    ASSERT_TRUE(after_unturn.count(3));
    EXPECT_NEAR(seat_angle_deg(after_unturn[3]), 0.0f, 1e-3f);

    // 3. turn_chair plays AGAIN (same key as step 1, restarted). It must move
    //    to the back of the vector so it wins the overlap once it settles
    //    again — proving a re-play IS a re-insertion, not an in-place mutate.
    s.play(kBridge, "data/animations/db_chair_h.nif", chair_clip(), 3.0, false, false);
    auto after_replay = s.sample(kBridge, m, 4.0);   // forward clip settled again
    ASSERT_TRUE(after_replay.count(3));
    EXPECT_NEAR(seat_angle_deg(after_replay[3]), 90.0f, 1e-3f)
        << "the chair must be able to turn again after unturn/turn; a settled "
           "clip played BEFORE the replay must not keep winning the node";
}

// stop() must clear only the targeted instance; a second instance's clips
// must survive untouched. (A "wipe everything" stop() would still pass the
// single-instance StopClearsTheInstanceAndSampleIsEmpty test above.)
TEST(BridgeNodeAnimStore, StopOnlyClearsTheTargetedInstance) {
    renderer::BridgeNodeAnimStore s;
    auto m = bridge_model();
    s.play(kBridge, "data/animations/db_door_l1.nif", door_clip(), 0.0, false, false);
    s.play(kBridge2, "data/animations/db_door_l1.nif", door_clip(), 0.0, false, false);

    s.stop(kBridge);

    EXPECT_EQ(s.active_count(kBridge), 0u);
    EXPECT_TRUE(s.sample(kBridge, m, 0.5).empty());

    EXPECT_EQ(s.active_count(kBridge2), 1u);
    auto ov = s.sample(kBridge2, m, 0.5);
    ASSERT_TRUE(ov.count(1));
    EXPECT_NEAR(ov[1][3].z, 9.0f, 1e-4f);   // untouched instance still mid-open
}

// Reverse playback is never exercised anywhere else. A non-loop reverse clip
// settles at t = dur - dur = 0, i.e. it holds the START of the underlying
// track (the END of reverse playback) — verify that directly instead of
// assuming it.
TEST(BridgeNodeAnimStore, ReversePlaybackSettlesAtTheClipsStart) {
    renderer::BridgeNodeAnimStore s;
    auto m = bridge_model();
    s.play(kBridge, "data/animations/db_chair_h.nif", chair_clip(), 0.0,
           /*loop=*/false, /*reverse=*/true);

    // Long after duration: settled, reverse-holds t=0 (REST), not t=1 (TURNED).
    auto settled = s.sample(kBridge, m, 99.0);
    ASSERT_TRUE(settled.count(3));
    EXPECT_NEAR(seat_angle_deg(settled[3]), 0.0f, 1e-3f);

    // Mid-playback: reverse runs the clip backwards, so as wall time advances
    // the sampled angle should DECREASE (moving from near-TURNED toward REST).
    auto early = s.sample(kBridge, m, 0.1);   // t = dur - 0.1 = 0.9 -> near TURNED
    auto late  = s.sample(kBridge, m, 0.9);   // t = dur - 0.9 = 0.1 -> near REST
    ASSERT_TRUE(early.count(3) && late.count(3));
    EXPECT_GT(seat_angle_deg(early[3]), seat_angle_deg(late[3]));
}
