#define CGLTF_IMPLEMENTATION
#include <cgltf.h>

#include <assets/cache.h>
#include <assets/gltf.h>

#include <glm/gtc/matrix_inverse.hpp>
#include <glm/gtc/type_ptr.hpp>

#include <cstdlib>
#include <cstring>
#include <iostream>
#include <memory>
#include <nlohmann/json.hpp>
#include <string>
#include <string_view>
#include <unordered_set>
#include <vector>

namespace assets::gltf {

namespace {

struct CgltfDataDeleter {
    void operator()(cgltf_data* data) const noexcept {
        if (data) cgltf_free(data);
    }
};
using CgltfDataPtr = std::unique_ptr<cgltf_data, CgltfDataDeleter>;

// Warn at most once per (file path, feature) pair, for the lifetime of the
// process. Keyed on the full path string so distinct files each get their
// own warning, but re-loading the same file (as tests do, to prove the
// warn-once contract) does not repeat it.
void warn_once(const std::string& path, const char* feature) {
    static std::unordered_set<std::string> seen;
    std::string key = path;
    key += '|';
    key += feature;
    if (seen.insert(key).second) {
        std::cerr << "gltf: " << path << ": ignoring " << feature << "\n";
    }
}

bool is_data_uri(const char* uri) {
    return uri != nullptr && std::string_view(uri).rfind("data:", 0) == 0;
}

// Resolves a texture view's image to either an external path or embedded
// bytes: `image->buffer_view` set means a `.glb` binary-chunk image (cgltf
// has already loaded the GLB BIN chunk / any external buffers via
// cgltf_load_buffers, so cgltf_buffer_view_data just returns a pointer into
// it); a `data:` URI is decoded with cgltf_load_buffer_base64, sized from the
// base64 payload length; anything else is today's external-file path.
CpuImage resolve_image(const cgltf_data* data, const std::filesystem::path& gltf_path,
                       const cgltf_texture_view& view, const std::string& path_str) {
    if (!view.texture || !view.texture->image) return {};
    const cgltf_image* image = view.texture->image;
    const int index = static_cast<int>(image - data->images);

    if (image->buffer_view) {
        const std::uint8_t* bytes = cgltf_buffer_view_data(image->buffer_view);
        if (!bytes) {
            warn_once(path_str, "unreadable embedded image");
            return {};
        }
        CpuImage out;
        out.key = path_str + "#image" + std::to_string(index);
        out.bytes.assign(bytes, bytes + image->buffer_view->size);
        return out;
    }

    if (!image->uri || image->uri[0] == '\0') return {};

    if (is_data_uri(image->uri)) {
        const char* comma = std::strchr(image->uri, ',');
        if (!comma) {
            warn_once(path_str, "malformed data-uri image");
            return {};
        }
        const std::string_view b64(comma + 1);
        const cgltf_size len = b64.size();
        cgltf_size padding = 0;
        if (len >= 1 && b64[len - 1] == '=') ++padding;
        if (len >= 2 && b64[len - 2] == '=') ++padding;
        const cgltf_size decoded_size = len / 4 * 3 - padding;

        cgltf_options options{};
        void* decoded = nullptr;
        cgltf_result result = cgltf_load_buffer_base64(&options, decoded_size, comma + 1, &decoded);
        if (result != cgltf_result_success || !decoded) {
            warn_once(path_str, "undecodable data-uri image");
            return {};
        }
        const auto* decoded_bytes = static_cast<const std::uint8_t*>(decoded);
        CpuImage out;
        out.key = path_str + "#image" + std::to_string(index);
        out.bytes.assign(decoded_bytes, decoded_bytes + decoded_size);
        std::free(decoded);
        return out;
    }

    CpuImage out;
    out.path = gltf_path.parent_path() / image->uri;
    out.key = out.path.string();
    return out;
}

// Unpacks a whole accessor's worth of `components`-wide floats in one call.
// Unlike per-element cgltf_accessor_read_float, cgltf_accessor_unpack_floats
// applies sparse substitution (its documented "second pass"), so a sparse
// POSITION/NORMAL/TEXCOORD_0 reads its overridden values instead of silently
// coming back as zero.
std::vector<float> unpack_floats(const cgltf_accessor* accessor, cgltf_size components) {
    std::vector<float> out(accessor->count * components, 0.0f);
    cgltf_accessor_unpack_floats(accessor, out.data(), out.size());
    return out;
}

}  // namespace

glm::vec3 to_bc_frame(glm::vec3 v_gltf) { return {-v_gltf.x, v_gltf.z, v_gltf.y}; }

CpuScene load_cpu(const std::filesystem::path& path, float scale) {
    const std::string path_str = path.string();

    cgltf_options options{};
    cgltf_data* raw_data = nullptr;
    cgltf_result result = cgltf_parse_file(&options, path_str.c_str(), &raw_data);
    if (result != cgltf_result_success) {
        throw AssetError("gltf: " + path_str + ": parse failed (code " +
                          std::to_string(static_cast<int>(result)) + ")");
    }
    CgltfDataPtr data(raw_data);

    result = cgltf_load_buffers(&options, data.get(), path_str.c_str());
    if (result != cgltf_result_success) {
        throw AssetError("gltf: " + path_str + ": failed to load buffers (code " +
                          std::to_string(static_cast<int>(result)) + ")");
    }

    result = cgltf_validate(data.get());
    if (result != cgltf_result_success) {
        throw AssetError("gltf: " + path_str + ": validation failed (code " +
                          std::to_string(static_cast<int>(result)) + ")");
    }

    if (data->skins_count > 0) warn_once(path_str, "skins");
    if (data->animations_count > 0) warn_once(path_str, "animations");
    if (data->cameras_count > 0) warn_once(path_str, "cameras");
    if (data->extensions_used_count > 0) warn_once(path_str, "extensions");

    CpuScene scene;

    // Materials, in declaration order, so `material - data->materials` gives
    // the same index used by CpuMaterial's position in `scene.materials`.
    scene.materials.reserve(data->materials_count);
    for (cgltf_size i = 0; i < data->materials_count; ++i) {
        const cgltf_material& mat = data->materials[i];
        CpuMaterial cm;
        const auto& bcf = mat.pbr_metallic_roughness.base_color_factor;
        cm.base_color_factor = {bcf[0], bcf[1], bcf[2], bcf[3]};
        cm.base_color_image =
            resolve_image(data.get(), path, mat.pbr_metallic_roughness.base_color_texture, path_str);
        cm.normal_image = resolve_image(data.get(), path, mat.normal_texture, path_str);
        scene.materials.push_back(std::move(cm));
    }

    auto material_index_of = [&](const cgltf_material* m) -> int {
        if (!m) return -1;
        return static_cast<int>(m - data->materials);
    };

    auto visit_node = [&](cgltf_node* node, auto&& self) -> void {
        if (node->mesh) {
            float world_m[16];
            cgltf_node_transform_world(node, world_m);
            glm::mat4 world = glm::make_mat4(world_m);
            glm::mat3 normal_mat = glm::inverseTranspose(glm::mat3(world));

            const cgltf_mesh* mesh = node->mesh;
            for (cgltf_size pi = 0; pi < mesh->primitives_count; ++pi) {
                const cgltf_primitive& prim = mesh->primitives[pi];

                if (prim.targets_count > 0) warn_once(path_str, "morph targets");

                if (prim.type != cgltf_primitive_type_triangles) {
                    throw AssetError("gltf: " + path_str + ": non-triangle primitive");
                }

                const cgltf_accessor* position = nullptr;
                const cgltf_accessor* normal = nullptr;
                const cgltf_accessor* texcoord0 = nullptr;
                for (cgltf_size ai = 0; ai < prim.attributes_count; ++ai) {
                    const cgltf_attribute& attr = prim.attributes[ai];
                    if (attr.type == cgltf_attribute_type_position) {
                        position = attr.data;
                    } else if (attr.type == cgltf_attribute_type_normal) {
                        normal = attr.data;
                    } else if (attr.type == cgltf_attribute_type_texcoord && attr.index == 0) {
                        texcoord0 = attr.data;
                    }
                }

                if (!position) {
                    throw AssetError("gltf: " + path_str + ": primitive without POSITION");
                }

                MeshCpu out;
                out.material_index = material_index_of(prim.material);
                out.node_index = 0;

                const cgltf_size vertex_count = position->count;
                out.vertices.resize(vertex_count);

                std::vector<float> pos_buf = unpack_floats(position, 3);
                std::vector<float> nrm_buf = normal ? unpack_floats(normal, 3) : std::vector<float>{};
                std::vector<float> uv_buf =
                    texcoord0 ? unpack_floats(texcoord0, 2) : std::vector<float>{};

                for (cgltf_size vi = 0; vi < vertex_count; ++vi) {
                    glm::vec3 p_local{pos_buf[vi * 3 + 0], pos_buf[vi * 3 + 1], pos_buf[vi * 3 + 2]};
                    glm::vec3 p_world = glm::vec3(world * glm::vec4(p_local, 1.0f));
                    out.vertices[vi].position = to_bc_frame(p_world) * kMetresToModelUnits * scale;

                    if (normal) {
                        glm::vec3 n_local{nrm_buf[vi * 3 + 0], nrm_buf[vi * 3 + 1], nrm_buf[vi * 3 + 2]};
                        glm::vec3 n_world = normal_mat * n_local;
                        out.vertices[vi].normal = glm::normalize(to_bc_frame(n_world));
                    }
                    if (texcoord0) {
                        out.vertices[vi].uv = {uv_buf[vi * 2 + 0], uv_buf[vi * 2 + 1]};
                    }
                }

                const cgltf_size index_count = prim.indices ? prim.indices->count : vertex_count;
                out.indices.resize(index_count);
                for (cgltf_size ii = 0; ii < index_count; ++ii) {
                    out.indices[ii] = prim.indices
                                           ? static_cast<std::uint32_t>(
                                                 cgltf_accessor_read_index(prim.indices, ii))
                                           : static_cast<std::uint32_t>(ii);
                }

                if (!normal) {
                    // Flat normals, computed per triangle in BC frame after mapping.
                    for (cgltf_size t = 0; t + 2 < index_count; t += 3) {
                        std::uint32_t i0 = out.indices[t], i1 = out.indices[t + 1],
                                      i2 = out.indices[t + 2];
                        glm::vec3 a = out.vertices[i0].position, b = out.vertices[i1].position,
                                  c = out.vertices[i2].position;
                        glm::vec3 face_n = glm::normalize(glm::cross(b - a, c - a));
                        out.vertices[i0].normal = face_n;
                        out.vertices[i1].normal = face_n;
                        out.vertices[i2].normal = face_n;
                    }
                }

                scene.meshes.push_back(std::move(out));
            }
        }
        for (cgltf_size ci = 0; ci < node->children_count; ++ci) {
            self(node->children[ci], self);
        }
    };

    if (data->scene) {
        for (cgltf_size i = 0; i < data->scene->nodes_count; ++i) {
            visit_node(data->scene->nodes[i], visit_node);
        }
    } else if (data->scenes_count > 0) {
        for (cgltf_size i = 0; i < data->scenes[0].nodes_count; ++i) {
            visit_node(data->scenes[0].nodes[i], visit_node);
        }
    } else {
        for (cgltf_size i = 0; i < data->nodes_count; ++i) {
            if (!data->nodes[i].parent) visit_node(&data->nodes[i], visit_node);
        }
    }

    // Extras: asset.extras.dauntless_volume, resolved relative to the file.
    cgltf_size extras_size = 0;
    if (cgltf_copy_extras_json(data.get(), &data->asset.extras, nullptr, &extras_size) ==
            cgltf_result_success &&
        extras_size > 1) {
        std::vector<char> buf(extras_size);
        cgltf_copy_extras_json(data.get(), &data->asset.extras, buf.data(), &extras_size);
        auto parsed = nlohmann::json::parse(buf.data(), nullptr, false);
        if (!parsed.is_discarded() && parsed.is_object()) {
            auto it = parsed.find("dauntless_volume");
            if (it != parsed.end() && it->is_string()) {
                scene.volume = path.parent_path() / it->get<std::string>();
            }
        }
    }

    return scene;
}

}  // namespace assets::gltf
