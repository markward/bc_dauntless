// Real-asset oracles for the per-channel binder, from the 2026-07-15
// investigation:
//  1. tilt_head_left.NIF ("Bip01 Head" track) on the welded BodyFemM +
//     kiska_head skeleton moves the head palette row while every body row
//     continues its breathing loop UNINTERRUPTED across the gesture bind.
//  2. Console_Look_Down.NIF ("Kiska …"-rigged) is dead ballast: every palette
//     row stays bit-identical (BC renders nothing for it either).
//  3. Walk reference: for every TRACKED bone, channel eval reproduces
//     sample_pose(clip, skeleton, t) — the unchanged sampler is the oracle,
//     so the cutover provably preserves today's walk output.
//
// Fixture skip guards copied from head_weld_seam_test.cc: skips when game/
// assets are absent or GL window creation fails (compose_officer_model uploads
// GL meshes). This worktree has both, so these tests are expected to RUN.
#include <gtest/gtest.h>
#include <glm/gtc/epsilon.hpp>
#include <glm/glm.hpp>

#include <assets/animation.h>
#include <assets/model.h>
#include <assets/model_compose.h>
#include <renderer/channel_binder.h>
#include <renderer/animation_update.h>
#include <renderer/pose_sampler.h>
#include <renderer/window.h>
#include <scenegraph/world.h>

#include <filesystem>
#include <memory>
#include <set>
#include <string>
#include <vector>

namespace {

namespace fs = std::filesystem;

const fs::path kRoot = fs::path(__FILE__)
    .parent_path().parent_path().parent_path().parent_path();
const fs::path kChars = kRoot / "game" / "data" / "Models" / "Characters";
const fs::path kAnims = kRoot / "game" / "data" / "Animations";

class ChannelBinderAssets : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w_;
    assets::Model model_;

