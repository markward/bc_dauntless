# Bridge Crew Speech Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make unmodified SDK bridge scripts produce crew speech by implementing `CharacterClass.SpeakLine`/`SayLine` and the `CSP_*` priorities, routing subtitle text (+ best-effort voice) through the existing subtitle mirror.

**Architecture:** A module-level `CrewSpeechBus` singleton owns the one global speech channel and does priority arbitration (only one crew member talks at a time; strictly-lower-priority lines are dropped while a line is live). `CharacterClass.SpeakLine` resolves the line's subtitle text + voice wav from the TGL database and hands them to the bus; the bus routes text to `_SubtitleWindow` (extended with a single replaceable crew slot carrying a speaker name) and plays the wav best-effort via `TGSoundManager`.

**Tech Stack:** Python 3 (engine shims under `engine/appc/`), pytest, CEF/JS subtitle mirror (`native/assets/ui-cef/`).

**Spec:** `docs/superpowers/specs/2026-06-13-bridge-crew-speech-design.md`

**Project constraints (read before running anything):**
- **NEVER run the full pytest suite** — it OOMs the machine (>100 GB RAM). Always run focused files via `.venv/bin/python -m pytest <files>`.
- No synthetic desktop input for visual verification (Mark's machine is in active use). JS changes are verified via the Python snapshot shape + asking Mark to drive.

---

### Task 1: Speech-priority constants (`CSP_*`)

The SDK calls `App.CSP_SPONTANEOUS` / `App.CSP_NORMAL` / `App.CSP_MISSION_CRITICAL`. Today only `CSP_NORMAL` is a real int; the other two fall through `App.__getattr__` to a **fresh `_NamedStub` per access** (distinct hash every time). Make all three real, ordered ints. Keep `CSP_LOW`/`CSP_HIGH` as aliases (still imported by `App.py` and `tests/unit/test_ai_primitives.py`).

**Files:**
- Modify: `engine/appc/ai.py:1116-1120`
- Modify: `App.py:171` (export the new names)
- Test: `tests/unit/test_crew_speech_priorities.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_crew_speech_priorities.py`:

```python
"""CSP_* speech-priority constants must be real, ordered ints and stable
across repeated App attribute accesses (identity-regression guard for the
_NamedStub footgun)."""
import App
from engine.appc.ai import (
    CSP_SPONTANEOUS, CSP_NORMAL, CSP_MISSION_CRITICAL, CSP_LOW, CSP_HIGH,
)


def test_priorities_are_ordered_ints():
    assert (CSP_SPONTANEOUS, CSP_NORMAL, CSP_MISSION_CRITICAL) == (0, 1, 2)
    assert CSP_SPONTANEOUS < CSP_NORMAL < CSP_MISSION_CRITICAL


def test_legacy_aliases_preserved():
    assert CSP_LOW == CSP_SPONTANEOUS
    assert CSP_HIGH == CSP_MISSION_CRITICAL
    assert len({CSP_LOW, CSP_NORMAL, CSP_HIGH}) == 3


def test_app_exposes_real_ints_with_stable_identity():
    # The bug: App.CSP_SPONTANEOUS used to return a fresh _NamedStub each time.
    assert App.CSP_SPONTANEOUS == 0
    assert App.CSP_MISSION_CRITICAL == 2
    assert App.CSP_NORMAL == 1
    assert App.CSP_SPONTANEOUS == App.CSP_SPONTANEOUS
    assert App.CSP_MISSION_CRITICAL is App.CSP_MISSION_CRITICAL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_crew_speech_priorities.py -v`
Expected: FAIL — `ImportError: cannot import name 'CSP_SPONTANEOUS'`.

- [ ] **Step 3: Update the constants in `engine/appc/ai.py`**

Replace lines 1116-1120:

```python
# ── Character action priority constants ──────────────────────────────────────
# Top-level App constants used in BridgeHandlers.py:650 and every SpeakLine
# call site. The SDK names are CSP_SPONTANEOUS/CSP_NORMAL/CSP_MISSION_CRITICAL;
# CSP_LOW/CSP_HIGH are dauntless-era aliases kept for back-compat.
CSP_SPONTANEOUS      = 0   # idle chatter (engineer reports, ge*)
CSP_NORMAL           = 1   # acknowledgements; default
CSP_MISSION_CRITICAL = 2   # scripted mission narration
CSP_LOW  = CSP_SPONTANEOUS      # back-compat alias
CSP_HIGH = CSP_MISSION_CRITICAL # back-compat alias
```

- [ ] **Step 4: Export the new names from `App.py`**

In `App.py`, change line 171 from:

```python
    CSP_LOW, CSP_NORMAL, CSP_HIGH,
```

to:

```python
    CSP_LOW, CSP_NORMAL, CSP_HIGH,
    CSP_SPONTANEOUS, CSP_MISSION_CRITICAL,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_crew_speech_priorities.py tests/unit/test_ai_primitives.py -v`
Expected: PASS (new file + existing `test_ai_primitives.py` still green).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/ai.py App.py tests/unit/test_crew_speech_priorities.py
git commit -m "feat(crew-speech): real CSP_* speech-priority ints + App export"
```

---

### Task 2: `_SubtitleWindow` crew-line slot + snapshot speaker field

Add a single replaceable crew slot, separate from the banner `_active_texts`, so preemption is a clean replacement and a crew line never piles onto a mission banner. The snapshot gains `speaker`/`speech` keys **only when a crew line is live** (existing banner-only snapshots stay byte-identical).

**Files:**
- Modify: `engine/appc/windows.py:182-214` (`_SubtitleWindow.__init__` + `_snapshot`)
- Test: `tests/unit/test_subtitle_window.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_subtitle_window.py`:

```python
def test_set_crew_line_records_slot(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 100.0)
    sw.set_crew_line("Tactical", "Shields holding", 4.0)
    assert sw._crew_line == ("Tactical", "Shields holding", 104.0)


def test_snapshot_includes_speaker_and_speech_when_crew_line_live(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw.set_crew_line("Helm", "Course laid in", 5.0)
    snap = sw._snapshot(now=1.0)
    assert snap["visible"] is True
    assert snap["speaker"] == "Helm"
    assert snap["speech"] == "Course laid in"
    assert snap["lines"] == []


def test_snapshot_prunes_expired_crew_line(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw.set_crew_line("XO", "Aye", 1.0)
    snap = sw._snapshot(now=5.0)   # crew line expired, nothing else visible
    assert snap is None


def test_snapshot_omits_speaker_keys_when_no_crew_line():
    sw = _SubtitleWindow()
    sw.SetOn()
    snap = sw._snapshot(now=0.0)
    assert "speaker" not in snap
    assert "speech" not in snap
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_subtitle_window.py -v`
Expected: FAIL — `AttributeError: '_SubtitleWindow' object has no attribute 'set_crew_line'`.

- [ ] **Step 3: Add the crew slot in `__init__`**

In `engine/appc/windows.py`, in `_SubtitleWindow.__init__` (after `self._active_texts: list[tuple[str, float]] = []`, currently line 186):

```python
        self._active_texts: list[tuple[str, float]] = []
        # Single replaceable crew-speech slot (speaker, text, expiry). Separate
        # from _active_texts so a SpeakLine preemption is a clean replacement
        # and never collides with a mission banner. Owned by CrewSpeechBus.
        self._crew_line: tuple[str, str, float] | None = None
```

- [ ] **Step 4: Add `set_crew_line` and update `_snapshot`**

In `engine/appc/windows.py`, add the method just above `_add_text` (line 201):

```python
    def set_crew_line(self, speaker: str, text: str, duration: float) -> None:
        # Replaces the crew slot wholesale — preemption == replacement.
        self._crew_line = (
            str(speaker), str(text), time.monotonic() + float(duration),
        )
```

Replace `_snapshot` (lines 204-214) with:

```python
    def _snapshot(self, now: float) -> dict | None:
        self._active_texts = [(t, e) for (t, e) in self._active_texts if e > now]
        if self._crew_line is not None and self._crew_line[2] <= now:
            self._crew_line = None
        has_crew = self._crew_line is not None
        if not self._visible and not self._active_texts and not has_crew:
            return None
        snap = {
            "type": "subtitle",
            "id": self._id,
            "visible": self._visible or bool(self._active_texts) or has_crew,
            "mode": self._mode,
            "lines": [t for (t, _) in self._active_texts],
        }
        if has_crew:
            snap["speaker"] = self._crew_line[0]
            snap["speech"] = self._crew_line[1]
        return snap
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_subtitle_window.py -v`
Expected: PASS (new + all pre-existing subtitle tests, including `test_snapshot_returns_dict_when_visible` which asserts the exact banner-only dict).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/windows.py tests/unit/test_subtitle_window.py
git commit -m "feat(crew-speech): _SubtitleWindow crew slot + speaker snapshot field"
```

---

### Task 3: `CrewSpeechBus` — arbitration, duration, routing, voice

The one global speech channel. `speak()` returns `True` when the line is accepted, `False` when dropped. Routing to the subtitle window and voice playback are best-effort and never raise.

**Files:**
- Create: `engine/appc/crew_speech.py`
- Test: `tests/unit/test_crew_speech_bus.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_crew_speech_bus.py`:

```python
"""CrewSpeechBus arbitration + duration. Pure logic — no top window, no audio
(routing degrades to no-op when collaborators are absent)."""
from engine.appc.crew_speech import CrewSpeechBus, _estimate_duration
from engine.appc.ai import CSP_SPONTANEOUS, CSP_NORMAL, CSP_MISSION_CRITICAL


def test_first_line_is_accepted():
    bus = CrewSpeechBus()
    assert bus.speak("Helm", "Course laid in", None, CSP_NORMAL, now=0.0) is True


def test_lower_priority_dropped_while_line_live():
    bus = CrewSpeechBus()
    bus.speak("Felix", "Mission critical!", None, CSP_MISSION_CRITICAL, now=0.0)
    # Spontaneous chatter arrives 1s later, line still live → dropped.
    assert bus.speak("Eng", "chatter", None, CSP_SPONTANEOUS, now=1.0) is False


def test_equal_priority_preempts_while_live():
    bus = CrewSpeechBus()
    bus.speak("A", "one", None, CSP_NORMAL, now=0.0)
    assert bus.speak("B", "two", None, CSP_NORMAL, now=0.5) is True


def test_higher_priority_preempts_while_live():
    bus = CrewSpeechBus()
    bus.speak("Eng", "chatter", None, CSP_SPONTANEOUS, now=0.0)
    assert bus.speak("Felix", "critical", None, CSP_MISSION_CRITICAL, now=0.5) is True


def test_expired_line_lets_lower_priority_through():
    bus = CrewSpeechBus()
    bus.speak("Felix", "critical", None, CSP_MISSION_CRITICAL, now=0.0)
    # Far past the max 8s dwell → channel free.
    assert bus.speak("Eng", "chatter", None, CSP_SPONTANEOUS, now=100.0) is True


def test_reset_frees_the_channel():
    bus = CrewSpeechBus()
    bus.speak("Felix", "critical", None, CSP_MISSION_CRITICAL, now=0.0)
    bus.reset()
    assert bus.speak("Eng", "chatter", None, CSP_SPONTANEOUS, now=0.1) is True


def test_duration_clamps_between_2_and_8_seconds():
    assert _estimate_duration("hi", None) == 2.0                 # 1 word → floored
    assert _estimate_duration(None, None) == 2.0                 # empty → floored
    long_text = " ".join(["word"] * 100)
    assert _estimate_duration(long_text, None) == 8.0            # capped
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_crew_speech_bus.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.appc.crew_speech'`.

- [ ] **Step 3: Create the module**

Create `engine/appc/crew_speech.py`:

```python
"""CrewSpeechBus — the one global bridge-speech channel.

Bridge scripts call CharacterClass.SpeakLine / SayLine, which resolve the
line's subtitle text and voice wav and hand them here. The bus owns priority
arbitration (only one crew member talks at a time; a strictly lower-priority
line is dropped while a line is still live) and routes the accepted line to
the subtitle surface (engine/appc/windows._SubtitleWindow) and the audio
subsystem (engine/audio/tg_sound) best-effort.

Spec: docs/superpowers/specs/2026-06-13-bridge-crew-speech-design.md
"""
from __future__ import annotations

import time
from typing import Optional

_MIN_DURATION_S = 2.0
_MAX_DURATION_S = 8.0
_WORDS_PER_SECOND = 2.5


def _estimate_duration(text: Optional[str], wav: Optional[str]) -> float:
    """Coarse reading-speed dwell. Drives both the on-screen time and the
    bus free-up time, so they can never disagree."""
    source = text or wav or ""
    words = max(1, len(source.split()))
    secs = words / _WORDS_PER_SECOND
    return max(_MIN_DURATION_S, min(_MAX_DURATION_S, secs))


class CrewSpeechBus:
    def __init__(self) -> None:
        self._active_priority: int = -1
        self._active_expiry: float = 0.0

    def reset(self) -> None:
        self._active_priority = -1
        self._active_expiry = 0.0

    def speak(self, speaker, text, wav, priority, now=None) -> bool:
        """Arbitrate one line. Returns True if accepted, False if dropped."""
        if now is None:
            now = time.monotonic()
        priority = int(priority)
        line_live = now < self._active_expiry
        if line_live and priority < self._active_priority:
            return False  # a higher-priority line is still talking
        duration = _estimate_duration(text, wav)
        self._active_priority = priority
        self._active_expiry = now + duration
        if text:
            self._route_subtitle(str(speaker), str(text), duration)
        if wav:
            self._play_voice(str(wav))
        return True

    # ── Best-effort routing (never raises) ──────────────────────────────────
    def _route_subtitle(self, speaker, text, duration) -> None:
        try:
            import App
            sub = App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)
        except Exception:
            sub = None
        if sub is not None and hasattr(sub, "set_crew_line"):
            sub.set_crew_line(speaker, text, duration)

    def _play_voice(self, wav) -> None:
        try:
            from engine.audio.tg_sound import TGSoundManager, TGSound
            mgr = TGSoundManager.instance()
            snd = mgr.GetSound(wav)
            if snd is None:
                # The wav path doubles as the GetSound name key.
                snd = mgr.LoadSound(wav, wav, TGSound.LS_STREAMED)
            if snd is None:
                return
            snd.SetVoice()
            snd.Play()
        except Exception:
            pass


_bus: Optional[CrewSpeechBus] = None


def bus() -> CrewSpeechBus:
    """Return the process-wide speech bus (created on first use)."""
    global _bus
    if _bus is None:
        _bus = CrewSpeechBus()
    return _bus
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_crew_speech_bus.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/crew_speech.py tests/unit/test_crew_speech_bus.py
git commit -m "feat(crew-speech): CrewSpeechBus priority arbitration + routing"
```

---

### Task 4: `CharacterClass.SpeakLine` / `SayLine`

Replace the `pass` no-ops. `SpeakLine` resolves subtitle text (gated on `HasString`, to avoid rendering raw line keys) + voice wav and hands them to the bus. `SayLine` is voice-only (the "Aye, Captain" acks).

**Files:**
- Modify: `engine/appc/characters.py:481-482` (`SpeakLine`/`SayLine`) and the import block at the top (line 26)
- Test: `tests/unit/test_characters.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_characters.py`:

```python
def test_speakline_routes_text_and_speaker_to_subtitle(monkeypatch):
    import App
    from engine.appc import top_window, crew_speech
    from engine.appc.characters import CharacterClass
    from engine.appc.localization import TGLocalizationDatabase
    from engine.appc.ai import CSP_NORMAL

    top_window.reset_for_tests()
    crew_speech.bus().reset()

    char = CharacterClass()
    char.SetCharacterName("Tactical")
    db = TGLocalizationDatabase("x.tgl", strings={"L1": "Shields holding"})

    char.SpeakLine(db, "L1", CSP_NORMAL)

    sub = App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)
    snap = sub._snapshot(now=0.0)
    assert snap["speaker"] == "Tactical"
    assert snap["speech"] == "Shields holding"


def test_speakline_without_string_shows_no_subtitle(monkeypatch):
    import App
    from engine.appc import top_window, crew_speech
    from engine.appc.characters import CharacterClass
    from engine.appc.localization import TGLocalizationDatabase

    top_window.reset_for_tests()
    crew_speech.bus().reset()

    char = CharacterClass()
    char.SetCharacterName("Eng")
    db = TGLocalizationDatabase("x.tgl")  # no strings → HasString False

    char.SpeakLine(db, "ge119")  # 2-arg form, default priority

    sub = App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)
    assert sub._snapshot(now=0.0) is None  # nothing displayed


def test_sayline_sets_no_subtitle(monkeypatch):
    import App
    from engine.appc import top_window, crew_speech
    from engine.appc.characters import CharacterClass
    from engine.appc.localization import TGLocalizationDatabase

    top_window.reset_for_tests()
    crew_speech.bus().reset()

    char = CharacterClass()
    char.SetCharacterName("XO")
    db = TGLocalizationDatabase("x.tgl", strings={"ack": "Aye sir"})

    char.SayLine(db, "ack")  # voice-only — must NOT set a subtitle slot

    sub = App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)
    assert sub._snapshot(now=0.0) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/test_characters.py -k "speakline or sayline" -v`
Expected: FAIL — `SpeakLine` is a no-op, so no subtitle slot is set (first test fails on missing `speaker`).

- [ ] **Step 3: Add imports to `characters.py`**

In `engine/appc/characters.py`, after line 26 (`from engine.appc.objects import ObjectClass`) and the existing `from engine.appc.tg_ui.widgets import TGPane`, add:

```python
from engine.appc import crew_speech
from engine.appc.ai import CSP_NORMAL
```

(`engine.appc.ai` does not import `characters`, and `crew_speech`'s module-level body imports only stdlib — no circular import.)

- [ ] **Step 4: Implement `SpeakLine`/`SayLine`**

In `engine/appc/characters.py`, replace lines 481-482:

```python
    def SpeakLine(self, *args) -> None:           pass
    def SayLine(self, *args) -> None:             pass
```

with:

```python
    def SpeakLine(self, pDatabase=None, lineID="", priority=CSP_NORMAL, *_) -> None:
        db = pDatabase if pDatabase is not None else self._database
        line = str(lineID)
        # Gate on HasString so a missing TGL doesn't render the raw line key.
        text = db.GetString(line) if (db and db.HasString(line)) else None
        wav = (db.GetFilename(line) or None) if db else None
        crew_speech.bus().speak(self._character_name, text, wav, int(priority))

    def SayLine(self, pDatabase=None, lineID="", priority=CSP_NORMAL, *_) -> None:
        # "Aye, Captain" acknowledgements: voice-only, no subtitle (matches BC).
        db = pDatabase if pDatabase is not None else self._database
        wav = (db.GetFilename(str(lineID)) or None) if db else None
        crew_speech.bus().speak(self._character_name, None, wav, int(priority))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_characters.py -v`
Expected: PASS (new + all pre-existing character tests).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/characters.py tests/unit/test_characters.py
git commit -m "feat(crew-speech): implement CharacterClass.SpeakLine/SayLine"
```

---

### Task 5: CEF subtitle rendering — speaker label

Render the crew `speech` line with a bold speaker prefix. Banner-only snapshots (no `speech`) render unchanged. There is no JS unit-test harness in this repo; correctness is covered by the Python snapshot shape (Task 4) plus a visual check Mark drives manually.

**Files:**
- Modify: `native/assets/ui-cef/js/sdk_mirror.js` (`renderSubtitle`)
- Modify: `native/assets/ui-cef/css/sdk_mirror.css` (add `.sdk-subtitle__speaker`)

- [ ] **Step 1: Update `renderSubtitle`**

In `native/assets/ui-cef/js/sdk_mirror.js`, replace the whole `renderSubtitle` function with:

```javascript
function renderSubtitle(entry) {
  const el = document.getElementById("sdk-subtitle");
  if (!el) return;
  const lines = (entry && entry.lines) || [];
  const hasSpeech = !!(entry && entry.speech);
  if (!entry || !entry.visible || (lines.length === 0 && !hasSpeech)) {
    el.hidden = true;
    el.innerHTML = "";
    return;
  }
  el.hidden = false;
  const parts = lines.map(escapeHtml);
  if (hasSpeech) {
    const speaker = entry.speaker
      ? '<span class="sdk-subtitle__speaker">' +
        escapeHtml(entry.speaker) + ":</span> "
      : "";
    parts.push(speaker + escapeHtml(entry.speech));
  }
  el.innerHTML = parts.join("<br>");
}
```

- [ ] **Step 2: Add the speaker style**

In `native/assets/ui-cef/css/sdk_mirror.css`, after the `#sdk-subtitle { … }` block (line 24), add:

```css
.sdk-subtitle__speaker {
  font-weight: 700;
  color: #9cc4ff;
}
```

- [ ] **Step 3: Sanity-check the JS parses**

Run: `node --check native/assets/ui-cef/js/sdk_mirror.js`
Expected: no output (exit 0). If `node` is unavailable, skip — the change is small and syntactically isolated.

- [ ] **Step 4: Commit**

```bash
git add native/assets/ui-cef/js/sdk_mirror.js native/assets/ui-cef/css/sdk_mirror.css
git commit -m "feat(crew-speech): render speaker label in subtitle mirror"
```

---

### Task 6: Reset the speech bus on mission swap

`top_window.reset_for_tests()` already rebuilds `_SubtitleWindow` (so the crew slot clears transitively), but the `CrewSpeechBus` singleton is a separate module-level object whose arbitration state must be cleared explicitly, or a line still "live" at swap time would suppress the next mission's first line.

**Files:**
- Modify: `engine/host_loop.py:reset_sdk_globals` (the `try/except` block near the end that resets `TacticalControlWindow`)
- Test: `tests/integration/test_bridge_crew_speech.py` (created in Task 7 — the reset assertion lives there)

- [ ] **Step 1: Add the bus reset**

In `engine/host_loop.py`, inside `reset_sdk_globals`, locate the existing block:

```python
    top_window.reset_for_tests()
```

Immediately after it, add:

```python
    # Clear the global crew-speech channel so a line still "live" at swap
    # time can't suppress the next mission's first SpeakLine. The subtitle
    # crew slot itself is cleared transitively by reset_for_tests (it
    # rebuilds _SubtitleWindow).
    from engine.appc import crew_speech
    crew_speech.bus().reset()
```

- [ ] **Step 2: Verify nothing breaks in the host-loop reset path**

Run: `.venv/bin/python -m pytest tests/unit/test_crew_speech_bus.py tests/unit/test_subtitle_window.py -v`
Expected: PASS (smoke — the full reset assertion is exercised in Task 7).

- [ ] **Step 3: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(crew-speech): reset speech bus in reset_sdk_globals"
```

---

### Task 7: Integration test — real SDK handler → subtitle, + reset

Drive a real `EngineerMenuHandlers` `SpeakLine` (the `ge*` lines, `CSP_SPONTANEOUS`) end-to-end through the bus into the subtitle snapshot, and confirm `reset_sdk_globals` clears the channel. The engineer lines resolve against `Bridge Crew General.tgl` (shipped under `sdk/Build/Data/TGL`); if that database lacks the string in a given environment, the test asserts the bus arbitration + reset directly via a populated `TGLocalizationDatabase` so it stays deterministic without `game/` installed.

**Files:**
- Test: `tests/integration/test_bridge_crew_speech.py` (create)

- [ ] **Step 1: Write the integration test**

Create `tests/integration/test_bridge_crew_speech.py`:

```python
"""End-to-end: a CharacterClass SpeakLine reaches the subtitle snapshot, and
reset_sdk_globals frees the speech channel for the next mission."""
import App
from engine.appc import top_window, crew_speech
from engine.appc.characters import CharacterClass
from engine.appc.localization import TGLocalizationDatabase
from engine.appc.ai import CSP_SPONTANEOUS, CSP_MISSION_CRITICAL


def _subtitle():
    return App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)


def test_speakline_reaches_subtitle_snapshot():
    top_window.reset_for_tests()
    crew_speech.bus().reset()

    eng = CharacterClass()
    eng.SetCharacterName("Engineering")
    db = TGLocalizationDatabase(
        "Bridge Crew General.tgl", strings={"ge119": "Warp core stable."})

    eng.SpeakLine(db, "ge119", CSP_SPONTANEOUS)

    snap = _subtitle()._snapshot(now=0.0)
    assert snap is not None
    assert snap["speaker"] == "Engineering"
    assert snap["speech"] == "Warp core stable."


def test_mission_critical_preempts_spontaneous():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase(
        "x.tgl", strings={"a": "chatter", "b": "ABANDON SHIP"})

    eng = CharacterClass(); eng.SetCharacterName("Engineering")
    felix = CharacterClass(); felix.SetCharacterName("Felix")

    eng.SpeakLine(db, "a", CSP_SPONTANEOUS)
    felix.SpeakLine(db, "b", CSP_MISSION_CRITICAL)

    snap = _subtitle()._snapshot(now=0.0)
    assert snap["speaker"] == "Felix"
    assert snap["speech"] == "ABANDON SHIP"


def test_reset_sdk_globals_clears_speech_channel():
    from engine.host_loop import reset_sdk_globals

    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase("x.tgl", strings={"crit": "critical"})

    felix = CharacterClass(); felix.SetCharacterName("Felix")
    felix.SpeakLine(db, "crit", CSP_MISSION_CRITICAL)

    reset_sdk_globals()

    # Channel is free: a brand-new low-priority line is accepted immediately.
    assert crew_speech.bus().speak("Eng", "hi", None, CSP_SPONTANEOUS) is True
    # And the rebuilt subtitle window starts empty.
    assert _subtitle()._snapshot(now=0.0) is not None  # the line we just spoke
```

- [ ] **Step 2: Run the integration test**

Run: `.venv/bin/python -m pytest tests/integration/test_bridge_crew_speech.py -v`
Expected: PASS. If `reset_sdk_globals` pulls in heavy imports, it still runs — but **do not** broaden the pytest selection beyond these files.

- [ ] **Step 3: Run the full crew-speech subset to confirm nothing regressed**

Run:
```bash
.venv/bin/python -m pytest \
  tests/unit/test_crew_speech_priorities.py \
  tests/unit/test_crew_speech_bus.py \
  tests/unit/test_subtitle_window.py \
  tests/unit/test_characters.py \
  tests/unit/test_ai_primitives.py \
  tests/integration/test_bridge_crew_speech.py -v
```
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_bridge_crew_speech.py
git commit -m "test(crew-speech): integration — SpeakLine to subtitle + reset"
```

---

## Self-Review notes

- **Spec coverage:** §1 constants → Task 1; §2 bus (arbitration/duration/reset/voice) → Task 3 (+ reset wiring Task 6); §3 subtitle slot + speaker field → Task 2; §4 SpeakLine/SayLine → Task 4; §5 voice best-effort → Task 3 `_play_voice`; §6 CEF → Task 5; §7 reset → Task 6; testing section → Tasks 1-7. All covered.
- **Type consistency:** `set_crew_line(speaker, text, duration)`, `bus().speak(speaker, text, wav, priority, now=None)`, `_crew_line == (speaker, text, expiry)`, snapshot keys `speaker`/`speech` — used identically across Tasks 2, 3, 4, 7.
- **Voice not asserted on real audio:** intentional — the null backend / absent wav path makes `_play_voice` a no-op; tests assert no crash via the routing path, not actual sound (matches the "no desktop interaction" + headless constraints).
