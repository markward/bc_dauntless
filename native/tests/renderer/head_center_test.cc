// renderer::skinned_head_center + HeadCenterCache (renderer/head_center.h).
//
// The head centre is the officer-zoom look-at point, so moving it out of the
// get_instance_head_center binding and optimising it (head_center.cc is built
// -O2 in every configuration) must not move it by one bit. reference_center
// below is the binding's body as it stood before the move, compiled with this
// test's own flags (-O0 in the Debug tree); every case compares bitwise.
#include <gtest/gtest.h>

#include <assets/model.h>
#include <assets/model_compose.h>
#include <renderer/bone_palette.h>
#include <renderer/head_center.h>
#include <renderer/window.h>

#include <glm/gtc/matrix_transform.hpp>

#include <cmath>
#include <cstring>
#include <filesystem>
#include <memory>
#include <optional>
#include <random>
#include <string>
#include <vector>
#include "support/content_root.h"

namespace {

namespace fs = std::filesystem;

// The get_instance_head_center body before renderer/head_center.cc existed
// (host_bindings.cc, main 7d3d9e5e9), minus the instance lookup and the world
// transform: the model-space centre, or nullopt where it returned None.
std::optional<glm::vec3> reference_center(const assets::Model* model,
                                          const std::vector<glm::mat4>& palette) {
    const bool use_mesh_range = model->head_mesh_begin >= 0;

    int head_bi = -1;
    if (!use_mesh_range) {
        for (std::size_t i = 0; i < model->skeleton.bones.size(); ++i) {
            if (model->skeleton.bones[i].name == "Bip01 Head") {
                head_bi = static_cast<int>(i);
                break;
            }
        }
    }

    glm::vec3 head_lo(1e30f), head_hi(-1e30f);
    glm::vec3 body_lo(1e30f), body_hi(-1e30f);
    bool any_head = false, any_body = false;
    auto scan = [&](std::size_t first_mesh) {
        for (std::size_t mesh_idx = first_mesh; mesh_idx < model->meshes.size();
             ++mesh_idx) {
            const auto& mesh = model->meshes[mesh_idx];
            const bool mesh_is_head =
                use_mesh_range &&
                static_cast<int>(mesh_idx) >= model->head_mesh_begin;
            const auto& cd = mesh.cpu_data();
            if (!cd) continue;
            for (const auto& v : cd->vertices) {
                const glm::vec4 p(v.position, 1.0f);
                glm::vec4 skinned(0.0f);
                float wsum = 0.0f;
                bool on_head = mesh_is_head;
                for (int k = 0; k < 4; ++k) {
                    const float w = static_cast<float>(v.bone_weights[k]) / 255.0f;
                    if (w <= 0.0f) continue;
                    const std::size_t bi =
                        static_cast<std::size_t>(v.bone_indices[k]);
                    if (bi >= palette.size()) continue;   // GPU-safe guard
                    skinned += w * (palette[bi] * p);
                    wsum += w;
                    if (!use_mesh_range && static_cast<int>(bi) == head_bi) {
                        on_head = true;
                    }
                }
                if (wsum <= 0.0f) continue;
                const glm::vec3 s(skinned);
                body_lo = glm::min(body_lo, s);
                body_hi = glm::max(body_hi, s);
                any_body = true;
                if (on_head) {
                    head_lo = glm::min(head_lo, s);
                    head_hi = glm::max(head_hi, s);
                    any_head = true;
                }
            }
        }
    };
    if (use_mesh_range)
        scan(static_cast<std::size_t>(model->head_mesh_begin));
    if (!any_head) {
        body_lo = glm::vec3(1e30f);
        body_hi = glm::vec3(-1e30f);
        any_body = false;
        scan(0);
    }
    if (any_head)      return 0.5f * (head_lo + head_hi);
    else if (any_body) return 0.5f * (body_lo + body_hi);
    return std::nullopt;
}

bool bits_equal(const glm::vec3& a, const glm::vec3& b) {
    return std::memcmp(&a, &b, sizeof(glm::vec3)) == 0;
}

void expect_same_bits(const std::optional<glm::vec3>& want,
                      const std::optional<glm::vec3>& got) {
    ASSERT_EQ(want.has_value(), got.has_value());
    if (!want) return;
    EXPECT_TRUE(bits_equal(*want, *got))
        << "want (" << want->x << ", " << want->y << ", " << want->z
        << ") got (" << got->x << ", " << got->y << ", " << got->z << ")";
}

// A palette of arbitrary affine matrices: rounding differences between two
// implementations show up only when the products are not exact.
std::vector<glm::mat4> random_palette(std::size_t n, std::uint32_t seed) {
    std::mt19937 rng(seed);
    std::uniform_real_distribution<float> d(-2.0f, 2.0f);
    std::vector<glm::mat4> out(n);
    for (auto& m : out) {
        for (int c = 0; c < 3; ++c)
            for (int r = 0; r < 3; ++r) m[c][r] = d(rng);
        m[3] = glm::vec4(d(rng) * 50.0f, d(rng) * 50.0f, d(rng) * 50.0f, 1.0f);
    }
    return out;
}

assets::MeshCpu::Vertex vert(std::mt19937& rng, int bones, int bone_count) {
    std::uniform_real_distribution<float> d(-40.0f, 40.0f);
    std::uniform_int_distribution<int> b(0, bone_count - 1);
    assets::MeshCpu::Vertex v;
    v.position = {d(rng), d(rng), d(rng)};
    // Weights in the shapes the loader writes: one rigid bone, or up to four
    // that sum to about 255.
    const int shares[4][4] = {{255, 0, 0, 0}, {128, 127, 0, 0},
                              {100, 80, 75, 0}, {70, 65, 60, 60}};
    for (int k = 0; k < bones; ++k) {
        v.bone_indices[k] = static_cast<std::uint8_t>(b(rng));
        v.bone_weights[k] = static_cast<std::uint8_t>(shares[bones - 1][k]);
    }
    return v;
}

assets::Mesh mesh_of(std::vector<assets::MeshCpu::Vertex> verts) {
    assets::Mesh m;
    assets::MeshCpu cd;
    cd.vertices = std::move(verts);
    m.set_cpu_data(std::move(cd));
    return m;
}

// body meshes, then head meshes; head_mesh_begin = number of body meshes
// (or -1 with `mesh_range` false, the non-composed fallback).
assets::Model synthetic_model(bool mesh_range, std::uint32_t seed,
                              int bone_count = 12) {
    std::mt19937 rng(seed);
    assets::Model m;
    for (int i = 0; i < bone_count; ++i) {
        assets::Bone bone;
        bone.name = (i == 5) ? "Bip01 Head" : "Bip01 Bone" + std::to_string(i);
        m.skeleton.bones.push_back(bone);
    }
    for (int mesh = 0; mesh < 4; ++mesh) {
        std::vector<assets::MeshCpu::Vertex> verts;
        for (int i = 0; i < 200; ++i)
            verts.push_back(vert(rng, 1 + (i % 4), bone_count));
        m.meshes.push_back(mesh_of(std::move(verts)));
    }
    m.head_mesh_begin = mesh_range ? 2 : -1;
    return m;
}

}  // namespace