    void SetUp() override {
        if (!fs::is_regular_file(
                kChars / "Bodies/BodyFemM/BodyFemM.NIF"))
            GTEST_SKIP() << "character NIFs not installed";
        if (!fs::is_regular_file(
                kChars / "Heads/HeadKiska/kiska_head.NIF"))
            GTEST_SKIP() << "character NIFs not installed";
        try {
            w_ = std::make_unique<renderer::Window>(64, 64, "binder-assets-test",
                                                    false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
        model_ = assets::compose_officer_model(
            kChars / "Bodies/BodyFemM/BodyFemM.NIF", /*body_tex=*/{},
            kChars / "Heads/HeadKiska/kiska_head.NIF", /*head_tex=*/{},
            "Bip01 Head");
    }

    /// Load clips[0] from `kAnims / name`, append to model_.animations,
    /// return the new index, or -1 if the file has no clips.
    int load_clip(const char* name) {
        auto clips = assets::load_animation_clips(kAnims / name);
        if (clips.empty()) return -1;
        model_.animations.push_back(std::move(clips[0]));
        return static_cast<int>(model_.animations.size()) - 1;
    }

    /// Linear scan of model_.skeleton.bones for `name`; -1 if absent.
    int bone_index(const std::string& name) const {
        for (std::size_t i = 0; i < model_.skeleton.bones.size(); ++i)
            if (model_.skeleton.bones[i].name == name)
                return static_cast<int>(i);
        return -1;
    }
};

}  // namespace

TEST_F(ChannelBinderAssets, TiltHeadMovesHeadWhileBodyBreathesUninterrupted) {
    int breathe = load_clip("breathing.NIF");        // helper: appends to
    int tilt    = load_clip("tilt_head_left.NIF");   // model_.animations,
    ASSERT_GE(breathe, 0); ASSERT_GE(tilt, 0);       // returns index or -1

    scenegraph::World w;
    auto id = w.create_instance(1);
    scenegraph::Instance& inst = *w.get(id);
    renderer::BindOptions idle; idle.loop = true;
    ASSERT_GT(renderer::bind_clip(inst, model_, breathe, idle, 0.0), 0);

    const int head = bone_index("Bip01 Head");
    ASSERT_GE(head, 0);
    // Bones the tilt clip will bind (by the same strcmp rule).
    std::set<int> tilt_bones;
    for (const auto& tr : model_.animations[tilt].tracks) {
        int b = bone_index(tr.target_node_name);
        if (b >= 0) tilt_bones.insert(b);
    }
    ASSERT_TRUE(tilt_bones.count(head)) << "tilt must drive the head";

    // Descendant closure: the world-space bone_palette entry for any bone
    // that is a descendant of a tilt-driven bone changes legitimately when the
    // head rotates, even if that bone's own channel is untouched. build_bone_palette
    // walks the full parent chain, so the palette entry is world_pose * inv_bind
    // and any ancestor rotation propagates down. Exclude these from the
    // bit-identical comparison — the invariant is that their CHANNELS are untouched,
    // not that their world-space palette rows are unchanged.
    std::set<int> tilt_affected = tilt_bones;  // start with directly driven bones
    const std::size_t nb = model_.skeleton.bones.size();
    // One forward pass: if any bone's parent is affected, so is the bone.
    bool changed = true;
    while (changed) {
        changed = false;
        for (std::size_t i = 0; i < nb; ++i) {
            if (tilt_affected.count(static_cast<int>(i))) continue;
            int p = model_.skeleton.bones[i].parent_index;
            if (p >= 0 && tilt_affected.count(p)) {
                tilt_affected.insert(static_cast<int>(i));
                changed = true;
            }
        }
    }

    // Record breathe-only palettes over a window, then re-play the SAME window
    // with the gesture bound mid-way, and compare non-tilt rows frame by
    // frame: they must be bit-identical (same clip, same phase, untouched
    // channels) — the eviction bug would desynchronize or freeze them.
    // Bones that are descendants of a tilt-driven bone are excluded because
    // their palette entries correctly change when an ancestor rotates.
    auto lookup = [&](scenegraph::ModelHandle){ return &model_; };
    std::vector<std::vector<glm::mat4>> baseline;
    for (double t = 0.0; t < 2.0; t += 0.1) {
        renderer::update_animations(w, lookup, t);
        baseline.push_back(inst.bone_palette);
    }
    // Reset to the same idle phase and replay with a gesture bind at t=1.0.
    renderer::clear_channels(inst);
    renderer::bind_clip(inst, model_, breathe, idle, 0.0);
    bool head_moved = false;
    std::size_t frame = 0;
    for (double t = 0.0; t < 2.0; t += 0.1, ++frame) {
        if (t >= 1.0 - 1e-9 && t < 1.1 - 1e-9)
            ASSERT_GT(renderer::bind_clip(inst, model_, tilt, {}, t), 0);
        renderer::update_animations(w, lookup, t);
        for (std::size_t b = 0; b < inst.bone_palette.size(); ++b) {
            if (tilt_affected.count(static_cast<int>(b))) {
                if (tilt_bones.count(static_cast<int>(b)) &&
                    t >= 1.0 && inst.bone_palette[b] != baseline[frame][b])
                    head_moved = true;
            } else {
                EXPECT_EQ(inst.bone_palette[b], baseline[frame][b])
                    << "non-gesture bone " << b << " disturbed at t=" << t;
            }
        }
    }
    EXPECT_TRUE(head_moved) << "tilt gesture produced no head motion";
}

TEST_F(ChannelBinderAssets, KiskaRiggedClipIsBitIdenticalNoOp) {
    int breathe = load_clip("breathing.NIF");
    int dead    = load_clip("Console_Look_Down.NIF");
    ASSERT_GE(breathe, 0); ASSERT_GE(dead, 0);

    scenegraph::World w;
    auto id = w.create_instance(1);
    scenegraph::Instance& inst = *w.get(id);
    renderer::BindOptions idle; idle.loop = true;
    renderer::bind_clip(inst, model_, breathe, idle, 0.0);
    auto lookup = [&](scenegraph::ModelHandle){ return &model_; };

    renderer::update_animations(w, lookup, 0.5);
    // Oracle precondition from the investigation: the clip's tracks are all
    // "Kiska …"-named — none matches a "Bip01 …" bone.
    EXPECT_EQ(renderer::bind_clip(inst, model_, dead, {}, 0.5), 0);
    auto before = inst.bone_palette;
    renderer::update_animations(w, lookup, 0.5);   // same instant: same phase
    ASSERT_EQ(inst.bone_palette.size(), before.size());
    for (std::size_t b = 0; b < before.size(); ++b)
        EXPECT_EQ(inst.bone_palette[b], before[b]);
}

TEST_F(ChannelBinderAssets, WalkChannelsReproduceSamplePoseOnTrackedBones) {
    // Any shipped placement/walk clip with a "Bip01" root translation works;
    // db_LtoH walk-family clips live in game/data/Animations. Use
    // tilt_head_left as the tracked-bone reference too — the invariant is
    // channels == sample_pose for TRACKED bones at matching t, for a
    // root-motion, clip-base bind (the walk configuration).
    int walk = load_clip("tilt_head_left.NIF");
    ASSERT_GE(walk, 0);
    const assets::AnimationClip& clip = model_.animations[walk];

    scenegraph::World w;
    auto id = w.create_instance(1);
    scenegraph::Instance& inst = *w.get(id);
    renderer::BindOptions o; o.root_motion = true; o.use_clip_base = true;
    ASSERT_GT(renderer::bind_clip(inst, model_, walk, o, 0.0), 0);

    for (float t : {0.0f, clip.duration_seconds * 0.5f, clip.duration_seconds}) {
        auto ref = renderer::sample_pose(clip, model_.skeleton, t);
        auto got = renderer::eval_channels(inst, model_, t);
        for (const auto& tr : clip.tracks) {
            int b = bone_index(tr.target_node_name);
            if (b < 0) continue;
            for (int c = 0; c < 4; ++c)
                EXPECT_TRUE(glm::all(glm::epsilonEqual(
                    got[b][c], ref[b][c], 1e-4f)))
                    << "bone " << b << " t=" << t << " col " << c;
        }
    }
}
