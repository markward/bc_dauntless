// native/tools/probe_officer_pose/probe_officer_pose.cc
//
// Headless numeric probe for officer posing. Builds a body NIF's node tree +
// skeleton WITHOUT a GL context (stub mesh/texture uploaders), then walks the
// node hierarchy to print the BIND world position of key Bip01 bones and
// inspects the body's skin controllers / shape counts. It then drives the SP2
// GPU palette path: it loads the placement clip, samples it, and prints the
// POSED world position of "Bip01 L Hand" (with the same X-flip officers are
// placed with) so the palette pose can be checked headlessly against the
// verified station value (db_stand_t_l → ≈ (-21, -107, 23): hip height,
// arms-down). The skeleton mirrors the FULL node hierarchy, so the clip's
// "Bip01" root-translation track (station offset) flows into the palette.
//
// SKIN-AABB explosion oracle (SP2): a bone ORIGIN check cannot catch a
// skinned-vertex explosion (mis-skinned verts blow up while bone origins stay
// put). So the probe ALSO fully skins every mesh vertex through the posed
// palette exactly as the GPU does — pos = Σ_k w_k · palette[idx_k] · v with
// u_model = inst.world applied uniformly, matching renderer/bridge_pass.cc's
// skinned sub-pass — and asserts the resulting AABB is bounded (|coord| < 300,
// extent < 200). This is the headless safety net for the "skinned shapes baked
// into bind-model space" fix in model_build.cc: a regression that returned the
// skinned arms to a wrong base space would shift this AABB (and, for a body
// whose skin-root bind-world carried rotation/scale, explode it outright).
//
// Usage:
//   probe_officer_pose <body.nif> <placement.nif>

#include <nif/file.h>

#include <assets/animation.h>
#include <assets/model.h>
#include <assets/path_resolver.h>

#include <renderer/bone_palette.h>
#include <renderer/pose_sampler.h>

#include <glm/glm.hpp>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <optional>
#include <set>
#include <string>
#include <unordered_map>
#include <variant>
#include <vector>

#include "../../src/assets/src/model_build.h"

namespace fs = std::filesystem;

namespace {

glm::vec3 world_pos(const assets::Model& m, int idx) {
    glm::mat4 w = m.nodes[idx].local_transform;
    int p = m.nodes[idx].parent_index;
    while (p >= 0) {
        w = m.nodes[p].local_transform * w;
        p = m.nodes[p].parent_index;
    }
    return glm::vec3(w[3]);
}

void dump(const assets::Model& m, const char* tag) {
    static const char* kBones[] = {
        "Bip01",        "Bip01 Pelvis", "Bip01 Spine",  "Bip01 Neck",
        "Bip01 Head",   "Bip01 L Clavicle", "Bip01 L UpperArm",
        "Bip01 L Hand", "Bip01 R Hand", "Bip01 L Foot", "Bip01 R Foot",
    };
    std::printf("--- %s ---\n", tag);
    for (const char* bn : kBones) {
        for (size_t i = 0; i < m.nodes.size(); ++i) {
            if (m.nodes[i].name == bn) {
                glm::vec3 p = world_pos(m, static_cast<int>(i));
                std::printf("  %-18s world = (%8.2f, %8.2f, %8.2f)\n",
                            bn, p.x, p.y, p.z);
                break;
            }
        }
    }
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 3) {
        std::fprintf(stderr,
                     "usage: probe_officer_pose <body.nif> <placement.nif>\n");
        return 2;
    }
    const fs::path body_nif = argv[1];
    const fs::path place_nif = argv[2];

