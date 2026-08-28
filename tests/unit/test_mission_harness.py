def test_discover_missions_finds_m1basic():
    from tools.mission_harness import discover_missions
    missions = discover_missions()
    assert "Custom.Tutorial.Episode.M1Basic.M1Basic" in missions


def test_discover_missions_count():
    from tools.mission_harness import discover_missions
    missions = discover_missions()
    # SDK has 35 files with def Initialize(pMission) — sanity-check the range
    assert 30 <= len(missions) <= 40


def test_discover_missions_no_init_files():
    from tools.mission_harness import discover_missions
    missions = discover_missions()
    assert not any("__init__" in m for m in missions)


def test_discover_missions_no_episode_scripts():
    from tools.mission_harness import discover_missions
    # Episode-level scripts use Initialize(pEpisode), not Initialize(pMission)
    missions = discover_missions()
    assert not any(m.endswith("Episode1") or m.endswith("Episode5") for m in missions)


# ── _FixPy2DictView (Python-2 dict-view compat) ───────────────────────────────
# BC's Python 1.5 returned a list from dict.keys()/values()/items(); Python 3
# returns a view. E1M2.CreateMovingAsteroids does `k = d.keys(); k.sort()`,
# which crashes under Py3 ('dict_keys' has no .sort()). _FixPy2DictView wraps
# every no-arg .keys()/.values()/.items() call in list() to restore Py2
# semantics. Drive the transform directly (parse → apply → compile → exec) so
# the test is hermetic and doesn't depend on any SDK file.

def _run_through_dict_view_fix(src: str) -> dict:
    import ast
    from tools.mission_harness import _FixPy2Sort, _FixPy2DictView
    tree = ast.parse(src)
    tree = _FixPy2Sort().visit(tree)
    tree = _FixPy2DictView().visit(tree)
    ast.fix_missing_locations(tree)
    ns: dict = {}
    exec(compile(tree, "<test>", "exec"), ns)
    return ns


def test_dict_view_fix_assign_then_sort():
    # The exact E1M2.CreateMovingAsteroids pattern: assign d.keys() to a name,
    # then call .sort() on it. Un-wrapped this raises AttributeError under Py3.
    ns = _run_through_dict_view_fix(
        "d = {'b': 2, 'a': 1, 'c': 3}\n"
        "lKeys = d.keys()\n"
        "lKeys.sort()\n"
    )
    assert ns["lKeys"] == ["a", "b", "c"]


def test_dict_view_fix_values_and_items_materialize():
    # .values() indexing and .items() indexing both need a real list under Py3.
    ns = _run_through_dict_view_fix(
        "d = {'a': 1, 'b': 2}\n"
        "vFirst = sorted(d.values())[0]\n"
        "iFirst = sorted(d.items())[0]\n"
    )
    assert ns["vFirst"] == 1
    assert ns["iFirst"] == ("a", 1)


def test_dict_view_fix_preserves_mid_loop_del_fidelity():
    # The original for-loop-only transform existed so SDK code could `del`
    # entries mid-iteration (Py3 view raises RuntimeError). The generalized
    # call-site wrap must still snapshot the loop iterable.
    ns = _run_through_dict_view_fix(
        "d = {1: 1, 2: 2, 3: 3}\n"
        "for k in d.keys():\n"
        "    if k == 2:\n"
        "        del d[k]\n"
        "remaining = sorted(d.keys())\n"
    )
    assert ns["remaining"] == [1, 3]


def test_dict_view_fix_leaves_argful_calls_untouched():
    # Only no-arg .keys()/.values()/.items() are dict views. A same-named method
    # taking an argument is not a dict view — must not be wrapped in list().
    ns = _run_through_dict_view_fix(
        "class Store:\n"
        "    def values(self, n):\n"
        "        return n * 2\n"
        "out = Store().values(21)\n"
    )
    assert ns["out"] == 42


