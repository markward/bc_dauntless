# Crew Menu Acknowledgement Speech Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make crew-menu interaction talk — opening a menu (F1–F5 / CEF title click) and issuing an order fire a subtitle+voice acknowledgement, and `CharacterAction(AT_SPEAK_LINE/AT_SAY_LINE).Play()` routes through the speech bus so mission dialogue and the 3D crewman-click path speak too.

**Architecture:** Reuse the merged `CrewSpeechBus` + `_SubtitleWindow` crew slot. A shared `crew_speech.emit()` resolves line text/wav and feeds the bus; `CharacterClass.SpeakLine`/`SayLine` and the new `CharacterAction._do_play` all call it. A `crew_speech.acknowledge(character)` produces the visible menu ack (with an `"Aye, Captain."` fallback). `crew_menu_hotkeys.resolve_character()` maps an opened menu's label to its bridge `CharacterClass`; `CrewMenuPanel` fires the ack on open and on command-button click.

**Tech Stack:** Python 3 (engine shims under `engine/`), pytest.

**Spec:** `docs/superpowers/specs/2026-06-13-crew-menu-acknowledgement-speech-design.md`

**Project constraints (read before running anything):**
- **NEVER run the full pytest suite** — it OOMs the machine (>100 GB RAM). Run only the focused files named in each task via `.venv/bin/python -m pytest <files>`.
- No synthetic desktop input for verification.

---

### Task 1: `crew_speech.emit()` + refactor `SpeakLine`/`SayLine` onto it

Extract the line-resolution logic (currently duplicated/inlined in `SpeakLine`/`SayLine`) into one helper. Pure refactor — identical behavior.

**Files:**
- Modify: `engine/appc/crew_speech.py` (add `emit` near `bus()`)
- Modify: `engine/appc/characters.py:483-512` (`SpeakLine`/`SayLine` bodies)
- Test: `tests/unit/test_crew_speech_emit.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_crew_speech_emit.py`:

```python
"""crew_speech.emit — shared line resolution feeding the bus."""
from engine.appc import top_window, crew_speech
from engine.appc.localization import TGLocalizationDatabase
from engine.appc.ai import CSP_NORMAL


def _subtitle():
    import App
    return App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)


def test_emit_speak_routes_text_and_wav():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase("x.tgl", strings={"L1": "Shields holding"})
    crew_speech.emit("Tactical", db, "L1", CSP_NORMAL, voice_only=False)
    snap = _subtitle()._snapshot(now=0.0)
    assert snap["speaker"] == "Tactical"
    assert snap["speech"] == "Shields holding"


def test_emit_voice_only_sets_no_subtitle():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase("x.tgl", strings={"L1": "Shields holding"})
    crew_speech.emit("XO", db, "L1", CSP_NORMAL, voice_only=True)
    assert _subtitle()._snapshot(now=0.0) is None


def test_emit_missing_string_shows_no_subtitle():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase("x.tgl")  # no strings -> HasString False
    crew_speech.emit("Eng", db, "ge119", CSP_NORMAL, voice_only=False)
    assert _subtitle()._snapshot(now=0.0) is None


def test_emit_none_db_is_safe():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    crew_speech.emit("Eng", None, "ge119", CSP_NORMAL, voice_only=False)
    assert _subtitle()._snapshot(now=0.0) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/test_crew_speech_emit.py -v`
Expected: FAIL — `AttributeError: module 'engine.appc.crew_speech' has no attribute 'emit'`.

- [ ] **Step 3: Add `emit` to `engine/appc/crew_speech.py`**

Insert immediately above the `_bus: Optional[CrewSpeechBus] = None` line:

```python
def emit(speaker, db, line_id, priority, *, voice_only) -> None:
    """Resolve a line's subtitle text (unless voice_only) and voice wav from a
    localization DB, then feed the speech bus. Single home for the HasString
    gate + isinstance(str) stub-DB guards shared by SpeakLine/SayLine and
    CharacterAction speak actions."""
    line = str(line_id)
    text = None
    if not voice_only and db is not None and db.HasString(line):
        t = db.GetString(line)
        text = t if isinstance(t, str) else None   # drop stub-DB repr
    wav = db.GetFilename(line) if db is not None else None
    if not isinstance(wav, str) or not wav:         # drop stub-DB / empty
        wav = None
    bus().speak(speaker, text, wav, int(priority))
```

