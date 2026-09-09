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
    """Mod-provided Custom/<subdir>/*.py, folded-key sorted.

    Reads the mod index rather than the filesystem so only enabled mods
    contribute and the overlay's own resolution rules apply.
    """
    prefix = ("custom/%s/" % subdir).lower()
    out = []
    for key, mf in index.files.items():
        if mf.target != "sdk":          # paths-guard: kind label
            continue
        if key.startswith(prefix) and key.endswith(".py"):
            out.append((key, mf))
    out.sort(key=lambda kv: kv[0])
    return out


def load_plugins() -> LoadReport:
    """Execute every enabled mod's Foundation plugin scripts."""
    import runpy

    from engine import mods

    report = LoadReport()
    index = mods.current()

    for subdir, bucket in _SUBDIRS:
        for key, mf in _scripts_in(index, subdir):
            try:
                runpy.run_path(str(mf.abs_path), run_name="__foundation__")
            except Exception as exc:
                # One broken mod must not stop the others registering --
                # the same rule build_index follows for an unreadable mod,
                # and for the same reason: silence is a support nightmare.
                report.failures.append(
                    (key, "%s: %s" % (type(exc).__name__, exc)))
                continue
            getattr(report, bucket).append(key)
    return report
