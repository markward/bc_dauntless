"""Observability for the engine's silent-stub layer.

The core ``_Stub`` (``engine/core/ids.py``) is returned by
``TGObject.__getattr__`` for any unimplemented engine method, so an absent
capability is indistinguishable from a working no-op. This module *observes*
that layer without changing its behavior: when enabled it records which stub
attributes are accessed (the implementation roadmap) and where stubs are
truth-tested (the data that decides whether flipping ``_Stub.__bool__`` is
safe), then dumps a ranked report at exit.

Constraints (see docs/superpowers/plans/2026-07-10-stub-observability.md):
- OFF by default. When disabled every hook is one bool read + return, so the
  production path is byte-identical.
- Stdlib only, so engine/core/ids.py can import it with no cycle.
- Never raises into the game: every hook is wrapped.
- Reports via print(), not logging (the embedded host installs no handler).
"""

from __future__ import annotations

import atexit
import os
import sys
from collections import Counter


def _env_truthy(value: str) -> bool:
    return value not in ("", "0", "false", "False")


ENABLED: bool = _env_truthy(os.environ.get("DAUNTLESS_STUB_TELEMETRY", ""))

_attr_hits: "Counter" = Counter()   # (owner_type, attr_name) -> count
_bool_sites: "Counter" = Counter()  # "file:lineno" -> count
_atexit_registered = False


def set_enabled(value: bool) -> None:
    global ENABLED
    ENABLED = bool(value)
    if ENABLED:
        _ensure_atexit()


def _ensure_atexit() -> None:
    global _atexit_registered
    if not _atexit_registered:
        try:
            atexit.register(_atexit_dump)
            _atexit_registered = True
        except Exception:
            pass


def _atexit_dump() -> None:
    if _attr_hits or _bool_sites:
        try:
            dump_report()
        except Exception:
            pass


def _caller(depth: int) -> str:
    try:
        frame = sys._getframe(depth)
        return "%s:%d" % (frame.f_code.co_filename, frame.f_lineno)
    except Exception:
        return "<unknown>"


def record_attr(owner_type: str, attr_name: str) -> None:
    if not ENABLED:
        return
    try:
        _attr_hits[(owner_type, attr_name)] += 1
    except Exception:
        pass


def record_bool(owner_type: str) -> None:
    if not ENABLED:
        return
    try:
        # depth 3: _caller -> record_bool -> __bool__ -> the truth-test site
        _bool_sites[_caller(3)] += 1
    except Exception:
        pass


def snapshot() -> dict:
    return {
        "attr_hits": dict(_attr_hits),
        "bool_sites": dict(_bool_sites),
    }


def reset() -> None:
    _attr_hits.clear()
    _bool_sites.clear()


def dump_report(stream=None) -> str:
    if stream is None:
        stream = sys.stderr
    lines = ["=== stub telemetry: unimplemented-attribute hits (roadmap) ==="]
    for (owner, attr), count in _attr_hits.most_common():
        lines.append("  %6d  %s.%s" % (count, owner, attr))
    lines.append("=== stub telemetry: boolean-test call sites (truthiness risk) ===")
    for site, count in _bool_sites.most_common():
        lines.append("  %6d  %s" % (count, site))
    report = "\n".join(lines)
    try:
        print(report, file=stream)
    except Exception:
        pass
    return report


if ENABLED:
    _ensure_atexit()
