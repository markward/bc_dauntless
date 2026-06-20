#version 330 core
// Depth-only shadow caster vertex stage. Position attribute location MUST match
// opaque.vert (layout(location = 0) in vec3 a_position) so the same mesh VAOs
// feed this program unchanged. No normals/uvs/skinning — depth is all we write.
layout(location = 0) in vec3 a_position;

uniform mat4 u_light_view_proj;
uniform mat4 u_model;

void main() {
    gl_Position = u_light_view_proj * u_model * vec4(a_position, 1.0);
}
