// Impulse-glow gain evaluated at glow-region upload (perf tier 1, spec
// 2026-11-08 §2.3). The closed form must equal the per-frame Python
// integration subsystem_glow.ShipGlowController used to run, within float
// rounding, and the pulse must be the same formula.
#include <gtest/gtest.h>

#include <cmath>
#include <random>

#include "renderer/glow_impulse.h"

namespace gi = renderer::glow_impulse;

namespace {

// Not M_PI: MSVC's <cmath> defines it only under _USE_MATH_DEFINES.
constexpr double kPi = 3.14159265358979323846;

// Today's per-frame rule (subsystem_glow.py before this change): snap is the
// caller's job; each frame eases by alpha = 1 - exp(-dt/tau), then settles to
// exactly 0 once the target is 0 and the value drops below the epsilon.
double integrate_step(double eased, double target, double dt) {
    const double alpha = 1.0 - std::exp(-dt / gi::kEaseTau);
    eased += (target - eased) * alpha;
    if (target == 0.0 && eased < gi::kSettleEps) eased = 0.0;
    return eased;
}

}  // namespace

TEST(GlowImpulse, EasedMatchesIntegratedForConstantTarget) {
    std::mt19937 rng(20261108u);
    std::uniform_real_distribution<double> dt_dist(1.0 / 240.0, 1.0 / 30.0);
    const struct { double start, target, t0; } cases[] = {
        {0.0, 1.0, 0.0}, {1.0, 0.0, 3.0}, {0.25, 0.75, 12.5},
        {0.9, 0.4, 100.0}, {0.6, 0.0, 41.0}, {0.0, 1.0 / 9.0, 7.0},
    };
    for (const auto& c : cases) {
        double integrated = c.start;
        double now = c.t0;
        double worst = 0.0;
        for (int i = 0; i < 600; ++i) {
            const double dt = dt_dist(rng);
            now += dt;
            integrated = integrate_step(integrated, c.target, dt);
            const float closed = gi::eased(static_cast<float>(c.start),
                                           static_cast<float>(c.target),
                                           static_cast<float>(c.t0),
                                           static_cast<float>(now));
            worst = std::max(worst, std::abs(closed - integrated));
        }
        EXPECT_LT(worst, 1e-5) << "start " << c.start << " target " << c.target;
    }
}

TEST(GlowImpulse, EasedBeforeStartIsStart) {
    EXPECT_FLOAT_EQ(gi::eased(0.3f, 1.0f, 10.0f, 9.0f), 0.3f);
    EXPECT_FLOAT_EQ(gi::eased(0.3f, 1.0f, 10.0f, 10.0f), 0.3f);
}

TEST(GlowImpulse, SettlesToZero) {
    // An exponential never reaches 0 on its own; below kSettleEps with a zero
    // target it snaps to exactly 0, so the gain sits on kGainIdle.
    EXPECT_GT(gi::eased(1.0f, 0.0f, 0.0f, 1.0f), 0.0f);
    const float tail = static_cast<float>(-gi::kEaseTau * std::log(gi::kSettleEps)) + 0.01f;
    EXPECT_EQ(gi::eased(1.0f, 0.0f, 0.0f, tail), 0.0f);
    EXPECT_EQ(gi::gain(1.0f, 0.0f, 0.0f, tail + 0.37f, true), gi::kGainIdle);
    // A non-zero target never snaps.
    EXPECT_GT(gi::eased(0.0f, 1e-4f, 0.0f, 100.0f), 0.0f);
}

TEST(GlowImpulse, UnpoweredIsOne) {
    for (float now : {0.0f, 0.6f, 1.3f, 7.7f, 250.0f})
        for (float target : {0.0f, 0.5f, 1.0f})
            EXPECT_EQ(gi::gain(0.2f, target, 0.0f, now, false), 1.0f);
}

TEST(GlowImpulse, PulseMatchesFormula) {
    for (float frac : {0.0f, 0.25f, 0.5f, 1.0f}) {
        for (float now : {0.0f, 0.4f, 0.625f, 1.3f, 33.3f}) {
            const double base = gi::kGainIdle + (gi::kGainMax - gi::kGainIdle) * frac;
            const double want = base * (1.0 + gi::kPulseAmp * frac *
                                std::sin(2.0 * kPi * gi::kPulseFreqHz * now));
            // Held target (start == target): the ease is the identity.
            EXPECT_NEAR(gi::gain(frac, frac, 0.0f, now, true), want, 1e-6)
                << "frac " << frac << " now " << now;
            EXPECT_NEAR(gi::impulse_gain(frac, now), want, 1e-6);
        }
    }
}

TEST(GlowImpulse, ConstantsMirrorSubsystemGlow) {
    EXPECT_EQ(gi::kGainIdle, 1.0);
    EXPECT_EQ(gi::kGainMax, 3.0);
    EXPECT_EQ(gi::kPulseFreqHz, 0.4);
    EXPECT_EQ(gi::kPulseAmp, 0.15);
    EXPECT_EQ(gi::kEaseTau, 0.35);
    EXPECT_EQ(gi::kSettleEps, 1e-3);
}
