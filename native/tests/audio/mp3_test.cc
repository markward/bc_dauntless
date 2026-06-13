#include <gtest/gtest.h>
#include <audio/mp3.h>
#include <cstdint>
#include <vector>

namespace {

TEST(DecodeMp3, RejectsGarbage) {
    // Random non-MP3 bytes must fail cleanly (caller treats as missing).
    std::vector<uint8_t> junk = {0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07};
    dauntless::audio::WavData out;
    EXPECT_FALSE(dauntless::audio::decode_mp3(junk.data(), junk.size(), out));
}

TEST(DecodeMp3, RejectsEmpty) {
    dauntless::audio::WavData out;
    EXPECT_FALSE(dauntless::audio::decode_mp3(nullptr, 0, out));
}

}  // namespace
