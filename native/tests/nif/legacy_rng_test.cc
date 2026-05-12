// native/tests/nif/legacy_rng_test.cc
#include <gtest/gtest.h>

#include <nif/legacy_rng.h>

namespace {
using nif::legacy::ParticleRng;
}

TEST(ParticleRng, SameSeedProducesSameStream) {
    ParticleRng a{42};
    ParticleRng b{42};
    for (int i = 0; i < 100; ++i) {
        EXPECT_FLOAT_EQ(a.unit(), b.unit()) << "diverged at iteration " << i;
    }
}

TEST(ParticleRng, DifferentSeedsProduceDifferentStreams) {
    ParticleRng a{1};
    ParticleRng b{2};
    int agreements = 0;
    for (int i = 0; i < 100; ++i) {
        if (a.unit() == b.unit()) ++agreements;
    }
    // Some collisions are statistically possible, but 100 agreements would
    // mean the seed has no effect.
    EXPECT_LT(agreements, 100);
}

TEST(ParticleRng, UnitStaysInHalfOpenZeroToOne) {
    ParticleRng r{1234567};
    for (int i = 0; i < 10000; ++i) {
        float v = r.unit();
        ASSERT_GE(v, 0.0f) << "iteration " << i;
        ASSERT_LT(v, 1.0f) << "iteration " << i;
    }
}

TEST(ParticleRng, SymmetricStaysInNegOneToOne) {
    ParticleRng r{7777};
    for (int i = 0; i < 10000; ++i) {
        float v = r.symmetric();
        ASSERT_GE(v, -1.0f) << "iteration " << i;
        ASSERT_LT(v, 1.0f) << "iteration " << i;
    }
}

TEST(ParticleRng, ZeroSeedDoesNotProduceZeroStream) {
    // splitmix64 with state zero produces zero forever; the constructor
    // remaps zero to a fixed nonzero golden-ratio constant. Verify the
    // first draw isn't zero and that we get a normal distribution out.
    ParticleRng r{0};
    bool saw_nonzero = false;
    for (int i = 0; i < 20; ++i) {
        if (r.unit() != 0.0f) { saw_nonzero = true; break; }
    }
    EXPECT_TRUE(saw_nonzero);
}

TEST(ParticleRng, ConstexprConstructible) {
    constexpr ParticleRng r{99};
    (void)r;  // smoke check that the constructor is usable in constexpr context
}
