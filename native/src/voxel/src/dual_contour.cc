#include <voxel/dual_contour.h>
#include <glm/glm.hpp>
#include <cmath>

namespace voxel {

glm::vec3 solve_qef(const std::vector<Plane>& planes, glm::vec3 fallback) {
    if (planes.empty()) {
        return fallback;
    }

    // Build the normal-equation system A = Σ n_i n_iᵀ, b = Σ d_i n_i.
    // glm::mat3 is column-major: mat3[col][row].
    // For a symmetric outer-product matrix n·nᵀ, column-major and row-major
    // representations are identical, so we can build it directly.
    glm::mat3 A(0.0f);
    glm::vec3 b(0.0f);

    for (const auto& p : planes) {
        const glm::vec3& n = p.n;
        // Outer product n·nᵀ accumulated into A (column-major: A[col][row])
        A[0][0] += n.x * n.x;  A[1][0] += n.y * n.x;  A[2][0] += n.z * n.x;
        A[0][1] += n.x * n.y;  A[1][1] += n.y * n.y;  A[2][1] += n.z * n.y;
        A[0][2] += n.x * n.z;  A[1][2] += n.y * n.z;  A[2][2] += n.z * n.z;
        b += p.d * n;
    }

    // Tikhonov regularization: (A + λI) v = b + λ·fallback
    // λ = 1e-4: small enough that a well-constrained corner (A = I, b = exact)
    // has error O(λ·d) < 1e-3 for typical cell coordinates, yet large enough
    // to guarantee invertibility and pull under-constrained axes toward the
    // seed (e.g. the two free axes in the single-plane case where only one
    // diagonal element of A is non-zero before regularization).
    constexpr float kLambda = 1e-4f;
    A[0][0] += kLambda;
    A[1][1] += kLambda;
    A[2][2] += kLambda;
    b += kLambda * fallback;

    const float det = glm::determinant(A);
    if (std::abs(det) < 1e-10f) {
        // Should not happen with λ > 0 and a well-formed normal matrix, but
        // defend against degenerate floating-point edge cases.
        return fallback;
    }

    return glm::inverse(A) * b;
}

}  // namespace voxel
