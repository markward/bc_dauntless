// native/src/assets/src/model_build.h
#pragma once

#include <assets/model.h>
#include <assets/path_resolver.h>
#include <nif/file.h>

#include <filesystem>
#include <functional>
#include <stdexcept>

namespace assets::detail {

using TextureUploaderFn = std::function<Texture(const Image&, bool)>;
using MeshUploaderFn    = std::function<Mesh(MeshCpu)>;

struct ModelBuildContext {
    PathResolver*           resolver = nullptr;
    std::filesystem::path   texture_search_path;
    TextureUploaderFn       texture_uploader;     // empty -> calls upload_image
    MeshUploaderFn          mesh_uploader;        // empty -> calls upload_mesh
    bool                    keep_cpu_data = false;
};

class ModelBuildError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

Model build_model(const nif::File& f, const ModelBuildContext& ctx);

}  // namespace assets::detail
