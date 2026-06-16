#include "model_build.h"

#include "animation_build.h"
#include "link_resolver.h"
#include "material_build.h"
#include "mesh_build.h"
#include "mesh_upload.h"
#include "skeleton_build.h"
#include "skin_weights.h"

#include "assets/crushability_bake.h"
#include <assets/texture.h>

#include <algorithm>
#include <cctype>
#include <fstream>
#include <functional>
#include <string>
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
    /// NIF link ID -> source filename (NiImage::file_name) for external
    /// images. Used by material_build's lightmap-pass predicate.
    std::unordered_map<std::uint32_t, std::string> image_filename_for_link;
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
            auto path = ctx.resolver->resolve(img->file_name, ctx.texture_search_paths);
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
        if (img->use_external != 0) {
            out.image_filename_for_link[link_id] = img->file_name;
        }
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
                    ctx.resolver->resolve(sibling_name, ctx.texture_search_paths);
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

/// child_link → parent NiNode block index. Built once per build_model
/// invocation and reused for every shape's inheritance walk. Keys are
/// NIF link IDs (the values stored in cross-block references), not block
/// array indices, to match every other cross-ref site in this file.
using ChildToParentMap = std::unordered_map<std::uint32_t, std::size_t>;

ChildToParentMap build_child_to_parent_map(const nif::File& f) {
    ChildToParentMap out;
    out.reserve(f.blocks.size());
    for (std::size_t i = 0; i < f.blocks.size(); ++i) {
        const auto* n = std::get_if<nif::NiNode>(&f.blocks[i]);
        if (!n) continue;
        for (std::uint32_t c : n->child_links) {
            out[c] = i;
        }
    }
    return out;
}

