# Subtitle Captions & Episode Title Cards — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the crew-caption box onto Dauntless's house UI tokens and add a two-tier bottom-left episode title card, driven by SDK timings.

**Architecture:** `_SubtitleWindow` grows a third slot for the episode title alongside its crew-line and banner slots. `TGCreditAction` — which today drops every arg but text and duration — starts reading the SDK's fade args and classifies its text with an episode-title regex: matches route to the title slot, everything else stays a banner. Fade opacity is computed in Python and shipped in the snapshot (never a CSS transition), so fades freeze under pause. CEF gains a new `#sdk-episode-title` element and a rewritten `#sdk-subtitle` rule.

**Tech Stack:** Python 3 (`engine/appc/`), pytest, CEF (vanilla HTML/CSS/JS under `native/assets/ui-cef/`).

**Spec:** `docs/superpowers/specs/2026-07-13-subtitle-episode-title-visual-language-design.md`

## Global Constraints

- **No C++ / native change.** This is Python + CEF assets only. No rebuild is needed for CSS/JS/HTML (they are loaded from disk), but `scripts/check_tests.sh` still builds and must pass.
- **Fade opacity is computed in Python and pushed per-frame.** Do **not** use CSS `transition` or `@keyframes` for fades — they run on wall-clock and keep animating while the sim is frozen (pause / F12 DevTools). This is the letterbox lesson; the design doc records it.
- **Dwell/expiry stays on `time.monotonic()`.** Do not move the subtitle window onto the game clock — caption duration is tied to real MP3 length. Fades use the same clock.
- **House tokens only.** Antonio (`"Antonio", sans-serif`), `rgba(10,10,16,0.85)` body, salmon `rgb(216,94,86)`, purple `rgb(147,103,255)`, chrome orange `#d88450`, label text `rgb(235,225,255)`. No `sans-serif`-only stacks, no blue palette.
- **Gate:** `scripts/check_tests.sh` (never `run_tests.sh` alone — it is pytest-only). The only permitted failures are the 7 headless-GL entries already in `tests/known_failures.txt`.
- **Never run destructive git** (`git checkout --`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`/`git add .`). Stage with explicit pathspecs only. This tree is shared with concurrent sessions.

---

### Task 1: Episode-title parser

The pure function that both classifies a credit action and splits the TGL string into
its two tiers. Lives next to `TGCreditAction`, which is its only caller.

**Files:**
- Modify: `engine/appc/actions.py` (add near the `TGCreditAction` block, ~line 815)
- Test: `tests/unit/test_episode_title_parse.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `engine.appc.actions.parse_episode_title(text: str) -> tuple[str, str] | None`
  returning `(eyebrow, title)` — e.g. `("Episode 1", "Picking up the Pieces")` — or
  `None` when the text is not an episode title. Task 3 calls this.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_episode_title_parse.py`:

```python
"""parse_episode_title() splits BC's single TGL episode string into two tiers.

The 8 EpNTitle strings below are the real values read from the shipped
game/data/TGL/Maelstrom/Maelstrom.tgl — note Ep6's trailing space and the
embedded punctuation in Ep8. Anything that does not match is not an episode
title and must fall through to the banner path (see TGCreditAction).
"""
import pytest

from engine.appc.actions import parse_episode_title


@pytest.mark.parametrize("raw,expected", [
    ('Episode 1 - "Picking up the Pieces"', ("Episode 1", "Picking up the Pieces")),
    ('Episode 2 - "Know Thine Enemy"',      ("Episode 2", "Know Thine Enemy")),
    ('Episode 3 - "Obscured by Clouds"',    ("Episode 3", "Obscured by Clouds")),
    ('Episode 4 - "Indefinite Presence"',   ("Episode 4", "Indefinite Presence")),
    ('Episode 5 - "Found and Lost"',        ("Episode 5", "Found and Lost")),
    ('Episode 6 - "Too Firm A Grasp" ',     ("Episode 6", "Too Firm A Grasp")),
    ('Episode 7 - "The Drawn Line"',        ("Episode 7", "The Drawn Line")),
    ('Episode 8 - "Arise, Fair Sun..."',    ("Episode 8", "Arise, Fair Sun...")),
])
def test_real_tgl_strings_parse_into_two_tiers(raw, expected):
    assert parse_episode_title(raw) == expected


@pytest.mark.parametrize("raw", [
    "Friendly Fire",
    "Saving",
    "Enroute To Starbase 12",
    "Chapter Three",
    "Episode",          # no number
    "Episode 9",        # number but no title
    "",
])
def test_non_episode_text_does_not_parse(raw):
    assert parse_episode_title(raw) is None


def test_unquoted_title_still_parses():
    # Mod text may omit the quotes; the hyphen + number prefix is the anchor.
    assert parse_episode_title("Episode 12 - Return to Sector 001") == (
        "Episode 12", "Return to Sector 001",
    )


def test_colon_separator_parses():
    assert parse_episode_title('Episode 3: "Obscured by Clouds"') == (
        "Episode 3", "Obscured by Clouds",
    )


def test_non_string_input_returns_none():
    assert parse_episode_title(None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_episode_title_parse.py -q`
Expected: FAIL — `ImportError: cannot import name 'parse_episode_title'`

- [ ] **Step 3: Write minimal implementation**

In `engine/appc/actions.py`, add `import re` to the imports if absent, then insert
immediately **above** the `class TGCreditAction` definition:

```python
# BC ships the episode title as one TGL string: 'Episode 1 - "Picking up the
# Pieces"'. Dauntless renders it as a two-tier card (purple eyebrow + large
# title), so the string has to be split -- and because EpisodeTitleAction and
# MissionLib.TextBanner both create a TGCreditAction aimed at the subtitle
# window, "does this parse as an episode title?" is also the only honest
# discriminator between the two. Anchored on the `Episode <n>` prefix rather
# than split on the first hyphen, so Ep8's 'Arise, Fair Sun...' survives.
_EPISODE_TITLE_RE = re.compile(
    r'^\s*Episode\s+(\d+)\s*[-–—:]\s*["“\']?(.+?)["”\']?\s*$',
    re.IGNORECASE,
)


def parse_episode_title(text) -> tuple[str, str] | None:
    """Split an episode-title string into (eyebrow, title), or None.

    Returns None for any text that is not shaped like a BC episode title --
    those are transient banners and must render in the caption box instead.
    """
    if not isinstance(text, str):
        return None
    m = _EPISODE_TITLE_RE.match(text)
    if m is None:
        return None
    return ("Episode " + m.group(1), m.group(2).strip())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_episode_title_parse.py -q`
Expected: PASS (16 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/appc/actions.py tests/unit/test_episode_title_parse.py
git commit -m "feat(ui): parse BC's single episode-title string into two tiers"
```

---

### Task 2: Subtitle window — fade timings, episode slot, new payload

`_SubtitleWindow` gains the third slot and starts computing fade opacity. This is the
breaking change: `lines` goes from `list[str]` to `list[dict]`, and `_active_texts`
entries grow from 2-tuples to 5-tuples.

**Files:**
- Modify: `engine/appc/windows.py:218-278` (`_SubtitleWindow`)
- Test: `tests/unit/test_subtitle_window.py` (modify — existing tests assert the old shapes)
- Test: `tests/integration/test_sdk_mirror_round_trip.py:43` (modify — asserts old `lines` shape)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces, on `_SubtitleWindow`:
  - `_add_text(text: str, duration_s: float, fade_in: float = 0.0, fade_out: float = 0.0) -> None`
  - `_add_episode_title(eyebrow: str, title: str, duration_s: float, fade_in: float = 0.0, fade_out: float = 0.0) -> None`
  - `_active_texts: list[tuple[str, float, float, float, float]]` — `(text, start, expiry, fade_in, fade_out)`
  - `_episode_title: tuple[str, str, float, float, float, float] | None` — `(eyebrow, title, start, expiry, fade_in, fade_out)`
  - `_snapshot(now)` payload keys: `lines: list[{"text": str, "opacity": float}]`, plus
    `title_eyebrow: str`, `title_text: str`, `title_opacity: float` when a title is live.
  Task 3 calls `_add_text` / `_add_episode_title`; Task 4 consumes the payload keys.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_subtitle_window.py`, **replace** these four existing tests —
`test_add_text_appends_with_expiry`, `test_snapshot_returns_dict_when_visible`,
`test_snapshot_prunes_expired_text`,
`test_snapshot_visible_true_when_text_active_even_if_set_off` — with the versions
below, and **append** the rest. (`test_snapshot_returns_dict_when_visible`'s dict is
unchanged in content — `lines` is still `[]` when empty — but keep it as the anchor
for the empty case.)

```python
def test_add_text_records_start_expiry_and_fades(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 100.0)
    sw._add_text("hello", 5.0, 0.25, 0.5)
    assert sw._active_texts == [("hello", 100.0, 105.0, 0.25, 0.5)]


def test_add_text_defaults_to_no_fade(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw._add_text("hello", 5.0)
    assert sw._active_texts == [("hello", 0.0, 5.0, 0.0, 0.0)]


def test_snapshot_returns_dict_when_visible():
    sw = _SubtitleWindow()
    sw.SetOn()
    snap = sw._snapshot(now=0.0)
    assert snap == {
        "type": "subtitle", "id": "subtitle-0",
        "visible": True, "mode": SubtitleWindow.SM_TACTICAL, "lines": [],
    }


def test_snapshot_prunes_expired_text(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw._add_text("expired", 1.0)
    sw._add_text("alive", 10.0)
    snap = sw._snapshot(now=5.0)
    assert snap["lines"] == [{"text": "alive", "opacity": 1.0}]
    assert sw._active_texts == [("alive", 0.0, 10.0, 0.0, 0.0)]


def test_snapshot_visible_true_when_text_active_even_if_set_off(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw._add_text("hello", 5.0)
    snap = sw._snapshot(now=1.0)
    assert snap["visible"] is True
    assert snap["lines"] == [{"text": "hello", "opacity": 1.0}]


# ── fade math ───────────────────────────────────────────────────────────────

def test_banner_fades_in_then_holds_then_fades_out(monkeypatch):
    # 10s banner starting at t=0, 0.25s fade-in, 0.5s fade-out.
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw._add_text("banner", 10.0, 0.25, 0.5)

    def opacity(now):
        return sw._snapshot(now=now)["lines"][0]["opacity"]

    assert opacity(0.0) == pytest.approx(0.0)     # start of fade-in
    assert opacity(0.125) == pytest.approx(0.5)   # mid fade-in
    assert opacity(0.25) == pytest.approx(1.0)    # fade-in complete
    assert opacity(5.0) == pytest.approx(1.0)     # hold
    assert opacity(9.75) == pytest.approx(1.0)    # start of fade-out
    assert opacity(9.875) == pytest.approx(0.25)  # mid fade-out
    assert opacity(9.999) == pytest.approx(0.002, abs=1e-3)


def test_zero_fade_args_give_hard_on(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw._add_text("banner", 5.0, 0.0, 0.0)
    assert sw._snapshot(now=0.0)["lines"][0]["opacity"] == pytest.approx(1.0)
    assert sw._snapshot(now=4.999)["lines"][0]["opacity"] == pytest.approx(1.0)


def test_crew_line_has_no_fade(monkeypatch):
    # Crew captions carry no SDK fade args -- they pop on and pop off.
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw.set_crew_line("Helm", "Course laid in", 5.0)
    snap = sw._snapshot(now=0.0)
    assert snap["speech"] == "Course laid in"
    assert "speech_opacity" not in snap   # no fade channel for captions


# ── episode title slot ──────────────────────────────────────────────────────

def test_add_episode_title_records_slot(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 100.0)
    sw._add_episode_title("Episode 1", "Picking up the Pieces", 5.0, 0.25, 0.5)
    assert sw._episode_title == (
        "Episode 1", "Picking up the Pieces", 100.0, 105.0, 0.25, 0.5,
    )


def test_snapshot_includes_episode_title_when_live(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw._add_episode_title("Episode 1", "Picking up the Pieces", 5.0, 0.25, 0.5)
    snap = sw._snapshot(now=1.0)
    assert snap["visible"] is True
    assert snap["title_eyebrow"] == "Episode 1"
    assert snap["title_text"] == "Picking up the Pieces"
    assert snap["title_opacity"] == pytest.approx(1.0)


def test_episode_title_fades(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw._add_episode_title("Episode 1", "Picking up the Pieces", 5.0, 0.25, 0.5)
    assert sw._snapshot(now=0.125)["title_opacity"] == pytest.approx(0.5)
    assert sw._snapshot(now=4.75)["title_opacity"] == pytest.approx(1.0)
    assert sw._snapshot(now=4.875)["title_opacity"] == pytest.approx(0.25)


def test_snapshot_prunes_expired_episode_title(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw._add_episode_title("Episode 1", "Picking up the Pieces", 5.0, 0.25, 0.5)
    assert sw._snapshot(now=10.0) is None       # expired, nothing else live
    assert sw._episode_title is None


def test_second_episode_title_replaces_the_first(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw._add_episode_title("Episode 1", "Picking up the Pieces", 5.0, 0.0, 0.0)
    sw._add_episode_title("Episode 2", "Know Thine Enemy", 5.0, 0.0, 0.0)
    assert sw._snapshot(now=1.0)["title_eyebrow"] == "Episode 2"


def test_snapshot_omits_title_keys_when_no_episode_title():
    sw = _SubtitleWindow()
    sw.SetOn()
    snap = sw._snapshot(now=0.0)
    assert "title_eyebrow" not in snap
    assert "title_text" not in snap
    assert "title_opacity" not in snap


def test_all_three_slots_can_be_live_at_once(monkeypatch):
    sw = _SubtitleWindow()
    monkeypatch.setattr("engine.appc.windows.time.monotonic", lambda: 0.0)
    sw._add_text("Friendly Fire", 5.0)
    sw.set_crew_line("Liu", "Captain.", 5.0)
    sw._add_episode_title("Episode 1", "Picking up the Pieces", 5.0)
    snap = sw._snapshot(now=1.0)
    assert snap["lines"] == [{"text": "Friendly Fire", "opacity": 1.0}]
    assert snap["speaker"] == "Liu"
    assert snap["title_text"] == "Picking up the Pieces"
    assert snap["visible"] is True
```

The file already imports `pytest`? It does not — add `import pytest` at the top of
`tests/unit/test_subtitle_window.py` (needed for `pytest.approx` and `parametrize`).

Also update `tests/integration/test_sdk_mirror_round_trip.py:43`:

```python
    assert subtitle_entry["lines"] == [{"text": "Disable the patrol", "opacity": 1.0}]
```

(The `TGCreditAction_Create("Disable the patrol", subtitle, 0.0, 0.0, 5.0)` call in that
test passes no fade args, so opacity is a hard 1.0 and the panel's payload diffing is
unaffected.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_subtitle_window.py tests/integration/test_sdk_mirror_round_trip.py -q`
Expected: FAIL — `AttributeError: '_SubtitleWindow' object has no attribute '_add_episode_title'`
and assertion failures on `lines` shape (`['alive'] != [{'text': 'alive', ...}]`).

- [ ] **Step 3: Write the implementation**

In `engine/appc/windows.py`, replace the `_SubtitleWindow` body from `__init__` through
`_snapshot` with:

```python
    def __init__(self):
        self._id = "subtitle-0"
        self._visible = False
        self._mode = self._SM_TACTICAL
        # (text, start, expiry, fade_in, fade_out) -- mission banners.
        self._active_texts: list[tuple[str, float, float, float, float]] = []
        # Single replaceable crew-speech slot (speaker, text, expiry). Separate
        # from _active_texts so a SpeakLine preemption is a clean replacement
        # and never collides with a mission banner. Owned by CrewSpeechBus.
        # Captions carry no SDK fade args: they pop on and pop off.
        self._crew_line: tuple[str, str, float] | None = None
        # (eyebrow, title, start, expiry, fade_in, fade_out) -- the episode
        # title card. Single slot: a second title replaces the first.
        self._episode_title: (
            tuple[str, str, float, float, float, float] | None
        ) = None
```

Keep `SetOn` / `SetOff` / `SetVisible` / `IsOn` / `SetPositionForMode` /
`set_crew_line` / `clear_crew_line` exactly as they are. Then replace `_add_text` and
`_snapshot` with:

```python
    def _add_text(
        self, text: str, duration_s: float,
        fade_in: float = 0.0, fade_out: float = 0.0,
    ) -> None:
        now = time.monotonic()
        self._active_texts.append((
            str(text), now, now + float(duration_s),
            float(fade_in), float(fade_out),
        ))

    def _add_episode_title(
        self, eyebrow: str, title: str, duration_s: float,
        fade_in: float = 0.0, fade_out: float = 0.0,
    ) -> None:
        now = time.monotonic()
        self._episode_title = (
            str(eyebrow), str(title), now, now + float(duration_s),
            float(fade_in), float(fade_out),
        )

    @staticmethod
    def _fade_opacity(
        now: float, start: float, expiry: float,
        fade_in: float, fade_out: float,
    ) -> float:
        # Computed here, in Python, and pushed per-frame -- NOT a CSS
        # transition. A CSS transition runs on wall-clock and would keep
        # animating while the sim is frozen (pause / DevTools); the letterbox
        # pass learned this the hard way.
        alpha = 1.0
        if fade_in > 0.0:
            alpha = min(alpha, (now - start) / fade_in)
        if fade_out > 0.0:
            alpha = min(alpha, (expiry - now) / fade_out)
        return max(0.0, min(1.0, alpha))

    def _snapshot(self, now: float) -> dict | None:
        self._active_texts = [e for e in self._active_texts if e[2] > now]
        if self._crew_line is not None and self._crew_line[2] <= now:
            self._crew_line = None
        if self._episode_title is not None and self._episode_title[3] <= now:
            self._episode_title = None
        has_crew = self._crew_line is not None
        has_title = self._episode_title is not None
        if (not self._visible and not self._active_texts
                and not has_crew and not has_title):
            return None
        snap = {
            "type": "subtitle",
            "id": self._id,
            "visible": (self._visible or bool(self._active_texts)
                        or has_crew or has_title),
            "mode": self._mode,
            "lines": [
                {"text": t, "opacity": self._fade_opacity(now, s, e, fi, fo)}
                for (t, s, e, fi, fo) in self._active_texts
            ],
        }
        if has_crew:
            snap["speaker"] = self._crew_line[0]
            snap["speech"] = self._crew_line[1]
        if has_title:
            eyebrow, title, start, expiry, fade_in, fade_out = self._episode_title
            snap["title_eyebrow"] = eyebrow
            snap["title_text"] = title
            snap["title_opacity"] = self._fade_opacity(
                now, start, expiry, fade_in, fade_out,
            )
        return snap
```

Also update the class's leading comment block (`windows.py:213-216`) to mention the
third slot:

```python
# ── SubtitleWindow ──────────────────────────────────────────────────────────
# Singleton main window hosting three independent text slots: crew-speech
# captions (set_crew_line), mission banners (_add_text, from TGCreditAction),
# and the episode title card (_add_episode_title). The mirror panel snapshots
# (and prunes expired entries) once per tick, computing fade opacity in Python.
# Spec: docs/superpowers/specs/2026-07-13-subtitle-episode-title-visual-language-design.md
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_subtitle_window.py tests/integration/test_sdk_mirror_round_trip.py -q`
Expected: PASS

Then check nothing else read the old tuple shape:
Run: `uv run pytest tests/unit/test_helm_entering_banner.py tests/unit/test_sdk_mirror_panel.py -q`
Expected: PASS (`test_helm_entering_banner.py:79` reads `_active_texts[0][0]`, which is
still the text.)

- [ ] **Step 5: Commit**

```bash
git add engine/appc/windows.py tests/unit/test_subtitle_window.py tests/integration/test_sdk_mirror_round_trip.py
git commit -m "feat(ui): add episode-title slot and Python-computed fades to SubtitleWindow"
```

---

### Task 3: Route TGCreditAction to the right slot

`TGCreditAction` starts honouring the SDK's fade args and uses `parse_episode_title`
to decide which slot its text belongs in.

**Files:**
- Modify: `engine/appc/actions.py:815-861` (`TGCreditAction`)
- Test: `tests/unit/test_credit_action_play.py` (modify — two tests unpack the old 2-tuple)

**Interfaces:**
- Consumes: `parse_episode_title` (Task 1); `_SubtitleWindow._add_text(text, duration, fade_in, fade_out)`
  and `_add_episode_title(eyebrow, title, duration, fade_in, fade_out)` (Task 2).
- Produces: `TGCreditAction._fade_in` / `._fade_out` floats (defaulting to 0.0).

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_credit_action_play.py`, fix the two tests that unpack the old
2-tuple and append the routing tests:

```python
def test_play_calls_host_add_text():
    host = _SubtitleWindow()
    ca = TGCreditAction_Create("Disable the patrol", host, 0.5, 0.5, 5.0, 0.25, 0.5, 16)
    ca.Play()
    assert len(host._active_texts) == 1
    assert host._active_texts[0][0] == "Disable the patrol"


def test_play_uses_duration_from_args():
    host = _SubtitleWindow()
    ca = TGCreditAction_Create("hi", host, 0.0, 0.0, 7.5)
    ca.Play()
    assert len(host._active_texts) == 1
    assert ca._duration_s == 7.5
```

Then append:

```python
# ── fade args ───────────────────────────────────────────────────────────────

def test_fade_args_are_read_from_the_sdk_call():
    # MissionLib.EpisodeTitleAction: (text, window, x, y, dur, fade_in, fade_out, size)
    host = _SubtitleWindow()
    ca = TGCreditAction_Create("hi", host, 0.5, 0.025, 5.0, 0.25, 0.5, 12)
    assert ca._fade_in == 0.25
    assert ca._fade_out == 0.5


def test_fade_args_default_to_zero_on_short_form():
    host = _SubtitleWindow()
    ca = TGCreditAction_Create("brief", host)
    assert ca._fade_in == 0.0
    assert ca._fade_out == 0.0


def test_fades_reach_the_banner_slot():
    host = _SubtitleWindow()
    TGCreditAction_Create("Friendly Fire", host, 0.0, 0.25, 5.0, 0.25, 0.5, 12).Play()
    _text, _start, _expiry, fade_in, fade_out = host._active_texts[0]
    assert (fade_in, fade_out) == (0.25, 0.5)


# ── slot routing ────────────────────────────────────────────────────────────

def test_episode_title_routes_to_the_title_slot():
    # This is exactly what MissionLib.EpisodeTitleAction emits.
    host = _SubtitleWindow()
    TGCreditAction_Create(
        'Episode 1 - "Picking up the Pieces"', host,
        0.5, 0.025, 5.0, 0.25, 0.5, 12,
    ).Play()
    assert host._active_texts == []          # NOT a banner
    eyebrow, title, _start, _expiry, fade_in, fade_out = host._episode_title
    assert eyebrow == "Episode 1"
    assert title == "Picking up the Pieces"
    assert (fade_in, fade_out) == (0.25, 0.5)


def test_banner_text_does_not_route_to_the_title_slot():
    host = _SubtitleWindow()
    TGCreditAction_Create("Friendly Fire", host, 0.0, 0.25, 5.0, 0.25, 0.5, 12).Play()
    assert host._episode_title is None
    assert host._active_texts[0][0] == "Friendly Fire"


def test_episode_title_on_a_host_without_the_title_slot_falls_back_to_text():
    # Some SDK paths chain credit actions onto a TGPane (E8M2's MoviePane).
    # Such a host has neither slot -- must not raise.
    class _Bare: pass
    TGCreditAction_Create('Episode 1 - "Picking up the Pieces"', _Bare(),
                          0.5, 0.025, 5.0, 0.25, 0.5, 12).Play()  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_credit_action_play.py -q`
Expected: FAIL — `AttributeError: 'TGCreditAction' object has no attribute '_fade_in'`,
and the episode string lands in `_active_texts`.

- [ ] **Step 3: Write the implementation**

In `engine/appc/actions.py`, in `TGCreditAction.__init__`, after the `_duration_s` line
add:

```python
        self._fade_in = float(args[5]) if len(args) > 5 else 0.0
        self._fade_out = float(args[6]) if len(args) > 6 else 0.0
```

and replace `_do_play` with:

```python
    def _do_play(self) -> None:
        # Overriding _do_play (not Play) lets the base TGAction.Play() call
        # Completed(), so a sequence step chained after this credit action
        # advances. The _played guard keeps the *visible* text idempotent when a
        # sequence re-fires Play on the same action; Completed() itself is
        # idempotent (it clears _completed_events after the first dispatch).
        if self._played: return
        self._played = True
        host = self._subtitle

        # EpisodeTitleAction and MissionLib.TextBanner both land here, aimed at
        # the same SubtitleWindow. The text's shape is the only discriminator:
        # if it parses as an episode title it gets the two-tier card, else it is
        # a transient banner in the caption box.
        parsed = parse_episode_title(self._text)
        add_title = getattr(host, "_add_episode_title", None)
        if parsed is not None and add_title is not None:
            eyebrow, title = parsed
            add_title(eyebrow, title, self._duration_s,
                      self._fade_in, self._fade_out)
            return

        adder = getattr(host, "_add_text", None)
        if adder is None: return
        adder(self._text, self._duration_s, self._fade_in, self._fade_out)
```

Update the block comment above the class (`actions.py:816-819`) to:

```python
# ── TGCreditAction ──────────────────────────────────────────────────────────
# Timed text overlay on the SubtitleWindow. Two SDK callers: MissionLib.
# TextBanner (transient notices) and MissionLib.EpisodeTitleAction (the episode
# title card) -- told apart by parse_episode_title(). We honour the SDK's
# duration and fade args; its x/y/font-size/colour are deliberately ignored
# (our layout owns placement).
# Spec: docs/superpowers/specs/2026-07-13-subtitle-episode-title-visual-language-design.md
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_credit_action_play.py tests/unit/test_actions.py tests/unit/test_helm_entering_banner.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/appc/actions.py tests/unit/test_credit_action_play.py
git commit -m "feat(ui): route episode titles and banners to their own subtitle slots"
```

---

### Task 4: CEF — restyled caption box and episode title card

The visual half. No Python change.

**Files:**
- Modify: `native/assets/ui-cef/index.html:560` (add the episode element)
- Modify: `native/assets/ui-cef/js/sdk_mirror.js` (new `lines` shape; speaker block; `renderEpisodeTitle`)
- Modify: `native/assets/ui-cef/css/sdk_mirror.css:8-31` (rewrite `#sdk-subtitle`; add episode rules)
- Test: `tests/ui/test_subtitle_styling.py` (create — asserts the assets match the house tokens)

**Interfaces:**
- Consumes: the payload keys from Task 2 (`lines[].text`, `lines[].opacity`, `speaker`,
  `speech`, `title_eyebrow`, `title_text`, `title_opacity`).
- Produces: nothing consumed downstream.

- [ ] **Step 1: Write the failing test**

The CEF assets have no JS test runner, so guard the two regressions that actually
matter — the off-theme font/palette creeping back, and the DOM contract between
`sdk_mirror.js` and `index.html` drifting. Create `tests/ui/test_subtitle_styling.py`:

```python
"""The caption box and episode title card must stay on the house tokens.

sdk_mirror.css was the last place in the UI still on bare `sans-serif` with a
blue palette; these assertions stop it coming back, and pin the DOM contract
between index.html and sdk_mirror.js.
Spec: docs/superpowers/specs/2026-07-13-subtitle-episode-title-visual-language-design.md
"""
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parents[2] / "native" / "assets" / "ui-cef"
CSS = (UI / "css" / "sdk_mirror.css").read_text()
JS = (UI / "js" / "sdk_mirror.js").read_text()
HTML = (UI / "index.html").read_text()


def _rule(css: str, selector: str) -> str:
    """Return the declaration block for `selector` (raises if absent)."""
    start = css.index(selector + " {") + len(selector) + 2
    return css[start:css.index("}", start)]


def test_caption_box_uses_antonio_not_bare_sans_serif():
    assert 'font-family: "Antonio", sans-serif;' in _rule(CSS, "#sdk-subtitle")


def test_caption_box_uses_house_body_and_salmon_rule():
    rule = _rule(CSS, "#sdk-subtitle")
    assert "background: rgba(10, 10, 16, 0.85);" in rule
    assert "border-left: 4px solid rgb(216, 94, 86);" in rule
    assert "border-top-right-radius: 14px;" in rule


def test_old_blue_palette_is_gone():
    for dead in ("#3a6bb8", "#9cc4ff", "rgba(20, 40, 80"):
        assert dead not in _rule(CSS, "#sdk-subtitle")
        assert dead not in _rule(CSS, ".sdk-subtitle__speaker")


def test_speaker_is_its_own_block_in_chrome_orange():
    rule = _rule(CSS, ".sdk-subtitle__speaker")
    assert "display: block;" in rule
    assert "color: #d88450;" in rule
    assert "text-transform: uppercase;" in rule


def test_speaker_has_no_colon_suffix_in_js():
    # The speaker is a block above the line now, not an inline "LIU:" prefix.
    assert '":</span>' not in JS


def test_episode_card_uses_house_purple_eyebrow():
    assert "color: rgb(147, 103, 255);" in _rule(CSS, ".sdk-episode__eyebrow")


@pytest.mark.parametrize("selector", [
    "#sdk-episode-title", ".sdk-episode__eyebrow", ".sdk-episode__title",
])
def test_episode_card_rules_exist(selector):
    assert selector + " {" in CSS


def test_fades_are_not_css_transitions():
    # Opacity is pushed per-frame from Python so fades freeze under pause.
    # A CSS transition/animation here would run on wall-clock -- see the spec.
    for banned in ("transition", "animation", "@keyframes"):
        assert banned not in CSS


@pytest.mark.parametrize("dom_id", ["sdk-episode-title"])
def test_episode_element_exists_in_index_html(dom_id):
    assert 'id="' + dom_id + '"' in HTML


@pytest.mark.parametrize("cls", ["sdk-episode__eyebrow", "sdk-episode__title"])
def test_episode_children_exist_in_index_html(cls):
    assert 'class="' + cls + '"' in HTML


def test_js_reads_the_new_payload_keys():
    for key in ("title_eyebrow", "title_text", "title_opacity", "lines"):
        assert key in JS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ui/test_subtitle_styling.py -q`
Expected: FAIL — `#sdk-subtitle` is still `font-family: sans-serif;` on the blue
palette, and `.sdk-episode__eyebrow {` is absent from the CSS.

- [ ] **Step 3: Write the implementation**

**3a.** In `native/assets/ui-cef/index.html`, replace line 560:

```html
      <div id="sdk-subtitle" class="sdk-mirror" hidden></div>
      <div id="sdk-episode-title" class="sdk-mirror" hidden>
        <div class="sdk-episode__eyebrow"></div>
        <div class="sdk-episode__title"></div>
      </div>
```

**3b.** In `native/assets/ui-cef/js/sdk_mirror.js`, replace `setSdkMirror` and
`renderSubtitle`, and add `renderEpisodeTitle`:

```js
function setSdkMirror(payload) {
  const entries = (payload && payload.entries) || [];
  const subtitle = entries.find(e => e.type === "subtitle");
  renderSubtitle(subtitle);
  renderEpisodeTitle(subtitle);
  renderStylizedStack(entries.filter(e => e.type === "stylized"));
}

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
  // Banner lines carry their own fade opacity (computed in Python, so it
  // freezes under pause); crew captions pop on and off at full opacity.
  const parts = lines.map(line =>
    '<span class="sdk-subtitle__line" style="opacity:' +
    Number(line.opacity).toFixed(3) + '">' + escapeHtml(line.text) + "</span>"
  );
  if (hasSpeech) {
    const speaker = entry.speaker
      ? '<span class="sdk-subtitle__speaker">' +
        escapeHtml(entry.speaker) + "</span>"
      : "";
    parts.push(speaker + escapeHtml(entry.speech));
  }
  el.innerHTML = parts.join("<br>");
}

function renderEpisodeTitle(entry) {
  const el = document.getElementById("sdk-episode-title");
  if (!el) return;
  if (!entry || !entry.visible || !entry.title_text) {
    el.hidden = true;
    return;
  }
  el.hidden = false;
  el.querySelector(".sdk-episode__eyebrow").textContent =
    entry.title_eyebrow || "";
  el.querySelector(".sdk-episode__title").textContent = entry.title_text;
  el.style.opacity = Number(
    entry.title_opacity === undefined ? 1 : entry.title_opacity
  ).toFixed(3);
}
```

`renderStylizedStack` and `escapeHtml` are unchanged.

**3c.** In `native/assets/ui-cef/css/sdk_mirror.css`, replace the header comment and
the `#sdk-subtitle` + `.sdk-subtitle__speaker` rules (lines 1-31) with:

```css
/* SDK UI mirror slots — receives JSON payloads from SDKMirrorPanel.
   #sdk-subtitle is the caption box: crew speech (speaker + line) and transient
   mission banners. #sdk-episode-title is the two-tier episode card.
   #sdk-stylized-stack is a centred column of dauntless modals for
   STStylizedWindow instances. SDK pixel coords are ignored; layout is
   dictated by these slot rules.

   Fades are driven by a per-frame `opacity` in the payload, NOT by CSS
   transitions — a transition runs on wall-clock and would keep animating while
   the sim is frozen (pause / DevTools).
   Spec: docs/superpowers/specs/2026-07-13-subtitle-episode-title-visual-language-design.md */

#sdk-subtitle {
  position: absolute;
  left: 50%;
  bottom: 14vh;                             /* clears the 6.25vh max letterbox bar */
  transform: translateX(-50%);
  max-width: 52vw;
  padding: 10px 20px 12px 16px;
  text-align: left;

  background: rgba(10, 10, 16, 0.85);       /* --bc-body-bg */
  border-left: 4px solid rgb(216, 94, 86);  /* --bc-menu1-base */
  border-top-right-radius: 14px;            /* the bc-panel tell — no other radius */

  font-family: "Antonio", sans-serif;
  font-size: 17px;
  line-height: 1.25;
  color: rgb(235, 225, 255);                /* --bc-label-text */
  text-shadow: 0 0 3px #000;
  z-index: 50;
  pointer-events: none;
}

.sdk-subtitle__speaker {
  display: block;                           /* own line, no colon */
  color: #d88450;                           /* chrome orange, per reticle names */
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  margin-bottom: 3px;
}

.sdk-subtitle__line {
  display: inline-block;
}

#sdk-episode-title {
  position: absolute;
  left: 5vw;
  bottom: 16vh;
  font-family: "Antonio", sans-serif;
  text-align: left;
  z-index: 50;
  pointer-events: none;
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

Leave the `#sdk-stylized-stack` rules below untouched.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/ui/test_subtitle_styling.py -q`
Expected: PASS

- [ ] **Step 5: Run the full gate**

Run: `scripts/check_tests.sh`
Expected: exit 0. Any failure not already in `tests/known_failures.txt` (the 7
headless-GL `FrameTest`s) is a regression from this change — fix it, do not baseline it.

- [ ] **Step 6: Commit**

```bash
git add native/assets/ui-cef/index.html native/assets/ui-cef/js/sdk_mirror.js native/assets/ui-cef/css/sdk_mirror.css tests/ui/test_subtitle_styling.py
git commit -m "feat(ui): restyle the caption box and add the episode title card"
```

---

### Task 5: Live verification

The gate proves the payload and the assets; it cannot prove the thing looks right.

**Files:** none (verification only).

- [ ] **Step 1: Build and launch in developer mode**

```bash
cmake -B build -S . && cmake --build build -j
./build/dauntless --developer
```

- [ ] **Step 2: Load E1M1**

Pause menu → **Load Mission…** → Maelstrom → Episode 1 → E1M1.

- [ ] **Step 3: Observe and report**

Watch the opening cutscene and confirm:
- the episode card fades in bottom-left over the establishing shot — purple `EPISODE 1`
  eyebrow above a large white `PICKING UP THE PIECES`, holding ~5s then fading out;
- Admiral Liu's and Picard's lines render in the new caption box — dark body, salmon
  left rule, orange uppercase speaker name on its own line above the text;
- neither element is clipped by the letterbox bars;
- pressing ESC mid-fade freezes the fade rather than letting it continue.

Report what you see. Do **not** claim this task complete without having actually run
it — if you cannot launch the binary, say so and stop.
