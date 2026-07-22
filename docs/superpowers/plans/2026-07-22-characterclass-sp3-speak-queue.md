# CharacterClass SP3 — SpeakQueue + PhonemeMap + Jaw Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put a faithful owned SpeakQueue + PhonemeMap in front of the existing crew-speech / lip-sync backends, and drive BC's repurposed `Bip01 Ponytail1` jaw bone from a discrete phoneme→viseme openness signal in lock-step with the `SpeakA/E/U` texture swap.

**Architecture:** Own + consolidate (same as SP2). `CharacterClass` owns `SpeakQueue` (thin faithful facade over `crew_speech`) and references a shared `PhonemeMap` (discrete code→viseme). The lip-sync controller resolves each `.LIP` segment through `PhonemeMap` to a `(texture_slot, openness)` pose, crossfades, and drives both the face texture (existing `set_officer_face`) and a new jaw channel (`set_officer_jaw`, applied to Ponytail1 in the C++ pose build).

**Tech Stack:** Python 3 (engine/appc, engine/lip_sync*), C++20 (native/src scenegraph + renderer + host bindings), pybind11 host bindings, pytest + ctest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-22-characterclass-sp3-speak-queue-design.md`.
- `crew_speech` and the lip backends are KEPT as execution backends — never rewritten or dissolved.
- Single-channel crew-speech bus stays; per-character concurrent speaking is OUT of scope.
- Tests patch `engine.host_io._h` / the `crew_speech` funnel — never call `_dauntless_host` directly (`project_host_io_facade`).
- `crew_speech.emit(name, db, line_id, priority)` is THE speech funnel to assert against.
- Any whole-SDK-module stub touched is fixed in BOTH `tools/mission_harness.py` and `tests/conftest.py` (`project_duplicate_sdk_ast_transforms`).
- Renderer bindings called from Python MUST have a wrapper in `engine/renderer.py` or they silently no-op (`project_damage_decals_phase2_branch`).
- Shader/renderer C++ changes need `cmake -B build -S .` reconfigure then `cmake --build build -j` (`feedback_shader_rebuild`, `feedback_host_bindings_build_target`).
- Gate is `scripts/check_tests.sh` (pytest + ctest), NOT `run_tests.sh` (`project_cpp_ctest_not_in_run_tests`). One baselined emitters flake in `tests/known_failures.txt` is unrelated.
- Shared checkout: commit with explicit pathspec only; never `git add -A` / `checkout` / `restore` / `stash` / `reset --hard` (`feedback_shared_checkout_hazards`). Two unrelated files (`engine/appc/objects.py`, `engine/host_loop.py`) are uncommitted in the tree — leave them.
- Branch: `feat/characterclass-sp3-speak-queue` (already created off `main`).
- SP3 is player-visible — final sign-off is Mark's live pass, NOT green tests (`feedback_green_tests_cannot_see_asset_paths`).

---

## File Structure

**Create:**
- `engine/appc/speak_queue.py` — `SpeakQueue` sub-object over `crew_speech`.
- `engine/appc/phoneme_map.py` — `PhonemeMap` (code→`Viseme`) + shared default.
- `engine/appc/lip_phonemes.json` — the discrete code→viseme table (data).
- `tests/unit/test_speak_queue.py`, `tests/unit/test_phoneme_map.py`, `tests/unit/test_lip_sync_discrete.py`
- `native/tests/renderer/officer_jaw_test.cc` — jaw pose + seam-invariant ctest.

**Modify:**
- `engine/appc/characters.py` — forward speak entry points to `SpeakQueue`; construct `SpeakQueue`/`PhonemeMap` refs; vestigial cleanup.
- `engine/lip_sync.py` — discrete-viseme + openness + crossfade; sink grows a jaw channel.
- `engine/lip_sync_runtime.py` — resolve via `PhonemeMap`; sink calls `set_officer_jaw`.
- `engine/renderer.py` — add `set_officer_jaw` wrapper.
- `native/src/scenegraph/include/scenegraph/world.h` — `Instance` jaw state + `set_officer_jaw` decl.
- `native/src/scenegraph/src/world.cc` — `World::set_officer_jaw`.
- `native/src/host/host_bindings.cc` — `set_officer_jaw` binding.
- `native/src/renderer/animation_update.cc` (+ possibly `bridge_pass.cc`) — apply jaw rotation to Ponytail1 in the pose build.
- `native/src/assets/src/model_compose.cc` — confirm/keep Ponytail1 drivable (probe-guided).
- Test migrations: `tests/unit/test_character_state_flags.py`, `tests/unit/test_character_animation_state.py`.

---

## Task 1: Vestigial SP2 cleanup

**Files:**
- Modify: `engine/appc/characters.py` (`__init__` ~line 442/452, `SetLocationName` ~974, lowercase shims ~829-848)
- Modify: `tests/unit/test_character_state_flags.py:125`
- Modify: `tests/unit/test_character_animation_state.py:95-117`

**Interfaces:**
- Produces: nothing new — removes `self._anim_queue`, `self._location_name`, `SetLocationName`, `set_current_animation`, `clear_current_animation`.

- [ ] **Step 1: Confirm zero functional readers (evidence, already gathered — re-verify)**

Run:
```bash
cd /Users/mward/Documents/Projects/bc_dauntless
grep -rn "\.set_current_animation\|\.clear_current_animation" engine/ | grep -v "def "
grep -rn "\.SetLocationName(" sdk/Build/scripts/ engine/ | grep -v App.py
grep -rn "_location_name\|_anim_queue" engine/appc/characters.py
```
Expected: no `engine/` production reader of the lowercase shims; 0 SDK `SetLocationName` call sites; only the `__init__`/comment references in characters.py.

- [ ] **Step 2: Migrate the two transitional tests to the queue model FIRST (they currently use the shims)**

In `tests/unit/test_character_animation_state.py`, replace shim calls with the queue API. Change:
```python
    ch.set_current_animation("PushingButtons", CharacterClass.CAT_NON_INTERRUPTABLE)
```
to:
```python
    ch.SetCurrentAnimation([("PushingButtons", 0.0)], CharacterClass.CAT_NON_INTERRUPTABLE, 0, None)
```
and replace:
```python
    ch.clear_current_animation()
```
with:
```python
    ch.ClearAnimationsOfType(CharacterClass.CAT_NON_INTERRUPTABLE)
