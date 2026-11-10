"""Golden A/B: run each golden scene at a base commit and at HEAD, report
where they first differ."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import golden_ab_build as build  # noqa: E402
from tools import golden_ab_side as side  # noqa: E402
from tools.golden_ab_compare import (SceneDiff, compare_scene,  # noqa: E402
                                     exit_code, format_report)

DESCRIPTION = """\
Run each golden scene at a base commit and at HEAD on this machine and report
where they first differ (tick, component, field).

Run it from the branch's own worktree. On demand only: never in a gate or CI.
It rebuilds HEAD's _dauntless_host first, and builds the base in its own
worktree under .claude/worktrees/golden-ab-base-<sha12>.

Commit-message convention: a commit that changes gameplay describes its change
in the commit message (the first divergent tick and what differs), optionally
pasted from this report.
"""


def resolve_sha(rev):
    proc = subprocess.run(["git", "rev-parse", rev], capture_output=True,
                          text=True)
    if proc.returncode != 0:
        raise RuntimeError("cannot resolve %r: %s" % (rev, proc.stderr.strip()))
    return proc.stdout.strip()


def _default_base():
    proc = subprocess.run(["git", "merge-base", "HEAD", "main"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("no merge-base with main: " + proc.stderr.strip())
    return proc.stdout.strip()


def _run_scene(scene, base_tree, head_tree, in_base, in_head):
    if scene not in in_head:
        return SceneDiff(scene, "only in base")
    if scene not in in_base:
        return SceneDiff(scene, "only in HEAD")
    try:
        base_rows = side.run_scene_rows(base_tree, scene)
        head_rows = side.run_scene_rows(head_tree, scene)
    except side.ChildError as e:
        return SceneDiff(scene, "error", error=e.tail)
    return compare_scene(scene, base_rows, head_rows)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="tools/golden_ab.py", description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", help="base revision (default: merge-base HEAD main)")
    ap.add_argument("--scene", action="append", default=[],
                    help="scene name; repeatable (default: all)")
    ap.add_argument("--prune", action="store_true",
                    help="remove the golden-ab-base-* worktrees and exit")
    args = ap.parse_args(argv)
    try:
        if args.prune:
            for p in build.prune_bases(build.main_root()):
                print("removed %s" % p)
            return 0
        sha = resolve_sha(args.base) if args.base else _default_base()
        head_tree = Path.cwd()
        build.build_head(head_tree)
        base_tree = build.ensure_base(sha, head_tree / "build")
        side.install_child(base_tree)
        problem = side.check_base_usable(base_tree)
        if problem:
            print("error: " + problem, file=sys.stderr)
            return 2
        in_base = side.list_scenes(base_tree)
        in_head = side.list_scenes(head_tree)
    except (RuntimeError, side.ChildError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    scenes = sorted(set(in_base) | set(in_head))
    if args.scene:
        unknown = [s for s in args.scene if s not in scenes]
        if unknown:
            print("error: unknown scene(s): %s" % ", ".join(unknown),
                  file=sys.stderr)
            return 2
        scenes = args.scene
    diffs = [_run_scene(s, base_tree, head_tree, in_base, in_head)
             for s in scenes]
    sys.stdout.write(format_report(diffs, build.harness_changed(sha)))
    return exit_code(diffs)


if __name__ == "__main__":
    sys.exit(main())
