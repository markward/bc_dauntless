# 09 — Welcome screen

Visual reference: [09-welcome-screen.html](09-welcome-screen.html)

The pre-game / between-mission welcome panel. Shown on startup before a mission is loaded, and after a mission ends (game-over screen variant).

## Structure

A single large centred panel containing:
1. Logo / title block (Dauntless project branding)
2. Status / hint line
3. Action buttons (e.g. "Load Mission", "Quick Battle", "Exit")

The exact layout is documented in the source mockup `60598-1779389274/content/welcome.html` (copied here as [09-welcome-screen.html](09-welcome-screen.html)). The chrome reuses the panel-chrome conventions (Menu1 gradient header, dark body, 4 px left edge stripe).

## Runtime contract

This is one of the few panels not driven by the SDK's bridge widgets. It's owned by the engine's host-loop mission-picker (`engine/mission_picker.py`) and shown:
- Before any mission is loaded
- When the user presses ESC and there's no current modal / officer menu open
- When a mission ends (with a "game over" variant)

```python
picker = engine.mission_picker.MissionPicker(...)
picker.open()   # shows the welcome screen
picker.on_load = lambda mission: ...  # fires when user selects a mission
picker.on_cancel = lambda: ...        # fires when user dismisses (no current mission)
```

## When the runtime emits state

State for this panel is small:
- Title text
- Status line text (e.g. "READY", "MISSION COMPLETE", "MISSION FAILED")
- List of mission entries to pick from
- Loaded-mission warning ("Loading a new mission will discard the current one")

See the host_loop's mission-picker code for the exact data shape.
