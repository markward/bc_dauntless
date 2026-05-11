#include "model_build.h"

#include "animation_build.h"
#include "link_resolver.h"
#include "material_build.h"
#include "mesh_build.h"
#include "mesh_upload.h"
#include "skeleton_build.h"

#include <assets/texture.h>

#include <algorithm>
#include <cctype>
#include <fstream>
#include <functional>
#include <unordered_map>
#include <unordered_set>

namespace fs = std::filesystem;

namespace assets::detail {

namespace {

std::vector<std::uint8_t> read_file(const fs::path& p) {
    std::ifstream in(p, std::ios::binary);
    if (!in) {
        throw ModelBuildError(
            "could not open texture file: " + p.string());
    }
    in.seekg(0, std::ios::end);
    const auto size = static_cast<std::size_t>(in.tellg());
    in.seekg(0, std::ios::beg);
    std::vector<std::uint8_t> bytes(size);
    in.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(size));
    return bytes;
}

/// True if `fname`'s extension-less basename ends in "_glow"
/// (case-insensitive). Matches BC's AddLOD suffix convention.
bool filename_is_glow(std::string_view fname) {
    auto dot = fname.find_last_of('.');
    auto stem = (dot == std::string_view::npos) ? fname : fname.substr(0, dot);
    if (stem.size() < 5) return false;
    std::string tail(stem.substr(stem.size() - 5));
    std::transform(tail.begin(), tail.end(), tail.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return tail == "_glow";
}

/// True if `fname`'s extension-less basename ends in "_specular" or
/// "_spec" (case-insensitive). Matches BC's AddLOD suffix convention
/// for the 9th positional arg. Stock BC ships only ever use the long
/// form; "_spec" support exists for mod packs.
bool filename_is_specular(std::string_view fname) {
    auto dot = fname.find_last_of('.');
    auto stem = (dot == std::string_view::npos) ? fname : fname.substr(0, dot);
    auto lower_ends_with = [](std::string_view s, std::string_view suffix) {
        if (s.size() < suffix.size()) return false;
        for (std::size_t i = 0; i < suffix.size(); ++i) {
            char c = s[s.size() - suffix.size() + i];
            c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
            if (c != suffix[i]) return false;
        }
        return true;
    };
    return lower_ends_with(stem, "_specular") || lower_ends_with(stem, "_spec");
}

/// Given a texture filename like "CardGalor01_glow.tga" or "Hull.tga",
/// produce the AddLOD-style sibling spec filename ("CardGalor01_specular.tga"
/// or "Hull_specular.tga"). Strips a trailing `_glow` (case-insensitive)
/// from the stem before appending `_specular`, so a _glow texture and
/// its hull-diffuse sibling resolve to the same spec map.
std::string sibling_specular_filename(std::string_view fname) {
    auto dot = fname.find_last_of('.');
    std::string stem(dot == std::string_view::npos ? fname : fname.substr(0, dot));
    std::string ext (dot == std::string_view::npos ? std::string{} : std::string(fname.substr(dot)));
    // Strip trailing "_glow" (case-insensitive, length 5).
    if (stem.size() >= 5) {
        std::string tail = stem.substr(stem.size() - 5);
        std::transform(tail.begin(), tail.end(), tail.begin(),
            [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        if (tail == "_glow") stem.resize(stem.size() - 5);
    }
    return stem + "_specular" + ext;
}

struct TextureLoadResult {
    std::unordered_map<std::uint32_t, int> image_to_texture;
    std::unordered_set<std::uint32_t>      glow_image_links;
    std::unordered_set<std::uint32_t>      specular_image_links;
    /// NIF link_id of a non-_specular NiImage -> Model::textures index
    /// of a sibling "<basename>_specular.tga" file discovered on disk
    /// next to the loaded image. Phase 1 stand-in for BC's AddLOD
    /// runtime injection of a `_specular` suffix: the actual NIFs
    /// reference only the diffuse/glow image, but BC's engine pairs
    /// each one with a sibling spec map at load time. We replicate that
    /// here so the spec pass has something to bind on stock assets.
    std::unordered_map<std::uint32_t, int> sibling_specular_for_image;
};

/// Walk all NiImage blocks; load + decode + upload referenced TGAs (or
/// embedded NiRawImageData). Returns: nif block index of NiImage -> Model::textures index.
TextureLoadResult load_all_textures(
    const nif::File& f,
    Model& model,
    const ModelBuildContext& ctx,
    const LinkResolver& resolver)
{
    TextureLoadResult out;
    auto upload = ctx.texture_uploader
        ? ctx.texture_uploader
        : TextureUploaderFn(&assets::upload_image);

    for (std::uint32_t i = 0; i < f.blocks.size(); ++i) {
        const auto* img = std::get_if<nif::NiImage>(&f.blocks[i]);
        if (!img) continue;
        Image decoded;
        if (img->use_external != 0) {
            auto path = ctx.resolver->resolve(img->file_name, ctx.texture_search_path);
            auto bytes = read_file(path);
            decoded = decode_tga(bytes);
        } else {
            auto raw_idx = resolver.resolve(img->image_data_link);
            const nif::NiRawImageData* raw = nullptr;
            if (raw_idx != LinkResolver::kInvalidIndex && raw_idx < f.blocks.size()) {
                raw = std::get_if<nif::NiRawImageData>(&f.blocks[raw_idx]);
            }
            if (!raw) {
                throw ModelBuildError(
                    "NiImage at block " + std::to_string(i) +
                    ": missing or unresolvable NiRawImageData link");
            }
            decoded = decode_raw_image(*raw);
        }
        Texture tex = upload(decoded, /*generate_mipmaps=*/true);
        // Key by the NIF block's *link ID* (the value other blocks store
        // in their cross-references), not the array index. BC NIFs use
        // arbitrary 8-digit link IDs that don't equal the block array
        // position. TexDesc::source_link is a link ID, so the lookup at
        // the consumer site (apply_stage in material_build.cc) needs the
        // same key. Synthetic test files with empty block_ids fall back to
        // identity, where link_id == block_index.
        const std::uint32_t link_id =
            (i < f.block_ids.size()) ? f.block_ids[i] : i;
        out.image_to_texture[link_id] = static_cast<int>(model.textures.size());
        if (img->use_external != 0 && filename_is_glow(img->file_name)) {
            out.glow_image_links.insert(link_id);
        }
        if (img->use_external != 0 && filename_is_specular(img->file_name)) {
            out.specular_image_links.insert(link_id);
        }
        model.textures.push_back(std::move(tex));

        // Phase 1 AddLOD-shim: BC's engine, given an AddLOD `_specular`
        // suffix arg, loads a sibling texture for each NiImage by
        // substituting `_specular` for the existing suffix (or appending
        // it). Our load path bypasses AddLOD entirely, so we replicate
        // the behavior here: for every external NiImage that isn't
        // itself a `_specular` file, probe the texture search path for
        // its sibling. Found ones are registered as additional textures
        // and matched back to the original image's link_id so
        // apply_texture_property can bind them to StageSlot::Gloss.
        if (img->use_external != 0 && !filename_is_specular(img->file_name)) {
            const std::string sibling_name =
                sibling_specular_filename(img->file_name);
            try {
                auto sibling_path =
                    ctx.resolver->resolve(sibling_name, ctx.texture_search_path);
                auto sibling_bytes = read_file(sibling_path);
                Image sibling_decoded = decode_tga(sibling_bytes);
                Texture sibling_tex = upload(sibling_decoded, true);
                const int sibling_idx =
                    static_cast<int>(model.textures.size());
                out.sibling_specular_for_image[link_id] = sibling_idx;
                model.textures.push_back(std::move(sibling_tex));
            } catch (const std::exception&) {
                // No sibling on disk — silently skip. Most ships don't
                // ship spec masks. The spec contribution then falls
                // through to black_fallback in the renderer.
            }
        }
    }
    return out;
}

glm::mat4 av_to_local_transform(const nif::AvObjectBase& av) {
    glm::mat4 m(1.0f);
    m[0] = glm::vec4(av.rotation.m[0], av.rotation.m[3], av.rotation.m[6], 0.0f);
    m[1] = glm::vec4(av.rotation.m[1], av.rotation.m[4], av.rotation.m[7], 0.0f);
    m[2] = glm::vec4(av.rotation.m[2], av.rotation.m[5], av.rotation.m[8], 0.0f);
    m[3] = glm::vec4(av.translation.x, av.translation.y, av.translation.z, 1.0f);
    if (av.scale != 1.0f) {
        m[0] *= av.scale;
        m[1] *= av.scale;
        m[2] *= av.scale;
    }
    return m;
}

struct NodeBuildResult {
    std::vector<Node> nodes;
    /// nif block index -> Model::nodes index
    std::unordered_map<std::uint32_t, int> nif_block_to_node_index;
    int root_node = 0;
};

/// Walk the scene graph: identify a root NiNode (one not referenced as a
/// child by any other NiNode), then recursively flatten it. Mesh attachment
/// is recorded as we walk so each Node carries indices into Model::meshes.
NodeBuildResult build_nodes(
    const nif::File& f,
    const LinkResolver& resolver)
{
    NodeBuildResult r;

    // Tally: how many distinct parents reference each block as a child?
    std::unordered_map<std::uint32_t, int> ref_count;
    for (std::uint32_t i = 0; i < f.blocks.size(); ++i) {
        const auto* node = std::get_if<nif::NiNode>(&f.blocks[i]);
        if (!node) continue;
        for (auto child_link : node->child_links) {
            auto child_idx = resolver.resolve(child_link);
            if (child_idx == LinkResolver::kInvalidIndex) continue;
            ref_count[child_idx]++;
        }
    }

    std::function<void(std::uint32_t, int)> walk =
        [&](std::uint32_t nif_idx, int parent) {
            if (nif_idx >= f.blocks.size()) return;
            const auto* node = std::get_if<nif::NiNode>(&f.blocks[nif_idx]);
            if (!node) return;
            Node out;
            out.name = node->av.obj.name;
            out.parent_index = parent;
            out.local_transform = av_to_local_transform(node->av);
            int self = static_cast<int>(r.nodes.size());
            r.nodes.push_back(std::move(out));
            r.nif_block_to_node_index[nif_idx] = self;
            if (parent >= 0) r.nodes[parent].children.push_back(self);

            for (auto child_link : node->child_links) {
                auto child_idx = resolver.resolve(child_link);
                if (child_idx != LinkResolver::kInvalidIndex) walk(child_idx, self);
            }
        };

    for (std::uint32_t i = 0; i < f.blocks.size(); ++i) {
        if (!std::get_if<nif::NiNode>(&f.blocks[i])) continue;
        if (ref_count[i] == 0) {
            walk(i, /*parent=*/-1);
            break;  // BC files have a single root NiNode
        }
    }
    return r;
}

MaterialInputs gather_material_inputs(
    const nif::File& f,
    const nif::NiTriShape& shape,
    const std::unordered_map<std::uint32_t, int>& image_to_texture,
    const std::unordered_set<std::uint32_t>& glow_image_links,
    const std::unordered_set<std::uint32_t>& specular_image_links,
    const std::unordered_map<std::uint32_t, int>& sibling_specular_for_image,
    const LinkResolver& resolver)
{
    MaterialInputs in;
    in.image_to_texture = &image_to_texture;
    in.glow_image_links = &glow_image_links;
    in.specular_image_links = &specular_image_links;
    in.sibling_specular_for_image = &sibling_specular_for_image;
    for (auto link : shape.av.property_links) {
        auto idx = resolver.resolve(link);
        if (idx == LinkResolver::kInvalidIndex) continue;
        if (idx >= f.blocks.size()) continue;
        const auto& b = f.blocks[idx];
        if (auto* p = std::get_if<nif::NiMaterialProperty>(&b))      in.material      = p;
        else if (auto* p = std::get_if<nif::NiTextureProperty>(&b))      in.texture       = p;
        else if (auto* p = std::get_if<nif::NiTexturingProperty>(&b))    in.texturing     = p;
        else if (auto* p = std::get_if<nif::NiMultiTextureProperty>(&b)) in.multi_texture = p;
        else if (auto* p = std::get_if<nif::NiAlphaProperty>(&b))        in.alpha         = p;
        else if (auto* p = std::get_if<nif::NiZBufferProperty>(&b))      in.zbuffer       = p;
        else if (auto* p = std::get_if<nif::NiVertexColorProperty>(&b))  in.vertex_color  = p;
    }
    return in;
}

/// For a NiTriShape at block index `shape_idx`, find the parent NiNode that
/// lists it in its child_links. Returns the Node index in `nodes_result`,
/// or -1 if not attached to any node.
int find_parent_node_index(
    const nif::File& f,
    std::uint32_t shape_idx,
    const NodeBuildResult& nodes_result,
    const LinkResolver& resolver)
{
    for (auto& [parent_nif_idx, node_idx] : nodes_result.nif_block_to_node_index) {
        const auto* n = std::get_if<nif::NiNode>(&f.blocks[parent_nif_idx]);
        if (!n) continue;
        for (auto c : n->child_links) {
            if (resolver.resolve(c) == shape_idx) return node_idx;
        }
    }
    return -1;
}

}  // namespace

Model build_model(const nif::File& f, const ModelBuildContext& ctx) {
    if (!ctx.resolver) throw ModelBuildError("ModelBuildContext::resolver is null");

    LinkResolver resolver(f);
    Model model;
    model.source = f.source;

    // 1. Skeleton (may be empty for ships).
    auto skel = build_skeleton(f);
    model.skeleton = std::move(skel.skeleton);

    // 2. Textures.
    auto tex_result = load_all_textures(f, model, ctx, resolver);

    // 3. Nodes.
    auto nodes = build_nodes(f, resolver);
    if (nodes.nodes.empty()) throw ModelBuildError("no NiNode root in NIF file");
    model.nodes = std::move(nodes.nodes);
    model.root_node = 0;

    // 4. Meshes + materials, in lock-step.
    auto mesh_upload = ctx.mesh_uploader
        ? ctx.mesh_uploader
        : MeshUploaderFn([](MeshCpu cpu) { return upload_mesh(cpu); });

    bool any_trishape = false;
    for (std::uint32_t i = 0; i < f.blocks.size(); ++i) {
        const auto* shape = std::get_if<nif::NiTriShape>(&f.blocks[i]);
        if (!shape) continue;
        any_trishape = true;
        auto data_idx = resolver.resolve(shape->data_link);
        const nif::NiTriShapeData* data = nullptr;
        if (data_idx != LinkResolver::kInvalidIndex && data_idx < f.blocks.size()) {
            data = std::get_if<nif::NiTriShapeData>(&f.blocks[data_idx]);
        }
        if (!data) continue;  // shape with no data block — skip silently

        auto mat_inputs = gather_material_inputs(
            f, *shape, tex_result.image_to_texture, tex_result.glow_image_links,
            tex_result.specular_image_links,
            tex_result.sibling_specular_for_image, resolver);
        Material mat = build_material(mat_inputs);
        int mat_index = static_cast<int>(model.materials.size());
        model.materials.push_back(std::move(mat));

        int node_index = find_parent_node_index(f, i, nodes, resolver);

        MeshCpu cpu = build_mesh_cpu(*shape, *data, mat_index, node_index);
        if (node_index >= 0) {
            int mesh_idx = static_cast<int>(model.meshes.size());
            model.nodes[node_index].meshes.push_back(mesh_idx);
        }
        // Avoid copying the CPU vertex data unless retention is requested.
        if (ctx.keep_cpu_data) {
            Mesh mesh = mesh_upload(MeshCpu(cpu));
            mesh.set_cpu_data(std::move(cpu));
            model.meshes.push_back(std::move(mesh));
        } else {
            model.meshes.push_back(mesh_upload(std::move(cpu)));
        }
    }
    if (!any_trishape) throw ModelBuildError("no NiTriShape in NIF file");

    // 5. Animations.
    model.animations = build_animations(f);

    return model;
}

}  // namespace assets::detail
