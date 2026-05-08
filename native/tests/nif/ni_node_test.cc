// native/tests/nif/ni_node_test.cc — NiNode parser against real BC samples.
#include <gtest/gtest.h>

#include <nif/block.h>
#include <nif/file.h>

#include <filesystem>
#include <variant>

namespace {

const nif::NiNode* find_first_ninode(const nif::File& f) {
    for (const auto& b : f.blocks) {
        if (auto* n = std::get_if<nif::NiNode>(&b)) return n;
    }
    return nullptr;
}

}  // namespace

TEST(NiNodeParser, GalaxyRootNiNodeParses) {
    auto path = std::filesystem::path(OPEN_STBC_PROJECT_ROOT)
                / "game/data/Models/Ships/Galaxy/Galaxy.nif";
    if (!std::filesystem::exists(path)) GTEST_SKIP() << path;
    auto f = nif::load(path);
    ASSERT_FALSE(f.blocks.empty()) << "Walker stopped before parsing any blocks";
    auto* root = find_first_ninode(f);
    ASSERT_NE(root, nullptr) << "First block should be a NiNode";

    EXPECT_FLOAT_EQ(root->av.translation.x, 0.0f);
    EXPECT_FLOAT_EQ(root->av.translation.y, 0.0f);
    EXPECT_FLOAT_EQ(root->av.translation.z, 0.0f);
    EXPECT_FLOAT_EQ(root->av.scale, 1.0f);
    EXPECT_FLOAT_EQ(root->av.rotation.m[0], 1.0f);
    EXPECT_FLOAT_EQ(root->av.rotation.m[4], 1.0f);
    EXPECT_FLOAT_EQ(root->av.rotation.m[8], 1.0f);
    EXPECT_FALSE(root->av.has_bounding_volume);
    EXPECT_GE(root->av.property_links.size(), 1u);
    EXPECT_GE(root->child_links.size(), 1u);
}

TEST(NiNodeParser, GalaxyParsesAtLeastOneBlock) {
    auto path = std::filesystem::path(OPEN_STBC_PROJECT_ROOT)
                / "game/data/Models/Ships/Galaxy/Galaxy.nif";
    if (!std::filesystem::exists(path)) GTEST_SKIP() << path;
    auto f = nif::load(path);
    EXPECT_GE(f.blocks.size(), 1u);
}
