#version 410 core
// One full-target triangle from gl_VertexID (no vertex buffer), for the puff
// hash-table bake (rock_puff_hash.frag).
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
