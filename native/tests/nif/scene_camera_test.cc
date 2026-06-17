// native/tests/nif/scene_camera_test.cc — find_first_camera against real BC sets.
#include <gtest/gtest.h>

#include <nif/file.h>
#include <nif/scene_camera.h>

#include <filesystem>

namespace {
std::filesystem::path asset(const char* rel) {
    return std::filesystem::path(OPEN_STBC_PROJECT_ROOT) / rel;
}
}  // namespace

TEST(FindFirstCamera, StarbaseControlHasCamera) {
    auto path = asset("game/data/Models/Sets/StarbaseControl/starbasecontrolRM.NIF");
    if (!std::filesystem::exists(path)) GTEST_SKIP() << path;
    auto f = nif::load(path);
    auto cam = nif::find_first_camera(f);
    ASSERT_TRUE(cam.has_value());
    // Frustum sides are non-degenerate (left<right, bottom<top).
    EXPECT_LT(cam->frustum[0], cam->frustum[1]);
    EXPECT_LT(cam->frustum[3], cam->frustum[2]);
    EXPECT_GT(cam->far_distance, cam->near_distance);
}

TEST(FindFirstCamera, DBridgeHasNoCamera) {
    auto path = asset("game/data/Models/Sets/DBridge/DBridge.NIF");
    if (!std::filesystem::exists(path)) GTEST_SKIP() << path;
    auto f = nif::load(path);
    EXPECT_FALSE(nif::find_first_camera(f).has_value());
}

TEST(FindFirstCamera, EBridgeHasNoCamera) {
    auto path = asset("game/data/Models/Sets/EBridge/EBridge.NIF");
    if (!std::filesystem::exists(path)) GTEST_SKIP() << path;
    auto f = nif::load(path);
    EXPECT_FALSE(nif::find_first_camera(f).has_value());
}
