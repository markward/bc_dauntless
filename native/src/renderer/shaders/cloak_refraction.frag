#version 330 core
// Cloak refraction + chromatic dispersion.
//
// For each hull fragment we sample a scratch copy of the scene colour at a
// screen-space offset along the hull normal — bending the background behind the
// ship as if light is passing through a refractive field.  The offset is split
// per RGB channel so white light disperses like a prism (the "split white
// light" brief): red bends most, blue least.  Strength ramps with the cloak
// transition (u_frac) and concentrates at grazing angles via a Fresnel term, so
// the silhouette reads as a refractive shell.
in vec3 v_world_pos;
in vec3 v_world_normal;
uniform sampler2D u_scene;     // scratch copy of the HDR scene colour
uniform vec3  u_camera_pos;
uniform vec2  u_viewport;      // framebuffer size in pixels
uniform float u_frac;          // 0..1 cloak progress (0 = visible, 1 = cloaked)
uniform float u_strength;      // max screen-space refraction offset (UV units)
uniform float u_dispersion;    // chromatic split fraction (prism strength)
uniform vec3  u_tint;          // faint cloak tint glowing along the rim
out vec4 frag;

void main() {
    vec3 N = normalize(v_world_normal);
    vec3 V = normalize(u_camera_pos - v_world_pos);
    float facing = clamp(abs(dot(N, V)), 0.0, 1.0);
    // Fresnel rim: refraction + dispersion peak at grazing angles.
    float fres = pow(1.0 - facing, 3.0);

    vec2 uv = gl_FragCoord.xy / u_viewport;
    // Refraction direction = hull normal projected into screen space. Guard the
    // head-on facets where N.xy vanishes so the normalize never yields NaN.
    vec2 ndir = N.xy;
    float nlen = length(ndir);
    ndir = (nlen > 1e-4) ? ndir / nlen : vec2(0.0);

    float amt = u_strength * u_frac * (0.30 + 0.70 * fres);
    // Per-channel offsets split white light into spectral fringes.
    vec2 oR = ndir * amt * (1.0 + u_dispersion);
    vec2 oG = ndir * amt;
    vec2 oB = ndir * amt * (1.0 - u_dispersion);

    float r = texture(u_scene, clamp(uv + oR, vec2(0.0), vec2(1.0))).r;
    float g = texture(u_scene, clamp(uv + oG, vec2(0.0), vec2(1.0))).g;
    float b = texture(u_scene, clamp(uv + oB, vec2(0.0), vec2(1.0))).b;
    vec3 col = vec3(r, g, b);
    // A faint cloak-field glow rides the refractive rim.
    col += u_tint * (fres * u_frac);

    // Replace the hull proportionally to cloak progress, weighted to the rim so
    // the body stays readable while the edges shimmer most.
    float a = clamp(u_frac * (0.25 + 0.75 * fres), 0.0, 1.0);
    frag = vec4(col, a);
}
