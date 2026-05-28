#version 330 core

// Camera-aligned billboard for the BC SunEffect overlay layer.
// Drawn as 4 vertices in a TRIANGLE_STRIP with corners encoded in a_corner
// ((-1,-1), (1,-1), (-1,1), (1,1)). World-space center comes in as a
// uniform so we don't need a per-instance VBO.

layout(location=0) in vec2 a_corner;   // unit-square corner in [-1,1]^2

uniform mat4  u_proj;
uniform mat4  u_view;
uniform vec3  u_world_center;
uniform float u_half_size;

out vec2 v_uv;

void main() {
    // Right and up of the camera in world space: rows 0 and 1 of the
    // view matrix transposed (i.e. columns 0 and 1 of view^T).
    vec3 right = vec3(u_view[0][0], u_view[1][0], u_view[2][0]);
    vec3 up    = vec3(u_view[0][1], u_view[1][1], u_view[2][1]);
    vec3 world = u_world_center
               + right * (a_corner.x * u_half_size)
               + up    * (a_corner.y * u_half_size);
    gl_Position = u_proj * u_view * vec4(world, 1.0);
    v_uv = a_corner * 0.5 + 0.5;   // [-1,1]^2 → [0,1]^2
}
