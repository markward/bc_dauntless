#include <gtest/gtest.h>
#include <renderer/node_anim.h>
#include <assets/model.h>
#include <assets/animation.h>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtx/matrix_decompose.hpp>
#include <glm/gtx/quaternion.hpp>

namespace {
// Two-node chain: root at origin, child translated +Y by 5.
assets::Model two_node() {
    assets::Model m;
    assets::Node root; root.name = "root"; root.parent_index = -1;
    root.local_transform = glm::mat4(1.0f);
    assets::Node child; child.name = "console seat 01"; child.parent_index = 0;
    child.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(0, 5, 0));
    m.nodes = {root, child};
    m.root_node = 0;
    return m;
}
}

TEST(ComposeNodeWorlds, NoOverridesMatchesStaticWalk) {
    auto m = two_node();
    std::unordered_map<int, glm::mat4> empty;
    auto w = renderer::compose_node_worlds(m, glm::mat4(1.0f), empty);
    ASSERT_EQ(w.size(), 2u);
    EXPECT_EQ(w[0], glm::mat4(1.0f));
    // child world = root * child local = translate(0,5,0)
    EXPECT_NEAR(w[1][3].y, 5.0f, 1e-5f);
}

TEST(ComposeNodeWorlds, OverrideReplacesOnlyThatNodeLocal) {
    auto m = two_node();
    std::unordered_map<int, glm::mat4> ov;
    // Rotate the seat 90deg about Z in its local frame, keep its translation.
    glm::mat4 rot = glm::rotate(glm::mat4(1.0f), glm::radians(90.0f), glm::vec3(0,0,1));
    ov[1] = glm::translate(glm::mat4(1.0f), glm::vec3(0,5,0)) * rot;
    auto w = renderer::compose_node_worlds(m, glm::mat4(1.0f), ov);
    EXPECT_EQ(w[0], glm::mat4(1.0f));                 // root untouched
    EXPECT_NEAR(w[1][3].y, 5.0f, 1e-5f);             // translation preserved
    // local +X (1,0,0) rotated 90deg about Z -> +Y
    glm::vec3 col0 = glm::normalize(glm::vec3(w[1][0]));
    EXPECT_NEAR(col0.y, 1.0f, 1e-4f);
}

TEST(ComposeNodeWorlds, InstanceWorldPremultiplies) {
    auto m = two_node();
    std::unordered_map<int, glm::mat4> empty;
    glm::mat4 iw = glm::translate(glm::mat4(1.0f), glm::vec3(100,0,0));
    auto w = renderer::compose_node_worlds(m, iw, empty);
    EXPECT_NEAR(w[0][3].x, 100.0f, 1e-5f);
    EXPECT_NEAR(w[1][3].x, 100.0f, 1e-5f);
    EXPECT_NEAR(w[1][3].y, 5.0f, 1e-5f);
}

TEST(SampleNodeOverrides, MatchesSeatTrackIgnoresUnknownNode) {
    auto m = two_node();   // nodes: "root", "console seat 01"
    assets::AnimationClip clip; clip.duration_seconds = 1.0f;
    // Track that rotates the seat 90deg about Z across the clip.
    assets::AnimationClip::NodeTrack seat; seat.target_node_name = "console seat 01";
    glm::quat q = glm::angleAxis(glm::radians(90.0f), glm::vec3(0,0,1));
    seat.rotation = {{0.0f, q}, {1.0f, q}};
    // Track for a node that does NOT exist in the bridge (the zoom camera).
    assets::AnimationClip::NodeTrack cam; cam.target_node_name = "Camera captain";
    cam.translation = {{0.0f, glm::vec3(0,0,0)}, {1.0f, glm::vec3(999,0,0)}};
    clip.tracks = {seat, cam};

    auto ov = renderer::sample_node_overrides(clip, m, 1.0f);
    // Only the seat node (index 1) gets an override; the camera track is ignored.
    ASSERT_EQ(ov.size(), 1u);
    ASSERT_TRUE(ov.count(1));
    // Seat keeps its static translation (0,5,0) and gains the 90deg-Z rotation.
    EXPECT_NEAR(ov[1][3].y, 5.0f, 1e-4f);
    glm::vec3 col0 = glm::normalize(glm::vec3(ov[1][0]));
    EXPECT_NEAR(col0.y, 1.0f, 1e-3f);
}

