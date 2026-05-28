#version 330 core

in vec2 v_uv;

uniform sampler2D u_texture;
uniform float     u_now_seconds;

out vec4 frag_color;

// Rotate the UV around (0.5, 0.5) by u_now_seconds * 0.0873 rad/s (~5°/s)
// for the slow solar-flare animation.
void main() {
    float angle = u_now_seconds * 0.0873;
    float c = cos(angle);
    float s = sin(angle);
    vec2 centered = v_uv - vec2(0.5);
    vec2 rotated  = vec2(c * centered.x - s * centered.y,
                         s * centered.x + c * centered.y);
    vec2 uv = rotated + vec2(0.5);
    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) {
        // Outside the rotated source rect — emit nothing.
        frag_color = vec4(0.0);
        return;
    }
    vec4 tex = texture(u_texture, uv);
    // Additive blend is set on the GL state; output RGB * alpha so the
    // texture's alpha channel governs intensity.
    frag_color = vec4(tex.rgb * tex.a, tex.a);
}
