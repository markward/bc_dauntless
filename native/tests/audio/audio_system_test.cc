#include <gtest/gtest.h>
#include <audio/audio_system.h>
#include <audio/null_backend.h>
#include <cstdint>
#include <cstring>
#include <memory>
#include <vector>

namespace {

std::vector<uint8_t> tiny_wav() {
    std::vector<uint8_t> b;
    auto p32=[&](uint32_t v){for(int i=0;i<4;i++)b.push_back(static_cast<uint8_t>((v>>(i*8))&0xff));};
    auto p16=[&](uint16_t v){for(int i=0;i<2;i++)b.push_back(static_cast<uint8_t>((v>>(i*8))&0xff));};
    auto pn =[&](const char*s,size_t n){for(size_t i=0;i<n;i++)b.push_back(static_cast<uint8_t>(s[i]));};
    pn("RIFF",4); p32(36+4); pn("WAVE",4);
    pn("fmt ",4); p32(16); p16(1); p16(1); p32(22050); p32(44100); p16(2); p16(16);
    pn("data",4); p32(4); p16(0); p16(0);
    return b;
}

TEST(AudioSystem, LoadGetPlayStop) {
    using namespace open_stbc::audio;
    auto backend = std::make_unique<NullBackend>();
    NullBackend* raw = backend.get();
    AudioSystem sys(std::move(backend));
    ASSERT_TRUE(sys.init());

    auto wav = tiny_wav();
    ASSERT_TRUE(sys.load_sound("sfx/test.wav", "TestSound",
                               wav.data(), wav.size(), /*positional*/ true));

    SoundId id = sys.get_sound("TestSound");
    EXPECT_NE(id, 0u);
    EXPECT_EQ(sys.get_sound("NotThere"), 0u);

    PlayingId pid = sys.play_sound("TestSound", /*looping*/ true, /*gain*/ 0.8f,
                                   Category::SFX, /*attach_node*/ 0,
                                   /*pos_provided*/ true, 1.f, 2.f, 3.f);
    ASSERT_NE(pid, 0u);

    sys.update(0.f,0.f,0.f, 0.f,0.f,-1.f, 0.f,1.f,0.f, 0.016f);
    sys.stop(pid);

    bool saw_play=false, saw_stop=false, saw_listener=false;
    for (const auto& c : raw->command_log()) {
        if (c.op == "play") saw_play = true;
        if (c.op == "stop") saw_stop = true;
        if (c.op == "set_listener") saw_listener = true;
    }
    EXPECT_TRUE(saw_play);
    EXPECT_TRUE(saw_stop);
    EXPECT_TRUE(saw_listener);
}

}  // namespace
