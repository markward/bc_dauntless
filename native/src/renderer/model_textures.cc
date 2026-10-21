// native/src/renderer/model_textures.cc
#include <renderer/model_textures.h>

#include <assets/material.h>
#include <assets/model.h>

#include <cstddef>

namespace renderer {

unsigned int find_base_texture_id(const assets::Model& model) {
    constexpr auto kBase =
        static_cast<std::size_t>(assets::Material::StageSlot::Base);
    for (const auto& mesh : model.meshes) {
        const int mi = mesh.material_index();
        if (mi < 0 || static_cast<std::size_t>(mi) >= model.materials.size()) continue;
        const int ti = model.materials[static_cast<std::size_t>(mi)].stages[kBase].texture_index;
        if (ti < 0 || static_cast<std::size_t>(ti) >= model.textures.size()) continue;
        const unsigned int id = model.textures[static_cast<std::size_t>(ti)].id();
        if (id != 0) return id;
    }
    return 0;
}

}  // namespace renderer
