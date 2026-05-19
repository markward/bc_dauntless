#include <gtest/gtest.h>
#include <audio/null_backend.h>
#include <cstdint>
#include <vector>

namespace {

TEST(NullBackend, RecordsLifecycleAndPlayback) {
    dauntless::audio::NullBackend b;
    b.init();

    dauntless::audio::PcmDesc desc{1, 16, 22050};
    std::vector<uint8_t> pcm = {0, 0, 1, 0};
    auto buf = b.create_buffer(desc, pcm.data(), pcm.size());
    ASSERT_NE(buf, 0u);

    auto s = b.play(buf, /*looping*/ true, /*gain*/ 1.0f,
                    dauntless::audio::Category::SFX,
                    /*positional*/ true, 0.0f, 0.0f, 0.0f);
    ASSERT_NE(s, 0u);
    b.set_position(s, 10.0f, 0.0f, 0.0f);
    b.stop(s);

    const auto& log = b.command_log();
    ASSERT_EQ(log.size(), 5u);
    EXPECT_EQ(log[0].op, "init");

    EXPECT_EQ(log[1].op, "create_buffer");
    EXPECT_EQ(log[1].u[0], 1u);                                   // channels
    EXPECT_EQ(log[1].u[1], 16u);                                  // bits_per_sample
    EXPECT_EQ(log[1].u[2], 22050u);                               // sample_rate
    EXPECT_EQ(log[1].u[3], pcm.size());                           // byte length

    EXPECT_EQ(log[2].op, "play");
    EXPECT_EQ(log[2].u[0], buf);                                  // buffer handle
    EXPECT_EQ(log[2].u[1],
              static_cast<uint32_t>(dauntless::audio::Category::SFX));
    EXPECT_TRUE(log[2].b[0]);                                     // looping
    EXPECT_TRUE(log[2].b[1]);                                     // positional
    EXPECT_FLOAT_EQ(log[2].f[0], 1.0f);                           // gain

    EXPECT_EQ(log[3].op, "set_position");
    EXPECT_EQ(log[3].u[0], s);
    EXPECT_FLOAT_EQ(log[3].f[0], 10.0f);

    EXPECT_EQ(log[4].op, "stop");
    EXPECT_EQ(log[4].u[0], s);
}

}  // namespace