- [ ] **Step 4: Refactor `SpeakLine`/`SayLine` in `engine/appc/characters.py`**

Replace the two methods (currently lines 483-512) with:

```python
    def SpeakLine(self, pDatabase=None, lineID="", priority=CSP_NORMAL, *_) -> None:
        # SDK call shape is uniformly SpeakLine(db, lineID, priority) (or the
        # 2-arg form with the default priority); no addressee arg.
        db = pDatabase if pDatabase is not None else self._database
        crew_speech.emit(self._character_name, db, lineID, priority, voice_only=False)

    def SayLine(self, pDatabase=None, lineID="", _addressee=None,
                _flag=None, priority=CSP_NORMAL, *_) -> None:
        # SDK SayLine has a 4-arg and a (dominant) 5-arg form:
        #   SayLine(db, lineID, "Captain", 1)                       -> default priority
        #   SayLine(db, lineID, "Captain", 1, App.CSP_SPONTANEOUS)  -> explicit priority
        # arg3 is the addressee and arg4 a flag; both are meaningless headless.
        # The real priority is the OPTIONAL 5th arg. Voice-only acknowledgement.
        db = pDatabase if pDatabase is not None else self._database
        crew_speech.emit(self._character_name, db, lineID, priority, voice_only=True)
```

- [ ] **Step 5: Run tests to verify pass (new + the merged feature's tests still green)**

Run:
```bash
.venv/bin/python -m pytest tests/unit/test_crew_speech_emit.py tests/unit/test_characters.py tests/unit/test_crew_speech_bus.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/appc/crew_speech.py engine/appc/characters.py tests/unit/test_crew_speech_emit.py
git commit -m "refactor(crew-speech): extract crew_speech.emit; SpeakLine/SayLine use it"
```

---

### Task 2: `CharacterAction._do_play` routing

Make the SDK's `CharacterAction(AT_SPEAK_LINE/AT_SAY_LINE).Play()` speak through the bus. Non-speech action types stay no-ops.

**Files:**
- Modify: `engine/appc/ai.py` — add `_do_play` to `CharacterAction` (after `UseNameAndSetInsteadOfObject`, ~line 1093)
- Test: `tests/unit/test_character_action_speech.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_character_action_speech.py`:

```python
"""CharacterAction speak action-types route through the speech bus."""
from engine.appc import top_window, crew_speech
from engine.appc.characters import CharacterClass
from engine.appc.ai import CharacterAction, CharacterAction_Create, CSP_NORMAL
from engine.appc.localization import TGLocalizationDatabase


def _subtitle():
    import App
    return App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)


def _char(name):
    c = CharacterClass()
    c.SetCharacterName(name)
    return c


def test_speak_line_action_shows_subtitle():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase("x.tgl", strings={"L1": "Course laid in"})
    a = CharacterAction_Create(_char("Helm"), CharacterAction.AT_SPEAK_LINE,
                               "L1", "Captain", 0, db, CSP_NORMAL)
    a.Play()
    snap = _subtitle()._snapshot(now=0.0)
    assert snap["speaker"] == "Helm"
    assert snap["speech"] == "Course laid in"


def test_say_line_action_sets_no_subtitle():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase("x.tgl", strings={"ack": "Aye sir"})
    a = CharacterAction_Create(_char("XO"), CharacterAction.AT_SAY_LINE,
                               "ack", "Captain", 0, db, CSP_NORMAL)
    a.Play()
    assert _subtitle()._snapshot(now=0.0) is None


def test_non_speech_action_is_silent():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    a = CharacterAction_Create(_char("Helm"), CharacterAction.AT_MOVE,
                               None, None, 0, None, CSP_NORMAL)
    a.Play()  # must not raise, must not speak
    assert _subtitle()._snapshot(now=0.0) is None
    assert crew_speech.bus()._active_priority == -1  # channel untouched
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/test_character_action_speech.py -v`
Expected: FAIL — `test_speak_line_action_shows_subtitle` fails (no subtitle; `_do_play` is the inherited no-op).

- [ ] **Step 3: Add `_do_play` to `CharacterAction` in `engine/appc/ai.py`**

Immediately after the `UseNameAndSetInsteadOfObject` method (before `def CharacterAction_Create`), add:

```python
    def _do_play(self) -> None:
        # Route the speak action-types through the shared speech bus; every
        # other action type (MOVE/TURN/GLANCE/...) stays a Phase-1 no-op.
        # Lazy imports avoid an ai<->characters/crew_speech import cycle.
        at = self._action_type
        if at in (self.AT_SPEAK_LINE, self.AT_SPEAK_LINE_NO_FLAP_LIPS):
            voice_only = False
        elif at in (self.AT_SAY_LINE, self.AT_SAY_LINE_AFTER_TURN):
            voice_only = True
        else:
            return
        from engine.appc import crew_speech
        from engine.appc.characters import CharacterClass_Cast
        cc = CharacterClass_Cast(self._character) if self._character is not None else None
        name = cc.GetCharacterName() if cc is not None else ""
        crew_speech.emit(name, self._database, self._detail,
                         self._priority, voice_only=voice_only)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/bin/python -m pytest tests/unit/test_character_action_speech.py tests/unit/test_ai_primitives.py -v`
Expected: PASS (new + existing CharacterAction tests).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/ai.py tests/unit/test_character_action_speech.py
git commit -m "feat(crew-speech): route CharacterAction speak actions through the bus"
```

---

### Task 3: `crew_speech.acknowledge(character)`

The visible menu ack, mirroring `CharacterInteraction`'s line selection, with a guaranteed-visible `"Aye, Captain."` fallback.

**Files:**
- Modify: `engine/appc/crew_speech.py` (add `acknowledge` + `_mission_database`/`_rand5` helpers)
- Test: `tests/unit/test_crew_ack.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_crew_ack.py`:

```python
"""crew_speech.acknowledge — the visible (subtitle+voice) menu ack."""
from engine.appc import top_window, crew_speech
from engine.appc.characters import CharacterClass
from engine.appc.localization import TGLocalizationDatabase


def _subtitle():
    import App
    return App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)