TEST(SampleNodeOverrides, EmptyClipProducesNoOverrides) {
    auto m = two_node();
    assets::AnimationClip clip; clip.duration_seconds = 0.0f;   // no tracks
    auto ov = renderer::sample_node_overrides(clip, m, 0.0f);
    EXPECT_TRUE(ov.empty());
}

// --- External-clip retargeting (the lift-door double-transform bug) -------
//
// An EXTERNAL clip NIF (data/animations/DB_door_L1.nif) keys its nodes in ITS
// OWN root frame. In the bridge model those same nodes hang under a parent that
// already carries their placement. Writing the clip's root-frame key straight in
// as the node's LOCAL transform applies the placement TWICE. Retarget instead:
//     override_local = model_local * inverse(clip_rest_local) * clip_sampled
namespace {
// The door's placement lives on its PARENT; the leaf's own local is identity.
// rest world of "door 04a" = (172.9, 182.7, 69.0), matching the live game.
const glm::vec3 kDoorRest(172.9f, 182.7f, 69.0f);

assets::Model door_under_placed_parent() {
    assets::Model m;
    assets::Node root; root.name = "root"; root.parent_index = -1;
    root.local_transform = glm::mat4(1.0f);
    assets::Node frame; frame.name = "lift frame"; frame.parent_index = 0;
    frame.local_transform = glm::translate(glm::mat4(1.0f), kDoorRest);
    assets::Node leaf; leaf.name = "door 04a"; leaf.parent_index = 1;
    leaf.local_transform = glm::mat4(1.0f);      // placement is on the PARENT
    m.nodes = {root, frame, leaf};
    m.root_node = 0;
    return m;
}

// External door clip: keys are in the CLIP's root frame (= the bridge world
// frame), so its t=0 key IS the door's rest world position. It slides +18 on Y.
assets::AnimationClip external_door_clip() {
    assets::AnimationClip clip; clip.duration_seconds = 1.0f;
    assets::AnimationClip::NodeTrack d; d.target_node_name = "door 04a";
    d.translation = {{0.0f, kDoorRest},
                     {1.0f, kDoorRest + glm::vec3(0, 18, 0)}};
    clip.tracks = {d};
    clip.rest_locals["door 04a"] =
        glm::translate(glm::mat4(1.0f), kDoorRest);   // the CLIP's own rest
    return clip;
}
}  // namespace

TEST(SampleNodeOverrides, ExternalClipAtRestLeavesTheDoorInItsDoorway) {
    auto m = door_under_placed_parent();
    auto clip = external_door_clip();
    auto ov = renderer::sample_node_overrides(clip, m, 0.0f);
    auto w = renderer::compose_node_worlds(m, glm::mat4(1.0f), ov);
    // At t=0 the clip's sampled pose IS its rest, so the door must not move.
    const glm::vec3 pos(w[2][3]);
    EXPECT_NEAR(pos.x, kDoorRest.x, 1e-3f);
    EXPECT_NEAR(pos.y, kDoorRest.y, 1e-3f);
    EXPECT_NEAR(pos.z, kDoorRest.z, 1e-3f);
    // Guard the exact signature of the bug: displacement by |rest| (260.8).
    EXPECT_LT(glm::length(pos - kDoorRest), 1e-3f);
}

TEST(SampleNodeOverrides, ExternalClipMidwayMovesByTheAuthoredDeltaOnly) {
    auto m = door_under_placed_parent();
    auto clip = external_door_clip();
    auto ov = renderer::sample_node_overrides(clip, m, 0.5f);
    auto w = renderer::compose_node_worlds(m, glm::mat4(1.0f), ov);
    const glm::vec3 pos(w[2][3]);
    const glm::vec3 want = kDoorRest + glm::vec3(0, 9, 0);   // half of the 18 slide
    EXPECT_NEAR(pos.x, want.x, 1e-3f);
    EXPECT_NEAR(pos.y, want.y, 1e-3f);
    EXPECT_NEAR(pos.z, want.z, 1e-3f);
}

