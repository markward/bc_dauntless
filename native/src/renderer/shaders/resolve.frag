#version 330 core
in vec2 v_uv;
out vec4 frag_color;
uniform sampler2D u_hdr;
uniform int u_hdr_enabled;   // 0 = neutral clamp passthrough (this task)
void main() {
    vec3 c = texture(u_hdr, v_uv).rgb;
    frag_color = vec4(clamp(c, 0.0, 1.0), 1.0);  // HDR-on path added in later tasks
}
