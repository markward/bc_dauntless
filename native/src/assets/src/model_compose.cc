// native/src/assets/src/model_compose.cc
#include <assets/model_compose.h>

#include <cstdio>
#include <fstream>
#include <set>
#include <utility>

#include <algorithm>

#include <assets/material.h>
#include <assets/path_resolver.h>
#include <assets/skeleton.h>
#include <assets/texture.h>
#include <nif/file.h>

#include "model_build.h"

namespace assets {

namespace {

namespace fs = std::filesystem;

// Read an entire file into a byte vector. Mirrors model_build.cc's read_file
// (which is in that TU's anonymous namespace and not reachable here). Throws
// nothing — returns empty on open failure so set_base_texture's default loader
// can distinguish "missing file" from "decode error" by catching the latter.
std::vector<std::uint8_t> read_file_bytes(const fs::path& p) {
    std::ifstream in(p, std::ios::binary);
    if (!in) return {};
    in.seekg(0, std::ios::end);
    const auto size = static_cast<std::size_t>(in.tellg());
    in.seekg(0, std::ios::beg);
    std::vector<std::uint8_t> bytes(size);
    in.read(reinterpret_cast<char*>(bytes.data()),
            static_cast<std::streamsize>(size));
    return bytes;
}

// Default TGA loader for set_base_texture: same decode/upload path the model
// pipeline uses in model_build.cc::load_all_textures (read_file -> decode_tga
// -> upload_image), so an overridden skin is byte-for-byte processed like the
// NIF default it replaces.
Texture default_tga_loader(const fs::path& tga_path) {
    std::vector<std::uint8_t> bytes = read_file_bytes(tga_path);
    if (bytes.empty())
        throw TextureDecodeError("set_base_texture: could not read " +
                                 tga_path.string());
    Image img = decode_tga(bytes);          // assets::decode_tga (texture.h)
    return upload_image(img, /*generate_mipmaps=*/true);  // assets::upload_image
}

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

