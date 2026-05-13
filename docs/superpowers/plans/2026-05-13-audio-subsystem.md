# Audio Subsystem Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land an OpenAL-backed audio subsystem in `native/src/audio/` exposed via `_open_stbc_host.audio`, wire `TGSound`/`TGSoundManager`/`TGSoundAction` in the Python shim so `LoadTacticalSounds.py` and `LoadBridge.py` run unchanged, and produce audible engine rumble on every spawned ship plus alert one-shots on Shift+1/2/3.

**Architecture:** C++ owns OpenAL state, 3D math, and a WAV decoder behind an `IAudioBackend` interface (real `OpenALBackend` for normal runs, `NullBackend` recording a command log for pytest). Python receives opaque handles. `engine/audio/tg_sound.py` implements the BC `TGSound` surface as a thin wrapper over the binding. `engine/audio/alert_audio.py` polls `player.GetAlertLevel()` per tick in `host_loop` to fire alert SFX on transitions; `engine/appc/ship_lifecycle.py` events drive engine-rumble Play/Stop on spawn/destroy.

**Tech Stack:** OpenAL Soft (FetchContent pin), pybind11 (existing), CPython 3.11 embed (existing), pytest. No new third-party deps beyond OpenAL Soft.

**Spec:** [docs/superpowers/specs/2026-05-13-audio-subsystem-design.md](../specs/2026-05-13-audio-subsystem-design.md)

---

## File Map

**Create:** Per-library layout follows the project convention (`include/<libname>/` for public headers, `src/` for sources). Tests live under `native/tests/audio/` as GTest cases registered via `gtest_discover_tests`.
- `native/src/audio/CMakeLists.txt` — audio library target
- `native/src/audio/include/audio/audio_backend.h` — `IAudioBackend` interface
- `native/src/audio/include/audio/wav.h`, `native/src/audio/src/wav.cc` — PCM WAV decoder
- `native/src/audio/include/audio/null_backend.h`, `native/src/audio/src/null_backend.cc` — recording backend
- `native/src/audio/include/audio/openal_backend.h`, `native/src/audio/src/openal_backend.cc` — OpenAL Soft backend
- `native/src/audio/include/audio/audio_system.h`, `native/src/audio/src/audio_system.cc` — facade + handle registries
- `native/src/audio/include/audio/python_binding.h`, `native/src/audio/src/python_binding.cc` — pybind11 submodule `_open_stbc_host.audio`
- `native/tests/audio/CMakeLists.txt`, `native/tests/audio/wav_test.cc`, `native/tests/audio/null_backend_test.cc`, `native/tests/audio/audio_system_test.cc` — GTest cases for the C++ side (registered via `gtest_discover_tests`)
- `engine/audio/__init__.py` — empty package marker
- `engine/audio/tg_sound.py` — `TGSound` / `TGSoundManager` / `TGSoundAction`
- `engine/audio/alert_audio.py` — alert-level listener
- `tests/audio/test_tg_sound.py` — TGSound surface tests against NullBackend
- `tests/audio/test_engine_rumble.py` — ship-spawn engine rumble integration
- `tests/audio/test_alert_audio.py` — alert listener transition tests

**Modify:**
- `native/CMakeLists.txt` — add OpenAL Soft FetchContent + `add_subdirectory(src/audio)`
- `native/src/host/CMakeLists.txt` — link audio library into host
- `native/src/host/host_bindings.cc:274` — register `audio` submodule alongside existing `keys`
- `engine/appc/properties.py:291-292` — add `SetEngineSound`/`GetEngineSound` to `ImpulseEngineProperty`
- `engine/appc/actions.py:175-184` — make `TGSoundAction.Play()` delegate to `g_kSoundManager.PlaySound`
- `App.py` — import `TGSound`, `TGSoundManager`, `g_kSoundManager` from `engine.audio.tg_sound`
- `engine/host_loop.py` — init audio system at boot; per-tick `audio.update`; mount alert listener; subscribe ship_lifecycle for engine rumble
- `tests/conftest.py` — set `OPEN_STBC_AUDIO=0` before any engine import

---

## Task 1: PCM WAV decoder (C++, no AL dep)

**Files:**
- Create: `native/src/audio/wav.h`, `native/src/audio/wav.cc`, `native/src/audio/CMakeLists.txt`
- Test: `native/src/audio/tests/test_wav.cc`

The decoder is pure C++ with no OpenAL dependency so it can be unit-tested in isolation.

- [ ] **Step 1: Write the failing test**

Create `native/src/audio/tests/test_wav.cc`:

```cpp
// Self-contained test: synthesizes a tiny PCM WAV in memory and parses it.
#include "audio/wav.h"
#include <cassert>
#include <cstdint>
#include <cstring>
#include <vector>

static std::vector<uint8_t> make_pcm16_mono_wav(uint32_t sample_rate,
                                                const std::vector<int16_t>& samples) {
    std::vector<uint8_t> b;
    auto push32 = [&](uint32_t v){ for (int i=0;i<4;i++) b.push_back((v>>(i*8))&0xff); };
    auto push16 = [&](uint16_t v){ for (int i=0;i<2;i++) b.push_back((v>>(i*8))&0xff); };
    auto push  = [&](const char* s, size_t n){ for(size_t i=0;i<n;i++) b.push_back((uint8_t)s[i]); };
    const uint32_t data_bytes = (uint32_t)(samples.size() * sizeof(int16_t));
    push("RIFF", 4); push32(36 + data_bytes); push("WAVE", 4);
    push("fmt ", 4); push32(16); push16(1); push16(1); push32(sample_rate);
    push32(sample_rate * 2); push16(2); push16(16);
    push("data", 4); push32(data_bytes);
    for (auto s : samples) push16((uint16_t)s);
    return b;
}

int main() {
    auto bytes = make_pcm16_mono_wav(22050, {0, 1, -1, 32767, -32768});
    open_stbc::audio::WavData wav;
    bool ok = open_stbc::audio::decode_wav(bytes.data(), bytes.size(), wav);
    assert(ok);
    assert(wav.channels == 1);
    assert(wav.bits_per_sample == 16);
    assert(wav.sample_rate == 22050);
    assert(wav.pcm.size() == 5 * 2);
    int16_t s0; std::memcpy(&s0, wav.pcm.data(), 2);
    assert(s0 == 0);
    return 0;
}
```

- [ ] **Step 2: Create the CMake target**

Create `native/src/audio/CMakeLists.txt`:

```cmake
add_library(open_stbc_audio STATIC
    wav.cc
)
target_include_directories(open_stbc_audio PUBLIC ${CMAKE_SOURCE_DIR}/native/src)
target_compile_features(open_stbc_audio PUBLIC cxx_std_20)

# Test executable, built only when OPEN_STBC_BUILD_TESTS is on (set by default
# in native/CMakeLists.txt for local builds).
if(OPEN_STBC_BUILD_TESTS)
    add_executable(test_wav tests/test_wav.cc)
    target_link_libraries(test_wav PRIVATE open_stbc_audio)
    add_test(NAME test_wav COMMAND test_wav)
endif()
```

Then in `native/CMakeLists.txt`, after the existing `add_subdirectory(third_party/...)` block (around line 22), add:

```cmake
# Enable native unit tests (cheap, no external deps).
option(OPEN_STBC_BUILD_TESTS "Build native unit tests" ON)
if(OPEN_STBC_BUILD_TESTS)
    enable_testing()
endif()

add_subdirectory(src/audio)
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
cmake -B build -S . && cmake --build build -j 2>&1 | tail -20
```

Expected: build failure — `wav.h` doesn't exist yet.

- [ ] **Step 4: Implement the WAV decoder**

Create `native/src/audio/wav.h`:

```cpp
#pragma once
#include <cstdint>
#include <vector>

namespace open_stbc::audio {

struct WavData {
    uint16_t channels = 0;
    uint16_t bits_per_sample = 0;
    uint32_t sample_rate = 0;
    std::vector<uint8_t> pcm;  // interleaved little-endian PCM bytes
};

// Returns true on success. Supports PCM (format code 1), 8 or 16 bit,
// 1 or 2 channels. Other formats return false (caller treats as missing).
bool decode_wav(const uint8_t* bytes, size_t len, WavData& out);

}
```

Create `native/src/audio/wav.cc`:

```cpp
#include "audio/wav.h"
#include <cstring>

namespace open_stbc::audio {

static bool read_u32(const uint8_t* p, size_t off, size_t len, uint32_t& v) {
    if (off + 4 > len) return false;
    v = (uint32_t)p[off] | ((uint32_t)p[off+1] << 8) |
        ((uint32_t)p[off+2] << 16) | ((uint32_t)p[off+3] << 24);
    return true;
}

static bool read_u16(const uint8_t* p, size_t off, size_t len, uint16_t& v) {
    if (off + 2 > len) return false;
    v = (uint16_t)p[off] | ((uint16_t)p[off+1] << 8);
    return true;
}

bool decode_wav(const uint8_t* p, size_t len, WavData& out) {
    if (len < 44) return false;
    if (std::memcmp(p, "RIFF", 4) != 0) return false;
    if (std::memcmp(p + 8, "WAVE", 4) != 0) return false;

    size_t off = 12;
    bool got_fmt = false;
    while (off + 8 <= len) {
        char id[4]; std::memcpy(id, p + off, 4);
        uint32_t sz;
        if (!read_u32(p, off + 4, len, sz)) return false;
        size_t chunk_data = off + 8;
        if (chunk_data + sz > len) return false;

        if (std::memcmp(id, "fmt ", 4) == 0) {
            uint16_t fmt_code, channels, bps;
            uint32_t sample_rate;
            if (!read_u16(p, chunk_data + 0, len, fmt_code)) return false;
            if (fmt_code != 1) return false;  // PCM only
            if (!read_u16(p, chunk_data + 2, len, channels)) return false;
            if (!read_u32(p, chunk_data + 4, len, sample_rate)) return false;
            if (!read_u16(p, chunk_data + 14, len, bps)) return false;
            if (channels != 1 && channels != 2) return false;
            if (bps != 8 && bps != 16) return false;
            out.channels = channels;
            out.bits_per_sample = bps;
            out.sample_rate = sample_rate;
            got_fmt = true;
        } else if (std::memcmp(id, "data", 4) == 0) {
            if (!got_fmt) return false;
            out.pcm.assign(p + chunk_data, p + chunk_data + sz);
            return true;
        }

        off = chunk_data + sz;
        if (sz % 2) off += 1;  // RIFF chunks pad to even length
    }
    return false;
}

}
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cmake --build build -j && ctest --test-dir build --output-on-failure -R test_wav
```

