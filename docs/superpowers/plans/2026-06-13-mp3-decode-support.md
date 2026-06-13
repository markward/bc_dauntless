# MP3 Decode Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add MP3 decoding to the native audio backend so MP3 game audio (the bridge-crew voice files, and everything else) loads and plays — unblocking crew voice with no crew-side changes.

**Architecture:** Vendor `dr_mp3` (single-header, public domain) like the existing `stb`. Add a `decode_mp3` that fills the existing `WavData` PCM struct. Dispatch in `AudioSystem::load_sound` by content sniff: `RIFF`+`WAVE` → `decode_wav` (unchanged), else → `decode_mp3`. Same downstream `create_buffer` path.

**Tech Stack:** C++20, CMake, gtest (native test harness), `dr_mp3` (dr_libs), OpenAL backend.

**Spec:** `docs/superpowers/specs/2026-06-13-mp3-decode-support-design.md`

**Branch:** `feat/audio-mp3-decode` (already created, stacked on `feat/bridge-crew-population`).

**Constraints:**
- This is native-only; do NOT run the Python pytest suite.
- New source files + CMake edits require a **reconfigure**: `cmake -B build -S .` before `cmake --build`. (Memory: CMake doesn't pick up new files/sources on a plain `--build`.)
- Build/run only the focused target `audio_tests` (not the whole renderer/CEF) to keep cycles short.
- The `decode_mp3` **success** path is verified by the live build (real game MP3s); CI unit tests cover vendoring, dispatch, WAV-regression, and the MP3-failure path deterministically (no committed MP3 fixture — game MP3s are copyrighted and no encoder is available to synthesize one).

---

### Task 1: Vendor `dr_mp3`

**Files:**
- Create: `native/third_party/dr_libs/dr_mp3.h` (fetched)
- Create: `native/third_party/dr_libs/CMakeLists.txt`
- Create: `native/third_party/dr_libs/LICENSE`
- Create: `native/third_party/dr_libs/UPSTREAM_VERSION`
- Modify: `native/CMakeLists.txt` (add `add_subdirectory(third_party/dr_libs)` next to the other `third_party` lines, ~line 18-20)

- [ ] **Step 1: Fetch the header and record the upstream commit**

```bash
cd /Users/mward/Documents/Projects/bc_dauntless
mkdir -p native/third_party/dr_libs
# Pin to the current master commit for reproducibility.
SHA=$(curl -s -m 20 "https://api.github.com/repos/mackron/dr_libs/commits/master" | grep -m1 '"sha"' | cut -d'"' -f4)
curl -s -m 60 -o native/third_party/dr_libs/dr_mp3.h \
  "https://raw.githubusercontent.com/mackron/dr_libs/${SHA}/dr_mp3.h"
printf 'mackron/dr_libs dr_mp3.h @ %s\nhttps://github.com/mackron/dr_libs\n' "$SHA" \
  > native/third_party/dr_libs/UPSTREAM_VERSION
# Sanity: header is non-trivial and defines the API.
test -s native/third_party/dr_libs/dr_mp3.h && \
  grep -q "drmp3_init_memory" native/third_party/dr_libs/dr_mp3.h && echo "fetch OK"
```
Expected: `fetch OK`. If the fetch fails (no network), STOP and report BLOCKED — the header must be vendored by hand.

- [ ] **Step 2: Extract the license**

`dr_mp3.h` ends with a dual public-domain / MIT-0 license block. Copy that block into `native/third_party/dr_libs/LICENSE`:

```bash
cd /Users/mward/Documents/Projects/bc_dauntless
# The license is the trailing block after the final "LICENSE" banner in the header.
awk '/^This software is available as a choice of the following licenses/{f=1} f' \
  native/third_party/dr_libs/dr_mp3.h > native/third_party/dr_libs/LICENSE
test -s native/third_party/dr_libs/LICENSE && echo "license OK"
```
Expected: `license OK`. If the `awk` match is empty (upstream reworded the banner), instead copy the entire trailing comment block containing the words "public domain" and "MIT No Attribution" into `LICENSE` manually.

- [ ] **Step 3: Add the CMake interface target (mirror `stb`)**

Create `native/third_party/dr_libs/CMakeLists.txt`:

```cmake
add_library(dr_mp3 INTERFACE)
target_include_directories(dr_mp3 INTERFACE ${CMAKE_CURRENT_SOURCE_DIR})
```

- [ ] **Step 4: Register the subdirectory**

In `native/CMakeLists.txt`, next to the existing `add_subdirectory(third_party/stb)` (~line 18), add:

```cmake
add_subdirectory(third_party/dr_libs)
```

- [ ] **Step 5: Reconfigure to verify it wires cleanly**

Run: `cmake -B build -S . 2>&1 | tail -5`
Expected: configures without error (no message about `dr_libs`/`dr_mp3` being unknown).

- [ ] **Step 6: Commit**

```bash
git add native/third_party/dr_libs native/CMakeLists.txt
git commit -m "build(audio): vendor dr_mp3 (dr_libs, public domain)"
```

---

### Task 2: `decode_mp3`

**Files:**
- Create: `native/src/audio/include/audio/mp3.h`
- Create: `native/src/audio/src/mp3.cc`
- Modify: `native/src/audio/CMakeLists.txt` (add `src/mp3.cc`; link `dr_mp3`)
- Test: `native/tests/audio/mp3_test.cc` (create) + `native/tests/audio/CMakeLists.txt` (add it)

- [ ] **Step 1: Write the failing test**

Create `native/tests/audio/mp3_test.cc`:

```cpp
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
```

Add `mp3_test.cc` to `native/tests/audio/CMakeLists.txt`:

```cmake
add_executable(audio_tests
    wav_test.cc
    null_backend_test.cc
    audio_system_test.cc
    mp3_test.cc
)
```

- [ ] **Step 2: Run to verify it fails (won't compile — `mp3.h` missing)**

Run: `cmake -B build -S . >/dev/null 2>&1 && cmake --build build --target audio_tests 2>&1 | tail -15`
Expected: FAIL — `fatal error: 'audio/mp3.h' file not found`.

- [ ] **Step 3: Create `mp3.h`**

Create `native/src/audio/include/audio/mp3.h`:

```cpp
#pragma once
#include <cstddef>
#include <cstdint>
#include <audio/wav.h>  // WavData

namespace dauntless::audio {

// Decodes a whole MP3 (in memory) to interleaved int16 PCM, filling `out`.
// Returns true on success; false on init/decode failure or empty output
// (caller treats false as "unloadable", same as a non-WAV decode_wav miss).
bool decode_mp3(const uint8_t* bytes, size_t len, WavData& out);

}  // namespace dauntless::audio
```

- [ ] **Step 4: Create `mp3.cc`**

Create `native/src/audio/src/mp3.cc`:

```cpp
#include <audio/mp3.h>

#define DR_MP3_IMPLEMENTATION
#include "dr_mp3.h"

namespace dauntless::audio {

bool decode_mp3(const uint8_t* bytes, size_t len, WavData& out) {
    if (bytes == nullptr || len == 0) return false;

    drmp3 mp3;
    if (!drmp3_init_memory(&mp3, bytes, len, nullptr)) return false;

    const drmp3_uint64 total_frames = drmp3_get_pcm_frame_count(&mp3);
    if (total_frames == 0) { drmp3_uninit(&mp3); return false; }

    const drmp3_uint32 channels = mp3.channels;
    std::vector<int16_t> samples(static_cast<size_t>(total_frames) * channels);
    const drmp3_uint64 read =
        drmp3_read_pcm_frames_s16(&mp3, total_frames, samples.data());
    const drmp3_uint32 sample_rate = mp3.sampleRate;
    drmp3_uninit(&mp3);

    if (read == 0) return false;

    out.channels = static_cast<uint16_t>(channels);
    out.bits_per_sample = 16;
    out.sample_rate = sample_rate;
    const size_t byte_count =
        static_cast<size_t>(read) * channels * sizeof(int16_t);
    out.pcm.assign(reinterpret_cast<const uint8_t*>(samples.data()),
                   reinterpret_cast<const uint8_t*>(samples.data()) + byte_count);
    return true;
}

}  // namespace dauntless::audio
```

- [ ] **Step 5: Wire `mp3.cc` into the audio library**

In `native/src/audio/CMakeLists.txt`, add `src/mp3.cc` to the `dauntless_audio` sources and link `dr_mp3`:

```cmake
add_library(dauntless_audio STATIC
    src/wav.cc
    src/mp3.cc
    src/null_backend.cc
    src/audio_system.cc
    src/python_binding.cc
    src/openal_backend.cc
)
```
and add, after the existing `target_link_libraries(dauntless_audio PRIVATE OpenAL)` line:
```cmake
target_link_libraries(dauntless_audio PRIVATE dr_mp3)
```

- [ ] **Step 6: Reconfigure, build, run the test**

Run:
```bash
cmake -B build -S . >/dev/null 2>&1 && cmake --build build --target audio_tests 2>&1 | tail -15 && \
ctest --test-dir build -R DecodeMp3 --output-on-failure 2>&1 | tail -15
```
Expected: build succeeds; `DecodeMp3.RejectsGarbage` and `DecodeMp3.RejectsEmpty` PASS.

- [ ] **Step 7: Commit**

```bash
git add native/src/audio/include/audio/mp3.h native/src/audio/src/mp3.cc \
        native/src/audio/CMakeLists.txt native/tests/audio/mp3_test.cc \
        native/tests/audio/CMakeLists.txt
git commit -m "feat(audio): decode_mp3 via dr_mp3 (whole-file to int16 PCM)"
```

---

### Task 3: Dispatch MP3 vs WAV in `AudioSystem::load_sound`

**Files:**
- Modify: `native/src/audio/src/audio_system.cc` (`load_sound` + include `audio/mp3.h`)
- Test: `native/tests/audio/audio_system_test.cc` (append)

- [ ] **Step 1: Write the failing test**

Append to `native/tests/audio/audio_system_test.cc` (it already has a `tiny_wav()` helper and constructs an `AudioSystem` with a `NullBackend` — reuse that pattern; this test asserts WAV still loads after dispatch is added, and a non-WAV blob is routed to the MP3 decoder and fails cleanly):

```cpp
TEST(AudioSystemDispatch, LoadsWavViaSniff) {
    auto sys = std::make_unique<dauntless::audio::AudioSystem>(
        std::make_unique<dauntless::audio::NullBackend>());
    sys->init();
    auto wav = tiny_wav();
    EXPECT_TRUE(sys->load_sound("", "wav_sound", wav.data(), wav.size(), false));
    EXPECT_NE(sys->get_sound("wav_sound"), 0u);
}

TEST(AudioSystemDispatch, NonWavRoutedToMp3AndFailsCleanly) {
    auto sys = std::make_unique<dauntless::audio::AudioSystem>(
        std::make_unique<dauntless::audio::NullBackend>());
    sys->init();
    // Not RIFF/WAVE -> routed to decode_mp3 -> not valid MP3 -> false, no crash.
    std::vector<uint8_t> junk = {0x49, 0x44, 0x33, 0x00, 0x11, 0x22, 0x33, 0x44};
    EXPECT_FALSE(sys->load_sound("", "bad", junk.data(), junk.size(), false));
    EXPECT_EQ(sys->get_sound("bad"), 0u);
}
```

(If `tiny_wav()` is in an anonymous namespace in that file, these tests can call it directly since they live in the same translation unit. Confirm the helper name by reading the file head; it is `tiny_wav()`.)

- [ ] **Step 2: Run to verify the WAV test still passes and confirm current behaviour**

Run:
```bash
cmake -B build -S . >/dev/null 2>&1 && cmake --build build --target audio_tests 2>&1 | tail -10 && \
ctest --test-dir build -R AudioSystemDispatch --output-on-failure 2>&1 | tail -15
```
Expected: `LoadsWavViaSniff` PASSES already (WAV path unchanged); `NonWavRoutedToMp3AndFailsCleanly` also PASSES already (today `decode_wav` rejects the non-RIFF blob and returns false). This test pins behaviour so the dispatch refactor can't regress it.

- [ ] **Step 3: Add the dispatch sniff**

In `native/src/audio/src/audio_system.cc`, add the include near the top:
```cpp
#include <audio/mp3.h>
#include <cstring>
```
Replace the body of `load_sound`'s decode step:
```cpp
    WavData wav;
    if (!decode_wav(wav_bytes, wav_len, wav)) return false;
```
with:
```cpp
    WavData wav;
    const bool is_wav = wav_len >= 12
        && std::memcmp(wav_bytes, "RIFF", 4) == 0
        && std::memcmp(wav_bytes + 8, "WAVE", 4) == 0;
    const bool decoded = is_wav ? decode_wav(wav_bytes, wav_len, wav)
                                : decode_mp3(wav_bytes, wav_len, wav);
    if (!decoded) return false;
```

- [ ] **Step 4: Reconfigure, build, run**

Run:
```bash
cmake -B build -S . >/dev/null 2>&1 && cmake --build build --target audio_tests 2>&1 | tail -10 && \
ctest --test-dir build -R "AudioSystemDispatch|DecodeMp3|Wav" --output-on-failure 2>&1 | tail -20
```
Expected: all PASS — WAV still loads (now via the sniff branch), the non-WAV blob routes to `decode_mp3` and fails cleanly, and the `DecodeMp3`/`Wav` suites are green.

- [ ] **Step 5: Run the full audio test suite to confirm no regressions**

Run: `ctest --test-dir build -R audio --output-on-failure 2>&1 | tail -20`
(If that regex matches nothing, run the binary directly: `ctest --test-dir build --output-on-failure 2>&1 | grep -iE "audio|wav|mp3|backend" | tail -20`.)
Expected: all audio tests PASS.

- [ ] **Step 6: Commit**

```bash
git add native/src/audio/src/audio_system.cc native/tests/audio/audio_system_test.cc
git commit -m "feat(audio): dispatch WAV vs MP3 by content sniff in load_sound"
```

---

### Milestone: live-build audio verification (user-driven — NOT a code task)

The `decode_mp3` **success** path and end-to-end audio are verified here (no committed MP3 fixture — see Constraints). The user does a full rebuild and runs the game:

```bash
cmake -B build -S . && cmake --build build -j
./build/dauntless --developer
```
Then opens a station menu (F2) / issues an order.

- **Officer's voice plays** → MP3 decode works end-to-end; the whole crew-speech + population + MP3 stack is verified — proceed to finish/merge the stacked branches.
- **Still silent, subtitle shows the officer line** → capture any `play_voice`-style error; the break is now inside decode/playback (e.g. an unusual MP3 sub-format dr_mp3 rejects, or an OpenAL buffer/format issue) — a focused follow-up, not a rework.

---

## Self-Review notes

- **Spec coverage:** §1 vendor dr_mp3 → Task 1; §2 `decode_mp3` → Task 2; §3 dispatch → Task 3; §4 no Python change → confirmed (untouched); testing (WAV-regression / dispatch / MP3-failure deterministic; success via live build) → Tasks 2–3 + Milestone. All covered.
- **Type/name consistency:** `decode_mp3(const uint8_t*, size_t, WavData&)` (Task 2) is called exactly that way in `load_sound` (Task 3); fills `WavData` fields (`channels`/`bits_per_sample`/`sample_rate`/`pcm`) defined in the existing `wav.h`. `dr_mp3` CMake target name matches between Task 1 (define) and Task 2 (link).
- **Build discipline:** every task that adds files/sources reconfigures (`cmake -B build -S .`) before building, and builds the focused `audio_tests` target.
- **Determinism:** no test depends on `game/` or a binary fixture; the MP3 success path is explicitly delegated to the live-build milestone (matches the approved spec's stated fallback).
- **YAGNI:** whole-file decode only; MP3 + WAV only; no streaming/OGG/resampling.
