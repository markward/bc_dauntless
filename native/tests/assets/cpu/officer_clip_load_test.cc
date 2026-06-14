#include <gtest/gtest.h>
#include <assets/animation.h>
#include <filesystem>

// SP2: assemble_officer requires a GL context (it uploads), so test the
// underlying contract at the asset layer: the placement clip loads non-empty
// with tracks. This is the exact operation assemble_officer does when it fills
// composed.animations = load_animation_clips(placement).
TEST(OfficerClipLoad, PlacementClipLoadsNonEmpty) {
    namespace fs = std::filesystem;
    const char* clip = "game/data/animations/db_stand_t_l.nif";
    if (!fs::exists(clip)) GTEST_SKIP() << "asset missing: " << clip;
    auto clips = assets::load_animation_clips(clip);
    ASSERT_FALSE(clips.empty());
    EXPECT_GT(clips.front().duration_seconds, 0.0f);
    EXPECT_FALSE(clips.front().tracks.empty());
}
