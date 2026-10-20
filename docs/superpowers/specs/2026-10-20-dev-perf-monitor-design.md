# Developer performance monitor — design

**Status:** built on `feat/dev-perf-monitor`, not yet live-checked.

## What

A developer-only readout in the top-right corner of the screen showing:

- **FPS**: frames per second, averaged over a 0.5 s window of wall time. It is
  coloured green at 55 or more, amber at 30 or more, and red below 30.
- **Frame time**: the average milliseconds per frame over the same window.
- **Resolution**: the framebuffer size in physical pixels. The scene draws at
  this size because the engine has no separate render scale, so this is the
  real render resolution.

The readout is turned on in **Developer Options → Diagnostics → Performance
Monitor**. It is off by default and is not saved between launches.

## Why this shape

- **Wall-clock frames, not sim ticks.** The meter is fed the host loop's
  `_wall_dt`, which is the delta before the pause freeze zeroes `_frame_dt`.
  So it measures what the player sees, and it keeps reading while paused.
- **Per-window, not a running average.** A slow stretch shows within half a
  second instead of being diluted by the session's history, and the number
  holds still long enough to read.
- **Cheap.** The panel is polled at 4 Hz and its payload is snapshot-diffed,
  so a steady frame rate pushes nothing to CEF. The meter costs two adds per
  frame.
- **It is not the frame profiler.** The profiler (`docs/engine/frame-profiler.md`)
  breaks a frame down per pass and prints to the terminal. This readout only
  answers "how fast, at what size" on screen. For a perf claim, use the
  profiler and the perf register. A Debug build's FPS is not a baseline.

## Parts

| Part | Role |
|---|---|
| `engine/dev_perf_monitor.py` | The on/off flag (`enabled()` ANDs `dev_mode.is_enabled()`) and `FrameRateMeter` |
| `engine/ui/perf_monitor_panel.py` | `PerfMonitorPanel`. `tick(wall_dt)` feeds the meter and mirrors the flag onto `visible`; it pushes `setPerfMonitor({...})` |
| `engine/ui/developer_options_panel.py` + `js/developer_options.js` | The Diagnostics row `toggle:perf_monitor` |
| `native/assets/ui-cef/{index.html, js/perf_monitor.js, css/perf_monitor.css}` | `#perf-monitor`, fixed top-right |
| `engine/host_loop.py` | Builds and registers the panel only under `--developer`, and ticks it each frame next to `_wall_dt` |

## Layering

- `#perf-monitor` sits at z-index 400, above the modals and the system screens
  (300–310). `modal_layer.js` occludes by z-index, so the readout stays
  visible while a modal is open. It is allow-listed in
  `tests/ui/test_modal_geometry.py`'s `_ABOVE_LAYER`.
- It has `pointer-events: none`, so it needs no `_cursor_in_*` click bbox and
  clicks pass through to the game.
- **Known overlap:** the Engineering power panel (`#engpower-root`) also sits
  at the top right when its menu is open. The monitor covers that panel's
  top-right corner.

## Tests

- `tests/unit/test_dev_perf_monitor.py` covers the flag, the meter, the panel
  payload, dedup and visibility, the Developer Options row, and the HTML/JS
  wiring.
- `tests/unit/test_developer_options_panel.py` adds the new key to the
  settings-shape test.
