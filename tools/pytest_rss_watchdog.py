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


IS_WINDOWS = os.name == "nt"
_warned_no_sampler = False


def _process_table():
    """(pid, ppid, rss_kb) for every process, or [] if unobtainable."""
    if IS_WINDOWS:
        # No ps(1). CIM gives the parent links a per-process query cannot.
        try:
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Process | "
                 "Select-Object ProcessId,ParentProcessId,WorkingSetSize | "
                 "ConvertTo-Csv -NoTypeInformation"],
                text=True, stderr=subprocess.DEVNULL)
        except Exception:
            return []
        rows = []
        for line in out.splitlines()[1:]:          # skip the CSV header
            parts = [f.strip('"') for f in line.split(",")]
            if len(parts) < 3:
                continue
            try:
                rows.append((int(parts[0]), int(parts[1]), int(parts[2]) // 1024))
            except ValueError:
                continue
        return rows
    try:
        out = subprocess.check_output(["ps", "-axo", "pid=,ppid=,rss="], text=True)
    except Exception:
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            rows.append((int(parts[0]), int(parts[1]), int(parts[2])))
        except ValueError:
            continue
    return rows


def child_tree_rss_kb(root_pid: int) -> int:
    """Sum RSS (KB) of root_pid and all its descendants."""
    global _warned_no_sampler
    table = _process_table()
    if not table:
        if not _warned_no_sampler:
            _warned_no_sampler = True
            print("WATCHDOG: cannot sample RSS on this platform - "
                  "the ceiling is NOT being enforced", flush=True)
        return 0
    children: dict[int, list[int]] = {}
    rss: dict[int, int] = {}
    for pid, ppid, r in table:
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


def _kill_tree(proc) -> None:
    """Kill the child and everything it spawned, on either platform."""
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True)
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        proc.kill()


def main() -> None:
    if len(sys.argv) < 4 or sys.argv[2] != "--":
        sys.exit("usage: pytest_rss_watchdog.py <ceiling_mb> -- <command...>")
    ceiling_mb = int(sys.argv[1])
    cmd = sys.argv[3:]
    print("WATCHDOG ceiling=%d MB  cmd=%s" % (ceiling_mb, " ".join(cmd)), flush=True)

    # New process group so we can kill the whole subtree at once. os.setsid
    # does not exist on Windows -- calling it unguarded made this script die on
    # import there, which the caller could not distinguish from a clean run.
    if IS_WINDOWS:
        proc = subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
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
                _kill_tree(proc)
                killed = True
                break
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        _kill_tree(proc)
        raise
    rc = proc.wait()
    print("WATCHDOG DONE peak_rss=%.1f MB  killed=%s  rc=%s"
          % (peak_kb / 1024, killed, rc), flush=True)
    sys.exit(99 if killed else (rc or 0))


if __name__ == "__main__":
    main()