TEST(SampleNodeOverrides, EmbeddedClipRestEqualsModelLocalSamplesAsBefore) {
    // The bridge's OWN embedded clip is authored in the model's frame, so its
    // rest_locals equal the model node locals -> the retarget collapses to the
    // sampled pose (identical to the pre-fix behaviour).
    auto m = two_node();                       // "console seat 01" local = T(0,5,0)
    assets::AnimationClip clip; clip.duration_seconds = 1.0f;
    assets::AnimationClip::NodeTrack s; s.target_node_name = "console seat 01";
    s.translation = {{0.0f, glm::vec3(0, 5, 0)}, {1.0f, glm::vec3(0, 9, 0)}};
    clip.tracks = {s};
    clip.rest_locals["console seat 01"] =
        glm::translate(glm::mat4(1.0f), glm::vec3(0, 5, 0));   // == model local

    auto ov = renderer::sample_node_overrides(clip, m, 1.0f);
    ASSERT_TRUE(ov.count(1));
    EXPECT_NEAR(ov[1][3].y, 9.0f, 1e-4f);     // exactly the sampled key
    EXPECT_NEAR(ov[1][3].x, 0.0f, 1e-4f);
}

TEST(SampleNodeOverrides, ExternalRotationOnlyClipRotatesInPlace) {
    // The chair clips (db_chair_*.nif) are external too but carry ROTATION keys
    // only. They must keep rotating the seat about its OWN origin without moving
    // it -- even though the clip's rest is in the clip's root frame.
    auto m = two_node();     // "console seat 01" local = T(0,5,0), no rotation
    assets::AnimationClip clip; clip.duration_seconds = 1.0f;
    assets::AnimationClip::NodeTrack s; s.target_node_name = "console seat 01";
    glm::quat q = glm::angleAxis(glm::radians(90.0f), glm::vec3(0, 0, 1));
    s.rotation = {{0.0f, glm::quat(1, 0, 0, 0)}, {1.0f, q}};
    clip.tracks = {s};
    // Clip's own rest: the seat placed somewhere else entirely (root frame).
    clip.rest_locals["console seat 01"] =
        glm::translate(glm::mat4(1.0f), glm::vec3(30, 40, 50));

    auto ov = renderer::sample_node_overrides(clip, m, 1.0f);
    ASSERT_TRUE(ov.count(1));
    auto w = renderer::compose_node_worlds(m, glm::mat4(1.0f), ov);
    // Did not move: still at its model rest (0,5,0) -- NOT at the clip's (30,40,50).
    EXPECT_NEAR(w[1][3].x, 0.0f, 1e-3f);
    EXPECT_NEAR(w[1][3].y, 5.0f, 1e-3f);
    EXPECT_NEAR(w[1][3].z, 0.0f, 1e-3f);
    // But it DID rotate 90deg about Z: local +X -> +Y.
    glm::vec3 col0 = glm::normalize(glm::vec3(w[1][0]));
    EXPECT_NEAR(col0.y, 1.0f, 1e-3f);
}

TEST(SampleNodeOverrides, NoRestLocalForNodeKeepsLegacyBehaviour) {
    // A clip with no rest_locals entry for the node falls back to the old path:
    // the key is written straight in as the node's local transform.
    auto m = door_under_placed_parent();
    auto clip = external_door_clip();
    clip.rest_locals.clear();                       // no rest pose recorded
    auto ov = renderer::sample_node_overrides(clip, m, 0.0f);
    ASSERT_TRUE(ov.count(2));
    EXPECT_NEAR(ov[2][3].x, kDoorRest.x, 1e-3f);    // key AS the local transform
    EXPECT_NEAR(ov[2][3].y, kDoorRest.y, 1e-3f);
    EXPECT_NEAR(ov[2][3].z, kDoorRest.z, 1e-3f);
}

