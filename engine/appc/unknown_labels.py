"""The placeholder an unidentified contact shows: "Unknown N".

Roadmap decision 4: N is held per contact until it is identified or leaves the
set, so the SDK's label-keyed button de-duplication (Science CreateScanButton's
GetButtonW) never merges two unknowns. BC's own "Unknown ..." wording is not
recovered (ShowUnknownName's body is unreconstructed) — Mark's call.

Weak-keyed: a contact that goes away releases its number with it.
"""
import weakref

_numbers: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def placeholder(obj) -> str:
    n = _numbers.get(obj)
    if n is None:
        used = set(_numbers.values())
        n = 1
        while n in used:
            n += 1
        _numbers[obj] = n
    return "Unknown %d" % n


def current(obj):
    n = _numbers.get(obj)
    return None if n is None else "Unknown %d" % n


def release(obj) -> None:
    _numbers.pop(obj, None)


def reset() -> None:
    _numbers.clear()
