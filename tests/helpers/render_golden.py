"""Recorded render goldens: the beam and torpedo render feeds' test reference
(phase 6 follow-up 4, Task 1; plan
docs/superpowers/plans/2026-11-06-phase6-delete-python-render-builders.md).

A golden is one scene's frames, each the four render vectors as they read
back from the host (`phaser_beams_debug`, `tractor_beams_debug`,
`torpedoes_debug`, `dynamic_lights_debug`), packed by the feed tests
(tests/host/test_native_beam_feed.py, test_native_torpedo_feed.py) to one
`bytes` per item. A frame record keeps the four counts and one SHA-256 over
all four lists, so a changed, moved, added or dropped item changes it.

The goldens were recorded ONCE, from the Python builders, and the builders
were then deleted (phase 6 follow-up 4, Task 3): the native feeds are now
the only builders, and the goldens are what they are checked against.

Recording is therefore REFUSED: under `UPDATE_RENDER_GOLDEN=1`, `record`
fails (require_python_builders), because the builders it recorded from are
gone and a golden is never recorded from the native feeds. Re-recording
after a deliberate visual change needs Mark's ruling AND a new source of
truth to record from; until then, a change that moves a golden is a
regression. `_write` is the writer such a source would use (the unit tests
build their goldens with it); it refuses a frame whose `source` is not
"python" (`frame(..., source=)`), so it can never write native frames.

`RENDER_GOLDEN_DIR` (read at use) reads elsewhere. Goldens are per
platform, as the combat goldens are (ruling R9: float math is not promised
bit-equal across libms): `tests/fixtures/render_goldens/<scene>.<sys.
platform>.json`. On a REQUIRED_PLATFORMS platform a missing golden fails,
naming the file; elsewhere it skips.
"""
import hashlib
import json
import os
import struct
import sys
from pathlib import Path

import pytest

UPDATE_ENV = "UPDATE_RENDER_GOLDEN"
DIR_ENV = "RENDER_GOLDEN_DIR"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "render_goldens"
SCHEMA = 1
FEEDS = ("phasers", "tractors", "torps", "lights")
# The platforms whose goldens were recorded: a missing file there fails.
REQUIRED_PLATFORMS = ("darwin",)


def frame(phasers=(), tractors=(), torps=(), lights=(), *, source):
    """One frame: each feed's items, one packed `bytes` each, and what built
    them ("python": the Python builders; "native": the native feeds)."""
    return {"phasers": list(phasers), "tractors": list(tractors),
            "torps": list(torps), "lights": list(lights), "source": source}


def require_python_builders(scene_name="") -> None:
    """Always fails: a golden was recorded only from engine/host_loop.py's
    Python beam and torpedo builders, which were deleted (phase 6 follow-up
    4, Task 3), and is never recorded from the native feeds."""
    pytest.fail("render golden %s: the Python builders are gone; a golden is "
                "recorded only from them, never from the native feeds. "
                "Re-recording needs Mark's ruling and a new source"
                % scene_name)


def recording() -> bool:
    return os.environ.get(UPDATE_ENV) == "1"


def _path(scene_name) -> Path:
    root = os.environ.get(DIR_ENV)
    base = Path(root) if root else FIXTURES
    return base / ("%s.%s.json" % (scene_name, sys.platform))


def _record_of(i, f) -> dict:
    h = hashlib.sha256()
    for feed in FEEDS:
        items = f.get(feed, ())
        h.update(feed.encode("ascii") + struct.pack("<i", len(items)))
        for item in items:
            h.update(struct.pack("<i", len(item)) + bytes(item))
    rec = {"frame": i}
    rec.update((feed, len(f.get(feed, ()))) for feed in FEEDS)
    rec["sha"] = h.hexdigest()
    return rec


def record(scene_name, frames) -> None:
    """Inert unless UPDATE_RENDER_GOLDEN=1; then it refuses
    (require_python_builders), writing nothing."""
    if not recording():
        return
    require_python_builders(scene_name)


def _write(scene_name, frames, source) -> Path:
    """Write `scene_name`'s golden from `frames` (counts and digests per
    frame) and return its path. A frame not from "python" is refused: a
    golden is never written from the native feeds."""
    sources = sorted({f.get("source") for f in frames} - {"python"},
                     key=repr)
    if sources:
        pytest.fail("render golden %s: frames from %r; a golden is never "
                    "written from the native feeds" % (scene_name, sources))
    path = _path(scene_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    recs = [_record_of(i, f) for i, f in enumerate(frames)]
    data = {"scene": scene_name, "platform": sys.platform, "schema": SCHEMA,
            "source": source, "frames": recs}
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    return path


def _compare(scene_name, frames):
    """(golden records, `frames`' records, differing frame indices)."""
    path = _path(scene_name)
    if not path.is_file():
        msg = ("no render golden for %s on %s: %s is missing (recording "
               "needs Mark's ruling and a new source: the Python builders "
               "are gone)" % (scene_name, sys.platform, path))
        if sys.platform in REQUIRED_PLATFORMS:
            raise AssertionError(msg)
        pytest.skip(msg)
    want = json.loads(path.read_text())["frames"]
    got = [_record_of(i, f) for i, f in enumerate(frames)]
    assert len(got) == len(want), (
        "render golden %s: %d frames, the golden holds %d frames"
        % (scene_name, len(got), len(want)))
    bad = [i for i, (g, w) in enumerate(zip(got, want)) if g != w]
    return want, got, bad


def differing_frames(scene_name, frames) -> list:
    """The indices of the frames of `frames` that differ from the golden."""
    return _compare(scene_name, frames)[2]


def check(scene_name, frames) -> None:
    """Assert `frames` equal `scene_name`'s golden for this platform, frame
    by frame, naming the first that differs (and every one that does)."""
    want, got, bad = _compare(scene_name, frames)
    if bad:
        i = bad[0]
        raise AssertionError(
            "render golden %s: frame %d differs (differing frames: %r)\n"
            "  golden %r\n  got    %r" % (scene_name, i, bad, want[i], got[i]))