TEST(HeadCenter, MeshRangeHeadMatchesReferenceBitForBit) {
    for (std::uint32_t seed = 1; seed <= 20; ++seed) {
        const assets::Model m = synthetic_model(true, seed);
        const auto pal = random_palette(m.skeleton.bones.size(), seed * 7u);
        expect_same_bits(reference_center(&m, pal),
                         renderer::skinned_head_center(m, pal));
    }
}

TEST(HeadCenter, HeadBoneFallbackMatchesReferenceBitForBit) {
    for (std::uint32_t seed = 1; seed <= 20; ++seed) {
        const assets::Model m = synthetic_model(false, seed);
        const auto pal = random_palette(m.skeleton.bones.size(), seed * 11u);
        expect_same_bits(reference_center(&m, pal),
                         renderer::skinned_head_center(m, pal));
    }
}

TEST(HeadCenter, NoHeadBoneFallsBackToBodyCentre) {
    assets::Model m = synthetic_model(false, 3);
    m.skeleton.bones[5].name = "Bip01 Neck";
    const auto pal = random_palette(m.skeleton.bones.size(), 5);
    const auto want = reference_center(&m, pal);
    ASSERT_TRUE(want.has_value());
    expect_same_bits(want, renderer::skinned_head_center(m, pal));
}

