// native/src/nif/include/nif/legacy_constants.h
#pragma once

// Behavioral constants used by the legacy NetImmerse/Gamebryo runtime to
// evaluate BC-era animation, particles, and flip controllers. The on-disk
// format does not encode these values — they are hardcoded in the stock
// SDK and must be matched by any reimplementation that wants visual /
// behavioral parity with original Bridge Commander effects.
//
// Sources: docs/project/cleanroom_netimmerse_answers_round2.md (NI2-Q34,
// NI2-Q59, NI2-Q27). Cross-reference docs/project/nif_conventions.md "Magic
// constants"
// table.
//
// These constants currently have no consumer in the codebase — they live
// here as a single documented source of truth so they're impossible to
// forget when the animation and particle subsystems are implemented in
// Phase 2. Move them to a more specific module when one of those exists.

namespace nif::legacy {

// NiGravity strength multiplier. Every gravity application (planar and
// spherical) is scaled by this factor on top of the user-supplied
// strength, an undocumented units-conversion fudge baked into the SDK.
// If we deviate from this value, BC particle effects driven by NiGravity
// will move at the wrong rate.
inline constexpr float kGravityStrengthMultiplier = 1.6f;

// NiFlipController index fudge. The interpolated float index has this
// added to it before integer truncation, biasing the round-down so that
// boundary float values pick the visually-correct frame.
inline constexpr float kFlipControllerIndexFudge = 0.01f;

// NiFlipController shader-map offset. Map indices < this value name
// standard texturing-property slots; indices >= this offset select a
// shader-map slot at (index - kFlipControllerShaderMapOffset).
inline constexpr int kFlipControllerShaderMapOffset = 1024;

// NiParticleSystemController initial run-up sample interval. When a
// particle system is first ticked, the runtime pre-simulates from
// emit-start up to current time at this fixed step so the system is not
// visibly empty at first render. 30 fps in the SDK.
inline constexpr float kParticleRunUpStepSeconds = 1.0f / 30.0f;

// NiParticleSystemController static-bound sampling interval. Used when
// computing a precomputed model bound for a particle system whose
// emit-start to emit-stop range is finite.
inline constexpr float kParticleStaticBoundSampleSeconds = 0.10f;

// NiParticleSystemController static-bound oversizing factor. The
// computed static bound is inflated by this multiplier "for safety"
// before being cached.
inline constexpr float kParticleStaticBoundOversize = 1.05f;

// Shared epsilon for particle size-clamping and time-comparison in
// NiParticleSystemController and NiParticleGrowFade. Prevents
// degenerate zero-size particles.
inline constexpr float kParticleEpsilon = 0.0001f;

}  // namespace nif::legacy
