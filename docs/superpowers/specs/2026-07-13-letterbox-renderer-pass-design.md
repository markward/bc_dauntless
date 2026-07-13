# Cutscene letterbox — move out of the UI layer into a renderer pass

**Date:** 2026-07-13
**Status:** design approved, not yet implemented

## Problem

The cutscene letterbox bars are CEF DOM: two `<div>`s in
`native/assets/ui-cef/index.html`, styled by `.sdk-letterbox` in
`css/sdk_mirror.css` at `z-index: 5`, animated by `renderLetterbox()` in
`js/sdk_mirror.js` from a payload emitted by `SDKMirrorPanel`.

Living in the UI layer forces the bars to negotiate stacking order with every
other UI element, and they currently **win against UI that must stay readable**.
The HUD roots declare no `z-index` at all — `#tactical-left-column` and
`#tactical-bottom-row` (`css/global.css`), `#reticle-name` / `#reticle-dist`,
`#ai-inspector-panel` — so they are `z-index: auto`. In CSS painting order,
positioned-auto elements paint in step 8 and any positive `z-index` paints in
step 9, so `z-index: 5` beats them regardless of DOM order.

Crew menus render inside `#tactical-target-stack` at `top: 24px`. A default
`fCoveredArea = 0.125` gives a top bar of ~6.25vh (≈67 px at 1080p), so a menu
the mission raises *during* a cutscene is partly swallowed by the bar. This has
already caused a shipped bug once: see the docstring of
`tests/ui/test_sdk_panel_positions.py::test_crew_menu_is_never_sdk_positioned`
— E1M1's XO menu went invisible "under E1M1's cutscene letterbox" and the
tutorial halted.

The elements that survive today (subtitle 50, info box 40, modals, pause menu
100) survive only because somebody happened to assign them a number. Every new
panel is one forgotten `z-index` away from the same bug.

The `z-index: 5` was never needed to sit above the 3D scene either: the entire
CEF page composites over GL, so the bars only ever needed ordering relative to
other DOM.

## Decision

**The letterbox is not a widget.** It is a framing property of the rendered
view — the same category as `FadeOut` and the cutscene camera modes. Draw it in
the renderer, below the whole UI layer.

Rejected alternative: a documented z-index scale in `global.css` that lifts
every UI root above the bars. It fixes today's symptom but keeps the
negotiation alive — the rule has to be remembered by every future panel author,
and it has already been forgotten once.

With the bars in GL, "UI draws over the letterbox" stops being a rule anyone can
break and becomes true by construction: there is no `z-index` for the bars to
have.

## Frame position

The post-process chain resolves into the default framebuffer (FBO 0) in
`native/src/host/host_bindings.cc` (the `passes[i](cur_tex, dst_fbo)` loop),
after which `dauntless::ui_cef::pump()` + `composite()` blend the overlay
bitmap on top, then `swap_buffers()`.

The letterbox pass slots into that seam: **after the post-chain, before
`ui_cef::composite()`**, drawing into FBO 0.

Consequences, all intended:
- The bars cover the 3D scene in **both** exterior and bridge views (BC
  letterboxes any `StartCutscene`, including bridge walk-on / crew-intro
  cutscenes).
- **Every** CEF element — subtitles, crew menus, info boxes, stylized modals,
  pause menu, DevTools-era panels — draws over the bars, with no CSS involved.
- No new render target is needed.

## Components

### 1. `native/src/renderer/letterbox_pass.{cc,h}`

Holds one float: the total covered fraction (BC's `fCoveredArea`; `0.125` =
6.25% per bar). When it is zero the pass returns immediately and costs nothing.

Otherwise it draws the two bars into FBO 0 with `glScissor` + `glClear` to
opaque black — no shader, no fullscreen quad, no FBO. Per-bar height in pixels
is `round(covered / 2 * framebuffer_height)`; the top bar is at the top of the
framebuffer, the bottom bar at the bottom. Scissor state and clear colour are
saved and restored so the pass has no side effects on the CEF composite that
follows.

State setter: `set_covered(float)`, clamped to `[0, 1]`.

### 2. Binding + renderer wrapper

- `host_bindings.cc`: `m.def("letterbox_set", ...)` forwarding to
  `letterbox_pass::set_covered`.
- `engine/renderer.py`: `letterbox_set(covered: float)` wrapper, and
  `"letterbox_set"` added to `_REQUIRED_BINDINGS` so a stale binary hard-fails
  at boot instead of silently dropping the bars.

### 3. `engine/ui/letterbox.py` — `LetterboxAnimator`

CSS `transition: height Ns ease` currently animates the slide for free. That
work moves to Python.

