// native/src/nif/include/nif/legacy_rng.h
#pragma once

#include <cstdint>

// Deterministic random source for legacy-particle simulation.
//
// Background (round 2 NI2-Q49): the stock NetImmerse/Gamebryo old-particle
// system pulls uniform / symmetric randoms from two global helpers
// (NiUnitRandom, NiSymmetricRandom) backed by an unseeded global RNG. That
// means save/load with active particles in-flight is non-reproducible
// across sessions: the future random rolls a system makes depend on what
// every other random consumer in the process drew between save and load.
//
// We diverge on purpose: each NiParticleSystemController-equivalent owns
// its own ParticleRng instance, seeded at construction. The seed source is
// the runtime's choice (block index, scene hash, world clock, etc.), but
// the contract is that two systems with identical seeds produce identical
// streams. This makes save/load deterministic for free.
//
// Implementation: splitmix64. ~16 bytes of state, fast, well-distributed,
// satisfies all the statistical properties old-particle code needs (which
// is to say: not much — just enough to scatter spawn directions and
// lifespans). Swap to a heavier generator if a quality issue surfaces.

namespace nif::legacy {

class ParticleRng {
public:
    /// Seed of zero is remapped to a non-zero constant so the splitmix64
    /// stream is well-defined; callers can pass anything else verbatim.
    explicit constexpr ParticleRng(std::uint64_t seed) noexcept
        : state_(seed != 0 ? seed : 0x9E3779B97F4A7C15ULL) {}

    /// Returns a uniform float in [0, 1). Mirrors NiUnitRandom semantics.
    float unit() noexcept {
        // Top 24 bits of a 64-bit splitmix output → mantissa of [1, 2),
        // then subtract 1 to land in [0, 1). Guaranteed strictly < 1.
        constexpr float kInv24 = 1.0f / static_cast<float>(1u << 24);
        return static_cast<float>(advance() >> 40) * kInv24;
    }

    /// Returns a uniform float in [-1, 1). Mirrors NiSymmetricRandom.
    float symmetric() noexcept {
        return unit() * 2.0f - 1.0f;
    }

private:
    std::uint64_t advance() noexcept {
        // splitmix64 (Steele/Lea/Flood) — state-incrementing variant.
        state_ += 0x9E3779B97F4A7C15ULL;
        std::uint64_t z = state_;
        z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
        z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
        return z ^ (z >> 31);
    }

    std::uint64_t state_;
};

}  // namespace nif::legacy