// --- Duplicate-name resolution (the chair-coupling bug) -------------------
namespace {
// Model with TWO nodes named "console seat 01" (like the real DBridge NIF),
// at indices 1 and 2. Index 2 is the one the override lands on.
assets::Model dup_seat() {
    assets::Model m;
    assets::Node root; root.name = "root"; root.parent_index = -1;
    root.local_transform = glm::mat4(1.0f);
    assets::Node a; a.name = "console seat 01"; a.parent_index = 0;
    a.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(0, 5, 0));
    assets::Node b; b.name = "console seat 01"; b.parent_index = 0;
    b.local_transform = glm::translate(glm::mat4(1.0f), glm::vec3(0, 7, 0));
    m.nodes = {root, a, b};
    m.root_node = 0;
    return m;
}
}

TEST(ResolveOverriddenNode, PrefersTheOverriddenDuplicate) {
    auto m = dup_seat();                 // indices 1 and 2 both "console seat 01"
    std::unordered_map<int, glm::mat4> ov;
    ov[2] = glm::mat4(1.0f);             // override on the SECOND duplicate
    EXPECT_EQ(renderer::resolve_overridden_node(m, "console seat 01", ov), 2);
}

TEST(ResolveOverriddenNode, FallsBackToFirstWhenNoOverride) {
    auto m = dup_seat();
    std::unordered_map<int, glm::mat4> empty;
    EXPECT_EQ(renderer::resolve_overridden_node(m, "console seat 01", empty), 1);
}

TEST(ResolveOverriddenNode, ReturnsMinusOneForUnknownName) {
    auto m = dup_seat();
    std::unordered_map<int, glm::mat4> empty;
    EXPECT_EQ(renderer::resolve_overridden_node(m, "no such node", empty), -1);
}

// --- Rest-BAKED clip on the nested duplicate node (the chair desync bug) ---
//
// DBridge.nif nests a DUPLICATE node: the outer 'console seat 01' carries the
// PLACEMENT and its identity-local CHILD of the same name holds the mesh. BC's
// NiKeyframeController overwrites the target node's local OUTRIGHT, so a clip's
// keys are the absolute local TRS of the PLACED node. And BC bakes each
// *_reverse / *_in clip's rest local to that clip's FIRST KEY, not to the set's
// rest pose (db_chair_H_face_capt_reverse rest = Rz(-60), keys -60 -> 0).
// Retargeting through inverse(clip_rest) therefore MIRRORS those clips: the
// chair swings OUT to +60 and holds there. Bind to the PLACED node and write
// the sampled pose in directly.
namespace {
// DBridge.nif's placed 'console seat 01' translation (all chair clips share it).
const glm::vec3 kSeatT(33.44f, -104.74f, 9.33f);

glm::mat4 rot_z(float deg) {
    return glm::rotate(glm::mat4(1.0f), glm::radians(deg), glm::vec3(0, 0, 1));
}

// Outer PLACED node + identity-local child of the SAME name (the mesh holder).
assets::Model nested_dup_seat() {
    assets::Model m;
    assets::Node root; root.name = "root"; root.parent_index = -1;
    root.local_transform = glm::mat4(1.0f);
    assets::Node placed; placed.name = "console seat 01"; placed.parent_index = 0;
    placed.local_transform = glm::translate(glm::mat4(1.0f), kSeatT);  // R = I
    assets::Node mesh; mesh.name = "console seat 01"; mesh.parent_index = 1;
    mesh.local_transform = glm::mat4(1.0f);          // identity-local duplicate
    m.nodes = {root, placed, mesh};
    m.root_node = 0;
    return m;
}

// db_chair_H_face_capt_reverse.NIF: clip rest bakes the TURNED pose (Rz(-60)),
// keys run turned -> console-facing. Rotation-only track (translation is a
// no-op: identical across every chair clip, so BC omits/repeats it).
assets::AnimationClip rest_baked_reverse_clip() {
    assets::AnimationClip clip; clip.duration_seconds = 1.0f;
    assets::AnimationClip::NodeTrack s; s.target_node_name = "console seat 01";
    s.rotation = {{0.0f, glm::angleAxis(glm::radians(-60.0f), glm::vec3(0, 0, 1))},
                  {1.0f, glm::quat(1, 0, 0, 0)}};
    clip.tracks = {s};
    clip.rest_locals["console seat 01"] =
        glm::translate(glm::mat4(1.0f), kSeatT) * rot_z(-60.0f);   // BAKED turn
    return clip;
}

// Compare a transform's rotation to a Z rotation by `deg` via its local +X axis.
void expect_rot_z(const glm::mat4& m, float deg, float tol = 1e-3f) {
    const glm::vec3 got = glm::normalize(glm::vec3(m[0]));
    const glm::vec3 want = glm::vec3(rot_z(deg)[0]);
    EXPECT_NEAR(got.x, want.x, tol);
    EXPECT_NEAR(got.y, want.y, tol);
    EXPECT_NEAR(got.z, want.z, tol);
}
}  // namespace

