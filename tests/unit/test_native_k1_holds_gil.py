"""The kernels release the GIL around exactly their compute call (kernels
off the lock, Task 3; spec docs/superpowers/specs/
2026-11-03-kernels-off-the-lock-design.md goal 3, lock map §5).

Revised deliberately from phase 1b's guard (controller ruling J), which
banned any release in the K1 bindings: a mirror row could then be freed by a
finalizer on another thread mid-read. Task 2 made frees wait for a drain and
queued off-main pushes, so the compute may now run without the lock -- but
ONLY the compute. Everything around it in a binding is CPython (the
applier, the queue appends, the record tuple; K1's walk check and launch
check went with fire control's Python copy, fire control native only, M3)
and must keep the GIL.

A released GIL around the wrong code cannot be caught by a behavioural test
(the race needs a second thread to run at the wrong microsecond), so this
guards the source:

- each of K0-K3's next() bindings, and K3's apply_hits, makes ONE
  released_compute call whose lambda is nothing but the kernel call;
- the helper releases the GIL before it opens the compute timer (the span
  never counts the re-acquire) and runs only the compute under it;
- no combat_* binding releases the GIL any other way, and K4 and can_detect
  keep it (single short calls: spec §2 goal 3).

The behavioural half (the release really happens; a throw re-acquires) is
tests/unit/test_native_gil_release.py.
"""
import re
from pathlib import Path

import pytest

BINDINGS = (Path(__file__).resolve().parents[2] / "native" / "src" / "host"
            / "host_bindings.cc")

# binding -> (its ComputeSite, the one compute call the release wraps)
RELEASED = {
    "combat_k0_next": ("K0", "k.next()"),
    "combat_k1_next": ("K1", "cb::k1_kernel().next()"),
    "combat_k2_next": ("K2", "cb::k2_kernel().next()"),
    "combat_k3_next": ("K3", "cb::k3_kernel().next()"),
    "combat_k3_apply_hits": (
        "K3Hits", "cb::k3_kernel().apply_hits(start, p, py_hits, out)"),
    "combat_motion_compute": (
        "Motion", "cb::motion_step(cb::mirror(), dauntless::transform_store(), "
                  "rows, player, dt, begin, resume)"),
    "combat_motion_step": (
        "Motion", "cb::motion_step(cb::mirror(), dauntless::transform_store(), "
                  "rows, player, dt, begin, resume)"),
}

# Any of these inside a binding would release (or let pybind release) the
# GIL outside released_compute.
_RELEASE_TOKENS = ("gil_scoped_release", "Py_BEGIN_ALLOW_THREADS",
                   "PyEval_SaveThread", "call_guard")


def _strip(text):
    """`text` with comments and string literals blanked (same length), so a
    bracket or a token inside one is not code."""
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif text.startswith("/*", i):
            j = text.index("*/", i) + 2
            out.append(re.sub(r"[^\n]", " ", text[i:j]))
            i = j
        elif c == '"' or (c == "'" and not text[i - 1].isalnum()):
            j = i + 1
            while text[j] != c:
                j += 2 if text[j] == "\\" else 1
            out.append(c + " " * (j - i - 1) + c)
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _call_span(code, start):
    """[start, end) of the bracketed call whose "(" is the first after
    `start`, brackets balanced."""
    i = code.index("(", start)
    depth = 0
    for j in range(i, len(code)):
        if code[j] in "([{":
            depth += 1
        elif code[j] in ")]}":
            depth -= 1
            if depth == 0:
                return start, j + 1
    raise AssertionError("unbalanced call at %d" % start)


@pytest.fixture(scope="module")
def source():
    text = BINDINGS.read_text()
    return text, _strip(text)


def _bindings(source):
    """{name: (code, raw)} for every m.def("combat_...") binding: its whole
    m.def(...) call, stripped and raw."""
    text, code = source
    out = {}
    for m in re.finditer(r'm\.def\("(combat_\w+)"', text):
        s, e = _call_span(code, m.start())
        out[m.group(1)] = (code[s:e], text[s:e])
    return out


def _norm(s):
    return re.sub(r"\s+", " ", s).strip()


