"""Cross-platform wall-clock timeout for the mission harnesses.

The harnesses previously used signal.alarm()/SIGALRM to bound a mission run.
SIGALRM does not exist on Windows (signal.SIGALRM raises AttributeError), so
every harness-backed test failed there before reaching any game logic.

This guard instead runs a watchdog timer thread that injects the timeout
exception into the guarded thread via PyThreadState_SetAsyncExc. The observable
behaviour matches the old SIGALRM handler: a TimeoutError subclass is raised
inside the guarded block, so existing `except Exception` handlers classify it
as a run failure exactly as before.

One difference from SIGALRM is worth knowing: an async exception is delivered
at an interpreter bytecode boundary, so it cannot interrupt a thread parked
inside a single long-running C call, whereas a signal could. The harness bodies
are pure-Python tick loops and module imports, so in practice the guard fires
at the same granularity.
"""
import contextlib
import ctypes
import threading


def _inject(thread_id, exc_type):
    """Raise exc_type in the given thread (never cancel with NULL: _drain)."""
    ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_ulong(thread_id), ctypes.py_object(exc_type))


@contextlib.contextmanager
def raise_after(seconds, message):
    """Raise TimeoutError(message) in this thread if the block outlives `seconds`."""
    target = threading.get_ident()
    fired = False   # the timer armed an exception
    done = False    # control has left the guarded block
    # Guards both flags AND the injections paired with them. Arming and disarming are
    # two-step (set the flag, then call into the interpreter), and the steps
    # must not interleave across threads: flag-set, block disarms, arming lands
    # leaves a HarnessTimeout pending on a thread that has already left the
    # guarded region, where it detonates in whatever ran next. Holding the lock
    # across both steps makes each sequence atomic with respect to the other,
    # so the exit either sees no fire and has nothing to clear, or sees a
    # completed fire and clears it.
    lock = threading.Lock()

    # SetAsyncExc instantiates the class with no arguments, so bake the message
    # into a per-call subclass rather than losing it.
    timeout_exc = type(
        "HarnessTimeout",
        (TimeoutError,),
        {"__init__": lambda self: TimeoutError.__init__(self, message)},
    )

    def _fire():
        nonlocal fired
        with lock:
            if done:
                return  # the block already exited; arming now would leak
            fired = True
            _inject(target, timeout_exc)

    timer = threading.Timer(seconds, _fire)
    timer.daemon = True
    timer.start()
    try:
        yield
    finally:
        timer.cancel()
        # The timer can fire in the window between the block finishing and the
        # cancel landing. Close that window under the lock: mark the region
        # left (so a still-stalled _fire returns without arming) and clear any
        # injection that already landed, so neither can surface later
        # attributed to unrelated code.
        with lock:
            done = True
            if fired:
                _drain(timeout_exc)


def _drain(exc_type):
    """Take delivery of a pending injection of exc_type here, and drop it.

    Not PyThreadState_SetAsyncExc(tid, NULL): that clears the pending
    exception but re-signals the interpreter's async-exception flag, and only
    a DELIVERED async exception clears that flag. Left set, it breaks the
    interpreter for everything after (CPython 3.11: a profiler enabled later
    spins forever on its next frame). If the exception already landed (raised
    out of the block, or caught inside it) nothing is pending and the loop
    just runs out; a pending one lands at the loop's first backward jump."""
    try:
        for _ in range(10000):
            pass
    except exc_type:
        pass
