// native/src/assets/src/model_compose.cc
#include <assets/model_compose.h>

#include <cctype>
#include <cmath>
#include <cstdio>
#include <functional>
#include <fstream>
#include <set>
#include <string_view>
#include <unordered_map>
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

// BC quirk: a few characters (e.g. Felix) register facial-image filenames that
// omit the canonical "_head" infix — Felix.py asks for "Felix_blink1.tga" but
// the shipped file is "felix_head_blink1.tga". Reconstruct the canonical name by
// inserting "_head" after the first underscore-delimited token of the stem.
// Returns an empty path when no sensible variant exists (no token boundary, or
// the name is already canonical).
fs::path head_infix_variant(const fs::path& p) {
    const std::string stem = p.stem().string();        // "Felix_blink1"
    const auto us = stem.find('_');
    if (us == std::string::npos) return {};            // no token boundary
    if (stem.compare(us, 6, "_head_") == 0) return {}; // already canonical
    const std::string alt = stem.substr(0, us) + "_head" + stem.substr(us);
    return p.parent_path() / (alt + p.extension().string());
}

// Load a per-officer face texture, tolerating the non-canonical filenames a few
// SDK characters register: try each face_texture_candidates() path in order
// (literal, spelling variants, "_head"-infix variant of each). Throws
// (propagating the failure) only when none resolves.
Texture load_face_texture(const fs::path& path) {
    const std::vector<fs::path> candidates = face_texture_candidates(path);
    for (std::size_t i = 0; i + 1 < candidates.size(); ++i) {
        try {
            return default_tga_loader(candidates[i]);
        } catch (const std::exception&) {
            // fall through to the next candidate
        }
    }
    return default_tga_loader(candidates.back());  // last one may throw
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

bool binds_equal(const glm::mat4& a, const glm::mat4& b) {
    for (int c = 0; c < 4; ++c)
        for (int r = 0; r < 3; ++r)  // row 3 is constant (0,0,0,1) — skip
            if (std::fabs(a[c][r] - b[c][r]) > 1e-4f) return false;
    return true;
}

}  // namespace

std::vector<fs::path> face_texture_candidates(const fs::path& path) {
    std::vector<fs::path> out;
    auto push = [&](const fs::path& c) {
        if (c.empty()) return;
        if (std::find(out.begin(), out.end(), c) == out.end())
            out.push_back(c);
    };

    push(path);

    // Spelling variants: four SDK characters (Admiral_Liu, Barel, CardCapt,
    // Korbus) register "*_eyes_closed.tga", which ships nowhere under
    // game/data — the on-disk convention is "*_eyesclosed.tga" (28 heads) or
    // "*_eyes_close.tga" (Brex). Match case-insensitively; splice the fix into
    // the original stem (the surrounding case doesn't matter on the
    // case-insensitive game-data filesystems we target).
    const std::string stem = path.stem().string();
    std::string lower = stem;
    std::transform(lower.begin(), lower.end(), lower.begin(),
                   [](unsigned char c) {
                       return static_cast<char>(std::tolower(c));
                   });
    constexpr std::string_view kSdkTypo = "eyes_closed";
    const auto pos = lower.find(kSdkTypo);
    if (pos != std::string::npos) {
        for (const char* fix : {"eyesclosed", "eyes_close"}) {
            std::string alt = stem;
            alt.replace(pos, kSdkTypo.size(), fix);
            push(path.parent_path() / (alt + path.extension().string()));
        }
    }

    // The "_head"-infix variant of each spelling (Felix quirk; Korbus needs it
    // COMPOSED with the spelling rewrite: "Korbus_eyes_closed.tga" ->
    // "Korbus_head_eyesclosed.tga").
    const std::size_t spelled = out.size();
    for (std::size_t i = 0; i < spelled; ++i)
        push(head_infix_variant(out[i]));

    return out;
}

std::vector<int> weld_head_bones(Skeleton& body, const Skeleton& head) {
    std::unordered_map<std::string, int> body_by_name;
    for (std::size_t i = 0; i < body.bones.size(); ++i)
        body_by_name.emplace(body.bones[i].name, static_cast<int>(i));

    std::vector<int> map(head.bones.size(), -1);

    // Recursive resolve: a head-only bone's PARENT must map first, and the
    // head skeleton's array order doesn't guarantee parents precede children.
    std::function<int(int)> resolve = [&](int hi) -> int {
        if (hi < 0 || hi >= static_cast<int>(head.bones.size())) return -1;
        if (map[hi] != -1) return map[hi];
        const Bone& hb = head.bones[hi];
        auto it = body_by_name.find(hb.name);
        if (it != body_by_name.end()) {
            if (binds_equal(body.bones[it->second].inverse_bind_pose,
                            hb.inverse_bind_pose))
                return map[hi] = it->second;
            // Bind mismatch: alias rides the body bone's pose but skins with
            // the HEAD's bind (BC: body node world x head bind offset).
            const std::string alias_name =
                hb.name + std::string(kHeadBindAliasSuffix);
            for (std::size_t i = 0; i < body.bones.size(); ++i)
                if (body.bones[i].name == alias_name)
                    return map[hi] = static_cast<int>(i);
            Bone alias;
            alias.name = alias_name;
            alias.parent_index = it->second;
            alias.local_transform = glm::mat4(1.0f);
            alias.inverse_bind_pose = hb.inverse_bind_pose;
            body.bones.push_back(std::move(alias));
            return map[hi] = static_cast<int>(body.bones.size()) - 1;
        }
        // Head-only bone: append for real, under its name-matched parent,
        // keeping name/local so animation clips may drive it.
        const int parent = resolve(hb.parent_index);
        Bone extra;
        extra.name = hb.name;
        extra.parent_index = parent;
        extra.local_transform = hb.local_transform;
        extra.inverse_bind_pose = hb.inverse_bind_pose;
        body.bones.push_back(std::move(extra));
        return map[hi] = static_cast<int>(body.bones.size()) - 1;
    };
    for (std::size_t i = 0; i < head.bones.size(); ++i)
        resolve(static_cast<int>(i));
    return map;
}

