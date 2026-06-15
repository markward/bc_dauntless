"""Run a command (normally pytest) under an RSS watchdog and kill it if it
crosses a memory ceiling.

Motivation: the bc_dauntless full test suite historically OOM'd the host
(>100 GB RAM, freezing macOS). The leak that caused it has been fixed and the
suite now plateaus around ~290 MB (see docs/test-suite-memory.md), but macOS
does not reliably enforce `ulimit -v` / RLIMIT_AS, so this watchdog is the
durable safety net for running the full suite or any large batch: it polls the
child process tree's RSS via `ps` and SIGKILLs the whole process group the
instant it exceeds the ceiling. A kill is a DATA POINT ("this batch breached
the cap"), reported via exit code 99 — not a crash.

Usage:
    python tools/pytest_rss_watchdog.py <ceiling_mb> -- <command...>

Example:
    python tools/pytest_rss_watchdog.py 4000 -- uv run pytest -q
"""
import os
import signal
import subprocess
import sys
import time

POLL_SECONDS = 0.5


def child_tree_rss_kb(root_pid: int) -> int:
    """Sum RSS (KB) of root_pid and all its descendants via a single ps call."""
    try:
        out = subprocess.check_output(["ps", "-axo", "pid=,ppid=,rss="], text=True)
    except Exception:
        return 0
    children: dict[int, list[int]] = {}
    rss: dict[int, int] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            pid, ppid, r = int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError:
            continue
        children.setdefault(ppid, []).append(pid)
        rss[pid] = r
    total = 0
    stack = [root_pid]
    seen: set[int] = set()
    while stack:
        pid = stack.pop()
        if pid in seen:
            continue
        seen.add(pid)
        total += rss.get(pid, 0)
        stack.extend(children.get(pid, []))
    return total


def main() -> None:
    if len(sys.argv) < 4 or sys.argv[2] != "--":
        sys.exit("usage: pytest_rss_watchdog.py <ceiling_mb> -- <command...>")
    ceiling_mb = int(sys.argv[1])
    cmd = sys.argv[3:]
    print("WATCHDOG ceiling=%d MB  cmd=%s" % (ceiling_mb, " ".join(cmd)), flush=True)

    # New process group so we can SIGKILL the whole subtree at once.
    proc = subprocess.Popen(cmd, preexec_fn=os.setsid)
    peak_kb = 0
    killed = False
    try:
        while proc.poll() is None:
            kb = child_tree_rss_kb(proc.pid)
            peak_kb = max(peak_kb, kb)
            if kb > ceiling_mb * 1024:
                print("WATCHDOG: RSS %.1f MB > ceiling %d MB -- KILLING"
                      % (kb / 1024, ceiling_mb), flush=True)
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    proc.kill()
                killed = True
                break
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            pass
        raise
    rc = proc.wait()
    print("WATCHDOG DONE peak_rss=%.1f MB  killed=%s  rc=%s"
          % (peak_kb / 1024, killed, rc), flush=True)
    sys.exit(99 if killed else (rc or 0))


if __name__ == "__main__":
    main()
