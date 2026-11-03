"""Process-wide membership generation for ProximityManager candidate caches.

Every mutation that could change any manager's candidate list or its order
calls ``bump()``; a cache keyed on ``generation()`` rebuilds when it moves.
Import-light on purpose (no engine imports): sets, planet, projectiles and
native_combat import it at module scope.
"""
_gen = 0


def bump() -> None:
    global _gen
    _gen += 1


def generation() -> int:
    return _gen
