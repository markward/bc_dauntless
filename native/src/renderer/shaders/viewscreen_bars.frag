#version 410 core
in vec2 v_pix;
in vec2 v_uv;
uniform int u_mode;              // 0 = band, 1 = text
uniform vec3 u_color;            // already capped below the bloom threshold
uniform vec4 u_rect;             // band x0, y0, x1, y1 in pixels
uniform float u_radius_top;      // corner radius for the band's top corners
uniform float u_radius_bottom;   // ... and its bottom corners
uniform sampler2D u_atlas;       // single-channel glyph coverage
out vec4 FragColor;

// Signed distance to a box (centre-relative p, half-size b) whose corners on
// one side of the centre line are rounded by r.
float rounded_box(vec2 p, vec2 b, float r) {
    vec2 q = abs(p) - b + r;
    return min(max(q.x, q.y), 0.0) + length(max(q, 0.0)) - r;
}

void main() {
    if (u_mode == 0) {
        vec2 c = 0.5 * (u_rect.xy + u_rect.zw);
        vec2 b = 0.5 * (u_rect.zw - u_rect.xy);
        vec2 p = v_pix - c;
        float r = p.y > 0.0 ? u_radius_top : u_radius_bottom;
        float d = rounded_box(p, b, r);
        FragColor = vec4(u_color, clamp(0.5 - d, 0.0, 1.0));
    } else {
        FragColor = vec4(u_color, texture(u_atlas, v_uv).r);
    }
}
