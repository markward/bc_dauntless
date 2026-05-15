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

TEST(AudioSystem, UpdatePushesAttachedNodePosition) {
    using namespace open_stbc::audio;
    auto backend = std::make_unique<NullBackend>();
    NullBackend* raw = backend.get();
    AudioSystem sys(std::move(backend));
    ASSERT_TRUE(sys.init());

    auto wav = tiny_wav();
    ASSERT_TRUE(sys.load_sound("sfx/test.wav", "Engine",
                               wav.data(), wav.size(), /*positional*/ true));

    // Stub node-position resolver: node 42 lives at (5, 6, 7).
    sys.set_node_position_fn([](NodeId nid, float& x, float& y, float& z) {
        if (nid == 42u) { x = 5.f; y = 6.f; z = 7.f; return true; }
        return false;
    });

    PlayingId pid = sys.play_sound("Engine", /*looping*/ true, /*gain*/ 1.0f,
                                   Category::SFX, /*attach_node*/ 42u,
                                   /*pos_provided*/ false, 0.f, 0.f, 0.f);
    ASSERT_NE(pid, 0u);

    raw->clear_command_log();
    sys.update(0.f,0.f,0.f, 0.f,0.f,-1.f, 0.f,1.f,0.f, 0.016f);

    bool saw_set_position_at_node = false;
    for (const auto& c : raw->command_log()) {
        if (c.op == "set_position" &&
            c.f[0] == 5.f && c.f[1] == 6.f && c.f[2] == 7.f) {
            saw_set_position_at_node = true;
        }
    }
    EXPECT_TRUE(saw_set_position_at_node);
}

TEST(AudioSystem, UpdateReapsFinishedOneShotsViaBackendStop) {
    using namespace open_stbc::audio;
    auto backend = std::make_unique<NullBackend>();
    NullBackend* raw = backend.get();
    AudioSystem sys(std::move(backend));
    ASSERT_TRUE(sys.init());

    auto wav = tiny_wav();
    ASSERT_TRUE(sys.load_sound("sfx/test.wav", "OneShot",
                               wav.data(), wav.size(), /*positional*/ false));

    PlayingId pid = sys.play_sound("OneShot", /*looping*/ false, /*gain*/ 1.0f,
                                   Category::SFX, /*attach_node*/ 0,
                                   /*pos_provided*/ false, 0.f, 0.f, 0.f);
    ASSERT_NE(pid, 0u);

    // NullBackend hands out SourceHandles starting at 1, so the only one we
    // allocated above has handle 1.
    const SourceHandle backend_handle = 1u;

    raw->mark_finished(backend_handle);
    raw->clear_command_log();
    sys.update(0.f,0.f,0.f, 0.f,0.f,-1.f, 0.f,1.f,0.f, 0.016f);

    // The reap path must call backend_->stop() so the underlying ALuint is
    // released. Without this, finished one-shots leak OpenAL sources and the
    // engine eventually trips OpenAL Soft's 256-source limit.
    bool saw_stop_for_handle = false;
    for (const auto& c : raw->command_log()) {
        if (c.op == "stop" && c.u[0] == backend_handle) saw_stop_for_handle = true;
    }
    EXPECT_TRUE(saw_stop_for_handle);
}

}  // namespace
