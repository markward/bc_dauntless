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
    def __init__(self, out="", rc=0):
        self.stdout, self.returncode, self.stderr = out, rc, ""


def test_prune_only_touches_own_paths(monkeypatch):
    listing = ("worktree /m\nHEAD aaa\nbranch refs/heads/main\n\n"
               "worktree /m/.claude/worktrees/golden-ab-base-abc\nHEAD bbb\ndetached\n\n"
               "worktree /m/.claude/worktrees/feature-x\nHEAD ccc\nbranch refs/heads/x\n")
    calls = []

    def fake(cmd, **kw):
        calls.append(cmd)
        return _Proc(listing)
    monkeypatch.setattr(subprocess, "run", fake)
    gone = build.prune_bases(Path("/m"))
    assert gone == [Path("/m/.claude/worktrees/golden-ab-base-abc")]
    removes = [c for c in calls if "remove" in c]
    assert removes == [["git", "worktree", "remove", "--force",
                        "/m/.claude/worktrees/golden-ab-base-abc"]]


def test_harness_changed_lists_names(monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: _Proc("tests/helpers/a.py\n\n"))
    assert build.harness_changed("abc") == ["tests/helpers/a.py"]


def test_cli_same_base_and_head_reports_identical(monkeypatch, capsys):
    rows = [[1, []], [2, []]]
    monkeypatch.setattr(golden_ab, "resolve_sha", lambda rev: "a" * 40)
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
    assert "s1: error: kaboom" in capsys.readouterr().out
