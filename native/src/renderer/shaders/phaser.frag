#version 330 core
in  vec2 v_uv;
out vec4 frag_color;

uniform sampler2D u_texture;
uniform vec4      u_color;

void main() {
    // Sample the beam texture along U (length) × V (width).
    vec4 t = texture(u_texture, v_uv);
    // Fade only the target-side endpoint — beam start is anchored to
    // the ship's hardpoint so it must read as solid all the way to the
    // emitter.  (Previous build also faded the emitter side, which made
    // the first ~5% of every beam translucent and lost the connection
    // to the hull.)
    float endpoint_fade = 1.0 - smoothstep(0.95, 1.0, v_uv.x);
    frag_color = t * u_color;
    frag_color.a *= endpoint_fade;
}
