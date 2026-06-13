# Bridge Crew Speech — Design

**Date:** 2026-06-13
**Status:** Approved (design); implementation pending
**Feature line:** crew-menu cluster (TG widget tree → menu activation → F1–F5 hotkeys
→ panel restyle → **speech**). See `project_crew_menu_panel.md` and the
`2026-06-12-*` / `2026-06-13-crew-menu-panel-restyle-*` specs for established patterns.

## Goal

Make the unmodified SDK bridge scripts produce crew speech by implementing
`CharacterClass.SpeakLine` (and `SayLine`) and the `CSP_*` speech-priority
constants. This is the "speech" bucket of the bridge crew-interaction cluster —
the single largest behavioural gap after character animation, which stays out of
scope.

The core SDK call is:

```python
pCharacter.SpeakLine(pDatabase, "lineID", priority)
```

with `priority` one of `App.CSP_SPONTANEOUS` / `App.CSP_NORMAL` /
`App.CSP_MISSION_CRITICAL`. `pDatabase` is a TGL localization DB loaded via
`g_kLocalizationManager.Load(...)`; the line ID resolves to subtitle text
(`GetString`) and a voice wav (`GetFilename`).

## Existing pieces this builds on

- **`SpeakLine`/`SayLine`** are currently no-ops (`pass`) on `CharacterClass`
  (`engine/appc/characters.py:481`).
- **Priorities are half-wired**: `engine/appc/ai.py:1118` defines
  `CSP_LOW/NORMAL/HIGH`. The SDK calls `App.CSP_SPONTANEOUS` / `CSP_NORMAL` /
  `CSP_MISSION_CRITICAL`. So `CSP_NORMAL` resolves to `1`, but
  `CSP_SPONTANEOUS` and `CSP_MISSION_CRITICAL` fall through to a **fresh
  `_NamedStub` per access** (distinct hash every time) — the dict-key / identity
  footgun documented in the crew-menu memory note. These must become real ints.
- **The localization database is real**: `g_kLocalizationManager.Load(...)`
  returns a `TGLocalizationDatabase` (`engine/appc/localization.py`) with
  `GetString(lineID)` → subtitle text (falls back to the key), `GetFilename(lineID)`
  → wav name (`""` if absent), `HasString(lineID)`. `tgl_reader` populates both
  the strings and sounds tables when the TGL file is present.
- **The subtitle surface exists end-to-end**: `_SubtitleWindow._add_text(text, dur)`
  → `_snapshot` → `SDKMirrorPanel` → `setSdkMirror(...)` → `sdk_mirror.js
  renderSubtitle`. `_SubtitleWindow` is registered as `MWT_SUBTITLE` in
  `engine/appc/top_window.py:41` and reachable via
  `TopWindow_GetTopWindow().FindMainWindow(MWT_SUBTITLE)`. It currently carries
  mission banners / cinematic text (via `TGCreditAction`).
- **Audio exists**: `TGSoundManager.LoadSound` + `TGSound.Play()` →
  `_dauntless_host.audio`; `SetVoice()` tags the "Voice" category. The SDK's own
  line-playback path (`MissionLib.py:4742`) loads the wav by
  `pDatabase.GetFilename(lineID)` then plays the named sound.

## Decisions (resolved during brainstorming)

1. **Output scope:** subtitle text **plus best-effort voice** through the existing
   `TGSound`/OpenAL path. Voice degrades silently when the wav / TGL sound-key is
   missing or the backend is null (headless, tests).
2. **Priority model:** one **global speech channel**, priority preempts. A new
   line preempts the active one only if its priority is `>=` the active line's; a
   strictly-lower-priority line is **dropped** while something is speaking. No
   unbounded queue. This matches BC feel — mission-critical narration is never
   stomped by idle callouts, and only one crew member talks at a time.
3. **Text routing:** **reuse the subtitle surface, extended with a speaker field**.
   Crew lines share the existing `#sdk-subtitle` CEF element (where stock BC puts
   `SpeakLine` subtitles) but the snapshot carries an optional `speaker` name so
   the element can render `Tactical: …`.

## Components

### 1. Priority constants — `engine/appc/ai.py`

Add the real SDK names as ordered ints; keep the existing two as aliases so
`App.py` and `tests/unit/test_ai_primitives.py` (which import `CSP_LOW`/`CSP_HIGH`)
keep working:

