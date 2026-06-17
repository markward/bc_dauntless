#version 330 core

// Classic BC "chunky colored guts": each interior voxel cube gets a stable
// pseudo-random color from its seed, giving the multicolor speckle seen
// through hull breaches in the original game. Fully opaque; depth-test +
// depth-write are configured by the pass so cubes behind intact hull are
// occluded and cubes behind holes show through.

flat in float v_seed;
out vec4 frag_color;

void main() {
    vec3 c = fract(sin(v_seed * vec3(12.9898, 78.233, 37.719)) * 43758.5453);
    // Keep the speckle reasonably saturated/bright (no near-black cubes).
    c = 0.25 + 0.75 * c;
    frag_color = vec4(c, 1.0);
}
