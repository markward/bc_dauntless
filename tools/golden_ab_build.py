"""Base worktree, builds and harness check for tools/golden_ab.py."""
import re
import subprocess
import sys
from pathlib import Path

WORKTREE_PREFIX = "golden-ab-base-"
_COPIED = ("CMAKE_BUILD_TYPE", "DAUNTLESS_ENABLE_CEF", "Python3_EXECUTABLE",
           "Python3_ROOT_DIR", "Python3_FIND_FRAMEWORK", "Python3_FIND_STRATEGY")
_FETCH = "FETCHCONTENT_SOURCE_DIR_"


def _entries(cache_text):
    out = {}
    for line in cache_text.splitlines():
        if "=" not in line or line.startswith(("//", "#")):
            continue
        key, _, value = line.partition("=")
        out[key.partition(":")[0]] = value
    return out


def cache_options(cache_text: str, build_dir: Path) -> list:
    """-D args for the base configure, copied from HEAD's CMakeCache.txt."""
    entries = _entries(cache_text)
    opts = ["-D%s=%s" % (k, entries[k]) for k in _COPIED if k in entries]
    opts.append("-DDAUNTLESS_BUILD_TESTS=OFF")
    have = set()
    for k, v in entries.items():
        if k.startswith(_FETCH):
            have.add(k[len(_FETCH):])
            opts.append("-D%s=%s" % (k, v))
    deps = Path(build_dir) / "_deps"
    if deps.is_dir():
        for d in sorted(deps.glob("*-src")):
            if not d.is_dir():
                continue
            name = d.name[:-len("-src")].upper()
            if name not in have:
                opts.append("-D%s%s=%s" % (_FETCH, name, d))
    return opts


def _run(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          check=False)


def _checked(cmd, cwd=None):
    proc = subprocess.run(cmd, cwd=cwd, stdout=sys.stderr)
    if proc.returncode != 0:
        raise RuntimeError("command failed (%d): %s" % (proc.returncode, " ".join(cmd)))


def head_root() -> Path:
    out = _run(["git", "rev-parse", "--show-toplevel"]).stdout.strip()
    if not out:
        raise RuntimeError("not inside a git work tree")
    return Path(out)


def main_root() -> Path:
    out = _run(["git", "rev-parse", "--path-format=absolute",
                "--git-common-dir"]).stdout.strip()
    return Path(out).parent


def base_tree_path(main_root: Path, sha: str) -> Path:
    return Path(main_root) / ".claude" / "worktrees" / (WORKTREE_PREFIX + sha[:12])


def _built(tree: Path) -> bool:
    return any((tree / "build" / "python").glob("_dauntless_host*"))


def ensure_base(sha: str, head_build: Path) -> Path:
    from tools import golden_ab_side as side
    tree = base_tree_path(main_root(), sha)
    if tree.exists():
        top = _run(["git", "-C", str(tree), "rev-parse",
                    "--show-toplevel"]).stdout.strip()
        head = _run(["git", "-C", str(tree), "rev-parse",
                     "HEAD"]).stdout.strip()
        if not top or Path(top).resolve() != tree.resolve() or head != sha:
            raise RuntimeError(
                "%s exists but is not a worktree of %s at that commit; "
                "delete it by hand and rerun" % (tree, sha[:12]))
        if _built(tree):
            _revalidate(tree, head_build)
            return tree
    else:
        _checked(["git", "worktree", "add", "--detach", str(tree), sha])
    side.install_child(tree)
    problem = side.check_base_usable(tree)
    if problem:
        raise RuntimeError(
            "%s\nthe base tree is left at %s; `tools/golden_ab.py --prune` "
            "removes it" % (problem, tree))
    cache = (Path(head_build) / "CMakeCache.txt").read_text()
    _checked(["cmake", "-B", "build", "-S", "."]
             + cache_options(cache, Path(head_build)), cwd=str(tree))
    _checked(["cmake", "--build", "build", "--target", "_dauntless_host", "-j"],
             cwd=str(tree))
    return tree


def _build_type(cache_path: Path):
    try:
        return _entries(Path(cache_path).read_text()).get("CMAKE_BUILD_TYPE")
    except OSError:
        return None


def _revalidate(tree: Path, head_build: Path) -> None:
    """A reused, built base must still match HEAD's build type and be unedited."""
    want = _build_type(Path(head_build) / "CMakeCache.txt")
    have = _build_type(tree / "build" / "CMakeCache.txt")
    if have != want:
        raise RuntimeError(
            "%s was built as %s but HEAD is %s; run `tools/golden_ab.py "
            "--prune` and rerun" % (tree, have, want))
    status = _run(["git", "-C", str(tree), "status", "--porcelain",
                   "--untracked-files=no"]).stdout.strip()
    if status:
        raise RuntimeError(
            "%s has edits to tracked files; run `tools/golden_ab.py --prune` "
            "and rerun" % tree)


def build_head(tree) -> None:
    build = Path(tree) / "build"
    if not (build / "CMakeCache.txt").is_file():
        raise RuntimeError("no CMakeCache.txt in %s: configure HEAD first" % build)
    home = _entries((build / "CMakeCache.txt").read_text()).get(
        "CMAKE_HOME_DIRECTORY")
    if home and Path(home).resolve() != Path(tree).resolve():
        raise RuntimeError("%s was configured for %s, not %s (symlinked build?)"
                           % (build, home, tree))
    _checked(["cmake", "--build", str(build), "--target", "_dauntless_host", "-j"])


def _git_lines(cmd) -> list:
    proc = _run(cmd)
    if proc.returncode != 0:
        raise RuntimeError("%s failed (%d): %s" % (
            " ".join(cmd), proc.returncode, (proc.stderr or "").strip()))
    return [line for line in proc.stdout.splitlines() if line]


def harness_changed(base_sha: str) -> list:
    child = "tests/helpers/golden_ab_child.py"
    changed = _git_lines(["git", "diff", "--name-only", base_sha, "--",
                          "tests/helpers", "tests/conftest.py",
                          ":(exclude)" + child])
    untracked = _git_lines(["git", "ls-files", "--others",
                            "--exclude-standard", "--", "tests/helpers"])
    return changed + [f for f in untracked if f != child and f not in changed]


_BASE_NAME = re.compile(r"^%s[0-9a-f]{12}$" % re.escape(WORKTREE_PREFIX))


def prune_bases(main_root: Path) -> list:
    out = _run(["git", "worktree", "list", "--porcelain"]).stdout
    parent = Path(main_root) / ".claude" / "worktrees"
    gone = []
    for record in out.split("\n\n"):
        lines = record.splitlines()
        first = next((l for l in lines if l.startswith("worktree ")), None)
        if first is None:
            continue
        path = Path(first[len("worktree "):])
        if path.parent != parent or not _BASE_NAME.match(path.name):
            continue
        if "detached" not in lines or any(
                l == "locked" or l.startswith("locked ") for l in lines):
            continue
        proc = subprocess.run(["git", "worktree", "remove", "--force", str(path)])
        if proc.returncode == 0:
            gone.append(path)
    return gone