# ── _FixPy2Compare (Python-2 cross-type ordering) ─────────────────────────────
# Python 2 let you order ANY two objects: unrelated types compared by type name,
# with numbers always sorting before non-numbers. Python 3 raises TypeError.
#
# AI/Compound/DockWithStarbase.py:94 leans on that by accident:
#
#     if vDiff.SqrLength < 0.5:          # note: no parens -- a METHOD vs a float
#         vDiff.SetXYZ(1, 0, 0)
#
# Under Python 2 the float is the smaller operand, so the branch is never taken
# and BC keeps the unitized away-direction it just computed. Under Python 3 the
# line raises. It went unnoticed because it sits inside SetupDockPositions'
# proximity walk, which never executed while ProximityManager.GetNextObject was
# a hardcoded `return None` -- so restoring that walk turned a dead line into a
# live crash on the docking path.
#
# We reproduce PYTHON 2's answer, not the author's evident intent. Calling the
# method would make the branch fire on a degenerate vector, which BC never did;
# BC instead divides by zero two lines later. Faithful beats tidy -- and that
# divide-by-zero needs an object exactly coincident with the docking entry.
#
# Narrow by design: only `<bare attribute> <op> <numeric constant>`, the shape
# of the bug. 35 SDK sites match it and 34 compare genuine numbers, where the
# helper is a pass-through -- the fallback costs nothing unless the comparison
# would otherwise have raised. It does NOT cover every possible cross-type
# comparison in the SDK; the other 6,764 comparisons are left alone rather than
# paying a wrapper on hot AI and combat paths.

def _run_through_compare_fix(src: str) -> dict:
    import ast
    from tools.mission_harness import _FixPy2Compare
    tree = _FixPy2Compare().visit(ast.parse(src))
    ast.fix_missing_locations(tree)
    ns: dict = {}
    exec(compile(tree, "<test>", "exec"), ns)
    return ns


def test_method_compared_to_number_does_not_raise():
    ns = _run_through_compare_fix(
        "class V:\n"
        "    def SqrLength(self):\n"
        "        return 1.0\n"
        "v = V()\n"
        "result = v.SqrLength < 0.5\n"
    )
    assert ns["result"] is False


def test_number_is_the_smaller_operand_either_way_round():
    """Python 2's rule, and the reason DockWithStarbase's branch never fired."""
    ns = _run_through_compare_fix(
        "class V:\n"
        "    def SqrLength(self):\n"
        "        return 1.0\n"
        "v = V()\n"
        "a = v.SqrLength < 0.5\n"
        "b = v.SqrLength > 0.5\n"
        "c = 0.5 < v.SqrLength\n"
        "d = 0.5 > v.SqrLength\n"
    )
    assert (ns["a"], ns["b"]) == (False, True)
    assert (ns["c"], ns["d"]) == (True, False)


def test_ordinary_numeric_attributes_are_untouched():
    """34 of the 35 matching SDK sites are comparing real numbers
    (`self.iNumInside < 1`, `self.fMemoryTime > 0.0`, module counters). The
    helper must be a pure pass-through for them, including the boundary."""
    ns = _run_through_compare_fix(
        "class C:\n"
        "    def __init__(self):\n"
        "        self.n = 1\n"
        "        self.f = 0.0\n"
        "c = C()\n"
        "lt = c.n < 1\n"
        "le = c.n <= 1\n"
        "gt = c.f > 0.0\n"
        "ge = c.f >= 0.0\n"
        "eq = c.n == 1\n"
        "ne = c.n != 1\n"
    )
    assert (ns["lt"], ns["le"], ns["gt"], ns["ge"]) == (False, True, False, True)
    assert (ns["eq"], ns["ne"]) == (True, False)


def test_equality_against_a_method_is_false_not_an_error():
    """== / != never raised in Python 2 either; they compare by identity."""
    ns = _run_through_compare_fix(
        "class V:\n"
        "    def SqrLength(self):\n"
        "        return 1.0\n"
        "v = V()\n"
        "eq = v.SqrLength == 0.5\n"
        "ne = v.SqrLength != 0.5\n"
    )
    assert (ns["eq"], ns["ne"]) == (False, True)


def test_the_real_sdk_line_survives_the_transform():
    """The exact DockWithStarbase.py:94 shape, unitized vector and all."""
    ns = _run_through_compare_fix(
        "class V:\n"
        "    def __init__(self):\n"
        "        self.taken = False\n"
        "    def SqrLength(self):\n"
        "        return 1.0\n"
        "    def SetXYZ(self, x, y, z):\n"
        "        self.taken = True\n"
        "vDiff = V()\n"
        "if vDiff.SqrLength < 0.5:\n"
        "    vDiff.SetXYZ(1, 0, 0)\n"
    )
    assert ns["vDiff"].taken is False, (
        "BC never takes this branch -- the float is the smaller operand"
    )
