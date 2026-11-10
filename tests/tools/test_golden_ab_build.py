"""tools/golden_ab_build.py and the tools/golden_ab.py CLI, with no git or cmake."""
import subprocess
from pathlib import Path

from tools import golden_ab, golden_ab_build as build
from tools.golden_ab_compare import SceneDiff

CACHE = """\
CMAKE_BUILD_TYPE:STRING=Debug
CMAKE_CXX_FLAGS:STRING=
DAUNTLESS_BUILD_TESTS:BOOL=ON
DAUNTLESS_ENABLE_CEF:BOOL=ON
FETCHCONTENT_SOURCE_DIR_CEF:PATH=/main/build/_deps/cef-src
FETCHCONTENT_SOURCE_DIR_FREETYPE:UNINITIALIZED=/main/build/_deps/freetype-src
Python3_EXECUTABLE:UNINITIALIZED=/v/bin/python3
Python3_FIND_FRAMEWORK:UNINITIALIZED=NEVER
Python3_ROOT_DIR:UNINITIALIZED=/py
_Python3_EXECUTABLE:INTERNAL=/v/bin/python3
"""


def test_cache_options_copies_build_type_python_and_deps(tmp_path):
    (tmp_path / "_deps/cef-src").mkdir(parents=True)
    (tmp_path / "_deps/openal_soft-src").mkdir(parents=True)
    (tmp_path / "_deps/freetype-src").mkdir(parents=True)
    got = build.cache_options(CACHE, tmp_path)
    assert got == [
        "-DCMAKE_BUILD_TYPE=Debug",
        "-DDAUNTLESS_ENABLE_CEF=ON",
        "-DPython3_EXECUTABLE=/v/bin/python3",
        "-DPython3_ROOT_DIR=/py",
        "-DPython3_FIND_FRAMEWORK=NEVER",
        "-DDAUNTLESS_BUILD_TESTS=OFF",
        "-DFETCHCONTENT_SOURCE_DIR_CEF=/main/build/_deps/cef-src",
        "-DFETCHCONTENT_SOURCE_DIR_FREETYPE=/main/build/_deps/freetype-src",
        "-DFETCHCONTENT_SOURCE_DIR_OPENAL_SOFT=%s" % (tmp_path / "_deps/openal_soft-src"),
    ]


def test_cache_options_without_deps_dirs(tmp_path):
    got = build.cache_options("CMAKE_BUILD_TYPE:STRING=Release\n", tmp_path)
    assert got == ["-DCMAKE_BUILD_TYPE=Release", "-DDAUNTLESS_BUILD_TESTS=OFF"]


def test_base_tree_path():
    p = build.base_tree_path(Path("/m"), "0123456789abcdef0123")
    assert p == Path("/m/.claude/worktrees/golden-ab-base-0123456789ab")


class _Proc:
    def __init__(self, out="", rc=0, err=""):
        self.stdout, self.returncode, self.stderr = out, rc, err


def test_prune_only_touches_own_paths(monkeypatch):
    listing = ("worktree /m\nHEAD aaa\nbranch refs/heads/main\n\n"
               "worktree /m/.claude/worktrees/golden-ab-base-0123456789ab\nHEAD bbb\ndetached\n\n"
               "worktree /m/.claude/worktrees/feature-x\nHEAD ccc\nbranch refs/heads/x\n")
    calls = []

    def fake(cmd, **kw):
        calls.append(cmd)
        return _Proc(listing)
    monkeypatch.setattr(subprocess, "run", fake)
    gone = build.prune_bases(Path("/m"))
    assert gone == [Path("/m/.claude/worktrees/golden-ab-base-0123456789ab")]
    removes = [c for c in calls if "remove" in c]
    assert removes == [["git", "worktree", "remove", "--force",
                        "/m/.claude/worktrees/golden-ab-base-0123456789ab"]]


def test_harness_changed_lists_names(monkeypatch):
    def fake(cmd, **kw):
        return _Proc("tests/helpers/a.py\n\n" if "diff" in cmd else "")
    monkeypatch.setattr(subprocess, "run", fake)
    assert build.harness_changed("abc") == ["tests/helpers/a.py"]


def test_harness_changed_includes_untracked_but_not_the_child(monkeypatch):
    seen = []

    def fake(cmd, **kw):
        seen.append(cmd)
        if "diff" in cmd:
            return _Proc("tests/helpers/a.py\n")
        return _Proc("tests/helpers/new.py\ntests/helpers/golden_ab_child.py\n")
    monkeypatch.setattr(subprocess, "run", fake)
    assert build.harness_changed("abc") == ["tests/helpers/a.py",
                                            "tests/helpers/new.py"]
    ls = [c for c in seen if "ls-files" in c][0]
    assert ls == ["git", "ls-files", "--others", "--exclude-standard", "--",
                  "tests/helpers"]


