// native/src/assets/src/mesh_upload.h
//
// Vertex layout (interleaved, 44 bytes, all attributes always present):
//   loc 0: vec3   position        offsetof = 0
//   loc 1: vec3   normal          offsetof = 12
//   loc 2: vec2   uv              offsetof = 24
//   loc 3: vec4 ub color          offsetof = 32  (normalized)
//   loc 4: ivec4 ub bone_indices  offsetof = 36  (integer attribute)
//   loc 5: vec4 ub bone_weights   offsetof = 40  (normalized)
//
// upload_mesh is now declared in the public header <assets/mesh.h>; this
// internal header is retained because asset .cc files include it for the
// vertex-layout doc comment above.
#pragma once

#include <assets/mesh.h>
