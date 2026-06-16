#version 330 core

layout(location = 0) in vec3 a_position;
layout(location = 1) in vec3 a_normal;
layout(location = 2) in vec2 a_uv;
layout(location = 3) in vec4 a_color;
layout(location = 4) in vec4 a_bone_indices;
layout(location = 5) in vec4 a_bone_weights;

uniform mat4 u_model;
uniform mat4 u_view;
uniform mat4 u_proj;

out vec3  v_normal_ws;
out vec2  v_uv;
out vec3  v_position_ws;
out float v_deform_depth;   // |hull displacement| (model units); 0 on the static path

void main() {
    vec4 ws = u_model * vec4(a_position, 1.0);
    v_normal_ws   = mat3(u_model) * a_normal;
    v_uv          = a_uv;
    v_position_ws = ws.xyz;
    v_deform_depth = 0.0;
    gl_Position   = u_proj * u_view * ws;
}
