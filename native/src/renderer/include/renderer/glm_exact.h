// native/src/renderer/include/renderer/glm_exact.h
// Bit-exact scalar replicas of the few glm operations the rock-field hot
// loops (rock_near.cc, far::make_impostor) run per rock / tile
// / sprite. This tree builds Debug (-O0), where every glm operator is an
// out-of-line call chain; these do the same IEEE operations in the same
// order as the glm source they replace, so their results are identical to
// the bit (pinned by native/tests/renderer/glm_exact_test.cc):
//   * a product glm rounds before summing (a vec*vec or vec*scalar inside
//     its own function) is a separate statement here, so the compiler cannot
//     contract it into a fused multiply-add;
//   * an expression glm writes as ONE expression (mat3 * vec3, the rotate()
//     terms) is written as the same one expression with the same operand
//     order, so any contraction the compiler applies is applied to both.
#pragma once
#include <cmath>
#include <glm/glm.hpp>
#include <glm/gtc/type_ptr.hpp>

namespace renderer::glm_exact {

// glm::dot(vec3, vec3): tmp = a * b; tmp.x + tmp.y + tmp.z.
template <class T>
inline T dot3(T ax, T ay, T az, T bx, T by, T bz) {
    const T x = ax * bx;
    const T y = ay * by;
    const T z = az * bz;
    return x + y + z;
}

// glm::mat3 * glm::vec3 (column-major m[col][row]).
inline glm::vec3 mul(const glm::mat3& m, const glm::vec3& v) {
    const float* p = glm::value_ptr(m);
    return glm::vec3(p[0] * v.x + p[3] * v.y + p[6] * v.z,
                     p[1] * v.x + p[4] * v.y + p[7] * v.z,
                     p[2] * v.x + p[5] * v.y + p[8] * v.z);
}

// glm::transpose(m) * v.
inline glm::vec3 mul_transposed(const glm::mat3& m, const glm::vec3& v) {
    const float* p = glm::value_ptr(m);
    return glm::vec3(p[0] * v.x + p[1] * v.y + p[2] * v.z,
                     p[3] * v.x + p[4] * v.y + p[5] * v.z,
                     p[6] * v.x + p[7] * v.y + p[8] * v.z);
}

// glm::mat3(glm::rotate(glm::mat4(1.0f), angle, v)).
inline glm::mat3 rotation(float angle, const glm::vec3& v) {
    const float a = angle;
    const float c = std::cos(a);
    const float s = std::sin(a);
    // normalize(v) = v * inversesqrt(dot(v, v)); inversesqrt(x) = 1 / sqrt(x)
    const float inv = 1.0f / std::sqrt(dot3(v.x, v.y, v.z, v.x, v.y, v.z));
    const float ax = v.x * inv;
    const float ay = v.y * inv;
    const float az = v.z * inv;
    const float omc = 1.0f - c;
    const float tx = omc * ax;
    const float ty = omc * ay;
    const float tz = omc * az;
    // Rotate[col][row], each written as glm writes it.
    const float r00 = c + tx * ax;
    const float r01 = tx * ay + s * az;
    const float r02 = tx * az - s * ay;
    const float r10 = ty * ax - s * az;
    const float r11 = c + ty * ay;
    const float r12 = ty * az + s * ax;
    const float r20 = tz * ax + s * ay;
    const float r21 = tz * ay - s * ax;
    const float r22 = c + tz * az;
    // Result[col] = I[0] * Rotate[col][0] + I[1] * Rotate[col][1] + I[2] * Rotate[col][2]:
    // vec4 * scalar products, then (A + B) + C.
    auto col = [](float k0, float k1, float k2) {
        float out[3];
        for (int j = 0; j < 3; ++j) {
            const float p0 = (j == 0 ? 1.0f : 0.0f) * k0;
            const float p1 = (j == 1 ? 1.0f : 0.0f) * k1;
            const float p2 = (j == 2 ? 1.0f : 0.0f) * k2;
            const float s01 = p0 + p1;
            out[j] = s01 + p2;
        }
        return glm::vec3(out[0], out[1], out[2]);
    };
    return glm::mat3(col(r00, r01, r02), col(r10, r11, r12), col(r20, r21, r22));
}

}  // namespace renderer::glm_exact