```
Apply the same `SetCurrentAnimation([(name, 0.0)], cat, 0, None)` shape to the other `set_current_animation("x", cat)` sites in that file.

In `tests/unit/test_character_state_flags.py:125`, drop `"_anim_queue"` from the slot list:
```python
    for slot in ("_speak_queue", "_position_zoom", "_menu_state"):
```

- [ ] **Step 3: Run the migrated tests to confirm they pass against the current (pre-removal) code**

Run: `uv run pytest tests/unit/test_character_animation_state.py tests/unit/test_character_state_flags.py -q`
Expected: PASS (the queue API already exists from SP2; the slot still exists so the shortened loop still passes).

- [ ] **Step 4: Remove the dead members from `characters.py`**

Delete the lowercase `set_current_animation` and `clear_current_animation` method definitions (~lines 829-848). Delete `self._anim_queue = None` and its comment (~lines 449-452). Delete `self._location_name: str = ""` (~line 442). Delete the `SetLocationName` method (~lines 973-974). Update the two comments that mention `_location_name` at ~591 and ~798-817 to drop the "(vestigial)" clause since the slot is gone (keep the substantive note that turn-back resolves via `GetLocation()`).

- [ ] **Step 5: Run the full character suite**

Run: `uv run pytest tests/unit/test_character_animation_state.py tests/unit/test_character_state_flags.py tests/unit/test_character_action_move.py tests/unit/test_character_anim_queue.py -q`
Expected: PASS (`test_at_set_location_name_updates_location` asserts `GetLocation()`, unaffected).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/characters.py tests/unit/test_character_animation_state.py tests/unit/test_character_state_flags.py
git commit -m "refactor(character): retire SP2 vestigial _anim_queue/_location_name/anim shims"
```

---

## Task 2: SpeakQueue — speak_line / say_line / is_speaking / is_ready_to_speak

**Files:**
- Create: `engine/appc/speak_queue.py`
- Test: `tests/unit/test_speak_queue.py`

**Interfaces:**
- Consumes: `engine.appc.crew_speech.emit(name, db, line_id, priority) -> float`, `crew_speech.is_speaking(name) -> bool`; the owner exposes `GetCharacterName() -> str` and `ClearExtraAnimations() -> None`.
- Produces: `class SpeakQueue(owner)` with `speak_line(db, line, priority) -> float`, `say_line(db, line, addressee, flag, priority) -> float`, `is_speaking() -> int`, `is_ready_to_speak() -> int`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_speak_queue.py
import engine.appc.crew_speech as crew_speech
from engine.appc.speak_queue import SpeakQueue


class _Owner:
    def __init__(self):
        self.name = "Kiska"
        self.cleared = 0
    def GetCharacterName(self):
        return self.name
    def ClearExtraAnimations(self):
        self.cleared += 1


def test_speak_line_clears_interruptable_then_emits(monkeypatch):
    calls = []
    monkeypatch.setattr(crew_speech, "emit",
                        lambda name, db, line, prio: calls.append((name, db, line, prio)) or 3.0)
    owner = _Owner()
    q = SpeakQueue(owner)
    dur = q.speak_line("DB", "gh075", 1)
    assert owner.cleared == 1                      # SpeakHelper clears cats 0,1,5,6
    assert calls == [("Kiska", "DB", "gh075", 1)]  # routed through the one funnel
    assert dur == 3.0


def test_say_line_forwards_optional_priority(monkeypatch):
    calls = []
    monkeypatch.setattr(crew_speech, "emit",
                        lambda name, db, line, prio: calls.append(prio) or 0.0)
    q = SpeakQueue(_Owner())
    q.say_line("DB", "gf020", "Captain", 1, 7)     # 5-arg form: real priority is arg5
    assert calls == [7]


def test_is_ready_to_speak_is_zero_when_queue_empty(monkeypatch):
    monkeypatch.setattr(crew_speech, "is_speaking", lambda name, now=None: False)
    q = SpeakQueue(_Owner())
    assert q.is_ready_to_speak() == 0              # fixes the always-1 Science-guard bug
    assert q.is_speaking() == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_speak_queue.py -q`
Expected: FAIL (`No module named engine.appc.speak_queue`).

- [ ] **Step 3: Write the implementation**

```python
# engine/appc/speak_queue.py
"""SpeakQueue -- CharacterClass's owned faithful facade over crew_speech.

Mirrors BC's per-character speak surface (SpeakHelper/SpeakLine/SayLine +
IsSpeaking/IsReadyToSpeak/AddSoundToQueue, tier-0 reference sec 4.11) in front
of the single-channel crew_speech bus, which stays the execution backend. BC
gives each character its own queue and lets two officers overlap; that
divergence is tracked separately and does not change this facade.
"""
from __future__ import annotations

from engine.appc import crew_speech


