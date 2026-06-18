# Subtitles Toggle (Configuration › Gameplay) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** All spoken dialogue (SpeakLine, SayLine, acks) shows subtitles, gated by a new Subtitles on/off toggle under a Gameplay tab in the Configuration panel (default ON, live, not persisted).

**Architecture:** A module-level Subtitles flag in `crew_speech` gates subtitle *display* at the single `_route_subtitle` choke point; `emit` now resolves subtitle text for every line (the vestigial `voice_only` parameter is removed). The Configuration panel gains a Gameplay tab carrying the toggle, wired in `host_loop` to the flag setter, and rendered by the CEF `configuration_panel.js`.

**Tech Stack:** Python 3 (engine shim + UI panel), CEF JavaScript (loaded from `file://`, no rebuild), pytest.

**Design doc:** `docs/superpowers/specs/2026-06-18-subtitles-toggle-gameplay-design.md`

## Global Constraints

- Pure-Python + CEF JS only. **No native rebuild** (CEF assets load via `file://`).
- Default **ON**; applies live; **not persisted** across launches (consistent with every other setting in this panel).
- The flag gates **display only**. Line duration and voice playback are unaffected — `emit` still resolves text (for the duration estimate fallback) and `bus.speak` still plays the voice; only `set_crew_line` is suppressed when off.
- Subtitle gate lives at **one choke point** (`CrewSpeechBus._route_subtitle`) so SpeakLine, SayLine, and `acknowledge()` are covered uniformly.
- `voice_only` is removed entirely (in BC, SpeakLine vs SayLine differ in lip-sync/turning, not subtitle visibility).
- Run focused tests while iterating; full suite via `scripts/run_tests.sh` (memory cap).
- SDK scripts are ground truth.

---

## File Structure

- `engine/appc/crew_speech.py` — Subtitles flag (`_subtitles_enabled` + `set_subtitles_enabled`/`subtitles_enabled`); `emit` drops `voice_only` + always resolves text; `_route_subtitle` gates on the flag.
- `engine/appc/characters.py` — `SpeakLine`/`SayLine` drop the `voice_only=` kwarg.
- `engine/appc/ai.py` — `CharacterAction._do_play` drops the `voice_only` branch (membership check + single emit).
- `engine/ui/configuration_panel.py` — `SettingsSnapshot.subtitles_on`; `set_subtitles` applier; `toggle:subtitles`; Gameplay-tab focusables + input.
- `engine/host_loop.py` — add the Gameplay tab, initial `subtitles_on`, `set_subtitles` applier.
- `native/assets/ui-cef/js/configuration_panel.js` — Gameplay-tab focusables + body render + dispatch.
- Tests: `tests/unit/test_crew_speech_emit.py`, `tests/unit/test_crew_speech_bus.py`, `tests/unit/test_configuration_panel.py`.

---

## Task 1: crew_speech — Subtitles flag, gate, and drop `voice_only`

**Files:**
- Modify: `engine/appc/crew_speech.py`
- Modify: `engine/appc/characters.py` (`SpeakLine` ~512, `SayLine` ~518)
- Modify: `engine/appc/ai.py` (`CharacterAction._do_play` ~1119)
- Test: `tests/unit/test_crew_speech_emit.py`, `tests/unit/test_crew_speech_bus.py`

**Interfaces:**
- Produces: `crew_speech.set_subtitles_enabled(on: bool) -> None`, `crew_speech.subtitles_enabled() -> bool`, `crew_speech.emit(speaker, db, line_id, priority) -> float` (no `voice_only`).

- [ ] **Step 1: Update the emit tests (remove `voice_only`, repurpose the voice-only test)**

In `tests/unit/test_crew_speech_emit.py`: remove `voice_only=...` from all four `emit(...)` calls, and replace `test_emit_voice_only_sets_no_subtitle` with a subtitles-disabled test. The file's `_subtitle()` helper and the other three tests stay (minus the kwarg):