def test_harness_changed_raises_when_git_fails(monkeypatch):
    import pytest
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: _Proc("", rc=128, err="bad object"))
    with pytest.raises(RuntimeError, match="bad object"):
        build.harness_changed("abc")
    calls = []

    def fake(cmd, **kw):
        calls.append(cmd)
        return _Proc("", rc=1 if "ls-files" in cmd else 0, err="nope")
    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(RuntimeError, match="ls-files"):
        build.harness_changed("abc")


def test_checked_sends_build_output_to_stderr(monkeypatch):
    import sys
    seen = {}

    def fake(cmd, **kw):
        seen.update(kw)
        return _Proc()
    monkeypatch.setattr(subprocess, "run", fake)
    build._checked(["cmake", "--version"])
    assert seen["stdout"] is sys.stderr


def test_cli_same_base_and_head_reports_identical(monkeypatch, capsys):
    rows = [[1, []], [2, []]]
    monkeypatch.setattr(golden_ab, "resolve_sha", lambda rev: "a" * 40)
    monkeypatch.setattr(golden_ab, "_default_base", lambda: "a" * 40)
    monkeypatch.setattr(golden_ab.build, "head_root",
                        lambda: golden_ab.side.PROJECT_ROOT)
    monkeypatch.setattr(golden_ab.build, "build_head", lambda tree: None)
    monkeypatch.setattr(golden_ab.build, "ensure_base",
                        lambda sha, head_build: Path("/base"))
    monkeypatch.setattr(golden_ab.build, "harness_changed", lambda sha: [])
    monkeypatch.setattr(golden_ab.side, "install_child", lambda t: None)
    monkeypatch.setattr(golden_ab.side, "check_base_usable", lambda t: None)
    monkeypatch.setattr(golden_ab.side, "list_scenes", lambda t: ["s1", "s2"])
    monkeypatch.setattr(golden_ab.side, "run_scene_rows", lambda t, s: rows)
    assert golden_ab.main([]) == 0
    out = capsys.readouterr().out
    assert "s1: identical" in out and "s2: identical" in out


def test_cli_child_error_becomes_error_row(monkeypatch, capsys):
    monkeypatch.setattr(golden_ab, "resolve_sha", lambda rev: "a" * 40)
    monkeypatch.setattr(golden_ab, "_default_base", lambda: "a" * 40)
    monkeypatch.setattr(golden_ab.build, "head_root",
                        lambda: golden_ab.side.PROJECT_ROOT)
    monkeypatch.setattr(golden_ab.build, "build_head", lambda tree: None)
    monkeypatch.setattr(golden_ab.build, "ensure_base",
                        lambda sha, head_build: Path("/base"))
    monkeypatch.setattr(golden_ab.build, "harness_changed", lambda sha: [])
    monkeypatch.setattr(golden_ab.side, "install_child", lambda t: None)
    monkeypatch.setattr(golden_ab.side, "check_base_usable", lambda t: None)
    monkeypatch.setattr(golden_ab.side, "list_scenes", lambda t: ["s1"])

    def boom(t, s):
        raise golden_ab.side.ChildError("kaboom")
    monkeypatch.setattr(golden_ab.side, "run_scene_rows", boom)
    assert golden_ab.main([]) == 2
    out = capsys.readouterr().out
    assert "s1: error (base)\n    kaboom" in out


def _fake_base(monkeypatch, tmp_path, top, head, built, calls, status=""):
    tree = tmp_path / "wt"
    tree.mkdir()
    monkeypatch.setattr(build, "main_root", lambda: tmp_path)
    monkeypatch.setattr(build, "base_tree_path", lambda m, sha: tree)
    monkeypatch.setattr(build, "_built", lambda t: built)

    def fake_run(cmd, cwd=None):
        calls.append(cmd)
        if "--show-toplevel" in cmd:
            return _Proc(str(top(tree)))
        if "status" in cmd:
            return _Proc(status)
        return _Proc(head)
    monkeypatch.setattr(build, "_run", fake_run)
    monkeypatch.setattr(build, "_checked", lambda cmd, cwd=None: calls.append(cmd))
    return tree