def _char(name):
    c = CharacterClass()
    c.SetCharacterName(name)
    return c


def test_ack_none_character_is_noop():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    crew_speech.acknowledge(None)  # must not raise
    assert _subtitle()._snapshot(now=0.0) is None


def test_ack_falls_back_to_aye_captain_when_no_line(monkeypatch):
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    monkeypatch.setattr(crew_speech, "_rand5", lambda: 0)
    char = _char("Tactical")  # no YesSir, no database -> fallback
    crew_speech.acknowledge(char)
    snap = _subtitle()._snapshot(now=0.0)
    assert snap["speaker"] == "Tactical"
    assert snap["speech"] == "Aye, Captain."


def test_ack_sirN_path_uses_character_database(monkeypatch):
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    monkeypatch.setattr(crew_speech, "_rand5", lambda: 0)  # -> "Sir1"
    char = _char("Helm")
    char.SetDatabase(TGLocalizationDatabase("x.tgl", strings={"HelmSir1": "Aye, sir."}))
    crew_speech.acknowledge(char)
    snap = _subtitle()._snapshot(now=0.0)
    assert snap["speaker"] == "Helm"
    assert snap["speech"] == "Aye, sir."


def test_ack_yessir_path_uses_mission_database(monkeypatch):
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase("m.tgl", strings={"FelixYes": "On it, Captain."})
    monkeypatch.setattr(crew_speech, "_mission_database", lambda: db)
    char = _char("Tactical")
    char.SetYesSir("FelixYes")
    crew_speech.acknowledge(char)
    snap = _subtitle()._snapshot(now=0.0)
    assert snap["speech"] == "On it, Captain."
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/test_crew_ack.py -v`
Expected: FAIL — `AttributeError: module 'engine.appc.crew_speech' has no attribute 'acknowledge'`.

- [ ] **Step 3: Add `acknowledge` + helpers to `engine/appc/crew_speech.py`**

Insert immediately above the `_bus: Optional[CrewSpeechBus] = None` line (after `emit`):

```python
def _mission_database():
    """MissionLib.GetMissionDatabase(), best-effort (None if unavailable)."""
    try:
        import MissionLib
        return MissionLib.GetMissionDatabase()
    except Exception:
        return None


def _rand5() -> int:
    """App.g_kSystemWrapper.GetRandomNumber(5) (0..4), best-effort -> 0."""
    try:
        import App
        return int(App.g_kSystemWrapper.GetRandomNumber(5))
    except Exception:
        return 0