TEST(HeadCenter, UnskinnedHeadRangeFallsBackToBodyCentre) {
    assets::Model m = synthetic_model(true, 4);
    // Head meshes keep their vertices but lose every weight: no skinned head
    // vertex, so the centre is the whole body's.
    for (std::size_t i = 2; i < m.meshes.size(); ++i) {
        assets::MeshCpu cd = *m.meshes[i].cpu_data();
        for (auto& v : cd.vertices) v.bone_weights = {0, 0, 0, 0};
        m.meshes[i].set_cpu_data(std::move(cd));
    }
    const auto pal = random_palette(m.skeleton.bones.size(), 9);
    const auto want = reference_center(&m, pal);
    ASSERT_TRUE(want.has_value());
    expect_same_bits(want, renderer::skinned_head_center(m, pal));
}

TEST(HeadCenter, BoneIndicesPastThePaletteAreIgnored) {
    const assets::Model m = synthetic_model(true, 6, /*bone_count=*/12);
    // A palette shorter than the skeleton: indices >= 8 hit the GPU-safe guard.
    const auto pal = random_palette(8, 13);
    expect_same_bits(reference_center(&m, pal),
                     renderer::skinned_head_center(m, pal));
}

TEST(HeadCenter, NothingSkinnedIsNullopt) {
    assets::Model m = synthetic_model(true, 2);
    const std::vector<glm::mat4> empty_palette;
    EXPECT_FALSE(renderer::skinned_head_center(m, empty_palette).has_value());
    m.meshes.clear();
    const auto pal = random_palette(m.skeleton.bones.size(), 1);
    EXPECT_FALSE(renderer::skinned_head_center(m, pal).has_value());
}

// --- the real officer the bridge uses: composed body + welded head ---------

TEST(HeadCenter, ComposedOfficerMatchesReferenceBitForBit) {
    const fs::path chars =
        test_support::game_root() / "data" / "Models" / "Characters";
    const fs::path body = chars / "Bodies/BodyMaleM/BodyMaleM.NIF";
    const fs::path head = chars / "Heads/HeadMiguel/miguel_head.NIF";
    if (!fs::is_regular_file(body) || !fs::is_regular_file(head))
        GTEST_SKIP() << "character NIFs not installed";
    std::unique_ptr<renderer::Window> w;
    try {
        w = std::make_unique<renderer::Window>(64, 64, "head-center-test", false);
    } catch (const std::runtime_error& e) {
        GTEST_SKIP() << "no GL context: " << e.what();
    }
    const assets::Model m =
        assets::compose_officer_model(body, {}, head, {}, "Bip01 Head");
    ASSERT_GE(m.head_mesh_begin, 0);

    const auto& sk = m.skeleton;
    std::vector<std::vector<glm::mat4>> palettes;
    palettes.push_back(renderer::build_bone_palette(sk, nullptr));
    // A bent neck, then an arbitrary pose on every bone.
    std::vector<glm::mat4> locals(sk.bones.size());
    std::mt19937 rng(42);
    std::uniform_real_distribution<float> ang(-0.6f, 0.6f);
    for (std::size_t i = 0; i < sk.bones.size(); ++i) {
        locals[i] = sk.bones[i].local_transform;
        if (sk.bones[i].name == "Bip01 Neck")
            locals[i] = locals[i] * glm::rotate(glm::mat4(1.0f), 0.44f,
                                                glm::vec3(1.0f, 0.0f, 0.0f));
    }
    palettes.push_back(renderer::build_bone_palette(sk, &locals));
    for (std::size_t i = 0; i < sk.bones.size(); ++i)
        locals[i] = locals[i] * glm::rotate(glm::mat4(1.0f), ang(rng),
                                            glm::normalize(glm::vec3(
                                                ang(rng), ang(rng), 1.0f)));
    palettes.push_back(renderer::build_bone_palette(sk, &locals));

    for (const auto& pal : palettes) {
        const auto want = reference_center(&m, pal);
        ASSERT_TRUE(want.has_value());
        expect_same_bits(want, renderer::skinned_head_center(m, pal));
    }
}

// --- HeadCenterCache --------------------------------------------------------

