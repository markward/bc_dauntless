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
    using namespace dauntless::audio;
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
                                   Category::SFX,
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

TEST(AudioSystem, PlayHasNoNodeParameter) {
    // Node tracking lives in Python (engine/audio/attached_sources.py) because
    // the deferred renderer has no scene graph. The C++ NodeId path assumed one,
    // was never wired outside this test file, and never moved a source.
    using namespace dauntless::audio;
    auto backend = std::make_unique<NullBackend>();
    NullBackend* raw = backend.get();
    AudioSystem sys(std::move(backend));
    ASSERT_TRUE(sys.init());

    auto wav = tiny_wav();
    ASSERT_TRUE(sys.load_sound("sfx/test.wav", "S", wav.data(), wav.size(), true));

    PlayingId pid = sys.play_sound("S", /*looping*/ false, /*gain*/ 1.0f,
                                   Category::SFX,
                                   /*pos_provided*/ true, 4.f, 5.f, 6.f);
    ASSERT_NE(pid, 0u);

    sys.update(0,0,0, 0,1,0, 0,0,1, 0.016f);

    // update() must not emit set_position for anything: the C++ layer no longer
    // owns tracking.
    for (const auto& c : raw->command_log())
        EXPECT_NE(c.op, "set_position");
}

TEST(AudioSystem, UpdateReapsFinishedOneShotsViaBackendStop) {
    using namespace dauntless::audio;
    auto backend = std::make_unique<NullBackend>();
    NullBackend* raw = backend.get();
    AudioSystem sys(std::move(backend));
    ASSERT_TRUE(sys.init());

    auto wav = tiny_wav();
    ASSERT_TRUE(sys.load_sound("sfx/test.wav", "OneShot",
                               wav.data(), wav.size(), /*positional*/ false));

    PlayingId pid = sys.play_sound("OneShot", /*looping*/ false, /*gain*/ 1.0f,
                                   Category::SFX,
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

TEST(AudioSystem, IsFinishedTrueForUnknownAndBackendFinishedSources) {
    using namespace dauntless::audio;
    auto backend = std::make_unique<NullBackend>();
    NullBackend* raw = backend.get();
    AudioSystem sys(std::move(backend));
    ASSERT_TRUE(sys.init());

    auto wav = tiny_wav();
    ASSERT_TRUE(sys.load_sound("sfx/test.wav", "OneShot",
                               wav.data(), wav.size(), /*positional*/ false));

    PlayingId pid = sys.play_sound("OneShot", /*looping*/ false, /*gain*/ 1.0f,
                                   Category::SFX,
                                   /*pos_provided*/ false, 0.f, 0.f, 0.f);
    ASSERT_NE(pid, 0u);

    // Not finished yet: NullBackend never marks a source finished on its own.
    EXPECT_FALSE(sys.is_finished(pid));

    // An unknown/never-issued pid must read as finished (already reaped, or
    // never existed) so a Python pump can't spin on a dead reference.
    EXPECT_TRUE(sys.is_finished(pid + 1000));

    const SourceHandle backend_handle = sys.debug_backend_handle(pid);
    ASSERT_NE(backend_handle, 0u);
    raw->mark_finished(backend_handle);
    EXPECT_TRUE(sys.is_finished(pid));

    // update() reaps it from sources_; is_finished must still read true for
    // the now-unknown pid.
    sys.update(0.f,0.f,0.f, 0.f,0.f,-1.f, 0.f,1.f,0.f, 0.016f);
    EXPECT_TRUE(sys.is_finished(pid));
}

TEST(AudioSystem, ForceNonPositionalOverridesLoadTimePositionalFlag) {
    using namespace dauntless::audio;
    auto backend = std::make_unique<NullBackend>();
    NullBackend* raw = backend.get();
    AudioSystem sys(std::move(backend));
    ASSERT_TRUE(sys.init());

    auto wav = tiny_wav();
    // Loaded as a positional (LS_3D) sound, same as every weapon WAV.
    ASSERT_TRUE(sys.load_sound("sfx/test.wav", "Weapon",
                               wav.data(), wav.size(), /*positional*/ true));

    raw->clear_command_log();
    PlayingId pid = sys.play_sound("Weapon", /*looping*/ false, /*gain*/ 1.0f,
                                   Category::SFX,
                                   /*pos_provided*/ false, 0.f, 0.f, 0.f,
                                   /*force_non_positional*/ true);
    ASSERT_NE(pid, 0u);

    bool saw_non_positional_play = false;
    for (const auto& c : raw->command_log()) {
        if (c.op == "play" && c.b[1] == false) saw_non_positional_play = true;
    }
    EXPECT_TRUE(saw_non_positional_play)
        << "force_non_positional must override the sound's load-time LS_3D "
           "flag, not just the pos_provided/attach_node heuristic";
}

TEST(AudioSystemDispatch, LoadsWavViaSniff) {
    using namespace dauntless::audio;
    auto backend = std::make_unique<NullBackend>();
    AudioSystem sys(std::move(backend));
    ASSERT_TRUE(sys.init());
    auto wav = tiny_wav();
    EXPECT_TRUE(sys.load_sound("", "wav_sound", wav.data(), wav.size(), false));
    EXPECT_NE(sys.get_sound("wav_sound"), 0u);
}

TEST(AudioSystemDispatch, NonWavRoutedToMp3AndFailsCleanly) {
    using namespace dauntless::audio;
    auto backend = std::make_unique<NullBackend>();
    AudioSystem sys(std::move(backend));
    ASSERT_TRUE(sys.init());
    // Not RIFF/WAVE -> routed to decode_mp3 -> not a valid MP3 -> false, no crash.
    std::vector<uint8_t> junk = {0x49, 0x44, 0x33, 0x00, 0x11, 0x22, 0x33, 0x44};
    EXPECT_FALSE(sys.load_sound("", "bad", junk.data(), junk.size(), false));
    EXPECT_EQ(sys.get_sound("bad"), 0u);
}

}  // namespace
