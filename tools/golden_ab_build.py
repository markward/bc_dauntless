"""Base worktree, builds and harness check for tools/golden_ab.py."""
import subprocess
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
    proc = subprocess.run(cmd, cwd=cwd)
    if proc.returncode != 0:
        raise RuntimeError("command failed (%d): %s" % (proc.returncode, " ".join(cmd)))


def main_root() -> Path:
    out = _run(["git", "rev-parse", "--path-format=absolute",
                "--git-common-dir"]).stdout.strip()
    return Path(out).parent


def base_tree_path(main_root: Path, sha: str) -> Path:
    return Path(main_root) / ".claude" / "worktrees" / (WORKTREE_PREFIX + sha[:12])


def _built(tree: Path) -> bool:
    return any((tree / "build" / "python").glob("_dauntless_host*"))


def ensure_base(sha: str, head_build: Path) -> Path:
    tree = base_tree_path(main_root(), sha)
    if tree.is_dir():
        head = _run(["git", "rev-parse", "HEAD"], cwd=str(tree)).stdout.strip()
        if head == sha and _built(tree):
            return tree
    if not tree.is_dir():
        _checked(["git", "worktree", "add", "--detach", str(tree), sha])
    cache = (Path(head_build) / "CMakeCache.txt").read_text()
    _checked(["cmake", "-B", "build", "-S", "."]
             + cache_options(cache, Path(head_build)), cwd=str(tree))
    _checked(["cmake", "--build", "build", "--target", "_dauntless_host", "-j"],
             cwd=str(tree))
    return tree


def build_head(tree) -> None:
    build = Path(tree) / "build"
    if not (build / "CMakeCache.txt").is_file():
        raise RuntimeError("no CMakeCache.txt in %s: configure HEAD first" % build)
    _checked(["cmake", "--build", str(build), "--target", "_dauntless_host", "-j"])


def harness_changed(base_sha: str) -> list:
    out = _run(["git", "diff", "--name-only", base_sha, "--",
                "tests/helpers", "tests/conftest.py"]).stdout
    return [line for line in out.splitlines() if line]


def prune_bases(main_root: Path) -> list:
    out = _run(["git", "worktree", "list", "--porcelain"]).stdout
    gone = []
    for line in out.splitlines():
        if not line.startswith("worktree "):
            continue
        path = Path(line[len("worktree "):])
        if path.name.startswith(WORKTREE_PREFIX):
            subprocess.run(["git", "worktree", "remove", "--force", str(path)])
            gone.append(path)
    return gone
