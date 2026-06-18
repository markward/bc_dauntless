# Subtitles Toggle (Configuration › Gameplay) — Design

**Date:** 2026-06-18
**Status:** Approved (pending implementation plan)
**Scope:** `engine/appc/crew_speech.py`, `engine/appc/characters.py`,
`engine/appc/ai.py` (CharacterAction), `engine/ui/configuration_panel.py`,
`engine/host_loop.py`, `native/assets/ui-cef/js/configuration_panel.js`.
Pure-Python + CEF JS — no native rebuild (CEF assets load via `file://`).

## Problem

Spoken dialogue is inconsistent about subtitles. `SpeakLine` / `AT_SPEAK_LINE`
and crew acknowledgements (`acknowledge()`) show subtitles, but `SayLine` /
`AT_SAY_LINE` / `AT_SAY_LINE_AFTER_TURN` do not — `crew_speech.emit` is called
with `voice_only=True` for those, which skips subtitle-text resolution. The most
visible consequence: the E1M1 Liu briefing (built from `AT_SAY_LINE`
CharacterActions) plays audio with no on-screen text.

In BC, `SpeakLine` vs `SayLine` differ in lip-sync / turning-to-addressee, **not**
subtitle visibility — both show subtitles when the Options "Subtitles" setting is
on. So `voice_only` is a wrong assumption, and BC gates subtitles with a single
global on/off option, not per-line.

## Decisions

- **All spoken lines resolve subtitle text.** Remove the `voice_only` parameter
  from `emit` and its three call sites (it no longer means anything in our
  engine; lip-sync/turning is unbuilt Phase-2 animation, unrelated to subtitles).
- **A single global Subtitles flag gates display**, applied at one choke point so
  `SpeakLine`, `SayLine`, and `acknowledge()` are all covered uniformly.
- **Exposed as a "Subtitles" toggle under a new "Gameplay" tab** in the existing
  Configuration panel. Default **ON**. Applies live; **not persisted** across
  launches — consistent with every other setting in this panel today.
- **Duration/audio are unaffected by the flag.** Subtitles off suppresses only
  on-screen text; the line's voice still plays and its duration still gates the
  sequence (text is still resolved for the duration estimate fallback).

## §1 — Subtitle display gate (`engine/appc/crew_speech.py`)

- Module-level flag mirroring the `dev_combat_cheats` pattern:
  ```
  _subtitles_enabled = True
  def set_subtitles_enabled(on: bool) -> None: ...
  def subtitles_enabled() -> bool: ...
  ```
- `emit(speaker, db, line_id, priority)` — drop the keyword-only `voice_only`
  parameter. Always resolve subtitle text:
  ```
  text = None
  if db is not None and db.HasString(line):
      t = db.GetString(line)
      text = t if isinstance(t, str) else None   # drop stub-DB repr
  ```
  (wav resolution unchanged.)
- `_route_subtitle(...)` returns early when `not subtitles_enabled()` — the single
  choke point. `bus.speak` still computes duration and plays the voice; only the
  `set_crew_line` call is suppressed. `acknowledge()` (which routes through
  `bus().speak`) is covered by the same gate.
- Call-site updates (drop the `voice_only=` kwarg):
  - `engine/appc/characters.py`: `SpeakLine` and `SayLine`.
  - `engine/appc/ai.py`: `CharacterAction._do_play` (remove the
    `voice_only = False/True` computation; the SPEAK vs SAY action-type branch is
    no longer needed for subtitle purposes — every speak-type emits with text).

Note: `CharacterAction._do_play` still must return `0.0` for non-speak action
types and the emitted duration for the four speak types — only the `voice_only`
distinction within the speak branch is removed.

## §2 — Gameplay tab + Subtitles setting (`engine/ui/configuration_panel.py`)

- `SettingsSnapshot`: add `subtitles_on: bool = True`.
- `__init__`: add `set_subtitles: Callable[[bool], None]`; copy `subtitles_on`
  into the working snapshot; store the applier.
