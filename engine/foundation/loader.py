"""Walk and execute a mod's Custom/Autoload and Custom/Ships scripts.

Neither directory is imported by BC: Foundation loads them. Ordering is
Autoload first, then Ships, because plugins register resources (sounds,
and later systems and TGL tables) that ship definitions may reference.

⚠️ That ordering is INFERRED, not established -- we do not have
Foundation's own. It is the safe direction, and it is the first assumption
to revisit if a mod misbehaves.

Within a directory, filename order: real plugins carry numeric prefixes
(FTech ships 000-Fixes20030305-FoundationTriggers.py), so authors rely on it.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LoadReport:
    autoload: list = field(default_factory=list)
    ships: list = field(default_factory=list)
    failures: list = field(default_factory=list)   # (script, "Type: msg")


_SUBDIRS = (("Autoload", "autoload"), ("Ships", "ships"))


def _scripts_in(index, subdir):
    """Mod-provided Custom/<subdir>/ plugin scripts, folded-key sorted.

    A `.py`, or a Python 1.5 `.pyc` with no `.py` beside it (a `.py` beats
    its own `.pyc`, Python 1.5's rule and the SDK loader's).

    Reads the mod index rather than the filesystem so only enabled mods
    contribute and the overlay's own resolution rules apply.
    """
    prefix = ("custom/%s/" % subdir).lower()
    found = {}
    for key, mf in index.files.items():
        if mf.target != "sdk":          # paths-guard: kind label
            continue
        if not key.startswith(prefix) or "/" in key[len(prefix):]:
            continue
        stem, dot, ext = key.rpartition(".")
        if not dot or ext not in ("py", "pyc"):
            continue
        if ext == "py" or stem not in found:
            found[stem] = (key, mf)
    return [found[stem] for stem in sorted(found)]


def _sdk_loader_class():
    """The `_SDKLoader` of the SDK import hook in use: tools/mission_harness
    in the game, tests/conftest under pytest. None when neither is installed."""
    import sys
    for finder in sys.meta_path:
        if type(finder).__name__ == "_SDKFinder":
            owner = sys.modules.get(type(finder).__module__)
            return getattr(owner, "_SDKLoader", None)
    return None


def _run_plugin(mf, key):
    """Execute one plugin script as the SDK loader executes any SDK script:
    Python 1.5 source fixes and the loader's transforms, or the lifter for a
    bytecode-only `.pyc`. Foundation imported these scripts inside BC's
    Python 1.5, so plain Python 3 parsing refuses or misreads many of them.

    The module is executed, not imported: like before, a plugin runs once
    per load and is not left in sys.modules under a name."""
    import importlib.util
    loader_cls = _sdk_loader_class()
    if loader_cls is None:
        raise RuntimeError("no SDK import hook installed; cannot run %s" % key)
    name = "__foundation__." + key.rsplit("/", 1)[-1].rpartition(".")[0]
    loader = loader_cls(str(mf.abs_path), logical_rel=key)
    spec = importlib.util.spec_from_loader(name, loader, origin=str(mf.abs_path))
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)


def load_plugins() -> LoadReport:
    """Execute every enabled mod's Foundation plugin scripts."""
    from engine import mods
    from engine.foundation.shipdef import plugin_origin

    report = LoadReport()
    index = mods.current()

    for subdir, bucket in _SUBDIRS:
        for key, mf in _scripts_in(index, subdir):
            try:
                with plugin_origin(mf.mod_name, key):
                    _run_plugin(mf, key)
            except Exception as exc:
                # One broken mod must not stop the others registering --
                # the same rule build_index follows for an unreadable mod,
                # and for the same reason: silence is a support nightmare.
                report.failures.append(
                    (key, "%s: %s" % (type(exc).__name__, exc)))
                continue
            getattr(report, bucket).append(key)
    return report
