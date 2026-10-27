// native/src/renderer/include/renderer/nebula_noise.h
#pragma once

#include <glm/glm.hpp>

#include <vector>

namespace renderer::nebula_noise {

/// The system nebula's haze lanes read their value noise from a baked hash
/// lattice instead of hashing 8 corners per octave (B3: the fbm noise was
/// ~90% of the nebula's cost at 4K, docs/reference/engine/perf-register.md SIG-083).
/// The lattice is kLatticeN^3 cells of hash13(cell); system_nebula.frag reads
/// it with hardware trilinear filtering at i + smoothstep(f), which is exactly
/// the procedural vnoise inside the first period [0, kLatticeN - 1) and
/// repeats with period kLatticeN past it. Must match the shader's kLatticeN.
///
/// Only the haze lanes use it. The clump noise stays procedural: its gameplay
/// twin (engine/appc/nebula_density.py) hashes the unbounded lattice.
constexpr int kLatticeN = 64;

/// backdrop.frag / system_nebula.frag hash13, in float.
float hash13(glm::vec3 p);

/// The procedural value noise the lattice replaces (8 hashes, smoothstep).
float vnoise(glm::vec3 p);

/// kLatticeN^3 floats, x fastest: hash13 of each integer cell.
std::vector<float> bake_hash_lattice(int n);

/// CPU twin of the shader's vnoise_lattice: the cell wrapped into [0, n), its
/// corners read from `lattice` (the far corners wrap to 0), blended with the
/// smoothstep weights -- what trilinear filtering at i + smoothstep(f) gives.
float vnoise_lattice(const std::vector<float>& lattice, int n, glm::vec3 p);

/// CPU twin of the shader's fbm_lattice: 5 octaves, lacunarity 2.02, gain 0.5.
float fbm_lattice(const std::vector<float>& lattice, int n, glm::vec3 p);

}  // namespace renderer::nebula_noise
