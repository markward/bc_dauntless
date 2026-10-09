// native/src/assets/src/model_build.h
#pragma once

#include <assets/model.h>
#include <assets/path_resolver.h>
#include <nif/file.h>

#include <filesystem>
#include <functional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace assets::detail {

using TextureUploaderFn = std::function<Texture(const Image&, bool)>;
using MeshUploaderFn    = std::function<Mesh(MeshCpu)>;

struct ModelBuildContext {
    PathResolver*                       resolver = nullptr;
    std::vector<std::filesystem::path>  texture_search_paths;
    TextureUploaderFn                   texture_uploader; // empty -> calls upload_image
    MeshUploaderFn                      mesh_uploader;    // empty -> calls upload_mesh
    bool                                keep_cpu_data = false;
    /// Per-registry hull-name swaps (Federation ship registry textures).
    /// Empty for the overwhelming majority of models; an empty list makes
    /// build_model byte-identical to the no-replacement path.
    std::vector<TextureReplacement>     texture_replacements;
    /// Hull-name decal placements (see DecalRequest, model.h). Empty for the
    /// overwhelming majority of models; an empty list makes build_model
    /// byte-identical to the no-decal path.
    std::vector<DecalRequest>           decals;
    /// Generate smooth normals for every shape authored WITHOUT normals
    /// (spec 2026-10-08-bridge-lighting-baseline-design.md §3). Set only for
    /// interior-set models; false keeps build_model byte-identical.
    bool                                generate_missing_normals = false;
    /// Interior sibling-map lookup policy (spec 2026-10-08-bridge-emitters
    /// §9.2/§9.3): when true, a sibling `_rough`/`_metal`/`_normal` probe is
    /// restricted to EITHER `sibling_overlay_dirs` (when the resolved albedo
    /// lives in the stock dir -- the last entry of texture_search_paths) OR
    /// just the albedo's own directory (otherwise); an empty resulting list
    /// means no probe at all. False (every ship load) keeps today's
    /// behaviour byte-identical: probe every texture_search_paths entry.
    bool                                interior_sibling_policy = false;
    /// Directories probed for a STOCK albedo's sibling maps when
    /// interior_sibling_policy is true (the replacements overlay). Ignored
    /// otherwise.
    std::vector<std::filesystem::path> sibling_overlay_dirs;
    /// Optional sink for each Model::textures entry's AUTHORED source basename
    /// ("body.tga", "head.tga", …), sized to model.textures.size(). Entries the
    /// loader synthesized rather than read from a NiImage (sibling _specular /
    /// _normal maps, embedded raw images) are left EMPTY. The loader knows this
    /// and otherwise discards it; compose_officer_model needs it to tell a
    /// body's uniform slot from its skin slot. nullptr -> not recorded.
    std::vector<std::string>*           out_texture_sources = nullptr;
};

class ModelBuildError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

/// True if `fname`'s extension-less basename ends in "_normal" or "_norm"
/// (case-insensitive). BC authored no normal maps at all, so both forms are
/// ours; the long form is primary. Declared here (unlike the file-local
/// _glow / _specular predicates) so the filename rules are unit-testable.
bool filename_is_normal(std::string_view fname);

/// True if `fname`'s extension-less basename ends in "_emissive",
/// "_emissive_y" or "_emissive_r" (case-insensitive): an emissive sibling map
/// (task 17), a derived map that is never itself probed for siblings.
bool filename_is_emissive(std::string_view fname);

/// Given "Hull.tga" or "Hull_glow.tga", produce the sibling normal-map
/// filename "Hull_normal.tga". Strips a trailing "_glow" (case-insensitive)
/// from the stem before appending, so a hull's diffuse and its glow map
/// resolve to the SAME normal map — matching sibling_specular_filename.
std::string sibling_normal_filename(std::string_view fname);

/// Given a texture filename and a sibling suffix (e.g. "_rough", "_metal",
/// "_normal"), produce the sibling map's filename: strips a trailing "_glow"
/// (case-insensitive) from the stem, then appends `suffix` before the
/// extension. `sibling_normal_filename` is sibling_map_filename(fname,
/// "_normal"); shared by the bridge PBR roughness/metalness siblings.
std::string sibling_map_filename(std::string_view fname, std::string_view suffix);

Model build_model(const nif::File& f, const ModelBuildContext& ctx);

/// True if `u_axis`, `v_axis` and `normal` don't span a usable 3D basis
/// (decal_body_to_mask would produce inf/NaN). Shared by apply_decals and
/// build_decal_override (decal_override.h) so both reject the same inputs.
bool decal_projector_is_degenerate(
    const glm::vec3& u_axis, const glm::vec3& v_axis, const glm::vec3& normal);

/// Premultiply an RGBA8 hull-decal mask's RGB by its alpha in place (spec §2:
/// opaque.frag composites base*(1-a) + mask.rgb). RGB8 / R8 are untouched --
/// implicit alpha 1. The ONE premultiply both the baked path (apply_decals)
/// and the per-instance mask cache (DecalMaskCache) use.
void premultiply_decal_mask(Image& image);

/// The dedupe key for a hull-decal mask path (spec §2.4a: masks dedupe by
/// resolved absolute path): weakly_canonical when the filesystem can answer,
/// else absolute + lexically_normal. Two spellings of one file ("m.png",
/// "./m.png") share a key, so they share a mask slot. Shared by apply_decals
/// and build_decal_override. Never throws.
std::string decal_mask_key(const std::filesystem::path& mask);

/// Build the ship-body-frame -> mask-space affine transform for a hull-name
/// decal: `origin` maps to mask (0,0,0), `origin+u_axis` to (1,0,0),
/// `origin+v_axis` to (0,1,0), and a point `depth` units along the unit
/// normal from the rectangle's plane to (0,0,depth). Exposed for direct
/// testing; callers must have already rejected a degenerate basis
/// (|u_axis x v_axis| < 1e-9) -- this function does not check.
glm::mat4 decal_body_to_mask(const glm::vec3& origin, const glm::vec3& u_axis,
                             const glm::vec3& v_axis, const glm::vec3& normal);

}  // namespace assets::detail
