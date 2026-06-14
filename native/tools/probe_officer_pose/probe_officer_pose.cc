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
// Usage:
//   probe_officer_pose <body.nif> <placement.nif>

#include <nif/file.h>

#include <assets/animation.h>
#include <assets/model.h>
#include <assets/path_resolver.h>

#include <renderer/bone_palette.h>
#include <renderer/pose_sampler.h>

#include <glm/glm.hpp>

#include <cstdio>
#include <filesystem>
#include <string>
#include <unordered_map>
#include <variant>

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
    ctx.keep_cpu_data = false;
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
    return 0;
}