    // Build the body's node tree headlessly: stub uploaders so no GL is touched.
    nif::File bf = nif::load(body_nif.string());
    assets::PathResolver resolver;
    assets::detail::ModelBuildContext ctx;
    ctx.resolver = &resolver;
    ctx.texture_search_paths = {body_nif.parent_path()};
    ctx.texture_uploader = [](const assets::Image&, bool) { return assets::Texture{}; };
    ctx.mesh_uploader = [](assets::MeshCpu) { return assets::Mesh{}; };
    // Keep CPU data so the SKIN-AABB oracle below can fully skin every vertex
    // through the posed palette and assert the result is bounded (an exploded
    // skinned shape produces coordinates in the thousands).
    ctx.keep_cpu_data = true;
    int ninodes = 0, shapes = 0, skinned = 0;
    for (const auto& blk : bf.blocks) {
        if (std::get_if<nif::NiNode>(&blk)) ++ninodes;
        if (std::get_if<nif::NiTriShape>(&blk)) ++shapes;
        if (std::get_if<nif::NiTriShapeSkinController>(&blk)) ++skinned;
    }
    std::printf("body blocks=%zu NiNodes=%d shapes=%d skin_controllers=%d\n",
                bf.blocks.size(), ninodes, shapes, skinned);
    // For each skin controller, resolve which bone NODES it weights, so we know
    // what body part is skinned (and thus explodes under the static node walk).
    {
        std::unordered_map<std::uint32_t, std::string> link_to_name;
        for (std::uint32_t i = 0; i < bf.blocks.size(); ++i)
            if (const auto* n = std::get_if<nif::NiNode>(&bf.blocks[i]))
                link_to_name[i] = n->av.obj.name;  // block index ~ link id
        int sc = 0;
        for (const auto& blk : bf.blocks) {
            const auto* skin = std::get_if<nif::NiTriShapeSkinController>(&blk);
            if (!skin) continue;
            std::printf("  skin_controller[%d] num_bones=%u bones:", sc++,
                        skin->num_bones);
            for (std::uint32_t bl : skin->bone_links) {
                auto it = link_to_name.find(bl);
                std::printf(" %s", it != link_to_name.end()
                            ? (it->second.empty() ? "<unnamed>" : it->second.c_str())
                            : "?");
            }
            std::printf("\n");
        }
    }
    // Build ONE model/skeleton and reuse it for the bind dump and the palette
    // pass (Model holds move-only Texture/Mesh, so we keep a single instance).
    assets::Model m = assets::detail::build_model(bf, ctx);
    std::printf("body nodes=%zu\n", m.nodes.size());

    dump(m, "BIND (body NIF, no pose applied)");

    // SP2 fix: the skeleton now mirrors the FULL node hierarchy, so its root is
    // the model root NiNode and the "Bip01" node — carrying the placement clip's
    // 17-key root-translation track (the station offset) — is a real bone the
    // pose sampler drives by name. The palette-path posed world below therefore
    // reproduces the node-walk posed hand EXACTLY (station offset + bind frame),
    // not just upper-body posing relative to the pelvis.
    std::printf("skeleton bones=%zu root_bone_index=%d (root name=%s)\n",
                m.skeleton.bones.size(), m.skeleton.root_bone_index,
                m.skeleton.root_bone_index >= 0
                    ? (m.skeleton.bones[m.skeleton.root_bone_index].name.empty()
                        ? "<model-root>"
                        : m.skeleton.bones[m.skeleton.root_bone_index].name.c_str())
                    : "<none>");