class SpeakQueue:
    def __init__(self, owner):
        self._owner = owner
        self._pending: list = []   # AddSoundToQueue enqueue (BC +queue); usually empty

    def _name(self) -> str:
        return self._owner.GetCharacterName()

    # -- SpeakHelper: clear the interruptable anim set, then route to the funnel.
    def _speak_helper(self, db, line, priority) -> float:
        try:
            self._owner.ClearExtraAnimations()     # cats 0,1,5,6 (tier-0 sec 4.11)
        except Exception:
            pass
        return crew_speech.emit(self._name(), db, line, int(priority))

    def speak_line(self, db, line, priority) -> float:
        return self._speak_helper(db, line, priority)

    def say_line(self, db, line, addressee=None, flag=None, priority=0) -> float:
        # addressee/flag are meaningless headless; real priority is the 5th arg.
        return self._speak_helper(db, line, priority)

    def is_speaking(self) -> int:
        return 1 if crew_speech.is_speaking(self._name()) else 0

    def is_ready_to_speak(self) -> int:
        # BC: a sound is queued and ready but not yet playing. Our only enqueuer
        # is add_sound_to_queue (no SDK caller), so this is 0 in practice --
        # which is exactly what unblocks the ScienceCharacterHandlers guard.
        return 1 if self._pending else 0
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_speak_queue.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/speak_queue.py tests/unit/test_speak_queue.py
git commit -m "feat(character): SpeakQueue facade -- SpeakHelper clear + funnel + ready state"
```

---

## Task 3: SpeakQueue — add_sound_to_queue + IsSomeoneSpeaking

**Files:**
- Modify: `engine/appc/speak_queue.py`
- Test: `tests/unit/test_speak_queue.py`

**Interfaces:**
- Produces: `SpeakQueue.add_sound_to_queue(pSound, sound_type, data) -> None`; module fn `someone_speaking() -> int`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_speak_queue.py
from engine.appc import speak_queue as sq


def test_add_sound_to_queue_noop_without_sound():
    q = sq.SpeakQueue(_Owner())
    q.add_sound_to_queue(None, 2, 0)
    assert q.is_ready_to_speak() == 0


def test_add_sound_to_queue_enqueues_non_immediate(monkeypatch):
    monkeypatch.setattr(crew_speech, "is_speaking", lambda name, now=None: False)
    q = sq.SpeakQueue(_Owner())

    class _Snd:
        def __init__(self): self.played = 0
        def Play(self): self.played += 1
    s = _Snd()
    q.add_sound_to_queue(s, 0, 0)          # type != 2 -> enqueue, don't play
    assert s.played == 0
    assert q.is_ready_to_speak() == 1      # now pending


def test_add_sound_to_queue_type2_plays_immediately_when_ready(monkeypatch):
    monkeypatch.setattr(crew_speech, "is_speaking", lambda name, now=None: False)
    q = sq.SpeakQueue(_Owner())

    class _Snd:
        def __init__(self): self.played = 0
        def Play(self): self.played += 1
    s = _Snd()
    q.add_sound_to_queue(s, 2, 0)          # type==2 & ready -> play now
    assert s.played == 1
    assert q.is_ready_to_speak() == 0


def test_someone_speaking_reflects_bus(monkeypatch):
    monkeypatch.setattr(crew_speech, "is_speaking", lambda name, now=None: False)
    b = crew_speech.bus()
    b._active_speaker = ""
    assert sq.someone_speaking() == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_speak_queue.py -q`
Expected: FAIL (`add_sound_to_queue` / `someone_speaking` missing).

- [ ] **Step 3: Implement**

Add to `SpeakQueue`:
```python
    def add_sound_to_queue(self, pSound, sound_type=0, data=0) -> None:
        # BC 0x0066CB90: no-op unless a sound is present. type==2 with the
        # character ready/speaking plays immediately; otherwise enqueue.
        if pSound is None:
            return
        if int(sound_type) == 2 and (self.is_ready_to_speak() or self.is_speaking()):
            try:
                pSound.Play()
            except Exception:
                pass
            return
        self._pending.append(pSound)
```
Add at module level:
```python
def someone_speaking() -> int:
    """BC CharacterClass_IsSomeoneSpeaking (0x00666F00): active-speaker count > 0.
    The crew_speech bus serialises, so the count is 0 or 1."""
    b = crew_speech.bus()
    import time
    return 1 if (b._active_speaker and time.monotonic() < b._active_expiry) else 0
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_speak_queue.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/speak_queue.py tests/unit/test_speak_queue.py
git commit -m "feat(character): SpeakQueue add_sound_to_queue + someone_speaking (faithful, unexercised)"
```

---

## Task 4: Wire CharacterClass speak entry points to the owned SpeakQueue

**Files:**
- Modify: `engine/appc/characters.py` (`__init__` ~453; `SpeakLine`/`SayLine` ~979-993; `IsSpeaking`/`IsReadyToSpeak` ~1194-1197)
- Test: `tests/unit/test_speak_queue.py` (integration section)

**Interfaces:**
- Consumes: `SpeakQueue` (Task 2/3).
- Produces: `CharacterClass._speak_queue` is a live `SpeakQueue`; `SpeakLine`/`SayLine`/`IsSpeaking`/`IsReadyToSpeak` route through it; `CharacterClass.IsSomeoneSpeaking()` classmethod.

- [ ] **Step 1: Write the failing integration test**

```python
# append to tests/unit/test_speak_queue.py
def test_characterclass_speakline_clears_interruptable_and_emits(monkeypatch):
    from engine.appc.characters import CharacterClass
    calls = []
    monkeypatch.setattr(crew_speech, "emit",
                        lambda name, db, line, prio: calls.append((name, line, prio)) or 2.0)
    ch = CharacterClass()
    ch.SetCharacterName("Kiska")
    seen = {"cleared": 0}
    monkeypatch.setattr(ch, "ClearExtraAnimations", lambda: seen.__setitem__("cleared", seen["cleared"] + 1))
    ch.SpeakLine("DB", "gh075", 1)
    assert seen["cleared"] == 1
    assert calls == [("Kiska", "gh075", 1)]


def test_characterclass_isreadytospeak_no_longer_hardcoded_one(monkeypatch):
    from engine.appc.characters import CharacterClass
    monkeypatch.setattr(crew_speech, "is_speaking", lambda name, now=None: False)
    ch = CharacterClass()
    ch.SetCharacterName("Science")
    assert ch.IsReadyToSpeak() == 0        # was a hard 1 (always-return Science bug)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_speak_queue.py::test_characterclass_isreadytospeak_no_longer_hardcoded_one -q`
Expected: FAIL (`IsReadyToSpeak` returns 1).

- [ ] **Step 3: Construct the queue and route through it**

In `characters.py __init__`, replace `self._speak_queue = None` with a lazily-safe construction after the data-bag is set up (place it at the end of `__init__`):
```python
        from engine.appc.speak_queue import SpeakQueue
        self._speak_queue = SpeakQueue(self)
```
Replace the `SpeakLine`/`SayLine` bodies:
```python
    def SpeakLine(self, pDatabase=None, lineID="", priority=CSP_NORMAL, *_) -> None:
        db = pDatabase if pDatabase is not None else self._database
        self._speak_queue.speak_line(db, lineID, priority)

    def SayLine(self, pDatabase=None, lineID="", _addressee=None,
                _flag=None, priority=CSP_NORMAL, *_) -> None:
        db = pDatabase if pDatabase is not None else self._database
        self._speak_queue.say_line(db, lineID, _addressee, _flag, priority)
```
Replace `IsSpeaking`/`IsReadyToSpeak`:
```python
    def IsSpeaking(self) -> int:
        return self._speak_queue.is_speaking()
    def IsReadyToSpeak(self) -> int:
        return self._speak_queue.is_ready_to_speak()
```
Add a classmethod near them:
```python
    @staticmethod
    def IsSomeoneSpeaking() -> int:
        from engine.appc.speak_queue import someone_speaking
        return someone_speaking()
```

