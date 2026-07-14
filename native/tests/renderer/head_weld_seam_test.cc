// §3.5's seam guarantee as a regression net: both meshes are skinned to ONE
// shared skeleton, so coincident, identically-weighted seam vertices stay
// together under any pose — with zero runtime reconciliation. Two real-NIF
// checks:
//   * matched pair (BodyMaleS + miguel_head, bit-identical binds): seam pairs
//     with byte-equal weights stay coincident under a bent neck;
//   * mismatched pair (BodyMaleM + miguel_head, ~5.9-unit bind deltas): the
//     alias-bone palette lifts the head onto the body's neck at bind (the old
//     vertex-rebase regression), and seam pairs still hold under a bent neck.
// Character model units (~78/body height), not GU. Skips without game/ assets
// or a GL context (compose_officer_model uploads GL meshes).
//
// Measured note on the mismatched pair (see task-4-report.md for the full
// diagnostic transcript): unlike BodyMaleS+miguel_head — which are literally
// cloned vertex data at the collar (matched test finds byte-identical-weight
// pairs coincident to <1e-3) — BodyMaleM's collar and miguel_head's neck ring
// are INDEPENDENTLY weight-painted meshes: an exhaustive 611x143 sweep found
// zero byte-equal-weight pairs closer than 7.8 units (a coincidental match
// elsewhere on the body), while the true seam-adjacent vertices sit 0.16-0.28
// units apart with weight bytes differing by up to ~30/255. That gap is small
// (<0.4% of body height) and, crucially, CONSTANT under the bent-neck pose
// (drift <0.004 units across all 7 candidates) — i.e. the two independently
// authored meshes don't coincide exactly, but the alias weld ties them
// together rigidly, which is the actual "seam holds" invariant. So the
// mismatched-pair seam check below uses nearest-neighbor-by-position pairing
// (no weight-equality requirement — that signal simply isn't present in this
// real, independently-painted asset pair) and asserts the bind/bent-neck
// distance stays constant, rather than requiring byte-equal weights the way
// the matched-pair check does.
#include <gtest/gtest.h>

#include <assets/model.h>
#include <assets/model_compose.h>
#include <renderer/bone_palette.h>
#include <renderer/window.h>

#include <glm/gtc/matrix_transform.hpp>

#include <cmath>
#include <filesystem>
#include <limits>
#include <memory>
#include <vector>

