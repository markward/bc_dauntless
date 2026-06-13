#version 330 core
layout(location = 0) in vec3 a_position;
layout(location = 1) in vec3 a_normal;
layout(location = 2) in vec2 a_uv;
layout(location = 4) in ivec4 a_bone_indices;
layout(location = 5) in vec4  a_bone_weights;

uniform mat4 u_model;
uniform mat4 u_view;
uniform mat4 u_proj;
uniform mat4 u_bones[128];

out vec3 v_normal_ws;
out vec2 v_uv;
out vec3 v_position_ws;

void main() {
    mat4 skin = a_bone_weights.x * u_bones[a_bone_indices.x]
              + a_bone_weights.y * u_bones[a_bone_indices.y]
              + a_bone_weights.z * u_bones[a_bone_indices.z]
              + a_bone_weights.w * u_bones[a_bone_indices.w];
    vec4 ws = u_model * skin * vec4(a_position, 1.0);
    v_normal_ws   = mat3(u_model) * mat3(skin) * a_normal;
    v_uv          = a_uv;
    v_position_ws = ws.xyz;
    gl_Position   = u_proj * u_view * ws;
}
