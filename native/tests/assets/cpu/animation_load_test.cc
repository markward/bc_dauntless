#include <gtest/gtest.h>

#include <assets/animation.h>

#include <filesystem>
#include "support/content_root.h"

// load_animation_clips must extract a clip from an animation-ONLY NIF (no
// NiTriShape geometry) — the case that defeats the full model build.
TEST(LoadAnimationClips, ExtractsClipFromPlacementNif) {
    namespace fs = std::filesystem;
    const fs::path game = test_support::game_root();
    const fs::path nif = game / "data" / "animations" / "db_stand_t_l.nif";
    if (!fs::is_regular_file(nif)) GTEST_SKIP() << "asset missing: " << nif;

    auto clips = assets::load_animation_clips(nif);
    ASSERT_FALSE(clips.empty()) << "placement NIF yielded no animation clip";
    const auto& clip = clips.front();
    EXPECT_GT(clip.tracks.size(), 0u) << "clip has no node tracks";
    EXPECT_GT(clip.duration_seconds, 0.0f);
}

TEST(LoadAnimationClips, MissingFileReturnsEmpty) {
    EXPECT_TRUE(assets::load_animation_clips("/no/such/file.nif").empty());
}