def _caches(tree, head_build, head_type, base_type):
    (tree / "build").mkdir(exist_ok=True)
    (tree / "build/CMakeCache.txt").write_text(
        "CMAKE_BUILD_TYPE:STRING=%s\n" % base_type)
    (head_build / "CMakeCache.txt").write_text(
        "CMAKE_BUILD_TYPE:STRING=%s\n" % head_type)


def test_ensure_base_rejects_reused_tree_with_other_build_type(monkeypatch, tmp_path):
    import pytest
    calls = []
    tree = _fake_base(monkeypatch, tmp_path, lambda t: t, "a" * 40, True, calls)
    _caches(tree, tmp_path, "Debug", "Release")
    with pytest.raises(RuntimeError) as e:
        build.ensure_base("a" * 40, tmp_path)
    assert str(tree) in str(e.value) and "--prune" in str(e.value)
    assert not any(c and c[0] == "cmake" for c in calls)


def test_ensure_base_rejects_reused_tree_with_tracked_edits(monkeypatch, tmp_path):
    import pytest
    calls = []
    tree = _fake_base(monkeypatch, tmp_path, lambda t: t, "a" * 40, True, calls,
                      status=" M engine/x.py\n")
    _caches(tree, tmp_path, "Debug", "Debug")
    with pytest.raises(RuntimeError) as e:
        build.ensure_base("a" * 40, tmp_path)
    assert str(tree) in str(e.value) and "--prune" in str(e.value)
    assert ["git", "-C", str(tree), "status", "--porcelain",
            "--untracked-files=no"] in calls


def test_ensure_base_unusable_fresh_base_names_path_and_prune(monkeypatch, tmp_path):
    import pytest
    from tools import golden_ab_side as side
    calls = []
    tree = _fake_base(monkeypatch, tmp_path, lambda t: t, "a" * 40, False, calls)
    tree.rmdir()
    monkeypatch.setattr(side, "install_child", lambda t: None)
    monkeypatch.setattr(side, "check_base_usable", lambda t: "too old")
    with pytest.raises(RuntimeError) as e:
        build.ensure_base("a" * 40, tmp_path)
    assert "too old" in str(e.value)
    assert str(tree) in str(e.value) and "--prune" in str(e.value)


def test_cli_rejects_head_root_that_is_not_the_tools_tree(monkeypatch, capsys):
    monkeypatch.setattr(golden_ab, "_default_base", lambda: "a" * 40)
    monkeypatch.setattr(golden_ab.build, "head_root", lambda: Path("/other/tree"))
    monkeypatch.setattr(golden_ab.build, "build_head",
                        lambda t: (_ for _ in ()).throw(AssertionError("built")))
    assert golden_ab.main([]) == 2
    err = capsys.readouterr().err
    assert "/other/tree" in err and str(golden_ab.side.PROJECT_ROOT) in err


def test_cli_header_lists_inherited_env(monkeypatch, capsys):
    monkeypatch.setenv("DAUNTLESS_PASSIVE_STATE", "0")
    monkeypatch.setattr(golden_ab, "_default_base", lambda: "a" * 40)
    monkeypatch.setattr(golden_ab.build, "head_root",
                        lambda: golden_ab.side.PROJECT_ROOT)
    monkeypatch.setattr(golden_ab.build, "build_head", lambda tree: None)
    monkeypatch.setattr(golden_ab.build, "ensure_base",
                        lambda sha, head_build: Path("/base"))
    monkeypatch.setattr(golden_ab.build, "harness_changed", lambda sha: [])
    monkeypatch.setattr(golden_ab.side, "install_child", lambda t: None)
    monkeypatch.setattr(golden_ab.side, "check_base_usable", lambda t: None)
    monkeypatch.setattr(golden_ab.side, "list_scenes", lambda t: ["s1"])
    monkeypatch.setattr(golden_ab.side, "run_scene_rows", lambda t, s: [[1, []]])
    assert golden_ab.main([]) == 0
    assert "inherited env: " in capsys.readouterr().out


def test_ensure_base_rejects_wrong_toplevel(monkeypatch, tmp_path):
    import pytest
    calls = []
    _fake_base(monkeypatch, tmp_path, lambda t: tmp_path, "a" * 40, True, calls)
    with pytest.raises(RuntimeError, match="delete it by hand"):
        build.ensure_base("a" * 40, tmp_path)
    assert not any("add" in c for c in calls)


def test_ensure_base_rejects_wrong_head(monkeypatch, tmp_path):
    import pytest
    calls = []
    _fake_base(monkeypatch, tmp_path, lambda t: t, "b" * 40, True, calls)
    with pytest.raises(RuntimeError, match="delete it by hand"):
        build.ensure_base("a" * 40, tmp_path)