def acknowledge(character) -> None:
    """Spoken acknowledgement for a bridge officer (subtitle + best-effort
    voice). Mirrors BridgeHandlers.CharacterInteraction's line selection;
    falls back to a literal 'Aye, Captain.' so the ack is always visible."""
    if character is None:
        return
    from engine.appc.ai import CSP_NORMAL
    name = character.GetCharacterName()
    yes = character.GetYesSir()
    if yes:
        db = _mission_database()
        line = str(yes)
    else:
        db = character.GetDatabase()
        line = name + "Sir" + str(_rand5() + 1)   # 1..5
    text = None
    if db is not None and db.HasString(line):
        t = db.GetString(line)
        text = t if isinstance(t, str) else None
    if not text:
        text = "Aye, Captain."                      # guaranteed-visible fallback
    wav = db.GetFilename(line) if db is not None else None
    if not isinstance(wav, str) or not wav:
        wav = None
    bus().speak(name, text, wav, CSP_NORMAL)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/bin/python -m pytest tests/unit/test_crew_ack.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/crew_speech.py tests/unit/test_crew_ack.py
git commit -m "feat(crew-speech): acknowledge() menu ack with Aye-Captain fallback"
```

---

### Task 4: `crew_menu_hotkeys.resolve_character()`

Map an opened menu's label to its bridge `CharacterClass`.

**Files:**
- Modify: `engine/ui/crew_menu_hotkeys.py` (add `_KEY_TO_CHARACTER` + `resolve_character`)
- Test: `tests/unit/test_crew_menu_hotkeys.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_crew_menu_hotkeys.py`:

```python
def test_resolve_character_maps_labels_to_officers():
    from engine.ui import crew_menu_hotkeys
    from engine.appc.characters import CharacterClass
    # Headless TGL falls back to the key, so label == key here.
    for label, expected in [
        ("Tactical", "Tactical"), ("Helm", "Helm"), ("Science", "Science"),
        ("Commander", "XO"), ("Engineering", "Engineer"),
    ]:
        char = crew_menu_hotkeys.resolve_character(label)
        assert isinstance(char, CharacterClass)
        assert char.GetCharacterName() == expected


def test_resolve_character_unknown_label_is_none():
    from engine.ui import crew_menu_hotkeys
    assert crew_menu_hotkeys.resolve_character("Bogus Menu") is None
```

Note: `CharacterClass_GetObject` auto-vivifies a character into the bridge set under the looked-up name and `SetCharacterName`s it, so `GetCharacterName()` returns the officer name even with an empty bridge set.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/test_crew_menu_hotkeys.py -k resolve_character -v`
Expected: FAIL — `AttributeError: module 'engine.ui.crew_menu_hotkeys' has no attribute 'resolve_character'`.

- [ ] **Step 3: Add the map + resolver to `engine/ui/crew_menu_hotkeys.py`**

After the `_event_map()` function, add:

```python
# Menu label (TGL key) -> bridge CharacterClass set-object name. Two officers
# differ: menu "Commander" is character "XO"; menu "Engineering" is "Engineer".
_KEY_TO_CHARACTER = {
    "Helm": "Helm", "Tactical": "Tactical", "Commander": "XO",
    "Science": "Science", "Engineering": "Engineer",
}


def resolve_character(menu_label):
    """Map an opened top-level menu's label to its bridge CharacterClass, or
    None. Locale-safe: matches the label against GetString(key) the same way
    the hotkey layer resolves labels."""
    import App
    db = App.g_kLocalizationManager.Load("data/TGL/Bridge Menus.tgl")
    try:
        for key, char_name in _KEY_TO_CHARACTER.items():
            if str(db.GetString(key)) == str(menu_label):
                bridge = App.g_kSetManager.GetSet("bridge")
                return App.CharacterClass_GetObject(bridge, char_name)
    finally:
        App.g_kLocalizationManager.Unload(db)
    return None
```

- [ ] **Step 4: Run tests to verify pass**

Run: `.venv/bin/python -m pytest tests/unit/test_crew_menu_hotkeys.py -v`
Expected: PASS (new + existing hotkey tests).

- [ ] **Step 5: Commit**

```bash
git add engine/ui/crew_menu_hotkeys.py tests/unit/test_crew_menu_hotkeys.py
git commit -m "feat(crew-speech): resolve_character maps menu label to bridge officer"
```

---

### Task 5: `CrewMenuPanel` triggers (open + order)

Fire the ack when a menu opens and when a command button is clicked.

