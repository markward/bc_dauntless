// native/src/host/model_identity_maps.h
//
// The body of model_identity's per-mesh "maps" computation (spec
// 2026-10-09-bridge-pbr), as free functions so it is unit-tested in C++
// (native/tests/host) against a hand-built assets::Model -- the binding
// itself has no test fixture for an out-of-range material index, since every
// NIF-loaded model's mesh.material_index() is already in range by
// construction.
#pragma once

namespace assets { struct Model; }

namespace dauntless {

/// Clamp a mesh's material_index() to -1 when it is not a valid index into
/// `model.materials`. assets::material_or_default requires the CALLER to
/// guarantee a non-negative index is in range -- it indexes with operator[]
/// and performs no bounds check of its own, so an out-of-range index passed
/// to it is an out-of-bounds read. Shared by model_identity's textures and
/// maps lookups so both treat a malformed index identically (no textures,
/// all-false maps) instead of each re-implementing (or skipping) the check.
int safe_material_index(const assets::Model& model, int material_index);

/// Which texture stages (roughness / metalness / normal == Bump) a mesh's
/// material has populated. `material_index` is bounds-checked internally via
/// safe_material_index -- callers never need to check it themselves, and an
/// out-of-range index yields the same all-false result as no material at
/// all (material_index == -1), never an out-of-bounds read.
struct MeshMaps {
    bool roughness = false;
    bool metalness = false;
    bool normal = false;
};
MeshMaps mesh_identity_maps(const assets::Model& model, int material_index);

}  // namespace dauntless
