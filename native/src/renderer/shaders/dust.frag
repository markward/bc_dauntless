#version 330 core

in vec2  v_uv;
in float v_brightness;
in vec3  v_local;
in float v_streak;

uniform sampler2D u_dust_tex;
uniform float     u_radius;
uniform float u_sun_tint;   // [0,1] orange-mix factor near suns

out vec4 out_color;

void main() {
    float r = length(v_local);
    if (r > u_radius) discard;
    vec4 tex = texture(u_dust_tex, v_uv);
    float fade = 1.0 - smoothstep(u_radius * 0.85, u_radius, r);
    // Warm the dust toward orange (#FF8030) as the camera nears a sun.
    vec3 tint = mix(vec3(1.0), vec3(1.0, 0.502, 0.188), u_sun_tint);
    vec3 base = tex.rgb * v_brightness * tint;
    if (v_streak > 0.0) {
        // Procedural prism: sweep hue along the streak's leading edge.
        float h = fract(v_uv.y * 0.5 + v_streak);    // hue 0..1 along streak
        vec3 prism = clamp(abs(fract(h + vec3(0.0, 0.3333, 0.6667)) * 6.0 - 3.0) - 1.0, 0.0, 1.0);
        base = mix(base, base + prism, v_streak);     // tint tips, fade in with streak
        base *= (1.0 + 1.5 * v_streak);               // brighten streaks
    }
    out_color = vec4(base, tex.a * fade);
}