    // BC "head" NIFs (e.g. felix_head.nif) are FULL CHARACTER NIFs — a complete
    // Bip01 body+head template. ReplaceBodyAndHead uses only the HEAD; the body
    // comes from `body`. So graft ONLY the meshes in the head NIF's attach-bone
    // ("Bip01 Head") subtree (the face + ponytail), discarding the template
    // body. Grafting every mesh binds the template's arms/torso/legs to the
    // single head bone — they fling out as skin-coloured spikes ("brown
    // skeleton"). If the head NIF has no such node (a head-only NIF), graft all.
    std::vector<const MeshCpu*> graftable;
    int head_node = -1;
    for (std::size_t i = 0; i < head.nodes.size(); ++i)
        if (head.nodes[i].name == attach_bone) { head_node = static_cast<int>(i); break; }
    if (head_node >= 0) {
        std::vector<char> in_subtree(head.nodes.size(), 0);
        std::vector<int> stack{head_node};
        while (!stack.empty()) {
            int n = stack.back(); stack.pop_back();
            if (n < 0 || n >= static_cast<int>(head.nodes.size()) || in_subtree[n])
                continue;
            in_subtree[n] = 1;
            for (int c : head.nodes[n].children) stack.push_back(c);
        }
        for (std::size_t n = 0; n < head.nodes.size(); ++n) {
            if (!in_subtree[n]) continue;
            for (int mi : head.nodes[n].meshes)
                if (mi >= 0 && mi < static_cast<int>(head.meshes.size()) &&
                    head.meshes[mi].cpu_data())
                    graftable.push_back(&*head.meshes[mi].cpu_data());
        }
    } else {
        for (const auto& mesh : head.meshes)
            if (mesh.cpu_data()) graftable.push_back(&*mesh.cpu_data());
    }
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
            // The head NIF builds its verts already in character-bind-model
            // space (the head sits at its character head height), so binding to
            // the head bone with weight 1 lets the body's bone palette pose it
            // exactly like a rigid body shape — no extra transform.
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

std::vector<int> graft_head(Model& body, Model& head,
                            std::string_view attach_bone) {
    int node_index = -1;
    std::vector<MeshCpu> grafted =
        graft_head_cpu(body, head, attach_bone, &node_index);
    if (grafted.empty()) return {};

    // BC's ReplaceBodyAndHead REPLACES the body's head with the new one. The
    // body NIF carries its own default head/neck geometry on the attach-node
    // sub-tree; drop those meshes from the node-walk before adding the grafted
    // head, otherwise the body's default head and the new head stack (the
    // long-neck / doubled-face artifact). Meshes stay in body.meshes (harmless,
    // just unreferenced); only the node->mesh links are cleared.
    if (node_index >= 0) {
        for (std::size_t i = 0; i < body.nodes.size(); ++i) {
            bool in_head_subtree = false;
            for (int c = static_cast<int>(i); c != -1;
                 c = body.nodes[c].parent_index) {
                if (c == node_index) { in_head_subtree = true; break; }
            }
            if (in_head_subtree) body.nodes[i].meshes.clear();
        }
    }

    std::vector<int> grafted_mesh_indices;
    grafted_mesh_indices.reserve(grafted.size());
    for (const MeshCpu& cpu : grafted) {
        Mesh mesh = upload_mesh(cpu);
        mesh.set_cpu_data(cpu);  // retain for any cpu-walking passes (shields,
                                 // bounds) that mirror keep_cpu_data semantics
        const int mesh_index = static_cast<int>(body.meshes.size());
        body.meshes.push_back(std::move(mesh));
        if (node_index >= 0 &&
            node_index < static_cast<int>(body.nodes.size()))
            body.nodes[node_index].meshes.push_back(mesh_index);
        grafted_mesh_indices.push_back(mesh_index);
    }
    return grafted_mesh_indices;
}

bool set_base_texture(Model& model, std::span<const int> mesh_indices,
                      const fs::path& tga_path,
                      const TgaTextureLoaderFn& loader) {
    if (tga_path.empty()) return false;  // no override requested

    // Gather the distinct, valid material indices referenced by the meshes.
    std::set<int> material_indices;
    for (int mi : mesh_indices) {
        if (mi < 0 || mi >= static_cast<int>(model.meshes.size())) continue;
        const int mat = model.meshes[mi].material_index();
        if (mat >= 0 && mat < static_cast<int>(model.materials.size()))
            material_indices.insert(mat);
    }
    if (material_indices.empty()) {
        std::fprintf(stderr,
                     "set_base_texture: no Base-stage material referenced by "
                     "the given meshes; leaving NIF default (%s)\n",
                     tga_path.string().c_str());
        return false;
    }

    // Decode + upload the override skin. On any failure (missing file, bad
    // TGA, GL error) leave the model untouched and warn — a bad per-officer
    // skin must not crash composition.
    Texture tex;
    try {
        tex = loader ? loader(tga_path) : default_tga_loader(tga_path);
    } catch (const std::exception& e) {
        std::fprintf(stderr,
                     "set_base_texture: failed to load '%s' (%s); leaving NIF "
                     "default\n",
                     tga_path.string().c_str(), e.what());
        return false;
    }

    const int new_index = static_cast<int>(model.textures.size());
    model.textures.push_back(std::move(tex));

    const auto base = static_cast<std::size_t>(Material::StageSlot::Base);
    for (int mat : material_indices)
        model.materials[mat].stages[base].texture_index = new_index;
    return true;
}

Model compose_officer_model(
    const std::filesystem::path& body_nif,
    const std::filesystem::path& body_tex,
    const std::filesystem::path& head_nif,
    const std::filesystem::path& head_tex,
    std::string_view attach_bone) {
    PathResolver resolver;

    // Each NIF's *default* (embedded-basename) textures resolve against the
    // NIF's own directory, exactly like the AssetCache path. Per-officer skin
    // selection happens afterwards via set_base_texture, not by search dir.
    auto build = [&](const std::filesystem::path& nif) {
        nif::File f = nif::load(nif);
        detail::ModelBuildContext ctx;
        ctx.resolver = &resolver;
        ctx.texture_search_paths = {nif.parent_path()};
        ctx.keep_cpu_data = true;  // empty uploaders -> upload_image/upload_mesh
        return detail::build_model(f, ctx);
    };

    Model body = build(body_nif);
    Model head = build(head_nif);

    // The body's own meshes are exactly those present before the graft; the
    // graft returns the indices of the appended head meshes. Capture the body
    // mesh indices first so the body skin override never touches head materials.
    std::vector<int> body_mesh_indices;
    body_mesh_indices.reserve(body.meshes.size());
    for (int i = 0; i < static_cast<int>(body.meshes.size()); ++i)
        body_mesh_indices.push_back(i);

    std::vector<int> head_mesh_indices =
        graft_head(body, head, attach_bone);  // empty (no-op) is tolerated:
                                              // caller still gets a renderable
                                              // body model.

    // Apply per-officer skin overrides to the loaded materials' Base stage.
    // Empty path -> NIF default kept; missing/unreadable -> warned, default
    // kept (set_base_texture is the no-crash guard).
    set_base_texture(body, body_mesh_indices, body_tex);
    set_base_texture(body, head_mesh_indices, head_tex);

    body.source = body_nif;
    return body;
}

}  // namespace assets
