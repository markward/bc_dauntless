#version 410 core
in vec2 v_uv;
out vec4 frag;

uniform vec3 u_color;   // rgb * intensity * level * blink (premultiplied)

// One soft disc, no separate halo: with HDR on the core (above the bloom
// threshold) blooms like every other bright source; with HDR off the soft
// edge still reads as a small light (running-lights spec §4.4).
void main() {
    float r = length(v_uv);
    if (r >= 1.0) { frag = vec4(0.0); return; }
    float f = 1.0 - smoothstep(0.0, 1.0, r);
    frag = vec4(u_color * f * f, 0.0);
}
