"""Shared developer dial keys: / L O drive whichever dial GROUP is active.

minor-rocks spec §5 (M4). dev_nebula_dials.py found / L O to be the only keys
free on a MacBook in every namespace (test_dev_key_collisions.py), and the
nebula dials held all three. Groups now share them: `/` cycles the dials of
the ACTIVE group, L / O step the selected dial down / up, and Developer
Options -> Lighting -> "Dial keys" cycles which group is active. The first
registered group (nebula, at boot) is active by default.

Each group supplies its dial order, a getter for its live values (for the
print) and a step function `step(dial_name, direction)` that does the
group's own clamping and pushes to native. Every press prints
`[<group> dials] selected=<dial> {...}`.
"""
from typing import Callable

import engine.dev_mode as dev_mode

_groups: dict = {}        # name -> {"order", "get", "step", "sel"}
_names: list = []
_active: int = 0


def reset() -> None:
    global _active
    _groups.clear()
    _names.clear()
    _active = 0


def register_group(name: str, order: tuple, get_dials: Callable[[], dict],
                   step: Callable[[str, int], None]) -> None:
    if not order:
        raise ValueError("dial group %r has no dials" % (name,))
    if name not in _groups:
        _names.append(name)
    _groups[name] = {"order": tuple(order), "get": get_dials, "step": step,
                     "sel": 0}


def groups() -> tuple:
    return tuple(_names)


def active() -> str:
    return _names[_active] if _names else ""


def cycle_active() -> str:
    global _active
    if _names:
        _active = (_active + 1) % len(_names)
        _report()
    return active()


def _group():
    return _groups.get(active())


def selected() -> str:
    grp = _group()
    return grp["order"][grp["sel"]] if grp else ""


def cycle_dial() -> None:
    grp = _group()
    if grp is None:
        return
    grp["sel"] = (grp["sel"] + 1) % len(grp["order"])
    _report()


def push(direction: int) -> None:
    grp = _group()
    if grp is None:
        return
    grp["step"](selected(), direction)
    _report()


def _report() -> None:
    grp = _group()
    if grp is not None:
        print("[%s dials] selected=%s %s" % (active(), selected(), grp["get"]()))


def register_keys(_h) -> None:
    """Claim / L O once at boot (gated on dev_mode by the caller)."""
    dev_mode.register_dev_keybinding(
        _h.keys.KEY_SLASH, cycle_dial,
        "Dev dials: select next dial in the active group (dev) - /")
    dev_mode.register_dev_keybinding(
        _h.keys.KEY_L, lambda: push(-1),
        "Dev dials: selected dial down (dev) - L")
    dev_mode.register_dev_keybinding(
        _h.keys.KEY_O, lambda: push(+1),
        "Dev dials: selected dial up (dev) - O")
