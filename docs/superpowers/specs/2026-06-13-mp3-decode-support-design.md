# MP3 Decode Support — Design

**Date:** 2026-06-13
**Status:** Approved (design); implementation pending
**Branch:** `feat/audio-mp3-decode` (stacked on `feat/bridge-crew-population` → `feat/crew-menu-ack-speech`).
**Motivation:** Live-build verification of the crew-population work showed the speech pipeline is correct end-to-end (real officer, DB, subtitle text `"Yes, Captain?"`, resolved file path) but **voice playback fails**: the bridge-crew voice files are MP3 (e.g. `sfx/Bridge/Crew/Tactical/FelixSir2.mp3`) and the native audio backend's `AudioSystem::load_sound` → `decode_wav` only accepts `RIFF/WAVE`. `LoadSound` returns `False` for every MP3.

## Goal

Add MP3 decoding to the native audio backend so MP3 game audio loads and plays. This unblocks bridge-crew voice with **no crew-side changes** — `crew_speech.acknowledge` already resolves the correct MP3 path and calls `LoadSound`; only the backend decode step fails today. It also benefits every other MP3 sound in the BC install.

## Decisions (resolved during brainstorming)

1. **Decoder:** vendor **`dr_mp3`** (dr_libs, public-domain/MIT-0) as a single-header library, mirroring the existing `stb` vendoring. Not minimp3, not a system library.
2. **Decode model:** whole-file decode to in-memory int16 PCM (clips are 6–9 KB), identical to the WAV path. Streaming (`LS_STREAMED`) is out of scope.
3. **Dispatch:** content sniff in `load_sound` (`RIFF`+`WAVE` → WAV, else MP3); no reliance on file extension (the backend only sees bytes).
4. **Test fixture:** commit a tiny public-domain MP3 fixture for the decode-success unit test; if a clean one can't be sourced, the success path is covered by the live-build listen, while dispatch / WAV-regression / MP3-failure stay deterministically unit-tested.

## Key facts established

- `WavData` (`native/src/audio/include/audio/wav.h`) is the shared PCM struct: `channels`, `bits_per_sample`, `sample_rate`, `pcm` (interleaved little-endian bytes). `decode_wav(bytes, len, out)` fills it.
- `AudioSystem::load_sound` (`audio_system.cc`) calls `decode_wav` then `backend_->create_buffer(PcmDesc{...}, pcm…)`. The only format gate is `decode_wav`.
- Third-party libs are vendored under `native/third_party/<lib>/` each with `LICENSE` + `UPSTREAM_VERSION` + `CMakeLists.txt` + the header(s), wired via `add_subdirectory(third_party/<lib>)` in `native/CMakeLists.txt` (precedent: `stb`).
- C++ tests use **gtest** (FetchContent in `native/tests/CMakeLists.txt`); pattern is `TEST(Suite, Case)` in a `*_test.cc` linked into a test executable.
- No `ffmpeg`/`lame` on PATH; game MP3s are gitignored and copyrighted (cannot be committed as fixtures).

## Components

### 1. Vendor `dr_mp3` — `native/third_party/dr_libs/`

Add `dr_mp3.h`, `LICENSE`, `UPSTREAM_VERSION`, and a `CMakeLists.txt` that exposes an `INTERFACE` target (header-only include dir), mirroring `native/third_party/stb/`. Register with `add_subdirectory(third_party/dr_libs)` in `native/CMakeLists.txt`. Only the header is vendored; the implementation macro is defined in our own `.cc` (below) so `dr_mp3`'s code compiles exactly once.

### 2. `decode_mp3` — `native/src/audio/{include/audio/mp3.h, src/mp3.cc}`

```cpp
// mp3.h
namespace dauntless::audio {
// Decodes a whole MP3 to interleaved int16 PCM. Returns true on success;
// false on init/decode failure or empty output (caller treats as missing).
bool decode_mp3(const uint8_t* bytes, size_t len, WavData& out);
}
```

