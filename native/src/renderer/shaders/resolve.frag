#version 330 core
in vec2 v_uv;
out vec4 frag_color;
uniform sampler2D u_hdr;
uniform int u_hdr_enabled;
void main() {
    vec3 c = texture(u_hdr, v_uv).rgb;
    if (u_hdr_enabled != 0) {
        // HDR resolve: tonemap + bloom + grade are added in later tasks.
        // Until then this equals passthrough so the toggle is wired
        // end-to-end without changing the image.
        c = clamp(c, 0.0, 1.0);
    } else {
        c = clamp(c, 0.0, 1.0);   // neutral passthrough (stock look)
    }
    frag_color = vec4(c, 1.0);
}