**Files:**
- Modify: `engine/ui/crew_menu_panel.py` — `toggle_menu` (~line 140) and `dispatch_event` click branch (~line 135)
- Test: `tests/unit/test_crew_menu_panel.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_crew_menu_panel.py`:

```python
def test_opening_menu_fires_acknowledgement():
    import App
    from engine.appc import top_window, crew_speech
    from engine.appc.characters import STTopLevelMenu
    from engine.appc.windows import TacticalControlWindow
    from engine.ui.crew_menu_panel import CrewMenuPanel

    top_window.reset_for_tests()
    crew_speech.bus().reset()
    tcw = TacticalControlWindow.GetInstance()
    menu = STTopLevelMenu("Tactical")          # label == TGL-key fallback
    tcw.AddMenuToList(menu)

    panel = CrewMenuPanel()
    panel.toggle_menu(menu)                     # opens -> ack

    sub = App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)
    snap = sub._snapshot(now=0.0)
    assert snap is not None
    assert snap["speaker"] == "Tactical"


def test_closing_menu_fires_no_acknowledgement():
    import App
    from engine.appc import top_window, crew_speech
    from engine.appc.characters import STTopLevelMenu
    from engine.appc.windows import TacticalControlWindow
    from engine.ui.crew_menu_panel import CrewMenuPanel

    top_window.reset_for_tests()
    crew_speech.bus().reset()
    tcw = TacticalControlWindow.GetInstance()
    menu = STTopLevelMenu("Tactical")
    tcw.AddMenuToList(menu)

    panel = CrewMenuPanel()
    panel.toggle_menu(menu)   # open (acks)
    crew_speech.bus().reset() # clear channel
    top_window.reset_for_tests()
    panel.toggle_menu(menu)   # close -> no ack

    sub = App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)
    assert sub._snapshot(now=0.0) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/unit/test_crew_menu_panel.py -k acknowledge -v`
Expected: FAIL — `test_opening_menu_fires_acknowledgement` finds no subtitle (no ack wired).

- [ ] **Step 3: Wire the ack in `toggle_menu`**

In `engine/ui/crew_menu_panel.py`, replace the body of `toggle_menu` (lines 146-152) with:

```python
        if not isinstance(menu, STMenu) or not menu.IsEnabled():
            return
        wid = ensure_widget_id(menu)
        opening = self._open_menu_id != wid
        self._open_menu_id = None if self._open_menu_id == wid else wid
        # Open menu changed (toggle always closes or switches) — a reopened
        # menu starts with all submenus collapsed.
        self._expanded_ids.clear()
        if opening:
            self._acknowledge(menu)
```

- [ ] **Step 4: Wire the ack in `dispatch_event` (order issue) and add the `_acknowledge` helper**

In the `click:` branch, after the `ET_ST_BUTTON_CLICKED` block (after line 135, inside `if isinstance(widget, STButton):`), add the order ack on the root menu:

```python
                if root is not None:
                    self._acknowledge(root)
```

So that block reads:

```python
            if isinstance(widget, STButton):
                widget.SendActivationEvent()
                if root is not None:
                    import App
                    clicked = App.TGEvent_Create()
                    clicked.SetEventType(App.ET_ST_BUTTON_CLICKED)
                    clicked.SetDestination(root)
                    clicked.SetSource(widget)
                    App.g_kEventManager.AddEvent(clicked)
                    self._acknowledge(root)
```

Add the helper method (place it just below `toggle_menu`):

```python
    def _acknowledge(self, menu) -> None:
        """Fire the owning officer's spoken acknowledgement. A resolution miss
        (unknown label / no bridge set) is a silent no-op — menu interaction
        must never break on a speech hiccup."""
        try:
            from engine.ui import crew_menu_hotkeys
            from engine.appc import crew_speech
            char = crew_menu_hotkeys.resolve_character(menu.GetLabel())
            crew_speech.acknowledge(char)
        except Exception:
            _logger.debug("crew-menu ack failed", exc_info=True)
```

- [ ] **Step 5: Run tests to verify pass (new + all existing panel tests)**

Run: `.venv/bin/python -m pytest tests/unit/test_crew_menu_panel.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add engine/ui/crew_menu_panel.py tests/unit/test_crew_menu_panel.py
git commit -m "feat(crew-speech): crew menu open + order-issue fire officer ack"
```

---

### Task 6: Integration test — F-key → spoken ack

