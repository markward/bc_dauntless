# Music Not Playing — Handoff

**Status 2026-08-10: DynamicMusic is fully wired and reached, but no sound is
audible.** Three fixes attempted, all failed silently. Deferred to its own
session because it needs live iteration, not more blind fixes.

This document exists so that session starts warm. **Read the ruled-out list
first — three of the obvious hypotheses are already dead.**

---

## What definitely works

| Fact | Evidence |
|---|---|
| DynamicMusic runs and reaches our manager | `g_kMusicManager` does **not** appear in the 2026-08-10 run's stub telemetry at all (last seen 2026-08-07, before implementation). It was heatmap rank 163/164 before |
| The SDK contract is right | 12 manager tests + 13 player tests + 5 adapter tests green; signatures taken from real SDK call sites |
| Music assets exist | 44 files in `game/sfx/Music/`, and `_resolve_sfx_path("sfx/Music/EpisGen2.mp3")` → `game/sfx/Music/EpisGen2.mp3`, which is present |
| The engine can decode MP3 | `native/src/audio/src/mp3.cc` (dr_mp3, memory-only); the shipped `build/dauntless` carries 22 `dr_mp3` symbols |
| Other audio works | weapons/voice/ambient are audible in the same runs, so `_audio_mod` is not `None` and `tick_audio` is running |

## Ruled out — do not re-try these

1. **Missing assets.** 44 MP3s present, path resolution verified.
2. **MP3 unsupported.** Decoder compiled in and present in the binary.
3. **DynamicMusic not reaching us.** Telemetry proves it does.
4. **`TGSound.SetupFromFile`.** No such method — invented in attempt #1.
5. **`TGSound(path, False)` direct construction.** Attempt #2. Does *not* read
   the file; the ctor only asks whether a sound of that NAME is registered
   (`_loaded = _audio.get_sound(name) != 0`). Pinned dead by
   `tests/audio/test_music_adapter.py`.

## Current implementation

- `engine/appc/music_manager.py` — `g_kMusicManager`, SDK surface, fade grid
- `engine/audio/music.py` — `MusicPlayer`, BC's two-record crossfade
- `engine/host_loop.py` — `_music_sound_adapter` (attempt #3:
  `TGSoundManager.LoadSound(path, path, TGSound.LS_STREAMED)`) and
  `_pump_music`, called at the end of `tick_audio`
- `App.py` — `ET_MUSIC_DONE` = 1100, `ET_MUSIC_CONDITION_CHANGED` = 1101

## Next diagnostic steps, in order

**This needs a live run with instrumentation. The failure is silent at every
layer, which is precisely why three static fixes missed it.**

1. **Is `_pump_music` called at all?** Log once on entry. It sits at the end of
   `tick_audio`, which returns early when `_audio_mod is None`. Other audio
   working suggests it is reached — but *suggests* is what burned the last three
   attempts. Confirm it.
2. **Does `set_backend` ever run?** It is lazy, on the first pump. If `_pump_music`
   is not reached, the manager has **no backend at all** and `StartMusic` returns
   1 while doing nothing — indistinguishable from working.
3. **What does `LoadSound` return?** `None` means unreadable file or no backend.
   Log the resolved path and the return.
4. **What does `Play()` return?** A `None` handle, or one whose `is_live()` is
   False, means the source never started — look at `AudioSystem::play` and the
   source-pool cap (see the eviction tie rule at `audio_system.cc:118`; a
   saturated pool DROPS new voices rather than stealing).
5. **Is the volume actually applied?** The crossfade starts the first track at
   volume 1 via a duration-0 record, so a stuck 0 gain would be a player bug —
   but check the gain reaching `TGSound.SetVolume`.

**Suspicion worth testing early (step 4):** music is a long stream, and the
source pool is small with `BC_DEFAULT_PRIORITY == 0.5` everywhere. If a music
voice is allocated then evicted by later SFX, playback would stop instantly and
silently. The tie rule drops rather than steals, so a saturated pool would also
refuse the music voice outright.

## Do not

- **Do not** "fix" this by making `StartMusic` return 0 on failure. The return
  is load-bearing (`DynamicMusic.py:178` drops the track from its queue), and a
  false 0 would silently drain the playlist.
- **Do not** revert the manager/event/crossfade work. It is correct and
  independently verified; only the final playback hop is broken.

## Related

- `docs/gap_analysis.md` OQ-6.1 — marked NOT resolved until music is heard
- `spec/TGMusic.md` (clean-room reference) — 9-entry contract, crossfade model
  with falsifiers, `ET_MUSIC_DONE` payload
