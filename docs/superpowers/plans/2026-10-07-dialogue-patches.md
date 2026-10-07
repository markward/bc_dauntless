# Dialogue Patches Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Insert lines after an existing scripted mission line, and replace a line's text/sound, at runtime, without editing the SDK; first use: E1M2's four cut replicator lines.

**Architecture:** A runtime data file (`native/assets/dialogue/patches.json`, keyed by TGL path) is read by a new module `engine/appc/dialogue_patches.py`. Replacement is merged into a `TGLocalizationDatabase` when `TGLocalizationManager` builds it. Insertion hooks `CharacterAction.Completed()`: a speak action whose `(database TGL, line key)` has inserts plays them as a `TGSequence` and only completes itself when that sequence ends, so whatever the mission chained on it waits.

**Tech Stack:** Python 3.11 engine shim (`engine/appc`), pytest, BC SDK scripts run headless.

**Spec:** `docs/superpowers/specs/2026-10-07-dialogue-patches-design.md`

## Global Constraints

- Patches always apply; no toggle.
- Never edit any SDK file (`<sdk>/Build/scripts/...`) or any BC content file.
- Data file: `native/assets/dialogue/patches.json`, resolved at use via `paths.project_asset_root()` — never a module-level path constant (`tests/unit/test_path_indirection.py`).
- Never spell `game` or `sdk` as a path segment in engine/tools/tests code; use `engine.paths`.
- TGL paths in the data are game-root-relative, matched case-insensitively with `\` and `/` alike.
- Speaker form `<set>/<object name>`, resolved with `CharacterClass_GetObjectStrict`; bridge-set speakers get `("Captain", 1)`, others `(None, 0)`.
- Out of scope: mod-supplied patches, inserting before a line, direct `SayLine`/`SpeakLine` anchors.
- Shared checkout rules (CLAUDE.md): never `git checkout --`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`/`git add .`. Stage explicit paths. Work on `feat/crew-hazard-prompts` in worktree `.claude/worktrees/crew-hazard-prompts`.
- A PreToolUse hook blocks any git command line containing the word "restore" — keep it out of commit messages (say "reinsert").
- Run every command from the worktree root with `uv run`.

## Review Focus