Drive the real hotkey path (`_on_talk_to` → `toggle_menu`) and confirm a subtitle appears; confirm `reset_sdk_globals` stays clean.

**Files:**
- Test: `tests/integration/test_crew_menu_ack.py` (create)

- [ ] **Step 1: Write the integration test**

Create `tests/integration/test_crew_menu_ack.py`:

```python
"""End-to-end: an F-key talk-to event opens a crew menu and the officer
acknowledges (subtitle reaches the snapshot)."""
import App
from engine.appc import top_window, crew_speech
from engine.appc.characters import STTopLevelMenu
from engine.appc.windows import TacticalControlWindow
from engine.ui.crew_menu_panel import CrewMenuPanel
from engine.ui import crew_menu_hotkeys


def _subtitle():
    return App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)


def test_fkey_talk_to_opens_menu_and_acknowledges():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    tcw = TacticalControlWindow.GetInstance()
    # Tactical menu present under its label (headless TGL -> key fallback).
    tcw.AddMenuToList(STTopLevelMenu("Tactical"))

    panel = CrewMenuPanel()
    crew_menu_hotkeys.wire(tcw, panel)

    # Simulate the TALK_TO_TACTICAL event the host feeds from F2.
    evt = App.TGIntEvent_Create() if hasattr(App, "TGIntEvent_Create") else App.TGEvent_Create()
    evt.SetEventType(App.ET_INPUT_TALK_TO_TACTICAL)
    crew_menu_hotkeys._on_talk_to(tcw, evt)

    assert panel.has_open_menu() is True
    snap = _subtitle()._snapshot(now=0.0)
    assert snap is not None
    assert snap["speaker"] == "Tactical"


def test_reset_sdk_globals_clean_after_ack():
    from engine.host_loop import reset_sdk_globals
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    tcw = TacticalControlWindow.GetInstance()
    tcw.AddMenuToList(STTopLevelMenu("Tactical"))
    panel = CrewMenuPanel()
    panel.toggle_menu(tcw.FindMenu("Tactical"))   # acks
    reset_sdk_globals()
    assert crew_speech.bus().speak("Eng", "x", None, App.CSP_SPONTANEOUS) is True
```

- [ ] **Step 2: Run the integration test**

Run: `.venv/bin/python -m pytest tests/integration/test_crew_menu_ack.py -v`
Expected: 2 PASS. If `_on_talk_to`'s label lookup misses (TGL nuance), capture the failure and report — do not patch production to force green without checking.

- [ ] **Step 3: Run the full focused subset to confirm no regressions**

Run:
```bash
.venv/bin/python -m pytest \
  tests/unit/test_crew_speech_emit.py \
  tests/unit/test_crew_speech_bus.py \
  tests/unit/test_crew_ack.py \
  tests/unit/test_character_action_speech.py \
  tests/unit/test_characters.py \
  tests/unit/test_crew_menu_hotkeys.py \
  tests/unit/test_crew_menu_panel.py \
  tests/unit/test_subtitle_window.py \
  tests/integration/test_bridge_crew_speech.py \
  tests/integration/test_crew_menu_ack.py -v
```
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_crew_menu_ack.py
git commit -m "test(crew-speech): integration -- F-key talk-to opens menu + acks"
```

---

## Self-Review notes

- **Spec coverage:** §1 `emit` → Task 1; §2 `CharacterAction._do_play` → Task 2; §3 `acknowledge` + fallback → Task 3; §4 `resolve_character` → Task 4; §5 panel open/order triggers → Task 5; testing → Tasks 1-6. All covered.
- **Type/name consistency:** `crew_speech.emit(speaker, db, line_id, priority, *, voice_only)`, `crew_speech.acknowledge(character)`, `crew_speech._rand5`/`_mission_database` (monkeypatched in tests by those exact names), `crew_menu_hotkeys.resolve_character(menu_label)`, `CrewMenuPanel._acknowledge(menu)` — used identically across tasks.
- **Import-cycle safety:** `CharacterAction._do_play` and `CrewMenuPanel._acknowledge` use deferred imports (`ai`↔`characters`/`crew_speech`, `panel`→`hotkeys`); `acknowledge` imports `CSP_NORMAL` lazily so `crew_speech` keeps its stdlib-only module top-level.
- **Double-speak on order-issue:** intentional per spec — bus arbitration resolves the overlap; not suppressed.
