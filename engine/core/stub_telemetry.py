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
- Never raises into the game: every GAME-REACHABLE hook (record_attr,
  record_bool, _caller) is wrapped. The report/inspection helpers (snapshot,
  reset, dump_report) are not hot-path and are not wrapped.
- Reports via print(), not logging (the embedded host installs no handler).
"""

from __future__ import annotations

import atexit
import json
import os
import sys
import time
from collections import Counter


def _env_truthy(value: str) -> bool:
    return value not in ("", "0", "false", "False")


ENABLED: bool = _env_truthy(os.environ.get("DAUNTLESS_STUB_TELEMETRY", ""))


def _default_sidecar_path() -> str:
    configured = os.environ.get("DAUNTLESS_STUB_TELEMETRY_FILE", "")
    if configured:
        return configured
    # Resolve to absolute at import time — the atexit write runs at shutdown,
    # and GLFW's macOS chdir-hijack can move the CWD after init, so a lazily
    # resolved relative path could land in the wrong directory.
    return os.path.abspath("stub_hits.jsonl")


SIDECAR_PATH: str = _default_sidecar_path()

_attr_hits: "Counter" = Counter()      # (owner_type, attr_name) -> count
_bool_sites: "Counter" = Counter()     # "file:lineno" -> count
_coercion_sites: "Counter" = Counter()  # (kind, "file:lineno") -> count
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
    if _attr_hits or _bool_sites or _coercion_sites:
        try:
            dump_report()
        except Exception:
            pass
        persist_run()


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
    """Record a truth-test of a stub, keyed by CALL SITE only.

    ⚠️ SCOUTED 2026-08-10 — ATTRIBUTION GAP, the single biggest obstacle to
    clearing the truthiness table.

    `owner_type` is accepted and then DISCARDED: only `_caller(3)` is stored.
    So `docs/stub_heatmap.md`'s "Boolean-test call sites" table says *where* a
    stub was truth-tested but never *which* stub — and one line can truth-test
    several different names over a run. Triaging any row therefore means
    opening the file and reasoning about which name on that line is undefined,
    which is slow and error-prone; it is why that table has sat unactioned.

    The fix is small and the data is already in hand: `_Stub` carries BOTH
    `_stub_owner` and `_stub_name` (`engine/core/ids.py:43-45`), and
    `_Stub.__bool__` already passes the owner here. To make the table
    self-describing:

      1. `_Stub.__bool__` -> `record_bool(self._stub_owner, self._stub_name)`
      2. key `_bool_sites` on `(owner, attr, site)` instead of `site`
      3. widen the generator's table in `tools/stub_heatmap.py` (the row
         builder near its `Boolean-test call sites` heading) with owner/attr
         columns

    Keep the site in the key: the same stub truth-tested from two places is two
    distinct bugs with different fixes. Note the counter is keyed data, so old
    `stub_hits.jsonl` records carry the narrow key — the generator must tolerate
    both shapes rather than assuming the wide one.

    See docs/engine/stub-scouting-2026-08-10.md for the rows this blocks.
    """
    if not ENABLED:
        return
    try:
        # depth 3: _caller -> record_bool -> __bool__ -> the truth-test site
        _bool_sites[_caller(3)] += 1
    except Exception:
        pass


def record_coercion(kind: str) -> None:
    """Record a numeric-coercion (``int()``/``float()``/``__index__``) hit.

    This is the int()==0 collapse trap: an undefined constant silently
    coerces to 0 and sails through comparisons/dict lookups instead of
    raising, so it needs its own signal distinct from record_bool's
    truthiness trap.

    ⚠️ SCOUTED 2026-08-10 — WORSE ATTRIBUTION GAP THAN record_bool.
    This does not even *receive* an owner or attr, only `kind`, so the
    "Numeric-coercion call sites" table identifies a coercion site with no clue
    which constant collapsed. That matters more here than for truthiness: the
    known casualties of this trap were all *constants* (`WC_*` keyboard codes,
    `TGUIObject.ALIGN_*`, `EngRepairPane.REPAIR_AREA`), and a site like
    `engine/appc/input.py:123` coerces a different constant on every keypress.

    Fix alongside record_bool: `_Stub.__int__`/`__float__`/`__index__`
    (`engine/core/ids.py`) have `self._stub_owner`/`self._stub_name` in scope —
    pass them through and key on `(kind, owner, attr, site)`.

    See docs/engine/stub-scouting-2026-08-10.md."""
    if not ENABLED:
        return
    try:
        # depth 3: _caller -> record_coercion -> __int__/__float__/__index__
        # -> the coercion site
        _coercion_sites[(kind, _caller(3))] += 1
    except Exception:
        pass


def snapshot() -> dict:
    return {
        "attr_hits": dict(_attr_hits),
        "bool_sites": dict(_bool_sites),
        "coercion_sites": dict(_coercion_sites),
    }


def reset() -> None:
    _attr_hits.clear()
    _bool_sites.clear()
    _coercion_sites.clear()


def dump_report(stream=None) -> str:
    if stream is None:
        stream = sys.stderr
    lines = ["=== stub telemetry: unimplemented-attribute hits (roadmap) ==="]
    for (owner, attr), count in _attr_hits.most_common():
        lines.append("  %6d  %s.%s" % (count, owner, attr))
    lines.append("=== stub telemetry: boolean-test call sites (truthiness risk) ===")
    for site, count in _bool_sites.most_common():
        lines.append("  %6d  %s" % (count, site))
    lines.append("=== stub telemetry: numeric-coercion call sites (int()==0 risk) ===")
    for (kind, site), count in _coercion_sites.most_common():
        lines.append("  %6d  %s  %s" % (count, kind, site))
    report = "\n".join(lines)
    try:
        print(report, file=stream)
    except Exception:
        pass
    return report


def persist_run(path: str | None = None) -> None:
    """Append one JSON line describing this run's counters to the sidecar.

    Never raises — a bad path / full disk / permission error is swallowed so
    persistence can never crash the game. The (owner, attr) pair is encoded as
    a tab-separated key so a dotted breadcrumb attr stays unambiguous."""
    if path is None:
        path = SIDECAR_PATH
    try:
        record = {
            "t": time.time(),
            "attr_hits": {
                ("%s\t%s" % (owner, attr)): count
                for (owner, attr), count in _attr_hits.items()
            },
            "bool_sites": dict(_bool_sites),
            "coercion_sites": {
                ("%s\t%s" % (kind, site)): count
                for (kind, site), count in _coercion_sites.items()
            },
        }
        line = json.dumps(record)
        with open(path, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


if ENABLED:
    _ensure_atexit()
