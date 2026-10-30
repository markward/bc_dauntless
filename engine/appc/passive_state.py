"""Passive subsystem state: a weapon bank or tube whose per-tick update would
do nothing is put to sleep and skipped until a field it depends on is written.
See docs/superpowers/specs/2026-10-30-passive-subsystem-state-design.md.
"""
import os
from typing import Callable, Mapping

_enabled = True
_audit = False
_failures: list = []
_counts = {"slept": 0, "woke": 0}


def configure(environ: Mapping[str, str] = os.environ) -> None:
    global _enabled, _audit
    _enabled = environ.get("DAUNTLESS_PASSIVE_STATE") != "0"
    _audit = environ.get("DAUNTLESS_PASSIVE_AUDIT") == "1"


def enabled() -> bool:
    return _enabled


def audit_enabled() -> bool:
    return _audit


def reset() -> None:
    global _enabled, _audit
    _enabled = True
    _audit = False
    _failures.clear()
    _counts["slept"] = 0
    _counts["woke"] = 0


def is_asleep(obj) -> bool:
    return obj.__dict__.get("_passive_asleep", False)


def put_to_sleep(obj) -> None:
    obj.__dict__["_passive_asleep"] = True
    _counts["slept"] += 1
    hook = getattr(obj, "_passive_on_sleep", None)
    if hook is not None:
        hook()


def wake(obj) -> None:
    if not is_asleep(obj):
        return
    obj.__dict__["_passive_asleep"] = False
    _counts["woke"] += 1
    hook = getattr(obj, "_passive_on_wake", None)
    if hook is not None:
        hook()


class WakeField:
    """Data descriptor with no __get__: reads stay plain instance-dict reads,
    every write (even of an equal value) wakes a sleeping owner."""

    def __set_name__(self, owner, name) -> None:
        self._name = name

    def __set__(self, obj, value) -> None:
        obj.__dict__[self._name] = value
        if obj.__dict__.get("_passive_asleep", False):
            wake(obj)


def _copy(value):
    if isinstance(value, (list, dict, set)):
        return value.copy()
    return value


def _snapshot(d: dict) -> dict:
    return {k: (v, _copy(v)) for k, v in d.items()}


def _restore(d: dict, snap: dict) -> None:
    for k in [k for k in d if k not in snap]:
        del d[k]
    for k, (orig, copy) in snap.items():
        if isinstance(orig, list):
            orig[:] = copy
        elif isinstance(orig, (dict, set)):
            orig.clear()
            orig.update(copy)
        d[k] = orig


def _diff(d: dict, snap: dict) -> list:
    changed = [k for k in d if k not in snap]
    changed += [k for k, (orig, copy) in snap.items()
                if k not in d or d[k] is not orig or d[k] != copy]
    return changed


def audit_step(obj, step: Callable[[], None]) -> None:
    targets = [(type(obj).__name__, vars(obj))]
    for attr in getattr(obj, "_passive_audit_children", ()):
        child = getattr(obj, attr, None)
        if child is not None:
            targets.append((type(child).__name__, vars(child)))
    snaps = [_snapshot(d) for _, d in targets]
    step()
    for (name, d), snap in zip(targets, snaps):
        for field in _diff(d, snap):
            _failures.append((name, field))
        _restore(d, snap)


def audit_failures() -> list:
    return list(_failures)


def counts() -> dict:
    return dict(_counts)