namespace {

namespace fs = std::filesystem;

const fs::path kRoot = fs::path(__FILE__)
    .parent_path().parent_path().parent_path().parent_path();
const fs::path kChars = kRoot / "game" / "data" / "Models" / "Characters";

struct SkinnedVert {
    glm::vec3 pos;          // skinned position
    glm::u8vec4 idx, wt;    // binding bytes (for the equal-weights pair rule)
};

// CPU-skin every vertex of the meshes in [begin, end) through `palette` —
// exactly the shader's blend (skinned_bridge.vert): sum of w * (pal[b] * v).
std::vector<SkinnedVert> skin_range(const assets::Model& m,
                                    std::size_t begin, std::size_t end,
                                    const std::vector<glm::mat4>& palette) {
    std::vector<SkinnedVert> out;
    for (std::size_t mi = begin; mi < end && mi < m.meshes.size(); ++mi) {
        const auto& cpu = m.meshes[mi].cpu_data();
        if (!cpu) continue;
        for (const auto& v : cpu->vertices) {
            glm::vec4 sp(0.0f);
            for (int k = 0; k < 4; ++k) {
                const float w = v.bone_weights[k] / 255.0f;
                if (w <= 0.0f) continue;
                const int b = v.bone_indices[k];
                if (b < static_cast<int>(palette.size()))
                    sp += w * (palette[b] * glm::vec4(v.position, 1.0f));
            }
            out.push_back({glm::vec3(sp), v.bone_indices, v.bone_weights});
        }
    }
    return out;
}

// Bind-pose palette: locals = the skeleton's own bind locals (nullptr pose).
// Identity for real bones; the bind-delta for alias bones.
std::vector<glm::mat4> bind_palette(const assets::Skeleton& sk) {
    return renderer::build_bone_palette(sk, nullptr);
}

// Posed palette: bind locals with "Bip01 Neck" bent 25 degrees about X.
std::vector<glm::mat4> bent_neck_palette(const assets::Skeleton& sk) {
    std::vector<glm::mat4> locals(sk.bones.size());
    for (std::size_t i = 0; i < sk.bones.size(); ++i)
        locals[i] = sk.bones[i].local_transform;
    for (std::size_t i = 0; i < sk.bones.size(); ++i)
        if (sk.bones[i].name == "Bip01 Neck")
            locals[i] = locals[i] * glm::rotate(glm::mat4(1.0f),
                                                glm::radians(25.0f),
                                                glm::vec3(1.0f, 0.0f, 0.0f));
    return renderer::build_bone_palette(sk, &locals);
}

// Seam pairs: (body vert, head vert) coincident at bind (dist < pair_eps)
// with byte-equal weight vectors — §3.5's authoring invariant. Weight-vector
// equality compares the WEIGHT bytes sorted descending (they arrive sorted
// from fill_skin_weights), not the indices (body and head verts legitimately
// reference different palette entries on a mismatched pair).
struct SeamPair { std::size_t body, head; };
std::vector<SeamPair> find_seam_pairs(const std::vector<SkinnedVert>& body,
                                      const std::vector<SkinnedVert>& head,
                                      float pair_eps) {
    std::vector<SeamPair> pairs;
    for (std::size_t h = 0; h < head.size(); ++h)
        for (std::size_t b = 0; b < body.size(); ++b)
            if (glm::distance(body[b].pos, head[h].pos) < pair_eps &&
                body[b].wt == head[h].wt)
                pairs.push_back({b, h});
    return pairs;
}

// Nearest-neighbor seam pairs by POSITION ONLY (no weight-equality
// requirement): for each head vertex, the closest body vertex, kept if
// within pair_eps. Used for the mismatched pair, where body and head are
// independently weight-painted meshes (see file header) so byte-equal
// weights never occur near the seam, even though the positions do
// converge under the alias weld.
std::vector<SeamPair> find_nearest_pairs(const std::vector<SkinnedVert>& body,
                                         const std::vector<SkinnedVert>& head,
                                         float pair_eps) {
    std::vector<SeamPair> pairs;
    for (std::size_t h = 0; h < head.size(); ++h) {
        float best_d = std::numeric_limits<float>::max();
        std::size_t best_b = 0;
        for (std::size_t b = 0; b < body.size(); ++b) {
            const float d = glm::distance(body[b].pos, head[h].pos);
            if (d < best_d) { best_d = d; best_b = b; }
        }
        if (best_d < pair_eps) pairs.push_back({best_b, h});
    }
    return pairs;
}

class HeadWeldSeamTest : public ::testing::Test {
protected:
    std::unique_ptr<renderer::Window> w;

    void SetUp() override {
        if (!fs::is_regular_file(
                kChars / "Heads/HeadMiguel/miguel_head.NIF"))
            GTEST_SKIP() << "character NIFs not installed";
        try {
            w = std::make_unique<renderer::Window>(64, 64, "seam-test", false);
        } catch (const std::runtime_error& e) {
            GTEST_SKIP() << "no GL context: " << e.what();
        }
    }

    assets::Model compose(const char* body_dir, const char* body_nif) {
        return assets::compose_officer_model(
            kChars / "Bodies" / body_dir / body_nif, /*body_tex=*/{},
            kChars / "Heads/HeadMiguel/miguel_head.NIF", /*head_tex=*/{},
            "Bip01 Head");
    }
};

}  // namespace

TEST_F(HeadWeldSeamTest, MatchedPairSeamHoldsUnderBentNeck) {
    assets::Model m = compose("BodyMaleS", "BodyMaleS.nif");
    ASSERT_GE(m.head_mesh_begin, 0);

    const auto bind = bind_palette(m.skeleton);
    const auto body0 = skin_range(m, 0, m.head_mesh_begin, bind);
    const auto head0 = skin_range(m, m.head_mesh_begin, m.meshes.size(), bind);

    // Matched binds: seam-ring verts coincide essentially exactly at bind.
    const auto pairs = find_seam_pairs(body0, head0, /*pair_eps=*/1e-3f);
    ASSERT_GT(pairs.size(), 0u)
        << "no coincident equal-weight seam pairs at bind — either the weld "
           "moved verts (it must not) or the pair search is broken";

    const auto bent = bent_neck_palette(m.skeleton);
    const auto body1 = skin_range(m, 0, m.head_mesh_begin, bent);
    const auto head1 = skin_range(m, m.head_mesh_begin, m.meshes.size(), bent);
    for (const auto& p : pairs)
        EXPECT_LT(glm::distance(body1[p.body].pos, head1[p.head].pos), 1e-3f)
            << "seam split under a bent neck (body vert " << p.body
            << " vs head vert " << p.head << ")";
}