TEST(SampleNodeOverrides, RestBakedClipBindsToThePlacedDuplicateNotTheMeshChild) {
    auto m = nested_dup_seat();          // 1 = placed, 2 = identity-local mesh
    auto clip = rest_baked_reverse_clip();
    auto ov = renderer::sample_node_overrides(clip, m, 0.0f);
    ASSERT_EQ(ov.size(), 1u);
    EXPECT_TRUE(ov.count(1)) << "must override the PLACED node (index 1)";
    EXPECT_FALSE(ov.count(2)) << "must NOT override the identity-local mesh child";
}

TEST(SampleNodeOverrides, RestBakedReverseClipStartsAtItsFirstKeyPose) {
    auto m = nested_dup_seat();
    auto clip = rest_baked_reverse_clip();
    auto ov = renderer::sample_node_overrides(clip, m, 0.0f);
    auto w = renderer::compose_node_worlds(m, glm::mat4(1.0f), ov);
    // t=0 is the clip's FIRST key: the seat is TURNED toward the captain (-60).
    expect_rot_z(w[2], -60.0f);
    const glm::vec3 pos(w[2][3]);        // and it never leaves its placement
    EXPECT_NEAR(pos.x, kSeatT.x, 1e-3f);
    EXPECT_NEAR(pos.y, kSeatT.y, 1e-3f);
    EXPECT_NEAR(pos.z, kSeatT.z, 1e-3f);
}

TEST(SampleNodeOverrides, RestBakedReverseClipEndsAtTheModelRestPose) {
    auto m = nested_dup_seat();
    auto clip = rest_baked_reverse_clip();
    auto ov = renderer::sample_node_overrides(clip, m, 1.0f);
    auto w = renderer::compose_node_worlds(m, glm::mat4(1.0f), ov);
    // t=end is the clip's LAST key: back to console-facing (= the model rest).
    // The bug produced +60 here (mirrored: rotated OUT and held).
    expect_rot_z(w[2], 0.0f);
    const glm::vec3 col0 = glm::normalize(glm::vec3(w[2][0]));
    EXPECT_LT(col0.y, 0.1f) << "chair must not swing OUT to +60 (the reported bug)";
    const glm::vec3 pos(w[2][3]);
    EXPECT_NEAR(pos.x, kSeatT.x, 1e-3f);
    EXPECT_NEAR(pos.y, kSeatT.y, 1e-3f);
    EXPECT_NEAR(pos.z, kSeatT.z, 1e-3f);
}