    // SP2 palette-path check: drive the GPU pose path and print the POSED world
    // origin of "Bip01 L Hand" so it can be compared headlessly against the
    // verified station pose (db_stand_t_l → L-Hand ≈ (-21, -107, 23): hip
    // height, arms-down).
    //
    // The renderer feeds the GPU u_model = inst.world and the bone palette. BC
    // character NIFs are authored in a left-handed model frame (left hand at +X),
    // and the renderer runs glFrontFace(GL_CW) assuming det < 0 — so officers are
    // placed with the determinant-normalization X-flip (engine/bridge_officers.py
    // _BRIDGE_IDENTITY_MAT4 negates the X axis), exactly like ships. We apply the
    // same X-flip to inst.world here so the printed value matches the on-bridge
    // render. The posed bone ORIGIN is world_pose(b)[3]; multiplying by inst.world
    // mirrors X into the renderer's right-handed world.
    {
        std::vector<assets::AnimationClip> clips =
            assets::load_animation_clips(place_nif.string());
        if (clips.empty()) {
            std::printf("PALETTE: no clips in %s\n", place_nif.string().c_str());
        } else {
            const assets::AnimationClip& clip = clips.front();
            // Stand clips settle into pose at t=duration (play-once-and-hold).
            std::vector<glm::mat4> pose =
                renderer::sample_pose(clip, m.skeleton, clip.duration_seconds);

            // inst.world for a bridge officer: identity with the X axis negated
            // (det < 0), matching engine/bridge_officers.py _BRIDGE_IDENTITY_MAT4.
            glm::mat4 inst_world(1.0f);
            inst_world[0][0] = -1.0f;

            // world_pose(b)[3]: product of sampled bone LOCAL transforms,
            // root->bone (mirrors build_bone_palette's internal world_of).
            auto posed_world = [&](int i) {
                glm::mat4 w(1.0f);
                std::vector<int> chain;
                for (int b = i; b != -1; b = m.skeleton.bones[b].parent_index)
                    chain.push_back(b);
                for (auto it = chain.rbegin(); it != chain.rend(); ++it)
                    w = w * pose[static_cast<std::size_t>(*it)];
                return w;
            };

            bool found = false;
            for (std::size_t b = 0; b < m.skeleton.bones.size(); ++b) {
                if (m.skeleton.bones[b].name == "Bip01 L Hand") {
                    glm::vec3 wp = glm::vec3(
                        inst_world * posed_world(static_cast<int>(b))[3]);
                    std::printf(
                        "PALETTE L-Hand posed world = (%.1f %.1f %.1f)\n",
                        wp.x, wp.y, wp.z);
                    found = true;
                    break;
                }
            }
            if (!found)
                std::printf("PALETTE: 'Bip01 L Hand' bone not found\n");
        }
    }