@pytest.mark.parametrize("name", sorted(RELEASED))
def test_the_release_wraps_exactly_the_compute_call(source, name):
    site_name, call = RELEASED[name]
    code, raw = _bindings(source)[name]
    sites = [m.start() for m in re.finditer(r"\breleased_compute\(", code)]
    assert len(sites) == 1, (name, len(sites))
    s, e = _call_span(code, sites[0])
    site = _norm(raw[s:e])
    pattern = (r"released_compute\( ?ComputeSite::%s, ?\[[^\]]*\] ?(\(\) ?)?"
               r"\{ ?return %s; ?\} ?\)$" % (site_name,
                                               re.escape(_norm(call))))
    assert re.match(pattern, site), (name, site)


def test_k1_applies_after_the_release(source):
    """K1's CPython around its compute -- the applier and the queue appends
    after it -- stays outside the released lambda, and nothing runs before
    it: the walk check's scan and the launch recheck went with fire
    control's Python copy (fire control native only, M3)."""
    code, _raw = _bindings(source)["combat_k1_next"]
    at = code.index("released_compute(")
    for gone in ("k1_scan(", "k1_launch_recheck("):
        assert gone not in code, gone
    for after in ("applier.apply(", "k1_append_entries("):
        assert code.index(after) > at, after


def test_k2_and_k3_cpython_stays_outside_the_release(source):
    b = _bindings(source)
    code = b["combat_k2_next"][0]
    at = code.index("released_compute(")
    assert code.index("k2_not_delivering(") < at
    for after in ("applier.apply(", "k1_append_entries(",
                  "damage_append_held("):
        assert code.index(after) > at, after
    code = b["combat_k3_apply_hits"][0]
    at = code.index("released_compute(")
    assert code.index("k2_pulse_ctx(") < at
    for after in ("applier.apply(", "damage_append_held("):
        assert code.index(after) > at, after


def test_motion_step_applies_after_the_release(source):
    """Kernel M driven (native motion phase 2, Task 5): the C applier
    (apply_motion_writes, CPython) runs after the released compute, and the
    ships/handles length check before it."""
    code, _raw = _bindings(source)["combat_motion_step"]
    at = code.index("released_compute(")
    assert code.index("PySequence_Size(") < at
    assert code.index("apply_motion_writes(") > at


def test_no_other_combat_binding_releases_the_gil(source):
    """Only the compute sites (RELEASED) release, and only through the helper.
    K4 and can_detect keep the GIL."""
    bindings = _bindings(source)
    for name in ("combat_k0_begin", "combat_k1_begin_pump", "combat_k2_begin",
                 "combat_k3_begin", "combat_k3_answer", "combat_k4_eligible",
                 "combat_can_detect"):
        assert name in bindings, name
    for name, (code, _raw) in bindings.items():
        for token in _RELEASE_TOKENS:
            assert token not in code, (name, token)
        if name not in RELEASED:
            assert "released_compute" not in code, name


def test_the_helper_releases_before_the_span_and_runs_only_compute(source):
    """released_compute: the release is declared first, so the compute
    timer's span closes before the GIL is re-acquired (the wait for it is
    never compute); between them only the compute (and the test-only probe's
    branch) runs."""
    text, code = source
    m = re.search(r"\bauto released_compute\(", code)
    assert m, "released_compute not defined"
    body_start = code.index("{", m.end())
    depth, j = 0, body_start
    while True:
        if code[j] == "{":
            depth += 1
        elif code[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    body = code[body_start:j + 1]
    release = body.index("py::gil_scoped_release")
    span = body.index("ComputeSpan")
    assert release < span
    assert "compute()" in body
    # The release appears once in the helper and nowhere else in the
    # combat bindings' file except the first-run folder picker.
    sites = [k.start() for k in re.finditer(r"gil_scoped_release", code)]
    assert len(sites) == 2, len(sites)
    other = [s for s in sites if not body_start <= s <= j]
    assert len(other) == 1
    m = re.search(r'm\.def\("pick_folder"', text)
    s, e = _call_span(code, m.start())
    assert s < other[0] < e, "the other release is not pick_folder's"