std::vector<MeshCpu> graft_head_cpu(Model& body, Model& head,
                                    std::string_view attach_bone,
                                    int* out_node_index) {
    const int attach_idx = find_bone(body.skeleton, attach_bone);
    if (attach_idx < 0) return {};  // unknown bone: leave body untouched

    // BC "head" NIFs (e.g. felix_head.nif) are FULL CHARACTER NIFs — a complete
    // Bip01 body+head template. ReplaceBodyAndHead uses only the HEAD; the body
    // comes from `body`. Earlier this grafted only the "Bip01 Head" node
    // subtree to discard the template body, but that was the wrong cut: the only
    // shapes parented under the "Bip01 Head" node are the HIDDEN "Biped Object"
    // skeleton-placeholder boxes (head box + ponytail box), while the real
    // head/face mesh is a SKINNED shape parented higher up (under "Bip01
    // Spine1"). The subtree walk therefore grafted placeholder boxes and missed
    // the actual head — the "lego skeleton head" bug.
    //
    // model_build now drops every hidden shape (see model_build.cc), so a built
    // head Model contains ONLY the real (visible) head/face mesh(es) — a corpus
    // scan confirms every head NIF's visible shapes are head geometry, never a
    // body. So graft ALL of the head Model's meshes: that is exactly the head.
    std::vector<const MeshCpu*> graftable;
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

    // §3.5 bone rebinding — the BC "weld". Map every head-skeleton bone onto
    // the body skeleton by name; grafted verts keep their AUTHORED weights and
    // only their indices are rewritten. Degenerate heads with no skeleton
    // (synthetic fixtures) keep the old rigid attach-bone bind.
    std::vector<int> bone_map;
    if (!head.skeleton.bones.empty())
        bone_map = weld_head_bones(body.skeleton, head.skeleton);

    std::vector<MeshCpu> out;
    out.reserve(graftable.size());
    bool warned_overflow = false;
    for (const MeshCpu* src : graftable) {
        MeshCpu cpu = *src;  // deep copy of vertices/indices/extra_uvs
        for (auto& v : cpu.vertices) {
            if (bone_map.empty()) {
                v.bone_indices = glm::u8vec4(
                    static_cast<std::uint8_t>(attach_idx), 0, 0, 0);
                v.bone_weights = glm::u8vec4(255, 0, 0, 0);
                continue;
            }
            for (int k = 0; k < 4; ++k) {
                if (v.bone_weights[k] == 0) { v.bone_indices[k] = 0; continue; }
                const int old = v.bone_indices[k];
                const int mapped =
                    (old >= 0 && old < static_cast<int>(bone_map.size()))
                        ? bone_map[old] : -1;
                const int resolved = mapped < 0 ? attach_idx : mapped;
                if (resolved > 255 && !warned_overflow) {
                    std::fprintf(stderr,
                        "[model_compose] welded bone index %d exceeds 255; "
                        "clamping (vertex will mis-bind)\n", resolved);
                    warned_overflow = true;
                }
                v.bone_indices[k] = static_cast<std::uint8_t>(
                    std::clamp(resolved, 0, 255));
            }
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
    std::string_view attach_bone,
    const std::map<std::string, fs::path>& face_images) {
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

    // Lip-sync face sink: record the head-mesh range, then upload the
    // per-officer viseme/blink face textures into the model keyed by slot.
    // Best-effort — a missing/bad image is warned and skipped (never crashes
    // composition); lip-sync simply has fewer slots to blend.
    if (!head_mesh_indices.empty()) {
        body.head_mesh_begin = *std::min_element(head_mesh_indices.begin(),
                                                 head_mesh_indices.end());
    }
    for (const auto& [slot, path] : face_images) {
        if (path.empty()) continue;
        try {
            Texture tex = load_face_texture(path);
            body.face_textures[slot] = static_cast<int>(body.textures.size());
            body.textures.push_back(std::move(tex));
        } catch (const std::exception& e) {
            std::fprintf(stderr,
                         "compose_officer_model: face image '%s' (%s) skipped\n",
                         path.string().c_str(), e.what());
        }
    }

    body.source = body_nif;
    return body;
}

}  // namespace assets