`TopWindow` already records everything needed and needs **no change**:
`StartCutscene` stores `_letterbox_covered` (target) and
`_letterbox_transition_s` (duration); `EndCutscene` sets the slide-out
duration; `AbortCutscene` sets `transition_s = 0.0` to snap;
`letterbox_snapshot()` returns `{visible, covered, transition_s}`.

`LetterboxAnimator` is pure Python with no engine imports:

```
update(dt: float, snapshot: dict) -> float   # current covered fraction
```

- Target is `snapshot["covered"]` when `visible`, else `0.0`.
- Eases the current value toward the target over `transition_s` seconds using
  smoothstep (an approximation of CSS `ease`).
- `transition_s == 0` snaps immediately (this is what `AbortCutscene` relies on).
- A new target mid-slide re-bases the ease from the current value.
- `dt == 0` holds the current value — so the bars freeze under the pause menu
  and the DevTools freeze instead of sliding on wall-clock time. This is a
  small correctness win over the CSS transition, which ignored both.

### 4. Host-loop wiring

Once per frame, in the render section of `engine/host_loop.py` (unconditional —
the bars are not view-gated):

```python
_lb = _letterbox_anim.update(_player_dt, TopWindow_GetTopWindow().letterbox_snapshot())
r.letterbox_set(_lb)
```

`_player_dt` is already 0 while `pause.sim_frozen`, which gives the freeze
behaviour above for free.

### 5. Deletions

- `native/assets/ui-cef/index.html`: the `#sdk-letterbox-top` /
  `#sdk-letterbox-bottom` divs.
- `native/assets/ui-cef/css/sdk_mirror.css`: the `.sdk-letterbox` block and the
  two id rules.
- `native/assets/ui-cef/js/sdk_mirror.js`: `renderLetterbox()` and its call in
  `setSdkMirror`.
- `engine/appc/sdk_mirror_panel.py`: the letterbox entry and the
  `_letterbox_emitted` dedup flag.

`TopWindow.letterbox_snapshot()` **survives** — the host loop becomes its
consumer in place of `SDKMirrorPanel`.

## Data flow

```
SDK mission script
  → MissionLib.StartCutscene / EndCutscene / AbortCutscene
  → TopWindow (_letterbox_covered, _letterbox_transition_s, _cutscene_active)
  → letterbox_snapshot()            [host loop, once per frame]
  → LetterboxAnimator.update(dt, snapshot) -> covered
  → renderer.letterbox_set(covered)
  → letterbox_pass  [FBO 0, after post-chain, before ui_cef::composite()]
```

## Error handling

- `letterbox_set` clamps to `[0, 1]`; a malformed `fCoveredArea` from a mission
  script cannot produce a negative scissor rect or a full-screen blackout
  beyond the clamp.
- `_REQUIRED_BINDINGS` turns a stale-binary mismatch into a boot-time failure,
  per the project's existing rule for missing `_dauntless_host` attributes.
- Headless (no GL): the pass never runs. The animator is pure Python and is
  tested directly, so headless coverage does not regress.

## Testing

| Test | Location | Asserts |
|---|---|---|
| Slide-in | `tests/unit/test_letterbox.py` | Repeated `update(dt, visible-snapshot)` converges to `covered`, monotonically, and reaches it at ≈`transition_s`. |
| Slide-out | same | `visible: False` eases to 0. |
| Snap on abort | same | `transition_s == 0` reaches the target in one `update`. |
| Frozen dt | same | `update(0.0, ...)` does not move the value. |
| Re-target mid-slide | same | A new target eases from the current value, no jump. |
| Host wiring | `tests/host/` | The snapshot reaches `renderer.letterbox_set` once per frame (fake renderer records the call). |
| Mirror panel no longer emits it | `tests/unit/test_sdk_mirror_panel.py` | The four existing letterbox tests are **deleted** with the feature; one test asserts no `letterbox` entry is ever emitted. |
| Pass renders | C++ `FrameTest` | With `covered = 0.5`, the top and bottom framebuffer rows read black and the centre band does not. |

`TopWindow`'s existing cutscene tests (`tests/unit/test_top_window.py`) are
untouched — the SDK-facing surface does not change.

The gate is `scripts/check_tests.sh` (pytest + ctest against
`tests/known_failures.txt`). The new `FrameTest` must pass under headless GL; if
it cannot, that is a signal the pass is wrong, not a reason to baseline it — do
not add it to `known_failures.txt`.

## Out of scope

- `_tactical_hud_visible()` still hides the tactical HUD for the duration of a
  cutscene, and `bHideReticle` still hides the reticle. This change moves only
  *where the bars are drawn*.
- The missing `z-index` values on the HUD roots are left alone. With the bars
  gone from the DOM there is nothing above them to fight, and inventing a layer
  scale for a problem that no longer exists is scope creep.
