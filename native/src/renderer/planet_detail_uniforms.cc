// native/src/renderer/planet_detail_uniforms.cc
#include "renderer/planet_detail_uniforms.h"

#include "renderer/shader.h"

namespace renderer::planet_detail {

void apply(Shader& s, const SampleUniforms& u) {
    s.use();
    s.set_int("u_pd_enabled", u.enabled ? 1 : 0);
    if (!u.enabled) return;

    s.set_int("u_pd_levels", u.levels);
    s.set_float("u_pd_ts0", u.ts0);
    s.set_vec4_array("u_pd_valid", u.valid.data(), kMaxLevels);
    s.set_vec3("u_pd_A", u.A);
    s.set_vec3("u_pd_E", u.E);
    s.set_vec3("u_pd_N", u.N);
    s.set_float("u_pd_R", u.R);
    s.set_float("u_pd_scale_local", u.scale_local);
    s.set_int("u_pd_type", u.type);
    s.set_vec3("u_pd_ocean", u.ocean);
    s.set_int("u_pd_has_ocean", u.has_ocean ? 1 : 0);
    s.set_float("u_pd_ocean_tol", u.ocean_tol);
    s.set_float("u_pd_strength", u.strength);
    s.set_float("u_pd_albedo", u.albedo);
    s.set_float("u_pd_scale", u.scale);
    s.set_int("u_pd_debug", u.debug);
    // uint uniform: Shader has no unsigned setter, so set it directly (the
    // program is current from s.use() above).
    glUniform1ui(glGetUniformLocation(s.program(), "u_pd_seed"), u.seed);

    const TypeParams& p = u.params;
    s.set_float("u_pd_p_base_wavelength_gu", p.base_wavelength_gu);
    s.set_int("u_pd_p_max_octaves", p.max_octaves);
    s.set_float("u_pd_p_gain", p.gain);
    s.set_float("u_pd_p_ridged", p.ridged);
    s.set_float("u_pd_p_amplitude", p.amplitude);
    s.set_float("u_pd_p_bump", p.bump);
    s.set_float("u_pd_p_albedo", p.albedo);
    s.set_float("u_pd_p_roughness", p.roughness);
    s.set_float("u_pd_p_roughness_var", p.roughness_var);
    s.set_float("u_pd_p_crack_width", p.crack_width);
    s.set_float("u_pd_p_stretch", p.stretch);
    s.set_float("u_pd_p_warp", p.warp);
    s.set_float("u_pd_p_gas_rate_gups", p.gas_rate_gups);
    s.set_float("u_pd_p_gas_period_s", p.gas_period_s);
    s.set_float("u_pd_p_coast_k", p.coast_k);
    s.set_float("u_pd_p_coast_a", p.coast_a);

    glActiveTexture(GL_TEXTURE12);
    glBindTexture(GL_TEXTURE_2D, u.atlas);
    glActiveTexture(GL_TEXTURE0);
}

}  // namespace renderer::planet_detail