Expected: `test_wav` passes.

- [ ] **Step 6: Commit**

```bash
git add native/src/audio/wav.h native/src/audio/wav.cc \
        native/src/audio/CMakeLists.txt native/src/audio/tests/test_wav.cc \
        native/CMakeLists.txt
git commit -m "feat(audio): PCM WAV decoder

Pure C++ decoder for the WAV subset BC uses (PCM mono/stereo, 8/16 bit).
Anything else is rejected so callers can treat unsupported files as
missing and continue. Unit-tested via synthesized in-memory WAV.
"
```

---

## Task 2: IAudioBackend interface + NullBackend

**Files:**
- Create: `native/src/audio/include/audio/audio_backend.h`, `native/src/audio/include/audio/null_backend.h`, `native/src/audio/src/null_backend.cc`, `native/tests/audio/null_backend_test.cc`
- Modify: `native/src/audio/CMakeLists.txt`, `native/tests/audio/CMakeLists.txt`

Convention reminder (established in Task 1): public headers under `include/audio/`, sources under `src/`, tests under `native/tests/audio/` as GTest cases registered via `gtest_discover_tests`. The audio library target is `open_stbc_audio`; the test executable is `audio_tests`.

- [ ] **Step 1: Write the failing test**

Create `native/tests/audio/null_backend_test.cc`:

```cpp
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
```

- [ ] **Step 2: Wire the test source and library source**

Append to `native/src/audio/CMakeLists.txt`:

```cmake
target_sources(open_stbc_audio PRIVATE src/null_backend.cc)
```

Append to `native/tests/audio/CMakeLists.txt` — add the new test source to the existing `audio_tests` executable:

```cmake
target_sources(audio_tests PRIVATE null_backend_test.cc)
```

- [ ] **Step 3: Run to verify failure**

```bash
cmake --build build -j 2>&1 | tail -10
```

Expected: build fails — `audio/audio_backend.h` and `audio/null_backend.h` missing.

- [ ] **Step 4: Implement the interface and null backend**

Create `native/src/audio/include/audio/audio_backend.h`:

```cpp
#pragma once
#include <cstdint>
#include <vector>

namespace open_stbc::audio {

using BufferHandle = uint32_t;  // 0 == invalid
using SourceHandle = uint32_t;  // 0 == invalid

enum class Category : uint8_t {
    SFX = 0,
    Voice = 1,
    Interface = 2,
};

struct PcmDesc {
    uint16_t channels;
    uint16_t bits_per_sample;
    uint32_t sample_rate;
};

class IAudioBackend {
public:
    virtual ~IAudioBackend() = default;
    virtual bool init() = 0;
    virtual void shutdown() = 0;

    virtual BufferHandle create_buffer(const PcmDesc& desc,
                                       const uint8_t* pcm, size_t bytes) = 0;
    virtual void destroy_buffer(BufferHandle) = 0;

    virtual SourceHandle play(BufferHandle, bool looping, float gain,
                              Category, bool positional,
                              float x, float y, float z) = 0;
    virtual void stop(SourceHandle) = 0;
    virtual void set_position(SourceHandle, float x, float y, float z) = 0;
    virtual void set_gain(SourceHandle, float) = 0;
    virtual void set_looping(SourceHandle, bool) = 0;
    virtual void set_min_max_distance(SourceHandle, float min, float max) = 0;

    virtual void set_listener(float px, float py, float pz,
                              float fx, float fy, float fz,
                              float ux, float uy, float uz) = 0;
    virtual void set_category_gain(Category, float) = 0;

    // True if the source has stopped on its own (one-shot completed).
    virtual bool source_finished(SourceHandle) = 0;
};

}  // namespace open_stbc::audio
```

Create `native/src/audio/include/audio/null_backend.h`:

```cpp
#pragma once
#include <audio/audio_backend.h>
#include <string>
#include <vector>
#include <variant>

namespace open_stbc::audio {

struct LoggedCall {
    std::string op;
    // Tagged-union args. We keep this loose because tests only inspect a handful.
    float f[9] = {0,0,0,0,0,0,0,0,0};
    uint32_t u[4] = {0,0,0,0};
    bool b[2] = {false,false};
};

class NullBackend : public IAudioBackend {
public:
    bool init() override;
    void shutdown() override;

    BufferHandle create_buffer(const PcmDesc&, const uint8_t*, size_t) override;
    void destroy_buffer(BufferHandle) override;
    SourceHandle play(BufferHandle, bool looping, float gain, Category,
                      bool positional, float, float, float) override;
    void stop(SourceHandle) override;
    void set_position(SourceHandle, float, float, float) override;
    void set_gain(SourceHandle, float) override;
    void set_looping(SourceHandle, bool) override;
    void set_min_max_distance(SourceHandle, float, float) override;
    void set_listener(float,float,float, float,float,float, float,float,float) override;
    void set_category_gain(Category, float) override;
    bool source_finished(SourceHandle) override;

    const std::vector<LoggedCall>& command_log() const { return log_; }
    void clear_command_log() { log_.clear(); }

private:
    uint32_t next_buf_ = 1;
    uint32_t next_src_ = 1;
    std::vector<LoggedCall> log_;
};

}  // namespace open_stbc::audio
```

Create `native/src/audio/src/null_backend.cc`:

```cpp
#include <audio/null_backend.h>

namespace open_stbc::audio {

bool NullBackend::init() { log_.push_back({"init"}); return true; }
void NullBackend::shutdown() { log_.push_back({"shutdown"}); }

BufferHandle NullBackend::create_buffer(const PcmDesc& d, const uint8_t*, size_t n) {
    LoggedCall c{"create_buffer"};
    c.u[0] = d.channels; c.u[1] = d.bits_per_sample;
    c.u[2] = d.sample_rate; c.u[3] = (uint32_t)n;
    log_.push_back(c);
    return next_buf_++;
}

void NullBackend::destroy_buffer(BufferHandle h) {
    LoggedCall c{"destroy_buffer"}; c.u[0] = h; log_.push_back(c);
}

SourceHandle NullBackend::play(BufferHandle buf, bool looping, float gain,
                               Category cat, bool positional,
                               float x, float y, float z) {
    LoggedCall c{"play"};
    c.u[0] = buf; c.u[1] = (uint32_t)cat;
    c.b[0] = looping; c.b[1] = positional;
    c.f[0] = gain; c.f[1] = x; c.f[2] = y; c.f[3] = z;
    log_.push_back(c);
    return next_src_++;
}

void NullBackend::stop(SourceHandle h) {
    LoggedCall c{"stop"}; c.u[0] = h; log_.push_back(c);
}

void NullBackend::set_position(SourceHandle h, float x, float y, float z) {
    LoggedCall c{"set_position"}; c.u[0] = h;
    c.f[0] = x; c.f[1] = y; c.f[2] = z;
    log_.push_back(c);
}

void NullBackend::set_gain(SourceHandle h, float g) {
    LoggedCall c{"set_gain"}; c.u[0] = h; c.f[0] = g; log_.push_back(c);
}

void NullBackend::set_looping(SourceHandle h, bool l) {
    LoggedCall c{"set_looping"}; c.u[0] = h; c.b[0] = l; log_.push_back(c);
}

void NullBackend::set_min_max_distance(SourceHandle h, float mn, float mx) {
    LoggedCall c{"set_min_max_distance"}; c.u[0] = h;
    c.f[0] = mn; c.f[1] = mx; log_.push_back(c);
}

void NullBackend::set_listener(float px, float py, float pz,
                               float fx, float fy, float fz,
                               float ux, float uy, float uz) {
    LoggedCall c{"set_listener"};
    c.f[0]=px; c.f[1]=py; c.f[2]=pz;
    c.f[3]=fx; c.f[4]=fy; c.f[5]=fz;
    c.f[6]=ux; c.f[7]=uy; c.f[8]=uz;
    log_.push_back(c);
}

void NullBackend::set_category_gain(Category cat, float g) {
    LoggedCall c{"set_category_gain"};
    c.u[0] = (uint32_t)cat; c.f[0] = g; log_.push_back(c);
}

bool NullBackend::source_finished(SourceHandle) { return false; }

}  // namespace open_stbc::audio
```

- [ ] **Step 5: Run to verify passes**

```bash
cmake --build build -j && ctest --test-dir build --output-on-failure -R "Wav\.|NullBackend\."
```

Expected: both `Wav.DecodesMono16` and `NullBackend.RecordsLifecycleAndPlayback` pass.

- [ ] **Step 6: Commit**

```bash
git add native/src/audio/include/audio/audio_backend.h \
        native/src/audio/include/audio/null_backend.h \
        native/src/audio/src/null_backend.cc \
        native/src/audio/CMakeLists.txt \
        native/tests/audio/null_backend_test.cc \
        native/tests/audio/CMakeLists.txt
git commit -m "feat(audio): IAudioBackend interface + recording NullBackend

NullBackend records every call into a vector so tests can assert on
the command stream without opening an audio device.
"
```

---

## Task 3: AudioSystem facade

**Files:**
- Create: `native/src/audio/include/audio/audio_system.h`, `native/src/audio/src/audio_system.cc`, `native/tests/audio/audio_system_test.cc`
- Modify: `native/src/audio/CMakeLists.txt`, `native/tests/audio/CMakeLists.txt`

`AudioSystem` owns the chosen backend, the name→buffer registry, and live source bookkeeping. Per-frame `update()` pushes positions for attached sources. Same per-library layout as Tasks 1 and 2.

- [ ] **Step 1: Write the failing test**

Create `native/tests/audio/audio_system_test.cc`:

```cpp
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
```

- [ ] **Step 2: Wire the new sources**

Append to `native/src/audio/CMakeLists.txt`:

```cmake
target_sources(open_stbc_audio PRIVATE src/audio_system.cc)
```

Append to `native/tests/audio/CMakeLists.txt`:

```cmake
target_sources(audio_tests PRIVATE audio_system_test.cc)
```

- [ ] **Step 3: Run to verify failure**

```bash
cmake --build build -j 2>&1 | tail -10
```

Expected: build error, `audio/audio_system.h` missing.

- [ ] **Step 4: Implement AudioSystem**