namespace {
constexpr scenegraph::InstanceId kA{3, 1};
constexpr scenegraph::InstanceId kB{4, 1};
}

TEST(HeadCenterCache, SameInputsReturnTheCachedBitsWithoutRecomputing) {
    const assets::Model m = synthetic_model(true, 8);
    const auto pal = random_palette(m.skeleton.bones.size(), 21);
    renderer::HeadCenterCache cache;
    const auto first = cache.get(kA, 1, m, pal);
    const auto second = cache.get(kA, 1, m, pal);
    EXPECT_EQ(cache.computes(), 1u);
    expect_same_bits(renderer::skinned_head_center(m, pal), first);
    expect_same_bits(first, second);
}

TEST(HeadCenterCache, AnyPaletteBitChangeRecomputes) {
    const assets::Model m = synthetic_model(true, 8);
    auto pal = random_palette(m.skeleton.bones.size(), 21);
    pal[0][2][2] = 0.0f;
    renderer::HeadCenterCache cache;
    (void)cache.get(kA, 1, m, pal);
    // +0 -> -0 compares equal as a float but is a different palette.
    pal[0][2][2] = -0.0f;
    const auto got = cache.get(kA, 1, m, pal);
    EXPECT_EQ(cache.computes(), 2u);
    expect_same_bits(renderer::skinned_head_center(m, pal), got);
    // A real pose change (the breathing idle rebuilds the palette each frame).
    pal[3][3][0] += 1.0f;
    expect_same_bits(renderer::skinned_head_center(m, pal),
                     cache.get(kA, 1, m, pal));
    EXPECT_EQ(cache.computes(), 3u);
}

TEST(HeadCenterCache, ModelHandleOrModelChangeRecomputes) {
    const assets::Model m1 = synthetic_model(true, 8);
    const assets::Model m2 = synthetic_model(true, 9);
    const auto pal = random_palette(m1.skeleton.bones.size(), 21);
    renderer::HeadCenterCache cache;
    (void)cache.get(kA, 1, m1, pal);
    (void)cache.get(kA, 2, m1, pal);
    EXPECT_EQ(cache.computes(), 2u);
    expect_same_bits(renderer::skinned_head_center(m2, pal),
                     cache.get(kA, 2, m2, pal));
    EXPECT_EQ(cache.computes(), 3u);
}

TEST(HeadCenterCache, InstancesAreCachedIndependently) {
    const assets::Model m = synthetic_model(true, 8);
    const auto pa = random_palette(m.skeleton.bones.size(), 1);
    const auto pb = random_palette(m.skeleton.bones.size(), 2);
    renderer::HeadCenterCache cache;
    (void)cache.get(kA, 1, m, pa);
    (void)cache.get(kB, 1, m, pb);
    expect_same_bits(renderer::skinned_head_center(m, pa), cache.get(kA, 1, m, pa));
    expect_same_bits(renderer::skinned_head_center(m, pb), cache.get(kB, 1, m, pb));
    EXPECT_EQ(cache.computes(), 2u);
    // A generation bump is a different instance.
    (void)cache.get(scenegraph::InstanceId{3, 2}, 1, m, pa);
    EXPECT_EQ(cache.computes(), 3u);
}

TEST(HeadCenterCache, ClearForgetsEverything) {
    const assets::Model m = synthetic_model(true, 8);
    const auto pal = random_palette(m.skeleton.bones.size(), 1);
    renderer::HeadCenterCache cache;
    (void)cache.get(kA, 1, m, pal);
    cache.clear();
    EXPECT_EQ(cache.size(), 0u);
    (void)cache.get(kA, 1, m, pal);
    EXPECT_EQ(cache.computes(), 2u);
}

TEST(HeadCenterCache, StaysBounded) {
    const assets::Model m = synthetic_model(true, 8);
    const auto pal = random_palette(m.skeleton.bones.size(), 1);
    renderer::HeadCenterCache cache;
    for (std::uint32_t i = 0; i < 10 * renderer::HeadCenterCache::kMaxEntries; ++i)
        (void)cache.get(scenegraph::InstanceId{i, 1}, 1, m, pal);
    EXPECT_LE(cache.size(), renderer::HeadCenterCache::kMaxEntries);
}
