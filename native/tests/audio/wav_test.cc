#include <gtest/gtest.h>
#include <audio/wav.h>
#include <cstdint>
#include <cstring>
#include <vector>

namespace {

std::vector<uint8_t> make_pcm16_mono_wav(uint32_t sample_rate,
                                         const std::vector<int16_t>& samples) {
    std::vector<uint8_t> b;
    auto push32 = [&](uint32_t v){ for (int i=0;i<4;i++) b.push_back(static_cast<uint8_t>((v>>(i*8))&0xff)); };
    auto push16 = [&](uint16_t v){ for (int i=0;i<2;i++) b.push_back(static_cast<uint8_t>((v>>(i*8))&0xff)); };
    auto push   = [&](const char* s, size_t n){ for(size_t i=0;i<n;i++) b.push_back(static_cast<uint8_t>(s[i])); };
    const uint32_t data_bytes = static_cast<uint32_t>(samples.size() * sizeof(int16_t));
    push("RIFF", 4); push32(36 + data_bytes); push("WAVE", 4);
    push("fmt ", 4); push32(16); push16(1); push16(1); push32(sample_rate);
    push32(sample_rate * 2); push16(2); push16(16);
    push("data", 4); push32(data_bytes);
    for (auto s : samples) push16(static_cast<uint16_t>(s));
    return b;
}

}  // namespace

TEST(Wav, DecodesMono16) {
    auto bytes = make_pcm16_mono_wav(22050, {0, 1, -1, 32767, -32768});
    dauntless::audio::WavData wav;
    ASSERT_TRUE(dauntless::audio::decode_wav(bytes.data(), bytes.size(), wav));
    EXPECT_EQ(wav.channels, 1);
    EXPECT_EQ(wav.bits_per_sample, 16);
    EXPECT_EQ(wav.sample_rate, 22050u);
    EXPECT_EQ(wav.pcm.size(), 5u * 2);
    int16_t s0; std::memcpy(&s0, wav.pcm.data(), 2);
    EXPECT_EQ(s0, 0);
}