TEST(SampleNodeOverrides, PlacementBakedDoorClipOnNestedDuplicateStillSlides) {
    // REGRESSION GUARD for ef058220: a DOOR clip's baked rest IS its placement
    // (rotation included), and the door hangs off the same nested-duplicate
    // shape. It must still sit in its doorway at t=0 and slide by the authored
    // delta only -- no double-applied placement.
    const glm::vec3 kDoorT(172.9f, 182.7f, 69.0f);
    assets::Model m;
    assets::Node root; root.name = "root"; root.parent_index = -1;
    root.local_transform = glm::mat4(1.0f);
    assets::Node placed; placed.name = "door 04a"; placed.parent_index = 0;
    placed.local_transform =
        glm::translate(glm::mat4(1.0f), kDoorT) * rot_z(30.0f);   // placement
    assets::Node mesh; mesh.name = "door 04a"; mesh.parent_index = 1;
    mesh.local_transform = glm::mat4(1.0f);
    m.nodes = {root, placed, mesh};
    m.root_node = 0;

    assets::AnimationClip clip; clip.duration_seconds = 1.0f;
    assets::AnimationClip::NodeTrack d; d.target_node_name = "door 04a";
    d.translation = {{0.0f, kDoorT}, {1.0f, kDoorT + glm::vec3(0, 18, 0)}};
    clip.tracks = {d};
    clip.rest_locals["door 04a"] =
        glm::translate(glm::mat4(1.0f), kDoorT) * rot_z(30.0f);   // == placement

    auto w0 = renderer::compose_node_worlds(
        m, glm::mat4(1.0f), renderer::sample_node_overrides(clip, m, 0.0f));
    EXPECT_NEAR(glm::length(glm::vec3(w0[2][3]) - kDoorT), 0.0f, 1e-3f);
    expect_rot_z(w0[2], 30.0f);                     // placement rotation intact

    auto w1 = renderer::compose_node_worlds(
        m, glm::mat4(1.0f), renderer::sample_node_overrides(clip, m, 0.5f));
    const glm::vec3 want = kDoorT + glm::vec3(0, 9, 0);
    EXPECT_NEAR(glm::length(glm::vec3(w1[2][3]) - want), 0.0f, 1e-3f);
    expect_rot_z(w1[2], 30.0f);
}

TEST(ResolveOverriddenNode, ResolvesToThePlacedNodeTheRestBakedClipOverrides) {
    // The chair coupling reads anim vs rest at the SAME node. With the binding
    // on the PLACED duplicate, the resolver must follow it there.
    auto m = nested_dup_seat();
    auto clip = rest_baked_reverse_clip();
    auto ov = renderer::sample_node_overrides(clip, m, 0.0f);
    const int idx = renderer::resolve_overridden_node(m, "console seat 01", ov);
    EXPECT_EQ(idx, 1) << "coupling must read the PLACED (overridden) node";
    // rest at that node is the console-facing placement; anim at t=0 is turned.
    std::unordered_map<int, glm::mat4> empty;
    auto rest = renderer::compose_node_worlds(m, glm::mat4(1.0f), empty);
    auto anim = renderer::compose_node_worlds(m, glm::mat4(1.0f), ov);
    expect_rot_z(rest[idx], 0.0f);
    expect_rot_z(anim[idx], -60.0f);
}

TEST(ResolveOverriddenNode, AnimAndRestResolveToSameOverriddenNode) {
    // The coupling reads anim (with overrides) and rest (compose ignores them,
    // but resolution must still target the overridden node so anim/rest are the
    // SAME node). Both calls pass the same override map to the resolver.
    auto m = dup_seat();
    std::unordered_map<int, glm::mat4> ov;
    ov[2] = glm::rotate(glm::mat4(1.0f), glm::radians(60.0f), glm::vec3(0,0,1));
    int idx = renderer::resolve_overridden_node(m, "console seat 01", ov);
    EXPECT_EQ(idx, 2);
    // anim world (override applied) differs from rest world (override ignored)
    // at THAT index -> a non-identity R_delta.
    auto anim = renderer::compose_node_worlds(m, glm::mat4(1.0f), ov);
    std::unordered_map<int, glm::mat4> empty;
    auto rest = renderer::compose_node_worlds(m, glm::mat4(1.0f), empty);
    glm::vec3 anim_col0 = glm::normalize(glm::vec3(anim[idx][0]));
    glm::vec3 rest_col0 = glm::normalize(glm::vec3(rest[idx][0]));
    EXPECT_GT(glm::length(anim_col0 - rest_col0), 0.1f);   // they differ (rotated)
}