def test_ensure_base_reuses_valid_built_tree(monkeypatch, tmp_path):
    calls = []
    tree = _fake_base(monkeypatch, tmp_path, lambda t: t, "a" * 40, True, calls)
    _caches(tree, tmp_path, "Debug", "Debug")
    assert build.ensure_base("a" * 40, tmp_path) == tree
    assert not any("worktree" in c for c in calls)
    assert not any(c and c[0] == "cmake" for c in calls)


def test_prune_ignores_other_roots_and_failed_removes(monkeypatch):
    listing = ("worktree /other/.claude/worktrees/golden-ab-base-0123456789ab\n"
               "detached\n\n"
               "worktree /m/.claude/worktrees/golden-ab-base-0123456789ab\n"
               "detached\n\n")

    class P:
        def __init__(self, out="", rc=0):
            self.stdout, self.returncode = out, rc

    def fake(cmd, **kw):
        if "list" in cmd:
            return P(listing)
        return P(rc=1)
    monkeypatch.setattr(subprocess, "run", fake)
    assert build.prune_bases(Path("/m")) == []


def test_build_head_rejects_foreign_cache(tmp_path):
    import pytest
    (tmp_path / "build").mkdir()
    (tmp_path / "build/CMakeCache.txt").write_text(
        "CMAKE_HOME_DIRECTORY:INTERNAL=/elsewhere\n")
    with pytest.raises(RuntimeError, match="configured for"):
        build.build_head(tmp_path)


def test_cli_missing_cmake_exits_2(monkeypatch, capsys):
    monkeypatch.setattr(golden_ab, "resolve_sha", lambda rev: "a" * 40)
    monkeypatch.setattr(golden_ab, "_default_base", lambda: "a" * 40)
    monkeypatch.setattr(golden_ab.build, "head_root",
                        lambda: golden_ab.side.PROJECT_ROOT)

    def boom(tree):
        raise FileNotFoundError("cmake")
    monkeypatch.setattr(golden_ab.build, "build_head", boom)
    assert golden_ab.main([]) == 2
    err = capsys.readouterr().err
    assert "error:" in err and "cmake" in err


def test_cli_undecodable_child_output_is_error_row(monkeypatch, capsys):
    import zlib
    monkeypatch.setattr(golden_ab, "resolve_sha", lambda rev: "a" * 40)
    monkeypatch.setattr(golden_ab, "_default_base", lambda: "a" * 40)
    monkeypatch.setattr(golden_ab.build, "head_root",
                        lambda: golden_ab.side.PROJECT_ROOT)
    monkeypatch.setattr(golden_ab.build, "build_head", lambda tree: None)
    monkeypatch.setattr(golden_ab.build, "ensure_base",
                        lambda sha, head_build: Path("/base"))
    monkeypatch.setattr(golden_ab.build, "harness_changed", lambda sha: [])
    monkeypatch.setattr(golden_ab.side, "install_child", lambda t: None)
    monkeypatch.setattr(golden_ab.side, "check_base_usable", lambda t: None)
    monkeypatch.setattr(golden_ab.side, "list_scenes", lambda t: ["s1"])

    def bad(t, s):
        raise zlib.error("bad data")
    monkeypatch.setattr(golden_ab.side, "run_scene_rows", bad)
    assert golden_ab.main([]) == 2
    assert "s1: error (base)" in capsys.readouterr().out


def test_prune_skips_loose_names_branches_and_locked(monkeypatch):
    base = "/m/.claude/worktrees/"
    listing = (
        "worktree %sgolden-ab-base-abc\nHEAD a\ndetached\n\n"
        "worktree %sgolden-ab-base-0123456789abc\nHEAD a\ndetached\n\n"
        "worktree %sgolden-ab-base-0123456789ab\nHEAD a\nbranch refs/heads/x\n\n"
        "worktree %sgolden-ab-base-aaaaaaaaaaaa\nHEAD a\ndetached\nlocked\n\n"
        "worktree %sgolden-ab-base-bbbbbbbbbbbb\nHEAD a\ndetached\nlocked why\n\n"
        "worktree %sgolden-ab-base-cccccccccccc\nHEAD a\ndetached\n"
    ) % ((base,) * 6)
    removed = []

    def fake(cmd, **kw):
        if "list" in cmd:
            return _Proc(listing)
        removed.append(cmd[-1])
        return _Proc()
    monkeypatch.setattr(subprocess, "run", fake)
    assert build.prune_bases(Path("/m")) == [Path(base + "golden-ab-base-cccccccccccc")]
    assert removed == [base + "golden-ab-base-cccccccccccc"]