```python
def test_emit_speak_routes_text_and_wav():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase("x.tgl", strings={"L1": "Shields holding"})
    crew_speech.emit("Tactical", db, "L1", CSP_NORMAL)
    snap = _subtitle()._snapshot(now=0.0)
    assert snap["speaker"] == "Tactical"
    assert snap["speech"] == "Shields holding"


def test_emit_say_line_now_routes_subtitle():
    # SayLine-style line (previously voice_only=True -> no subtitle). With the
    # voice_only distinction removed, a line with text routes a subtitle like
    # any other spoken line.
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase("x.tgl", strings={"L1": "Shields holding"})
    crew_speech.emit("XO", db, "L1", CSP_NORMAL)
    snap = _subtitle()._snapshot(now=0.0)
    assert snap is not None
    assert snap["speech"] == "Shields holding"


def test_emit_no_subtitle_when_subtitles_disabled():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase("x.tgl", strings={"L1": "Shields holding"})
    crew_speech.set_subtitles_enabled(False)
    try:
        crew_speech.emit("XO", db, "L1", CSP_NORMAL)
        assert _subtitle()._snapshot(now=0.0) is None
    finally:
        crew_speech.set_subtitles_enabled(True)


def test_emit_missing_string_shows_no_subtitle():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    db = TGLocalizationDatabase("x.tgl")  # no strings -> HasString False
    crew_speech.emit("Eng", db, "ge119", CSP_NORMAL)
    assert _subtitle()._snapshot(now=0.0) is None


def test_emit_none_db_is_safe():
    top_window.reset_for_tests()
    crew_speech.bus().reset()
    crew_speech.emit("Eng", None, "ge119", CSP_NORMAL)
    assert _subtitle()._snapshot(now=0.0) is None
```

- [ ] **Step 2: Add the duration-unaffected test**

Append to `tests/unit/test_crew_speech_bus.py` (it already imports `CrewSpeechBus`):

```python
def test_subtitles_disabled_does_not_affect_duration():
    # The subtitle flag gates display only — a text-only line still returns its
    # estimated duration so the sequence still gates on it.
    from engine.appc.crew_speech import set_subtitles_enabled
    bus = CrewSpeechBus()
    set_subtitles_enabled(False)
    try:
        dur = bus.speak("Liu", "A briefing line here", None, 1, now=0.0)
        assert dur > 0.0
    finally:
        set_subtitles_enabled(True)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_crew_speech_emit.py tests/unit/test_crew_speech_bus.py -k "say_line_now_routes or no_subtitle_when_subtitles_disabled or subtitles_disabled_does_not_affect" -v`