- [ ] **Step 4: Run the speak tests + the bridge-officer speech guard**

Run: `uv run pytest tests/unit/test_speak_queue.py tests/host/test_bridge_officer_speech_live.py -q`
Expected: PASS. (Confirms the funnel + interruptable-clear didn't regress live speech.)

- [ ] **Step 5: Commit**

```bash
git add engine/appc/characters.py tests/unit/test_speak_queue.py
git commit -m "feat(character): route SpeakLine/SayLine/IsSpeaking/IsReadyToSpeak through owned SpeakQueue"
```

---

## Task 5: PhonemeMap — discrete code→viseme table

**Files:**
- Create: `engine/appc/phoneme_map.py`, `engine/appc/lip_phonemes.json`
- Test: `tests/unit/test_phoneme_map.py`

**Interfaces:**
- Produces: `Viseme = namedtuple("Viseme", "name openness texture")`; `class PhonemeMap` with `viseme_for(code:int) -> Viseme`; `default_phoneme_map() -> PhonemeMap` (shared singleton). Openness: closed 0.0, partly 0.286, open 1.0, rounded 0.286. Texture: closed→neutral, partly→e, open→a, rounded→u.

- [ ] **Step 1: Write the data file**

```json
{
  "_comment": "BC .LIP phoneme code -> discrete viseme name. Buckets derived from the empirically recovered code->phoneme table (project_lipsync_re_findings). Structurally BC-faithful (3 jaw openness levels); per-code assignment is a tunable reconstruction, not BC's compiled group.",
  "_visemes": {
    "closed":  {"openness": 0.0,   "texture": "neutral"},
    "partly":  {"openness": 0.286, "texture": "e"},
    "open":    {"openness": 1.0,   "texture": "a"},
    "rounded": {"openness": 0.286, "texture": "u"}
  },
  "0": "closed", "1": "closed", "29": "closed", "40": "closed", "43": "closed",
  "56": "open", "59": "open", "64": "open", "115": "open", "139": "open",
  "42": "rounded", "48": "rounded", "50": "rounded",
  "31": "partly", "32": "partly", "33": "partly", "35": "partly", "36": "partly",
  "37": "partly", "38": "partly", "39": "partly", "41": "partly", "46": "partly",
  "47": "partly", "49": "partly", "53": "partly", "54": "partly", "65": "partly",
  "66": "partly", "81": "partly", "96": "partly", "106": "partly", "113": "partly",
  "121": "partly", "142": "partly"
}
```

- [ ] **Step 2: Write the failing test**

```python
# tests/unit/test_phoneme_map.py
from engine.appc.phoneme_map import PhonemeMap, default_phoneme_map, Viseme


def test_bilabials_and_silence_are_closed():
    pm = default_phoneme_map()
    for code in (0, 1, 40, 29, 43):            # sil, closure, M, B, P
        v = pm.viseme_for(code)
        assert v.name == "closed"
        assert v.openness == 0.0
        assert v.texture == "neutral"


def test_open_vowels_are_open():
    pm = default_phoneme_map()
    for code in (56, 64, 115, 139, 59):        # AA, AH x3, AO
        v = pm.viseme_for(code)
        assert v.name == "open" and v.openness == 1.0 and v.texture == "a"


def test_rounded_uses_u_texture_partly_open_jaw():
    pm = default_phoneme_map()
    for code in (50, 42, 48):                   # W, OW, UW
        v = pm.viseme_for(code)
        assert v.name == "rounded" and v.texture == "u"
        assert abs(v.openness - 0.286) < 1e-6


def test_unknown_code_is_closed():
    assert default_phoneme_map().viseme_for(9999).name == "closed"


def test_every_recovered_code_resolves():
    pm = default_phoneme_map()
    codes = [0,1,29,31,32,33,35,36,37,38,39,40,41,42,43,46,47,48,49,50,
             53,54,56,59,64,65,66,81,96,106,113,115,121,139,142]
    assert len(codes) == 35
    for c in codes:
        assert pm.viseme_for(c).name in ("closed", "partly", "open", "rounded")
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/unit/test_phoneme_map.py -q`
Expected: FAIL (`No module named engine.appc.phoneme_map`).

- [ ] **Step 4: Implement**

```python
# engine/appc/phoneme_map.py
"""PhonemeMap: BC .LIP phoneme code -> discrete Viseme (openness + texture).

BC drives the jaw bone (Bip01 Ponytail1) and the SpeakA/E/U face texture from
ONE discrete openness signal with three authored jaw levels. This map is the
shared/global default phoneme group (BC's is compiled in; AddPhoneme/
UsePhonemeGroup are never called). See project_lipsync_re_findings.
"""
from __future__ import annotations

import json
from collections import namedtuple
from pathlib import Path

Viseme = namedtuple("Viseme", "name openness texture")

_PATH = Path(__file__).with_name("lip_phonemes.json")
_CLOSED = Viseme("closed", 0.0, "neutral")


class PhonemeMap:
    def __init__(self, raw: dict):
        specs = raw.get("_visemes", {})
        self._visemes = {
            name: Viseme(name, float(s["openness"]), str(s["texture"]))
            for name, s in specs.items()
        }
        self._by_code = {}
        for key, name in raw.items():
            if key.startswith("_"):
                continue
            self._by_code[int(key)] = self._visemes.get(name, _CLOSED)

    def viseme_for(self, code: int) -> Viseme:
        return self._by_code.get(int(code), _CLOSED)


_default = None


def default_phoneme_map() -> PhonemeMap:
    global _default
    if _default is None:
        _default = PhonemeMap(json.loads(_PATH.read_text()))
    return _default
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/unit/test_phoneme_map.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/phoneme_map.py engine/appc/lip_phonemes.json tests/unit/test_phoneme_map.py
git commit -m "feat(character): PhonemeMap -- discrete code->viseme (openness+texture)"
```

---

## Task 6: Refactor lip_sync controller to discrete visemes + jaw openness

**Files:**
- Modify: `engine/lip_sync.py` (`LipTimeline`, `LipSyncController`)
- Test: `tests/unit/test_lip_sync_discrete.py`

**Interfaces:**
- Consumes: `PhonemeMap.viseme_for(code) -> Viseme`; `LipSegment(code, start, duration)`.
- Produces: `LipTimeline(segments, phoneme_map, t0, xfade=0.06)` with `.pose_at(now) -> (tex_a, tex_b, mix, openness)`; `LipSyncController(sink=fn, phoneme_map=None, xfade=0.06)` where `sink(officer, tex_a, tex_b, mix, openness)`; `.start(officer, segments, t0)`, `.update(now)`, `.stop(officer)`, `.clear()`. Line-done emits `(officer, "neutral", "neutral", 0.0, 0.0)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_lip_sync_discrete.py
from engine.appc.lip_data import LipSegment
from engine.appc.phoneme_map import default_phoneme_map
from engine.lip_sync import LipTimeline, LipSyncController


def test_pose_settles_on_current_viseme_after_xfade():
    pm = default_phoneme_map()
    segs = [LipSegment(56, 0.0, 0.5)]          # AA -> open / a / openness 1.0
    tl = LipTimeline(segs, pm, t0=0.0, xfade=0.06)
    tex_a, tex_b, mix, openness = tl.pose_at(0.3)   # well past xfade
    assert tex_a == "a"
    assert openness == 1.0


def test_pose_crossfades_openness_from_previous_viseme():
    pm = default_phoneme_map()
    # closed (openness 0) -> open (openness 1) at t=0.5, xfade 0.10
    segs = [LipSegment(0, 0.0, 0.5), LipSegment(56, 0.5, 0.5)]
    tl = LipTimeline(segs, pm, t0=0.0, xfade=0.10)
    _, _, _, op_mid = tl.pose_at(0.55)          # 0.05 into the 0.10 xfade -> ~0.5
    assert 0.3 < op_mid < 0.7


def test_controller_emits_jaw_channel_and_neutral_on_done():
    pm = default_phoneme_map()
    events = []
    ctrl = LipSyncController(sink=lambda *a: events.append(a), phoneme_map=pm)
    ctrl.start("Kiska", [LipSegment(56, 0.0, 0.2)], t0=0.0)
    ctrl.update(0.1)
    assert events[-1][0] == "Kiska" and len(events[-1]) == 5   # (name,a,b,mix,openness)
    ctrl.update(0.5)                                            # past end -> neutral+rest
    assert events[-1] == ("Kiska", "neutral", "neutral", 0.0, 0.0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_lip_sync_discrete.py -q`
Expected: FAIL (old `LipTimeline` signature / 4-arg sink).

- [ ] **Step 3: Rewrite `LipTimeline` and `LipSyncController` in `engine/lip_sync.py`**

Replace the `viseme_weights`/`dominant_pair` import line with:
```python
from engine.appc.phoneme_map import default_phoneme_map
```
Replace the `LipTimeline` class body:
```python
class LipTimeline:
    """A spoken line resolved to a discrete-viseme timeline with crossfade.

    Each .LIP segment maps through PhonemeMap to a Viseme (texture + openness).
    At time t the pose is the current viseme, crossfaded from the previous
    viseme's texture/openness over the first `xfade` seconds of the segment.
    """

    def __init__(self, segments, phoneme_map, t0, xfade=0.06):
        self._segs = list(segments)
        self._vis = [phoneme_map.viseme_for(s.code) for s in self._segs]
        self._t0 = float(t0)
        self._xfade = float(xfade)
        self._total = self._segs[-1].end if self._segs else 0.0

    @property
    def total(self) -> float:
        return self._total

    def done(self, now) -> bool:
        return (now - self._t0) >= self._total

    def _index(self, elapsed) -> int:
        for i, s in enumerate(self._segs):
            if elapsed < s.end:
                return i
        return len(self._segs) - 1

    def pose_at(self, now):
        """(tex_a, tex_b, mix, openness) for the renderer sink at `now`."""
        elapsed = now - self._t0
        if not self._segs or elapsed < 0.0 or elapsed >= self._total:
            return ("neutral", "neutral", 0.0, 0.0)
        i = self._index(elapsed)
        cur = self._vis[i]
        into = elapsed - self._segs[i].start
        if self._xfade > 0.0 and into < self._xfade:
            prev = self._vis[i - 1] if i > 0 else Viseme("closed", 0.0, "neutral")
            f = into / self._xfade
            openness = prev.openness * (1.0 - f) + cur.openness * f
            return (prev.texture, cur.texture, f, openness)   # blend prev->cur
        return (cur.texture, cur.texture, 0.0, cur.openness)  # settled on cur
```
Add the `Viseme` import at the top:
```python
from engine.appc.phoneme_map import default_phoneme_map, Viseme
```
Replace `LipSyncController`:
```python
class LipSyncController:
    def __init__(self, sink=None, phoneme_map=None, xfade=0.06):
        self._sink = sink or (lambda *a: None)
        self._pm = phoneme_map if phoneme_map is not None else default_phoneme_map()
        self._xfade = xfade
        self._active: dict = {}

    def start(self, officer, segments, t0):
        self._active[officer] = LipTimeline(segments, self._pm, t0, self._xfade)

    def update(self, now):
        for officer, tl in list(self._active.items()):
            if tl.done(now):
                self._sink(officer, "neutral", "neutral", 0.0, 0.0)
                del self._active[officer]
            else:
                self._sink(officer, *tl.pose_at(now))

    def stop(self, officer):
        if officer in self._active:
            del self._active[officer]
            self._sink(officer, "neutral", "neutral", 0.0, 0.0)

    def clear(self):
        for officer in list(self._active):
            self.stop(officer)
```
Delete the now-unused `_lerp` / `_norm` / `_NEUTRAL` helpers if nothing else references them (grep first; `BlinkScheduler` does not).

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_lip_sync_discrete.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/lip_sync.py tests/unit/test_lip_sync_discrete.py
git commit -m "refactor(lipsync): discrete-viseme timeline + openness/jaw channel + crossfade"
```

---

## Task 7: lip_sync_runtime — drive PhonemeMap + set_officer_jaw

**Files:**
- Modify: `engine/lip_sync_runtime.py`
- Modify: `engine/renderer.py` (add `set_officer_jaw` to the wrapper list)
- Test: `tests/unit/test_lip_sync_discrete.py` (runtime section, with a fake renderer)

**Interfaces:**
- Consumes: `renderer.set_officer_face(iid, a, b, mix)`, NEW `renderer.set_officer_jaw(iid, openness)`.
- Produces: `LipSyncRuntime._sink(name, a, b, mix, openness)` calls both bindings; `_speaking_codes` derived from `PhonemeMap` (codes whose viseme != closed).

- [ ] **Step 1: Add the `set_officer_jaw` wrapper name to `engine/renderer.py`**

In the wrapper list (~line 81) add `"set_officer_jaw"` beside `"set_officer_face"`:
```python
    "set_debug_cylinders", "set_officer_face", "set_officer_jaw", "set_spv_overlay_beams",
```

- [ ] **Step 2: Write the failing runtime test**

```python
# append to tests/unit/test_lip_sync_discrete.py
def test_runtime_sink_drives_face_and_jaw():
    from engine.lip_sync_runtime import LipSyncRuntime

    class _FakeR:
        def __init__(self): self.face = []; self.jaw = []
        def set_officer_face(self, iid, a, b, mix): self.face.append((iid, a, b, mix))
        def set_officer_jaw(self, iid, openness): self.jaw.append((iid, openness))

    class _Ch:
        _character_name = "Kiska"
        _render_instance = 7

    r = _FakeR()
    rt = LipSyncRuntime(r, lambda: [_Ch()])
    rt._sink("Kiska", "a", "a", 0.0, 1.0)
    assert r.face == [(7, "a", "a", 0.0)]
    assert r.jaw == [(7, 1.0)]
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/unit/test_lip_sync_discrete.py::test_runtime_sink_drives_face_and_jaw -q`
Expected: FAIL (`_sink` takes 4 args / no jaw call).

- [ ] **Step 4: Update `lip_sync_runtime.py`**

Replace the `load_viseme_table` import with `from engine.appc.phoneme_map import default_phoneme_map`. In `__init__`, replace the table/controller/speaking-codes setup:
```python
        self._pm = default_phoneme_map()
        self._ctrl = LipSyncController(sink=self._sink, phoneme_map=self._pm)
        # Codes that actually move the mouth (non-closed viseme), for the
        # no-.LIP random-phoneme fallback.
        self._speaking_codes = [c for c in _ALL_LIP_CODES
                                if self._pm.viseme_for(c).name != "closed"]
```
Add the code list near the top of the module:
```python
# The .LIP phoneme codes PhonemeMap knows about (recovered corpus set).
_ALL_LIP_CODES = [0,1,29,31,32,33,35,36,37,38,39,40,41,42,43,46,47,48,49,50,
                  53,54,56,59,64,65,66,81,96,106,113,115,121,139,142]
```
Replace `_sink`:
```python
    def _sink(self, name, slot_a, slot_b, mix, openness=0.0):
        iid = self._resolve(name)
        if iid is not None:
            self._r.set_officer_face(iid, slot_a, slot_b, mix)
            self._r.set_officer_jaw(iid, openness)
```
In `_on_speech`, the `self._ctrl.start(str(speaker), segs, now)` call is unchanged (start no longer takes amplitude). In `update`, the blink branch calls `set_officer_face` only — add a jaw reset so a blink after a line leaves the jaw shut:
```python
            if slot is not None:
                self._r.set_officer_face(iid, slot, slot, 0.0)
                self._r.set_officer_jaw(iid, 0.0)
                self._blinking.add(name)
            elif name in self._blinking:
                self._r.set_officer_face(iid, "neutral", "neutral", 0.0)
                self._r.set_officer_jaw(iid, 0.0)
                self._blinking.discard(name)
```

- [ ] **Step 5: Run the lip-sync suite**

Run: `uv run pytest tests/unit/test_lip_sync_discrete.py -q && uv run pytest -k lip -q`
Expected: PASS (fix or delete any stale test that imported `viseme_weights`/`dominant_pair` or the old 4-arg sink).

- [ ] **Step 6: Commit**

```bash
git add engine/lip_sync_runtime.py engine/renderer.py tests/unit/test_lip_sync_discrete.py
git commit -m "feat(lipsync): runtime drives PhonemeMap + set_officer_jaw openness channel"
```

---

## Task 8: Jaw probe — confirm Ponytail1 skins the mouth in the COMPOSED model

**Files:**
- Use (copy in): `probe_mouth.cc`, `probe_skin.cc` from `/private/tmp/claude-501/-Users-mward-Documents-Projects-bc-dauntless/b7608d57-51e1-4aa9-832b-b2a1f3f94850/scratchpad/`
- Create: `native/tests/renderer/officer_jaw_test.cc` (characterization portion)

**Interfaces:**
- Produces documented constants recorded in the ledger: `kJawBoneName` (expected `"Bip01 Ponytail1"`), the mouth-vert count skinned to it, the bone's rest local rotation axis, and the closed/open angle span (~7°). These feed Task 10's rotation math.

- [ ] **Step 1: Copy the probes into this session's scratchpad and compile**

```bash
cd /Users/mward/Documents/Projects/bc_dauntless
SP=/private/tmp/claude-501/-Users-mward-Documents-Projects-bc-dauntless/b7608d57-51e1-4aa9-832b-b2a1f3f94850/scratchpad
cp "$SP/probe_mouth.cc" ./scratch_probe_mouth.cc 2>/dev/null || true
cp "$SP/probe_skin.cc"  ./scratch_probe_skin.cc  2>/dev/null || true
cmake --build build -j --target nif >/dev/null 2>&1 || cmake -B build -S . >/dev/null
clang++ -std=c++20 -I native/src/nif/include scratch_probe_skin.cc -Wl,-force_load,build/native/src/nif/libnif.a -o /tmp/probe_skin
clang++ -std=c++20 -I native/src/nif/include scratch_probe_mouth.cc -Wl,-force_load,build/native/src/nif/libnif.a -o /tmp/probe_mouth
```
(If the scratchpad path is gone, the probes' source is reconstructable from `project_lipsync_re_findings`; the goal of this step is only to obtain the facts below.)

- [ ] **Step 2: Run the probes and RECORD the findings in the ledger**

Run `/tmp/probe_skin` against a head NIF (e.g. `game/data/Models/Characters/*head*.nif`) and `/tmp/probe_mouth` against `game/data/Animations/mouth_close.NIF`, `mouthopenpartly.NIF`, `mouth_open.NIF`.
Record: (a) which bone the ~18-29 mouth verts skin to (expect `Bip01 Ponytail1`); (b) that bone's rest local rotation in the head frame; (c) the per-clip Ponytail1 rotation (expect ≈114° / ≈116° / ≈121°) and hence the rotation AXIS and the closed→open delta (~7°).

- [ ] **Step 3: Confirm the composed officer model keeps Ponytail1 drivable**

Run:
```bash
grep -n "Ponytail" native/src/assets/src/model_compose.cc native/src/assets/src/skeleton_build.cc
```
Confirm Ponytail1 is an appended real bone (per `project_bc_character_rigid_skinning`) carrying the head's mouth-vert weights — i.e. rotating it moves the mouth verts. Record the bone-index lookup path (`skeleton.bones` by name) for Task 10.

- [ ] **Step 4: Write the characterization ctest (pins the invariant, not the exact float)**

```cpp
// native/tests/renderer/officer_jaw_test.cc  (characterization half)
// Asserts the composed officer skeleton contains a "Bip01 Ponytail1" bone and
// that >= 1 head mouth vertex weights to it. Exact rest angle recorded in the
// ledger; this test guards that the bone survives composition.
#include <gtest/gtest.h>
#include "assets/model_compose.h"
// ... load a real officer body+head, compose, find the bone by name, assert
// index >= 0 and that the grafted head mesh has weights referencing it.
TEST(OfficerJaw, Ponytail1BoneSurvivesComposition) {
    // (fill from the actual compose API surface used by head_weld_seam_test.cc)
    ASSERT_TRUE(true);  // replaced with the real assertion during Step 5
}
```

- [ ] **Step 5: Flesh out the characterization test using `head_weld_seam_test.cc` as the pattern, build, run**

Model the load/compose calls on `native/tests/renderer/head_weld_seam_test.cc`. Register it in the renderer test CMake. Then:
```bash
cmake -B build -S . >/dev/null && cmake --build build -j --target renderer_tests >/dev/null
ctest --test-dir build -R OfficerJaw -V
```
Expected: PASS (bone present, mouth verts weight to it).

- [ ] **Step 6: Commit (probes are scratch — do NOT commit them; commit only the test)**

```bash
rm -f scratch_probe_mouth.cc scratch_probe_skin.cc
git add native/tests/renderer/officer_jaw_test.cc native/src/renderer/CMakeLists.txt
git commit -m "test(jaw): characterize Bip01 Ponytail1 as the mouth/jaw bone in composed officers"
```

---

## Task 9: Instance jaw state + set_officer_jaw binding

**Files:**
- Modify: `native/src/scenegraph/include/scenegraph/world.h` (`Instance` struct + method decl)
- Modify: `native/src/scenegraph/src/world.cc` (`World::set_officer_jaw`)
- Modify: `native/src/host/host_bindings.cc` (binding near `set_officer_face` ~1231)
- Test: `native/tests/renderer/officer_jaw_test.cc`

**Interfaces:**
- Consumes: nothing new.
- Produces: `Instance.jaw_openness` (float, default 0), `Instance.jaw_active` (bool, default false); `World::set_officer_jaw(InstanceId, float openness)`; host binding `set_officer_jaw(id, openness)`.

- [ ] **Step 1: Write the failing ctest**

```cpp
// append to officer_jaw_test.cc
#include "scenegraph/world.h"
TEST(OfficerJaw, SetOfficerJawStoresOpenness) {
    scenegraph::World w;
    auto id = w.create_instance(scenegraph::ModelHandle{});
    w.set_officer_jaw(id, 0.7f);
    const auto* in = w.get(id);
    ASSERT_TRUE(in->jaw_active);
    ASSERT_NEAR(in->jaw_openness, 0.7f, 1e-6f);
}
```

- [ ] **Step 2: Build + run to verify it fails**

Run: `cmake --build build -j --target renderer_tests 2>&1 | tail -5`
Expected: FAIL to compile (`set_officer_jaw` / `jaw_active` undeclared).

- [ ] **Step 3: Add the Instance fields + declaration**

In `world.h`, beside `face_active`/`face_mix` in `struct Instance` add:
```cpp
    bool  jaw_active = false;
    float jaw_openness = 0.0f;   // 0 = closed (rest), 1 = fully open
```
Beside `set_officer_face` declaration add:
```cpp
    void set_officer_jaw(InstanceId id, float openness);
```

- [ ] **Step 4: Implement in `world.cc`**

```cpp
void World::set_officer_jaw(InstanceId id, float openness) {
    if (auto* inst = get(id)) {
        inst->jaw_active = true;
        inst->jaw_openness = openness;
    }
}
```

- [ ] **Step 5: Add the host binding in `host_bindings.cc` (after `set_officer_face`)**

```cpp
    m.def("set_officer_jaw",
          [](scenegraph::InstanceId id, float openness) {
              g_world.set_officer_jaw(id, openness);
          },
          py::arg("id"), py::arg("openness"),
          "Lip-sync: set an officer's jaw openness in [0,1]; drives the "
          "Bip01 Ponytail1 bone. 0 = closed (rest). No-op for a bad id.");
```

- [ ] **Step 6: Build + run to verify it passes**

Run: `cmake -B build -S . >/dev/null && cmake --build build -j 2>&1 | tail -3 && ctest --test-dir build -R OfficerJaw -V`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add native/src/scenegraph/include/scenegraph/world.h native/src/scenegraph/src/world.cc native/src/host/host_bindings.cc native/tests/renderer/officer_jaw_test.cc
git commit -m "feat(jaw): Instance jaw_openness state + set_officer_jaw host binding"
```

---

## Task 10: Apply the jaw rotation to Ponytail1 in the officer pose build

**Files:**
- Modify: `native/src/renderer/animation_update.cc` (post-`eval_channels`, pre-`build_bone_palette`)
- Modify: `native/src/renderer/bridge_pass.cc` if it builds the palette on a settled instance (~273)
- Modify: `native/src/renderer/include/renderer/bone_palette.h` / a small helper as needed
- Test: `native/tests/renderer/officer_jaw_test.cc`

**Interfaces:**
- Consumes: `Instance.jaw_active`, `Instance.jaw_openness`; the bone-index-by-name lookup recorded in Task 8; `kJawAxis` + `kJawMaxDropRad` constants (from Task 8 findings).
- Produces: a driven Ponytail1 local rotation each frame while `jaw_active`; the officer is re-posed every frame while a jaw is active (so the mouth tracks openness).

- [ ] **Step 1: Write the failing ctest — driven openness rotates the mouth verts, closed does not**

```cpp
// append to officer_jaw_test.cc — uses the composed officer + build path
TEST(OfficerJaw, OpennessRotatesMouthVertsSeamStable) {
    // Compose officer; find a mouth vertex (weighted to Ponytail1) and a neck
    // seam vertex (weighted to Bip01 Neck).
    // Build palette with jaw_openness = 0 -> record mouth vert world pos P0.
    // Build palette with jaw_openness = 1 -> record mouth vert world pos P1.
    // ASSERT: |P1 - P0| > epsilon (mouth moved) AND the neck-seam vert moved
    //         < 1e-4 between the two (seam invariant, per head_weld_seam_test).
    ASSERT_TRUE(true);  // replace with real assertions
}
```

- [ ] **Step 2: Build + run to verify it fails**

Run: `cmake --build build -j --target renderer_tests 2>&1 | tail -5 && ctest --test-dir build -R OpennessRotatesMouth -V`
Expected: FAIL (mouth vert does not move — jaw not applied yet).

- [ ] **Step 3: Define the jaw constants (from Task 8) in `bone_palette.h`**

```cpp
// From the mouth_*.NIF probe (project_lipsync_re_findings): Ponytail1 rotates
// ~7 degrees between mouth_close and mouth_open about <axis from probe>.
inline constexpr float kJawMaxDropRad = 0.122173f;   // ~7 deg (RECORD exact from Task 8)
inline constexpr glm::vec3 kJawAxis = {1.0f, 0.0f, 0.0f};  // RECORD exact from Task 8
inline constexpr char kJawBoneName[] = "Bip01 Ponytail1";
```

- [ ] **Step 4: Apply the rotation in the pose build**

In `animation_update.cc`, after `locals` is produced and before `build_bone_palette`, add:
```cpp
        if (inst.jaw_active && inst.jaw_openness > 0.0f) {
            apply_jaw_rotation(*m, locals, inst.jaw_openness);
        }
```
Add a helper (in `bone_palette.cc`/`.h` or a small `jaw.cc`):
```cpp
void apply_jaw_rotation(const assets::Model& model,
                        std::vector<glm::mat4>& locals, float openness) {
    int bi = find_bone_index(model.skeleton, kJawBoneName);   // by name (Task 8)
    if (bi < 0 || bi >= (int)locals.size()) return;
    float ang = kJawMaxDropRad * glm::clamp(openness, 0.0f, 1.0f);
    locals[bi] = locals[bi] * glm::rotate(glm::mat4(1.0f), ang, kJawAxis);
}
```
Ensure the officer re-poses every frame while jaw is active: in `animation_update.cc`, the early `if (!inst.anim.dirty) return;` skips settled instances — extend it so a jaw-active officer is not skipped:
```cpp
        if (!inst.anim.dirty && !inst.jaw_active) return;
```
If `bridge_pass.cc` builds the palette for a settled instance (`inst.bone_palette.empty()` branch, ~273), route it through the same `apply_jaw_rotation` on a fresh `locals` so a never-animated officer still gets a jaw. (Prefer keeping the single application in `animation_update`; only touch `bridge_pass` if the ctest shows the settled path bypasses it.)

- [ ] **Step 5: Fill in the real ctest assertions (Step 1) and iterate to green**

Use `head_weld_seam_test.cc` for the compose + palette-build API. Then:
```bash
cmake -B build -S . >/dev/null && cmake --build build -j 2>&1 | tail -3
ctest --test-dir build -R "OfficerJaw|OpennessRotatesMouth|HeadWeldSeam" -V
```
Expected: mouth-move + seam-invariant PASS; `head_weld_seam_test` still PASS.

- [ ] **Step 6: Commit**

```bash
git add native/src/renderer/animation_update.cc native/src/renderer/bone_palette.cc native/src/renderer/include/renderer/bone_palette.h native/tests/renderer/officer_jaw_test.cc
git commit -m "feat(jaw): drive Bip01 Ponytail1 from openness in the officer pose build"
```

---

## Task 11: Full gate + whole-branch verification

**Files:** none (verification only).

- [ ] **Step 1: Run the gate**

Run: `scripts/check_tests.sh`
Expected: exit 0; the only failure named is the baselined emitters flake in `tests/known_failures.txt`. Any other failure is a regression this branch introduced — fix it before proceeding.

- [ ] **Step 2: Confirm no whole-SDK-module stub was needed (or fixed in BOTH lists)**

Run: `grep -rn "AddSoundToQueue\|IsSomeoneSpeaking\|set_officer_jaw" tools/mission_harness.py tests/conftest.py`
Expected: nothing requiring a stub change. If a module was stubbed, confirm the fix landed in both files.

- [ ] **Step 3: Sanity-check the branch diff scope**

Run: `git status --short && git log --oneline main..HEAD`
Expected: only SP3 files changed; the two unrelated uncommitted files (`engine/appc/objects.py`, `engine/host_loop.py`) remain uncommitted and untouched.

- [ ] **Step 4: Hand off for whole-branch code review + Mark's live pass**

Do NOT claim done. Report gate results and request `superpowers:requesting-code-review` (whole-branch), then Mark's in-game live pass (crew speech + lip-sync + the new jaw motion — the parts green tests cannot see).

---

## Self-Review Notes

- **Spec coverage:** §4.1 SpeakQueue → Tasks 2-4; §4.2 PhonemeMap + controller → Tasks 5-6; §4.3 jaw → Tasks 8-10; §4.4 data flow → Task 7; §5 cleanup → Task 1; §7 testing → per-task + Task 11; §2 fidelity fixes (interruptable clear, IsReadyToSpeak) → Tasks 2 & 4.
- **Runtime-discovered values:** `kJawAxis` / `kJawMaxDropRad` are recorded from the Task 8 probe, not invented — Task 10 Step 3 flags them explicitly. This is a spike-then-implement seam, not a placeholder.
- **Type consistency:** sink is 5-arg `(officer, tex_a, tex_b, mix, openness)` in Tasks 6 and 7; `Viseme(name, openness, texture)` consistent across Tasks 5-6; `set_officer_jaw(id, openness)` consistent across Tasks 7, 9, 10.
