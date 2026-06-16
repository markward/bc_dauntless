#version 410 core
// Identity pass-through; cw winding is arbitrary here (the smoke test draws
// without face culling). Real displacement shaders set winding to match the mesh.
layout(triangles, equal_spacing, cw) in;
void main() {
    gl_Position = gl_TessCoord.x * gl_in[0].gl_Position
                + gl_TessCoord.y * gl_in[1].gl_Position
                + gl_TessCoord.z * gl_in[2].gl_Position;
}
