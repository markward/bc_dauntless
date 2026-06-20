in vec2 a_pos;
out vec2 v_uv;
out vec4 v_offset;
void main() {
    v_uv = (a_pos + 1.0) * 0.5;
    SMAANeighborhoodBlendingVS(v_uv, v_offset);
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
