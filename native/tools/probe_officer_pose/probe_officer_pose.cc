// native/tools/probe_officer_pose/probe_officer_pose.cc
//
// Headless numeric probe for SP3 officer posing. Builds a body NIF's node
// tree + skeleton WITHOUT a GL context (stub mesh/texture uploaders), applies
// load_pose_locals(placement) via apply_pose_to_nodes, then walks the node
// hierarchy to print the WORLD position of key Bip01 bones. This lets us check
// the pose math (arms down, neck normal, legs at rest) without a live render.
//
// Usage:
//   probe_officer_pose <body.nif> <placement.nif> [--sample-start]
//
// It prints two passes:
//   REST  = the placement NIF's static node skeleton (no keyframe overlay)
//   POSED = load_pose_locals output (selective upper-body keyframe overlay)
// so the legs should be identical across both and the arms/neck should differ.

#include <nif/file.h>

#include <assets/animation.h>
#include <assets/model.h>
#include <assets/model_compose.h>
#include <assets/path_resolver.h>

#include <glm/glm.hpp>
#include <glm/gtc/quaternion.hpp>
#include <glm/gtx/quaternion.hpp>

#include <cstdio>
#include <filesystem>
#include <string>
#include <unordered_map>
#include <variant>

#include "../../src/assets/src/model_build.h"

namespace fs = std::filesystem;

namespace {

// Read a placement NIF's per-node REST local transforms (no keyframe overlay)
// the same way load_pose_locals builds its `rest` map, so we have a pure-rest
// baseline to diff the selective overlay against.
std::unordered_map<std::string, glm::mat4> rest_only(const fs::path& nif_path) {
    std::unordered_map<std::string, glm::mat4> out;
    nif::File f = nif::load(nif_path.string());
    for (const auto& blk : f.blocks) {
        const auto* n = std::get_if<nif::NiNode>(&blk);
        if (!n || n->av.obj.name.empty()) continue;
        const auto& av = n->av;
        glm::mat4 m(1.0f);
        const auto& r = av.rotation.m;
        m[0] = glm::vec4(r[0], r[3], r[6], 0.0f);
        m[1] = glm::vec4(r[1], r[4], r[7], 0.0f);
        m[2] = glm::vec4(r[2], r[5], r[8], 0.0f);
        m[3] = glm::vec4(av.translation.x, av.translation.y, av.translation.z, 1.0f);
        if (av.scale != 1.0f) { m[0] *= av.scale; m[1] *= av.scale; m[2] *= av.scale; }
        out[av.obj.name] = m;
    }
    return out;
}

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
                     "usage: probe_officer_pose <body.nif> <placement.nif> "
                     "[--sample-start]\n");
        return 2;
    }
    const fs::path body_nif = argv[1];
    const fs::path place_nif = argv[2];
    bool sample_start = (argc > 3 && std::string(argv[3]) == "--sample-start");

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
    std::printf("body nodes=%zu\n", assets::detail::build_model(bf, ctx).nodes.size());

    // Model holds move-only Texture/Mesh; rebuild a fresh body per pass.
    auto fresh = [&]() { return assets::detail::build_model(bf, ctx); };

    {
        assets::Model m = fresh();
        dump(m, "BIND (body NIF, no pose applied)");
    }
    {
        assets::Model m = fresh();
        assets::apply_pose_to_nodes(m, rest_only(place_nif));
        dump(m, "REST (placement static skeleton)");
    }
    {
        assets::Model m = fresh();
        assets::apply_pose_to_nodes(
            m, assets::load_pose_locals(place_nif, sample_start));
        dump(m, sample_start ? "POSED (selective overlay @start)"
                             : "POSED (selective overlay @end)");
    }
    return 0;
}
