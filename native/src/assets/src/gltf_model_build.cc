#include "gltf_model_build.h"

#include <assets/gltf.h>
#include <assets/hull_source.h>
#include <assets/material.h>
#include <assets/mesh.h>
#include <assets/texture.h>

#include <cstdint>
#include <cstdio>
#include <fstream>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>

namespace fs = std::filesystem;

namespace assets::detail {

namespace {

std::vector<std::uint8_t> read_file_bytes(const fs::path& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        throw ModelBuildError("could not open glTF image file: " + path.string());
    }
    in.seekg(0, std::ios::end);
    const auto size = static_cast<std::size_t>(in.tellg());
    in.seekg(0, std::ios::beg);
    std::vector<std::uint8_t> bytes(size);
    in.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(size));
    return bytes;
}

}  // namespace

Model build_model_from_gltf(const fs::path& path, float scale, const ModelBuildContext& ctx) {
    gltf::CpuScene scene = gltf::load_cpu(path, scale);

    Model model;

    auto upload = ctx.texture_uploader
        ? ctx.texture_uploader
        : TextureUploaderFn(&assets::upload_image);

    // CpuImage::key -> Model::textures index. A failed load is cached too (as
    // -1), so a bad texture referenced by multiple materials only warns once
    // and is only attempted once. `key` dedupes both external images (by
    // path) and embedded ones (by "<gltf path>#image<N>"), so two materials
    // that happen to reference the same embedded image share one upload.
    std::unordered_map<std::string, int> tex_index_for_path;
    static std::unordered_set<std::string> warned;

    auto load_texture = [&](const gltf::CpuImage& image) -> int {
        if (image.empty()) return -1;
        const std::string& key = image.key;
        auto found = tex_index_for_path.find(key);
        if (found != tex_index_for_path.end()) return found->second;

        int index = -1;
        try {
            std::vector<std::uint8_t> bytes =
                image.bytes.empty() ? read_file_bytes(image.path) : image.bytes;
            Image decoded = decode_image(bytes);
            Texture tex = upload(decoded, /*generate_mipmaps=*/true);
            index = static_cast<int>(model.textures.size());
            model.textures.push_back(std::move(tex));
        } catch (const std::exception& e) {
            if (warned.insert(key).second) {
                std::fprintf(stderr,
                    "[gltf_model_build] texture '%s': %s; leaving stage unset\n",
                    key.c_str(), e.what());
            }
        }
        tex_index_for_path[key] = index;
        return index;
    };

    model.materials.reserve(scene.materials.size());
    for (const auto& cm : scene.materials) {
        Material mat;
        mat.diffuse = glm::vec3(cm.base_color_factor);
        mat.alpha = cm.base_color_factor.a;
        mat.specular = glm::vec3(0.12f);  // the branch's rock value
        mat.glossiness = 0.0f;
        mat.stages[static_cast<std::size_t>(Material::StageSlot::Base)].texture_index =
            load_texture(cm.base_color_image);
        mat.stages[static_cast<std::size_t>(Material::StageSlot::Bump)].texture_index =
            load_texture(cm.normal_image);
        model.materials.push_back(mat);
    }

    // One root node holding every mesh.
    Node root;
    root.name = "gltf_root";
    root.parent_index = -1;
    model.nodes.push_back(std::move(root));
    model.root_node = 0;

    auto mesh_upload = ctx.mesh_uploader
        ? ctx.mesh_uploader
        : MeshUploaderFn([](MeshCpu cpu) { return upload_mesh(cpu); });

    model.meshes.reserve(scene.meshes.size());
    for (std::size_t i = 0; i < scene.meshes.size(); ++i) {
        MeshCpu cpu = std::move(scene.meshes[i]);
        Mesh mesh = ctx.keep_cpu_data ? mesh_upload(MeshCpu(cpu)) : mesh_upload(std::move(cpu));
        mesh.set_shape_name("gltf_mesh_" + std::to_string(i));
        if (ctx.keep_cpu_data) mesh.set_cpu_data(std::move(cpu));
        const int mesh_index = static_cast<int>(model.meshes.size());
        model.nodes[0].meshes.push_back(mesh_index);
        model.meshes.push_back(std::move(mesh));
    }

    model.source = hull_source_string(path, scale);
    return model;
}

}  // namespace assets::detail
