// native/src/host/model_identity_maps.cc
#include "model_identity_maps.h"

#include <assets/model.h>

namespace dauntless {

int safe_material_index(const assets::Model& model, int material_index) {
    return (material_index >= 0 &&
            material_index < static_cast<int>(model.materials.size()))
           ? material_index
           : -1;
}

MeshMaps mesh_identity_maps(const assets::Model& model, int material_index) {
    const int safe_mi = safe_material_index(model, material_index);
    const assets::Material& mat = assets::material_or_default(model, safe_mi);
    using S = assets::Material::StageSlot;
    MeshMaps maps;
    maps.roughness = mat.stages[static_cast<std::size_t>(S::Roughness)].texture_index >= 0;
    maps.metalness = mat.stages[static_cast<std::size_t>(S::Metalness)].texture_index >= 0;
    maps.normal    = mat.stages[static_cast<std::size_t>(S::Bump)].texture_index >= 0;
    maps.emissive  = mat.stages[static_cast<std::size_t>(S::Emissive)].texture_index >= 0;
    return maps;
}

}  // namespace dauntless
