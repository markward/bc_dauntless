"""Project-root shim shadowing Python 1.5's C `strop` module (removed in
Python 3). SDK scripts import it for string ops that predate string methods;
the only call site is MissionLib.ConditionChangedRedirect:
``strop.split(sModuleAndFunction, "*")`` (the CallFunctionWhenConditionChanges
redirect that drives, e.g., the helm "entering/leaving orbit" lines).

See CLAUDE.md → "Project-root SDK shims" for how root modules shadow
SDK/stdlib names (App.py, LoadBridge.py are the precedents).
"""


def split(s, sep=None, maxsplit=-1):
    return s.split(sep, maxsplit)


def join(words, sep=" "):
    return sep.join(words)


def strip(s):
    return s.strip()


def lower(s):
    return s.lower()


def upper(s):
    return s.upper()