- `render_payload`: include `subtitles_on` in both the change-detection
  `snapshot` tuple and the `settings` payload dict.
- `dispatch_event`: add
  ```
  if action == "toggle:subtitles":
      new_val = not self._settings.subtitles_on
      self._set_subtitles(new_val)
      self._settings.subtitles_on = new_val
      return True
  ```
- `_focusables`: when `self._selected_tab == "gameplay"`, append
  `[("ctrl", "subtitles")]` after the tab rows.
- `handle_input`: on Space/Enter with `kind == "ctrl" and target == "subtitles"`,
  dispatch `toggle:subtitles`.

## §3 — Wiring (`engine/host_loop.py`)

At the `ConfigurationPanel(...)` construction site (~line 2877):
- `tabs=[("graphics", "Graphics"), ("gameplay", "Gameplay")]`.
- `initial_settings=SettingsSnapshot(..., subtitles_on=crew_speech.subtitles_enabled())`.
- `set_subtitles=crew_speech.set_subtitles_enabled`.

(Import `crew_speech` locally at the construction site, matching existing
late-import style.)

## §4 — CEF render (`native/assets/ui-cef/js/configuration_panel.js`)

- Mirror the Python `_focusables` for the gameplay tab: when
  `state.selected_tab === 'gameplay'`, push `{kind:'ctrl', target:'subtitles'}`.
- When `selected_tab === 'gameplay'`, render a Subtitles toggle row reusing the
  existing `cp-row` / `cp-toggle` markup (same shape as the dust/specular
  toggles), wired to `dauntlessEvent('configuration/toggle:subtitles')` and
  reflecting `s.subtitles_on`.
- The graphics-tab rendering is unchanged and only shows when its tab is
  selected.

## §5 — Units, boundaries, dependencies

- **`crew_speech` Subtitles flag** — one purpose: "should spoken-line subtitles
  display." Depends on nothing; read by `_route_subtitle`, set by the applier.
  Unit-testable directly.
- **`ConfigurationPanel` Gameplay tab** — one purpose: surface the toggle and
  fire its applier. Depends on the injected `set_subtitles` callable. Testable
  without CEF (dispatch + payload + focusables).
- **Wiring** (host_loop) binds the applier to the flag setter — the only
  integration point.

## §6 — Testing

- `crew_speech` (`tests/unit/test_crew_speech_bus.py` /
  `test_crew_speech_emit.py`):
  - With subtitles ON, a `SayLine`-style emit (line with text) routes a subtitle
    (`set_crew_line` called with the text); the returned duration is unchanged.
  - With subtitles OFF, the same emit routes **no** subtitle, but still returns
    the same duration and still plays the voice (`_play_voice` called).
  - `acknowledge()` and a `SpeakLine`-style emit are equally gated by the flag.
  - `set_subtitles_enabled(False/True)` flips `subtitles_enabled()`.
- `configuration_panel` (`tests/unit/test_configuration_panel.py`):
  - `toggle:subtitles` flips `subtitles_on` and calls the applier with the new
    value.
  - `render_payload` includes `subtitles_on`; changing it re-pushes (snapshot
    change detection).
  - Gameplay-tab `_focusables` includes `("ctrl","subtitles")`; `tab:gameplay`
    selects it.
- Regression: existing `test_configuration_panel.py`, `test_crew_speech_*`,
  `test_character_action_speech.py`, `test_crew_ack.py` stay green (the
  `voice_only` removal must not change resolved text for existing SpeakLine
  cases — they already resolved text).

## §7 — Out of scope

- Persistence across launches (a panel-wide follow-up that should cover all
  settings, not just subtitles).
- Lip-sync / turn-to-addressee animation differences between SpeakLine and
  SayLine (Phase-2 character animation).
- A subtitle on/off keybinding or HUD indicator.
