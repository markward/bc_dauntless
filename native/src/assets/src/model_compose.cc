// native/src/assets/src/model_compose.cc
#include <assets/model_compose.h>

#include <utility>

#include <assets/material.h>
#include <assets/path_resolver.h>
#include <assets/skeleton.h>
#include <nif/file.h>

#include "model_build.h"

namespace assets {

namespace {

int find_bone(const Skeleton& sk, std::string_view name) {
    for (std::size_t i = 0; i < sk.bones.size(); ++i)
        if (sk.bones[i].name == name) return static_cast<int>(i);
    return -1;
}

// Choose the body node the grafted meshes attach to: the node named like the
// attach bone if present (so the renderer's node-walk applies that node's world
// transform, matching the body's own head-region nodes), else the root node.
int choose_attach_node(const Model& body, std::string_view attach_bone) {
    for (std::size_t i = 0; i < body.nodes.size(); ++i)
        if (body.nodes[i].name == attach_bone) return static_cast<int>(i);
    return body.root_node;
}

}  // namespace

std::vector<MeshCpu> graft_head_cpu(Model& body, Model& head,
                                    std::string_view attach_bone,
                                    int* out_node_index) {
    const int attach_idx = find_bone(body.skeleton, attach_bone);
    if (attach_idx < 0) return {};  // unknown bone: leave body untouched

    // Collect the head meshes that carry CPU data (the only ones we can graft).
    std::vector<const MeshCpu*> graftable;
    graftable.reserve(head.meshes.size());
    for (const auto& mesh : head.meshes)
        if (mesh.cpu_data()) graftable.push_back(&*mesh.cpu_data());
    if (graftable.empty()) return {};  // nothing to graft: leave body untouched

    const int node_index = choose_attach_node(body, attach_bone);
    if (out_node_index) *out_node_index = node_index;

    // Offset applied to the head materials' texture-stage indices, then MOVE the
    // head textures onto the end of the body palette. (Texture is move-only; the
    // head is cannibalized — see header.)
    const int tex_offset = static_cast<int>(body.textures.size());
    for (auto& tex : head.textures)
        body.textures.push_back(std::move(tex));
    head.textures.clear();

    // Remap: head material index -> body material index. A copy of each head
    // material is appended with every valid stage texture_index offset.
    const int mat_offset = static_cast<int>(body.materials.size());
    for (const Material& src : head.materials) {
        Material copy = src;
        for (auto& stage : copy.stages)
            if (stage.texture_index >= 0)
                stage.texture_index += tex_offset;
        // NiFlipController animation indices reference head.texture_animations,
        // which we don't merge; drop the animation binding to avoid dangling
        // indices into the body's (different) texture_animations table.
        copy.animation_index = -1;
        body.materials.push_back(std::move(copy));
    }

    // Build one rigid-bound MeshCpu per graftable head mesh.
    std::vector<MeshCpu> out;
    out.reserve(graftable.size());
    for (const MeshCpu* src : graftable) {
        MeshCpu cpu = *src;  // deep copy of vertices/indices/extra_uvs
        for (auto& v : cpu.vertices) {
            v.bone_indices = glm::u8vec4(static_cast<std::uint8_t>(attach_idx),
                                         0, 0, 0);
            v.bone_weights = glm::u8vec4(255, 0, 0, 0);
        }
        const int src_mat = src->material_index;
        cpu.material_index =
            (src_mat >= 0) ? mat_offset + src_mat : -1;
        cpu.node_index = node_index;
        out.push_back(std::move(cpu));
    }
    return out;
}

bool graft_head(Model& body, Model& head, std::string_view attach_bone) {
    int node_index = -1;
    std::vector<MeshCpu> grafted =
        graft_head_cpu(body, head, attach_bone, &node_index);
    if (grafted.empty()) return false;

    for (const MeshCpu& cpu : grafted) {
        Mesh mesh = upload_mesh(cpu);
        mesh.set_cpu_data(cpu);  // retain for any cpu-walking passes (shields,
                                 // bounds) that mirror keep_cpu_data semantics
        const int mesh_index = static_cast<int>(body.meshes.size());
        body.meshes.push_back(std::move(mesh));
        if (node_index >= 0 &&
            node_index < static_cast<int>(body.nodes.size()))
            body.nodes[node_index].meshes.push_back(mesh_index);
    }
    return true;
}

Model compose_officer_model(
    const std::filesystem::path& body_nif,
    const std::vector<std::filesystem::path>& body_tex_dirs,
    const std::filesystem::path& head_nif,
    const std::vector<std::filesystem::path>& head_tex_dirs,
    std::string_view attach_bone) {
    PathResolver resolver;

    auto build = [&](const std::filesystem::path& nif,
                     const std::vector<std::filesystem::path>& tex_dirs) {
        nif::File f = nif::load(nif);
        detail::ModelBuildContext ctx;
        ctx.resolver = &resolver;
        ctx.texture_search_paths = tex_dirs.empty()
            ? std::vector<std::filesystem::path>{nif.parent_path()}
            : tex_dirs;
        ctx.keep_cpu_data = true;  // empty uploaders -> upload_image/upload_mesh
        return detail::build_model(f, ctx);
    };

    Model body = build(body_nif, body_tex_dirs);
    Model head = build(head_nif, head_tex_dirs);
    graft_head(body, head, attach_bone);  // false (no-op) is tolerated: caller
                                          // still gets a renderable body model.
    body.source = body_nif;
    return body;
}

}  // namespace assets
