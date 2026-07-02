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
