#version 410 core
// Upsample the half-res god-ray image to full res, blurred, for the additive
// composite into the HDR target (blend GL_ONE, GL_ONE). Four bilinear taps at
// +-kBlur half-res texels: a soft tent over ~3x3 half-res texels that hides
// the 2x2 blocks and the march's per-pixel jitter noise for 4 fetches.
in vec2 v_uv;
out vec4 frag;

uniform sampler2D u_rays;      // half-res scatter (premultiplied, additive)
uniform vec2 u_texel;          // 1 / half-res size

const float kBlur = 0.75;      // tap offset, half-res texels

void main() {
    vec2 o = u_texel * kBlur;
    vec3 s = texture(u_rays, v_uv + vec2(-o.x, -o.y)).rgb
           + texture(u_rays, v_uv + vec2( o.x, -o.y)).rgb
           + texture(u_rays, v_uv + vec2(-o.x,  o.y)).rgb
           + texture(u_rays, v_uv + vec2( o.x,  o.y)).rgb;
    frag = vec4(s * 0.25, 1.0);
}
