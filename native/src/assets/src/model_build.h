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

/// Given "Hull.tga" or "Hull_glow.tga", produce the sibling normal-map
/// filename "Hull_normal.tga". Strips a trailing "_glow" (case-insensitive)
/// from the stem before appending, so a hull's diffuse and its glow map
/// resolve to the SAME normal map — matching sibling_specular_filename.
std::string sibling_normal_filename(std::string_view fname);

Model build_model(const nif::File& f, const ModelBuildContext& ctx);

}  // namespace assets::detail
