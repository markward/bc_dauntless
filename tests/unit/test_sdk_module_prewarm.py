"""SDK modules the engine imports lazily in combat are imported at boot.

The SDK loader parses, transforms and compiles each script on its first
import in a process (engine/sdk_code_cache.py is in-memory). Only five SDK
missions import Effects themselves; everywhere else the engine's first
`import Effects` -- death_cascade's first debris explosion, or
hull_hit_smoke's first hull hit -- paid it mid-combat: 15.8 ms of a dying
Sovereign's death frame in Debug (perf-register P-4).
"""
import sys

import pytest


def test_boot_prewarm_imports_effects(monkeypatch):
    from engine import host_loop
    monkeypatch.delitem(sys.modules, "Effects", raising=False)
    host_loop._prewarm_sdk_modules()
    assert "Effects" in sys.modules


def test_boot_prewarm_failure_never_propagates(monkeypatch):
    from engine import host_loop
    monkeypatch.setattr(host_loop, "_PREWARM_SDK_MODULES", ("NoSuchSdkModule",))
    host_loop._prewarm_sdk_modules()   # must not raise
