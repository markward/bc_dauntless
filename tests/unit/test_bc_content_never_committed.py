"""The BC content roots must never enter a commit.

`game/` and `sdk/` hold copyrighted Bridge Commander material. Since
2026-09-05 they no longer have to live inside the project at all
(engine/paths.py), so a developer may leave a SYMLINK at either name
pointing at an install elsewhere on their machine. That gives the old
copyright hazard a second edge: committing the symlink would publish an
absolute home path.

The regression these guards exist for, found 2026-09-06: .gitignore
spelled the patterns `game/` and `sdk/`, and a trailing slash matches
DIRECTORIES ONLY. Measured against a scratch repo, for each pattern:

                     absent      symlink     real dir
    pattern `game/`  NOT ign.    NOT ign.    ignored
    pattern `game`   ignored     ignored     ignored

So the trailing-slash form stopped ignoring the roots the moment they
became symlinks, and both showed up untracked and stageable. It also
never ignored them in a fresh checkout, where the directory does not
exist yet -- which is why the slashless form is the one to keep, and why
`git check-ignore` is a stable assertion in CI rather than one that
depends on what happens to be on disk.

These guards ask git, not the filesystem. `git check-ignore` is pure
pattern evaluation, so the first test means the same thing on a machine
with a real install, one with a symlink, and a bare CI checkout.
"""

import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

BC_ROOTS = ("game", "sdk")


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ("git", *args),
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("root", BC_ROOTS)
def test_bc_root_is_ignored_whatever_it_is_on_disk(root: str) -> None:
    """A directory, a symlink, or absent -- all three must be ignored.

    Fails if the .gitignore pattern regains a trailing slash.
    """
    result = _git("check-ignore", "-q", root)
    assert result.returncode == 0, (
        f"{root!r} is not git-ignored. A trailing slash in .gitignore "
        f"matches directories only, so a symlink or a fresh checkout is "
        f"left stageable -- committing it would publish copyrighted BC "
        f"content or an absolute home path. Spell the pattern {root!r}, "
        f"not {root + '/'!r}."
    )


@pytest.mark.parametrize("root", BC_ROOTS)
def test_bc_root_is_not_tracked(root: str) -> None:
    """Ignoring is advisory; `git add -f` defeats it. This catches the result."""
    tracked = _git("ls-files", "--", root).stdout.split()
    assert not tracked, (
        f"{root!r} has tracked entries: {tracked[:5]}. BC content and "
        f"machine-specific symlinks must never be committed."
    )


def test_no_tracked_symlink_escapes_the_repo() -> None:
    """The general form of the bug: any committed symlink leaving the tree.

    A symlink's blob content IS its target. An absolute target embeds the
    author's filesystem layout; a relative one that climbs past the repo
    root points at whatever happens to sit there on someone else's machine.
    """
    listing = _git("ls-files", "-s").stdout.splitlines()
    offenders = []
    for line in listing:
        mode, sha, _rest = line.split(maxsplit=2)
        if mode != "120000":  # not a symlink
            continue
        path = _rest.split("\t", 1)[1]
        target = _git("cat-file", "blob", sha).stdout.strip()
        if Path(target).is_absolute():
            offenders.append(f"{path} -> {target} (absolute)")
            continue
        # Resolve the target against the link's own directory, purely
        # lexically -- the real path need not exist on this machine.
        landed = Path(path).parent / target
        parts: list[str] = []
        for part in landed.parts:
            if part == "..":
                if not parts:
                    offenders.append(f"{path} -> {target} (escapes repo)")
                    break
                parts.pop()
            elif part != ".":
                parts.append(part)

    assert not offenders, (
        "Tracked symlinks point outside the repository:\n  "
        + "\n  ".join(offenders)
    )
