// §3.5 bone rebinding (the BC "weld"): weld_head_bones maps every head-skeleton
// bone onto the body skeleton by NAME. Equal binds map directly; a bind-pose
// mismatch appends an ALIAS bone (rides the body bone's pose, skins with the
// HEAD's inverse bind — BC composes body node worlds with the head controller's
// own bind offsets); a head-only bone (Bip01 Ponytail1) is appended for real.
#include <gtest/gtest.h>

#include <assets/model_compose.h>
#include <assets/skeleton.h>

#include <glm/gtc/matrix_transform.hpp>

#include <string>
#include <vector>

namespace {

// Two-bone skeleton: "Bip01" root (identity bind) + "Bip01 Head" child with a
// bind-world at Z = head_bind_z.
assets::Skeleton two_bone(float head_bind_z) {
    assets::Skeleton sk;
    assets::Bone root;
    root.name = "Bip01";
    root.parent_index = -1;
    assets::Bone head;
    head.name = "Bip01 Head";
    head.parent_index = 0;
    head.local_transform =
        glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 0.0f, head_bind_z));
    head.inverse_bind_pose =
        glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 0.0f, -head_bind_z));
    sk.bones = {root, head};
    sk.root_bone_index = 0;
    return sk;
}

}  // namespace

TEST(WeldHeadBones, EqualBindsMapDirectlyNoAppends) {
    assets::Skeleton body = two_bone(10.0f);
    // Head lists its bones in a DIFFERENT order to prove the mapping is by
    // NAME, not by index.
    assets::Skeleton head;
    assets::Bone hhead;
    hhead.name = "Bip01 Head";
    hhead.parent_index = 1;
    hhead.inverse_bind_pose =
        glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 0.0f, -10.0f));
    assets::Bone hroot;
    hroot.name = "Bip01";
    hroot.parent_index = -1;
    head.bones = {hhead, hroot};
    head.root_bone_index = 1;

    const std::size_t before = body.bones.size();
    const std::vector<int> map = assets::weld_head_bones(body, head);

    ASSERT_EQ(map.size(), 2u);
    EXPECT_EQ(map[0], 1);  // head's "Bip01 Head" -> body index 1
    EXPECT_EQ(map[1], 0);  // head's "Bip01"      -> body index 0
    EXPECT_EQ(body.bones.size(), before);  // nothing appended
}

TEST(WeldHeadBones, BindMismatchAppendsAliasWithHeadBind) {
    assets::Skeleton body = two_bone(10.0f);
    assets::Skeleton head = two_bone(4.0f);  // same names, different binds

    const std::vector<int> map = assets::weld_head_bones(body, head);

    EXPECT_EQ(map[0], 0);       // root binds equal (identity) -> direct
    ASSERT_EQ(map[1], 2);       // head bone -> appended alias
    ASSERT_EQ(body.bones.size(), 3u);
    const assets::Bone& alias = body.bones[2];
    EXPECT_EQ(alias.name,
              std::string("Bip01 Head") +
                  std::string(assets::kHeadBindAliasSuffix));
    EXPECT_EQ(alias.parent_index, 1);  // rides the body's real "Bip01 Head"
    EXPECT_EQ(alias.local_transform, glm::mat4(1.0f));
    EXPECT_EQ(alias.inverse_bind_pose,
              glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 0.0f, -4.0f)));
}

TEST(WeldHeadBones, AliasReusedNotDuplicated) {
    assets::Skeleton body = two_bone(10.0f);
    assets::Skeleton head = two_bone(4.0f);

    const std::vector<int> m1 = assets::weld_head_bones(body, head);
    const std::vector<int> m2 = assets::weld_head_bones(body, head);

    EXPECT_EQ(m1[1], m2[1]);
    EXPECT_EQ(body.bones.size(), 3u);  // still exactly one alias
}

TEST(WeldHeadBones, HeadOnlyBoneAppendedUnderMappedParent) {
    assets::Skeleton body = two_bone(10.0f);
    assets::Skeleton head = two_bone(10.0f);  // binds match
    assets::Bone pony;
    pony.name = "Bip01 Ponytail1";  // body skeletons lack this bone (corpus)
    pony.parent_index = 1;          // under the head's "Bip01 Head"
    pony.local_transform =
        glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, -2.0f, 1.0f));
    pony.inverse_bind_pose =
        glm::translate(glm::mat4(1.0f), glm::vec3(0.0f, 2.0f, -11.0f));
    head.bones.push_back(pony);

    const std::vector<int> map = assets::weld_head_bones(body, head);

    ASSERT_EQ(map.size(), 3u);
    ASSERT_EQ(map[2], 2);
    const assets::Bone& b = body.bones[2];
    EXPECT_EQ(b.name, "Bip01 Ponytail1");  // name KEPT: clips may drive it
    EXPECT_EQ(b.parent_index, 1);          // under the body's "Bip01 Head"
    EXPECT_EQ(b.local_transform, pony.local_transform);
    EXPECT_EQ(b.inverse_bind_pose, pony.inverse_bind_pose);
}