    // SKIN-AABB explosion oracle (SP2): the L-Hand bone-ORIGIN check above
    // verifies the skeleton/palette, but cannot catch a skinned-vertex
    // explosion — mis-skinned verts blow up while the bone origins stay put.
    // Here we fully skin EVERY mesh vertex through the posed palette exactly as
    // the GPU does (pos = Σ_k w_k · palette[idx_k] · v) and assert the AABB is
    // bounded. A correctly bind-baked body poses to ~80 units at a station
    // offset of ~|130|; an exploded shape produces coordinates in the thousands.
    {
        std::vector<assets::AnimationClip> clips =
            assets::load_animation_clips(place_nif.string());
        if (clips.empty()) {
            std::printf("SKIN-AABB: no clips in %s\n", place_nif.string().c_str());
            return 1;
        }
        const assets::AnimationClip& clip = clips.front();
        std::vector<glm::mat4> pose =
            renderer::sample_pose(clip, m.skeleton, clip.duration_seconds);
        std::vector<glm::mat4> palette =
            renderer::build_bone_palette(m.skeleton, &pose);

        // Which mesh indices the live bridge skinned pass would actually draw:
        // it iterates m.nodes[i].meshes, so a mesh with no node registration is
        // never drawn (orphaned). Build that set so the oracle can report it.
        std::set<int> drawn_by_bridge_pass;
        for (const auto& node : m.nodes)
            for (int mi : node.meshes) drawn_by_bridge_pass.insert(mi);

        glm::vec3 lo(1e30f), hi(-1e30f);
        std::size_t verts_skinned = 0, meshes_with_cpu = 0;
        int mesh_no = -1;
        for (const assets::Mesh& mesh : m.meshes) {
            ++mesh_no;
            const std::optional<assets::MeshCpu>& cd = mesh.cpu_data();
            if (!cd) continue;
            ++meshes_with_cpu;
            // Per-mesh diagnostic: distinct bone-index count (>1 ⇒ true
            // multi-bone skinned shape) and this mesh's own posed AABB.
            std::set<int> bones_used;
            glm::vec3 mlo(1e30f), mhi(-1e30f);
            std::size_t mverts = 0;
            for (const assets::MeshCpu::Vertex& v : cd->vertices) {
                glm::vec4 p(v.position, 1.0f);
                glm::vec4 skinned(0.0f);
                float wsum = 0.0f;
                for (int k = 0; k < 4; ++k) {
                    float w = static_cast<float>(v.bone_weights[k]) / 255.0f;
                    if (w <= 0.0f) continue;
                    std::size_t bi = static_cast<std::size_t>(v.bone_indices[k]);
                    if (bi >= palette.size()) continue;
                    skinned += w * (palette[bi] * p);
                    wsum += w;
                    bones_used.insert(static_cast<int>(bi));
                }
                // Vertices with no weight at all (degenerate) are skipped so they
                // don't anchor the AABB at the origin and mask an explosion.
                if (wsum <= 0.0f) continue;
                glm::vec3 s = glm::vec3(skinned);
                lo = glm::min(lo, s);
                hi = glm::max(hi, s);
                mlo = glm::min(mlo, s);
                mhi = glm::max(mhi, s);
                ++verts_skinned;
                ++mverts;
            }
            if (mverts > 0 && bones_used.size() > 1) {
                glm::vec3 me = mhi - mlo;
                float mme = std::max(me.x, std::max(me.y, me.z));
                // Read node_index from the CPU data (the stub mesh uploader
                // discards Mesh::node_index_, so mesh.node_index() is always -1).
                int pn = cd->node_index;
                glm::vec3 pnt(0.0f);
                const char* pname = "?";
                if (pn >= 0 && pn < static_cast<int>(m.nodes.size())) {
                    pnt = world_pos(m, pn);
                    pname = m.nodes[pn].name.c_str();
                }
                std::printf(
                    "  mesh[%d] MULTI-BONE bones=%zu verts=%zu posed_extent=%.1f "
                    "min=(%.1f %.1f %.1f) max=(%.1f %.1f %.1f) node_index=%d "
                    "parent='%s' parent_bindworld=(%.1f %.1f %.1f) "
                    "drawn_by_bridge_pass=%d\n",
                    mesh_no, bones_used.size(), mverts, mme, mlo.x, mlo.y, mlo.z,
                    mhi.x, mhi.y, mhi.z, pn, pname, pnt.x, pnt.y, pnt.z,
                    drawn_by_bridge_pass.count(mesh_no) ? 1 : 0);
            }
        }

        if (verts_skinned == 0) {
            std::printf("SKIN-AABB FAIL (no skinned vertices; meshes_with_cpu=%zu)\n",
                        meshes_with_cpu);
            return 1;
        }

        glm::vec3 ext = hi - lo;
        float max_ext = std::max(ext.x, std::max(ext.y, ext.z));
        float max_coord = std::max(std::max(std::abs(lo.x), std::abs(hi.x)),
                          std::max(std::max(std::abs(lo.y), std::abs(hi.y)),
                                   std::max(std::abs(lo.z), std::abs(hi.z))));
        std::printf(
            "SKIN-AABB meshes_with_cpu=%zu verts=%zu min=(%.1f %.1f %.1f) "
            "max=(%.1f %.1f %.1f) extent=(%.1f %.1f %.1f) max_extent=%.1f "
            "max_coord=%.1f\n",
            meshes_with_cpu, verts_skinned, lo.x, lo.y, lo.z, hi.x, hi.y, hi.z,
            ext.x, ext.y, ext.z, max_ext, max_coord);

        const bool ok = (max_coord < 300.0f) && (max_ext < 200.0f);
        if (ok) {
            std::printf("SKIN-AABB PASS\n");
        } else {
            std::printf("SKIN-AABB FAIL (extent=%.1f max_coord=%.1f)\n",
                        max_ext, max_coord);
            return 1;
        }
    }
    return 0;
}