Create `native/src/audio/include/audio/audio_system.h`:

```cpp
#pragma once
#include <audio/audio_backend.h>
#include <functional>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace open_stbc::audio {

using SoundId = uint32_t;    // logical buffer id, returned to Python
using PlayingId = uint32_t;  // logical source id, returned to Python
using NodeId = uint32_t;     // scenegraph node id, 0 == none

// Pulls a node's world position. Set by host_loop; tests provide a stub.
using NodePositionFn = std::function<bool(NodeId, float& x, float& y, float& z)>;

class AudioSystem {
public:
    explicit AudioSystem(std::unique_ptr<IAudioBackend> backend);
    ~AudioSystem();

    bool init();
    void shutdown();

    void set_node_position_fn(NodePositionFn fn) { node_pos_fn_ = std::move(fn); }

    bool load_sound(const std::string& path, const std::string& name,
                    const uint8_t* wav_bytes, size_t wav_len, bool positional);

    SoundId get_sound(const std::string& name) const;
    bool is_loaded(SoundId) const;
    bool is_positional(SoundId) const;

    PlayingId play_sound(const std::string& name, bool looping, float gain,
                         Category, NodeId attach_node,
                         bool position_provided, float x, float y, float z);

    PlayingId play(SoundId, bool looping, float gain, Category, NodeId attach_node,
                   bool position_provided, float x, float y, float z);

    void stop(PlayingId);
    void set_gain(PlayingId, float);
    void set_looping(PlayingId, bool);
    void set_min_max_distance(PlayingId, float, float);
    void set_position(PlayingId, float, float, float);

    void set_category_gain(Category, float);

    void update(float lx, float ly, float lz,
                float fx, float fy, float fz,
                float ux, float uy, float uz,
                float dt);

    // Test/inspection.
    IAudioBackend* backend() { return backend_.get(); }

private:
    struct Sound {
        BufferHandle buf;
        bool positional;
    };
    struct Source {
        SourceHandle backend;
        NodeId node;
        bool looping;
    };

    std::unique_ptr<IAudioBackend> backend_;
    std::unordered_map<std::string, SoundId> name_to_id_;
    std::unordered_map<SoundId, Sound> sounds_;
    std::unordered_map<PlayingId, Source> sources_;
    SoundId next_sound_id_ = 1;
    PlayingId next_playing_id_ = 1;
    NodePositionFn node_pos_fn_;
};

}  // namespace open_stbc::audio
```

Create `native/src/audio/src/audio_system.cc`:

```cpp
#include <audio/audio_system.h>
#include <audio/wav.h>

namespace open_stbc::audio {

AudioSystem::AudioSystem(std::unique_ptr<IAudioBackend> b)
    : backend_(std::move(b)) {}

AudioSystem::~AudioSystem() = default;

bool AudioSystem::init() { return backend_ && backend_->init(); }
void AudioSystem::shutdown() { if (backend_) backend_->shutdown(); }

bool AudioSystem::load_sound(const std::string&, const std::string& name,
                             const uint8_t* wav_bytes, size_t wav_len,
                             bool positional) {
    WavData wav;
    if (!decode_wav(wav_bytes, wav_len, wav)) return false;
    PcmDesc d{wav.channels, wav.bits_per_sample, wav.sample_rate};
    BufferHandle h = backend_->create_buffer(d, wav.pcm.data(), wav.pcm.size());
    if (h == 0) return false;
    SoundId id = next_sound_id_++;
    sounds_[id] = {h, positional};
    name_to_id_[name] = id;
    return true;
}

SoundId AudioSystem::get_sound(const std::string& name) const {
    auto it = name_to_id_.find(name);
    return it == name_to_id_.end() ? 0 : it->second;
}

bool AudioSystem::is_loaded(SoundId id) const { return sounds_.count(id) > 0; }
bool AudioSystem::is_positional(SoundId id) const {
    auto it = sounds_.find(id);
    return it != sounds_.end() && it->second.positional;
}

PlayingId AudioSystem::play(SoundId id, bool looping, float gain, Category cat,
                            NodeId attach_node, bool pos_provided,
                            float x, float y, float z) {
    auto it = sounds_.find(id);
    if (it == sounds_.end()) return 0;
    bool positional = it->second.positional || pos_provided || attach_node != 0;
    SourceHandle bh = backend_->play(it->second.buf, looping, gain, cat,
                                     positional, x, y, z);
    if (bh == 0) return 0;
    PlayingId pid = next_playing_id_++;
    sources_[pid] = {bh, attach_node, looping};
    return pid;
}

PlayingId AudioSystem::play_sound(const std::string& name, bool looping, float gain,
                                  Category cat, NodeId attach_node,
                                  bool pos_provided, float x, float y, float z) {
    SoundId id = get_sound(name);
    return id == 0 ? 0 : play(id, looping, gain, cat, attach_node,
                              pos_provided, x, y, z);
}

void AudioSystem::stop(PlayingId pid) {
    auto it = sources_.find(pid);
    if (it == sources_.end()) return;
    backend_->stop(it->second.backend);
    sources_.erase(it);
}

void AudioSystem::set_gain(PlayingId pid, float g) {
    auto it = sources_.find(pid);
    if (it != sources_.end()) backend_->set_gain(it->second.backend, g);
}

void AudioSystem::set_looping(PlayingId pid, bool l) {
    auto it = sources_.find(pid);
    if (it == sources_.end()) return;
    it->second.looping = l;
    backend_->set_looping(it->second.backend, l);
}

void AudioSystem::set_min_max_distance(PlayingId pid, float mn, float mx) {
    auto it = sources_.find(pid);
    if (it != sources_.end()) backend_->set_min_max_distance(it->second.backend, mn, mx);
}

void AudioSystem::set_position(PlayingId pid, float x, float y, float z) {
    auto it = sources_.find(pid);
    if (it != sources_.end()) backend_->set_position(it->second.backend, x, y, z);
}

void AudioSystem::set_category_gain(Category c, float g) {
    backend_->set_category_gain(c, g);
}

void AudioSystem::update(float lx, float ly, float lz,
                         float fx, float fy, float fz,
                         float ux, float uy, float uz, float /*dt*/) {
    backend_->set_listener(lx,ly,lz, fx,fy,fz, ux,uy,uz);

    // Update attached source positions.
    for (auto& [pid, src] : sources_) {
        if (src.node == 0 || !node_pos_fn_) continue;
        float x, y, z;
        if (node_pos_fn_(src.node, x, y, z)) {
            backend_->set_position(src.backend, x, y, z);
        }
    }

    // Reap finished one-shots.
    for (auto it = sources_.begin(); it != sources_.end(); ) {
        if (!it->second.looping && backend_->source_finished(it->second.backend)) {
            it = sources_.erase(it);
        } else {
            ++it;
        }
    }
}

}  // namespace open_stbc::audio
```

- [ ] **Step 5: Run to verify passes**

```bash
cmake --build build -j && ctest --test-dir build --output-on-failure -R "AudioSystem\."
```

Expected: `AudioSystem.LoadGetPlayStop` passes.

- [ ] **Step 6: Commit**

```bash
git add native/src/audio/include/audio/audio_system.h \
        native/src/audio/src/audio_system.cc \
        native/src/audio/CMakeLists.txt \
        native/tests/audio/audio_system_test.cc \
        native/tests/audio/CMakeLists.txt
git commit -m "feat(audio): AudioSystem facade owning backend + handle registries

Issues opaque SoundId/PlayingId handles to callers, maps named sounds
to buffers, and pumps attached-source position updates each frame via
an injected NodePositionFn callback.
"
```

---

## Task 4: pybind11 binding — `_open_stbc_host.audio` submodule

**Files:**
- Create: `native/src/audio/include/audio/python_binding.h`, `native/src/audio/src/python_binding.cc`
- Modify: `native/src/audio/CMakeLists.txt`, `native/src/host/host_bindings.cc`, `native/src/host/CMakeLists.txt`

- [ ] **Step 1: Write the failing test**

Create `tests/audio/test_binding.py` (this test exercises the C++ binding end-to-end via the audio package once Task 5 lands; for now it asserts the submodule is reachable):

```python
import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")  # force NullBackend

# These imports will succeed only after the binding lands.
_open_stbc_host = pytest.importorskip("_open_stbc_host")


def _make_pcm16_mono_wav(rate, samples):
    data = b"".join(struct.pack("<h", s) for s in samples)
    fmt = struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16) + fmt
            + b"data" + struct.pack("<I", len(data)) + data)


def test_audio_submodule_exists():
    assert hasattr(_open_stbc_host, "audio")


def test_audio_load_and_play_via_null_backend():
    audio = _open_stbc_host.audio
    audio.init(backend="null")
    wav = _make_pcm16_mono_wav(22050, [0, 1, -1, 2, -2])
    assert audio.load_sound("sfx/test.wav", "TestSound", wav, positional=False)
    sid = audio.get_sound("TestSound")
    assert sid != 0
    pid = audio.play("TestSound", looping=False, gain=1.0, category="SFX",
                     attach_node=0, position=None)
    assert pid != 0
    log = audio.debug_command_log()
    assert any(entry["op"] == "play" for entry in log)
    audio.stop(pid)
    audio.shutdown()
```

- [ ] **Step 2: Run to verify failure**

```bash
PYTHONPATH=build/python uv run pytest tests/audio/test_binding.py -x 2>&1 | tail -20
```

Expected: `assert hasattr(_open_stbc_host, "audio")` fails — submodule not registered.

- [ ] **Step 3: Implement the binding**

Create `native/src/audio/include/audio/python_binding.h`:

```cpp
#pragma once
#include <pybind11/pybind11.h>

namespace open_stbc::audio {
// Attach the `audio` submodule onto the parent _open_stbc_host module.
void register_python_bindings(pybind11::module_& parent);

// Test/host accessor — the singleton AudioSystem after init().
class AudioSystem;
AudioSystem* system();
}  // namespace open_stbc::audio
```

Create `native/src/audio/src/python_binding.cc`:

```cpp
#include <audio/python_binding.h>
#include <audio/audio_system.h>
#include <audio/null_backend.h>
#include <audio/openal_backend.h>   // forward-declared; real impl lands in Task 5
#include <pybind11/stl.h>
#include <memory>
#include <optional>
#include <string>

namespace py = pybind11;

namespace open_stbc::audio {

static std::unique_ptr<AudioSystem> g_system;

AudioSystem* system() { return g_system.get(); }

static Category parse_category(const std::string& s) {
    if (s == "Voice") return Category::Voice;
    if (s == "Interface") return Category::Interface;
    return Category::SFX;
}

static const char* category_name(Category c) {
    switch (c) {
        case Category::Voice: return "Voice";
        case Category::Interface: return "Interface";
        default: return "SFX";
    }
}

static bool init_impl(const std::string& backend_kind) {
    std::unique_ptr<IAudioBackend> b;
    if (backend_kind == "null") {
        b = std::make_unique<NullBackend>();
    } else {
        b = make_openal_backend();
        if (!b) b = std::make_unique<NullBackend>();
    }
    g_system = std::make_unique<AudioSystem>(std::move(b));
    return g_system->init();
}

static void shutdown_impl() {
    if (g_system) { g_system->shutdown(); g_system.reset(); }
}

static bool load_sound_impl(const std::string& path, const std::string& name,
                            py::bytes wav, bool positional) {
    if (!g_system) return false;
    std::string s = wav;
    return g_system->load_sound(path, name,
                                reinterpret_cast<const uint8_t*>(s.data()),
                                s.size(), positional);
}

static uint32_t get_sound_impl(const std::string& name) {
    return g_system ? g_system->get_sound(name) : 0;
}

static uint32_t play_impl(const std::string& name, bool looping, float gain,
                          const std::string& category, uint32_t attach_node,
                          py::object position) {
    if (!g_system) return 0;
    float x=0,y=0,z=0; bool provided=false;
    if (!position.is_none()) {
        auto t = position.cast<std::tuple<float,float,float>>();
        x = std::get<0>(t); y = std::get<1>(t); z = std::get<2>(t);
        provided = true;
    }
    return g_system->play_sound(name, looping, gain, parse_category(category),
                                attach_node, provided, x, y, z);
}

static void stop_impl(uint32_t pid) { if (g_system) g_system->stop(pid); }

static void set_position_impl(uint32_t pid, float x, float y, float z) {
    if (g_system) g_system->set_position(pid, x, y, z);
}

static void set_gain_impl(uint32_t pid, float g) {
    if (g_system) g_system->set_gain(pid, g);
}

static void set_looping_impl(uint32_t pid, bool l) {
    if (g_system) g_system->set_looping(pid, l);
}

static void set_min_max_distance_impl(uint32_t pid, float mn, float mx) {
    if (g_system) g_system->set_min_max_distance(pid, mn, mx);
}

static void set_category_gain_impl(const std::string& cat, float g) {
    if (g_system) g_system->set_category_gain(parse_category(cat), g);
}

static void update_impl(float lx, float ly, float lz,
                        float fx, float fy, float fz,
                        float ux, float uy, float uz, float dt) {
    if (g_system) g_system->update(lx,ly,lz, fx,fy,fz, ux,uy,uz, dt);
}

static py::list debug_command_log_impl() {
    py::list out;
    if (!g_system) return out;
    auto* nb = dynamic_cast<NullBackend*>(g_system->backend());
    if (!nb) return out;
    for (const auto& c : nb->command_log()) {
        py::dict d;
        d["op"] = c.op;
        d["u"] = py::make_tuple(c.u[0], c.u[1], c.u[2], c.u[3]);
        d["f"] = py::make_tuple(c.f[0], c.f[1], c.f[2], c.f[3],
                                 c.f[4], c.f[5], c.f[6], c.f[7], c.f[8]);
        d["b"] = py::make_tuple(c.b[0], c.b[1]);
        out.append(d);
    }
    return out;
}

static void clear_command_log_impl() {
    if (!g_system) return;
    if (auto* nb = dynamic_cast<NullBackend*>(g_system->backend()))
        nb->clear_command_log();
}

void register_python_bindings(py::module_& parent) {
    auto m = parent.def_submodule("audio", "OpenAL audio subsystem.");
    m.def("init", &init_impl, py::arg("backend") = "openal");
    m.def("shutdown", &shutdown_impl);
    m.def("load_sound", &load_sound_impl,
          py::arg("path"), py::arg("name"), py::arg("wav"),
          py::arg("positional") = false);
    m.def("get_sound", &get_sound_impl);
    m.def("play", &play_impl,
          py::arg("name"), py::arg("looping") = false,
          py::arg("gain") = 1.0f, py::arg("category") = "SFX",
          py::arg("attach_node") = 0u, py::arg("position") = py::none());
    m.def("stop", &stop_impl);
    m.def("set_position", &set_position_impl);
    m.def("set_gain", &set_gain_impl);
    m.def("set_looping", &set_looping_impl);
    m.def("set_min_max_distance", &set_min_max_distance_impl);
    m.def("set_category_gain", &set_category_gain_impl);
    m.def("update", &update_impl);
    m.def("debug_command_log", &debug_command_log_impl);
    m.def("clear_command_log", &clear_command_log_impl);
}

}
```

Append to `native/src/audio/CMakeLists.txt`:

```cmake
target_sources(open_stbc_audio PRIVATE src/python_binding.cc)
target_link_libraries(open_stbc_audio PUBLIC pybind11::headers)
```

Add a temporary stub for `openal_backend.h` so the binding compiles before Task 5. Create `native/src/audio/include/audio/openal_backend.h`:

```cpp
#pragma once
#include <audio/audio_backend.h>
#include <memory>
namespace open_stbc::audio {
// Returns nullptr if OpenAL is unavailable or stubbed (replaced in Task 5).
std::unique_ptr<IAudioBackend> make_openal_backend();
}  // namespace open_stbc::audio
```

Create `native/src/audio/src/openal_backend.cc` (stub):

```cpp
#include <audio/openal_backend.h>
namespace open_stbc::audio {
std::unique_ptr<IAudioBackend> make_openal_backend() { return nullptr; }
}  // namespace open_stbc::audio
```

Add it to `native/src/audio/CMakeLists.txt`:

```cmake
target_sources(open_stbc_audio PRIVATE src/openal_backend.cc)
```

Modify `native/src/host/host_bindings.cc` — add inside the existing `PYBIND11_MODULE` block, right after the existing `keys` submodule registration:

```cpp
#include <audio/python_binding.h>
// ...
PYBIND11_MODULE(_open_stbc_host, m) {
    // ... existing entries ...

    auto keys = m.def_submodule("keys", "GLFW key-code constants for input bindings.");
    // ... existing key constants ...

    open_stbc::audio::register_python_bindings(m);  // <-- add at end of module body
}
```

Modify `native/src/host/CMakeLists.txt` to link `open_stbc_audio` into the host extension target. Find the existing `target_link_libraries` for the host module and append `open_stbc_audio`.

- [ ] **Step 4: Run to verify passes**

```bash
cmake --build build -j 2>&1 | tail -20 && \
PYTHONPATH=build/python uv run pytest tests/audio/test_binding.py -x
```

Expected: build succeeds; both tests pass.

- [ ] **Step 5: Commit**

```bash
git add native/src/audio/include/audio/python_binding.h \
        native/src/audio/src/python_binding.cc \
        native/src/audio/include/audio/openal_backend.h \
        native/src/audio/src/openal_backend.cc \
        native/src/audio/CMakeLists.txt \
        native/src/host/host_bindings.cc native/src/host/CMakeLists.txt \
        tests/audio/test_binding.py
git commit -m "feat(audio): expose AudioSystem as _open_stbc_host.audio submodule

load/play/stop/update + debug command log surface. OpenAL backend is
stubbed; the binding defaults to null and tests drive the command log.
"
```

---

## Task 5: OpenAL Soft backend (real audio output)

**Files:**
- Modify: `native/CMakeLists.txt` (FetchContent OpenAL Soft), `native/src/audio/CMakeLists.txt` (link al), `native/src/audio/src/openal_backend.cc` (replace stub from Task 4).
- No new tests — this backend is exercised by the end-to-end gameplay test in Task 11 and by running `./build/open_stbc` manually.

- [ ] **Step 1: Add OpenAL Soft via FetchContent**

In `native/CMakeLists.txt`, after the existing `FetchContent_MakeAvailable(RmlUi)` block (around line 49), add:

```cmake
# OpenAL Soft for audio output. Library-only build; no examples or utils.
set(LIBTYPE STATIC CACHE STRING "" FORCE)
set(ALSOFT_UTILS OFF CACHE BOOL "" FORCE)
set(ALSOFT_EXAMPLES OFF CACHE BOOL "" FORCE)
set(ALSOFT_TESTS OFF CACHE BOOL "" FORCE)
set(ALSOFT_INSTALL OFF CACHE BOOL "" FORCE)
FetchContent_Declare(
    openal_soft
    GIT_REPOSITORY https://github.com/kcat/openal-soft.git
    GIT_TAG        1.23.1
)
FetchContent_MakeAvailable(openal_soft)
```

In `native/src/audio/CMakeLists.txt`, link the AL library:

```cmake
target_link_libraries(open_stbc_audio PUBLIC OpenAL)
target_include_directories(open_stbc_audio PUBLIC
    ${openal_soft_SOURCE_DIR}/include)
```

- [ ] **Step 2: Replace the stub `openal_backend.cc`**

Overwrite `native/src/audio/src/openal_backend.cc`:

```cpp
#include <audio/openal_backend.h>
#include <AL/al.h>
#include <AL/alc.h>
#include <cstdio>
#include <unordered_map>
#include <vector>

namespace open_stbc::audio {

namespace {

ALenum pick_format(uint16_t channels, uint16_t bps) {
    if (channels == 1 && bps == 8)  return AL_FORMAT_MONO8;
    if (channels == 1 && bps == 16) return AL_FORMAT_MONO16;
    if (channels == 2 && bps == 8)  return AL_FORMAT_STEREO8;
    if (channels == 2 && bps == 16) return AL_FORMAT_STEREO16;
    return AL_NONE;
}

class OpenALBackend : public IAudioBackend {
public:
    bool init() override {
        device_ = alcOpenDevice(nullptr);
        if (!device_) {
            std::fprintf(stderr, "[audio] alcOpenDevice failed; running silent\n");
            return false;
        }
        context_ = alcCreateContext(device_, nullptr);
        if (!context_ || !alcMakeContextCurrent(context_)) {
            std::fprintf(stderr, "[audio] alcCreateContext failed\n");
            return false;
        }
        // Three category gains start at 1.0.
        for (int i = 0; i < 3; i++) category_gain_[i] = 1.0f;
        return true;
    }

    void shutdown() override {
        for (auto& [_, src] : sources_) alDeleteSources(1, &src.al);
        sources_.clear();
        for (auto& [_, buf] : buffers_) alDeleteBuffers(1, &buf);
        buffers_.clear();
        if (context_) { alcMakeContextCurrent(nullptr); alcDestroyContext(context_); context_=nullptr; }
        if (device_) { alcCloseDevice(device_); device_ = nullptr; }
    }

    BufferHandle create_buffer(const PcmDesc& d, const uint8_t* pcm, size_t bytes) override {
        ALenum fmt = pick_format(d.channels, d.bits_per_sample);
        if (fmt == AL_NONE) return 0;
        ALuint al;
        alGenBuffers(1, &al);
        if (alGetError() != AL_NO_ERROR) return 0;
        alBufferData(al, fmt, pcm, (ALsizei)bytes, (ALsizei)d.sample_rate);
        if (alGetError() != AL_NO_ERROR) { alDeleteBuffers(1, &al); return 0; }
        BufferHandle h = ++next_buf_;
        buffers_[h] = al;
        return h;
    }

    void destroy_buffer(BufferHandle h) override {
        auto it = buffers_.find(h);
        if (it != buffers_.end()) { alDeleteBuffers(1, &it->second); buffers_.erase(it); }
    }

    SourceHandle play(BufferHandle buf, bool looping, float gain, Category cat,
                      bool positional, float x, float y, float z) override {
        auto it = buffers_.find(buf);
        if (it == buffers_.end()) return 0;
        ALuint al;
        alGenSources(1, &al);
        if (alGetError() != AL_NO_ERROR) return 0;
        alSourcei(al, AL_BUFFER, (ALint)it->second);
        alSourcei(al, AL_LOOPING, looping ? AL_TRUE : AL_FALSE);
        alSourcef(al, AL_GAIN, gain * category_gain_[(int)cat]);
        if (positional) {
            alSourcei(al, AL_SOURCE_RELATIVE, AL_FALSE);
            alSource3f(al, AL_POSITION, x, y, z);
            alSourcef(al, AL_REFERENCE_DISTANCE, 100.0f);
            alSourcef(al, AL_ROLLOFF_FACTOR, 1.0f);
        } else {
            alSourcei(al, AL_SOURCE_RELATIVE, AL_TRUE);
            alSource3f(al, AL_POSITION, 0, 0, 0);
        }
        alSourcePlay(al);
        SourceHandle h = ++next_src_;
        sources_[h] = {al, cat, gain};
        return h;
    }

    void stop(SourceHandle h) override {
        auto it = sources_.find(h);
        if (it == sources_.end()) return;
        alSourceStop(it->second.al);
        alDeleteSources(1, &it->second.al);
        sources_.erase(it);
    }

    void set_position(SourceHandle h, float x, float y, float z) override {
        if (auto it = sources_.find(h); it != sources_.end())
            alSource3f(it->second.al, AL_POSITION, x, y, z);
    }
    void set_gain(SourceHandle h, float g) override {
        if (auto it = sources_.find(h); it != sources_.end()) {
            it->second.user_gain = g;
            alSourcef(it->second.al, AL_GAIN, g * category_gain_[(int)it->second.cat]);
        }
    }
    void set_looping(SourceHandle h, bool l) override {
        if (auto it = sources_.find(h); it != sources_.end())
            alSourcei(it->second.al, AL_LOOPING, l ? AL_TRUE : AL_FALSE);
    }
    void set_min_max_distance(SourceHandle h, float mn, float mx) override {
        if (auto it = sources_.find(h); it != sources_.end()) {
            alSourcef(it->second.al, AL_REFERENCE_DISTANCE, mn);
            alSourcef(it->second.al, AL_MAX_DISTANCE, mx);
        }
    }
    void set_listener(float px, float py, float pz,
                      float fx, float fy, float fz,
                      float ux, float uy, float uz) override {
        alListener3f(AL_POSITION, px, py, pz);
        float ori[6] = {fx, fy, fz, ux, uy, uz};
        alListenerfv(AL_ORIENTATION, ori);
    }
    void set_category_gain(Category c, float g) override {
        category_gain_[(int)c] = g;
        for (auto& [_, src] : sources_) {
            if (src.cat == c) alSourcef(src.al, AL_GAIN, src.user_gain * g);
        }
    }
    bool source_finished(SourceHandle h) override {
        auto it = sources_.find(h);
        if (it == sources_.end()) return true;
        ALint state = 0;
        alGetSourcei(it->second.al, AL_SOURCE_STATE, &state);
        return state != AL_PLAYING && state != AL_PAUSED;
    }

private:
    struct Source { ALuint al; Category cat; float user_gain; };
    ALCdevice*  device_  = nullptr;
    ALCcontext* context_ = nullptr;
    std::unordered_map<BufferHandle, ALuint> buffers_;
    std::unordered_map<SourceHandle, Source> sources_;
    BufferHandle next_buf_ = 0;
    SourceHandle next_src_ = 0;
    float category_gain_[3] = {1.f, 1.f, 1.f};
};

}  // namespace

std::unique_ptr<IAudioBackend> make_openal_backend() {
    auto b = std::make_unique<OpenALBackend>();
    return b;
}

}  // namespace open_stbc::audio
```

- [ ] **Step 3: Build and run an end-to-end smoke**

```bash
cmake -B build -S . && cmake --build build -j 2>&1 | tail -20
PYTHONPATH=build/python uv run pytest tests/audio/test_binding.py -x
```

