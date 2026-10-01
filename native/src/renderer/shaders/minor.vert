#version 410 core
// Minor rocks (minor-rocks spec §2): opaque.vert with a per-instance model
// matrix. Linked with opaque.frag, so minors are lit exactly as majors are.
layout(location = 0) in vec3 a_position;
layout(location = 1) in vec3 a_normal;
layout(location = 2) in vec2 a_uv;
layout(location = 7) in vec4 a_row0;   // rows of [R*s | t], RENDER space
layout(location = 8) in vec4 a_row1;
layout(location = 9) in vec4 a_row2;

uniform mat4 u_view;
uniform mat4 u_proj;

out vec3 v_normal_ws;
out vec2 v_uv;
out vec3 v_position_ws;
flat out float v_dither;   // opaque.frag's far-tier dither; minors never dither

void main() {
    mat4 model = transpose(mat4(a_row0, a_row1, a_row2, vec4(0.0, 0.0, 0.0, 1.0)));
    vec4 ws = model * vec4(a_position, 1.0);
    v_normal_ws = mat3(model) * a_normal;
    v_uv = a_uv;
    v_position_ws = ws.xyz;
    gl_Position = u_proj * u_view * ws;
    v_dither = 0.0;
}
