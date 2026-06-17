#pragma once
#include <cstddef>
#include <cstdint>
#include <vector>
#include <glm/glm.hpp>
#include <voxel/volume.h>
#include <scenegraph/breach_events.h>  // for kDebrisLife

namespace renderer {

/// Number of chunks spawned per breach event (eyeball-tunable constant).
inline constexpr int kChunkCount = 16;

/// Sample up to max_chunks solid voxel centers from fill that lie within
/// radius of center_body. Deterministic for fixed seed. Returns fewer than
/// max_chunks when insufficient solid voxels exist inside the sphere.
std::vector<glm::vec3> sample_chunk_origins(
    const voxel::VoxelVolume& fill,
    const glm::vec3& center_body,
    float radius,
    std::uint64_t seed,
    int max_chunks = kChunkCount);

/// Per-chunk world transform computed analytically from birth state + age.
struct ChunkTransform {
    glm::vec3 pos_body;  ///< current position in body frame
    glm::mat3 rot;       ///< current rotation (tumble)
    float     alpha;     ///< opacity: 1 at age=0, 0 at kDebrisLife
};

/// Compute the transform for chunk i at the given age.
/// origin     — voxel center in body frame (from sample_chunk_origins)
/// center     — breach center in body frame (radial outward direction source)
/// age        — now - birth_time (seconds)
/// seed       — event seed
/// i          — chunk index [0, kChunkCount)
ChunkTransform chunk_transform(
    const glm::vec3& origin,
    const glm::vec3& breach_center,
    float age,
    std::uint64_t seed,
    int i);

} // namespace renderer
