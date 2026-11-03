# engine/appc/presentation_rng.py
"""The presentation random-number generator, P.

Every cosmetic draw -- a hit sound's pick, a smoke puff, a particle seed, a
death blast's size, a bridge animation -- comes from here, so that whether
one happens never shifts a gameplay roll. Gameplay keeps the two streams it
has always drawn: the SDK's ``App.g_kSystemWrapper.GetRandomNumber`` (S1) and
Python's process-global ``random`` (S2).

Engine code that presents draws P directly (``rand``, ``random``, ...). An
SDK script the engine runs ONLY to present (``LoadTacticalSounds
.GetRandomSound``, ``Effects.CreateSmokeHigh``, a bridge animation builder, a
mission death script) is called inside ``scope()``: while one is open on
this thread, ``GetRandomNumber`` and ``ObjectClass.GetRandomPointOnModel``
answer from P. ``combat.apply_hit`` checks no scope is open (raising under tests, logging
once per call site under ``--developer``), so a presentation script that
reaches gameplay is caught rather than silently drawing gameplay numbers
from P.

The scope is thread-local: presentation is moving to its own queue and the
Python work to its own thread, and a global flag would leak across them.

P has a fixed seed and is reseeded at every mission load
(host_loop._reset_session_scratch: the initial load, a swap, an in-transit
mission change), by the test reset and by Damage Preview's seed, so a
capture of a mission looks the same whatever ran before it.

Spec: docs/superpowers/specs/2026-11-02-presentation-rng-design.md; map:
docs/reference/engine/native-combat/rng-map.md.
"""
import contextlib
import random as _random
import sys
import threading

PRESENTATION_SEED = 0x9E5E17   # any constant: P never needs to be unpredictable

_rng = _random.Random(PRESENTATION_SEED)
_local = threading.local()


def reset(seed=PRESENTATION_SEED) -> None:
    """Reseed P (mission load, tests, Damage Preview's seed)."""
    _rng.seed(seed)


def rand(n) -> int:
    """``GetRandomNumber`` semantics on P: an int in [0, n), 0 for n <= 0."""
    if n <= 0:
        return 0
    return _rng.randrange(int(n))


def random() -> float:
    return _rng.random()


def uniform(a, b) -> float:
    return _rng.uniform(a, b)


def gauss(mu, sigma) -> float:
    return _rng.gauss(mu, sigma)


def randrange(*args) -> int:
    return _rng.randrange(*args)


def in_scope() -> bool:
    """True while a ``scope()`` is open on this thread."""
    return getattr(_local, "depth", 0) > 0


@contextlib.contextmanager
def scope():
    """Run presentation-only code with the SDK's draws answered from P.
    Nests; an exception inside still closes it."""
    _local.depth = getattr(_local, "depth", 0) + 1
    try:
        yield
    finally:
        _local.depth -= 1


_reported = set()   # call sites --developer has already reported


def check_gameplay(where: str, modules=None) -> None:
    """Gameplay is never drawn from P: report a presentation scope open on
    this thread at a gameplay entry point (``combat.apply_hit``). Under
    tests (pytest imported) it raises. Under ``--developer`` it logs once
    per call site to stderr and carries on, so a dev session plays the same
    game as production (raising would skip the rest of the presenting
    script, and the damage). Production pays one thread-local read."""
    if not in_scope():
        return
    if modules is None:
        modules = sys.modules
    message = ("%s ran inside a presentation scope: presentation code "
               "reached gameplay, whose draws would come from the "
               "presentation generator" % where)
    if "pytest" in modules:
        raise AssertionError(message)
    from engine import dev_mode
    if dev_mode.is_enabled() and where not in _reported:
        _reported.add(where)
        sys.stderr.write("[presentation-rng] %s\n" % message)