TEST_F(HeadWeldSeamTest, MismatchedPairAliasLiftsHeadOntoNeck) {
    assets::Model m = compose("BodyMaleM", "BodyMaleM.NIF");
    ASSERT_GE(m.head_mesh_begin, 0);

    // Raw (unskinned) head verts sit in the HEAD template's bind space,
    // several units below the body's head; the alias palette must lift them.
    glm::vec3 raw_lo(1e9f), raw_hi(-1e9f);
    for (std::size_t mi = m.head_mesh_begin; mi < m.meshes.size(); ++mi) {
        const auto& cpu = m.meshes[mi].cpu_data();
        ASSERT_TRUE(cpu);
        for (const auto& v : cpu->vertices) {
            raw_lo = glm::min(raw_lo, v.position);
            raw_hi = glm::max(raw_hi, v.position);
        }
    }

    const auto bind = bind_palette(m.skeleton);
    const auto head0 = skin_range(m, m.head_mesh_begin, m.meshes.size(), bind);
    glm::vec3 sk_lo(1e9f), sk_hi(-1e9f);
    for (const auto& sv : head0) {
        sk_lo = glm::min(sk_lo, sv.pos);
        sk_hi = glm::max(sk_hi, sv.pos);
    }

    // BodyMaleM's skeleton is ~5-6 units taller than the S/M head template
    // (measured sweep: per-bone deltas 4.85-5.9). The lift must be a clear
    // upward shift, and the skinned head must sit at the BODY's head-bone
    // height (regression for the deleted translation-rebase).
    const float lift = ((sk_lo.z + sk_hi.z) - (raw_lo.z + raw_hi.z)) * 0.5f;
    EXPECT_GT(lift, 3.0f)
        << "alias palette did not lift the mismatched head onto the neck "
           "(head-in-chest regression)";

    int body_head_bone = -1;
    for (std::size_t i = 0; i < m.skeleton.bones.size(); ++i)
        if (m.skeleton.bones[i].name == "Bip01 Head")
            body_head_bone = static_cast<int>(i);
    ASSERT_GE(body_head_bone, 0);
    const glm::vec3 head_bind_world(
        glm::inverse(m.skeleton.bones[body_head_bone].inverse_bind_pose)[3]);
    EXPECT_LT(std::fabs((sk_lo.z + sk_hi.z) * 0.5f - head_bind_world.z), 8.0f)
        << "skinned head centre is far from the body's Bip01 Head bind";

    // Seam still holds under a bent neck — but (see file header) BodyMaleM's
    // collar and miguel_head's neck ring are independently weight-painted, so
    // byte-equal weights never occur near the seam (measured: nearest
    // exact-weight-match anywhere is 7.8 units away, clearly a coincidental,
    // unrelated pair — not a seam correspondence). Pair by nearest position
    // instead (measured seam-adjacent gaps: 0.16-0.28 units, cleanly
    // separated from the next-nearest unrelated pair at 1.6 units), and
    // assert the gap stays CONSTANT under the bent neck (measured drift
    // <0.004 units across all 7 candidates) — that constancy, not an
    // absolute distance, is the actual "moves as one rigid unit" invariant.
    const auto body0 = skin_range(m, 0, m.head_mesh_begin, bind);
    const auto pairs = find_nearest_pairs(body0, head0, /*pair_eps=*/0.3f);
    ASSERT_GT(pairs.size(), 0u) << "no seam-adjacent pairs found on the "
                                   "mismatched pair (alias weld isn't "
                                   "bringing the head close to the body)";

    const auto bent = bent_neck_palette(m.skeleton);
    const auto body1 = skin_range(m, 0, m.head_mesh_begin, bent);
    const auto head1 = skin_range(m, m.head_mesh_begin, m.meshes.size(), bent);
    for (const auto& p : pairs) {
        const float bind_d = glm::distance(body0[p.body].pos, head0[p.head].pos);
        const float bent_d = glm::distance(body1[p.body].pos, head1[p.head].pos);
        EXPECT_LT(std::fabs(bent_d - bind_d), 0.05f)
            << "mismatched-pair seam gap changed under a bent neck (body "
               "vert " << p.body << " vs head vert " << p.head
            << "): bind=" << bind_d << " bent=" << bent_d;
    }
}
