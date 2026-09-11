// native/src/voxel/include/voxel/field_brush.h
#pragma once

#include <glm/glm.hpp>

#include <voxel/distance_field.h>

namespace voxel {

/// Depth of a carve along the hit normal, as a fraction of its lateral radius.
/// MUST equal opaque.frag's kDepthFactor: the breach scoop still derives from
/// the sphere list, so hole and scoop only stay aligned while both use this
/// same oblate. Change one, change both, and live-test the pair.
inline constexpr float kCarveDepthFactor = 0.45f;

/// Rim-noise amplitude, as a fraction of the carve radius. MUST equal
/// opaque.frag's kShapeAmp. The shader perturbs the hole's lateral radius by
/// +/- this fraction, so the brush's lateral half-extent must be
/// radius * (1 + kCarveRimAmp) to cover the OUTWARD half of that perturbation
/// -- carving only `radius` left an un-backed band around every hole.
inline constexpr float kCarveRimAmp = 0.25f;

/// Minimum carve half-depth, in CELLS. A carve's true half-depth is
/// kCarveDepthFactor * radius, which is under one cell for every radius below
/// about 11 model units -- i.e. for every ordinary combat hit. A feature
/// thinner than a cell does not survive trilinear reconstruction, so the
/// field read "no damage" inside holes the hull shader had already cut and
/// breach.frag's march bailed at its entry point: see-through hull.
/// Flooring the half-depth here is what makes a small carve exist at all.
/// MUST equal opaque.frag's kFieldDepthFloor.
inline constexpr float kCarveDepthFloorCells = 1.25f;

/// Constant offset added to the brush before the CSG max(), in CELLS. The
/// floor above makes a carve representable; this makes it representable with
/// MARGIN. Reconstruction is only tangent to the true surface at the
/// boundary, so without it the reconstructed hole edge falls slightly inside
/// the analytic one and the rim goes un-backed.
///
/// Measured: with the floor alone, worst-case coverage of the analytic hole
/// is 73%; with both, it is 100% across cell 3.0-7.5 and radius 3-30.
/// The cost is a damaged region 1.7x the nominal rim on average (3.3x for a
/// tiny carve on a coarse lattice) -- suppressed wherever a tracked carve
/// governs, and visible only as generous holes beyond the 24-carve ring.
/// MUST equal opaque.frag's kFieldSdfOffset.
inline constexpr float kCarveFieldOffsetCells = 1.25f;

/// Subtract an oblate breach from the hull: full lateral radius `radius`,
/// kCarveDepthFactor * radius along `normal_body`, centred on the hull surface.
///
/// CSG subtraction on a signed distance field is `d = max(d, -d_brush)`, which
/// is monotonic: a carve can only ever remove material, never restore it. That
/// is what lets overlapping carves merge into one cavity instead of evicting
/// each other, which the fixed 24-slot sphere array could not do.
///
/// Each call quantizes `d_new` to int8 immediately, so overlapping carves
/// accumulate through quantised values, not full-precision floats. This is a
/// design property: do not "optimise" by keeping a float accumulator, as that
/// would change every result.
///
/// All arguments are body frame, MODEL UNITS. A degenerate normal falls back to
/// +Z rather than producing NaN. Empty field, non-positive radius, non-finite
/// radius, non-finite centre_body or normal_body components, or a carve
/// entirely off the grid are all no-ops.
void field_carve_oblate(DistanceField& f,
                        const glm::vec3& center_body,
                        const glm::vec3& normal_body,
                        float radius);

/// Subtract a CAPSULE -- every point within `radius` of the segment
/// p0_body..p1_body -- from the field. The death cascade's swept cut: a line
/// of material removed, so a dying hull can part at the neck or across the
/// saucer, which no 0.3 GU sphere can do.
///
/// Same conservative treatment as the oblate (kCarveDepthFloorCells floors
/// the radius, kCarveFieldOffsetCells dilates it), same CSG max(), same
/// quantisation. The capsule's distance is exactly 1-Lipschitz, so the
/// offset dilates it uniformly. It NEVER enters the sphere list: beyond
/// tracked carves the field is the hole authority (plan 2c), so a capsule is
/// cut, rimmed and given an interior entirely by machinery that exists.
///
/// Body frame, MODEL UNITS. Empty field, non-positive/non-finite radius,
/// non-finite endpoints, or a capsule wholly off-grid are no-ops.
void field_carve_capsule(DistanceField& f,
                         const glm::vec3& p0_body,
                         const glm::vec3& p1_body,
                         float radius);

}  // namespace voxel