MaterialInputs gather_material_inputs(
    const nif::File& f,
    std::uint32_t shape_block_index,
    const nif::NiTriShape& shape,
    const ChildToParentMap& child_to_parent,
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

    auto consider = [&](std::uint32_t link) {
        auto idx = resolver.resolve(link);
        if (idx == LinkResolver::kInvalidIndex) return;
        if (idx >= f.blocks.size()) return;
        const auto& b = f.blocks[idx];
        // Child overrides parent: only fill each per-type slot if it's
        // still empty. The walk visits the shape's own links first
        // (depth 0), then each ancestor NiNode in turn.
        if (auto* p = std::get_if<nif::NiMaterialProperty>(&b)) {
            if (!in.material) in.material = p;
        } else if (auto* p = std::get_if<nif::NiTextureProperty>(&b)) {
            if (!in.texture) {
                in.texture = p;
                in.texture_link_id = link;
            }
        } else if (auto* p = std::get_if<nif::NiMultiTextureProperty>(&b)) {
            if (!in.multi_texture) in.multi_texture = p;
        } else if (auto* p = std::get_if<nif::NiAlphaProperty>(&b)) {
            if (!in.alpha) in.alpha = p;
        } else if (auto* p = std::get_if<nif::NiZBufferProperty>(&b)) {
            if (!in.zbuffer) in.zbuffer = p;
        } else if (auto* p = std::get_if<nif::NiVertexColorProperty>(&b)) {
            if (!in.vertex_color) in.vertex_color = p;
        }
    };

    for (auto link : shape.av.property_links) consider(link);

    if (shape_block_index >= f.block_ids.size()) return in;
    std::uint32_t cur_id = f.block_ids[shape_block_index];
    while (true) {
        auto it = child_to_parent.find(cur_id);
        if (it == child_to_parent.end()) break;
        const std::size_t parent_idx = it->second;
        const auto* parent = std::get_if<nif::NiNode>(&f.blocks[parent_idx]);
        if (!parent) break;
        for (auto link : parent->av.property_links) consider(link);
        cur_id = f.block_ids[parent_idx];
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
    const auto nif_block_to_bone = skel.nif_block_to_bone_index;  // copy for weight fill
    model.skeleton = std::move(skel.skeleton);

    // Map each skeleton bone's name -> its index, to bind rigid shapes to the
    // bone their NIF node corresponds to (the node and bone share a name).
    // Assumes bone names are unique (true for the canonical Bip01 skeleton);
    // a duplicate name would keep the last bone, mis-following only under a pose.
    std::unordered_map<std::string, int> bone_by_name;
    for (std::size_t b = 0; b < model.skeleton.bones.size(); ++b)
        bone_by_name[model.skeleton.bones[b].name] = static_cast<int>(b);

    // 2. Textures.
    auto tex_result = load_all_textures(f, model, ctx, resolver);

    // 3. Nodes.
    auto nodes = build_nodes(f, resolver);
    if (nodes.nodes.empty()) throw ModelBuildError("no NiNode root in NIF file");
    model.nodes = std::move(nodes.nodes);
    model.root_node = 0;

    // Bind-world of each model node (product of node local_transforms root->node).
    // Used to bake RIGID character shapes into bind-model space (SP2). Nodes are
    // ordered parents-before-children, so a single linear pass suffices.
    std::vector<glm::mat4> node_bind_world(model.nodes.size(), glm::mat4(1.0f));
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        const auto& nd = model.nodes[i];
        node_bind_world[i] = nd.parent_index >= 0
            ? node_bind_world[nd.parent_index] * nd.local_transform
            : nd.local_transform;
    }

    // 4. Meshes + materials, in lock-step.
    auto mesh_upload = ctx.mesh_uploader
        ? ctx.mesh_uploader
        : MeshUploaderFn([](MeshCpu cpu) { return upload_mesh(cpu); });

    auto child_to_parent = build_child_to_parent_map(f);

    // NiFlipController plumbing. For every NiTextureProperty whose own
    // image_link is 0 but whose controller_link resolves to a
    // NiFlipController, build:
    //   (a) flip_image_override_for_prop: (property link_id → frame-0
    //       NiImage link_id) so apply_texture_property assigns the
    //       first frame to stages[Base].texture_index;
    //   (b) flip_animation_index_for_prop: (property link_id →
    //       Model::texture_animations index) so the renderer can pick
    //       per-frame textures at draw time;
    //   (c) Model::texture_animations entry: full timing + per-frame
    //       texture indices (resolved via tex_result.image_to_texture).
    std::unordered_map<std::uint32_t, std::uint32_t> flip_image_override_for_prop;
    std::unordered_map<std::uint32_t, int>           flip_animation_index_for_prop;
    for (std::size_t i = 0; i < f.blocks.size(); ++i) {
        const auto* prop = std::get_if<nif::NiTextureProperty>(&f.blocks[i]);
        if (!prop) continue;
        if (prop->image_link != 0) continue;
        auto ctrl_idx = resolver.resolve(prop->obj.controller_link);
        if (ctrl_idx == LinkResolver::kInvalidIndex) continue;
        if (ctrl_idx >= f.blocks.size()) continue;
        const auto* ctrl = std::get_if<nif::NiFlipController>(&f.blocks[ctrl_idx]);
        if (!ctrl || ctrl->image_links.empty()) continue;
        const std::uint32_t prop_link_id =
            (i < f.block_ids.size()) ? f.block_ids[i] : static_cast<std::uint32_t>(i);
        flip_image_override_for_prop[prop_link_id] = ctrl->image_links[0];

        TextureAnimation anim;
        anim.delta      = static_cast<double>(ctrl->delta);
        anim.start_time = static_cast<double>(ctrl->start_time);
        anim.frequency  = static_cast<double>(ctrl->frequency);
        anim.phase      = static_cast<double>(ctrl->phase);
        // Skip image_links[0]: BC's NiFlipController treats element 0
        // as the property's static base texture (the one BC would show
        // if the controller weren't running), and cycles only elements
        // 1..N. EBridge's LCarsSchematicRight is the base; LCarsAnim1
        // ..LCarsAnim7 are the actual animation frames.
        if (ctrl->image_links.size() >= 2) {
            anim.texture_indices.reserve(ctrl->image_links.size() - 1);
            for (std::size_t fi = 1; fi < ctrl->image_links.size(); ++fi) {
                auto it = tex_result.image_to_texture.find(ctrl->image_links[fi]);
                if (it == tex_result.image_to_texture.end()) {
                    // Frame's NiImage didn't load — drop the whole anim
                    // to avoid binding an invalid index later.
                    anim.texture_indices.clear();
                    break;
                }
                anim.texture_indices.push_back(it->second);
            }
        }
        if (anim.texture_indices.empty()) continue;
        const int anim_idx = static_cast<int>(model.texture_animations.size());
        model.texture_animations.push_back(std::move(anim));
        flip_animation_index_for_prop[prop_link_id] = anim_idx;
    }

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
            f, /*shape_block_index=*/i, *shape, child_to_parent,
            tex_result.image_to_texture, tex_result.glow_image_links,
            tex_result.specular_image_links,
            tex_result.sibling_specular_for_image, resolver);
        mat_inputs.image_filename_for_link = &tex_result.image_filename_for_link;
        mat_inputs.flip_image_override_for_prop = &flip_image_override_for_prop;
        Material mat = build_material(mat_inputs);
        if (mat_inputs.texture_link_id != 0) {
            auto it = flip_animation_index_for_prop.find(mat_inputs.texture_link_id);
            if (it != flip_animation_index_for_prop.end()) {
                mat.animation_index = it->second;
            }
        }
        int mat_index = static_cast<int>(model.materials.size());
        model.materials.push_back(std::move(mat));

        int node_index = find_parent_node_index(f, i, nodes, resolver);

        // Skinning: if this shape carries a NiTriShapeSkinController via its
        // controller link, map its bones to skeleton indices and fill
        // per-vertex weights. BC character shapes attach the skin controller
        // directly to the shape's controller link, so we resolve that single
        // link rather than walking the controller chain. Mirrors
        // gather_bone_block_indices' resolve. Resolve it FIRST so we know
        // whether this shape is rigid before building the mesh (SP2).
        const nif::NiTriShapeSkinController* skin = nullptr;
        if (!model.skeleton.bones.empty()) {
            std::uint32_t ctrl = shape->av.obj.controller_link;
            if (ctrl != 0) {
                auto ci = resolver.resolve(ctrl);
                if (ci != LinkResolver::kInvalidIndex && ci < f.blocks.size())
                    skin = std::get_if<nif::NiTriShapeSkinController>(&f.blocks[ci]);
            }
        }

        // SP2: ALL character shapes (rigid AND skinned) are baked into
        // bind-model space via the parent node's bind-world. The renderer feeds
        // u_model = inst.world, so the per-node bind-world factor SP1's
        // node-walk applied is no longer in u_model and MUST live in the verts.
        // fill_skin_weights applies no compensating bind transform, so skinned
        // verts must already be in bind-model space. At bind, palette = identity
        // ⇒ pos = inst.world · node_bind_world[parent] · v_nodelocal, exactly
        // SP1's world_per_node[parent]·v; under a pose the palette poses it. The
        // ONLY rigid/skinned difference is the WEIGHTS (single parent bone vs
        // multi-bone via fill_skin_weights). Non-skeleton models keep identity.
        glm::mat4 bake(1.0f);
        if (!model.skeleton.bones.empty() &&
            node_index >= 0 &&
            node_index < static_cast<int>(node_bind_world.size()))
            bake = node_bind_world[node_index];

        MeshCpu cpu = build_mesh_cpu(*shape, *data, mat_index, node_index, bake);

        if (!model.skeleton.bones.empty()) {
            if (skin) {
                std::vector<int> skin_bone_to_skeleton(skin->bone_links.size(), -1);
                for (std::size_t b = 0; b < skin->bone_links.size(); ++b) {
                    auto blk = resolver.resolve(skin->bone_links[b]);
                    auto it = nif_block_to_bone.find(blk);
                    if (it != nif_block_to_bone.end())
                        skin_bone_to_skeleton[b] = it->second;
                }
                fill_skin_weights(cpu, *skin, skin_bone_to_skeleton);
            } else {
                // Skinned model, but this shape carries NO skin controller. In
                // BC, body parts are rigid shapes parented to bone nodes (the
                // static node-walk in draw_model already places them via
                // u_model = world * node_chain). When this model is drawn
                // through the skinned program, every vertex is blended by the
                // bone palette; a default {0,0,0,0} weight would collapse the
                // shape to the origin.
                //
                // Bind every vertex fully to the shape's PARENT bone so the
                // rigid part follows the right bone under a pose. node_index is
                // this shape's parent NiNode; the node and its skeleton bone
                // share a name, so we resolve it through bone_by_name. Fall back
                // to bone 0 (the root) only if unmatched. At bind pose every
                // palette entry is identity, so binding to the parent bone is
                // byte-identical to bone 0 and matches the static draw exactly;
                // under a pose it now follows the correct bone (SP1's bone-0
                // caveat is resolved here).
                int rigid_bone = 0;
                if (node_index >= 0 &&
                    node_index < static_cast<int>(model.nodes.size())) {
                    auto it = bone_by_name.find(model.nodes[node_index].name);
                    if (it != bone_by_name.end()) rigid_bone = it->second;
                }
                const auto idx =
                    static_cast<std::uint8_t>(std::clamp(rigid_bone, 0, 255));
                for (auto& v : cpu.vertices) {
                    v.bone_indices = glm::u8vec4(idx, 0, 0, 0);
                    v.bone_weights = glm::u8vec4(255, 0, 0, 0);
                }
            }
        }

        if (node_index >= 0) {
            int mesh_idx = static_cast<int>(model.meshes.size());
            model.nodes[node_index].meshes.push_back(mesh_idx);
        }
        // Avoid copying the CPU vertex data unless retention is requested.
        if (ctx.keep_cpu_data) {
            // Ships retain CPU geometry (for ray-tracing) and are the only
            // models that deform — bake per-vertex crushability here, before
            // upload, so attribute 7 carries real thickness-derived weights.
            // Non-retained models (bridge/props/UI) keep the 0.5 default.
            bake_crushability(cpu);
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
