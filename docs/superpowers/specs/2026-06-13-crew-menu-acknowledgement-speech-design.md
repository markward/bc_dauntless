# Crew Menu Acknowledgement Speech — Design

**Date:** 2026-06-13
**Status:** Approved (design); implementation pending
**Feature line:** crew-menu cluster → **crew speech** (`SpeakLine`/`SayLine` + `CSP_*`, merged `00a119a`) → **menu-interaction acknowledgement** (this slice).
**Builds on:** `docs/superpowers/specs/2026-06-13-bridge-crew-speech-design.md` and the memory note `project_crew_menu_panel.md`.

## Goal

Make interacting with a crew menu produce spoken dialogue. Today F1–F5 open the
CEF crew menus but no one talks, because the "Yes Captain" acknowledgement runs
through a different code path than the `SpeakLine`/`SayLine` we shipped:
`BridgeHandlers.CharacterInteraction` builds a `CharacterAction(AT_SAY_LINE, …)`
and calls `.Play()`, and our `CharacterAction` inherits the no-op
`TGAction.Play()`. Our F1–F5 path goes through `CrewMenuPanel`, which never
invokes `CharacterInteraction` at all.

This slice delivers:

1. **Opening a crew menu** (F1–F5 or CEF title click) → the officer
   acknowledges (subtitle + best-effort voice).
2. **Issuing an order** (clicking a command button) → the officer acknowledges.
3. **`CharacterAction(AT_SPEAK_LINE/AT_SAY_LINE).Play()` routes through the
   speech bus**, so mission-scripted dialogue actions and the SDK's own
   `CharacterInteraction` (3D-bridge crewman click) also speak.

## Key facts established during brainstorming

- The F1–F5 menus are the **TacticalControlWindow interface menus** (built by
  `Bridge/TacticalMenuHandlers.CreateMenus` etc.), **not** the character dialog
  trees. `TacticalMenuHandlers.py:227` builds the menu from
  `pTacticalMenuPane.GetInteriorPane().GetFirstChild()`, a standalone pane — it
  is **not** `pCharacter.GetMenu()`. So the SDK's resolution
  (`pCharacter.GetMenu().GetObjID() == idOpenMenu`, `BridgeHandlers.py:597`)
  does not apply here; we resolve menu → character by **label**.
- Canonical bridge character names (set-object keys): `Tactical`, `Helm`,
  `Science`, `XO`, `Engineer` (`CharacterClass_GetObject(pSet, "...")`).
- Menu labels differ from character names for two officers: menu **"Commander"**
  → character **"XO"**; menu **"Engineering"** → character **"Engineer"**
  (already documented in `crew_menu_hotkeys._event_map`).
- `CharacterAction` ctor is `(character, action_type, detail, set_name, flag,
  database, priority)`; for a speak action `detail` is the line ID,
  `set_name` the addressee, `database` the TGL DB.
- `CharacterInteraction` line selection (`BridgeHandlers.py:647-652`): if
  `pCharacter.GetYesSir()` use that key against `MissionLib.GetMissionDatabase()`,
  else `pCharacter.GetCharacterName() + "Sir" + str(rand(5)+1)` against
  `pCharacter.GetDatabase()`.

## Decisions (resolved during brainstorming)

1. **Trigger:** on menu **open** AND on **order issue** (command-button click).
2. **Ack visibility:** **subtitle + voice** (reusing the merged
   `CrewSpeechBus`/`_SubtitleWindow` crew slot with its speaker field), with a
   guaranteed-visible `"Aye, Captain."` fallback when the ack line carries no
   subtitle text. (Stock BC acks are voice-only; this is a deliberate dauntless
   divergence so F1–F5 is visibly verifiable.)
3. **Slice width:** ack helper **plus** `CharacterAction` routing, so
   mission-scripted dialogue and the 3D crewman-click path speak too.

## Components

### 1. `crew_speech.emit(...)` — shared resolution helper

Extract the per-line text/wav resolution currently inlined in
`CharacterClass.SpeakLine`/`SayLine` into one function in
`engine/appc/crew_speech.py`:

```python
def emit(speaker, db, line_id, priority, *, voice_only):
    line = str(line_id)
    text = None
    if not voice_only and db is not None and db.HasString(line):
        t = db.GetString(line)
        text = t if isinstance(t, str) else None   # stub-DB guard
    wav = db.GetFilename(line) if db is not None else None
    if not isinstance(wav, str) or not wav:         # stub-DB / empty guard
        wav = None
    bus().speak(speaker, text, wav, int(priority))
```

`SpeakLine` → `emit(name, db, line, priority, voice_only=False)`; `SayLine` →
`emit(name, db, line, priority, voice_only=True)`. This is a pure refactor of
the merged feature — same `HasString` gate and `isinstance(str)` stub guards,
one home. (A stub DB's `HasString` returns a truthy `_NamedStub`, so the gate
passes, but the `isinstance(str)` check then drops the stub `GetString` result —
exactly the behaviour the merged `SpeakLine` already had.)

### 2. `CharacterAction._do_play` routing

Override `_do_play` on `CharacterAction` (`engine/appc/ai.py`; today it inherits
`TGAction`'s no-op):

```python
def _do_play(self):
    from engine.appc import crew_speech
    at = self._action_type
    if at in (self.AT_SPEAK_LINE, self.AT_SPEAK_LINE_NO_FLAP_LIPS):
        voice_only = False
    elif at in (self.AT_SAY_LINE, self.AT_SAY_LINE_AFTER_TURN):
        voice_only = True
    else:
        return                       # non-speech actions stay no-ops
    name = ""
    char = self._character
    cc = CharacterClass_Cast(char) if char is not None else None
    if cc is not None:
        name = cc.GetCharacterName()
    crew_speech.emit(name, self._database, self._detail,
                     self._priority, voice_only=voice_only)
```

`TGAction.Play()` already calls `_do_play()` then `Completed()`, so sequence
chaining is unaffected. This makes the SDK's own `CharacterInteraction`
(voice-only `AT_SAY_LINE` — faithful) and mission dialogue actions speak.

### 3. `crew_speech.acknowledge(character)` — the visible menu ack

```python
def acknowledge(character):
    if character is None:
        return
    name = character.GetCharacterName()
    yes = character.GetYesSir()
    if yes:
        db = _mission_database()       # MissionLib.GetMissionDatabase(), best-effort
        line = str(yes)
    else:
        db = character.GetDatabase()
        line = name + "Sir" + str(_rand5() + 1)   # 1..5, mirrors SDK
    text = None
    if db is not None and db.HasString(line):
        t = db.GetString(line)
        text = t if isinstance(t, str) else None
    if not text:
        text = "Aye, Captain."         # guaranteed-visible dauntless fallback
    wav = db.GetFilename(line) if db is not None else None
    if not isinstance(wav, str) or not wav:
        wav = None
    bus().speak(name, text, wav, CSP_NORMAL)
```

`_mission_database()` and `_rand5()` wrap `MissionLib.GetMissionDatabase()` and
`App.g_kSystemWrapper.GetRandomNumber(5)` in try/except so a missing collaborator
degrades to (None db, 0) rather than raising — the `"Aye, Captain."` fallback
still fires.

### 4. Menu → character resolution (`engine/ui/crew_menu_hotkeys.py`)

Add, alongside the existing `_event_map`:

```python
_KEY_TO_CHARACTER = {
    "Helm": "Helm", "Tactical": "Tactical", "Commander": "XO",
    "Science": "Science", "Engineering": "Engineer",
}

def resolve_character(menu_label):
    """Map an opened top-level menu's label to its bridge CharacterClass,
    or None. Locale-safe: matches the label against GetString(key) the same
    way the hotkey layer resolves labels."""
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

`CharacterClass_GetObject` auto-vivifies in our shim, so this returns a real
`CharacterClass` even headless (with empty `GetYesSir`/`GetDatabase` → the SirN
path + `"Aye, Captain."` fallback).

### 5. `CrewMenuPanel` triggers (`engine/ui/crew_menu_panel.py`)

- **`toggle_menu`:** after computing the new `_open_menu_id`, if the menu just
  transitioned to **open** (i.e. `_open_menu_id == wid`), resolve the character
  from `menu.GetLabel()` via `crew_menu_hotkeys.resolve_character` and call
  `crew_speech.acknowledge`. Closing fires nothing. Covers F-keys and CEF title
  clicks (both route through `toggle_menu`).
- **`dispatch_event`:** in the existing `ET_ST_BUTTON_CLICKED` branch (leaf
  command click), resolve the **root** menu of the clicked widget
  (`_root_of(wid)`), then `acknowledge` its character.

Both call sites wrap the ack so a resolution miss (unknown label, no bridge set)
is a silent no-op — menu interaction must never break on a speech hiccup.

## Data flow

```
F1-F5 / CEF title click
   → CrewMenuPanel.toggle_menu  (transitions to OPEN)
   → crew_menu_hotkeys.resolve_character(menu.GetLabel())  → CharacterClass
   → crew_speech.acknowledge(char)
   → bus.speak(name, text-or-"Aye, Captain.", wav, CSP_NORMAL)
   → _SubtitleWindow crew slot → SDKMirrorPanel → CEF "Tactical: Aye, Captain."

command-button click
   → CrewMenuPanel.dispatch_event (ET_ST_BUTTON_CLICKED branch)
   → resolve_character(root_menu.GetLabel()) → acknowledge  (same path)

SDK CharacterInteraction / mission CharacterAction.Play()
   → CharacterAction._do_play → crew_speech.emit → bus  (AT_SAY_LINE voice-only,
                                                          AT_SPEAK_LINE subtitle+voice)
```

## Error handling / edge cases

- **Resolution miss** (unknown label / no bridge set): `resolve_character`
  returns None; `acknowledge(None)` is a no-op. Menu still opens.
- **Missing `MissionLib`/`g_kSystemWrapper`**: wrapped; falls back to (None db,
  0) → `"Aye, Captain."` subtitle, no wav.
- **Stub database** (`GetEpisode().GetDatabase()` with no live episode): the
  `isinstance(str)` guards in `emit`/`acknowledge` drop stub text/wav.
- **Double-speak on order-issue**: a command handler that itself `SpeakLine`s
  (e.g. engineer reports) plus our `CSP_NORMAL` ack both reach the bus;
  priority-preempt arbitration resolves to one visible line. Accepted as
  self-correcting (not suppressed).
- **Rapid toggle**: each open transition fires one ack; the bus dedups
  overlapping lines by priority/expiry. Closing never acks.

## Testing

Headless, **focused pytest subsets only** (never the full suite — it OOMs the
machine). No synthetic desktop input.

- **`emit`**: SPEAK (text+voice) vs SAY (voice-only); `HasString=False` ⇒ no
  subtitle; stub-DB text/wav dropped. (`SpeakLine`/`SayLine` tests still green
  after the refactor.)
- **`CharacterAction.Play()`**: `AT_SPEAK_LINE` ⇒ subtitle appears;
  `AT_SAY_LINE` ⇒ no subtitle, voice attempted; a non-speech action type
  (e.g. `AT_MOVE`) ⇒ no bus activity.
- **`acknowledge`**: GetYesSir path; SirN path; `"Aye, Captain."` fallback when
  the line has no string ⇒ subtitle shows speaker + fallback; speaker label set.
- **`resolve_character`**: the 5 labels map to `Tactical/Helm/XO/Science/
  Engineer`; an unknown label ⇒ None.
- **`CrewMenuPanel`**: opening a menu fires an ack (subtitle shows the speaker);
  closing fires none; a leaf command-button click fires an ack for the root
  menu's officer.
- **Integration**: drive a simulated F-key (`_on_talk_to` → `toggle_menu`) and
  assert the subtitle snapshot carries `speaker`/`speech`; `reset_sdk_globals`
  still clears cleanly.

## Out of scope

- Character lip-sync / facial / body animation.
- Per-command bespoke confirmation lines (we use the generic acknowledgement).
- Subtitle positioning modes (`SM_FELIX`/`SM_NONFELIX` stay cosmetic-only).
- Suppressing the ack when a command handler already speaks (bus arbitration
  handles the overlap instead).
