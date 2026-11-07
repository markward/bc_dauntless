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

Re-recording (Mark's ruling, 2026-11-07: native re-record on ruling):

* `UPDATE_RENDER_GOLDEN=1` (record from the Python builders) is REFUSED:
  the builders are gone (require_python_builders).
* `UPDATE_RENDER_GOLDEN=native` records from the native feeds (every frame
  must say `source="native"`) and then skips. It is for ONE case only: a
  deliberate visual change Mark has ruled on, with the ruling written down
  in the plan or the SDD ledger first. It also needs
  `RENDER_GOLDEN_RULING=<where that ruling is recorded>`, which is written
  into the golden's header; without it, record refuses. Only Mark, or a
  session acting on that recorded ruling, runs it. It is NEVER run to make a
  red golden test green: without a ruling, a frame that moves is a
  regression in the feed, and the fix goes there.

      UPDATE_RENDER_GOLDEN=native RENDER_GOLDEN_RULING="<plan/ledger ref>" \
          uv run pytest <the golden test>

  Then review the diff of `tests/fixtures/render_goldens/` and commit it
  with the ruling named in the message. The scene premises the golden tests
  assert (coverage counts, shields up and down hit) still run while
  recording, so a re-record cannot quietly drop a case.
* Any other value (unset, "", "0", "true", ...) records nothing.

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
RULING_ENV = "RENDER_GOLDEN_RULING"
# The UPDATE_RENDER_GOLDEN values that record, and the frame source each
# records from.
MODES = {"1": "python", "native": "native"}
_HEADER_SOURCE = {"python": "python builders", "native": "native feeds"}
# The platforms whose goldens were recorded: a missing file there fails.
REQUIRED_PLATFORMS = ("darwin",)


def frame(phasers=(), tractors=(), torps=(), lights=(), *, source):
    """One frame: each feed's items, one packed `bytes` each, and what built
    them ("python": the Python builders; "native": the native feeds)."""
    return {"phasers": list(phasers), "tractors": list(tractors),
            "torps": list(torps), "lights": list(lights), "source": source}


def require_python_builders(scene_name="") -> None:
    """Always fails: the goldens were first recorded from engine/host_loop.py's
    Python beam and torpedo builders, which were deleted (phase 6 follow-up
    4, Task 3), so UPDATE_RENDER_GOLDEN=1 cannot record."""
    pytest.fail("render golden %s: the Python builders are gone, so "
                "UPDATE_RENDER_GOLDEN=1 cannot record. A re-record from the "
                "native feeds (UPDATE_RENDER_GOLDEN=native) needs Mark's "
                "recorded ruling" % scene_name)


def mode():
    """The source UPDATE_RENDER_GOLDEN records from ("python" | "native"),
    or None: not recording."""
    return MODES.get(os.environ.get(UPDATE_ENV))


def recording() -> bool:
    return mode() is not None


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
    """Inert unless UPDATE_RENDER_GOLDEN records (see the module docstring):
    "1" refuses (require_python_builders); "native" needs
    RENDER_GOLDEN_RULING, writes the golden from the native `frames` and
    skips."""
    m = mode()
    if m is None:
        return
    if m == "python":
        require_python_builders(scene_name)
    ruling = os.environ.get(RULING_ENV, "").strip()
    if not ruling:
        pytest.fail("render golden %s: UPDATE_RENDER_GOLDEN=native needs %s "
                    "naming where Mark's ruling for this re-record is "
                    "recorded (plan or ledger); never re-record to make a "
                    "red test green" % (scene_name, RULING_ENV))
    path = _write(scene_name, frames, m, ruling=ruling)
    pytest.skip("render golden recorded from the %s: %s (%d frames) -> %s"
                % (_HEADER_SOURCE[m], scene_name, len(frames), path))


def _write(scene_name, frames, source, ruling=None) -> Path:
    """Write `scene_name`'s golden from `frames` (counts and digests per
    frame), every one of which must say `source` ("python" | "native"), and
    return its path. `ruling` (where Mark's ruling is recorded) goes into
    the header."""
    sources = sorted({f.get("source") for f in frames} - {source}, key=repr)
    if sources:
        pytest.fail("render golden %s: frames from %r; this golden is "
                    "written only from %r frames" % (scene_name, sources,
                                                      source))
    path = _path(scene_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    recs = [_record_of(i, f) for i, f in enumerate(frames)]
    data = {"scene": scene_name, "platform": sys.platform, "schema": SCHEMA,
            "source": _HEADER_SOURCE[source], "frames": recs}
    if ruling is not None:
        data["ruling"] = ruling
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    return path


def _compare(scene_name, frames):
    """(golden records, `frames`' records, differing frame indices)."""
    path = _path(scene_name)
    if not path.is_file():
        msg = ("no render golden for %s on %s: %s is missing (recording "
               "one needs Mark's recorded ruling: UPDATE_RENDER_GOLDEN="
               "native, see tests/helpers/render_golden.py)"
               % (scene_name, sys.platform, path))
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