```python
CSP_SPONTANEOUS      = 0   # idle chatter (engineer reports, ge*)
CSP_NORMAL           = 1   # acknowledgements; default
CSP_MISSION_CRITICAL = 2   # scripted mission narration
CSP_LOW  = CSP_SPONTANEOUS      # back-compat alias
CSP_HIGH = CSP_MISSION_CRITICAL # back-compat alias
```

Export `CSP_SPONTANEOUS` and `CSP_MISSION_CRITICAL` from `App.py` (alongside the
existing `CSP_LOW, CSP_NORMAL, CSP_HIGH` import). This is the load-bearing fix:
real ints make every priority comparison and identity check deterministic instead
of resolving to distinct `_NamedStub`s.

### 2. `CrewSpeechBus` — new module `engine/appc/crew_speech.py`

A module-level singleton owning the one global speech channel.

- **State:** `_active_priority: int`, `_active_expiry: float` (monotonic seconds).
- **`speak(speaker, text, wav, priority, now=None)`:**
  - `now` defaults to `time.monotonic()`.
  - If a line is active (`now < _active_expiry`) **and** `priority <
    _active_priority` → **drop** (return without side effects).
  - Otherwise **accept/preempt**: compute `duration`, set
    `_active_priority = priority`, `_active_expiry = now + duration`; route `text`
    (when not `None`) to the subtitle window via `set_crew_line`; play `wav`
    best-effort.
- **`reset()`** — clears state. Called from `reset_sdk_globals`.
- **Duration model:** `clamp(word_count / 2.5, 2.0, 8.0)` seconds, where
  `word_count` comes from `text` when present, else from `wav`/`lineID` string
  length as a coarse proxy. This single value drives both the on-screen dwell and
  the bus free-up time, so they can never disagree.
- **Subtitle-window resolution:** lazily via
  `App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)`; tolerate `None`
  (no top window in a bare unit test) by skipping the subtitle route.
- **Module accessor:** `bus()` returns the singleton (created on first use).

Arbitration lives here, not in `CharacterClass`, giving one place to reset and one
place to unit-test the priority logic in isolation from rendering and audio.

### 3. Subtitle surface — `engine/appc/windows.py`

`_SubtitleWindow` gains a single replaceable crew slot, kept separate from the
banner `_active_texts` list (so a crew line and a mission banner don't collide and
preemption is a clean replacement):

- `_crew_line: tuple[str, str, float] | None` = `(speaker, text, expiry)`.
- `set_crew_line(speaker, text, duration)` — replaces the slot;
  `expiry = time.monotonic() + duration`. Preemption = replacement.
- `_snapshot(now)` — prunes the crew slot on expiry, reports the window visible
  when a crew line is live, and adds `speaker` and `speech` keys to the emitted
  dict alongside the existing `lines`. When no crew line is live the keys are
  omitted (banner-only snapshots are byte-identical to today).

### 4. `CharacterClass.SpeakLine` / `SayLine` — `engine/appc/characters.py`

Replace the `pass` no-ops:

```python
def SpeakLine(self, pDatabase=None, lineID="", priority=CSP_NORMAL, *_):
    db = pDatabase if pDatabase is not None else self.GetDatabase()
    text = db.GetString(lineID) if (db and db.HasString(lineID)) else None
    wav  = (db.GetFilename(lineID) or None) if db else None
    crew_speech.bus().speak(self.GetCharacterName(), text, wav, int(priority))

def SayLine(self, pDatabase=None, lineID="", priority=CSP_NORMAL, *_):
    # "Aye, Captain" acknowledgements: voice-only, no subtitle (matches BC).
    db  = pDatabase if pDatabase is not None else self.GetDatabase()
    wav = (db.GetFilename(lineID) or None) if db else None
    crew_speech.bus().speak(self.GetCharacterName(), None, wav, int(priority))
```

- **Tolerant/variadic signature** — SDK calls range from 2 args
  (`CommonAnimations.py:38: SpeakLine(db, name + "NothingToAdd")`) to 3
  (`App.CSP_*`). Default `priority = CSP_NORMAL`.
- **Subtitle gated on `HasString`** — when the DB lacks the line (TGL absent), no
  subtitle is shown (avoids rendering the raw line key), but voice is still
  attempted.
- **`priority` coerced to `int`** — defends against a stray `_NamedStub` slipping
  through from a not-yet-fixed call site.

