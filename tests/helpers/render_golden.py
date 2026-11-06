"""Recorded render goldens: the beam and torpedo render feeds' test reference
(phase 6 follow-up 4, Task 1; plan
docs/superpowers/plans/2026-11-06-phase6-delete-python-render-builders.md).

A golden is one scene's frames, each the four render vectors as they read
back from the host (`phaser_beams_debug`, `tractor_beams_debug`,
`torpedoes_debug`, `dynamic_lights_debug`), packed by the feed tests
(tests/host/test_native_beam_feed.py, test_native_torpedo_feed.py) to one
`bytes` per item. A frame record keeps the four counts and one SHA-256 over
all four lists, so a changed, moved, added or dropped item changes it.

The goldens were recorded ONCE, from the Python builders, before they were
deleted. Never re-record one without Mark's say.

    UPDATE_RENDER_GOLDEN=1 uv run pytest <the test>

writes `tests/fixtures/render_goldens/<scene>.<sys.platform>.json` and
skips. `RENDER_GOLDEN_DIR` (read at use) writes and reads elsewhere: a
second recording into a temp dir is how a golden is shown deterministic.
Goldens are per platform, as the combat goldens are (ruling R9: float math
is not promised bit-equal across libms). On a REQUIRED_PLATFORMS platform a
missing golden fails, naming the file; elsewhere it skips.

Recording takes only the Python builders' frames: each frame says its
source (`frame(..., source=)`), and `record` refuses a frame that is not
"python", or a host_loop without the builders.
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
# What the goldens were recorded from (engine/host_loop.py).
PYTHON_BUILDERS = ("_build_phaser_beam_render_data",
                   "_build_tractor_beam_render_data",
                   "_build_torpedo_render_data",
                   "_build_dynamic_light_render_data")


def frame(phasers=(), tractors=(), torps=(), lights=(), *, source):
    """One frame: each feed's items, one packed `bytes` each, and what built
    them ("python": the Python builders; "native": the native feeds)."""
    return {"phasers": list(phasers), "tractors": list(tractors),
            "torps": list(torps), "lights": list(lights), "source": source}


def python_builders_available() -> bool:
    from engine import host_loop
    return all(callable(getattr(host_loop, n, None)) for n in PYTHON_BUILDERS)


def require_python_builders(scene_name="") -> None:
    """Fail unless host_loop still has the Python builders: a golden is
    recorded only from them, never from the native feeds."""
    if not python_builders_available():
        pytest.fail("render golden %s: the Python builders are gone; a "
                    "golden is recorded only from them" % scene_name)


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


def record(scene_name, frames, source="python builders") -> None:
    """Write `scene_name`'s golden from `frames`, only under
    UPDATE_RENDER_GOLDEN=1 (then skip); inert otherwise."""
    if not recording():
        return
    require_python_builders(scene_name)
    sources = sorted({f.get("source") for f in frames} - {"python"},
                     key=repr)
    if sources:
        pytest.fail("render golden %s: frames from %r; a golden is recorded "
                    "only from the Python builders" % (scene_name, sources))
    path = _path(scene_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    recs = [_record_of(i, f) for i, f in enumerate(frames)]
    data = {"scene": scene_name, "platform": sys.platform, "schema": SCHEMA,
            "source": source, "frames": recs}
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    pytest.skip("render golden recorded: %s (%d frames) -> %s"
                % (scene_name, len(recs), path))


def _compare(scene_name, frames):
    """(golden records, `frames`' records, differing frame indices)."""
    path = _path(scene_name)
    if not path.is_file():
        msg = ("no render golden for %s on %s: %s is missing (record one "
               "with %s=1, only with Mark's say)"
               % (scene_name, sys.platform, path, UPDATE_ENV))
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