Expected: FAIL — `crew_speech.set_subtitles_enabled` does not exist yet; and (after that's added) `emit()` still rejects the removed `voice_only` only once the signature changes. The `say_line_now_routes` test fails today because `emit` requires `voice_only`.

- [ ] **Step 4: Implement the flag in `crew_speech.py`**

Add module-level state near the top constants (after `_WORDS_PER_SECOND = 2.5`):

```python
# Global subtitle display flag (Configuration > Gameplay). Gates on-screen text
# only — line duration + voice playback are unaffected. Default ON; applied live
# by the configuration panel; not persisted across launches.
_subtitles_enabled: bool = True


def set_subtitles_enabled(on: bool) -> None:
    global _subtitles_enabled
    _subtitles_enabled = bool(on)


def subtitles_enabled() -> bool:
    return _subtitles_enabled
```

- [ ] **Step 5: Gate `_route_subtitle` on the flag**

In `CrewSpeechBus._route_subtitle`, return early when subtitles are off (add as the first line of the method body):

```python
    def _route_subtitle(self, speaker, text, duration) -> None:
        if not subtitles_enabled():
            return
        try:
            import App
            sub = App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)
        except Exception:
            sub = None
        if sub is not None and hasattr(sub, "set_crew_line"):
            sub.set_crew_line(speaker, text, duration)
```

- [ ] **Step 6: Drop `voice_only` from `emit` and always resolve text**

Replace the `emit` signature + text-resolution block:

```python
def emit(speaker, db, line_id, priority) -> float:
    """Resolve a line's subtitle text and voice wav from a localization DB,
    then feed the speech bus. Single home for the HasString gate +
    isinstance(str) stub-DB guards shared by SpeakLine/SayLine and
    CharacterAction speak actions. Subtitle *display* is gated globally by
    subtitles_enabled() inside the bus; text is always resolved here so the
    duration estimate (text-only lines) is unaffected by the toggle."""
    line = str(line_id)
    text = None
    if db is not None and db.HasString(line):
        t = db.GetString(line)
        text = t if isinstance(t, str) else None   # drop stub-DB repr
    wav = db.GetFilename(line) if db is not None else None
    if not isinstance(wav, str) or not wav:         # drop stub-DB / empty
        wav = None
    return bus().speak(speaker, text, wav, int(priority))
```

- [ ] **Step 7: Update the three `emit` call sites**

`engine/appc/characters.py` — `SpeakLine` and `SayLine` (drop the `voice_only=` kwarg):

```python
    def SpeakLine(self, pDatabase=None, lineID="", priority=CSP_NORMAL, *_) -> None:
        db = pDatabase if pDatabase is not None else self._database
        crew_speech.emit(self._character_name, db, lineID, priority)

    def SayLine(self, pDatabase=None, lineID="", _addressee=None,
                _flag=None, priority=CSP_NORMAL, *_) -> None:
        db = pDatabase if pDatabase is not None else self._database
        crew_speech.emit(self._character_name, db, lineID, priority)
```

`engine/appc/ai.py` — `CharacterAction._do_play` (collapse the SPEAK/SAY `voice_only` branch into a single membership check):

```python
    def _do_play(self):
        at = self._action_type
        if at not in (self.AT_SPEAK_LINE, self.AT_SPEAK_LINE_NO_FLAP_LIPS,
                      self.AT_SAY_LINE, self.AT_SAY_LINE_AFTER_TURN):
            return 0.0
        from engine.appc import crew_speech
        from engine.appc.characters import CharacterClass_Cast
        cc = CharacterClass_Cast(self._character) if self._character is not None else None
        if cc is not None:
            name = cc.GetCharacterName()
        elif isinstance(self._character, str):
            name = self._character
        else:
            name = ""
        return crew_speech.emit(name, self._database, self._detail,
                                self._priority) or 0.0
```

- [ ] **Step 8: Run the focused tests to verify they pass**

Run: `uv run pytest tests/unit/test_crew_speech_emit.py tests/unit/test_crew_speech_bus.py tests/unit/test_character_action_speech.py tests/unit/test_crew_ack.py -v`
Expected: PASS (all). The repurposed + new tests pass; `acknowledge()` and `SpeakLine` paths unaffected (they already resolved text; only the new flag gate is added, default ON).

- [ ] **Step 9: Commit**

```bash
git add engine/appc/crew_speech.py engine/appc/characters.py engine/appc/ai.py tests/unit/test_crew_speech_emit.py tests/unit/test_crew_speech_bus.py
git commit -m "feat(crew_speech): global Subtitles flag gates display; drop vestigial voice_only"
```

---

## Task 2: ConfigurationPanel — Gameplay tab + Subtitles setting

**Files:**
- Modify: `engine/ui/configuration_panel.py`
- Test: `tests/unit/test_configuration_panel.py`

**Interfaces:**
- Consumes: an injected `set_subtitles: Callable[[bool], None]`.
- Produces: `SettingsSnapshot(subtitles_on=...)`; the panel handles `toggle:subtitles` and renders `subtitles_on` in its payload; Gameplay-tab focusables include `("ctrl", "subtitles")`.

- [ ] **Step 1: Update the test factory + add Gameplay/subtitles tests**

In `tests/unit/test_configuration_panel.py`, add `set_subtitles=Mock()` to the `_make` factory's kwargs dict (the constructor will require it). Then append these tests:

```python
def test_render_payload_includes_subtitles_on():
    p, _ = _make()
    p.open()
    payload = p.render_payload()
    data = json.loads(payload[len("setConfigurationPanel("):-len(");")])
    assert data["settings"]["subtitles_on"] is True


def test_toggle_subtitles_flips_and_calls_applier():
    p, kwargs = _make()
    p.open()
    p.dispatch_event("toggle:subtitles")
    kwargs["set_subtitles"].assert_called_once_with(False)
    # state reflects the new value
    payload = p.render_payload()
    data = json.loads(payload[len("setConfigurationPanel("):-len(");")])
    assert data["settings"]["subtitles_on"] is False


def test_gameplay_tab_focusables_include_subtitles():
    p, _ = _make(tabs=[("graphics", "Graphics"), ("gameplay", "Gameplay")])
    p.dispatch_event("tab:gameplay")
    focusables = p._focusables()
    assert ("ctrl", "subtitles") in focusables
    # graphics controls are not present on the gameplay tab
    assert ("ctrl", "dust") not in focusables


def test_initial_subtitles_off_round_trips():
    p, _ = _make(initial_settings=SettingsSnapshot(
        dust_on=True, specular_on=True, hdr_on=True, rim_on=True,
        decals_on=True, hull_damage_on=True, fov_deg=70, subtitles_on=False,
    ))
    p.open()
    payload = p.render_payload()
    data = json.loads(payload[len("setConfigurationPanel("):-len(");")])
    assert data["settings"]["subtitles_on"] is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_configuration_panel.py -k "subtitles or gameplay" -v`
Expected: FAIL — `set_subtitles` is not a constructor param yet and `subtitles_on` is not in the snapshot/payload.

- [ ] **Step 3: Add `subtitles_on` to `SettingsSnapshot`**

In `engine/ui/configuration_panel.py`:

```python
@dataclass
class SettingsSnapshot:
    dust_on: bool
    specular_on: bool
    hdr_on: bool
    rim_on: bool
    decals_on: bool
    hull_damage_on: bool
    fov_deg: int
    fxaa_on: bool = True
    subtitles_on: bool = True
```

- [ ] **Step 4: Thread `set_subtitles` + `subtitles_on` through the constructor**

Add the `set_subtitles` parameter (after `set_fxaa`) and copy `subtitles_on`:

```python
                 set_fxaa: Callable[[bool], None],
                 set_subtitles: Callable[[bool], None],
                 set_fov_rad: Callable[[float], None]):
        super().__init__()
        self._tabs = list(tabs)
        self._selected_tab = tabs[0][0]
        self._settings = SettingsSnapshot(
            dust_on=initial_settings.dust_on,
            specular_on=initial_settings.specular_on,
            hdr_on=initial_settings.hdr_on,
            rim_on=initial_settings.rim_on,
            decals_on=initial_settings.decals_on,
            hull_damage_on=initial_settings.hull_damage_on,
            fxaa_on=initial_settings.fxaa_on,
            fov_deg=int(initial_settings.fov_deg),
            subtitles_on=initial_settings.subtitles_on,
        )
        self._set_dust = set_dust
        self._set_specular = set_specular
        self._set_hdr = set_hdr
        self._set_rim = set_rim
        self._set_decals = set_decals
        self._set_hull_damage = set_hull_damage
        self._set_fxaa = set_fxaa
        self._set_subtitles = set_subtitles
        self._set_fov_rad = set_fov_rad
```

- [ ] **Step 5: Include `subtitles_on` in `render_payload`**

Add `self._settings.subtitles_on` to the `snapshot` tuple (after `fxaa_on`) and to the `settings` dict:

```python
        snapshot = (
            self._visible,
            tuple(self._tabs),
            self._selected_tab,
            self._focused,
            self._settings.dust_on,
            self._settings.specular_on,
            self._settings.hdr_on,
            self._settings.rim_on,
            self._settings.decals_on,
            self._settings.hull_damage_on,
            self._settings.fxaa_on,
            self._settings.subtitles_on,
            self._settings.fov_deg,
        )
```

and in the payload dict:

```python
            "settings": {
                "dust_on": self._settings.dust_on,
                "specular_on": self._settings.specular_on,
                "hdr_on": self._settings.hdr_on,
                "rim_on": self._settings.rim_on,
                "decals_on": self._settings.decals_on,
                "hull_damage_on": self._settings.hull_damage_on,
                "fxaa_on": self._settings.fxaa_on,
                "subtitles_on": self._settings.subtitles_on,
                "fov_deg": self._settings.fov_deg,
            },
```

- [ ] **Step 6: Handle `toggle:subtitles` in `dispatch_event`**

Add after the `toggle:fxaa` branch:

```python
        if action == "toggle:subtitles":
            new_val = not self._settings.subtitles_on
            self._set_subtitles(new_val)
            self._settings.subtitles_on = new_val
            return True
```

- [ ] **Step 7: Add Gameplay-tab focusables + input**

In `_focusables`, add the gameplay branch (after the graphics branch):

```python
        out: list = [("tab", tid) for tid, _ in self._tabs]
        if self._selected_tab == "graphics":
            out += [("ctrl", "dust"), ("ctrl", "specular"), ("ctrl", "fov"),
                    ("ctrl", "hdr"), ("ctrl", "rim"), ("ctrl", "decals"),
                    ("ctrl", "hull_damage"), ("ctrl", "fxaa")]
        elif self._selected_tab == "gameplay":
            out += [("ctrl", "subtitles")]
        return out
```

In `handle_input`, add a branch in the activate chain (after the `fxaa` branch):

```python
        elif activate and kind == "ctrl" and target == "subtitles":
            self.dispatch_event("toggle:subtitles")
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_configuration_panel.py -v`
Expected: PASS (all — the `_make` factory now supplies `set_subtitles`, and the new tests pass).

- [ ] **Step 9: Commit**

```bash
git add engine/ui/configuration_panel.py tests/unit/test_configuration_panel.py
git commit -m "feat(ui): Gameplay tab + Subtitles toggle in ConfigurationPanel"
```

---

## Task 3: Wire the Gameplay tab + Subtitles applier in host_loop

**Files:**
- Modify: `engine/host_loop.py` (ConfigurationPanel construction ~2877)

**Interfaces:**
- Consumes: `crew_speech.subtitles_enabled` / `set_subtitles_enabled` (Task 1); `ConfigurationPanel(set_subtitles=..., SettingsSnapshot(subtitles_on=...))`, tabs list (Task 2).

- [ ] **Step 1: Add the Gameplay tab, initial value, and applier**

In `engine/host_loop.py`, update the `ConfigurationPanel(...)` construction. Add a local import of `crew_speech` near the panel construction (matching the existing late-import style), set the tabs, the initial `subtitles_on`, and the `set_subtitles` applier:

```python
        from engine.ui.configuration_panel import (
            ConfigurationPanel, SettingsSnapshot,
        )
        from engine.appc import crew_speech as _crew_speech
        configuration_panel = ConfigurationPanel(
            tabs=[("graphics", "Graphics"), ("gameplay", "Gameplay")],
            initial_settings=SettingsSnapshot(
                dust_on=True,
                specular_on=True,
                hdr_on=True,
                rim_on=True,
                decals_on=True,
                hull_damage_on=True,
                fxaa_on=True,
                fov_deg=int(round(_math.degrees(
                    director.fov_y_rad
                ))),
                subtitles_on=_crew_speech.subtitles_enabled(),
            ),
            set_dust=r.set_dust_enabled,
            set_specular=r.set_specular_enabled,
            set_hdr=r.set_hdr_enabled,
            set_rim=r.set_rim_enabled,
            set_decals=r.set_decals_enabled,
            set_hull_damage=r.set_hull_damage_enabled,
            set_fxaa=r.set_fxaa_enabled,
            set_subtitles=_crew_speech.set_subtitles_enabled,
            set_fov_rad=director.set_fov,
        )
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `uv run python -c "import ast; ast.parse(open('engine/host_loop.py').read()); print('host_loop.py parses OK')"`
Expected: `host_loop.py parses OK`. (host_loop is not unit-tested in isolation — it needs the full renderer; the panel wiring is verified live in Task 5, and the panel itself is unit-covered in Task 2.)

- [ ] **Step 3: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(host): wire Gameplay tab + Subtitles applier into ConfigurationPanel"
```

---

## Task 4: CEF render — Gameplay tab body

**Files:**
- Modify: `native/assets/ui-cef/js/configuration_panel.js`

**Interfaces:**
- Consumes: the `settings.subtitles_on` field and `gameplay` tab id from the Python payload (Tasks 2-3).

- [ ] **Step 1: Add the gameplay branch to `_cpFocusableList`**

In `native/assets/ui-cef/js/configuration_panel.js`, extend `_cpFocusableList` (after the `graphics` branch):

```javascript
    if (state.selected_tab === 'graphics') {
        out.push({kind: 'ctrl', target: 'dust'});
        out.push({kind: 'ctrl', target: 'specular'});
        out.push({kind: 'ctrl', target: 'fov'});
        out.push({kind: 'ctrl', target: 'hdr'});
        out.push({kind: 'ctrl', target: 'rim'});
        out.push({kind: 'ctrl', target: 'decals'});
        out.push({kind: 'ctrl', target: 'hull_damage'});
        out.push({kind: 'ctrl', target: 'fxaa'});
    } else if (state.selected_tab === 'gameplay') {
        out.push({kind: 'ctrl', target: 'subtitles'});
    }
```

- [ ] **Step 2: Add a `_cpRenderGameplayBody` function**

Add next to `_cpRenderGraphicsBody` (mirrors the toggle-row markup the graphics toggles use):

```javascript
function _cpRenderGameplayBody(state, focusables) {
    const focused = focusables[state.focused] || {};
    const isFoc = (target) => focused.kind === 'ctrl' && focused.target === target;
    const s = state.settings;
    let html = '';

    // Subtitles toggle
    html += '<div class="cp-row' + (isFoc('subtitles') ? ' cp-focused' : '') + '">'
          +     '<span class="cp-label">Subtitles</span>'
          +     '<button class="cp-toggle' + (s.subtitles_on ? ' cp-toggle--on' : '') + '"'
          +        ' onclick="dauntlessEvent(\'configuration/toggle:subtitles\')">'
          +       (s.subtitles_on ? 'On' : 'Off')
          +     '</button>'
          + '</div>';
    return html;
}
```

- [ ] **Step 3: Dispatch the gameplay body in `setConfigurationPanel`**

Replace the body-render branch so gameplay renders its body instead of falling into the empty `else`:

```javascript
    const body = document.getElementById('cp-body');
    if (body) {
        if (state.selected_tab === 'graphics') {
            body.innerHTML = _cpRenderGraphicsBody(state, focusables);
        } else if (state.selected_tab === 'gameplay') {
            body.innerHTML = _cpRenderGameplayBody(state, focusables);
        } else {
            body.innerHTML = '';
        }
    }
```

- [ ] **Step 4: Sanity-check the JS parses**

Run: `node --check native/assets/ui-cef/js/configuration_panel.js && echo "JS OK"`
Expected: `JS OK`. (If `node` is unavailable, skip — the file is validated live in Task 5.)

- [ ] **Step 5: Commit**

```bash
git add native/assets/ui-cef/js/configuration_panel.js
git commit -m "feat(ui-cef): render Gameplay tab Subtitles toggle"
```

---

## Task 5: Integration regression + live verification

**Files:**
- Test: `tests/unit/` (broad), live GUI (Mark drives)

- [ ] **Step 1: Run the focused unit suites together**

Run: `uv run pytest tests/unit/test_crew_speech_emit.py tests/unit/test_crew_speech_bus.py tests/unit/test_configuration_panel.py tests/unit/test_character_action_speech.py tests/unit/test_crew_ack.py -v`
Expected: PASS (all).

- [ ] **Step 2: Run the broader suite under the watchdog**

Run: `scripts/run_tests.sh`
Expected: PASS within the memory cap. If any `voice_only` reference remains, grep finds it: `grep -rn "voice_only" engine/ tests/` should return nothing.

- [ ] **Step 3: Live verification (Mark drives the GUI)**

Provide these steps for the user (no synthetic desktop interaction):
1. `./build/dauntless --developer` → load E1M1 → trigger the Starbase 12 hail.
2. Expected: Liu's briefing now shows **subtitle text** on screen as he speaks (default ON), in sync with the audio.
3. Open the pause menu → Configuration → **Gameplay** tab → toggle **Subtitles Off** → confirm new dialogue shows no subtitle text but still plays audio; toggle back **On** → subtitles return.

- [ ] **Step 4: Commit any verification notes**

```bash
git commit --allow-empty -m "test(subtitles): integration regression + live verification notes"
```

---

## Self-Review

**Spec coverage:**
- §1 subtitle gate + flag + drop `voice_only` + 3 call sites → Task 1. ✓
- §2 Gameplay tab + Subtitles setting (snapshot/applier/payload/dispatch/focusables/input) → Task 2. ✓
- §3 host_loop wiring → Task 3. ✓
- §4 CEF render → Task 4. ✓
- §5 units/boundaries → each task independently testable (panel without CEF; crew_speech flag direct). ✓
- §6 testing (enabled routes, disabled suppresses, duration unaffected, acks/SpeakLine gated; panel dispatch/payload/focusables) → Tasks 1, 2, 5. ✓
- §7 out of scope (persistence, lip-sync, keybinding) — not implemented. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every run step has a command + expected output.

**Type consistency:** `set_subtitles_enabled(on)`/`subtitles_enabled()` (Task 1) consumed in Task 3; `emit(speaker, db, line_id, priority)` (Task 1) matches the updated call sites and tests; `SettingsSnapshot.subtitles_on` + `set_subtitles` (Task 2) consumed in Task 3; payload key `subtitles_on` (Task 2) consumed by JS in Task 4; focusable `("ctrl","subtitles")` consistent between Task 2 (`_focusables`) and Task 4 (`_cpFocusableList`); dispatch verb `toggle:subtitles` consistent across Task 2 (`dispatch_event`/`handle_input`) and Task 4 (`onclick`).
