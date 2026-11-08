// native/src/renderer/include/renderer/glow_impulse.h
#pragma once

#include <cmath>

// Impulse-engine glow gain, evaluated at glow-region upload (frame.cc) from
// the game clock the glow flicker already uses (u_decal_time), so Python
// pushes (start, target, t0, powered) only when one of them changes instead
// of a fresh gain every frame (perf tier 1, spec 2026-11-08 §2.3).
//
// TWIN of engine/appc/subsystem_glow.py: the constants below MUST equal
// GAIN_IDLE, GAIN_MAX, PULSE_FREQ_HZ, PULSE_AMP, IMPULSE_EASE_TAU and
// IMPULSE_SETTLE_EPS, and eased()/impulse_gain() its eased_frac() and
// impulse_gain(). Pinned by native/tests/renderer/glow_impulse_test.cc and
// tests/unit/test_glow_impulse_twin.py. Maths is double, like Python's.

namespace renderer::glow_impulse {

inline constexpr double kGainIdle = 1.0;      // powered but stopped
inline constexpr double kGainMax = 3.0;       // full throttle
inline constexpr double kPulseFreqHz = 0.4;   // slow throb rate
inline constexpr double kPulseAmp = 0.15;     // peak pulse fraction at full throttle
inline constexpr double kEaseTau = 0.35;      // throttle ease time constant (s)
inline constexpr double kSettleEps = 1e-3;    // snap to 0 below this when target is 0

/// Commanded throttle eased from `start` (at game time `t0`) toward `target`:
/// target + (start - target) * exp(-(now - t0) / tau), snapped to exactly 0
/// once target is 0 and the value is below kSettleEps. For a target held
/// since t0 this equals the old per-frame integration (the product of
/// exp(-dt_i/tau) is exp(-sum dt_i/tau)). At or before t0 it is `start`
/// (still subject to the snap), so the push instant has no rounding step.
inline float eased(float start, float target, float t0, float now) {
    const double e =
        now <= t0 ? static_cast<double>(start)
                  : static_cast<double>(target) +
                        (static_cast<double>(start) - static_cast<double>(target)) *
                            std::exp(-(static_cast<double>(now) - static_cast<double>(t0)) /
                                     kEaseTau);
    if (target == 0.0f && e < kSettleEps) return 0.0f;
    return static_cast<float>(e);
}

/// Powered gain for an (already eased) throttle fraction: base ramps
/// kGainIdle..kGainMax with frac, times a slow pulse whose amplitude grows
/// with frac (dead steady at rest).
inline float impulse_gain(float frac, float now) {
    const double f = frac < 0.0f ? 0.0 : (frac > 1.0f ? 1.0 : static_cast<double>(frac));
    const double base = kGainIdle + (kGainMax - kGainIdle) * f;
    constexpr double kTwoPi = 6.283185307179586;
    const double pulse =
        1.0 + kPulseAmp * f * std::sin(kTwoPi * kPulseFreqHz * static_cast<double>(now));
    return static_cast<float>(base * pulse);
}

/// The gain uploaded in u_glow_region_d.x for an impulse region. Unpowered
/// (unhealthy pod) is exactly 1.0: the dim state machine owns it then.
inline float gain(float start, float target, float t0, float now, bool powered) {
    if (!powered) return 1.0f;
    return impulse_gain(eased(start, target, t0, now), now);
}

}  // namespace renderer::glow_impulse
