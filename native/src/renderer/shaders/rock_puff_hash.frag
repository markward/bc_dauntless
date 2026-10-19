#version 410 core
// Bakes rock_puff.frag's lattice hash table: texel (x, y) holds the hash of
// lattice point (x, y) - kHashOffset. MUST stay the expression rock_puff.frag
// evaluated per fragment before the table (2026-10-18): the GPU's sine of a
// large argument is what makes the pattern, so the table has to be computed
// on the GPU, by this exact expression, to keep the picture
// (RockPuffGLTest.TheBakedHashTableMatchesTheInlineHashExactly).
out float h;
const int kHashOffset = 20;   // rockfield::kPuffHashOffset
float hash2(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
void main() { h = hash2(vec2(ivec2(gl_FragCoord.xy) - kHashOffset)); }
