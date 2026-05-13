#include <gtest/gtest.h>
#include <audio/null_backend.h>
#include <cstdint>
#include <vector>

namespace {

TEST(NullBackend, RecordsLifecycleAndPlayback) {
    open_stbc::audio::NullBackend b;
    b.init();

    open_stbc::audio::PcmDesc desc{1, 16, 22050};
    std::vector<uint8_t> pcm = {0, 0, 1, 0};
    auto buf = b.create_buffer(desc, pcm.data(), pcm.size());
    ASSERT_NE(buf, 0u);

    auto s = b.play(buf, /*looping*/ true, /*gain*/ 1.0f,
                    open_stbc::audio::Category::SFX,
                    /*positional*/ true, 0.0f, 0.0f, 0.0f);
    ASSERT_NE(s, 0u);
    b.set_position(s, 10.0f, 0.0f, 0.0f);
    b.stop(s);

    const auto& log = b.command_log();
    ASSERT_EQ(log.size(), 5u);
    EXPECT_EQ(log[0].op, "init");
    EXPECT_EQ(log[1].op, "create_buffer");
    EXPECT_EQ(log[2].op, "play");
    EXPECT_EQ(log[3].op, "set_position");
    EXPECT_EQ(log[4].op, "stop");
}

}  // namespace
