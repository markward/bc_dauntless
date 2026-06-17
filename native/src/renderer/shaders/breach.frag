#version 330 core

// Breach interior surface — flat-panel hull cross-section seen through breach
// holes. The dual-contour mesh winds INWARD with OUTWARD normals and is drawn
// DOUBLE-SIDED (cull off), so the fragment shader must not rely on winding:
//
//  * Triplanar projection of BC's Damage.tga along the three BODY axes, blended
//    by the normalized abs() of the body normal — so the texture reads as panel
//    detail regardless of facet orientation, with no UVs and no seams.
//  * Double-sided lighting: faceforward() flips the normal toward the viewer
//    before the N.L term so back-facing facets (seen through a hole from the
//    "wrong" side) still light, instead of going black.
//  * Muted look: low ambient + a soft diffuse term, modest brightness, so the
//    interior reads as shadowed structural guts rather than a bright splat.

in vec3 v_body_pos;
in vec3 v_body_normal;
in vec3 v_world_pos;

uniform sampler2D u_damage_tex;
uniform mat4  u_view;
uniform float u_tex_scale;   // body-units -> texture-period scale

out vec4 frag_color;

void main() {
    vec3 n = normalize(v_body_normal);

    // Triplanar blend weights from the body normal.
    vec3 w = abs(n);
    w = max(w, vec3(1e-4));
    w /= (w.x + w.y + w.z);

    vec3 uvw = v_body_pos * u_tex_scale;
    vec3 cx = texture(u_damage_tex, uvw.yz).rgb;   // project along +X
    vec3 cy = texture(u_damage_tex, uvw.zx).rgb;   // project along +Y
    vec3 cz = texture(u_damage_tex, uvw.xy).rgb;   // project along +Z
    vec3 tex = cx * w.x + cy * w.y + cz * w.z;

    // Neutral metallic base so the cross-section always reads as structural
    // hull interior; Damage.tga modulates it. With no texture bound (mod ship /
    // missing asset) the sample is ~0, leaving just the muted grey base —
    // graceful degradation, never a black hole to the stars.
    const vec3 kBase = vec3(0.32, 0.33, 0.36);
    tex = kBase + tex * 0.6;

    // Double-sided lighting. Camera world pos = inverse(view)[3].
    vec3 cam_pos = inverse(u_view)[3].xyz;
    vec3 view_dir = normalize(cam_pos - v_world_pos);
    vec3 nf = faceforward(n, -view_dir, n);  // flip toward the viewer

    // A fixed key light from the camera-ish direction keeps the cross-section
    // readable from any angle (no world up in space).
    float ndl = max(dot(nf, view_dir), 0.0);
    float light = 0.35 + 0.55 * ndl;   // ambient + soft diffuse

    // Mute: desaturate slightly and keep brightness moderate (no blown-out
    // panels), so the interior reads as structural guts, not a bright decal.
    float luma = dot(tex, vec3(0.299, 0.587, 0.114));
    vec3 muted = mix(vec3(luma), tex, 0.6);
    vec3 c = muted * light * 0.85;

    frag_color = vec4(c, 1.0);
}