`mp3.cc` defines `DR_MP3_IMPLEMENTATION` then `#include "dr_mp3.h"`. Implementation:
- `drmp3 mp3; if (!drmp3_init_memory(&mp3, bytes, len, NULL)) return false;`
- Read all frames: `drmp3_read_pcm_frames_s16` into a growing buffer (or `drmp3_get_pcm_frame_count` then one read).
- On success fill `out`: `channels = mp3.channels`, `bits_per_sample = 16`, `sample_rate = mp3.sampleRate`, `pcm` = the int16 bytes.
- `drmp3_uninit(&mp3)`. Return `false` if zero frames decoded.

### 3. Dispatch in `AudioSystem::load_sound` — `native/src/audio/src/audio_system.cc`

Replace the unconditional `decode_wav` call with a content sniff:
- If `len >= 12 && memcmp(bytes,"RIFF",4)==0 && memcmp(bytes+8,"WAVE",4)==0` → `decode_wav`.
- Else → `decode_mp3`.
- If the chosen decoder returns `false`, return `false` (unchanged downstream behaviour).

Both branches produce a `WavData`; the existing `create_buffer` / `sounds_` / `name_to_id_` path is untouched. Add `src/mp3.cc` to the `dauntless_audio` sources in `native/src/audio/CMakeLists.txt` and link the `dr_mp3` interface target.

### 4. Python side — no change

`TGSoundManager.LoadSound` already reads file bytes and passes them to `_audio.load_sound`; dispatch is by content. The crew `.mp3` path resolves and plays once the backend decodes it.

## Data flow

```
acknowledge → wav="sfx/Bridge/Crew/Tactical/FelixSir2.mp3"
  → TGSoundManager.LoadSound reads bytes → _audio.load_sound(bytes)
  → AudioSystem::load_sound: sniff → not RIFF → decode_mp3 → WavData(int16 PCM)
  → backend->create_buffer → TGSound.Play() → audible
```

## Error handling

`decode_mp3` returns `false` on malformed/truncated data → `load_sound` returns `false` → `LoadSound` → `None` → `_play_voice` no-ops (best-effort, unchanged). Degrades silently, exactly like a missing WAV today. No new exception surface crosses the Python boundary.

## Testing

C++ gtest — new `native/tests/audio/decode_test.cc` in a test executable linking `dauntless_audio` + gtest (registered in `native/tests/CMakeLists.txt`):

- **WAV regression**: a minimal in-memory WAV (RIFF/WAVE, PCM, 16-bit mono) still decodes via `load_sound`/`decode_wav` — proves the dispatch sniff didn't break WAV.
- **Dispatch**: `RIFF…` bytes route to the WAV decoder; non-`RIFF` bytes route to `decode_mp3`.
- **MP3 failure path**: garbage / truncated bytes → `decode_mp3` returns `false`, no crash, `load_sound` returns `false`.
- **MP3 success path**: decode a committed tiny public-domain MP3 fixture under `native/tests/audio/fixtures/` → `WavData` has non-zero `channels`/`sample_rate` and non-empty `pcm`. If a clean CC0/public-domain fixture can't be sourced (no encoder on PATH; game assets can't be committed), this single assertion is deferred to the live-build verification, and a comment in the test records why.
- **Live-build verification** (user-driven, the real end-to-end proof): rebuild, open a station menu (F2) / issue an order → hear the officer's voice. This also un-gates merging the stacked crew branches.

Per project rules: Python suite stays untouched here (this is native-only); never run the full pytest suite.

## Out of scope

- Streaming decode for long audio (`LS_STREAMED`) — we whole-decode; fine for short clips, a follow-up for music/ambient if needed.
- OGG or other formats (BC uses MP3 + WAV).
- `.LIP` lip-sync data (animation; separate concern).
- Resampling / channel conversion beyond what `create_buffer` already accepts (dr_mp3 yields the file's native rate/channels, same as WAV).
