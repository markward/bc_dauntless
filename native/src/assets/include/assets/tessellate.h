// native/src/assets/include/assets/tessellate.h
#pragma once

#include <assets/mesh.h>
#include <assets/model.h>

namespace assets {

// One level of boundary-pinned Phong tessellation. Splits every triangle into 4
// (three edge midpoints), projecting INTERIOR midpoints onto the per-vertex
// tangent planes to round the silhouette, while pinning midpoints that lie on a
// mesh boundary edge to the flat linear position so separate body/head shapes
// never crack apart at their shared seam. Boundaries are classified by welded
// vertex POSITION, so a UV seam (duplicate verts on a continuous surface) rounds
// while genuine open borders stay pinned. All vertex attributes (uv, uv1, color,
// bone indices/weights) are interpolated; bone influences are accumulated across
// the two endpoints and the top four kept, so rigid shapes (single shared bone)
// are unchanged and skinned shapes blend correctly.
//
// `phong_strength` in [0,1]: 0 = pure linear subdivision (no silhouette gain),
// 1.0 = full projection onto the tangent planes (the natural maximum; values
// above extrapolate past it and balloon).
MeshCpu tessellate_phong(const MeshCpu& src, float phong_strength = 0.75f);

// Apply `levels` of tessellation at `strength` to every mesh of `model` that
// retains cpu_data, re-uploading each in place. Each level x4 triangles. Meshes
// without cpu_data are skipped; `levels <= 0` is a no-op.
void tessellate_model_in_place(Model& model, int levels = 1,
                               float strength = 1.0f);

}  // namespace assets