1. **Anchor aborted while its inserts play** (mission swap or a killed conversation mid-insert): the inserts stop, the anchor never completes, nothing chained on it runs. Test in Task 3.
2. **Anchor with no database of its own** (SDK passes `None`; the line falls back to the character's DB): no crash, no inserts, completes normally. Test in Task 3.
3. **Missing or malformed `patches.json`**: BC plays unchanged, the error is dev-logged, never raised into the game. Test in Task 1.
4. **`Completed()` reached twice for one play** (e.g. a skip racing the natural end): inserts play once, the anchor completes once. Test in Task 3.
5. **The script spells the TGL differently from the data** (`E1M2.tgl` vs `E1M2.TGL`, backslashes): still matches. Test in Task 1.

---

### Task 1: `dialogue_patches` — load, validate, look up

**Files:**
- Create: `engine/appc/dialogue_patches.py`
- Create: `native/assets/dialogue/patches.json` (empty table `{}` for now)
- Test: `tests/unit/test_dialogue_patches.py`

**Interfaces:**
- Produces:
  - `patches_path() -> pathlib.Path`
  - `norm_tgl(path) -> str`
  - `table() -> dict` — `{norm_tgl: {"insert_after": {key: [insert, ...]}, "replace": {key: {"text"?: str, "sound"?: str}}}}`; `{}` when missing/invalid
  - `reset_cache() -> None`
  - `inserts_for(tgl: str, key) -> list[dict]` — each `{"speaker": "set/name", "key": str, "tgl"?: str}`
  - `replacements_for(tgl: str) -> dict[str, dict]`
  - `validate_shape(raw) -> list[str]` — empty list when valid

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_dialogue_patches.py
"""engine.appc.dialogue_patches: the runtime patch table
(spec docs/superpowers/specs/2026-10-07-dialogue-patches-design.md)."""
import json

import pytest

from engine.appc import dialogue_patches as dp

E1M2 = "data/TGL/Maelstrom/Episode 1/E1M2.TGL"


@pytest.fixture
def patches(monkeypatch, tmp_path):
    """Point the module at a temp patches.json; returns a writer."""
    path = tmp_path / "patches.json"
    monkeypatch.setattr(dp, "patches_path", lambda: path)
    dp.reset_cache()

    def write(data):
        path.write_text(json.dumps(data) if not isinstance(data, str) else data)
        dp.reset_cache()
    yield write
    dp.reset_cache()


def test_patches_path_is_under_the_project_assets():
    from engine import paths
    assert dp.patches_path() == paths.project_asset_root() / "dialogue" / "patches.json"


def test_inserts_are_looked_up_by_tgl_and_key(patches):
    patches({E1M2: {"insert_after": {"A": [{"speaker": "MiscEng/Soams", "key": "B"}]}}})
    assert dp.inserts_for(E1M2, "A") == [{"speaker": "MiscEng/Soams", "key": "B"}]
    assert dp.inserts_for(E1M2, "Other") == []
    assert dp.inserts_for("data/TGL/Elsewhere.tgl", "A") == []


def test_tgl_spelling_differences_still_match(patches):
    patches({E1M2: {"insert_after": {"A": [{"speaker": "bridge/XO", "key": "B"}]}}})
    for spelling in ("data/TGL/Maelstrom/Episode 1/E1M2.tgl",
                     "data\\TGL\\Maelstrom\\Episode 1\\E1M2.TGL",
                     "DATA/tgl/maelstrom/episode 1/e1m2.tgl"):
        assert dp.inserts_for(spelling, "A"), spelling


def test_replacements_are_looked_up_by_tgl(patches):
    patches({E1M2: {"replace": {"K": {"text": "New."}}}})
    assert dp.replacements_for("data/TGL/Maelstrom/Episode 1/E1M2.tgl") == {"K": {"text": "New."}}
    assert dp.replacements_for("data/TGL/Elsewhere.tgl") == {}


def test_a_missing_file_means_no_patches(patches):
    assert dp.table() == {}
    assert dp.inserts_for(E1M2, "A") == []


@pytest.mark.parametrize("bad", [
    "{not json",
    "[]",
    {E1M2: {"insert_after": {"A": [{"speaker": "Soams", "key": "B"}]}}},
    {E1M2: {"insert_after": {"A": []}}},
    {E1M2: {"insert_after": {"A": [{"speaker": "bridge/XO"}]}}},
    {E1M2: {"replace": {"K": {}}}},
    {E1M2: {"replace": {"K": {"voice": "x.wav"}}}},
    {E1M2: {"surprise": {}}},
])
def test_a_malformed_file_means_no_patches_and_never_raises(patches, bad):
    patches(bad)
    assert dp.table() == {}
    assert dp.inserts_for(E1M2, "A") == []


def test_validate_shape_names_each_problem():
    errors = dp.validate_shape({E1M2: {"insert_after": {"A": [{"speaker": "Soams", "key": "B"}]},
                                       "replace": {"K": {"voice": "x"}}}})
    assert len(errors) == 2
    assert any("Soams" in e for e in errors)
    assert any("K" in e for e in errors)


def test_validate_shape_accepts_a_good_table():
    assert dp.validate_shape({E1M2: {
        "insert_after": {"A": [{"speaker": "bridge/XO", "key": "B", "tgl": "data/TGL/Dauntless Crew.tgl"}]},
        "replace": {"K": {"text": "t", "sound": "sfx/x.wav"}}}}) == []


def test_an_edited_file_is_picked_up_without_a_restart(patches):
    patches({E1M2: {"replace": {"K": {"text": "one"}}}})
    assert dp.replacements_for(E1M2)["K"]["text"] == "one"
    import os, time
    p = dp.patches_path()
    p.write_text(json.dumps({E1M2: {"replace": {"K": {"text": "two"}}}}))
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert dp.replacements_for(E1M2)["K"]["text"] == "two"


def test_the_shipped_file_is_well_formed():
    raw = json.loads(dp.patches_path().read_text(encoding="utf-8"))
    assert dp.validate_shape(raw) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_dialogue_patches.py -q`
Expected: collection ERROR — `ImportError: cannot import name 'dialogue_patches'`

- [ ] **Step 3: Write the module and the empty data file**

```python
# engine/appc/dialogue_patches.py
"""Dialogue patches: insert lines after a scripted line, replace a line's
text and/or sound -- at runtime, without editing the SDK.

Spec: docs/superpowers/specs/2026-10-07-dialogue-patches-design.md.
Data: native/assets/dialogue/patches.json, keyed by the TGL a line is read
from (game-root-relative, matched case-insensitively, either slash):

    {"data/TGL/Maelstrom/Episode 1/E1M2.TGL": {
        "insert_after": {"<anchor key>": [{"speaker": "<set>/<object>",
                                           "key": "<line key>",
                                           "tgl": "<optional other TGL>"}]},
        "replace": {"<key>": {"text": "...", "sound": "sfx/..."}}}}

Resolved at use and re-read when the file changes. A missing or malformed
file means no patches: BC plays unchanged and the problem is dev-logged.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import engine.dev_mode as dev_mode

_SPEAKER = re.compile(r"^[^/]+/[^/]+$")
_ENTRY_KEYS = {"insert_after", "replace"}
_INSERT_KEYS = {"speaker", "key", "tgl"}
_REPLACE_KEYS = {"text", "sound"}

_cache = None   # (path, mtime_ns, table)


def patches_path() -> Path:
    from engine import paths
    return paths.project_asset_root() / "dialogue" / "patches.json"


def norm_tgl(path) -> str:
    return str(path).replace("\\", "/").lower()


def reset_cache() -> None:
    global _cache
    _cache = None


def table() -> dict:
    global _cache
    path = patches_path()
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return {}
    if _cache is not None and _cache[0] == path and _cache[1] == mtime:
        return _cache[2]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        errors = validate_shape(raw)
        if errors:
            raise ValueError("; ".join(errors))
        loaded = {norm_tgl(tgl): {"insert_after": entry.get("insert_after", {}),
                                  "replace": entry.get("replace", {})}
                  for tgl, entry in raw.items()}
    except Exception as exc:
        dev_mode.log_swallowed("dialogue patches load %s" % path, exc)
        loaded = {}
    _cache = (path, mtime, loaded)
    return loaded


def inserts_for(tgl, key) -> list:
    if not tgl or key is None:
        return []
    return table().get(norm_tgl(tgl), {}).get("insert_after", {}).get(str(key), [])


def replacements_for(tgl) -> dict:
    if not tgl:
        return {}
    return table().get(norm_tgl(tgl), {}).get("replace", {})


def validate_shape(raw) -> list:
    if not isinstance(raw, dict):
        return ["top level must be an object keyed by TGL path"]
    errors = []
    for tgl, entry in raw.items():
        if not isinstance(entry, dict) or set(entry) - _ENTRY_KEYS:
            errors.append("%s: only 'insert_after' and 'replace' are allowed" % tgl)
            continue
        inserts = entry.get("insert_after", {})
        if not isinstance(inserts, dict):
            errors.append("%s: insert_after must be an object" % tgl)
            inserts = {}
        for anchor, lines in inserts.items():
            if not isinstance(lines, list) or not lines:
                errors.append("%s: %s: inserts must be a non-empty list" % (tgl, anchor))
                continue
            for ins in lines:
                if (not isinstance(ins, dict) or set(ins) - _INSERT_KEYS
                        or not isinstance(ins.get("key"), str)
                        or not isinstance(ins.get("tgl", ""), str)):
                    errors.append("%s: %s: insert needs 'speaker' and 'key' (optional 'tgl'): %r"
                                  % (tgl, anchor, ins))
                elif not _SPEAKER.match(str(ins.get("speaker", ""))):
                    errors.append("%s: %s: speaker must be '<set>/<object>': %r"
                                  % (tgl, anchor, ins.get("speaker")))
        replaces = entry.get("replace", {})
        if not isinstance(replaces, dict):
            errors.append("%s: replace must be an object" % tgl)
            replaces = {}
        for key, rep in replaces.items():
            if (not isinstance(rep, dict) or not rep or set(rep) - _REPLACE_KEYS
                    or not all(isinstance(v, str) for v in rep.values())):
                errors.append("%s: replace %s needs 'text' and/or 'sound' strings" % (tgl, key))
    return errors
```

```json
{}
```
(save the second block as `native/assets/dialogue/patches.json`)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_dialogue_patches.py tests/unit/test_path_indirection.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add engine/appc/dialogue_patches.py native/assets/dialogue/patches.json tests/unit/test_dialogue_patches.py
git commit -m "feat(dialogue): runtime patch table for inserting and replacing lines"
```

---

### Task 2: Replacement merged into the database at load; WAV guards cover replacement voices

**Files:**
- Modify: `engine/appc/localization.py` (`TGLocalizationManager._build_database`)
- Modify: `tests/tools/test_dauntless_dialogue_drift.py` (two WAV tests)
- Test: `tests/unit/test_dialogue_patch_replace.py`

**Interfaces:**
- Consumes: `dialogue_patches.replacements_for(tgl) -> dict`, `dialogue_patches.patches_path()`, `dialogue_patches.reset_cache()`
- Produces: `TGLocalizationManager.Load(filename)` returns a database whose strings/sounds carry that TGL's `replace` entries.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_dialogue_patch_replace.py
"""dialogue_patches 'replace' entries are merged into a TGL's database when
TGLocalizationManager builds it."""
import json

import pytest

from engine.appc import dialogue_patches as dp
from engine.appc.localization import TGLocalizationManager
from engine.missions.tgl_reader import write_tgl

TGL = "data/TGL/Test/Patched.tgl"


@pytest.fixture
def setup(monkeypatch, tmp_path):
    """A fake install with one TGL, and a patches.json writer."""
    from engine import paths
    game = tmp_path / "install"
    (game / "data" / "TGL" / "Test").mkdir(parents=True)
    (game / "data" / "TGL" / "Test" / "Patched.tgl").write_bytes(write_tgl([
        ("Keep", "Original keep.", "sfx/keep.mp3"),
        ("Swap", "Original swap.", "sfx/swap.mp3"),
    ]))
    monkeypatch.setattr(paths, "game_asset", lambda rel: game / rel)
    patch_file = tmp_path / "patches.json"
    monkeypatch.setattr(dp, "patches_path", lambda: patch_file)
    dp.reset_cache()

    def write(data):
        patch_file.write_text(json.dumps(data))
        dp.reset_cache()
    yield write
    dp.reset_cache()


def test_no_patch_leaves_the_database_as_bc_ships_it(setup):
    db = TGLocalizationManager().Load(TGL)
    assert db.GetString("Swap") == "Original swap."
    assert db.GetFilename("Swap") == "sfx/swap.mp3"


def test_text_only_replacement_keeps_the_voice(setup):
    setup({TGL: {"replace": {"Swap": {"text": "New swap."}}}})
    db = TGLocalizationManager().Load(TGL)
    assert db.GetString("Swap") == "New swap."
    assert db.GetFilename("Swap") == "sfx/swap.mp3"
    assert db.GetString("Keep") == "Original keep."


def test_sound_only_replacement_keeps_the_text(setup):
    setup({TGL: {"replace": {"Swap": {"sound": "sfx/new.wav"}}}})
    db = TGLocalizationManager().Load(TGL)
    assert db.GetString("Swap") == "Original swap."
    assert db.GetFilename("Swap") == "sfx/new.wav"


def test_a_replace_entry_can_add_a_line_bc_never_had(setup):
    setup({TGL: {"replace": {"Brand": {"text": "Brand new.", "sound": "sfx/brand.wav"}}}})
    db = TGLocalizationManager().Load(TGL)
    assert db.HasString("Brand")
    assert db.GetFilename("Brand") == "sfx/brand.wav"


def test_the_script_spelling_of_the_path_still_matches(setup):
    setup({"data/TGL/Test/PATCHED.TGL": {"replace": {"Swap": {"text": "New swap."}}}})
    db = TGLocalizationManager().Load(TGL)
    assert db.GetString("Swap") == "New swap."
```

Replace the two WAV tests at the end of `tests/tools/test_dauntless_dialogue_drift.py` (`test_every_wav_is_a_format_the_native_decoder_accepts` and `test_every_shipped_voice_file_is_a_listed_dauntless_line`) with:

```python
def _listed_wavs() -> set:
    """Every WAV the game is told to play from replacements: our own crew
    lines, plus replacement voices in native/assets/dialogue/patches.json."""
    import json
    from engine.appc import dialogue_patches
    listed = {sound for _k, _t, sound in g.entries() if sound.lower().endswith(".wav")}
    raw = json.loads(dialogue_patches.patches_path().read_text(encoding="utf-8"))
    for entry in raw.values():
        for rep in entry.get("replace", {}).values():
            sound = rep.get("sound", "")
            if sound.lower().endswith(".wav"):
                listed.add(sound)
    return listed


def test_every_wav_is_a_format_the_native_decoder_accepts():
    """native/src/audio/src/wav.cc takes PCM only (format 1, not
    WAVE_FORMAT_EXTENSIBLE), 1-2 channels, 8 or 16 bit."""
    import struct
    for sound in sorted(_listed_wavs()):
        data = (mods.replacements_root() / sound).read_bytes()
        assert data[:4] == b"RIFF" and data[8:12] == b"WAVE", sound
        off = 12
        while data[off:off + 4] != b"fmt ":
            off += 8 + struct.unpack_from("<I", data, off + 4)[0]
        code, channels, _rate, _bps, _align, bits = struct.unpack_from(
            "<HHIIHH", data, off + 8)
        assert (code, channels in (1, 2), bits in (8, 16)) == (1, True, True), sound


def test_every_shipped_voice_file_is_a_listed_line():
    """.gitignore un-ignores replacements/sfx WAVs for our own lines; this
    keeps that exception from admitting anything else (BC audio is
    copyrighted and must never be committed)."""
    root = mods.replacements_root()
    shipped = {p.relative_to(root).as_posix()
               for p in (root / "sfx").rglob("*") if p.is_file()}
    assert shipped <= _listed_wavs()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_dialogue_patch_replace.py tests/tools/test_dauntless_dialogue_drift.py -q`
Expected: the four replacement tests FAIL (BC text/sound returned unchanged); `test_no_patch_leaves_the_database_as_bc_ships_it` and the drift tests PASS.

- [ ] **Step 3: Merge replacements in `_build_database`**

In `engine/appc/localization.py`, replace the final `return TGLocalizationDatabase(...)` of `TGLocalizationManager._build_database` (after the `read_tgl` try/except) with:

```python
        strings, sounds = dict(parsed.strings), dict(parsed.sounds)
        # Dialogue patches (engine/appc/dialogue_patches.py): per-key text
        # and/or sound overrides for this TGL, applied in memory only.
        from engine.appc import dialogue_patches
        for key, rep in dialogue_patches.replacements_for(filename).items():
            if "text" in rep:
                strings[key] = rep["text"]
            if "sound" in rep:
                sounds[key] = rep["sound"]
        return TGLocalizationDatabase(filename, strings=strings, sounds=sounds)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_dialogue_patch_replace.py tests/tools/test_dauntless_dialogue_drift.py tests/missions -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add engine/appc/localization.py tests/unit/test_dialogue_patch_replace.py tests/tools/test_dauntless_dialogue_drift.py
git commit -m "feat(dialogue): merge patch replacements into TGL databases; WAV guards cover replacement voices"
```

---

### Task 3: Insertion — an anchor line plays its inserts before completing

**Files:**
- Modify: `engine/appc/dialogue_patches.py` (add `insert_actions`, `play_then`)
- Modify: `engine/appc/ai.py` (`CharacterAction.__init__`, `Play`, new `Completed`, `Abort`)
- Test: `tests/unit/test_dialogue_patch_insert.py`

**Interfaces:**
- Consumes: `dialogue_patches.inserts_for(tgl, key)`, `CharacterClass_GetObjectStrict(pSet, name)` (`engine/appc/characters.py`), `TGSequence_Create()` (`engine/appc/actions.py`), `TGLocalizationDatabase.GetSourceFilename()/HasString()`.
- Produces:
  - `dialogue_patches.insert_actions(anchor: CharacterAction) -> list[CharacterAction]`
  - `dialogue_patches.play_then(actions: list, fn: Callable[[], None]) -> TGSequence`
  - `CharacterAction._insert_seq: TGSequence | None`, `CharacterAction._inserts_done: bool`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_dialogue_patch_insert.py
"""An anchor CharacterAction plays its patched-in lines before it completes
(spec docs/superpowers/specs/2026-10-07-dialogue-patches-design.md)."""
import App
import pytest

from engine.appc import crew_speech, dialogue_patches as dp
from engine.appc.actions import TGAction, TGSequence_Create
from engine.appc.characters import CharacterClass_Create
from engine.appc.localization import TGLocalizationDatabase
from engine.appc.sets import SetClass

TGL = "data/TGL/Test/Mission.tgl"


class _Hold(TGAction):
    def Play(self):
        self._playing = True


@pytest.fixture
def world(monkeypatch):
    """A bridge set with an XO, a viewscreen set with Soams, a mission DB,
    and a patch table the test fills in. Every line spoken is recorded."""
    sets = {}
    for set_name, obj in (("bridge", "XO"), ("MiscEng", "Soams")):
        pset = SetClass()
        App.g_kSetManager.AddSet(pset, set_name)
        pset.AddObjectToSet(CharacterClass_Create("", ""), obj)
        sets[set_name] = pset
    db = TGLocalizationDatabase(TGL, strings={k: k + " text" for k in
                                             ("Anchor", "Ins1", "Ins2", "After")})
    table = {}
    monkeypatch.setattr(dp, "inserts_for",
                        lambda tgl, key: table.get((dp.norm_tgl(tgl), key), []))
    spoken = []
    real_emit = crew_speech.emit

    def spy(speaker, d, line_id, priority):
        spoken.append(str(line_id))
        return real_emit(speaker, d, line_id, priority)

    monkeypatch.setattr(crew_speech, "emit", spy)
    yield {"db": db, "table": table, "spoken": spoken, "sets": sets}
    for set_name in sets:
        App.g_kSetManager.DeleteSet(set_name)


def _patch(world, anchor, *inserts):
    world["table"][(dp.norm_tgl(TGL), anchor)] = [
        {"speaker": s, "key": k} for s, k in inserts]


def _line(world, key, db=None, speaker=("bridge", "XO")):
    char = App.CharacterClass_GetObject(App.g_kSetManager.GetSet(speaker[0]), speaker[1])
    return App.CharacterAction_Create(char, App.CharacterAction.AT_SAY_LINE, key,
                                      "Captain", 1, world["db"] if db is None else db)


def _run(seconds=30.0):
    from tests.helpers import headless_mission as hm
    hm.tick(seconds)


def test_no_patch_completes_exactly_as_before(world):
    seq = TGSequence_Create()
    seq.AppendAction(_line(world, "Anchor"))
    seq.AppendAction(_line(world, "After"))
    seq.Play()
    _run()
    assert world["spoken"] == ["Anchor", "After"]
    assert not seq.IsPlaying()


def test_inserts_play_after_the_anchor_and_before_what_follows(world):
    _patch(world, "Anchor", ("MiscEng/Soams", "Ins1"), ("bridge/XO", "Ins2"))
    seq = TGSequence_Create()
    seq.AppendAction(_line(world, "Anchor"))
    seq.AppendAction(_line(world, "After"))
    seq.Play()
    _run()
    assert world["spoken"] == ["Anchor", "Ins1", "Ins2", "After"]


def test_an_explicit_dependent_of_the_anchor_also_waits(world):
    _patch(world, "Anchor", ("bridge/XO", "Ins1"))
    anchor = _line(world, "Anchor")
    seq = TGSequence_Create()
    seq.AddAction(anchor)
    seq.AddAction(_line(world, "After"), anchor)
    seq.Play()
    _run()
    assert world["spoken"] == ["Anchor", "Ins1", "After"]


def test_skipping_the_anchor_still_plays_the_inserts(world):
    _patch(world, "Anchor", ("bridge/XO", "Ins1"))
    anchor = _line(world, "Anchor")
    seq = TGSequence_Create()
    seq.AppendAction(anchor)
    seq.AppendAction(_line(world, "After"))
    seq.Play()
    anchor.Skip()
    _run()
    assert world["spoken"] == ["Anchor", "Ins1", "After"]


def test_aborting_before_the_anchor_finishes_plays_no_inserts(world):
    _patch(world, "Anchor", ("bridge/XO", "Ins1"))
    hold = _Hold()
    seq = TGSequence_Create()
    seq.AppendAction(hold)
    seq.AppendAction(_line(world, "Anchor"))
    seq.Play()
    seq.Abort()
    _run()
    assert world["spoken"] == []


def test_aborting_while_inserts_play_stops_them_and_the_anchor(world):
    _patch(world, "Anchor", ("bridge/XO", "Ins1"), ("bridge/XO", "Ins2"))
    anchor = _line(world, "Anchor")
    seq = TGSequence_Create()
    seq.AppendAction(anchor)
    seq.AppendAction(_line(world, "After"))
    seq.Play()
    anchor.Completed()                 # anchor done speaking -> inserts start
    assert anchor._insert_seq is not None
    seq.Abort()
    _run()
    assert "After" not in world["spoken"]
    assert "Ins2" not in world["spoken"]
    assert anchor._insert_seq is None


def test_completed_twice_plays_inserts_once(world):
    _patch(world, "Anchor", ("bridge/XO", "Ins1"))
    anchor = _line(world, "Anchor")
    seq = TGSequence_Create()
    seq.AppendAction(anchor)
    seq.AppendAction(_line(world, "After"))
    seq.Play()
    anchor.Completed()
    anchor.Completed()
    _run()
    assert world["spoken"].count("Ins1") == 1
    assert world["spoken"].count("After") == 1


def test_a_missing_speaker_is_skipped_and_the_rest_play(world):
    _patch(world, "Anchor", ("bridge/Nobody", "Ins1"), ("bridge/XO", "Ins2"))
    seq = TGSequence_Create()
    seq.AppendAction(_line(world, "Anchor"))
    seq.AppendAction(_line(world, "After"))
    seq.Play()
    _run()
    assert world["spoken"] == ["Anchor", "Ins2", "After"]


def test_a_line_missing_from_the_database_is_skipped(world):
    _patch(world, "Anchor", ("bridge/XO", "NotInTheTGL"))
    seq = TGSequence_Create()
    seq.AppendAction(_line(world, "Anchor"))
    seq.AppendAction(_line(world, "After"))
    seq.Play()
    _run()
    assert world["spoken"] == ["Anchor", "After"]


def test_an_anchor_without_its_own_database_completes_normally(world):
    _patch(world, "Anchor", ("bridge/XO", "Ins1"))
    char = App.CharacterClass_GetObject(App.g_kSetManager.GetSet("bridge"), "XO")
    anchor = App.CharacterAction_Create(char, App.CharacterAction.AT_SAY_LINE,
                                        "Anchor", "Captain", 1, None)
    seq = TGSequence_Create()
    seq.AppendAction(anchor)
    seq.Play()
    _run()
    assert not seq.IsPlaying()
    assert "Ins1" not in world["spoken"]


def test_inserts_count_as_scripted_dialogue(world):
    from engine.appc import actions
    _patch(world, "Anchor", ("bridge/XO", "Ins1"))
    anchor = _line(world, "Anchor")
    seq = TGSequence_Create()
    seq.AppendAction(anchor)
    seq.Play()
    anchor.Completed()
    assert actions.scripted_line_pending() is True
    seq.Abort()


def test_viewscreen_speakers_get_bcs_viewscreen_arguments(world):
    _patch(world, "Anchor", ("MiscEng/Soams", "Ins1"), ("bridge/XO", "Ins2"))
    actions_ = dp.insert_actions(_line(world, "Anchor"))
    assert [(a._set_name, a._flag) for a in actions_] == [(None, 0), ("Captain", 1)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_dialogue_patch_insert.py -q`
Expected: `test_no_patch_completes_exactly_as_before` and `test_an_anchor_without_its_own_database_completes_normally` PASS; the rest FAIL (inserts never spoken / `AttributeError: _insert_seq` / `insert_actions` missing).

- [ ] **Step 3: Add `insert_actions` and `play_then` to `dialogue_patches.py`**

Append to `engine/appc/dialogue_patches.py`:

```python
# ── Insertion (called from CharacterAction.Completed, engine/appc/ai.py) ────

def insert_actions(anchor) -> list:
    """AT_SAY_LINE CharacterActions for the lines patched in after `anchor`,
    in order. An insert whose speaker is absent or whose line is not in its
    database is skipped (dev-logged). [] when nothing applies."""
    db = getattr(anchor, "_database", None)
    getter = getattr(db, "GetSourceFilename", None)
    tgl = getter() if callable(getter) else ""
    out = []
    for ins in inserts_for(tgl, getattr(anchor, "_detail", None)):
        try:
            out.append(_build_insert(ins, db))
        except Exception as exc:
            dev_mode.log_swallowed("dialogue patch insert %s" % ins.get("key"), exc)
    return out


def _build_insert(ins, anchor_db):
    import App
    from engine.appc.ai import CharacterAction
    from engine.appc.characters import CharacterClass_GetObjectStrict
    set_name, obj_name = ins["speaker"].split("/", 1)
    speaker = CharacterClass_GetObjectStrict(App.g_kSetManager.GetSet(set_name), obj_name)
    if speaker is None:
        raise LookupError("speaker %s is not present" % ins["speaker"])
    db = App.g_kLocalizationManager.Load(ins["tgl"]) if ins.get("tgl") else anchor_db
    if db is None or not db.HasString(ins["key"]):
        raise LookupError("line %s is not in its database" % ins["key"])
    # BC's own forms: bridge crew address the captain and turn; a viewscreen
    # speaker (E1M2's Soams) does not.
    addressee, flag = ("Captain", 1) if set_name == "bridge" else (None, 0)
    return CharacterAction(speaker, CharacterAction.AT_SAY_LINE, ins["key"],
                           addressee, flag, db)


def play_then(actions, fn):
    """Play `actions` in order, then call fn(). Returns the sequence, so the
    caller can Abort() it (fn is then never called)."""
    from engine.appc.actions import TGAction, TGSequence_Create

    class _Then(TGAction):
        def _do_play(self):
            fn()

    seq = TGSequence_Create()
    for action in actions:
        seq.AppendAction(action)
    seq.AppendAction(_Then())
    seq.Play()
    return seq
```

- [ ] **Step 4: Hook `CharacterAction`**

In `engine/appc/ai.py`, `CharacterAction.__init__`, after `self._speaking: bool = False` add:

```python
        # Dialogue patches (engine/appc/dialogue_patches.py): the sequence of
        # lines patched in after this one while it plays, and whether this
        # play has already looked for them.
        self._insert_seq = None
        self._inserts_done: bool = False
```

At the top of `CharacterAction.Play`, right after `self._speaking = False`, add:

```python
        self._insert_seq = None
        self._inserts_done = False
```

Add this method to `CharacterAction` directly above `def Skip(self)`:

```python
    def Completed(self) -> None:
        """A speak line with patched-in lines plays them before it completes,
        so every step chained on it -- AppendAction or an explicit
        AddAction(x, pAnchor) dependency -- waits for them
        (engine/appc/dialogue_patches.py). Skip routes here too, so skipping
        the anchor still plays the inserts; Abort never does."""
        if self._insert_seq is not None:
            return              # inserts still playing; they complete us
        if (self._playing and not self._inserts_done
                and self._action_type in (self.AT_SPEAK_LINE,
                                          self.AT_SPEAK_LINE_NO_FLAP_LIPS,
                                          self.AT_SAY_LINE,
                                          self.AT_SAY_LINE_AFTER_TURN)):
            self._inserts_done = True
            from engine.appc import dialogue_patches
            inserts = dialogue_patches.insert_actions(self)
            if inserts:
                self._insert_seq = dialogue_patches.play_then(
                    inserts, self._inserts_finished)
                return
        super().Completed()

    def _inserts_finished(self) -> None:
        self._insert_seq = None
        if self._playing:
            super().Completed()
```

At the very top of `CharacterAction.Abort` (before its existing first statement) add:

```python
        # Aborting an anchor whose patched-in lines are playing stops them;
        # the anchor then never completes (dialogue_patches).
        insert_seq, self._insert_seq = self._insert_seq, None
        if insert_seq is not None:
            insert_seq.Abort()
```

Why this reaches the anchor: `TGSequence.Abort()` (`engine/appc/actions.py`, the `Abort` after `_maybe_complete`) aborts every step that has started and is not in `_completed_actions`. An anchor playing its inserts has not called `TGAction.Completed`, so it is never in that set, and the mission sequence's `Abort()` calls the anchor's `Abort()`, which aborts the insert sequence.

Headless timing note for the tests: a spoken line with no audio backend completes on a realtime timer (`_complete_after` with the estimated duration), so `anchor.Completed()` called by hand in a test runs while that timer is still pending. When the timer later fires, `Completed()` runs again: it returns early while inserts play (`_insert_seq is not None`), and once they have finished it reaches `TGAction.Completed`, whose completed-event list is already empty, so nothing advances twice.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_dialogue_patch_insert.py tests/unit/test_scripted_line_pending.py tests/unit/test_character_action_verbs.py tests/unit/test_actions.py -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add engine/appc/dialogue_patches.py engine/appc/ai.py tests/unit/test_dialogue_patch_insert.py
git commit -m "feat(dialogue): anchor lines play their patched-in lines before completing"
```

---

### Task 4: E1M2's replicator lines, content validation, end-to-end, docs

**Files:**
- Modify: `native/assets/dialogue/patches.json`
- Modify: `tests/integration/test_e1m2_supply_transfer.py`
- Create: `tests/tools/test_dialogue_patches_content.py`
- Modify: `docs/engine/dauntless-crew-dialogue.md`, `CLAUDE.md` (the "Dauntless crew dialogue" row)

**Interfaces:**
- Consumes: everything from Tasks 1–3; `localization._resolve_tgl_path(filename) -> Path | None`; `tgl_reader.read_tgl(path).strings`; `paths.game_asset(rel)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/tools/test_dialogue_patches_content.py
"""Every entry in native/assets/dialogue/patches.json points at real
content: the TGL exists, anchors and inserted keys are in their databases,
replacement sounds exist."""
import json

import pytest

from engine import paths
from engine.appc import dialogue_patches as dp
from engine.appc.localization import _resolve_tgl_path
from engine.missions.tgl_reader import read_tgl


def _raw():
    return json.loads(dp.patches_path().read_text(encoding="utf-8"))


def _strings(tgl):
    path = _resolve_tgl_path(tgl)
    if path is None:
        try:
            paths.game_root()
        except paths.PathsUnresolved:
            pytest.skip("BC content not configured")
    assert path is not None, "TGL not found: %s" % tgl
    return read_tgl(path).strings


def test_the_file_is_well_formed():
    assert dp.validate_shape(_raw()) == []


def test_every_anchor_and_insert_exists():
    for tgl, entry in _raw().items():
        strings = _strings(tgl)
        added = set(entry.get("replace", {}))
        for anchor, inserts in entry.get("insert_after", {}).items():
            assert anchor in strings or anchor in added, (tgl, anchor)
            for ins in inserts:
                own = _strings(ins["tgl"]) if ins.get("tgl") else strings
                assert ins["key"] in own or ins["key"] in added, (tgl, ins)


def test_every_replacement_sound_exists_and_new_keys_are_complete():
    for tgl, entry in _raw().items():
        strings = _strings(tgl)
        for key, rep in entry.get("replace", {}).items():
            if "sound" in rep:
                assert paths.game_asset(rep["sound"]).is_file(), (tgl, key, rep["sound"])
            if key not in strings:
                assert set(rep) == {"text", "sound"}, (tgl, key)
```

In `tests/integration/test_e1m2_supply_transfer.py`, add below the existing test:

```python
_REINSERTED = ["E1M2TransferSupplies1", "E1M2TransferSupplies2",
               "E1M2TransferSupplies2a",
               "E1M2TransferSupplies3", "E1M2TransferSupplies3a",
               "E1M2TransferSupplies3b",
               "E1M2TransferSupplies4", "E1M2TransferSupplies4a",
               "E1M2TransferSupplies5", "E1M2TransferSupplies6"]


def _supply_lines(spoken):
    return [k for k in spoken if k.startswith("E1M2TransferSupplies")]


def _spy(monkeypatch):
    from engine.appc import crew_speech
    spoken = []
    real_emit = crew_speech.emit

    def spy(speaker, db, line_id, priority):
        spoken.append(str(line_id))
        return real_emit(speaker, db, line_id, priority)

    monkeypatch.setattr(crew_speech, "emit", spy)
    return spoken


def test_transfer_supplies_speaks_the_reinserted_replicator_lines(monkeypatch):
    hm.load("Maelstrom.Episode1.E1M2.E1M2")
    import Maelstrom.Episode1.E1M2.E1M2 as m
    spoken = _spy(monkeypatch)
    m.g_bMissionTerminate = 1
    m.g_bSuppliesTransfered = m.FALSE
    m.g_bSequenceRunning = m.FALSE
    m.g_bCanTransferSupplies = m.TRUE
    m.TransferSupplies(None)
    hm.tick(240.0)
    assert _supply_lines(spoken) == _REINSERTED


def test_win_with_transfer_speaks_the_reinserted_replicator_lines(monkeypatch):
    hm.load("Maelstrom.Episode1.E1M2.E1M2")
    import Maelstrom.Episode1.E1M2.E1M2 as m
    spoken = _spy(monkeypatch)
    m.g_bMissionTerminate = 1
    m.g_bSuppliesTransfered = m.FALSE
    m.WinWithTransfer()
    hm.tick(240.0)
    assert _supply_lines(spoken) == _REINSERTED
    # BC's unconditional "Lowering shields" follows 2a in this branch.
    assert spoken.index("LoweringShields") == spoken.index("E1M2TransferSupplies2a") + 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/tools/test_dialogue_patches_content.py tests/integration/test_e1m2_supply_transfer.py -q`
Expected: content tests PASS (empty table); the two new integration tests FAIL (no `2a`/`3a`/`3b`/`4a` spoken). If `WinWithTransfer` fails for another reason (e.g. `MissionLib.QueueActionToPlay` needs an existing master sequence), fix the test setup, not the engine, and note why in the test.

- [ ] **Step 3: Add the E1M2 patch**

Write `native/assets/dialogue/patches.json`:

```json
{
  "data/TGL/Maelstrom/Episode 1/E1M2.TGL": {
    "insert_after": {
      "E1M2TransferSupplies2": [
        {"speaker": "MiscEng/Soams", "key": "E1M2TransferSupplies2a"}
      ],
      "E1M2TransferSupplies3": [
        {"speaker": "MiscEng/Soams", "key": "E1M2TransferSupplies3a"},
        {"speaker": "bridge/XO", "key": "E1M2TransferSupplies3b"}
      ],
      "E1M2TransferSupplies4": [
        {"speaker": "bridge/Engineer", "key": "E1M2TransferSupplies4a"}
      ]
    }
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/tools/test_dialogue_patches_content.py tests/integration/test_e1m2_supply_transfer.py tests/unit/test_dialogue_patches.py -q`
Expected: all PASS

- [ ] **Step 5: Document**

Append to `docs/engine/dauntless-crew-dialogue.md`:

```markdown
## Dialogue patches — insert and replace lines in BC's missions

Spec: `docs/superpowers/specs/2026-10-07-dialogue-patches-design.md`.
Data: `native/assets/dialogue/patches.json` (read by the game at runtime,
so it lives with the assets, not in `tools/`). Always applied.

- **Insert:** `insert_after` under a TGL path lists lines to play after an
  anchor line. The anchor `CharacterAction` plays them before it completes
  (`CharacterAction.Completed` → `dialogue_patches.insert_actions`), so the
  mission's following steps wait. Sequenced lines only, not direct
  `SayLine` calls. Missing speaker or line: skipped, dev-logged.
- **Replace:** `replace` entries override a key's text and/or sound when
  the TGL loads (`TGLocalizationManager._build_database`), and can add a
  key BC never had. A replacement voice mirrors BC's folder as `.wav` under
  `native/assets/replacements/` so it never shadows BC's `.mp3`.
- **Where files go:** a cut BC line needs only a `patches.json` entry; a
  newly recorded line goes through `dauntless_crew.json` (text) +
  `replacements/sfx/...` (voice) + an insert with `"tgl": "data/TGL/Dauntless Crew.tgl"`.
- First use: E1M2's replicator exchange (`2a`, `3a` Soams; `3b` Saffi;
  `4a` Brex), present in `E1M2.TGL` with voices but never scripted by BC.
- Guards: `tests/tools/test_dialogue_patches_content.py` (every entry points
  at real content), `tests/integration/test_e1m2_supply_transfer.py`.
```

In `CLAUDE.md`, in the row starting `| Dauntless crew dialogue`, add `native/assets/dialogue/patches.json` to the files column and append to the description: `Dialogue patches insert lines after a scripted line or replace a line's text/sound at runtime, without SDK edits (first use: E1M2's cut replicator lines).` Keep the row under 1200 characters (`tests/docs/test_doc_consistency.py` enforces it); trim elsewhere in the row if needed.

- [ ] **Step 6: Run the full gate**

Run: `VIRTUAL_ENV= scripts/check_tests.sh`
Expected: `OK — no new failures.` Any listed failure is a regression this branch introduced; fix it, do not baseline it.

- [ ] **Step 7: Commit**

```bash
git add native/assets/dialogue/patches.json tests/tools/test_dialogue_patches_content.py tests/integration/test_e1m2_supply_transfer.py docs/engine/dauntless-crew-dialogue.md CLAUDE.md
git commit -m "feat(dialogue): reinsert E1M2's cut replicator lines via dialogue patches"
```

- [ ] **Step 8: Hand Mark the live check**

Tell Mark (no `#` comments in shell snippets):

```
cd /Users/mward/Documents/Projects/bc_dauntless/.claude/worktrees/crew-hazard-prompts && ./build/dauntless
```

Live check: play E1M2 to the supply transfer, once orbiting Haven after the win (TransferSupplies) and once arriving in orbit during the win conversation (WinWithTransfer). Expect Soams 2a, Soams 3a, Saffi 3b, Brex 4a in place, subtitles included.
