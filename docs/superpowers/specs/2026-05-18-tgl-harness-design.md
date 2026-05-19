# TGL Harness — Design

## Purpose

Smoke-test the TGL binary parser (`engine.missions.tgl_reader.read_tgl`)
against every `.tgl` file shipped with BC and the SDK, in the style of
`tools/mission_harness.py`. Catch regressions in the parser and surface
any file the parser can't handle — by parse error or by yielding no
strings/sounds.

This is a parser smoke test, not a content audit. It does not validate
key naming, sound-file references, or cross-mission consistency.

## Scope

In-scope:
- Discover every `.tgl` (case-insensitive) under `game/data/TGL/` and
  `sdk/Build/Data/TGL/`.
- Call `read_tgl` on each.
- Classify each as PASS or FAIL with a sub-reason.
- Print per-file results and a ranked summary of failure modes.

Out of scope:
- SDK Python module compatibility (not relevant — the parser is pure
  Python and reads bytes).
- Validating that `sounds[key]` filenames exist on disk.
- Validating that strings referenced by SDK mission scripts actually
  appear in some TGL.
- Pickling/round-trip checks.

## Location & invocation

New file: `tools/tgl_harness.py`. Run with:

```
uv run python tools/tgl_harness.py
```

No CLI flags in v1.

## Discovery

Two roots, walked recursively, suffix matched case-insensitively (the
game ships a mix of `.tgl` and `.TGL`):

```python
ROOTS = [
    PROJECT_ROOT / "game" / "data" / "TGL",
    PROJECT_ROOT / "sdk" / "Build" / "Data" / "TGL",
]
files = []
for root in ROOTS:
    if root.is_dir():
        files.extend(
            sorted(p for p in root.rglob("*") if p.suffix.lower() == ".tgl")
        )
```

A missing root is skipped silently — `game/` is a developer-supplied
install and may not be present in every checkout. The SDK root is
checked-in and should always be present, but the same skip logic
applies for symmetry.

Expected counts at time of writing: 57 in `game/data/TGL/`, 3 in
`sdk/Build/Data/TGL/` — 60 total.

## Per-file classification

```python
try:
    tgl = read_tgl(path)
except Exception as exc:
    status, reason = "fail", ("parse", exc)
else:
    if len(tgl.strings) == 0 and len(tgl.sounds) == 0:
        status, reason = "fail", ("empty", None)
    else:
        status, reason = "pass", (len(tgl.strings), len(tgl.sounds))
```

Three outcomes:

| Status | Sub-reason | Trigger |
|---|---|---|
| PASS | counts | `read_tgl` returns a `TGLFile` with at least one string or sound |
| FAIL | `parse` | `read_tgl` raised any exception (typically `TGLParseError`) |
| FAIL | `empty` | parsed cleanly but yielded zero strings AND zero sounds |

No real TGL in the project decodes to empty — the original engine
asserts on empty TGLs, so the game ships none. (The tutorial
placeholder `Episode.tgl` looks empty by intent, but actually contains
a single self-documenting `Unused` entry, so it parses as a normal
1-string/1-sound TGL.) The empty classification is therefore a
defensive guard against future parser regressions or hand-authored
TGLs: it's exercised by the unit test (via a synthetic `count=0`
file) but expected to produce zero hits when run against the
shipped data.

Catching bare `Exception` (not just `TGLParseError`) is deliberate —
the harness is the place where unexpected parser failures should
surface, not propagate up and kill the run.

## Output format

Per-file lines, mirroring `mission_harness.py` formatting (two-space
indent, four-char status marker):

```
  PASS  game/data/TGL/Maelstrom/Maelstrom.tgl  (strings=42 sounds=42)
  FAIL  sdk/Build/Data/TGL/Tutorial/Episode/Episode.tgl  empty: 0 strings, 0 sounds
  FAIL  game/data/TGL/Foo.tgl
         TGLParseError: keys section truncated
```

Path is rendered relative to project root for readability. Parse
failures use the same two-line format as `mission_harness.py`
(filename on one line, exception type + message on the next). Empty
failures fit on a single line.

Header and summary block, again mirroring `mission_harness.py`:

```
open_stbc TGL harness
==================================================
Found 60 TGL files

Parsing...

  [... per-file lines ...]

==================================================
Results: 59 passed, 1 failed of 60 total

Top errors (1 distinct):
  [ 1]  empty TGL (0 strings, 0 sounds)
```

The error key used by the Counter is:
- For parse failures: `f"{type(exc).__name__}: {msg[:80]}"` — same
  shape as `mission_harness._error_key`, no need for the SyntaxError
  normalization mission_harness does (TGL parser doesn't raise
  SyntaxError).
- For empty failures: the literal string
  `"empty TGL (0 strings, 0 sounds)"`.

## What it does NOT inherit from mission_harness

- **No `setup_sdk()`** — no `_SDKFinder`, no `_StubModule`, no AST
  rewriters. The parser is pure Python on bytes; nothing needs to be
  importable.
- **No SIGALRM timeout** — TGL parsing is bounded by file size and
  cannot hang. The longest file in the game is a few hundred KB.
- **No per-run sys.modules cleanup** — nothing is being imported per
  file.

## Testing

Add `tests/missions/test_tgl_harness.py` covering:

1. **Discovery returns sorted relative paths** from a temp directory
   containing a couple of fake `.tgl` files and a non-`.tgl` distractor.
   Verifies case-insensitive matching (`Foo.TGL` and `Bar.tgl` both
   picked up) and that non-TGL files are excluded.
2. **Classification — pass.** Pass a real valid TGL
   (`sdk/Build/Data/TGL/Tutorial/Tutorial.tgl`); expect `("pass", ...)`
   with string/sound counts.
3. **Classification — empty.** Write a synthetic TGL with `count=0`
   into `tmp_path` (20-byte header, no TOC, no body); expect
   `("fail", ("empty", None))`. No shipped TGL decodes to empty, so
   this path must be exercised with a constructed file.
4. **Classification — parse error.** Write a 4-byte file in `tmp_path`;
   expect `("fail", ("parse", TGLParseError))`.
5. **Error-key generation** for both failure modes — verifies the
   strings the Counter aggregates on match the spec.

Tests should `pytest.skip` if the SDK TGL fixtures aren't present, the
same way `tests/missions/test_tgl_reader.py` already does for the
shared fixtures.

## File structure

```
tools/tgl_harness.py
  PROJECT_ROOT, ROOTS                  module constants
  discover_tgl_files() -> list[Path]   discovery
  classify(path) -> tuple              per-file run + classification
  error_key(status, reason) -> str     summary grouping key
  format_line(path, status, reason)    one per-file line
  main()                                orchestration + summary

tests/missions/test_tgl_harness.py     unit tests per above
```

Keep all top-level constants and functions module-scoped so the tests
can import them directly without invoking `main()`.

## Success criteria

- `uv run python tools/tgl_harness.py` runs to completion on a checkout
  with both `game/` and `sdk/` present.
- Zero FAIL lines are expected today (all 60 shipped TGLs parse with
  at least one string and one sound).
- The unit tests pass under `uv run pytest tests/missions/test_tgl_harness.py`.
- The harness has no dependency on the SDK module-loading machinery in
  `tools/mission_harness.py`.