### 5. Voice playback (best-effort) — inside `CrewSpeechBus`

When `wav` resolves and audio is available:
`TGSoundManager.instance().LoadSound(wav, wav, TGSound.LS_STREAMED)` (the wav path
doubles as the `GetSound` name key, so the load is idempotent — `GetSound(wav)`
first), `SetVoice()`, then `Play()`. Degrades silently when the wav / TGL sound-key
is missing or the backend is null. No new audio surface. The bus receives the
already-resolved `wav` path from `SpeakLine`/`SayLine` and needs no `lineID`.

### 6. CEF — `native/assets/ui-cef/js/sdk_mirror.js` (+ `css/sdk_mirror.css`)

`renderSubtitle` prepends a styled speaker label when `entry.speaker` is present
(e.g. a bold `Tactical:` prefix before the line). Banner-only snapshots (no
`speaker`) render exactly as today. CSS adds a `.sdk-subtitle__speaker` rule.

### 7. Reset wiring — `engine/host_loop.py:reset_sdk_globals`

Add `crew_speech.bus().reset()` on mission swap and clear the subtitle crew slot —
the same teardown discipline the crew-menu world already follows.

## Data flow

```
SDK bridge script
  pEngineer.SpeakLine(pDatabase, "ge119", App.CSP_SPONTANEOUS)
        │
        ▼
CharacterClass.SpeakLine
  text = db.GetString("ge119") if db.HasString else None
  wav  = db.GetFilename("ge119") or None
        │
        ▼
CrewSpeechBus.speak(speaker="Engineering", text, wav, priority=0)
  ├─ drop if a higher-priority line is still live
  └─ else: _SubtitleWindow.set_crew_line(speaker, text, duration)   ──┐
           + TGSound load/Play(wav)  (best-effort)                     │
        │                                                              │
        ▼ (once per tick)                                              │
SDKMirrorPanel.render_payload → _SubtitleWindow._snapshot ◄───────────┘
  → setSdkMirror({entries:[{type:"subtitle", speaker, speech, lines}]})
        │
        ▼
sdk_mirror.js renderSubtitle → #sdk-subtitle shows "Engineering: <line>"
```

## Error handling / edge cases

- **Missing top window** (bare unit test): bus skips the subtitle route, still
  performs arbitration. Callers never crash.
- **Null audio backend / missing wav**: voice no-ops; subtitle (if any) still shows.
- **`_NamedStub` priority**: coerced to `int` at the `SpeakLine` boundary.
- **Mission swap mid-line**: `reset()` clears arbitration; the subtitle slot is
  cleared so a stale line can't linger into the next mission.
- **DB is `None`**: both methods fall back to `self.GetDatabase()`, then to a
  no-op when still absent.

## Testing

Per project rules: **focused pytest subsets only** via `.venv/bin/python -m pytest
<files>` — never the full suite (it OOMs the machine). No synthetic desktop input
for visual verification.

- **CSP constants**: real ints, ordered `SPONTANEOUS < NORMAL < MISSION_CRITICAL`;
  `App.CSP_SPONTANEOUS`/`App.CSP_MISSION_CRITICAL` return a stable value across
  repeated accesses (identity regression guard).
- **Bus arbitration** (pure, no rendering/audio): strictly-lower priority dropped
  while a line is live; equal and higher priority preempt; an expired line lets the
  next line through regardless of priority.
- **Duration model**: short and long text clamp to `[2.0, 8.0]`.
- **`SpeakLine` → subtitle snapshot** carries `text` + `speaker`; `HasString=False`
  ⇒ no subtitle but voice still attempted.
- **`SayLine`**: voice-only, no subtitle slot set.
- **Voice best-effort**: null backend ⇒ no crash; `LoadSound`/`Play` invoked
  (assert via the null backend or a fake `TGSoundManager`).
- **Integration**: drive a real `EngineerMenuHandlers` `SpeakLine` call → subtitle
  appears in the snapshot; `reset_sdk_globals` clears it.

## Out of scope (explicit)

- Character lip-sync / facial / body animation.
- The subtitle on/off config gate (`g_kConfigMapping` "Subtitles") — we always
  render for now.
- Real wav-duration-driven dwell — we estimate from text length.
- Any new dedicated CEF panel — crew speech reuses the subtitle element.
- A multi-line speech queue — equal/lower lines are dropped, not queued.
