#version 410 core
in vec2 v_pix;
in vec2 v_uv;
uniform int u_mode;              // 0 = affiliation dot, 1 = text
uniform vec3 u_color;            // already capped below the bloom threshold
uniform float u_alpha;           // 1, or the shadow's alpha
uniform vec3 u_dot;              // dot centre x, y and radius, in pixels
uniform sampler2D u_atlas;       // single-channel glyph coverage
out vec4 FragColor;

void main() {
    float cov;
    if (u_mode == 0) {
        float d = length(v_pix - u_dot.xy) - u_dot.z;   // circle SDF
        cov = clamp(0.5 - d, 0.0, 1.0);
    } else {
        cov = texture(u_atlas, v_uv).r;
    }
    FragColor = vec4(u_color, u_alpha * cov);
}
