# Subtitle captions & episode title cards — visual language

**Date:** 2026-07-13
**Status:** design approved, ready for planning

## Problem

Three unrelated kinds of text share one `#sdk-subtitle` strip, all rendered as a
centred blue `sans-serif` box that matches nothing else in the game:

| Kind | Producer | Today |
|---|---|---|
| Crew captions | `CrewSpeechBus` → `_SubtitleWindow.set_crew_line` | `LIU: Captain, I'm glad…` — inline speaker + colon |
| Episode titles | `MissionLib.EpisodeTitleAction` → `TGCreditAction` | dumped into the same strip as a plain line |
| Transient banners | `MissionLib.TextBanner` → `TGCreditAction` | same strip |

`sdk_mirror.css` is one of only two files in the UI still on bare `sans-serif`
with a blue palette (`#3a6bb8` / `#9cc4ff`); every other panel is Antonio on the
salmon/orange + purple house tokens. There is no episode title *card* at all —
`TGCreditAction` stores its x/y/fade/size/colour args and drops them, calling
`_add_text(text, duration)` and nothing more.

## Goals

- Captions and episode titles read as part of Dauntless's UI (Antonio, house tokens,
  the `bc-panel` chrome tells).
- Episode titles become a real two-tier display card (purple eyebrow + large title).
- SDK-authored fade/duration timings are honoured (see Decision 4 for the
  known wall-clock/pause limitation this carries forward unchanged).

## Non-goals

- **`info_box.css`** — the other off-theme `sans-serif` box. Untouched; separate pass.
- **Full `TGCreditAction` fidelity.** We deliberately ignore its x/y/font-size/colour
  (see Decisions). The credit action's *geometry* stays unimplemented.
- **Moving dwell/expiry onto the game clock.** Stays on `time.monotonic()` — see Decisions.
- Banners do not get their own presentation; they reuse the caption box.

## Decisions

**1. `EpisodeTitleAction` is a semantic cue, not a coordinate.** BC asks for
top-centre (`x=0.5, y=0.025`), 12pt, pale blue-lavender
(`SetDefaultColor(0.65, 0.65, 1.0, 1.0)`). We render our own bottom-left card
instead, keeping only its **duration and fade timings** (5s / 0.25s in / 0.5s out).
This matches how the project already treats SDK UI intent — the SDK says *what*,
our layout says *where*. (Same principle as identifier-centric UI attention.)

**2. The episode-title parse is also the classifier, and it lives in Python.**
`EpisodeTitleAction` and `TextBanner` both create a `TGCreditAction` aimed at the
subtitle window; nothing else distinguishes them. So the discriminator is "does the
text parse as an episode title?", applied in `TGCreditAction._do_play()` *before*
slot routing. CEF never sees the raw string — the payload carries the two tiers as
separate fields. A naive JS split on `-` would both mis-route banners and mangle
`Episode 8 - "Arise, Fair Sun..."`.

**3. Fade opacity is computed in Python, not by CSS transitions.** The `opacity`
value in the snapshot is authoritative and rewritten every frame; a CSS
transition/animation would interpolate between those per-frame writes and fight
the Python-driven fade, smearing or lagging it behind the value Python actually
computed. So we compute the fade curve ourselves in Python and ship a plain
`opacity` float each frame instead. (This is a different failure mode from the
letterbox pass's wall-clock-vs-game-time bug -- see Decision 4 for how this
system relates to pause.)

**4. Dwell/expiry stays on `time.monotonic()`** (as today). Crew-caption duration is
derived from the real MP3 length, so moving captions to the game clock would desync a
caption from its own audio. Fades use the same clock, so dwell and fade never disagree
with each other.

Known, accepted limitation: because both clocks are wall-clock, a pause (or F12
DevTools) does NOT freeze a dwell or a fade in progress -- `SDKMirrorPanel.render_payload()`
snapshots `time.monotonic()` and `PanelRegistry.render_all()` runs unconditionally in
the host loop before the `pause.sim_frozen` check (panels, including the pause menu
itself, must keep rendering while paused). Pausing while an episode title is
mid-fade lets it keep fading and expire on wall-clock time, never to return on
resume. This is not a regression -- pre-existing subtitle/banner behaviour was the
same before this change -- and is not being fixed here: plumbing a game clock
through this path is out of scope (see Non-goals).

## Design

### Slot model

`_SubtitleWindow` (`engine/appc/windows.py`) keeps three independent slots:

- `_crew_line: (speaker, text, expiry) | None` — existing; preemption == replacement.
- `_active_texts: list[...]` — existing banner list, **now carrying fade timings**.
- `_episode_title: (eyebrow, title, start, expiry, fade_in, fade_out) | None` — new,
  single-slot (a second episode title replaces the first).

New method:

```python
def _add_episode_title(self, eyebrow, title, duration_s, fade_in, fade_out) -> None
```

`_add_text` gains optional `fade_in` / `fade_out` (defaulting to 0.0 so existing
callers are unchanged in behaviour).

### Fade math

For an item with `start`, `expiry`, `fade_in`, `fade_out` at time `now`:

```
opacity = clamp(min(
    (now - start) / fade_in    if fade_in  > 0 else 1.0,
    (expiry - now) / fade_out  if fade_out > 0 else 1.0,
    1.0), 0.0, 1.0)
```

Crew captions have no SDK fade args and keep today's pop-on/pop-off (`opacity` 1.0).

### Snapshot payload

`_snapshot(now)` prunes expired entries as it does today, and emits:

```python
{
  "type": "subtitle", "id": ..., "visible": ..., "mode": ...,
  "lines": [{"text": str, "opacity": float}],      # SHAPE CHANGE (was list[str])
  "speaker": str,                                  # present iff a crew line is live
  "speech": str,
  "title_eyebrow": str,                            # present iff an episode title is live
  "title_text": str,
  "title_opacity": float,
}
```

`visible` becomes true if any of the three slots is populated. The `lines` shape
change is a breaking change to the CEF contract; `sdk_mirror.js` and the existing
subtitle-payload tests are updated in the same change.

### `TGCreditAction` (`engine/appc/actions.py`)

Constructor additionally reads `fade_in = args[5]`, `fade_out = args[6]` (guarded —
the short `(text, window)` form must keep working).

```python
_EPISODE_RE = re.compile(r'^\s*Episode\s+(\d+)\s*[-–—:]\s*["“\']?(.+?)["”\']?\s*$', re.I)
```

`_do_play()`:

1. `m = _EPISODE_RE.match(self._text)`
2. if `m` and the host exposes `_add_episode_title` →
   `host._add_episode_title("Episode " + m.group(1), m.group(2), duration, fade_in, fade_out)`
3. else → `host._add_text(text, duration, fade_in, fade_out)` (today's path)

The `_played` idempotency guard and `Restart()` reset are unchanged.

Verified against the live TGL (`game/data/TGL/Maelstrom/Maelstrom.tgl`) — all 8 strings
parse, including the embedded punctuation of `Ep8Title` and the trailing space of `Ep6Title`:

```
Ep1Title  Episode 1 - "Picking up the Pieces"
Ep2Title  Episode 2 - "Know Thine Enemy"
Ep3Title  Episode 3 - "Obscured by Clouds"
Ep4Title  Episode 4 - "Indefinite Presence"
Ep5Title  Episode 5 - "Found and Lost"
Ep6Title  Episode 6 - "Too Firm A Grasp" ␠
Ep7Title  Episode 7 - "The Drawn Line"
Ep8Title  Episode 8 - "Arise, Fair Sun..."
```

Anything that does not match (mod text, `Friendly Fire`, `Saving`) falls through to the
banner path — it cannot be mis-rendered as a title card.

### CEF

**`index.html`** — one new element beside `#sdk-subtitle`:

```html
<div id="sdk-episode-title" hidden>
  <div class="sdk-episode__eyebrow"></div>
  <div class="sdk-episode__title"></div>
</div>
```

**`js/sdk_mirror.js`** — `renderSubtitle()` reads the new `lines` shape (per-line
`opacity` on a wrapping span) and renders the speaker as its own block with no colon.
New `renderEpisodeTitle(entry)` fills the two divs, sets `el.style.opacity` from
`title_opacity`, and hides the element when no title is live.

**`css/sdk_mirror.css`** — `#sdk-subtitle` rewritten; episode rules added.

```css
#sdk-subtitle {
  position: absolute;
  left: 50%; bottom: 14vh;                  /* clears the 6.25vh max letterbox bar */
  transform: translateX(-50%);
  max-width: 52vw;
  padding: 10px 20px 12px 16px;
  text-align: left;

  background: rgba(10, 10, 16, 0.85);       /* --bc-body-bg */
  border-left: 4px solid rgb(216, 94, 86);  /* salmon rule */
  border-top-right-radius: 14px;            /* the LCARS tell — no other radius */

  font-family: "Antonio", sans-serif;
  font-size: 17px; line-height: 1.25;
  color: rgb(235, 225, 255);                /* --bc-label-text */
  text-shadow: 0 0 3px #000;
  z-index: 50; pointer-events: none;
}

.sdk-subtitle__speaker {                    /* own line; no colon */
  display: block;
  color: #d88450;                           /* chrome orange — reticle-name convention */
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  margin-bottom: 3px;
}

#sdk-episode-title {
  position: absolute;
  left: 5vw; bottom: 16vh;
  font-family: "Antonio", sans-serif;
  text-align: left;
  z-index: 50; pointer-events: none;
}
.sdk-episode__eyebrow {
  font-size: 20px;
  text-transform: uppercase;
  letter-spacing: 0.18em;
  color: rgb(147, 103, 255);                /* house purple */
  margin-bottom: 6px;
}
.sdk-episode__title {
  font-size: clamp(40px, 5.4vw, 72px);
  line-height: 1.0;
  text-transform: uppercase;
  letter-spacing: 0.02em;
  color: #fff;
  text-shadow: 0 2px 12px rgba(0, 0, 0, 0.75);
}
```

The card has no box or border — it floats on the letterboxed shot. Both slots sit at
`z-index: 50` and are drawn above the letterbox bars by construction (the bars are a
GL pass beneath the whole CEF layer).

## Tests

- **Episode-title parse table** — the 8 real TGL strings → `(eyebrow, title)`; plus
  non-matching inputs (`Friendly Fire`, `Saving`, `Chapter Three`, `""`) → no match.
- **Fade math** — `_snapshot()` opacity is 0 at `start`, 1.0 through the hold, and
  ramps to 0 at `expiry`; zero fade args give a hard 1.0.
- **`TGCreditAction` routing** — an episode string lands in `_episode_title`; a banner
  string lands in `_active_texts`; the short `(text, window)` constructor form still works.
- **Snapshot payload** — all three slots can be live simultaneously; `visible` is true
  if any is.
- **Updated:** existing subtitle-payload tests for the `lines` shape change.

Gate: `scripts/check_tests.sh`.

## Verification

`--developer` → mission picker → Episode 1 / E1M1: the opening cutscene shows the
bottom-left title card fading in over the establishing shot, and Admiral Liu's and
Picard's lines render in the new caption box.
