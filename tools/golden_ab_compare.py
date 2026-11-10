"""Compare two golden-scene row logs and report where they first differ.

Pure: no git, subprocess or engine. tools/golden_ab.py feeds it the rows it
collected at the base commit and at HEAD."""
import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.helpers.golden_rows import (COMPONENTS, describe,  # noqa: E402
                                       differences)

MAX_FIELDS = 20


@dataclass
class SceneDiff:
    scene: str
    status: str  # identical | differs | only in base | only in HEAD | error
    first_tick: "int | None" = None
    fields: list = field(default_factory=list)
    differing_ticks: int = 0
    last_tick: "int | None" = None
    first_kind: "str | None" = None
    error: "str | None" = None
    side: "str | None" = None  # which side crashed: base | HEAD


def _is_hex_float(v):
    if not isinstance(v, str) or "p" not in v:
        return False
    try:
        float.fromhex(v)
    except ValueError:
        return False
    return True


def format_value(v):
    """A float's hex string as 'decimal [hex]'; anything else as is."""
    if _is_hex_float(v):
        return "%r [%s]" % (float.fromhex(v), v)
    return str(v)


def _pair(w, g):
    if _is_hex_float(w) and _is_hex_float(g):
        return "%r → %r [%s → %s]" % (
            float.fromhex(w), float.fromhex(g), w, g)
    return "%s → %s" % (format_value(w), format_value(g))


def _kind(at, want_row, scene):
    comp = COMPONENTS[at[0]] if at and isinstance(at[0], int) else None
    if comp is None:
        return None
    if comp == "state" and len(at) > 1 and isinstance(at[1], int):
        try:
            return "state/%s" % want_row[1][at[1]][0]
        except (IndexError, TypeError):
            pass
    return comp


def compare_scene(scene, base_rows, head_rows):
    d = SceneDiff(scene, "identical")
    for b, h in zip(base_rows, head_rows):
        t = b[0]
        want, got = list(b), list(h)
        diffs = differences(want, got, MAX_FIELDS)
        if not diffs:
            continue
        d.differing_ticks += 1
        d.last_tick = t
        if d.first_tick is None:
            d.first_tick = t
            d.first_kind = _kind(diffs[0][0], want, scene)
            d.fields = ["%s: %s" % (describe(t, at, want, scene), _pair(w, g))
                        for at, w, g in diffs]
    if len(base_rows) != len(head_rows):
        note = "ticks: %d \u2192 %d" % (len(base_rows), len(head_rows))
        d.fields = d.fields[:MAX_FIELDS - 1] + [note]
    if d.differing_ticks or len(base_rows) != len(head_rows):
        d.status = "differs"
    return d


TAIL_LINES = 15


def format_report(diffs, harness_changed, inherited_env=None):
    lines = []
    if inherited_env:
        lines.append("inherited env: " + " ".join(inherited_env))
    if harness_changed:
        lines.append("WARNING: harness differs between base and HEAD: "
                     + ", ".join(harness_changed))
    for d in diffs:
        if d.status == "error":
            lines.append("%s: error%s" % (
                d.scene, " (%s)" % d.side if d.side else ""))
            for t in (d.error or "").splitlines()[-TAIL_LINES:]:
                lines.append("    " + t)
            continue
        lines.append("%s: %s" % (d.scene, d.status))
        if d.status != "differs":
            continue
        if d.first_tick is not None:
            lines.append("    first difference at tick %d (%s)"
                         % (d.first_tick, d.first_kind))
        for f in d.fields:
            lines.append("    " + f)
        if d.differing_ticks:
            lines.append("    %d ticks differ, last at %d"
                         % (d.differing_ticks, d.last_tick))
    return "\n".join(lines) + "\n"


def exit_code(diffs):
    if any(d.status == "error" for d in diffs):
        return 2
    if any(d.status != "identical" for d in diffs):
        return 1
    return 0
