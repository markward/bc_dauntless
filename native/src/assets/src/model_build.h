// native/src/assets/src/model_build.h
#pragma once

#include <assets/model.h>
#include <assets/path_resolver.h>
#include <nif/file.h>

#include <filesystem>
#include <functional>
#include <stdexcept>
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
};

class ModelBuildError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

Model build_model(const nif::File& f, const ModelBuildContext& ctx);

}  // namespace assets::detail