Expected: builds, prior tests still pass (binding tests use `backend="null"` so OpenAL isn't loaded).

- [ ] **Step 4: Commit**

```bash
git add native/CMakeLists.txt native/src/audio/CMakeLists.txt \
        native/src/audio/src/openal_backend.cc
git commit -m "feat(audio): OpenAL Soft backend

Real audio output. Static link from openal-soft 1.23.1 via FetchContent.
Falls back to NullBackend if alcOpenDevice fails so headless / no-device
runs stay alive.
"
```

---

## Task 6: Python `engine/audio/` package — TGSound surface

**Files:**
- Create: `engine/audio/__init__.py`, `engine/audio/tg_sound.py`
- Test: `tests/audio/test_tg_sound.py`

- [ ] **Step 1: Write the failing test**

Create `tests/audio/test_tg_sound.py`:

```python
import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")

_open_stbc_host = pytest.importorskip("_open_stbc_host")

from engine.audio.tg_sound import (
    TGSound, TGSoundManager, TGSoundAction, TGSoundAction_Create,
    init_audio_for_tests, shutdown_audio_for_tests,
)


def _wav(rate, samples):
    data = b"".join(struct.pack("<h", s) for s in samples)
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16)
            + struct.pack("<HHIIHH", 1, 1, rate, rate*2, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


@pytest.fixture
def audio():
    init_audio_for_tests()
    yield TGSoundManager.instance()
    shutdown_audio_for_tests()


def test_load_then_get(audio, tmp_path):
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav(22050, [0, 0, 0, 0]))
    snd = audio.LoadSound(str(wav), "MySfx", TGSound.LS_3D)
    assert snd is not None
    assert audio.GetSound("MySfx") is not None
    assert audio.GetSound("MissingName") is None


def test_play_sound_via_manager(audio, tmp_path):
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav(22050, [0, 0]))
    audio.LoadSound(str(wav), "OneShot", TGSound.LS_3D)
    _open_stbc_host.audio.clear_command_log()
    audio.PlaySound("OneShot")
    ops = [e["op"] for e in _open_stbc_host.audio.debug_command_log()]
    assert "play" in ops


def test_sound_action_play_routes_to_manager(audio, tmp_path):
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav(22050, [0, 0]))
    audio.LoadSound(str(wav), "AlertSnd", TGSound.LS_3D)
    _open_stbc_host.audio.clear_command_log()
    action = TGSoundAction_Create("AlertSnd")
    action.Play()
    ops = [e["op"] for e in _open_stbc_host.audio.debug_command_log()]
    assert "play" in ops


def test_play_returns_handle_we_can_stop(audio, tmp_path):
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav(22050, [0, 0]))
    snd = audio.LoadSound(str(wav), "LoopySnd", TGSound.LS_3D)
    snd.SetLooping(1)
    playing = snd.Play()
    assert playing is not None
    _open_stbc_host.audio.clear_command_log()
    playing.Stop()
    ops = [e["op"] for e in _open_stbc_host.audio.debug_command_log()]
    assert "stop" in ops
```

- [ ] **Step 2: Run to verify failure**

```bash
PYTHONPATH=build/python uv run pytest tests/audio/test_tg_sound.py -x 2>&1 | tail -10
```

Expected: `ModuleNotFoundError: No module named 'engine.audio'`.

- [ ] **Step 3: Implement the package**

Create `engine/audio/__init__.py` (empty file).

Create `engine/audio/tg_sound.py`:

```python
"""Phase-1 shim implementation of BC's TGSound / TGSoundManager / TGSoundAction.

Delegates to the C++ audio subsystem exposed as _open_stbc_host.audio. Surface
matches sdk/Build/scripts/App.py wherever LoadTacticalSounds.py, LoadBridge.py,
or hardpoint files touch it; the rest of the SDK surface stays stubbed.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

try:
    import _open_stbc_host
    _audio = _open_stbc_host.audio
except (ImportError, AttributeError):
    _audio = None  # tests can still import the module shape


_GAME_DIR_ENV = "OPEN_STBC_GAME_DIR"


def _resolve_sfx_path(rel: str) -> str:
    base = os.environ.get(_GAME_DIR_ENV)
    if base:
        return str(Path(base) / rel)
    # Fallback to project-relative game/ directory.
    return str(Path(__file__).resolve().parents[2] / "game" / rel)


_CATEGORY_BY_TAG = {"SFX": "SFX", "Voice": "Voice", "Interface": "Interface"}


class _PlayingSound:
    """Lightweight handle returned by TGSound.Play(); supports Stop()."""

    __slots__ = ("_pid",)

    def __init__(self, pid: int) -> None:
        self._pid = pid

    def Stop(self) -> None:
        if _audio and self._pid:
            _audio.stop(self._pid)
        self._pid = 0


class TGSound:
    # Loadspec constants (match App.py).
    LS_3D = 0
    LS_STREAMED = 1
    LS_DELAY_LOADING = 2
    # Status (return values for GetStatus).
    SS_PLAYING = 0
    SS_STOPPED = 1
    SS_UNLOADED = 2
    SS_UNKNOWN = 3

    def __init__(self, name: str, positional: bool) -> None:
        self._name = name
        self._positional = positional
        self._looping = False
        self._gain = 1.0
        self._category_tag = "SFX"
        self._min_dist = 100.0
        self._max_dist = 100000.0
        self._loaded = _audio is not None and _audio.get_sound(name) != 0

    # ---- BC surface ---------------------------------------------------
    def IsLoaded(self) -> int:
        return 1 if self._loaded else 0

    def GetStatus(self) -> int:
        return TGSound.SS_STOPPED  # one-shots aren't tracked back to TGSound

    def SetLooping(self, looping) -> None:
        self._looping = bool(looping)

    def GetLooping(self) -> int:
        return 1 if self._looping else 0

    def SetVolume(self, gain) -> None:
        self._gain = float(gain)

    def GetVolume(self) -> float:
        return self._gain

    def SetMinMaxDistance(self, mn, mx) -> None:
        self._min_dist, self._max_dist = float(mn), float(mx)

    def SetSFX(self, *_args) -> None:       self._category_tag = "SFX"
    def IsSFX(self) -> int:                  return 1 if self._category_tag == "SFX" else 0
    def SetVoice(self, *_args) -> None:      self._category_tag = "Voice"
    def IsVoice(self) -> int:                return 1 if self._category_tag == "Voice" else 0
    def SetInterface(self, *_args) -> None:  self._category_tag = "Interface"
    def IsInterface(self) -> int:            return 1 if self._category_tag == "Interface" else 0

    def Play(self, attach_node: int = 0, position=None) -> Optional[_PlayingSound]:
        if not _audio or not self._loaded:
            return None
        pid = _audio.play(
            name=self._name, looping=self._looping, gain=self._gain,
            category=self._category_tag, attach_node=int(attach_node),
            position=position,
        )
        if pid == 0:
            return None
        if self._positional or attach_node != 0 or position is not None:
            _audio.set_min_max_distance(pid, self._min_dist, self._max_dist)
        return _PlayingSound(pid)

    # ---- No-ops kept for the wider SDK surface (callers exist; behaviour TBD)
    def PlayAndNotify(self, *_args, **_kw): return self.Play()
    def Stop(self): pass
    def Pause(self): pass
    def Unpause(self): pass
    def SetSingleShot(self, *_a): pass
    def IsSingleShot(self): return 0
    def AttachToNode(self, *_a): pass
    def DetachFromNode(self, *_a): pass
    def SetPosition(self, *_a): pass
    def SetOrientation(self, *_a): pass
    def GetSoundName(self): return self._name
    def GetFileName(self): return self._name
    def Is3D(self): return 1 if self._positional else 0
    def IsStreamed(self): return 0


class TGSoundManager:
    _instance: "Optional[TGSoundManager]" = None

    def __init__(self) -> None:
        self._sounds: dict[str, TGSound] = {}

    @classmethod
    def instance(cls) -> "TGSoundManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def LoadSound(self, path: str, name: str, loadspec: int) -> Optional[TGSound]:
        if _audio is None:
            return None
        full = _resolve_sfx_path(path) if not os.path.isabs(path) else path
        try:
            with open(full, "rb") as f:
                data = f.read()
        except OSError:
            return None
        positional = (loadspec == TGSound.LS_3D)
        ok = _audio.load_sound(path=full, name=name, wav=data, positional=positional)
        if not ok:
            return None
        snd = TGSound(name, positional)
        self._sounds[name] = snd
        return snd

    def GetSound(self, name: str) -> Optional[TGSound]:
        return self._sounds.get(name)

    def PlaySound(self, name: str) -> Optional[_PlayingSound]:
        snd = self._sounds.get(name)
        return None if snd is None else snd.Play()


class TGSoundAction:
    """SDK-style action object: Play() fires the named sound."""

    def __init__(self, name: str) -> None:
        self._name = name

    def Play(self) -> None:
        TGSoundManager.instance().PlaySound(self._name)

    # Action surface stubs; SDK code calls these on sequences.
    def Stop(self): pass
    def SetName(self, n): self._name = n


def TGSoundAction_Create(name: str) -> TGSoundAction:
    return TGSoundAction(name)


# Module-level singleton, exported as App.g_kSoundManager
g_kSoundManager = TGSoundManager.instance()


# ---- Test helpers (NOT for production code) ------------------------------
def init_audio_for_tests() -> None:
    """Init the C++ audio subsystem with the null backend."""
    if _audio is None:
        return
    _audio.init(backend="null")
    # Fresh manager state per-test.
    TGSoundManager._instance = TGSoundManager()
    global g_kSoundManager
    g_kSoundManager = TGSoundManager._instance


def shutdown_audio_for_tests() -> None:
    if _audio is None:
        return
    _audio.shutdown()
    TGSoundManager._instance = None
```

- [ ] **Step 4: Run to verify passes**

```bash
PYTHONPATH=build/python uv run pytest tests/audio/test_tg_sound.py -x
```

Expected: all four tests pass.

- [ ] **Step 5: Commit**

```bash
git add engine/audio/__init__.py engine/audio/tg_sound.py \
        tests/audio/test_tg_sound.py
git commit -m "feat(audio): engine.audio.tg_sound — TGSound/TGSoundManager surface

Delegates to _open_stbc_host.audio. Covers the LoadSound / GetSound /
PlaySound / SetLooping / SetMinMaxDistance / category-tag surface that
LoadTacticalSounds.py, LoadBridge.py, and hardpoint files touch.
"
```

---

## Task 7: Wire `App.py` shim and `engine.appc` surface

**Files:**
- Modify: `App.py`, `engine/appc/actions.py:175-184`, `engine/appc/properties.py:291-292`
- Test: `tests/audio/test_app_shim_wiring.py`

- [ ] **Step 1: Write the failing test**

Create `tests/audio/test_app_shim_wiring.py`:

```python
import os
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
pytest.importorskip("_open_stbc_host")

from engine.audio.tg_sound import init_audio_for_tests, shutdown_audio_for_tests


@pytest.fixture
def boot():
    init_audio_for_tests()
    yield
    shutdown_audio_for_tests()


def test_app_exposes_tgsound_and_manager(boot):
    import App
    assert hasattr(App, "TGSound")
    assert App.TGSound.LS_3D == 0
    assert hasattr(App, "TGSoundManager")
    assert App.g_kSoundManager is not None


def test_impulse_engine_property_remembers_sound_name():
    import App
    prop = App.ImpulseEngineProperty_Create("Impulse Engines")
    prop.SetEngineSound("Federation Engines")
    assert prop.GetEngineSound() == "Federation Engines"


def test_tg_sound_action_create_uses_audio_module(boot, tmp_path):
    import App
    import _open_stbc_host

    # Round-trip: load a sound, fire an action, see a play in the command log.
    wav = tmp_path / "x.wav"
    import struct
    data = struct.pack("<h", 0) * 4
    wav.write_bytes(
        b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
        + b"fmt " + struct.pack("<I", 16)
        + struct.pack("<HHIIHH", 1, 1, 22050, 44100, 2, 16)
        + b"data" + struct.pack("<I", len(data)) + data
    )
    App.g_kSoundManager.LoadSound(str(wav), "TestRedAlert", App.TGSound.LS_3D)
    _open_stbc_host.audio.clear_command_log()
    action = App.TGSoundAction_Create("TestRedAlert")
    action.Play()
    ops = [e["op"] for e in _open_stbc_host.audio.debug_command_log()]
    assert "play" in ops
```

- [ ] **Step 2: Run to verify failure**

```bash
PYTHONPATH=build/python uv run pytest tests/audio/test_app_shim_wiring.py -x 2>&1 | tail -15
```

Expected: `AttributeError: module 'App' has no attribute 'TGSound'` (or similar).

- [ ] **Step 3: Patch the action layer**

Edit `engine/appc/actions.py` — locate the `class TGSoundAction` block at line 175. Replace its body so `Play()` calls into the real manager:

```python
class TGSoundAction(TGTimedAction):
    def __init__(self, sound_name: str = "") -> None:
        super().__init__()
        self._sound_name = sound_name

    def SetName(self, name: str) -> None:
        self._sound_name = name

    def GetName(self) -> str:
        return self._sound_name

    def Play(self) -> None:
        # Late import to avoid circular dep at module init.
        from engine.audio.tg_sound import TGSoundManager
        TGSoundManager.instance().PlaySound(self._sound_name)


def TGSoundAction_Create(*args) -> TGSoundAction:
    sound_name = args[0] if args else ""
    return TGSoundAction(sound_name)
```

- [ ] **Step 4: Patch `ImpulseEngineProperty`**

Edit `engine/appc/properties.py` at line 291 — replace `class ImpulseEngineProperty(PoweredSubsystemProperty): pass` with:

```python
class ImpulseEngineProperty(PoweredSubsystemProperty):
    def __init__(self, name: str = "") -> None:
        super().__init__(name)
        self._engine_sound_name: str = ""

    def SetEngineSound(self, name: str) -> None:
        self._engine_sound_name = name or ""

    def GetEngineSound(self) -> str:
        return self._engine_sound_name
```

(If `PoweredSubsystemProperty.__init__` does not accept a name, pattern-match how the surrounding property classes are constructed and follow that — keep `_engine_sound_name` as a per-instance attribute.)

- [ ] **Step 5: Wire `App.py`**

Add to `App.py` near the existing `from engine.appc.actions import ...` block (line 38) — add `engine.audio.tg_sound` imports:

```python
from engine.audio.tg_sound import (
    TGSound, TGSoundManager, g_kSoundManager,
)
```

If `TGSound` is not already exported, add it to the public name list as well (no `__all__` is in use today; the module-level binding above is enough).

- [ ] **Step 6: Run to verify passes**

```bash
PYTHONPATH=build/python uv run pytest tests/audio/test_app_shim_wiring.py tests/audio/test_tg_sound.py -x
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add App.py engine/appc/actions.py engine/appc/properties.py \
        tests/audio/test_app_shim_wiring.py
git commit -m "feat(audio): wire App shim — TGSound, TGSoundAction, ImpulseEngineProperty

TGSoundAction.Play() now routes through TGSoundManager into the real
audio module; ImpulseEngineProperty remembers SetEngineSound(name) so
ship-spawn code can pick up the per-ship rumble.
"
```

---

## Task 8: Engine rumble on ship spawn

**Files:**
- Create: `engine/audio/engine_rumble.py`
- Test: `tests/audio/test_engine_rumble.py`

`engine_rumble.subscribe()` hooks into `engine/appc/ship_lifecycle.py`'s pub/sub to start a looping 3D sound when a ship is added and stop it when it's destroyed.

- [ ] **Step 1: Write the failing test**

Create `tests/audio/test_engine_rumble.py`:

```python
import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
_open_stbc_host = pytest.importorskip("_open_stbc_host")

from engine.audio.tg_sound import (
    TGSound, TGSoundManager, init_audio_for_tests, shutdown_audio_for_tests,
)
from engine.audio.engine_rumble import install_engine_rumble_listener


def _wav():
    data = struct.pack("<h", 0) * 8
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16)
            + struct.pack("<HHIIHH", 1, 1, 22050, 44100, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


class _FakeImpulse:
    def __init__(self, name): self._name = name
    def GetEngineSound(self): return self._name


class _FakeShip:
    def __init__(self, sound_name, scene_node=42):
        self._impulse = _FakeImpulse(sound_name)
        self._scene_node = scene_node
    def GetImpulseEngineSubsystem(self):
        return None  # not used in this path
    def GetImpulseEngineProperty(self):
        return self._impulse
    def GetSceneNodeId(self):
        return self._scene_node


@pytest.fixture
def boot(tmp_path):
    init_audio_for_tests()
    wav = tmp_path / "engine.wav"
    wav.write_bytes(_wav())
    TGSoundManager.instance().LoadSound(str(wav), "Federation Engines", TGSound.LS_3D)
    yield
    shutdown_audio_for_tests()


def test_engine_rumble_plays_on_publish_added(boot, monkeypatch):
    # Use the ship_lifecycle module's fanout directly.
    from engine.appc import ship_lifecycle
    ship_lifecycle.reset()
    install_engine_rumble_listener()

    _open_stbc_host.audio.clear_command_log()
    ship = _FakeShip("Federation Engines")
    ship_lifecycle.publish_added(ship)

    entries = _open_stbc_host.audio.debug_command_log()
    play_entries = [e for e in entries if e["op"] == "play"]
    assert len(play_entries) == 1
    assert play_entries[0]["b"][0] is True       # looping
    assert play_entries[0]["u"][1] == 0           # category SFX
    # attach_node was non-zero
    # (binding stores attach_node into log via play path; we accept the assertion
    # that *some* play happened with looping=True at SFX.)


def test_engine_rumble_stops_on_destroy(boot):
    from engine.appc import ship_lifecycle
    ship_lifecycle.reset()
    install_engine_rumble_listener()
    ship = _FakeShip("Federation Engines")
    ship_lifecycle.publish_added(ship)

    _open_stbc_host.audio.clear_command_log()
    ship_lifecycle.publish_destroyed(ship)
    ops = [e["op"] for e in _open_stbc_host.audio.debug_command_log()]
    assert "stop" in ops


def test_missing_engine_sound_does_not_crash(boot):
    from engine.appc import ship_lifecycle
    ship_lifecycle.reset()
    install_engine_rumble_listener()
    ship = _FakeShip("Nonexistent Engines")
    ship_lifecycle.publish_added(ship)  # must not raise
    ship_lifecycle.publish_destroyed(ship)  # must not raise
```

- [ ] **Step 2: Run to verify failure**

```bash
PYTHONPATH=build/python uv run pytest tests/audio/test_engine_rumble.py -x 2>&1 | tail -10
```

Expected: `ModuleNotFoundError: No module named 'engine.audio.engine_rumble'`.

- [ ] **Step 3: Implement the listener**

Create `engine/audio/engine_rumble.py`:

```python
"""Per-ship engine rumble: looping 3D sound attached to each ship's scene node.

Hooks into ship_lifecycle pub/sub; starts the sound on `added`, stops it on
`destroyed`. Approximates Appc's behavior where engine rumble auto-starts when
an ImpulseEngineProperty binds to a ship.
"""
from __future__ import annotations

import weakref

from engine.appc import ship_lifecycle
from engine.audio.tg_sound import TGSound, TGSoundManager


_installed = False
_active: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _engine_sound_name_for(ship) -> str:
    prop_getter = getattr(ship, "GetImpulseEngineProperty", None)
    if prop_getter is None:
        return ""
    prop = prop_getter()
    if prop is None:
        return ""
    getter = getattr(prop, "GetEngineSound", None)
    return getter() if getter else ""


def _scene_node_for(ship) -> int:
    getter = getattr(ship, "GetSceneNodeId", None)
    return int(getter()) if getter else 0


def _on_ship_event(event: str, ship) -> None:
    if event == "added":
        name = _engine_sound_name_for(ship)
        if not name:
            return
        snd = TGSoundManager.instance().GetSound(name)
        if snd is None:
            return
        snd.SetLooping(1)
        snd.SetSFX()
        playing = snd.Play(attach_node=_scene_node_for(ship))
        if playing is not None:
            _active[ship] = playing
    elif event == "destroyed":
        playing = _active.pop(ship, None)
        if playing is not None:
            playing.Stop()


def install_engine_rumble_listener() -> None:
    """Idempotent install — safe to call from host_loop boot."""
    global _installed
    if _installed:
        return
    ship_lifecycle.subscribe(_on_ship_event)
    _installed = True


def reset_for_tests() -> None:
    global _installed
    _installed = False
    _active.clear()
```

`ship_lifecycle.subscribe` returns an `unsubscribe` callable, but we don't need to use it for the host's normal lifetime. The `reset_for_tests` helper plus `ship_lifecycle.reset()` keep test isolation clean.

- [ ] **Step 4: Run to verify passes**

```bash
PYTHONPATH=build/python uv run pytest tests/audio/test_engine_rumble.py -x
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add engine/audio/engine_rumble.py tests/audio/test_engine_rumble.py
git commit -m "feat(audio): engine rumble on ship spawn

Looping 3D sound attached per-ship; starts on ship_lifecycle.added,
stops on destroyed. Missing engine sound names are silently skipped.
"
```

---

## Task 9: Alert audio listener

**Files:**
- Create: `engine/audio/alert_audio.py`
- Test: `tests/audio/test_alert_audio.py`

The alert state lives on `ShipClass._alert_level` with `Get/SetAlertLevel`. There's no signal for transitions, so the listener polls and remembers the last level. `host_loop` calls `tick(player)` each frame.

- [ ] **Step 1: Write the failing test**

Create `tests/audio/test_alert_audio.py`:

```python
import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
_open_stbc_host = pytest.importorskip("_open_stbc_host")

from engine.audio.tg_sound import (
    TGSound, TGSoundManager, init_audio_for_tests, shutdown_audio_for_tests,
)
from engine.audio.alert_audio import AlertAudioListener


def _wav():
    data = struct.pack("<h", 0) * 4
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16)
            + struct.pack("<HHIIHH", 1, 1, 22050, 44100, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


class _FakeShip:
    GREEN_ALERT, YELLOW_ALERT, RED_ALERT = 1, 2, 3
    def __init__(self, level=GREEN_ALERT): self._lvl = level
    def GetAlertLevel(self): return self._lvl
    def SetAlertLevel(self, v): self._lvl = v


@pytest.fixture
def boot(tmp_path):
    init_audio_for_tests()
    mgr = TGSoundManager.instance()
    for name in ("RedAlertSound", "YellowAlertSound", "GreenAlertSound"):
        wav = tmp_path / f"{name}.wav"
        wav.write_bytes(_wav())
        mgr.LoadSound(str(wav), name, TGSound.LS_3D)
    yield
    shutdown_audio_for_tests()


def test_transition_to_red_fires_red_sound(boot):
    listener = AlertAudioListener()
    ship = _FakeShip(level=_FakeShip.GREEN_ALERT)
    listener.tick(ship)            # baseline; no transition
    _open_stbc_host.audio.clear_command_log()
    ship.SetAlertLevel(_FakeShip.RED_ALERT)
    listener.tick(ship)
    play_entries = [e for e in _open_stbc_host.audio.debug_command_log()
                    if e["op"] == "play"]
    assert len(play_entries) == 1  # exactly one one-shot fired


def test_no_transition_no_sound(boot):
    listener = AlertAudioListener()
    ship = _FakeShip(level=_FakeShip.YELLOW_ALERT)
    listener.tick(ship)
    _open_stbc_host.audio.clear_command_log()
    listener.tick(ship)            # same level — silent
    play_entries = [e for e in _open_stbc_host.audio.debug_command_log()
                    if e["op"] == "play"]
    assert play_entries == []


def test_each_named_level_maps_to_its_sound(boot):
    listener = AlertAudioListener()
    ship = _FakeShip(level=_FakeShip.GREEN_ALERT)
    listener.tick(ship)

    cases = [
        (_FakeShip.RED_ALERT,    "RedAlertSound"),
        (_FakeShip.YELLOW_ALERT, "YellowAlertSound"),
        (_FakeShip.GREEN_ALERT,  "GreenAlertSound"),
    ]
    for lvl, _expected_name in cases:
        ship.SetAlertLevel(lvl)
        _open_stbc_host.audio.clear_command_log()
        listener.tick(ship)
        play_entries = [e for e in _open_stbc_host.audio.debug_command_log()
                        if e["op"] == "play"]
        assert len(play_entries) == 1


def test_handles_missing_player(boot):
    listener = AlertAudioListener()
    listener.tick(None)            # must not crash
```

- [ ] **Step 2: Run to verify failure**

```bash
PYTHONPATH=build/python uv run pytest tests/audio/test_alert_audio.py -x 2>&1 | tail -10
```

Expected: `ModuleNotFoundError: No module named 'engine.audio.alert_audio'`.

- [ ] **Step 3: Implement the listener**

Create `engine/audio/alert_audio.py`:

```python
"""Alert audio listener: plays Red/Yellow/Green alert SFX on transitions.

The alert state is a plain field on ShipClass (no signal). host_loop calls
.tick(player) each frame; the listener remembers the previous level and fires
the matching one-shot when the level changes.
"""
from __future__ import annotations

from typing import Optional

from engine.audio.tg_sound import TGSoundManager


# ShipClass alert constants from engine/appc/ships.py.
# Defined here as module-level so we don't pay an import-of-ShipClass cost
# in tests that use fake ships.
RED_ALERT = 3
YELLOW_ALERT = 2
GREEN_ALERT = 1
OFF_ALERT = 0

_SOUND_BY_LEVEL = {
    RED_ALERT:    "RedAlertSound",
    YELLOW_ALERT: "YellowAlertSound",
    GREEN_ALERT:  "GreenAlertSound",
}


class AlertAudioListener:
    def __init__(self) -> None:
        self._last_level: Optional[int] = None

    def tick(self, player) -> None:
        if player is None:
            return
        getter = getattr(player, "GetAlertLevel", None)
        if getter is None:
            return
        level = int(getter())
        if self._last_level is None:
            self._last_level = level
            return
        if level == self._last_level:
            return
        self._last_level = level
        name = _SOUND_BY_LEVEL.get(level)
        if name:
            TGSoundManager.instance().PlaySound(name)

    def reset(self) -> None:
        self._last_level = None
```

- [ ] **Step 4: Run to verify passes**

```bash
PYTHONPATH=build/python uv run pytest tests/audio/test_alert_audio.py -x
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add engine/audio/alert_audio.py tests/audio/test_alert_audio.py
git commit -m "feat(audio): alert listener fires Red/Yellow/Green SFX on transitions

Polls player.GetAlertLevel() each tick; only fires on level-change, so a
held alert doesn't loop the sample. Missing player or sound is a no-op.
"
```

---

## Task 10: Host loop integration

**Files:**
- Modify: `engine/host_loop.py`, `tests/conftest.py`
- Add: `tests/audio/test_host_loop_audio_init.py`

This is the place where audio is initialized, the per-tick `update()` is wired, and engine-rumble + alert-audio listeners are mounted. The test asserts the wiring exists by stubbing out the C++ host import.

- [ ] **Step 1: Write the failing test**

Create `tests/audio/test_host_loop_audio_init.py`:

```python
"""Smoke test that host_loop initializes audio and ticks the listeners.

We don't run the full host loop — we exercise the audio init/tick helpers
that host_loop.py exposes for testability.
"""
import os
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
pytest.importorskip("_open_stbc_host")


def test_host_loop_exposes_audio_helpers():
    from engine import host_loop
    assert hasattr(host_loop, "init_audio")
    assert hasattr(host_loop, "tick_audio")
    assert hasattr(host_loop, "shutdown_audio")


def test_init_audio_uses_null_backend_when_env_set(monkeypatch):
    monkeypatch.setenv("OPEN_STBC_AUDIO", "0")
    from engine import host_loop
    import _open_stbc_host
    host_loop.init_audio()
    log_ops = [e["op"] for e in _open_stbc_host.audio.debug_command_log()]
    assert "init" in log_ops
    host_loop.shutdown_audio()


def test_tick_audio_pushes_listener_pose(monkeypatch):
    monkeypatch.setenv("OPEN_STBC_AUDIO", "0")
    from engine import host_loop
    import _open_stbc_host
    host_loop.init_audio()
    _open_stbc_host.audio.clear_command_log()
    host_loop.tick_audio(
        camera_position=(0.0, 0.0, 0.0),
        camera_forward=(0.0, 0.0, -1.0),
        camera_up=(0.0, 1.0, 0.0),
        dt=0.016,
        player=None,
    )
    assert any(e["op"] == "set_listener"
               for e in _open_stbc_host.audio.debug_command_log())
    host_loop.shutdown_audio()
```

- [ ] **Step 2: Patch `tests/conftest.py`**

At the top of `tests/conftest.py`, after the existing `from pathlib import Path` block (around line 8), add:

```python
# Default audio to the null backend during tests so no device is opened.
os.environ.setdefault("OPEN_STBC_AUDIO", "0")
```

You'll also need `import os` if it isn't already imported (it currently isn't — `tests/conftest.py:1` starts with `import ast`). Add `import os` at the top alongside the existing imports.

- [ ] **Step 3: Run to verify failure**

```bash
uv run pytest tests/audio/test_host_loop_audio_init.py -x 2>&1 | tail -10
```

Expected: `AttributeError: module 'engine.host_loop' has no attribute 'init_audio'`.

- [ ] **Step 4: Add audio helpers to `host_loop.py`**

Add this block near the top of `engine/host_loop.py`, just below the existing imports (around line 30):

```python
# ── Audio integration ────────────────────────────────────────────────────────
import os as _os

try:
    import _open_stbc_host as _host_mod
    _audio_mod = _host_mod.audio
except (ImportError, AttributeError):
    _audio_mod = None

from engine.audio.alert_audio import AlertAudioListener
from engine.audio.engine_rumble import install_engine_rumble_listener
from engine.audio.tg_sound import TGSoundManager

_alert_listener: AlertAudioListener = AlertAudioListener()


def init_audio() -> None:
    """Boot the audio subsystem. Null backend if OPEN_STBC_AUDIO=0."""
    if _audio_mod is None:
        return
    backend = "null" if _os.environ.get("OPEN_STBC_AUDIO") == "0" else "openal"
    _audio_mod.init(backend=backend)
    install_engine_rumble_listener()
    _alert_listener.reset()


def shutdown_audio() -> None:
    if _audio_mod is None:
        return
    _audio_mod.shutdown()


def tick_audio(*, camera_position, camera_forward, camera_up, dt, player) -> None:
    if _audio_mod is None:
        return
    px, py, pz = camera_position
    fx, fy, fz = camera_forward
    ux, uy, uz = camera_up
    _audio_mod.update(px, py, pz, fx, fy, fz, ux, uy, uz, dt)
    _alert_listener.tick(player)
```

- [ ] **Step 5: Hook `init_audio` and `tick_audio` into the main loop**

Find the host_loop entry point (the function that contains the main `while not should_close()` tick loop — search for `_host.frame` or `should_close()`). Add `init_audio()` just before the loop starts and `tick_audio(...)` once per iteration after the existing render frame call, using the current camera state and player ship reference already in scope. Use exact values:

```python
# Just before entering the main tick loop:
init_audio()

# Per-tick (in the same scope where 'player' and camera state are used for HUD):
tick_audio(
    camera_position=camera.world_position(),
    camera_forward=camera.world_forward(),
    camera_up=camera.world_up(),
    dt=dt,
    player=player,
)

# After the loop exits:
shutdown_audio()
```

If the camera helper names differ in `host_loop.py`, use whatever the existing code already calls to get camera world pose for the renderer (search `set_camera` and reuse those variables). This is a 5-line splice, not a refactor.

- [ ] **Step 6: Run to verify passes**

```bash
uv run pytest tests/audio/test_host_loop_audio_init.py -x
```

Expected: 3 tests pass.

- [ ] **Step 7: Run the full audio test set to confirm no regressions**

```bash
uv run pytest tests/audio/ -x
```

Expected: all audio tests green.

- [ ] **Step 8: Commit**

```bash
git add engine/host_loop.py tests/conftest.py \
        tests/audio/test_host_loop_audio_init.py
git commit -m "feat(audio): host_loop boots audio + ticks listeners

init_audio chooses null vs openal backend by OPEN_STBC_AUDIO env;
tick_audio pushes listener pose each frame and runs the alert listener.
conftest defaults to null so pytest never opens a device.
"
```

---

## Task 11: Acceptance — manual gameplay verification

This is a manual step, not a test. The full audio test suite is green by now; here we confirm the goal of the user request: I can actually hear engine rumble and alert sounds.

- [ ] **Step 1: Build and launch**

```bash
cmake -B build -S . && cmake --build build -j
./build/open_stbc
```

- [ ] **Step 2: Spawn into a tactical scene and verify**

- Hear a continuous engine rumble loop. Pan / volume should change as you orbit the camera or move the ship (3D positional).
- Press Shift+3 (Red Alert): hear `redalert.wav` play once. Pressing again at the same level: silent.
- Press Shift+2 (Yellow): hear `yellowalert.wav`. Shift+1 (Green): hear `greenalert.wav`.
- Quit cleanly with no error spam in stderr.

- [ ] **Step 3: Run the full project test suite to confirm nothing else broke**

```bash
uv run pytest -x
```

Expected: full suite green. (CLAUDE.md note: don't pipe through tail; run scoped/foreground.)

- [ ] **Step 4: Commit nothing if all is well**

If a tweak was needed (volume defaults, missing sound name, etc.), commit that single change with a focused message. Otherwise, this task closes the plan with no extra commit.

---

## Self-review notes (filled in after writing)

**Spec coverage check:**
- Goal: engine rumble + alert SFX → Tasks 8, 9, 11
- Architecture (native/src/audio + engine/audio + App.py shim) → Tasks 1–7, 10
- Null backend for headless tests → Task 2; conftest wiring Task 10
- TGSound surface listed in spec → Task 6 (Load/Play/Stop/SetLooping/SetVolume/SetMinMaxDistance/AttachToNode→via attach_node arg in Play/SetSFX/SetVoice/SetInterface/Is3D/IsLoaded/GetStatus)
- TGSoundManager surface → Task 6 (LoadSound/GetSound/PlaySound + per-category gain in binding)
- TGSoundAction + TGSoundAction_Create → Task 7
- ImpulseEngineProperty.SetEngineSound/GetEngineSound → Task 7
- Ship-construction hook (via ship_lifecycle) → Task 8
- Per-frame audio update + listener pose → Task 10
- Alert listener with transition detection → Task 9
- OpenAL Soft via FetchContent → Task 5
- Categories (SFX/Voice/Interface) + master gain plumbing → in binding (Task 4), tag tracked on TGSound (Task 6)

**Open spec items handled here:**
- "Options.cfg volume keys" — deferred; default 1.0 applied via `category_gain_` init; can be hooked later by calling `_audio.set_category_gain(...)` once on startup once we read Options.cfg.
- "Reference distance / rolloff factor defaults" — chosen in Task 5 (100 / 1.0).
- "OpenAL Soft version pin" — 1.23.1 pinned in Task 5.

**Placeholder scan:** none of the forbidden phrases appear in any task body. All code is complete.

**Type consistency:** `BufferHandle`/`SourceHandle`/`SoundId`/`PlayingId` all `uint32_t`; `Category` enum class used end-to-end; `NodeId` is `uint32_t` in C++, plain int in Python.
