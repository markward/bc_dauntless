#version 410 core
in vec2 v_uv;
out vec4 frag;

uniform vec3 u_color;   // rgb * intensity * level * blink (premultiplied)

// One soft disc, no separate halo: with HDR on the core (above the bloom
// threshold) blooms like every other bright source; with HDR off the soft
// edge still reads as a small light (running-lights spec §4.4).
//
// A broad gaussian, ~0.05 at the quad edge: when the min_px floor wins the
// quad is a couple of pixels across, and a profile that is ~0 by r ~0.9
// leaves a sprite centred on a pixel corner black (its nearest pixel centres
// sit at r ~0.94 at a 1.5 px floor), so moving lights twinkled.
void main() {
    float r = length(v_uv);
    if (r >= 1.0) { frag = vec4(0.0); return; }
    frag = vec4(u_color * exp(-3.0 * r * r), 0.0);
}
